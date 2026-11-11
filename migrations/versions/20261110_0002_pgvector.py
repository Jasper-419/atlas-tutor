"""Native dimension-flexible pgvector storage on PostgreSQL; SQLite remains JSON.

Revision ID: 20261110_0002
Revises: 20261110_0001
"""

from alembic import op, context
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = "20261110_0002"
down_revision = "20261110_0001"
branch_labels = None
depends_on = None


def upgrade():
    # Preserve compatibility with an Atlas API started while the initial local schema was being authored.
    if not context.is_offline_mode():
        inspector = sa.inspect(op.get_bind())
        if "worker_token" not in {
            column["name"] for column in inspector.get_columns("atlas_tasks")
        }:
            op.add_column(
                "atlas_tasks", sa.Column("worker_token", sa.String(40), nullable=True)
            )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        # Vector without a hard-coded dimension supports independently configured embedding models.
        # The API rejects mismatched existing/query dimensions before retrieval.
        op.alter_column(
            "atlas_chunks",
            "embedding",
            existing_type=sa.JSON(),
            type_=Vector(),
            existing_nullable=True,
            postgresql_using="CASE WHEN embedding IS NULL OR embedding::text = 'null' THEN NULL ELSE embedding::text::vector END",
        )


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.alter_column(
            "atlas_chunks",
            "embedding",
            existing_type=Vector(),
            type_=sa.JSON(),
            existing_nullable=True,
            postgresql_using="CASE WHEN embedding IS NULL THEN NULL ELSE embedding::text::json END",
        )
        # The extension may be shared with other applications, so it is deliberately retained.
