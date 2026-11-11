"""Durable Tutor sessions, turns, checkpoints and event replay."""

import sqlalchemy as sa
from alembic import op

revision = "20261110_0004"
down_revision = "20261110_0003"
branch_labels = None
depends_on = None


def owned_columns():
    return [
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("atlas_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.String(40), nullable=False),
    ]


def upgrade():
    op.create_table(
        "atlas_tutor_sessions",
        *owned_columns(),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column(
            "course_id",
            sa.String(40),
            sa.ForeignKey("atlas_courses.id", ondelete="CASCADE"),
        ),
        sa.Column(
            "node_id",
            sa.String(40),
            sa.ForeignKey("atlas_nodes.id", ondelete="SET NULL"),
        ),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
    )
    for field in ("user_id", "course_id", "node_id"):
        op.create_index(
            "ix_atlas_tutor_sessions_" + field, "atlas_tutor_sessions", [field]
        )
    op.create_table(
        "atlas_tutor_turns",
        *owned_columns(),
        sa.Column(
            "session_id",
            sa.String(40),
            sa.ForeignKey("atlas_tutor_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("request_id", sa.String(120), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("input", sa.Text(), nullable=False),
        sa.Column("output", sa.Text(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("checkpoint", sa.JSON(), nullable=False),
        sa.Column("pending_action", sa.JSON()),
        sa.Column("last_seq", sa.Integer(), nullable=False),
        sa.Column("lease_until", sa.String(40)),
        sa.Column("worker_token", sa.String(40)),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("session_id", "request_id"),
    )
    for field in ("user_id", "session_id", "status"):
        op.create_index("ix_atlas_tutor_turns_" + field, "atlas_tutor_turns", [field])
    op.create_table(
        "atlas_tutor_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "turn_id",
            sa.String(40),
            sa.ForeignKey("atlas_tutor_turns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("turn_id", "seq"),
    )
    op.create_index("ix_atlas_tutor_events_turn_id", "atlas_tutor_events", ["turn_id"])


def downgrade():
    op.drop_table("atlas_tutor_events")
    op.drop_table("atlas_tutor_turns")
    op.drop_table("atlas_tutor_sessions")
