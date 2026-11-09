"""Create learner, tutor, lesson, progress and plan tables.

Only adds tables. Syllabus tables and their rows are not touched.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _timestamp(name: str, nullable: bool = False) -> sa.Column[object]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _fk(name: str, target: str) -> sa.Column[object]:
    return sa.Column(name, sa.Integer, sa.ForeignKey(target), nullable=False)


def upgrade() -> None:
    op.create_table(
        "learner",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        _timestamp("created_at"),
        sa.UniqueConstraint("token_hash", name="uq_learner_token_hash"),
    )
    op.create_table(
        "conversation",
        sa.Column("id", sa.Integer, primary_key=True),
        _fk("learner_id", "learner.id"),
        _fk("syllabus_version_id", "syllabus_version.id"),
        sa.Column("scope_level", sa.String(16), nullable=True),
        sa.Column("scope_id", sa.Integer, nullable=True),
        sa.Column("title", sa.Text, nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.CheckConstraint(
            "scope_level IN ('domain', 'skill', 'subskill')",
            name="ck_conversation_scope_level",
        ),
    )
    op.create_index("ix_conversation_learner_id", "conversation", ["learner_id"])
    op.create_table(
        "conversation_message",
        sa.Column("id", sa.Integer, primary_key=True),
        _fk("conversation_id", "conversation.id"),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("syllabus_refs", sa.JSON, nullable=False),
        sa.Column("llm_model", sa.Text, nullable=True),
        sa.Column("llm_provider", sa.Text, nullable=True),
        sa.Column("client_message_id", sa.String(64), nullable=True),
        _timestamp("created_at"),
        sa.UniqueConstraint(
            "conversation_id",
            "client_message_id",
            name="uq_conversation_message_client_id",
        ),
        sa.CheckConstraint(
            "role IN ('user', 'assistant')", name="ck_conversation_message_role"
        ),
    )
    op.create_index(
        "ix_conversation_message_conversation_id",
        "conversation_message",
        ["conversation_id"],
    )
    op.create_table(
        "lesson",
        sa.Column("id", sa.Integer, primary_key=True),
        _fk("syllabus_version_id", "syllabus_version.id"),
        sa.Column("scope_level", sa.String(16), nullable=False),
        sa.Column("scope_id", sa.Integer, nullable=False),
        sa.Column("depth", sa.String(16), nullable=False),
        sa.Column("content", sa.JSON, nullable=False),
        sa.Column("syllabus_refs", sa.JSON, nullable=False),
        sa.Column("llm_model", sa.Text, nullable=False),
        sa.Column("llm_provider", sa.Text, nullable=False),
        _timestamp("created_at"),
        sa.UniqueConstraint(
            "syllabus_version_id",
            "scope_level",
            "scope_id",
            "depth",
            name="uq_lesson_scope_depth",
        ),
        sa.CheckConstraint(
            "scope_level IN ('domain', 'skill', 'subskill')",
            name="ck_lesson_scope_level",
        ),
        sa.CheckConstraint(
            "depth IN ('beginner', 'intermediate', 'advanced')", name="ck_lesson_depth"
        ),
    )
    op.create_table(
        "lesson_progress",
        sa.Column("id", sa.Integer, primary_key=True),
        _fk("learner_id", "learner.id"),
        _fk("lesson_id", "lesson.id"),
        sa.Column("status", sa.String(16), nullable=False),
        _timestamp("started_at"),
        _timestamp("completed_at", nullable=True),
        sa.Column("check_answers", sa.JSON, nullable=True),
        sa.Column("check_score", sa.Integer, nullable=True),
        sa.Column("check_total", sa.Integer, nullable=True),
        sa.Column("check_attempts", sa.Integer, nullable=False),
        _timestamp("check_submitted_at", nullable=True),
        sa.UniqueConstraint("learner_id", "lesson_id", name="uq_lesson_progress"),
        sa.CheckConstraint(
            "status IN ('in_progress', 'completed')", name="ck_lesson_progress_status"
        ),
    )
    op.create_table(
        "topic_progress",
        sa.Column("id", sa.Integer, primary_key=True),
        _fk("learner_id", "learner.id"),
        _fk("syllabus_version_id", "syllabus_version.id"),
        _fk("subskill_id", "syllabus_subskill.id"),
        sa.Column("status", sa.String(16), nullable=False),
        _timestamp("started_at", nullable=True),
        _timestamp("completed_at", nullable=True),
        _timestamp("updated_at"),
        sa.UniqueConstraint("learner_id", "subskill_id", name="uq_topic_progress"),
        sa.CheckConstraint(
            "status IN ('not_started', 'in_progress', 'completed')",
            name="ck_topic_progress_status",
        ),
    )
    op.create_index(
        "ix_topic_progress_learner_version",
        "topic_progress",
        ["learner_id", "syllabus_version_id"],
    )
    op.create_table(
        "learning_plan",
        sa.Column("id", sa.Integer, primary_key=True),
        _fk("learner_id", "learner.id"),
        _fk("syllabus_version_id", "syllabus_version.id"),
        sa.Column("familiarity", sa.JSON, nullable=False),
        sa.Column("weekly_hours", sa.Integer, nullable=False),
        sa.Column("exam_date", sa.Date, nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.UniqueConstraint(
            "learner_id", "syllabus_version_id", name="uq_learning_plan"
        ),
        sa.CheckConstraint(
            "weekly_hours BETWEEN 1 AND 80", name="ck_learning_plan_weekly_hours"
        ),
    )


def downgrade() -> None:
    op.drop_table("learning_plan")
    op.drop_table("topic_progress")
    op.drop_table("lesson_progress")
    op.drop_table("lesson")
    op.drop_table("conversation_message")
    op.drop_table("conversation")
    op.drop_table("learner")
