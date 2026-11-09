"""Compare two parsed syllabi. Pure: no HTML and no database."""

from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Literal

from app.syllabus.parser import Domain, Skill, Syllabus

Level = Literal["syllabus", "domain", "skill", "subskill"]
ChangeType = Literal["added", "removed", "modified", "reordered"]

# ponytail: edit-distance heuristic. A heavy rewrite reports as removed + added, and an
# item moved to another parent does too. Nothing goes undetected, only labelled coarser.
_SAME_ITEM_RATIO = 0.6


@dataclass(frozen=True)
class Change:
    level: Level
    change_type: ChangeType
    domain_name: str | None = None
    skill_name: str | None = None
    old_value: Any = None
    new_value: Any = None


def _align(old: Sequence[str], new: Sequence[str]) -> dict[str, str]:
    """Map old names to new ones: exact matches first, then closest rewordings."""
    matched = {name: name for name in old if name in new}
    candidates = sorted(
        (
            (
                SequenceMatcher(None, before, after, autojunk=False).ratio(),
                before,
                after,
            )
            for before in old
            if before not in matched
            for after in new
            if after not in matched
        ),
        reverse=True,
    )
    for ratio, before, after in candidates:
        if ratio < _SAME_ITEM_RATIO:
            break
        if before not in matched and after not in matched.values():
            matched[before] = after
    return matched


def _reordered(
    level: Level,
    matched: dict[str, str],
    old: Sequence[str],
    new: Sequence[str],
    domain_name: str | None = None,
    skill_name: str | None = None,
) -> list[Change]:
    before = [matched[name] for name in old if name in matched]
    after = [name for name in new if name in matched.values()]
    if before == after:
        return []
    return [Change(level, "reordered", domain_name, skill_name, before, after)]


def _domain_value(domain: Domain) -> dict[str, Any]:
    return {
        "name": domain.name,
        "weight_min": domain.weight_min,
        "weight_max": domain.weight_max,
    }


def _whole_skill(
    domain_name: str, skill: Skill, change_type: Literal["added", "removed"]
) -> list[Change]:
    def change(level: Level, skill_name: str | None, value: str) -> Change:
        old, new = (None, value) if change_type == "added" else (value, None)
        return Change(level, change_type, domain_name, skill_name, old, new)

    return [
        change("skill", None, skill.name),
        *(change("subskill", skill.name, text) for text in skill.subskills),
    ]


def _whole_domain(
    domain: Domain, change_type: Literal["added", "removed"]
) -> list[Change]:
    value = _domain_value(domain)
    old, new = (None, value) if change_type == "added" else (value, None)
    return [
        Change("domain", change_type, domain.name, None, old, new),
        *(
            change
            for skill in domain.skills
            for change in _whole_skill(domain.name, skill, change_type)
        ),
    ]


def _diff_skill(domain_name: str, old: Skill, new: Skill) -> list[Change]:
    changes = []
    if old.name != new.name:
        changes.append(
            Change("skill", "modified", domain_name, None, old.name, new.name)
        )

    matched = _align(old.subskills, new.subskills)
    for text in old.subskills:
        if text not in matched:
            changes.append(
                Change("subskill", "removed", domain_name, new.name, text, None)
            )
        elif matched[text] != text:
            changes.append(
                Change(
                    "subskill", "modified", domain_name, new.name, text, matched[text]
                )
            )
    changes.extend(
        Change("subskill", "added", domain_name, new.name, None, text)
        for text in new.subskills
        if text not in matched.values()
    )
    changes.extend(
        _reordered(
            "subskill", matched, old.subskills, new.subskills, domain_name, new.name
        )
    )
    return changes


def _diff_domain(old: Domain, new: Domain) -> list[Change]:
    changes = []
    if _domain_value(old) != _domain_value(new):
        changes.append(
            Change(
                "domain",
                "modified",
                new.name,
                None,
                _domain_value(old),
                _domain_value(new),
            )
        )

    old_skills = {skill.name: skill for skill in old.skills}
    new_skills = {skill.name: skill for skill in new.skills}
    matched = _align(list(old_skills), list(new_skills))
    for name, skill in old_skills.items():
        if name in matched:
            changes.extend(_diff_skill(new.name, skill, new_skills[matched[name]]))
        else:
            changes.extend(_whole_skill(new.name, skill, "removed"))
    for name, skill in new_skills.items():
        if name not in matched.values():
            changes.extend(_whole_skill(new.name, skill, "added"))
    changes.extend(
        _reordered("skill", matched, list(old_skills), list(new_skills), new.name)
    )
    return changes


def diff_syllabi(old: Syllabus, new: Syllabus) -> list[Change]:
    changes: list[Change] = []
    if old.effective_date != new.effective_date:
        changes.append(
            Change(
                "syllabus",
                "modified",
                old_value=old.effective_date.isoformat(),
                new_value=new.effective_date.isoformat(),
            )
        )

    old_domains = {domain.name: domain for domain in old.domains}
    new_domains = {domain.name: domain for domain in new.domains}
    matched = _align(list(old_domains), list(new_domains))
    for name, domain in old_domains.items():
        if name in matched:
            changes.extend(_diff_domain(domain, new_domains[matched[name]]))
        else:
            changes.extend(_whole_domain(domain, "removed"))
    for name, domain in new_domains.items():
        if name not in matched.values():
            changes.extend(_whole_domain(domain, "added"))
    changes.extend(_reordered("domain", matched, list(old_domains), list(new_domains)))
    return changes
