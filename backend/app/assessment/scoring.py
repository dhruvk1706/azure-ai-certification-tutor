"""Question selection, analytics and adaptive ranking. Plain arithmetic, no model.

Grading itself is one comparison with the stored `correct_index`, done in the API on
the server; nothing here trusts anything the browser sends beyond an option index.
"""

import math
import random
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

from app.learning.retrieval import Topic

# ponytail: a percentage stands in for Microsoft's scaled score (700 of 1000), whose
# per-question weighting is not public. Treat readiness as a rough guide, not a forecast.
PASS_PERCENT = 70
READY_PERCENT = 80
STRONG_PERCENT = 80
WEAK_PERCENT = 60
MIN_AREA_ANSWERS = 5
MIN_READINESS_ANSWERS = 20
MIN_READINESS_DOMAIN_ANSWERS = 3
MAX_RECOMMENDATIONS = 5

Standing = Literal["strength", "developing", "weakness", "insufficient_data"]
Readiness = Literal["likely_ready", "borderline", "not_ready", "insufficient_data"]


@dataclass(frozen=True)
class Candidate:
    """A question that could be selected, with this learner's history on it."""

    question_id: int
    subskill_id: int
    domain_id: int
    last_correct: bool | None  # None: never graded for this learner


@dataclass(frozen=True)
class Graded:
    subskill_id: int
    is_correct: bool


@dataclass(frozen=True)
class Tally:
    answered: int = 0
    correct: int = 0

    @property
    def percent(self) -> int | None:
        return self.correct * 100 // self.answered if self.answered else None

    def add(self, correct: bool) -> "Tally":
        return Tally(self.answered + 1, self.correct + correct)


def weight(topic: Topic) -> int:
    """Domain weight midpoint, doubled to stay an integer."""
    return topic.weight_min + topic.weight_max


def standing(tally: Tally) -> Standing:
    if tally.answered < MIN_AREA_ANSWERS or tally.percent is None:
        return "insufficient_data"
    if tally.percent >= STRONG_PERCENT:
        return "strength"
    if tally.percent < WEAK_PERCENT:
        return "weakness"
    return "developing"


def tallies(graded: Iterable[Graded], key: dict[int, int]) -> dict[int, Tally]:
    """Tally graded answers by `key[subskill_id]` (identity, skill or domain)."""
    result: dict[int, Tally] = defaultdict(Tally)
    for row in graded:
        group = key[row.subskill_id]
        result[group] = result[group].add(row.is_correct)
    return result


def readiness(
    topics: Sequence[Topic], graded: Sequence[Graded]
) -> tuple[int | None, Readiness]:
    """Accuracy per domain, weighted by exam weight. A domain with no answers counts
    as 0%, because nothing has shown it is known."""
    if not graded:
        return None, "insufficient_data"
    domain_of = {topic.subskill_id: topic.domain_id for topic in topics}
    by_domain = tallies(graded, domain_of)
    weights = {topic.domain_id: weight(topic) for topic in topics}
    # Exact fractions, rounded down once, so a result exactly on a threshold stays on it.
    exact = sum(
        (
            Fraction(weights[domain] * by_domain[domain].correct, tally.answered)
            for domain in weights
            if (tally := by_domain[domain]).answered
        ),
        Fraction(0),
    )
    estimate = math.floor(exact * 100 / sum(weights.values()))
    if len(graded) < MIN_READINESS_ANSWERS or any(
        by_domain[domain].answered < MIN_READINESS_DOMAIN_ANSWERS for domain in weights
    ):
        return estimate, "insufficient_data"
    if estimate >= READY_PERCENT:
        return estimate, "likely_ready"
    return estimate, "borderline" if estimate >= PASS_PERCENT else "not_ready"


def weakness(tally: Tally) -> float:
    """Share wrong, smoothed so an untried objective counts as half known."""
    return (tally.answered - tally.correct + 1) / (tally.answered + 2)


def adaptive_order(
    candidates: Sequence[Candidate],
    by_subskill: dict[int, Tally],
    topic_weights: dict[int, int],
    rng: random.Random,
) -> list[Candidate]:
    """Questions answered wrong last time first, then unseen ones, then ones answered
    right; within each, objectives with the weakest record and heaviest domain first."""

    def tier(candidate: Candidate) -> int:
        if candidate.last_correct is False:
            return 0
        return 1 if candidate.last_correct is None else 2

    shuffled = list(candidates)
    rng.shuffle(shuffled)  # Random among equals; sorting below is stable.
    return sorted(
        shuffled,
        key=lambda c: (
            tier(c),
            -weakness(by_subskill.get(c.subskill_id, Tally()))
            * topic_weights[c.subskill_id],
        ),
    )


def topic_order(candidates: Sequence[Candidate], rng: random.Random) -> list[Candidate]:
    """Unseen questions first, then the rest, each group in random order."""
    shuffled = list(candidates)
    rng.shuffle(shuffled)
    return sorted(shuffled, key=lambda c: c.last_correct is not None)


def allocate(
    available: dict[int, int], weights: dict[int, int], count: int
) -> dict[int, int]:
    """Spread `count` over domains in proportion to exam weight (Sainte-Laguë), skipping
    domains that have run out of questions. Ties go to the earlier domain in `weights`."""
    allocation = {domain: 0 for domain in weights}
    for _ in range(count):
        open_domains = [d for d in weights if allocation[d] < available.get(d, 0)]
        if not open_domains:
            break
        best = max(open_domains, key=lambda d: weights[d] / (allocation[d] + 0.5))
        allocation[best] += 1
    return allocation


def exam_selection(
    candidates: Sequence[Candidate],
    weights: dict[int, int],
    count: int,
    rng: random.Random,
) -> list[Candidate]:
    by_domain: dict[int, list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        by_domain[candidate.domain_id].append(candidate)
    allocation = allocate(
        {d: len(items) for d, items in by_domain.items()}, weights, count
    )
    chosen = [
        item
        for domain, items in by_domain.items()
        for item in topic_order(items, rng)[: allocation.get(domain, 0)]
    ]
    rng.shuffle(chosen)
    return chosen


def recommendations(
    topics: Sequence[Topic],
    by_subskill: dict[int, Tally],
    available: dict[int, int],
) -> list[tuple[Topic, Tally, str]]:
    """Objectives to practise next: tried and weak first, then untried, by exam weight.
    Only objectives that have questions are offered, since nothing else can be practised."""
    ranked = []
    for topic in topics:
        tally = by_subskill.get(topic.subskill_id, Tally())
        if not available.get(topic.subskill_id):
            continue
        if tally.answered and (tally.percent or 0) >= STRONG_PERCENT:
            continue
        reason = "low_accuracy" if tally.answered else "not_attempted"
        ranked.append(
            (
                0 if tally.answered else 1,
                -weakness(tally) * weight(topic),
                topic,
                tally,
                reason,
            )
        )
    ranked.sort(key=lambda row: (row[0], row[1]))
    return [(topic, tally, reason) for _, _, topic, tally, reason in ranked][
        :MAX_RECOMMENDATIONS
    ]
