"""Versioned syllabus tables. Rows are append-only except `last_checked_at`."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SyllabusVersion(Base):
    __tablename__ = "syllabus_version"
    __table_args__ = (
        # Latest version is max(version_number). Also stops concurrent duplicates.
        UniqueConstraint(
            "exam_code", "version_number", name="uq_syllabus_version_number"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_code: Mapped[str] = mapped_column(String(32))
    version_number: Mapped[int] = mapped_column(Integer)
    source_url: Mapped[str] = mapped_column(Text)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_date: Mapped[date] = mapped_column(Date)
    content_hash: Mapped[str] = mapped_column(String(64))

    domains: Mapped[list["SyllabusDomain"]] = relationship(
        order_by="SyllabusDomain.position"
    )
    changes: Mapped[list["SyllabusChange"]] = relationship(
        order_by="SyllabusChange.position"
    )


class SyllabusDomain(Base):
    __tablename__ = "syllabus_domain"
    __table_args__ = (
        UniqueConstraint("version_id", "position", name="uq_syllabus_domain_position"),
        UniqueConstraint("version_id", "name", name="uq_syllabus_domain_name"),
        CheckConstraint(
            "weight_min >= 0 AND weight_min <= weight_max AND weight_max <= 100",
            name="ck_syllabus_domain_weight",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("syllabus_version.id"))
    position: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(Text)
    weight_min: Mapped[int] = mapped_column(Integer)
    weight_max: Mapped[int] = mapped_column(Integer)

    skills: Mapped[list["SyllabusSkill"]] = relationship(
        order_by="SyllabusSkill.position"
    )


class SyllabusSkill(Base):
    __tablename__ = "syllabus_skill"
    __table_args__ = (
        UniqueConstraint("domain_id", "position", name="uq_syllabus_skill_position"),
        UniqueConstraint("domain_id", "name", name="uq_syllabus_skill_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("syllabus_domain.id"))
    position: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(Text)

    subskills: Mapped[list["SyllabusSubskill"]] = relationship(
        order_by="SyllabusSubskill.position"
    )


class SyllabusSubskill(Base):
    __tablename__ = "syllabus_subskill"
    __table_args__ = (
        UniqueConstraint("skill_id", "position", name="uq_syllabus_subskill_position"),
        UniqueConstraint("skill_id", "text", name="uq_syllabus_subskill_text"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("syllabus_skill.id"))
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)


class SyllabusChange(Base):
    """One difference between a version and the version before it."""

    __tablename__ = "syllabus_change"
    __table_args__ = (
        UniqueConstraint("version_id", "position", name="uq_syllabus_change_position"),
        CheckConstraint(
            "level IN ('syllabus', 'domain', 'skill', 'subskill')",
            name="ck_syllabus_change_level",
        ),
        CheckConstraint(
            "change_type IN ('added', 'removed', 'modified', 'reordered')",
            name="ck_syllabus_change_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("syllabus_version.id"))
    position: Mapped[int] = mapped_column(Integer)
    level: Mapped[str] = mapped_column(String(16))
    change_type: Mapped[str] = mapped_column(String(16))
    domain_name: Mapped[str | None] = mapped_column(Text)
    skill_name: Mapped[str | None] = mapped_column(Text)
    # none_as_null: "no value" is SQL NULL, not a JSON null that IS NULL would miss.
    old_value: Mapped[Any] = mapped_column(JSON(none_as_null=True), nullable=True)
    new_value: Mapped[Any] = mapped_column(JSON(none_as_null=True), nullable=True)
