"""Durable practice batches, evidence and legacy mastery baseline."""

from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "20261110_0005"
down_revision = "20261110_0004"
branch_labels = None
depends_on = None


def owned():
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
        "atlas_practice_batches",
        *owned(),
        sa.Column(
            "node_id",
            sa.String(40),
            sa.ForeignKey("atlas_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("request_key", sa.String(120), nullable=False),
        sa.Column("request_spec", sa.JSON(), nullable=False),
        sa.Column("exercise_ids", sa.JSON(), nullable=False),
        sa.UniqueConstraint("user_id", "node_id", "request_key"),
    )
    op.create_table(
        "atlas_exercise_metadata",
        *owned(),
        sa.Column(
            "exercise_id",
            sa.String(40),
            sa.ForeignKey("atlas_exercises.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("skill_type", sa.String(30), nullable=False),
        sa.Column("difficulty", sa.String(30), nullable=False),
        sa.Column("focus", sa.Text(), nullable=False),
        sa.Column("criteria", sa.JSON(), nullable=False),
    )
    op.create_table(
        "atlas_learning_evidence",
        *owned(),
        sa.Column(
            "attempt_id",
            sa.String(40),
            sa.ForeignKey("atlas_attempts.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "node_id",
            sa.String(40),
            sa.ForeignKey("atlas_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "exercise_id",
            sa.String(40),
            sa.ForeignKey("atlas_exercises.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("skill_type", sa.String(30), nullable=False),
        sa.Column("difficulty", sa.String(30), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("independent", sa.Boolean(), nullable=False),
        sa.Column("misconception", sa.Text(), nullable=False),
        sa.Column("criteria_scores", sa.JSON(), nullable=False),
    )
    op.create_table(
        "atlas_node_learning_states",
        *owned(),
        sa.Column(
            "node_id",
            sa.String(40),
            sa.ForeignKey("atlas_nodes.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("baseline_mastery", sa.Float(), nullable=False),
        sa.Column("strategy", sa.String(30), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
    )
    for table, columns in {
        "atlas_practice_batches": ["user_id", "node_id"],
        "atlas_exercise_metadata": ["user_id", "exercise_id"],
        "atlas_learning_evidence": ["user_id", "attempt_id", "node_id", "exercise_id"],
        "atlas_node_learning_states": ["user_id", "node_id"],
    }.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])
    # Existing achievement remains valid; only subsequent submitted evidence can alter it.
    connection = op.get_bind()
    nodes = (
        connection.execute(
            sa.text("SELECT id, user_id, mastery FROM atlas_nodes WHERE mastery >= 80")
        )
        .mappings()
        .all()
    )
    timestamp = datetime.now(UTC).isoformat()
    target = sa.table(
        "atlas_node_learning_states",
        sa.column("id"),
        sa.column("user_id"),
        sa.column("created_at"),
        sa.column("node_id"),
        sa.column("baseline_mastery"),
        sa.column("strategy"),
        sa.column("updated_at"),
    )
    if nodes:
        connection.execute(
            target.insert(),
            [
                {
                    "id": str(uuid4()),
                    "user_id": node["user_id"],
                    "created_at": timestamp,
                    "node_id": node["id"],
                    "baseline_mastery": node["mastery"],
                    "strategy": "concept",
                    "updated_at": timestamp,
                }
                for node in nodes
            ],
        )


def downgrade():
    for name in (
        "atlas_learning_evidence",
        "atlas_exercise_metadata",
        "atlas_practice_batches",
        "atlas_node_learning_states",
    ):
        op.drop_table(name)
