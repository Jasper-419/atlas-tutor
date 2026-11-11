"""Private model-assisted practice validation receipts, preserving history."""

from alembic import op
import sqlalchemy as sa

revision = "20261110_0007"
down_revision = "20261110_0006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("atlas_practice_batches", sa.Column("validation", sa.JSON(),
        server_default=sa.text("'{}'"), nullable=False))


def downgrade():
    op.drop_column("atlas_practice_batches", "validation")
