"""Phase 6: limits on model calls outside question generation."""

import pytest
from conftest import FakeLLM, Learner


def _send(learner: Learner, conversation: int, n: int) -> int:
    return learner.client.post(
        f"/api/conversations/{conversation}/messages",
        json={"content": "What is hybrid search?", "client_message_id": f"m{n}"},
    ).status_code


def test_model_calls_are_limited_per_learner_and_in_total(
    fake_llm: FakeLLM, learner: Learner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_LEARNER_HOURLY_LIMIT", "2")
    monkeypatch.setenv("LLM_HOURLY_LIMIT", "3")
    mine = learner.conversation()
    assert [_send(learner, mine, n) for n in range(2)] == [200, 200]

    refused = learner.client.post(
        f"/api/conversations/{mine}/messages",
        json={"content": "And again?", "client_message_id": "m2"},
    )
    assert refused.status_code == 429
    assert refused.json()["code"] == "llm_rate_limited"
    assert len(fake_llm.requests) == 2  # a refused request never reaches the model
    # Refused requests store nothing.
    messages = learner.ok("GET", f"/api/conversations/{mine}")["messages"]
    assert len(messages) == 4

    # Every model feature shares the learner's allowance.
    assert (
        learner.client.post(
            "/api/sandbox/labs/foundry-setup/assistant",
            json={"question": "Where do I start?"},
        ).status_code
        == 429
    )

    other = Learner()
    theirs = other.conversation()
    assert _send(other, theirs, 0) == 200
    # The global ceiling holds however many learner tokens exist.
    third = Learner()
    response = third.client.post(
        f"/api/conversations/{third.conversation()}/messages",
        json={"content": "Hello?", "client_message_id": "x"},
    )
    assert response.status_code == 429
    assert "hourly limit" in response.json()["detail"]
    assert len(fake_llm.requests) == 3


def test_a_zero_limit_turns_model_features_off(
    fake_llm: FakeLLM, learner: Learner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_LEARNER_HOURLY_LIMIT", "0")
    assert _send(learner, learner.conversation(), 0) == 429
    assert (
        learner.client.post(
            "/api/lessons",
            json={
                "scope_level": "subskill",
                "scope_id": learner.subskill_id(
                    "Select a retrieval and indexing approach"
                ),
                "depth": "beginner",
            },
        ).status_code
        == 429
    )
    assert fake_llm.requests == []


def test_a_bad_limit_falls_back_to_the_default(
    fake_llm: FakeLLM, learner: Learner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_LEARNER_HOURLY_LIMIT", "lots")
    assert _send(learner, learner.conversation(), 0) == 200
