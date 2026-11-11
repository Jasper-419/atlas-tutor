"""Private assessment metadata and durable, attributable learning evidence."""

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)

from backend.database import Base
from backend.models.domain import Owned, now


class PracticeBatch(Owned, Base):
    __tablename__ = "atlas_practice_batches"
    node_id = Column(
        String(40),
        ForeignKey("atlas_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    request_key = Column(String(120), nullable=False)
    request_spec = Column(JSON, nullable=False)
    exercise_ids = Column(JSON, nullable=False, default=list)
    # Private model-assisted receipt; historical batches retain an empty receipt.
    validation = Column(JSON, nullable=False, default=dict, server_default="{}")
    __table_args__ = (UniqueConstraint("user_id", "node_id", "request_key"),)


class ExerciseMetadata(Owned, Base):
    __tablename__ = "atlas_exercise_metadata"
    exercise_id = Column(
        String(40),
        ForeignKey("atlas_exercises.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    skill_type = Column(String(30), nullable=False, default="concept")
    difficulty = Column(String(30), nullable=False, default="beginner")
    focus = Column(Text, nullable=False, default="")
    # Structured criteria stay private until submission; public rubric is separately projected.
    criteria = Column(JSON, nullable=False, default=list)


class LearningEvidence(Owned, Base):
    __tablename__ = "atlas_learning_evidence"
    attempt_id = Column(
        String(40),
        ForeignKey("atlas_attempts.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    node_id = Column(
        String(40),
        ForeignKey("atlas_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    exercise_id = Column(
        String(40),
        ForeignKey("atlas_exercises.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    skill_type = Column(String(30), nullable=False)
    difficulty = Column(String(30), nullable=False)
    score = Column(Float, nullable=False)
    independent = Column(Boolean, nullable=False)
    misconception = Column(Text, nullable=False, default="")
    criteria_scores = Column(JSON, nullable=False, default=list)


class NodeLearningState(Owned, Base):
    __tablename__ = "atlas_node_learning_states"
    node_id = Column(
        String(40),
        ForeignKey("atlas_nodes.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    baseline_mastery = Column(Float, nullable=False, default=0)
    strategy = Column(String(30), nullable=False, default="concept")
    updated_at = Column(String(40), nullable=False, default=now, onupdate=now)
