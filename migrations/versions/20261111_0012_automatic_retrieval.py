"""Default untouched course libraries to automatic retrieval."""

from alembic import op
import sqlalchemy as sa

revision = "20261111_0012"
down_revision = "20261111_0011"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("atlas_source_revisions", sa.Column("page_index", sa.JSON(), nullable=True))
    courses = sa.table(
        "atlas_courses", sa.column("knowledge_engine", sa.String()),
        sa.column("knowledge_index", sa.JSON()),
    )
    op.execute(courses.update().where(
        courses.c.knowledge_engine == "atlas",
        courses.c.knowledge_index["generation"].as_string().is_(None),
    ).values(knowledge_engine="auto"))


def downgrade():
    op.execute("UPDATE atlas_courses SET knowledge_engine = 'atlas' WHERE knowledge_engine = 'auto'")
    op.drop_column("atlas_source_revisions", "page_index")
