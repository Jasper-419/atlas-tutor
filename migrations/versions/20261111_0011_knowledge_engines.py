"""Add a retrieval engine and published index to each course library."""

from alembic import op
import sqlalchemy as sa

revision = "20261111_0011"
down_revision = "20261111_0010"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("atlas_courses", sa.Column(
        "knowledge_engine", sa.String(24), nullable=False, server_default="atlas",
    ))
    op.add_column("atlas_courses", sa.Column(
        "knowledge_index", sa.JSON(), nullable=False, server_default="{}",
    ))


def downgrade():
    op.drop_column("atlas_courses", "knowledge_index")
    op.drop_column("atlas_courses", "knowledge_engine")
