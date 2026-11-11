"""Durable conversations, model/tool checkpoints and replayable user events."""

from sqlalchemy import JSON, Column, ForeignKey, Integer, String, Text, UniqueConstraint

from backend.database import Base
from backend.models.domain import Owned, now


class TutorSession(Owned, Base):
    __tablename__ = "atlas_tutor_sessions"
    title = Column(String(255), nullable=False, default="新对话")
    course_id = Column(
        String(40),
        ForeignKey("atlas_courses.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    node_id = Column(
        String(40),
        ForeignKey("atlas_nodes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    mode = Column(String(20), nullable=False, default="study")
    summary = Column(Text, nullable=False, default="")
    updated_at = Column(String(40), nullable=False, default=now, onupdate=now)


class TutorTurn(Owned, Base):
    __tablename__ = "atlas_tutor_turns"
    session_id = Column(
        String(40),
        ForeignKey("atlas_tutor_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    request_id = Column(String(120), nullable=False)
    status = Column(String(30), nullable=False, default="queued", index=True)
    input = Column(Text, nullable=False)
    output = Column(Text, nullable=False, default="")
    error = Column(Text, nullable=True)
    checkpoint = Column(JSON, nullable=False, default=dict)
    pending_action = Column(JSON, nullable=True)
    last_seq = Column(Integer, nullable=False, default=0)
    lease_until = Column(String(40), nullable=True)
    worker_token = Column(String(40), nullable=True)
    updated_at = Column(String(40), nullable=False, default=now, onupdate=now)
    __table_args__ = (UniqueConstraint("session_id", "request_id"),)


class TutorEvent(Base):
    __tablename__ = "atlas_tutor_events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    turn_id = Column(
        String(40),
        ForeignKey("atlas_tutor_turns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seq = Column(Integer, nullable=False)
    type = Column(String(40), nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(String(40), nullable=False, default=now)
    __table_args__ = (UniqueConstraint("turn_id", "seq"),)
