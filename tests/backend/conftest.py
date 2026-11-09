import json
import os
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, make_url
from sqlalchemy.orm import Session

import app.assessment.models
import app.learning.models
from app.db import get_session
from app.learning import llm
from app.main import app
from app.syllabus.ingest import store_syllabus
from app.syllabus.models import Base
from app.syllabus.parser import parse_syllabus

BACKEND_DIR = Path(__file__).parents[2] / "backend"
FIXTURES_DIR = Path(__file__).parent / "fixtures"
URL = "https://example.test/ai-103"
T0 = datetime(2026, 11, 1, tzinfo=UTC)
RETRIEVAL_OBJECTIVE = "Select a retrieval and indexing approach"

_OFFICIAL_SHAPE = (
    ("25–30%", (4, 4, 4, 4)),
    ("30–35%", (6, 6, 4)),
    ("10–15%", (5, 8, 3)),
    ("10–15%", (4, 4)),
    ("10–15%", (5, 3)),
)
LAST_SKILL_HEADING = "<h4>Skill 5.2</h4>"


def load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def official_shape_page() -> str:
    """Placeholder text in the live page's shape: 5 domains, 14 skills, 64 subskills."""
    glance = []
    domains = []
    for domain, (weight, skills) in enumerate(_OFFICIAL_SHAPE, 1):
        heading = f"Domain {domain} ({weight})"
        glance.append(f"<li><p>{heading}</p></li>")
        domains.append(f"<h3>{heading}</h3>")
        for skill, subskills in enumerate(skills, 1):
            items = "".join(
                f"<li><p>Subskill {domain}.{skill}.{item}</p></li>"
                for item in range(1, subskills + 1)
            )
            domains.append(f"<h4>Skill {domain}.{skill}</h4><ul>{items}</ul>")
    return f"""<!DOCTYPE html><html lang="en-us"><body><main>
<h1>Study guide for Exam AI-103</h1>
<h2>Skills measured as of April 16, 2026</h2>
<h3>Audience profile</h3><p>You build agents.</p>
<h3>Skills at a glance</h3><ul>{"".join(glance)}</ul>
{"".join(domains)}
<h2>Study resources</h2><p>We recommend hands-on experience.</p>
<table><tr><td>Get trained</td></tr></table>
<h2 hidden>Additional resources</h2><ul><li>Last updated on 2026-10-31</li></ul>
</main></body></html>"""


def last_skill_list_after(page: str, headings: str) -> str:
    """Replace the last skill's heading, leaving its list stranded after other headings."""
    start = page.index(LAST_SKILL_HEADING)
    return page[:start] + headings + page[start + len(LAST_SKILL_HEADING) :]


def alembic_config(database_url: str) -> Config:
    config = Config(toml_file=str(BACKEND_DIR / "pyproject.toml"))
    config.attributes["database_url"] = database_url
    return config


def postgres_test_url() -> str | None:
    """A disposable Postgres to migrate and wipe. Never falls back to DATABASE_URL."""
    url = os.environ.get("TEST_DATABASE_URL")
    if url and not (make_url(url).database or "").endswith("_test"):
        pytest.fail("TEST_DATABASE_URL must name a database ending in _test")
    return url


@pytest.fixture
def baseline_html() -> str:
    return load_fixture("ai103_baseline.html")


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    """Postgres through the real migration if configured, otherwise SQLite."""
    url = postgres_test_url()
    if url:
        config = alembic_config(url)
        command.upgrade(config, "head")
        engine = create_engine(url)
        yield engine
        engine.dispose()
        command.downgrade(config, "base")
    else:
        engine = create_engine(f"sqlite:///{tmp_path / 'syllabus.db'}")
        Base.metadata.create_all(engine)
        yield engine
        engine.dispose()


# --- Fakes and fixtures ---


@dataclass
class FakeLLM:
    url: str = ""
    replies: list[str] = field(default_factory=list)
    default_reply: str = "A tutor explanation [1]."
    fail_status: int | None = None
    requests: list[list[dict[str, str]]] = field(default_factory=list)

    @property
    def last_prompt(self) -> str:
        return self.requests[-1][-1]["content"]


class _LLMHandler(BaseHTTPRequestHandler):
    fake: FakeLLM

    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.fake.requests.append(body["messages"])
        if self.fake.fail_status:
            self.send_response(self.fake.fail_status)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        reply = (
            self.fake.replies.pop(0) if self.fake.replies else self.fake.default_reply
        )
        payload = json.dumps(
            {
                "id": "x",
                "object": "chat.completion",
                "created": 0,
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": reply},
                    }
                ],
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeLLM]:
    fake = FakeLLM()
    handler = type("Handler", (_LLMHandler,), {"fake": fake})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    fake.url = f"http://127.0.0.1:{server.server_port}/v1"
    monkeypatch.setenv("LLM_BASE_URL", fake.url)
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "fake-model")
    yield fake
    server.shutdown()
    server.server_close()


def use_engine(engine: Engine) -> None:
    def session() -> Iterator[Session]:
        with Session(engine, expire_on_commit=False) as value:
            yield value

    app.dependency_overrides[get_session] = session


@pytest.fixture
def seeded(engine: Engine, baseline_html: str) -> Engine:
    ingest_html(engine, baseline_html)
    return engine


def ingest_html(engine: Engine, html: str) -> None:
    with Session(engine) as session, session.begin():
        store_syllabus(session, parse_syllabus(html), URL, T0)


@pytest.fixture(autouse=True)
def clear_overrides() -> Iterator[None]:
    llm.reset_limits()
    yield
    app.dependency_overrides.clear()


class Learner:
    """One browser: a client that sends one learner's token."""

    def __init__(self) -> None:
        self.client = TestClient(app)
        token = self.client.post("/api/learners").json()["token"]
        self.client.headers["Authorization"] = f"Bearer {token}"

    def ok(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.client.request(method, path, **kwargs)
        assert response.status_code < 300, response.text
        return response.json()

    def syllabus(self) -> dict[str, Any]:
        result: dict[str, Any] = self.ok("GET", "/api/syllabus")
        return result

    def subskill_id(self, text: str) -> int:
        for domain in self.syllabus()["domains"]:
            for skill in domain["skills"]:
                for subskill in skill["subskills"]:
                    if subskill["text"] == text:
                        return int(subskill["id"])
        raise AssertionError(f"no subskill {text!r}")

    def skill_ids(self) -> dict[str, int]:
        return {
            skill["name"]: skill["id"]
            for domain in self.syllabus()["domains"]
            for skill in domain["skills"]
        }

    def open_lesson(
        self, text: str = RETRIEVAL_OBJECTIVE, depth: str = "beginner"
    ) -> Any:
        return self.ok(
            "POST",
            "/api/lessons",
            json={
                "scope_level": "subskill",
                "scope_id": self.subskill_id(text),
                "depth": depth,
            },
        )

    def complete(self, lesson_id: int) -> Any:
        return self.ok(
            "PUT", f"/api/lessons/{lesson_id}/progress", json={"status": "completed"}
        )

    def conversation(self, **kwargs: Any) -> int:
        return int(self.ok("POST", "/api/conversations", json=kwargs)["id"])

    def send(self, conversation: int, content: str, message_id: str = "m1") -> Any:
        return self.ok(
            "POST",
            f"/api/conversations/{conversation}/messages",
            json={"content": content, "client_message_id": message_id},
        )


@pytest.fixture
def learner(seeded: Engine) -> Learner:
    use_engine(seeded)
    return Learner()
