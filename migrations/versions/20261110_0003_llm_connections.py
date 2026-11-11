"""User-owned model connections and write-only credentials."""

from alembic import op
import sqlalchemy as sa

revision = "20261110_0003"
down_revision = "20261110_0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "atlas_llm_connections",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("atlas_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("base_url", sa.String(2000), nullable=False),
        sa.Column("protocol", sa.String(40), nullable=False),
        sa.Column("models", sa.JSON(), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
    )
    op.create_index(
        "ix_atlas_llm_connections_user_id", "atlas_llm_connections", ["user_id"]
    )
    op.create_table(
        "atlas_llm_credentials",
        sa.Column(
            "connection_id",
            sa.String(40),
            sa.ForeignKey("atlas_llm_connections.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("encrypted_key", sa.Text(), nullable=False),
    )
    op.create_table(
        "atlas_llm_selections",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("atlas_users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "connection_id",
            sa.String(40),
            sa.ForeignKey("atlas_llm_connections.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade():
    op.drop_table("atlas_llm_selections")
    op.drop_table("atlas_llm_credentials")
    op.drop_index(
        "ix_atlas_llm_connections_user_id", table_name="atlas_llm_connections"
    )
    op.drop_table("atlas_llm_connections")
