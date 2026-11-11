"""Node-scoped teaching navigation and attributable misconception reviews."""

from sqlalchemy import JSON, Column, ForeignKey, Integer, String, Text, UniqueConstraint

from backend.database import Base
from backend.models.domain import Owned, now


class NodeTeachingState(Owned, Base):
    __tablename__ = "atlas_node_teaching_states"
    node_id = Column(String(40), ForeignKey("atlas_nodes.id", ondelete="CASCADE"),
                     nullable=False, unique=True, index=True)
    phase = Column(String(30), nullable=False, default="explain")
    last_strategy = Column(String(500), nullable=False, default="")
    last_exercise_ids = Column(JSON, nullable=False, default=list)
    deferred_until = Column(String(40), nullable=True)
    defer_reason = Column(Text, nullable=False, default="")
    updated_at = Column(String(40), nullable=False, default=now, onupdate=now)


class TeachingFeedback(Owned, Base):
    __tablename__ = "atlas_teaching_feedback"
    node_id = Column(String(40), ForeignKey("atlas_nodes.id", ondelete="CASCADE"),
                     nullable=False, index=True)
    request_key = Column(String(120), nullable=False)
    content = Column(Text, nullable=False)
    effect = Column(String(20), nullable=False)
    strategy = Column(String(500), nullable=False, default="")
    __table_args__ = (UniqueConstraint("user_id", "node_id", "request_key"),)


class MisconceptionReview(Owned, Base):
    __tablename__ = "atlas_misconception_reviews"
    node_id = Column(String(40), ForeignKey("atlas_nodes.id", ondelete="CASCADE"),
                     nullable=False, index=True)
    origin_exercise_id = Column(String(40), ForeignKey("atlas_exercises.id", ondelete="CASCADE"),
                               nullable=False, index=True)
    origin_attempt_id = Column(String(40), ForeignKey("atlas_attempts.id", ondelete="CASCADE"),
                              nullable=False, unique=True, index=True)
    description = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="open", index=True)
    due_at = Column(String(40), nullable=False, default=now, index=True)
    interval_days = Column(Integer, nullable=False, default=1)
    resolved_attempt_id = Column(String(40), ForeignKey("atlas_attempts.id", ondelete="SET NULL"),
                                nullable=True)
    resolved_at = Column(String(40), nullable=True)
    updated_at = Column(String(40), nullable=False, default=now, onupdate=now)


class PracticeTarget(Owned, Base):
    __tablename__ = "atlas_practice_targets"
    exercise_id = Column(String(40), ForeignKey("atlas_exercises.id", ondelete="CASCADE"),
                         nullable=False, index=True)
    misconception_id = Column(String(40), ForeignKey("atlas_misconception_reviews.id", ondelete="CASCADE"),
                              nullable=False, index=True)
    __table_args__ = (UniqueConstraint("exercise_id", "misconception_id"),)
