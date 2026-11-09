"""Read the ingested syllabus and find the objectives relevant to a question."""

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.syllabus.models import (
    SyllabusDomain,
    SyllabusSkill,
    SyllabusSubskill,
    SyllabusVersion,
)
from app.syllabus.parser import normalize_text

ScopeLevel = Literal["domain", "skill", "subskill"]
MAX_REFERENCES = 5

# ponytail: lexical search, so a question sharing no word with the syllabus finds nothing
# and is reported as ungrounded. It suits ~64 short objectives and needs no embedding
# model. Add pgvector here if learners regularly miss objectives they meant.
_STOPWORD_TEXT = """a about ai an and are as at azure be but by can could do does exam
explain for from give had has have how i if implement implementing in into is it its me
microsoft my of on or our please should show so solution solutions tell than that the
their them then there these they this those to us use used using was we what when where
which who why will with would you your"""
_STOPWORDS = frozenset(_STOPWORD_TEXT.split())
_ALIASES = {"rag": "retrieval augmented"}
# A term in this share of objectives identifies nothing.
_MAX_DOCUMENT_SHARE = 0.4
_FIELD_WEIGHTS = (3, 2, 1)
_SUFFIXES = (
    "ations",
    "ation",
    "ities",
    "ions",
    "ives",
    "ings",
    "ion",
    "ity",
    "ive",
    "ing",
    "als",
    "al",
    "ed",
    "es",
    "s",
    "e",
)
_MIN_STEM = 3
_WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Topic:
    """One objective with its place in the syllabus."""

    version_number: int
    domain_id: int
    domain_position: int
    domain_name: str
    weight_min: int
    weight_max: int
    skill_id: int
    skill_position: int
    skill_name: str
    subskill_id: int
    subskill_position: int
    subskill_text: str

    @property
    def code(self) -> str:
        return f"{self.domain_position}.{self.skill_position}.{self.subskill_position}"

    def reference(self, match: str | None = None) -> dict[str, Any]:
        """A snapshot of real syllabus rows. This is the only source of citations."""
        return {
            "subskill_id": self.subskill_id,
            "skill_id": self.skill_id,
            "domain_id": self.domain_id,
            "code": self.code,
            "domain": self.domain_name,
            "skill": self.skill_name,
            "subskill": self.subskill_text,
            "weight_min": self.weight_min,
            "weight_max": self.weight_max,
            "version_number": self.version_number,
            "match": match,
        }


def load_topics(session: Session, version_id: int) -> list[Topic]:
    rows = session.execute(
        select(
            SyllabusVersion.version_number,
            SyllabusDomain,
            SyllabusSkill,
            SyllabusSubskill,
        )
        .join(SyllabusDomain, SyllabusDomain.version_id == SyllabusVersion.id)
        .join(SyllabusSkill, SyllabusSkill.domain_id == SyllabusDomain.id)
        .join(SyllabusSubskill, SyllabusSubskill.skill_id == SyllabusSkill.id)
        .where(SyllabusVersion.id == version_id)
        .order_by(
            SyllabusDomain.position, SyllabusSkill.position, SyllabusSubskill.position
        )
    )
    return [
        Topic(
            number,
            domain.id,
            domain.position,
            domain.name,
            domain.weight_min,
            domain.weight_max,
            skill.id,
            skill.position,
            skill.name,
            subskill.id,
            subskill.position,
            subskill.text,
        )
        for number, domain, skill, subskill in rows
    ]


def scope_version_id(session: Session, level: ScopeLevel, scope_id: int) -> int | None:
    """The syllabus version a domain, skill or subskill row belongs to, if it exists."""
    query = select(SyllabusDomain.version_id)
    if level == "domain":
        query = query.where(SyllabusDomain.id == scope_id)
    elif level == "skill":
        query = query.join(SyllabusSkill).where(SyllabusSkill.id == scope_id)
    else:
        query = (
            query.join(SyllabusSkill)
            .join(SyllabusSubskill)
            .where(SyllabusSubskill.id == scope_id)
        )
    return session.scalar(query)


def in_scope(
    topics: list[Topic], level: str | None, scope_id: int | None
) -> list[Topic]:
    if level == "domain":
        return [topic for topic in topics if topic.domain_id == scope_id]
    if level == "skill":
        return [topic for topic in topics if topic.skill_id == scope_id]
    if level == "subskill":
        return [topic for topic in topics if topic.subskill_id == scope_id]
    return []


def _stem(word: str) -> str:
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= _MIN_STEM:
            return word[: -len(suffix)]
    return word


def _terms(text: str) -> set[str]:
    words = _WORD.findall(normalize_text(text).lower())
    expanded = [part for word in words for part in _ALIASES.get(word, word).split()]
    return {_stem(word) for word in expanded if word not in _STOPWORDS}


def search(topics: list[Topic], query: str, limit: int = MAX_REFERENCES) -> list[Topic]:
    """Rank objectives by rare shared terms. Same input, same result, ties in syllabus order."""
    terms = _terms(query)
    if not terms or not topics:
        return []
    fields = [
        (
            _terms(topic.subskill_text),
            _terms(topic.skill_name),
            _terms(topic.domain_name),
        )
        for topic in topics
    ]
    # Domain names don't count: every objective inherits one, which would make each of
    # their words look common, including a topic as central as "generative".
    document_counts = Counter(
        term for subskill, skill, _ in fields for term in subskill | skill
    )
    total = len(topics)

    def score(topic_fields: tuple[set[str], set[str], set[str]]) -> float:
        result = 0.0
        for term in terms:
            count = max(document_counts[term], 1)
            if count <= total * _MAX_DOCUMENT_SHARE:
                weight = next(
                    (
                        weight
                        for field, weight in zip(
                            topic_fields, _FIELD_WEIGHTS, strict=True
                        )
                        if term in field
                    ),
                    0,
                )
                result += weight * math.log(1 + total / count)
        return result

    scored = [
        (value, topic)
        for topic, topic_fields in zip(topics, fields, strict=True)
        if (value := score(topic_fields)) > 0
    ]
    if not scored:
        return []
    best = max(value for value, _ in scored)
    # Sorting is stable, so equal scores keep syllabus order.
    ranked = sorted(scored, key=lambda pair: -pair[0])
    return [topic for value, topic in ranked if value >= best / 2][:limit]
