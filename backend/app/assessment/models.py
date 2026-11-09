"""Question bank and attempt tables.

`learn_source` and `question` are shared and append-only: a source's text is never
rewritten (new content is a new row) and a question is never edited, only retired, so
every stored answer can always be traced to the exact text it was verified against.
Attempts and their answers belong to exactly one learner.
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.syllabus.models import Base


class LearnSource(Base):
    """Plain text of one Microsoft Learn page, as fetched at `retrieved_at`."""

    __tablename__ = "learn_source"
    __table_args__ = (
        UniqueConstraint("url", "content_hash", name="uq_learn_source_url_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ObjectiveSource(Base):
    """A source attached to one objective. The objective fixes the syllabus version."""

    __tablename__ = "objective_source"
    __table_args__ = (
        UniqueConstraint("subskill_id", "source_id", name="uq_objective_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    subskill_id: Mapped[int] = mapped_column(
        ForeignKey("syllabus_subskill.id"), index=True
    )
    source_id: Mapped[int] = mapped_column(ForeignKey("learn_source.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Question(Base):
    """A single-answer practice question, mapped by the server to one objective."""

    __tablename__ = "question"
    __table_args__ = (
        UniqueConstraint(
            "syllabus_version_id", "fingerprint", name="uq_question_fingerprint"
        ),
        CheckConstraint("kind IN ('mcq', 'scenario')", name="ck_question_kind"),
        CheckConstraint(
            "difficulty IN ('easy', 'medium', 'hard')", name="ck_question_difficulty"
        ),
        CheckConstraint("status IN ('active', 'retired')", name="ck_question_status"),
        CheckConstraint("correct_index >= 0", name="ck_question_correct_index"),
        Index("ix_question_version_subskill", "syllabus_version_id", "subskill_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Version, domain and skill are copies of the objective's own rows, for filtering.
    syllabus_version_id: Mapped[int] = mapped_column(ForeignKey("syllabus_version.id"))
    domain_id: Mapped[int] = mapped_column(ForeignKey("syllabus_domain.id"))
    skill_id: Mapped[int] = mapped_column(ForeignKey("syllabus_skill.id"))
    subskill_id: Mapped[int] = mapped_column(ForeignKey("syllabus_subskill.id"))
    kind: Mapped[str] = mapped_column(String(16))
    difficulty: Mapped[str] = mapped_column(String(16))
    scenario: Mapped[str | None] = mapped_column(Text)
    stem: Mapped[str] = mapped_column(Text)
    options: Mapped[list[str]] = mapped_column(JSON)
    correct_index: Mapped[int] = mapped_column(Integer)
    explanation: Mapped[str] = mapped_column(Text)
    source_id: Mapped[int] = mapped_column(ForeignKey("learn_source.id"))
    # Verbatim text of the source that supports the answer, checked on the server.
    source_excerpt: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    llm_model: Mapped[str] = mapped_column(Text)
    llm_provider: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class QuestionGeneration(Base):
    """One generation request. Written before the model is called, so failed and
    refused requests still count, and request rates can be limited from it."""

    __tablename__ = "question_generation"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'refused')",
            name="ck_question_generation_status",
        ),
        Index("ix_question_generation_created_at", "created_at"),
        Index("ix_question_generation_learner_created", "learner_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("learner.id"))
    subskill_id: Mapped[int] = mapped_column(ForeignKey("syllabus_subskill.id"))
    status: Mapped[str] = mapped_column(String(16))
    accepted: Mapped[int | None] = mapped_column(Integer)
    rejected: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExamAttempt(Base):
    """A practice quiz or a mock exam. Deadlines are server time, stored, so they
    survive restarts; an overdue attempt is submitted the next time anything reads it."""

    __tablename__ = "exam_attempt"
    __table_args__ = (
        UniqueConstraint(
            "learner_id", "client_attempt_id", name="uq_exam_attempt_client_id"
        ),
        CheckConstraint("mode IN ('practice', 'mock')", name="ck_exam_attempt_mode"),
        CheckConstraint(
            "status IN ('in_progress', 'submitted')", name="ck_exam_attempt_status"
        ),
        CheckConstraint(
            "selection IN ('topic', 'adaptive', 'exam')",
            name="ck_exam_attempt_selection",
        ),
        CheckConstraint(
            "submit_reason IN ('learner', 'completed', 'time_expired')",
            name="ck_exam_attempt_submit_reason",
        ),
        CheckConstraint(
            "scope_level IN ('domain', 'skill', 'subskill')",
            name="ck_exam_attempt_scope_level",
        ),
        Index("ix_exam_attempt_learner_version", "learner_id", "syllabus_version_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("learner.id"))
    syllabus_version_id: Mapped[int] = mapped_column(ForeignKey("syllabus_version.id"))
    client_attempt_id: Mapped[str] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(16))
    selection: Mapped[str] = mapped_column(String(16))
    scope_level: Mapped[str | None] = mapped_column(String(16))
    scope_id: Mapped[int | None] = mapped_column(Integer)
    difficulty: Mapped[str | None] = mapped_column(String(16))
    question_count: Mapped[int] = mapped_column(Integer)
    time_limit_seconds: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submit_reason: Mapped[str | None] = mapped_column(String(16))
    score: Mapped[int | None] = mapped_column(Integer)


class AttemptQuestion(Base):
    """One question in an attempt. `is_correct` is set only by server-side grading:
    when a practice answer is given, or for every question when a mock is submitted."""

    __tablename__ = "attempt_question"
    __table_args__ = (
        UniqueConstraint("attempt_id", "position", name="uq_attempt_question_position"),
        UniqueConstraint(
            "attempt_id", "question_id", name="uq_attempt_question_question"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("exam_attempt.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    question_id: Mapped[int] = mapped_column(ForeignKey("question.id"))
    chosen_index: Mapped[int | None] = mapped_column(Integer)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_correct: Mapped[bool | None] = mapped_column()
