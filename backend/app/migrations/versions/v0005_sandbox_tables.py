"""Create the Azure sandbox simulator and guided lab tables.

Only adds tables. Earlier tables and their rows are not touched.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _timestamp(name: str, nullable: bool = False) -> sa.Column[object]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _learner() -> sa.Column[object]:
    return sa.Column(
        "learner_id", sa.Integer, sa.ForeignKey("learner.id"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "sandbox",
        sa.Column("id", sa.Integer, primary_key=True),
        _learner(),
        _timestamp("created_at"),
        sa.UniqueConstraint("learner_id", name="uq_sandbox_learner"),
    )
    op.create_table(
        "sandbox_resource",
        sa.Column("id", sa.Integer, primary_key=True),
        _learner(),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column(
            "parent_id",
            sa.Integer,
            sa.ForeignKey("sandbox_resource.id"),
            nullable=True,
        ),
        sa.Column("unique_key", sa.String(300), nullable=False),
        sa.Column("properties", sa.JSON, nullable=False),
        sa.Column("outputs", sa.JSON, nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("client_request_id", sa.String(64), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        _timestamp("deleted_at", nullable=True),
        sa.UniqueConstraint("learner_id", "unique_key", name="uq_sandbox_resource_key"),
        sa.UniqueConstraint(
            "learner_id", "client_request_id", name="uq_sandbox_resource_request"
        ),
        sa.CheckConstraint(
            "state IN ('succeeded', 'running', 'stopped', 'soft_deleted')",
            name="ck_sandbox_resource_state",
        ),
    )
    op.create_index(
        "ix_sandbox_resource_learner_parent",
        "sandbox_resource",
        ["learner_id", "parent_id"],
    )
    op.create_table(
        "lab_progress",
        sa.Column("id", sa.Integer, primary_key=True),
        _learner(),
        sa.Column("lab_id", sa.String(40), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        _timestamp("started_at"),
        _timestamp("completed_at", nullable=True),
        sa.Column("resets", sa.Integer, nullable=False),
        sa.Column("hints", sa.JSON, nullable=False),
        sa.UniqueConstraint("learner_id", "lab_id", name="uq_lab_progress"),
        sa.CheckConstraint(
            "status IN ('in_progress', 'completed')", name="ck_lab_progress_status"
        ),
    )
    op.create_table(
        "lab_validation",
        sa.Column("id", sa.Integer, primary_key=True),
        _learner(),
        sa.Column("lab_id", sa.String(40), nullable=False),
        sa.Column("client_validation_id", sa.String(64), nullable=False),
        sa.Column("passed", sa.Boolean, nullable=False),
        sa.Column("passed_checks", sa.Integer, nullable=False),
        sa.Column("total_checks", sa.Integer, nullable=False),
        sa.Column("results", sa.JSON, nullable=False),
        _timestamp("created_at"),
        sa.UniqueConstraint(
            "learner_id", "client_validation_id", name="uq_lab_validation_client_id"
        ),
    )
    op.create_index(
        "ix_lab_validation_learner_lab", "lab_validation", ["learner_id", "lab_id"]
    )


def downgrade() -> None:
    op.drop_table("lab_validation")
    op.drop_table("lab_progress")
    op.drop_table("sandbox_resource")
    op.drop_table("sandbox")
