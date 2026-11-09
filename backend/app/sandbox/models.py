"""Simulated Azure resources and guided lab progress. Every row belongs to one learner.

Nothing here talks to Azure: rows are the whole simulation, so state survives restarts
and a learner can only ever see rows carrying their own `learner_id`.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.syllabus.models import Base

RESOURCE_STATES = ("succeeded", "running", "stopped", "soft_deleted")


class Sandbox(Base):
    """One per learner. Every sandbox write locks this row, which serializes a
    learner's writes so checks across resources (quota, references) stay true."""

    __tablename__ = "sandbox"
    __table_args__ = (UniqueConstraint("learner_id", name="uq_sandbox_learner"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("learner.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SandboxResource(Base):
    """A simulated resource. `properties` is learner configuration, validated by
    `catalog.py`; `outputs` is what the simulation computed (test runs, documents)."""

    __tablename__ = "sandbox_resource"
    __table_args__ = (
        # Names are unique the way Azure scopes them; soft-deleted rows keep theirs.
        UniqueConstraint("learner_id", "unique_key", name="uq_sandbox_resource_key"),
        UniqueConstraint(
            "learner_id", "client_request_id", name="uq_sandbox_resource_request"
        ),
        CheckConstraint(
            "state IN ('succeeded', 'running', 'stopped', 'soft_deleted')",
            name="ck_sandbox_resource_state",
        ),
        Index("ix_sandbox_resource_learner_parent", "learner_id", "parent_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("learner.id"))
    resource_type: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(128))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("sandbox_resource.id"))
    unique_key: Mapped[str] = mapped_column(String(300))
    properties: Mapped[dict[str, Any]] = mapped_column(JSON)
    outputs: Mapped[dict[str, Any]] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(16))
    # Bumped on every configuration change; updates must name the version they read.
    version: Mapped[int] = mapped_column(Integer)
    client_request_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LabProgress(Base):
    __tablename__ = "lab_progress"
    __table_args__ = (
        UniqueConstraint("learner_id", "lab_id", name="uq_lab_progress"),
        CheckConstraint(
            "status IN ('in_progress', 'completed')", name="ck_lab_progress_status"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("learner.id"))
    lab_id: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # The first completion. A reset never clears it.
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resets: Mapped[int] = mapped_column(Integer)
    # Check id to the number of hints revealed.
    hints: Mapped[dict[str, int]] = mapped_column(JSON)


class LabValidation(Base):
    """One automated grading run, kept as history. Results are computed on the server
    from stored resources only."""

    __tablename__ = "lab_validation"
    __table_args__ = (
        UniqueConstraint(
            "learner_id", "client_validation_id", name="uq_lab_validation_client_id"
        ),
        Index("ix_lab_validation_learner_lab", "learner_id", "lab_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("learner.id"))
    lab_id: Mapped[str] = mapped_column(String(40))
    client_validation_id: Mapped[str] = mapped_column(String(64))
    passed: Mapped[bool] = mapped_column()
    passed_checks: Mapped[int] = mapped_column(Integer)
    total_checks: Mapped[int] = mapped_column(Integer)
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
