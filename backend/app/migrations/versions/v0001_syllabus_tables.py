"""Create versioned syllabus tables.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "syllabus_version",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("exam_code", sa.String(32), nullable=False),
        sa.Column("version_number", sa.Integer, nullable=False),
        sa.Column("source_url", sa.Text, nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_date", sa.Date, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint(
            "exam_code", "version_number", name="uq_syllabus_version_number"
        ),
    )
    op.create_table(
        "syllabus_domain",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "version_id",
            sa.Integer,
            sa.ForeignKey("syllabus_version.id"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("weight_min", sa.Integer, nullable=False),
        sa.Column("weight_max", sa.Integer, nullable=False),
        sa.UniqueConstraint(
            "version_id", "position", name="uq_syllabus_domain_position"
        ),
        sa.UniqueConstraint("version_id", "name", name="uq_syllabus_domain_name"),
        sa.CheckConstraint(
            "weight_min >= 0 AND weight_min <= weight_max AND weight_max <= 100",
            name="ck_syllabus_domain_weight",
        ),
    )
    op.create_table(
        "syllabus_skill",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "domain_id", sa.Integer, sa.ForeignKey("syllabus_domain.id"), nullable=False
        ),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.UniqueConstraint("domain_id", "position", name="uq_syllabus_skill_position"),
        sa.UniqueConstraint("domain_id", "name", name="uq_syllabus_skill_name"),
    )
    op.create_table(
        "syllabus_subskill",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "skill_id", sa.Integer, sa.ForeignKey("syllabus_skill.id"), nullable=False
        ),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.UniqueConstraint(
            "skill_id", "position", name="uq_syllabus_subskill_position"
        ),
        sa.UniqueConstraint("skill_id", "text", name="uq_syllabus_subskill_text"),
    )
    op.create_table(
        "syllabus_change",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "version_id",
            sa.Integer,
            sa.ForeignKey("syllabus_version.id"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("change_type", sa.String(16), nullable=False),
        sa.Column("domain_name", sa.Text, nullable=True),
        sa.Column("skill_name", sa.Text, nullable=True),
        sa.Column("old_value", sa.JSON, nullable=True),
        sa.Column("new_value", sa.JSON, nullable=True),
        sa.UniqueConstraint(
            "version_id", "position", name="uq_syllabus_change_position"
        ),
        sa.CheckConstraint(
            "level IN ('syllabus', 'domain', 'skill', 'subskill')",
            name="ck_syllabus_change_level",
        ),
        sa.CheckConstraint(
            "change_type IN ('added', 'removed', 'modified', 'reordered')",
            name="ck_syllabus_change_type",
        ),
    )


def downgrade() -> None:
    op.drop_table("syllabus_change")
    op.drop_table("syllabus_subskill")
    op.drop_table("syllabus_skill")
    op.drop_table("syllabus_domain")
    op.drop_table("syllabus_version")
