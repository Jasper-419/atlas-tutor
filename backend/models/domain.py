from datetime import UTC, datetime
from uuid import uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    text,
)

from backend.database import Base


def uid():
    return str(uuid4())


def now():
    return datetime.now(UTC).isoformat()


class User(Base):
    __tablename__ = "atlas_users"
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    full_name = Column(String(150), nullable=False, default="")
    hashed_password = Column(String(255), nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    preferences = Column(JSON, default=dict, nullable=False)
    created_at = Column(String(40), default=now, nullable=False)
    updated_at = Column(String(40), default=now, onupdate=now, nullable=False)


class Session(Base):
    __tablename__ = "atlas_sessions"
    token_hash = Column(String(64), primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("atlas_users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    expires_at = Column(String(40), nullable=False)


class Owned:
    id = Column(String(40), primary_key=True, default=uid)
    user_id = Column(
        Integer,
        ForeignKey("atlas_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(String(40), default=now, nullable=False)


class LLMConnection(Owned, Base):
    __tablename__ = "atlas_llm_connections"
    name = Column(String(100), nullable=False)
    base_url = Column(String(2000), nullable=False)
    protocol = Column(String(40), nullable=False)
    models = Column(JSON, nullable=False)
    model = Column(String(200), nullable=False)
    updated_at = Column(String(40), default=now, onupdate=now, nullable=False)


class LLMCredential(Base):
    __tablename__ = "atlas_llm_credentials"
    connection_id = Column(
        String(40),
        ForeignKey("atlas_llm_connections.id", ondelete="CASCADE"),
        primary_key=True,
    )
    encrypted_key = Column(Text, nullable=False)


class LLMSelection(Base):
    __tablename__ = "atlas_llm_selections"
    user_id = Column(
        Integer,
        ForeignKey("atlas_users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    connection_id = Column(
        String(40),
        ForeignKey("atlas_llm_connections.id", ondelete="SET NULL"),
        nullable=True,
    )


class Course(Owned, Base):
    __tablename__ = "atlas_courses"
    title = Column(String(255), nullable=False)
    goal = Column(Text, nullable=False)
    background = Column(Text, default="")
    minutes_per_day = Column(Integer, default=30)
    deadline = Column(String(40), nullable=True)
    level = Column(String(100), default="beginner")
    status = Column(String(20), default="planning", nullable=False)
    task_id = Column(String(40), nullable=True)
    plan_version = Column(Integer, default=0)
    updated_at = Column(String(40), default=now, onupdate=now, nullable=False)


class Node(Owned, Base):
    __tablename__ = "atlas_nodes"
    course_id = Column(
        String(40),
        ForeignKey("atlas_courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title = Column(String(255), nullable=False)
    summary = Column(Text, default="")
    objective = Column(Text, default="")
    content = Column(Text, nullable=True)
    lesson_citations = Column(JSON, default=list)
    lesson_stale = Column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    lesson_source_versions = Column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    estimated_minutes = Column(Integer, default=20)
    difficulty = Column(String(30), default="beginner")
    position = Column(Integer, default=0)
    status = Column(String(20), default="locked")
    mastery = Column(Float, default=0)
    prerequisites = Column(JSON, default=list)
    retired = Column(Boolean, default=False, nullable=False)


class PlanVersion(Owned, Base):
    __tablename__ = "atlas_plan_versions"
    course_id = Column(
        String(40),
        ForeignKey("atlas_courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version = Column(Integer, nullable=False)
    reason = Column(Text, default="Initial plan")
    snapshot = Column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("course_id", "version"),)


class Source(Owned, Base):
    __tablename__ = "atlas_sources"
    course_id = Column(
        String(40),
        ForeignKey("atlas_courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title = Column(String(255), nullable=False)
    url = Column(Text, nullable=True)
    kind = Column(String(30), default="text")
    chunk_count = Column(Integer, default=0)
    version = Column(Integer, nullable=False, default=1, server_default="1")
    content_hash = Column(String(64), nullable=False, default="", server_default="")
    embedding_signature = Column(String(64), nullable=True)
    embedding_dimension = Column(Integer, nullable=True)


class Chunk(Owned, Base):
    __tablename__ = "atlas_chunks"
    source_id = Column(
        String(40),
        ForeignKey("atlas_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    course_id = Column(
        String(40),
        ForeignKey("atlas_courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    page_start = Column(Integer, nullable=True)
    page_end = Column(Integer, nullable=True)
    section = Column(String(300), nullable=True)
    embedding = Column(JSON().with_variant(Vector(), "postgresql"), nullable=True)


class Message(Owned, Base):
    __tablename__ = "atlas_messages"
    node_id = Column(
        String(40),
        ForeignKey("atlas_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    citations = Column(JSON, default=list)
    request_id = Column(String(120), nullable=True)
    __table_args__ = (UniqueConstraint("user_id", "node_id", "role", "request_id"),)


class Exercise(Owned, Base):
    __tablename__ = "atlas_exercises"
    node_id = Column(
        String(40),
        ForeignKey("atlas_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type = Column(String(20), nullable=False)
    prompt = Column(Text, nullable=False)
    options = Column(JSON, default=list)
    rubric = Column(Text, default="")
    correct_answer = Column(Text, nullable=False)
    explanation = Column(Text, default="")
    revision = Column(Integer, nullable=False, default=1, server_default="1")
    voided = Column(Boolean, nullable=False, default=False, server_default=false())


class Attempt(Owned, Base):
    __tablename__ = "atlas_attempts"
    exercise_id = Column(
        String(40),
        ForeignKey("atlas_exercises.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node_id = Column(
        String(40),
        ForeignKey("atlas_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    request_id = Column(String(120), nullable=False)
    answer = Column(Text, nullable=False)
    score = Column(Float, nullable=False)
    feedback = Column(Text, nullable=False)
    correct_answer = Column(Text, nullable=False)
    mastery = Column(Float, nullable=False)
    passed = Column(Boolean, nullable=False)
    next_node_id = Column(String(40), nullable=True)
    voided = Column(Boolean, nullable=False, default=False, server_default=false())
    __table_args__ = (UniqueConstraint("user_id", "exercise_id", "request_id"),)


class Review(Owned, Base):
    __tablename__ = "atlas_reviews"
    node_id = Column(
        String(40),
        ForeignKey("atlas_nodes.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    due_at = Column(String(40), nullable=False)
    interval_days = Column(Integer, default=1)
    repetitions = Column(Integer, default=0)
    ease = Column(Float, default=2.5)


class Memory(Owned, Base):
    __tablename__ = "atlas_memories"
    course_id = Column(
        String(40),
        ForeignKey("atlas_courses.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    category = Column(String(60), default="note")
    content = Column(Text, nullable=False)
    updated_at = Column(String(40), default=now, onupdate=now, nullable=False)


class Task(Owned, Base):
    __tablename__ = "atlas_tasks"
    course_id = Column(
        String(40),
        ForeignKey("atlas_courses.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    kind = Column(String(30), nullable=False)
    status = Column(String(20), default="queued", nullable=False, index=True)
    progress = Column(Integer, default=0)
    message = Column(Text, default="等待执行")
    error = Column(Text, nullable=True)
    result = Column(JSON, nullable=True)
    payload = Column(JSON, default=dict)
    run_id = Column(String(40), default=uid, nullable=False)
    lease_until = Column(String(40), nullable=True)
    worker_token = Column(String(40), nullable=True)
    attempts = Column(Integer, default=0)
    updated_at = Column(String(40), default=now, onupdate=now, nullable=False)


class Trace(Owned, Base):
    __tablename__ = "atlas_traces"
    task_id = Column(
        String(40),
        ForeignKey("atlas_tasks.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    step = Column(String(80), nullable=False)
    status = Column(String(20), default="succeeded")
    detail = Column(Text, default="")
    duration_ms = Column(Integer, nullable=True)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    model = Column(String(120), nullable=True)


class Activity(Owned, Base):
    __tablename__ = "atlas_activities"
    title = Column(String(255), nullable=False)
    detail = Column(Text, default="")
    minutes = Column(Integer, default=0)
