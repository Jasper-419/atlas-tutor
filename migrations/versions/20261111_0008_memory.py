"""Add memory provenance without rewriting any historical Memory row."""
from alembic import op
import sqlalchemy as sa

revision = "20261111_0008"
down_revision = "20261110_0007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("atlas_memory_metadata",
        sa.Column("memory_id", sa.String(40), sa.ForeignKey("atlas_memories.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("origin", sa.String(30), nullable=False),
        sa.Column("facet", sa.String(100), nullable=True))
    op.create_table("atlas_memory_revisions",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("atlas_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("memory_id", sa.String(40), sa.ForeignKey("atlas_memories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("category", sa.String(60), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("origin", sa.String(30), nullable=False),
        sa.Column("facet", sa.String(100), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("request_key", sa.String(120), nullable=True),
        sa.UniqueConstraint("memory_id", "revision"),
        sa.UniqueConstraint("user_id", "request_key"))
    op.create_index("ix_atlas_memory_revisions_user_id", "atlas_memory_revisions", ["user_id"])
    op.create_index("ix_atlas_memory_revisions_memory_id", "atlas_memory_revisions", ["memory_id"])
    op.create_table("atlas_memory_profiles",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("atlas_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("course_id", sa.String(40), sa.ForeignKey("atlas_courses.id", ondelete="CASCADE"), nullable=True),
        sa.Column("request_key", sa.String(120), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("facts", sa.JSON(), nullable=False),
        sa.Column("groups", sa.JSON(), nullable=False),
        sa.Column("method", sa.String(30), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("user_id", "request_key"))
    op.create_index("ix_atlas_memory_profiles_user_id", "atlas_memory_profiles", ["user_id"])
    op.create_index("ix_atlas_memory_profiles_course_id", "atlas_memory_profiles", ["course_id"])

    op.create_table("atlas_memory_write_receipts",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("atlas_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("memory_id", sa.String(40), sa.ForeignKey("atlas_memories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("request_key", sa.String(120), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.UniqueConstraint("user_id", "request_key"))
    op.create_index("ix_atlas_memory_write_receipts_user_id", "atlas_memory_write_receipts", ["user_id"])
    op.create_index("ix_atlas_memory_write_receipts_memory_id", "atlas_memory_write_receipts", ["memory_id"])


def downgrade():
    op.drop_table("atlas_memory_write_receipts")
    op.drop_table("atlas_memory_profiles")
    op.drop_table("atlas_memory_revisions")
    op.drop_table("atlas_memory_metadata")
