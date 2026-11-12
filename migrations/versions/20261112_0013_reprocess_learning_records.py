"""Let previously scanned conversations and notes use the new extractor."""

from alembic import op
import sqlalchemy as sa

revision = "20261112_0013"
down_revision = "20261111_0012"
branch_labels = None
depends_on = None


def upgrade():
    cursors = sa.table(
        "atlas_memory_record_cursors", sa.column("user_id", sa.Integer()),
        sa.column("course_id", sa.String()), sa.column("kind", sa.String()),
        sa.column("done", sa.Boolean()), sa.column("next_offset", sa.Integer()),
    )
    exclusions = sa.table(
        "atlas_memory_suppressions", sa.column("user_id", sa.Integer()),
        sa.column("course_id", sa.String()),
    )
    # Older exclusions may identify the excerpt but not its original source.
    # Avoid reopening an excluded scope where new excerpt boundaries could
    # otherwise restore something the learner asked to remove.
    excluded_scope = sa.exists().where(
        exclusions.c.user_id == cursors.c.user_id,
        sa.or_(
            exclusions.c.course_id == cursors.c.course_id,
            sa.and_(exclusions.c.course_id.is_(None), cursors.c.course_id.is_(None)),
        ),
    )
    op.execute(cursors.update().where(
        cursors.c.kind.in_(("chat", "reply", "note")),
        ~excluded_scope,
    ).values(done=False, next_offset=0))


def downgrade():
    # Rescanning is incremental, source-verified and deduplicated.
    pass
