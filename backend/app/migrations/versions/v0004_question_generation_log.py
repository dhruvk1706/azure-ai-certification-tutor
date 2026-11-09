"""Log question generation requests, so their rate can be limited.

Only adds a table. Earlier tables and their rows are not touched.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "question_generation",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "learner_id", sa.Integer, sa.ForeignKey("learner.id"), nullable=False
        ),
        sa.Column(
            "subskill_id",
            sa.Integer,
            sa.ForeignKey("syllabus_subskill.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("accepted", sa.Integer, nullable=True),
        sa.Column("rejected", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'refused')",
            name="ck_question_generation_status",
        ),
    )
    op.create_index(
        "ix_question_generation_created_at", "question_generation", ["created_at"]
    )
    op.create_index(
        "ix_question_generation_learner_created",
        "question_generation",
        ["learner_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("question_generation")
