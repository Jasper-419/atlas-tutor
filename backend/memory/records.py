"""Bounded incremental reads from the original learning records."""

from dataclasses import dataclass

from sqlalchemy import String, and_, case, cast, literal, or_, select

from backend.memory.service import _assessment_fingerprint, _hash
from backend.models.domain import Attempt, Course, Exercise, Node
from backend.models.learning import LearningEvidence
from backend.models.memory import MemoryRecordCursor
from backend.models.notebook import NotebookNote
from backend.models.tutor import TutorEvent, TutorSession, TutorTurn

PASSAGE_SIZE = 1600
PER_KIND = 3


@dataclass(frozen=True)
class Record:
    kind: str
    id: str
    version: int
    course_id: str | None
    text: str
    offset: int
    next_offset: int
    done: bool
    ref: dict
    topic: str = ""


def _queries(db, user_id):
    turns = (
        db.query(TutorTurn, TutorSession)
        .join(TutorSession, TutorSession.id == TutorTurn.session_id)
        .filter(TutorTurn.user_id == user_id, TutorSession.user_id == user_id,
                TutorTurn.status == "completed")
    )
    chats = turns.filter(TutorTurn.checkpoint["grade_input"].as_string().is_(None))
    replies = (
        turns.add_entity(TutorEvent).join(TutorEvent, TutorEvent.turn_id == TutorTurn.id)
        .filter(TutorEvent.type == "user_response", TutorEvent.payload["origin"].as_string() == "user_input")
    )
    notes = db.query(NotebookNote).filter(NotebookNote.user_id == user_id)
    practice = (
        db.query(Attempt, Exercise, LearningEvidence, Node)
        .join(Exercise, and_(Exercise.id == Attempt.exercise_id, Exercise.node_id == Attempt.node_id))
        .outerjoin(LearningEvidence, and_(LearningEvidence.attempt_id == Attempt.id,
                                         LearningEvidence.exercise_id == Exercise.id,
                                         LearningEvidence.node_id == Attempt.node_id,
                                         LearningEvidence.user_id == user_id))
        .join(Node, Node.id == Attempt.node_id)
        .filter(Attempt.user_id == user_id, Exercise.user_id == user_id,
                Node.user_id == user_id,
                Attempt.voided.is_(False), Exercise.voided.is_(False))
    )
    # A legacy grade can gain a learning-evidence row without changing the exercise.
    practice_version = case((LearningEvidence.id.is_(None), -Exercise.revision), else_=Exercise.revision)
    return (
        ("chat", chats, TutorTurn.id, literal(1), TutorSession.course_id, TutorTurn.created_at),
        ("reply", replies, cast(TutorEvent.id, String), literal(1), TutorSession.course_id, TutorEvent.created_at),
        ("note", notes, NotebookNote.id, NotebookNote.version, NotebookNote.course_id, NotebookNote.updated_at),
        ("practice", practice, Attempt.id, practice_version, Node.course_id, Attempt.created_at),
    )


def _record(kind, row):
    cursor = row[-1]
    offset = cursor.next_offset if cursor else 0
    topic = ""
    if kind in {"chat", "reply"}:
        turn, session = row[:2]
        event = row[2] if kind == "reply" else None
        identifier, version, course_id = str(event.id) if event else turn.id, 1, session.course_id
        text = event.payload.get("content") if event else turn.input
        text = text if isinstance(text, str) else ""
        ref = {
            "kind": "turn", "turn_id": turn.id, "session_id": session.id,
            "field": "event" if event else "input", "seq": event.seq if event else 0,
            "recorded_at": event.created_at if event else turn.created_at,
            "source_course_id": course_id, "source_hash": _hash(text),
        }
        if event:
            ref["event_origin"] = "user_input"
    elif kind == "note":
        note = row[0]
        identifier, version, course_id, text = note.id, note.version, note.course_id, note.content
        ref = {
            "kind": "note", "note_id": identifier, "note_version": version, "recorded_at": note.updated_at,
            "source_course_id": course_id, "source_hash": _hash(text),
        }
    else:
        attempt, exercise, evidence, node = row[:4]
        identifier, course_id, text = attempt.id, node.course_id, attempt.answer
        version = exercise.revision if evidence else -exercise.revision
        topic = node.title[:100]
        ref = {
            "kind": "assessment", "attempt_id": identifier, "exercise_id": exercise.id,
            "exercise_revision": exercise.revision, "score": float(attempt.score),
            "grade_only": evidence is None, "recorded_at": attempt.created_at,
            "topic": topic, "passed": attempt.passed,
            "source_hash": _assessment_fingerprint(attempt, exercise, evidence),
        }
    if kind == "practice":
        passage, end = text[:600].strip(), len(text)
    else:
        end = min(len(text), offset + PASSAGE_SIZE)
        if end < len(text):
            boundary = text.rfind("\n", offset + PASSAGE_SIZE // 2, end)
            if boundary >= 0:
                end = boundary + 1
        passage = text[offset:end].strip()
    return Record(kind, identifier, version, course_id, passage, offset, end, end >= len(text), ref, topic)


def collect_records(db, user_id, course_id=None, *, first_only=False):
    owned_courses = select(Course.id).where(Course.user_id == user_id)
    records = []
    for kind, query, identifier, version, scope, timestamp in _queries(db, user_id):
        query = query.filter(scope == course_id) if course_id is not None else query.filter(
            or_(scope.is_(None), scope.in_(owned_courses)),
        )
        cursor = MemoryRecordCursor
        query = query.outerjoin(cursor, and_(
            cursor.user_id == user_id, cursor.kind == kind,
            cursor.source_id == identifier, cursor.source_version == version,
        )).filter(or_(cursor.id.is_(None), cursor.done.is_(False)))
        if first_only:
            if query.with_entities(identifier).first():
                return True
        else:
            rows = query.add_entity(cursor).order_by(timestamp, identifier).limit(PER_KIND).all()
            records.extend(_record(kind, row) for row in rows)
    return False if first_only else records
