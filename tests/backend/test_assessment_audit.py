"""Phase 4 audit: races, every route's auth, and analytics recounted independently."""

import random
import re
import threading
from collections import defaultdict
from datetime import UTC, datetime
from fractions import Fraction
from typing import Any

import pytest
from conftest import RETRIEVAL_OBJECTIVE, FakeLLM, Learner, load_fixture
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session
from test_assessment import (
    HYBRID,
    KEYWORD,
    LEARN_URL,
    answer,
    answers_by_stem,
    attach_source,
    count,
    explained,
    generate,
    generation_reply,
    mock,
    question,
    seed_bank,
    start,
    verdicts,
)

from app.assessment import generation, scoring, sources
from app.assessment.api import (
    GLOBAL_HOURLY_LIMIT_ENV,
    LEARNER_HOURLY_LIMIT_ENV,
    MAX_ACTIVE_PER_OBJECTIVE,
)
from app.assessment.models import (
    AttemptQuestion,
    ExamAttempt,
    Question,
    QuestionGeneration,
)
from app.learning.retrieval import load_topics
from app.main import app
from app.syllabus.models import SyllabusVersion


def client_for(learner: Learner) -> TestClient:
    client = TestClient(app)
    client.headers["Authorization"] = learner.client.headers["Authorization"]
    return client


def run_together(*actions: Any) -> list[Any]:
    barrier = threading.Barrier(len(actions))
    results: list[Any] = [None] * len(actions)

    def run(index: int, action: Any) -> None:
        barrier.wait()
        results[index] = action()

    threads = [threading.Thread(target=run, args=(i, a)) for i, a in enumerate(actions)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results


# --- Authentication ---


def test_every_api_route_needs_a_learner_token(learner: Learner) -> None:
    """Sweeps the real route table, so a new route can't skip authentication."""
    client = TestClient(app)
    checked = 0
    for route_path, operations in app.openapi()["paths"].items():
        if not route_path.startswith("/api"):
            continue
        path = re.sub(r"\{[^}]+\}", "1", route_path)
        for method in (name.upper() for name in operations):
            if (method, route_path) == ("POST", "/api/learners"):
                continue
            for headers in ({}, {"Authorization": "Bearer forged"}):
                response = client.request(method, path, json={}, headers=headers)
                assert response.status_code == 401, (method, route_path, headers)
            checked += 1
    assert checked >= 20


# --- Races ---


def test_concurrent_identical_starts_create_one_attempt(
    seeded: Engine, learner: Learner
) -> None:
    seed_bank(seeded)
    body = {
        "client_attempt_id": "same",
        "mode": "mock",
        "question_count": 5,
        "time_limit_minutes": 10,
    }
    clients = [client_for(learner) for _ in range(4)]
    responses = run_together(
        *[lambda c=c: c.post("/api/attempts", json=body) for c in clients]
    )
    assert {r.status_code for r in responses} == {201}
    assert len({r.json()["id"] for r in responses}) == 1
    assert count(seeded, ExamAttempt) == 1
    assert count(seeded, AttemptQuestion) == 5


def test_an_answer_racing_submission_never_leaves_a_stale_grade(
    seeded: Engine, learner: Learner
) -> None:
    seed_bank(seeded, per_objective=3)
    key = answers_by_stem(seeded)
    for round_number in range(6):
        exam = mock(learner, f"race{round_number}", questions=5)
        first = exam["items"][0]
        path = f"/api/attempts/{exam['id']}"
        body = {"chosen_index": key[first["stem"]][0]}
        answering, submitting = client_for(learner), client_for(learner)
        put, post = run_together(
            lambda c=answering, p=path, b=body: c.put(f"{p}/answers/1", json=b),
            lambda c=submitting, p=path: c.post(f"{p}/submit"),
        )
        assert put.status_code in (200, 409)
        assert post.status_code == 200
        final = learner.ok("GET", f"/api/attempts/{exam['id']}")
        for item in final["items"]:
            feedback = item["feedback"]
            assert feedback["is_correct"] == (
                item["chosen_index"] == feedback["correct_index"]
            )
        assert final["score"] == sum(
            i["feedback"]["is_correct"] for i in final["items"]
        )
        # The answer counts if and only if it was accepted before grading.
        assert (final["items"][0]["chosen_index"] is not None) == (
            put.status_code == 200
        )


def test_racing_practice_answers_keep_the_first(
    seeded: Engine, learner: Learner
) -> None:
    seed_bank(seeded)
    quiz = start(learner, "p", mode="practice", adaptive=True, question_count=2)
    clients = [client_for(learner) for _ in range(2)]
    responses = run_together(
        *[
            lambda c=c, choice=choice: c.put(
                f"/api/attempts/{quiz['id']}/answers/1", json={"chosen_index": choice}
            )
            for c, choice in zip(clients, (0, 1), strict=True)
        ]
    )
    assert sorted(r.status_code for r in responses) == [200, 409]
    winner = next(r for r in responses if r.status_code == 200).json()
    stored = learner.ok("GET", f"/api/attempts/{quiz['id']}")["items"][0]
    assert stored["chosen_index"] == winner["items"][0]["chosen_index"]


# --- Analytics, recounted without the scoring module ---


def syllabus_maps(
    learner: Learner,
) -> tuple[dict[int, int], dict[int, int], dict[int, int]]:
    domain_of: dict[int, int] = {}
    skill_of: dict[int, int] = {}
    weight: dict[int, int] = {}
    for domain in learner.syllabus()["domains"]:
        weight[domain["id"]] = domain["weight_min"] + domain["weight_max"]
        for skill in domain["skills"]:
            for subskill in skill["subskills"]:
                domain_of[subskill["id"]] = domain["id"]
                skill_of[subskill["id"]] = skill["id"]
    return domain_of, skill_of, weight


def test_analytics_match_an_independent_recount(
    seeded: Engine, learner: Learner
) -> None:
    seed_bank(seeded, per_objective=3)
    key = answers_by_stem(seeded)
    domain_of, skill_of, weight = syllabus_maps(learner)
    rng = random.Random(20261108)
    graded: list[tuple[int, bool]] = []  # (subskill, correct), from what we sent

    def choose(stem: str, right_share: float) -> tuple[int, bool]:
        correct = key[stem][0]
        right = rng.random() < right_share
        return (correct if right else (correct + 1) % 4), right

    # Practice: answered questions count; the ones left before finishing don't.
    for number in range(3):
        quiz = start(
            learner, f"p{number}", mode="practice", adaptive=True, question_count=12
        )
        for item in quiz["items"][:9]:
            chosen, right = choose(item["stem"], 0.65)
            assert (
                answer(learner, quiz["id"], item["position"], chosen).status_code == 200
            )
            graded.append((key[item["stem"]][1], right))
        learner.ok("POST", f"/api/attempts/{quiz['id']}/submit")

    # Mock: unanswered questions count as wrong.
    exam = mock(learner, "m", questions=20)
    for item in exam["items"]:
        if rng.random() < 0.8:
            chosen, right = choose(item["stem"], 0.75)
            answer(learner, exam["id"], item["position"], chosen)
        else:
            right = False
        graded.append((key[item["stem"]][1], right))
    learner.ok("POST", f"/api/attempts/{exam['id']}/submit")

    analytics = learner.ok("GET", "/api/analytics")
    assert analytics["answered"] == len(graded)
    assert analytics["correct"] == sum(right for _, right in graded)

    by_domain: dict[int, list[bool]] = defaultdict(list)
    by_skill: dict[int, list[bool]] = defaultdict(list)
    for subskill, right in graded:
        by_domain[domain_of[subskill]].append(right)
        by_skill[skill_of[subskill]].append(right)
    for row in analytics["domains"]:
        results = by_domain[row["domain_id"]]
        assert (row["answered"], row["correct"]) == (len(results), sum(results))
    for row in analytics["skills"]:
        results = by_skill[row["skill_id"]]
        assert (row["answered"], row["correct"]) == (len(results), sum(results))

    # Readiness: exact weighted accuracy, untried domains at zero, floored once.
    exact = (
        sum(
            (Fraction(weight[d] * sum(r), len(r)) for d, r in by_domain.items() if r),
            Fraction(0),
        )
        * 100
        / sum(weight.values())
    )
    assert analytics["readiness_percent"] == int(exact)
    enough = len(graded) >= 20 and all(len(by_domain[d]) >= 3 for d in weight)
    expected = (
        "insufficient_data"
        if not enough
        else "likely_ready"
        if exact >= 80
        else "borderline"
        if exact >= 70
        else "not_ready"
    )
    assert analytics["readiness"] == expected
    [mock_summary] = [a for a in analytics["attempts"] if a["mode"] == "mock"]
    mock_rights = sum(right for _, right in graded[-20:])
    assert (mock_summary["score"], mock_summary["percent"]) == (
        mock_rights,
        mock_rights * 5,
    )


def test_adaptive_order_follows_each_questions_last_result(
    seeded: Engine, learner: Learner
) -> None:
    seed_bank(seeded, per_objective=2)
    key = answers_by_stem(seeded)
    rng = random.Random(7)
    last: dict[str, bool] = {}
    for number in range(2):
        quiz = start(
            learner, f"h{number}", mode="practice", adaptive=True, question_count=10
        )
        for item in quiz["items"]:
            correct = key[item["stem"]][0]
            right = rng.random() < 0.5
            answer(
                learner,
                quiz["id"],
                item["position"],
                correct if right else (correct + 1) % 4,
            )
            last[item["stem"]] = right

    adaptive = start(learner, "all", mode="practice", adaptive=True, question_count=60)
    tiers = [
        0 if last.get(item["stem"]) is False else 1 if item["stem"] not in last else 2
        for item in adaptive["items"]
    ]
    assert len(tiers) == len(key)
    assert tiers == sorted(tiers)
    assert tiers.count(0) == sum(not right for right in last.values())


def test_readiness_matches_exact_weighted_accuracy(seeded: Engine) -> None:
    """Regression: per-domain rounding could put a score on a threshold just below it."""
    with Session(seeded) as session:
        topics = load_topics(session, session.scalars(select(SyllabusVersion)).one().id)
    first_of = {}
    weight = {}
    for topic in topics:
        first_of.setdefault(topic.domain_id, topic.subskill_id)
        weight[topic.domain_id] = scoring.weight(topic)
    rng = random.Random(3)
    for _ in range(300):
        graded = [
            scoring.Graded(first_of[d], rng.random() < 0.7)
            for d in weight
            for _ in range(rng.randint(0, 9))
        ]
        if not graded:
            continue
        by_domain: dict[int, list[bool]] = defaultdict(list)
        for row in graded:
            by_domain[
                next(d for d, s in first_of.items() if s == row.subskill_id)
            ].append(row.is_correct)
        exact = (
            sum(
                (Fraction(weight[d] * sum(r), len(r)) for d, r in by_domain.items()),
                Fraction(0),
            )
            * 100
            / sum(weight.values())
        )
        assert scoring.readiness(topics, graded)[0] == int(exact)


# --- Generation: grounding fixes ---


def learn_source() -> generation.SourceText:
    title, content = sources.extract_text(load_fixture("learn_retrieval.html"))
    return generation.SourceText(1, title, LEARN_URL, content)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        # Regression: the excerpt proved a distractor, and the wrong answer was kept.
        ({"source_excerpt": KEYWORD}, "answer_not_in_excerpt"),
        # Regression: the only shared word was one every option has.
        (
            {
                "source_excerpt": "Vector search finds content by meaning: text is converted into embeddings"
            },
            "answer_not_in_excerpt",
        ),
        # Regression: lax parsing read true and "0" as answer indexes.
        ({"correct_index": True}, "invalid_shape"),
        ({"correct_index": "0"}, "invalid_shape"),
        ({"source_number": "1"}, "invalid_shape"),
        (
            {
                "options": [
                    "Hybrid search",
                    "A and B",
                    "Vector search",
                    "Keyword search",
                ]
            },
            "ambiguous_option",
        ),
        (
            {
                "options": [
                    "Hybrid search",
                    "Options 1 or 2",
                    "Vector search",
                    "Keyword search",
                ]
            },
            "ambiguous_option",
        ),
    ],
)
def test_weak_evidence_and_loose_fields_are_rejected(
    changes: dict[str, Any], reason: str
) -> None:
    accepted, rejected = generation.check_candidate(
        question(**changes),
        "mcq",
        [learn_source()],
        generation.Existing(frozenset(), ()),
    )
    assert accepted is None
    assert rejected is not None and rejected.reason == reason


def test_answer_specific_evidence_still_passes() -> None:
    accepted, _ = generation.check_candidate(
        question(source_excerpt=HYBRID),
        "mcq",
        [learn_source()],
        generation.Existing(frozenset(), ()),
    )
    assert accepted is not None


@pytest.fixture
def objective(seeded: Engine, learner: Learner) -> int:
    subskill_id = learner.subskill_id(RETRIEVAL_OBJECTIVE)
    attach_source(seeded, subskill_id)
    return subskill_id


def test_unsupported_explanations_are_rejected(
    seeded: Engine, learner: Learner, fake_llm: FakeLLM, objective: int
) -> None:
    """Regression: explanations were never checked against the source."""
    invented = "Hybrid search is free in every region and has no query limits at all."
    fake_llm.replies = [
        generation_reply(question(explanation=invented)),
        verdicts(0),
        explained(False),
    ]
    result = generate(learner, objective, count=1).json()
    assert result["accepted"] == 0
    assert [r["reason"] for r in result["rejected"]] == ["explanation_unsupported"]
    assert count(seeded, Question) == 0
    audit = fake_llm.requests[2]
    assert "every factual claim" in audit[0]["content"]
    assert invented in audit[1]["content"]
    assert HYBRID in audit[1]["content"]


def test_unreadable_explanation_verdict_stores_nothing(
    seeded: Engine, learner: Learner, fake_llm: FakeLLM, objective: int
) -> None:
    fake_llm.replies = [generation_reply(question()), verdicts(0), "nope", "still nope"]
    response = generate(learner, objective, count=1)
    assert (response.status_code, response.json()["code"]) == (
        502,
        "llm_invalid_output",
    )
    assert count(seeded, Question) == 0
    with Session(seeded) as session:
        assert session.scalars(select(QuestionGeneration.status)).all() == ["failed"]


def test_prompt_uses_at_most_the_newest_sources(
    seeded: Engine, learner: Learner, fake_llm: FakeLLM
) -> None:
    subskill = learner.subskill_id(RETRIEVAL_OBJECTIVE)
    page = load_fixture("learn_retrieval.html")
    for number in range(generation.MAX_SOURCES + 1):
        title, content = sources.extract_text(
            page.replace("<h1>", f"<h1>Page {number} ")
        )
        with Session(seeded) as session, session.begin():
            sources.store_source(
                session,
                f"{LEARN_URL}/{number}",
                title,
                content,
                [subskill],
                datetime.now(UTC),
            )
    fake_llm.default_reply = "not json"
    generate(learner, subskill)
    prompt = fake_llm.requests[0][-1]["content"]
    assert "Page 0" not in prompt
    assert all(f"Page {n}" in prompt for n in range(1, generation.MAX_SOURCES + 1))


# --- Generation: cost limits ---


def test_generation_is_limited_per_learner(
    seeded: Engine,
    learner: Learner,
    fake_llm: FakeLLM,
    objective: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: any learner could call the model without limit."""
    monkeypatch.setenv(LEARNER_HOURLY_LIMIT_ENV, "2")
    fake_llm.default_reply = "not json"  # Each allowed call fails, and still counts.
    assert [generate(learner, objective).status_code for _ in range(2)] == [502, 502]
    calls = len(fake_llm.requests)

    refused = generate(learner, objective)
    assert refused.status_code == 429
    assert refused.headers["Retry-After"] == "3600"
    assert "2 times an hour" in refused.json()["detail"]
    assert len(fake_llm.requests) == calls  # Refused before the model was called.
    assert generate(learner, objective).status_code == 429
    with Session(seeded) as session:
        statuses = session.scalars(
            select(QuestionGeneration.status).order_by(QuestionGeneration.id)
        ).all()
    assert statuses == ["failed", "failed", "refused", "refused"]

    # Refused requests don't use up anyone's allowance; another learner can go on.
    fake_llm.replies = [generation_reply(question()), verdicts(0), explained(True)]
    assert generate(Learner(), objective).json()["accepted"] == 1


def test_generation_has_a_global_limit_and_an_off_switch(
    learner: Learner,
    fake_llm: FakeLLM,
    objective: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(GLOBAL_HOURLY_LIMIT_ENV, "2")
    fake_llm.default_reply = "not json"
    others = [Learner() for _ in range(3)]
    statuses = [generate(other, objective).status_code for other in others]
    assert statuses == [502, 502, 429]
    assert "hourly limit" in generate(learner, objective).json()["detail"]

    monkeypatch.setenv(GLOBAL_HOURLY_LIMIT_ENV, "0")
    calls = len(fake_llm.requests)
    assert generate(Learner(), objective).status_code == 429
    assert len(fake_llm.requests) == calls


def test_an_objective_bank_is_capped(
    seeded: Engine, learner: Learner, fake_llm: FakeLLM, objective: int
) -> None:
    seed_bank(seeded, per_objective=MAX_ACTIVE_PER_OBJECTIVE)
    response = generate(learner, objective)
    assert response.status_code == 409
    assert fake_llm.requests == []
