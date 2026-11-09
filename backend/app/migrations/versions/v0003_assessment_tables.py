"""Create question bank, Learn source and attempt tables.

Only adds tables. Syllabus and learning tables and their rows are not touched.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _timestamp(name: str, nullable: bool = False) -> sa.Column[object]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _fk(name: str, target: str) -> sa.Column[object]:
    return sa.Column(name, sa.Integer, sa.ForeignKey(target), nullable=False)


def upgrade() -> None:
    op.create_table(
        "learn_source",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        _timestamp("retrieved_at"),
        sa.UniqueConstraint("url", "content_hash", name="uq_learn_source_url_hash"),
    )
    op.create_table(
        "objective_source",
        sa.Column("id", sa.Integer, primary_key=True),
        _fk("subskill_id", "syllabus_subskill.id"),
        _fk("source_id", "learn_source.id"),
        _timestamp("created_at"),
        sa.UniqueConstraint("subskill_id", "source_id", name="uq_objective_source"),
    )
    op.create_index(
        "ix_objective_source_subskill_id", "objective_source", ["subskill_id"]
    )
    op.create_table(
        "question",
        sa.Column("id", sa.Integer, primary_key=True),
        _fk("syllabus_version_id", "syllabus_version.id"),
        _fk("domain_id", "syllabus_domain.id"),
        _fk("skill_id", "syllabus_skill.id"),
        _fk("subskill_id", "syllabus_subskill.id"),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("difficulty", sa.String(16), nullable=False),
        sa.Column("scenario", sa.Text, nullable=True),
        sa.Column("stem", sa.Text, nullable=False),
        sa.Column("options", sa.JSON, nullable=False),
        sa.Column("correct_index", sa.Integer, nullable=False),
        sa.Column("explanation", sa.Text, nullable=False),
        _fk("source_id", "learn_source.id"),
        sa.Column("source_excerpt", sa.Text, nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("llm_model", sa.Text, nullable=False),
        sa.Column("llm_provider", sa.Text, nullable=False),
        _timestamp("created_at"),
        sa.UniqueConstraint(
            "syllabus_version_id", "fingerprint", name="uq_question_fingerprint"
        ),
        sa.CheckConstraint("kind IN ('mcq', 'scenario')", name="ck_question_kind"),
        sa.CheckConstraint(
            "difficulty IN ('easy', 'medium', 'hard')", name="ck_question_difficulty"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'retired')", name="ck_question_status"
        ),
        sa.CheckConstraint("correct_index >= 0", name="ck_question_correct_index"),
    )
    op.create_index(
        "ix_question_version_subskill",
        "question",
        ["syllabus_version_id", "subskill_id"],
    )
    op.create_table(
        "exam_attempt",
        sa.Column("id", sa.Integer, primary_key=True),
        _fk("learner_id", "learner.id"),
        _fk("syllabus_version_id", "syllabus_version.id"),
        sa.Column("client_attempt_id", sa.String(64), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("selection", sa.String(16), nullable=False),
        sa.Column("scope_level", sa.String(16), nullable=True),
        sa.Column("scope_id", sa.Integer, nullable=True),
        sa.Column("difficulty", sa.String(16), nullable=True),
        sa.Column("question_count", sa.Integer, nullable=False),
        sa.Column("time_limit_seconds", sa.Integer, nullable=True),
        _timestamp("started_at"),
        _timestamp("deadline_at", nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        _timestamp("submitted_at", nullable=True),
        sa.Column("submit_reason", sa.String(16), nullable=True),
        sa.Column("score", sa.Integer, nullable=True),
        sa.UniqueConstraint(
            "learner_id", "client_attempt_id", name="uq_exam_attempt_client_id"
        ),
        sa.CheckConstraint("mode IN ('practice', 'mock')", name="ck_exam_attempt_mode"),
        sa.CheckConstraint(
            "status IN ('in_progress', 'submitted')", name="ck_exam_attempt_status"
        ),
        sa.CheckConstraint(
            "selection IN ('topic', 'adaptive', 'exam')",
            name="ck_exam_attempt_selection",
        ),
        sa.CheckConstraint(
            "submit_reason IN ('learner', 'completed', 'time_expired')",
            name="ck_exam_attempt_submit_reason",
        ),
        sa.CheckConstraint(
            "scope_level IN ('domain', 'skill', 'subskill')",
            name="ck_exam_attempt_scope_level",
        ),
    )
    op.create_index(
        "ix_exam_attempt_learner_version",
        "exam_attempt",
        ["learner_id", "syllabus_version_id"],
    )
    op.create_table(
        "attempt_question",
        sa.Column("id", sa.Integer, primary_key=True),
        _fk("attempt_id", "exam_attempt.id"),
        sa.Column("position", sa.Integer, nullable=False),
        _fk("question_id", "question.id"),
        sa.Column("chosen_index", sa.Integer, nullable=True),
        _timestamp("answered_at", nullable=True),
        sa.Column("is_correct", sa.Boolean, nullable=True),
        sa.UniqueConstraint(
            "attempt_id", "position", name="uq_attempt_question_position"
        ),
        sa.UniqueConstraint(
            "attempt_id", "question_id", name="uq_attempt_question_question"
        ),
    )
    op.create_index(
        "ix_attempt_question_attempt_id", "attempt_question", ["attempt_id"]
    )


def downgrade() -> None:
    op.drop_table("attempt_question")
    op.drop_table("exam_attempt")
    op.drop_table("question")
    op.drop_table("objective_source")
    op.drop_table("learn_source")
