"""Learner data. Everything except `lesson` belongs to exactly one learner.

Lessons are shared on purpose: their prompt holds only syllabus text and a depth, never
anything a learner typed, so reusing one between learners leaks nothing.
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.syllabus.models import Base


class Learner(Base):
    """An anonymous learner, identified by a bearer token only its browser holds."""

    __tablename__ = "learner"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_learner_token_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Conversation(Base):
    __tablename__ = "conversation"
    __table_args__ = (
        CheckConstraint(
            "scope_level IN ('domain', 'skill', 'subskill')",
            name="ck_conversation_scope_level",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("learner.id"), index=True)
    syllabus_version_id: Mapped[int] = mapped_column(ForeignKey("syllabus_version.id"))
    # The topic the learner chose to talk about, if any.
    scope_level: Mapped[str | None] = mapped_column(String(16))
    scope_id: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConversationMessage(Base):
    """Ordered by id. Each exchange is written in one transaction, or not at all."""

    __tablename__ = "conversation_message"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "client_message_id",
            name="uq_conversation_message_client_id",
        ),
        CheckConstraint(
            "role IN ('user', 'assistant')", name="ck_conversation_message_role"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversation.id"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    # Set on assistant messages: what retrieval supplied, never what the model claimed.
    syllabus_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    llm_model: Mapped[str | None] = mapped_column(Text)
    llm_provider: Mapped[str | None] = mapped_column(Text)
    # Set on user messages, so a retried send can't create a second exchange.
    client_message_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Lesson(Base):
    __tablename__ = "lesson"
    __table_args__ = (
        UniqueConstraint(
            "syllabus_version_id",
            "scope_level",
            "scope_id",
            "depth",
            name="uq_lesson_scope_depth",
        ),
        CheckConstraint(
            "scope_level IN ('domain', 'skill', 'subskill')",
            name="ck_lesson_scope_level",
        ),
        CheckConstraint(
            "depth IN ('beginner', 'intermediate', 'advanced')", name="ck_lesson_depth"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    syllabus_version_id: Mapped[int] = mapped_column(ForeignKey("syllabus_version.id"))
    scope_level: Mapped[str] = mapped_column(String(16))
    scope_id: Mapped[int] = mapped_column(Integer)
    depth: Mapped[str] = mapped_column(String(16))
    content: Mapped[dict[str, Any]] = mapped_column(JSON)
    syllabus_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    llm_model: Mapped[str] = mapped_column(Text)
    llm_provider: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LessonProgress(Base):
    """One learner's completion of a lesson and their latest comprehension check."""

    __tablename__ = "lesson_progress"
    __table_args__ = (
        UniqueConstraint("learner_id", "lesson_id", name="uq_lesson_progress"),
        CheckConstraint(
            "status IN ('in_progress', 'completed')", name="ck_lesson_progress_status"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("learner.id"))
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lesson.id"))
    status: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    check_answers: Mapped[list[int] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    check_score: Mapped[int | None] = mapped_column(Integer)
    check_total: Mapped[int | None] = mapped_column(Integer)
    check_attempts: Mapped[int] = mapped_column(Integer)
    check_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TopicProgress(Base):
    """One learner's status on one objective, which belongs to one syllabus version."""

    __tablename__ = "topic_progress"
    __table_args__ = (
        UniqueConstraint("learner_id", "subskill_id", name="uq_topic_progress"),
        CheckConstraint(
            "status IN ('not_started', 'in_progress', 'completed')",
            name="ck_topic_progress_status",
        ),
        Index("ix_topic_progress_learner_version", "learner_id", "syllabus_version_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("learner.id"))
    syllabus_version_id: Mapped[int] = mapped_column(ForeignKey("syllabus_version.id"))
    subskill_id: Mapped[int] = mapped_column(ForeignKey("syllabus_subskill.id"))
    status: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LearningPlan(Base):
    """Only the learner's inputs. Recommendations are always recalculated from these."""

    __tablename__ = "learning_plan"
    __table_args__ = (
        UniqueConstraint("learner_id", "syllabus_version_id", name="uq_learning_plan"),
        CheckConstraint(
            "weekly_hours BETWEEN 1 AND 80", name="ck_learning_plan_weekly_hours"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("learner.id"))
    syllabus_version_id: Mapped[int] = mapped_column(ForeignKey("syllabus_version.id"))
    # Skill id (as a string, since this is JSON) to a level from 0 to 3.
    familiarity: Mapped[dict[str, int]] = mapped_column(JSON)
    weekly_hours: Mapped[int] = mapped_column(Integer)
    exam_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
