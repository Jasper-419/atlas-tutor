"""Track processed learning records and user memory exclusions."""

from alembic import op
import sqlalchemy as sa

revision = "20261111_0010"
down_revision = "20261111_0009"
branch_labels = None
depends_on = None


def _owned_columns():
    return (
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("atlas_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )


def upgrade():
    op.create_table(
        "atlas_memory_record_cursors", *_owned_columns(),
        sa.Column("course_id", sa.String(40), sa.ForeignKey("atlas_courses.id", ondelete="CASCADE")),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("source_id", sa.String(40), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("next_offset", sa.Integer(), nullable=False),
        sa.Column("done", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("user_id", "kind", "source_id"),
    )
    op.create_table(
        "atlas_memory_organize_runs", *_owned_columns(),
        sa.Column("course_id", sa.String(40), sa.ForeignKey("atlas_courses.id", ondelete="CASCADE")),
        sa.Column("request_key", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("user_id", "request_key"),
    )
    op.create_table(
        "atlas_memory_suppressions", *_owned_columns(),
        sa.Column("course_id", sa.String(40), sa.ForeignKey("atlas_courses.id", ondelete="CASCADE")),
        sa.Column("scope_key", sa.String(48), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("user_id", "scope_key", "content_hash"),
    )
    for table in ("atlas_memory_record_cursors", "atlas_memory_organize_runs", "atlas_memory_suppressions"):
        op.create_index("ix_" + table + "_user_id", table, ["user_id"])
        op.create_index("ix_" + table + "_course_id", table, ["course_id"])


def downgrade():
    for table in ("atlas_memory_suppressions", "atlas_memory_organize_runs", "atlas_memory_record_cursors"):
        op.drop_table(table)
