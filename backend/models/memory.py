"""Provenance around unchanged L2 Memory rows; revisions are append-only."""
from sqlalchemy import JSON, Column, ForeignKey, Integer, String, Text, UniqueConstraint
from backend.database import Base
from backend.models.domain import Owned, now


class MemoryMetadata(Base):
    __tablename__ = "atlas_memory_metadata"
    memory_id = Column(String(40), ForeignKey("atlas_memories.id", ondelete="CASCADE"), primary_key=True)
    current_revision = Column(Integer, nullable=False, default=1)
    status = Column(String(30), nullable=False, default="active")
    origin = Column(String(30), nullable=False)
    facet = Column(String(100), nullable=True)


class MemoryRevision(Owned, Base):
    __tablename__ = "atlas_memory_revisions"
    memory_id = Column(String(40), ForeignKey("atlas_memories.id", ondelete="CASCADE"), nullable=False, index=True)
    revision = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    category = Column(String(60), nullable=False)
    status = Column(String(30), nullable=False)
    origin = Column(String(30), nullable=False)
    facet = Column(String(100), nullable=True)
    evidence = Column(JSON, nullable=False, default=list)
    request_key = Column(String(120), nullable=True)
    __table_args__ = (UniqueConstraint("memory_id", "revision"), UniqueConstraint("user_id", "request_key"))


class MemoryProfile(Owned, Base):
    __tablename__ = "atlas_memory_profiles"
    course_id = Column(String(40), ForeignKey("atlas_courses.id", ondelete="CASCADE"), nullable=True, index=True)
    request_key = Column(String(120), nullable=True)
    status = Column(String(30), nullable=False, default="pending")
    fingerprint = Column(String(64), nullable=False)
    facts = Column(JSON, nullable=False, default=list)
    groups = Column(JSON, nullable=False, default=list)
    method = Column(String(30), nullable=False, default="extractive")
    updated_at = Column(String(40), nullable=False, default=now)
    __table_args__ = (UniqueConstraint("user_id", "request_key"),)


class MemoryWriteReceipt(Owned, Base):
    __tablename__ = "atlas_memory_write_receipts"
    memory_id = Column(String(40), ForeignKey("atlas_memories.id", ondelete="CASCADE"), nullable=False, index=True)
    request_key = Column(String(120), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    __table_args__ = (UniqueConstraint("user_id", "request_key"),)
