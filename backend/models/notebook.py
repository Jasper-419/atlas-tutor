"""Owned Markdown notes and durable question-repair previews/audit receipts."""

from sqlalchemy import JSON, Column, ForeignKey, Integer, String, Text, UniqueConstraint

from backend.database import Base
from backend.models.domain import Owned, now


class NotebookNote(Owned, Base):
    __tablename__ = "atlas_notebook_notes"
    course_id = Column(String(40), ForeignKey("atlas_courses.id", ondelete="CASCADE"), index=True)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    sources = Column(JSON, nullable=False, default=list)
    origin_turn_id = Column(String(40), ForeignKey("atlas_tutor_turns.id", ondelete="SET NULL"), index=True)
    request_id = Column(String(120), nullable=True)
    request_fingerprint = Column(String(64), nullable=True)
    updated_at = Column(String(40), nullable=False, default=now, onupdate=now)
    __table_args__ = (UniqueConstraint("user_id", "request_id"),)


class ExerciseCorrection(Owned, Base):
    __tablename__ = "atlas_exercise_corrections"
    exercise_id = Column(String(40), ForeignKey("atlas_exercises.id", ondelete="CASCADE"), nullable=False, index=True)
    node_id = Column(String(40), ForeignKey("atlas_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    action_id = Column(String(120), nullable=False)
    status = Column(String(20), nullable=False, default="proposed")
    mode = Column(String(20), nullable=False)
    reason = Column(Text, nullable=False)
    proposal = Column(JSON, nullable=False, default=dict)
    before_snapshot = Column(JSON, nullable=False, default=dict)
    after_snapshot = Column(JSON, nullable=False, default=dict)
    result = Column(JSON, nullable=False, default=dict)
    __table_args__ = (UniqueConstraint("user_id", "action_id"),)


# A correction becomes its audit record atomically when confirmed.
CorrectionAudit = ExerciseCorrection
