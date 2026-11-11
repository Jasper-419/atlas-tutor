"""Immutable evidence snapshots; current source rows point to their version."""

from sqlalchemy import JSON, Column, ForeignKey, Integer, String, Text, UniqueConstraint

from backend.database import Base
from backend.models.domain import Owned


class SourceRevision(Owned, Base):
    __tablename__ = "atlas_source_revisions"
    source_id = Column(
        String(40),
        ForeignKey("atlas_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version = Column(Integer, nullable=False)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False)
    url = Column(Text, nullable=True)
    kind = Column(String(30), nullable=False)
    pages = Column(JSON, nullable=False, default=list)
    file_path = Column(Text, nullable=True)
    filename = Column(String(255), nullable=True)
    page_index = Column(JSON(none_as_null=True), nullable=True)
    __table_args__ = (UniqueConstraint("source_id", "version"),)


class IndexBatch(Base):
    """Unpublished vectors owned by a durable task."""

    __tablename__ = "atlas_index_batches"
    task_id = Column(String(40), ForeignKey("atlas_tasks.id", ondelete="CASCADE"), primary_key=True)
    offset = Column(Integer, primary_key=True)
    source_id = Column(String(40), ForeignKey("atlas_sources.id", ondelete="CASCADE"), index=True)
    fingerprint = Column(String(64), nullable=False)
    vectors = Column(JSON, nullable=False)
