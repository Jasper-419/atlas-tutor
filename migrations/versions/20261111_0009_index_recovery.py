"""Bind published source vectors and retain unpublished task batches."""

from alembic import op
import sqlalchemy as sa

revision = "20261111_0009"
down_revision = "20261111_0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("atlas_sources", sa.Column("embedding_signature", sa.String(64), nullable=True))
    op.add_column("atlas_sources", sa.Column("embedding_dimension", sa.Integer(), nullable=True))
    op.create_table(
        "atlas_index_batches",
        sa.Column("task_id", sa.String(40), sa.ForeignKey("atlas_tasks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("offset", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.String(40), sa.ForeignKey("atlas_sources.id", ondelete="CASCADE"), nullable=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("vectors", sa.JSON(), nullable=False),
    )
    op.create_index("ix_atlas_index_batches_source_id", "atlas_index_batches", ["source_id"])


def downgrade():
    op.drop_table("atlas_index_batches")
    op.drop_column("atlas_sources", "embedding_dimension")
    op.drop_column("atlas_sources", "embedding_signature")
