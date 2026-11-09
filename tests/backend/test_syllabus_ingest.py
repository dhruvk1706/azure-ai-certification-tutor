import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import astuple
from datetime import UTC, date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, unquote

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from conftest import (
    LAST_SKILL_HEADING,
    alembic_config,
    last_skill_list_after,
    load_fixture,
    official_shape_page,
    postgres_test_url,
)
from sqlalchemy import Engine, create_engine, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.syllabus import ingest
from app.syllabus.diff import Change, diff_syllabi
from app.syllabus.ingest import fetch_html, run_ingestion, store_syllabus
from app.syllabus.models import (
    Base,
    SyllabusChange,
    SyllabusDomain,
    SyllabusSkill,
    SyllabusSubskill,
    SyllabusVersion,
)
from app.syllabus.parser import SyllabusError, content_hash, parse_syllabus

URL = "https://example.test/ai-103"
T0 = datetime(2026, 11, 1, tzinfo=UTC)
TABLES = [
    SyllabusVersion,
    SyllabusDomain,
    SyllabusSkill,
    SyllabusSubskill,
    SyllabusChange,
]


def ingest_fixture(
    engine: Engine, html: str, at: datetime = T0
) -> ingest.IngestionResult:
    with Session(engine) as session, session.begin():
        return store_syllabus(session, parse_syllabus(html), URL, at)


def snapshot(engine: Engine) -> list[list[tuple[object, ...]]]:
    """Every row of every syllabus table, to prove a failure changed nothing."""
    with engine.connect() as connection:
        return [
            sorted(tuple(row) for row in connection.execute(select(model.__table__)))
            for model in TABLES
        ]


def as_utc(value: datetime) -> datetime:
    """SQLite drops the zone. Postgres keeps the instant, in the session's zone."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def versions(session: Session) -> list[SyllabusVersion]:
    return list(
        session.scalars(
            select(SyllabusVersion).order_by(SyllabusVersion.version_number)
        )
    )


# --- First ingestion ---


def test_first_ingestion_stores_hierarchy_and_provenance(
    engine: Engine, baseline_html: str
) -> None:
    result = ingest_fixture(engine, baseline_html)
    assert (result.status, result.version_number, result.changes) == ("created", 1, [])

    with Session(engine) as session:
        version = session.scalars(select(SyllabusVersion)).one()
        assert version.exam_code == "AI-103"
        assert version.source_url == URL
        assert as_utc(version.retrieved_at) == T0
        assert version.effective_date == date(2026, 4, 16)
        assert version.content_hash == content_hash(parse_syllabus(baseline_html))
        assert version.changes == []

        assert [d.position for d in version.domains] == [1, 2, 3, 4, 5]
        assert (version.domains[0].weight_min, version.domains[0].weight_max) == (
            25,
            30,
        )
        skill = version.domains[0].skills[1]
        assert (skill.position, skill.name) == (2, "Secure and monitor AI workloads")
        first = skill.subskills[0]
        assert (first.position, first.text) == (
            1,
            "Track quota, scaling, and spend for deployed models",
        )
        assert session.scalar(select(func.count()).select_from(SyllabusSubskill)) == 18


def test_stored_version_round_trips_to_the_same_hash(
    engine: Engine, baseline_html: str
) -> None:
    ingest_fixture(engine, baseline_html)
    with Session(engine) as session:
        version = session.scalars(select(SyllabusVersion)).one()
        assert ingest._to_syllabus(version) == parse_syllabus(baseline_html)


# --- Unchanged content ---


@pytest.mark.parametrize("fixture", ["ai103_baseline.html", "ai103_html_churn.html"])
def test_unchanged_content_creates_no_new_version(
    engine: Engine, baseline_html: str, fixture: str
) -> None:
    ingest_fixture(engine, baseline_html)
    before = snapshot(engine)

    later = T0 + timedelta(days=7)
    result = ingest_fixture(engine, load_fixture(fixture), later)

    assert (result.status, result.version_number) == ("unchanged", 1)
    with Session(engine) as session:
        version = session.scalars(select(SyllabusVersion)).one()
        assert as_utc(version.retrieved_at) == T0
        assert as_utc(version.last_checked_at) == later
    # Everything except the version row's last_checked_at is byte-identical.
    assert snapshot(engine)[1:] == before[1:]


# --- Modified content ---

D1 = "Plan and manage an Azure AI solution"
D2 = "Implement generative AI and agentic solutions"
D3 = "Implement computer vision solutions"
D4 = "Implement text analysis solutions"
S1 = "Select Foundry services"
S2 = "Secure and monitor AI workloads"
EXPECTED_CHANGES = [
    Change("syllabus", "modified", old_value="2026-04-16", new_value="2026-07-01"),
    Change(
        "domain",
        "modified",
        D1,
        old_value={"name": D1, "weight_min": 25, "weight_max": 30},
        new_value={"name": D1, "weight_min": 20, "weight_max": 25},
    ),
    Change(
        "subskill",
        "modified",
        D1,
        S1,
        "Pick a model that fits each workload",
        "Pick a model that fits each workload and budget",
    ),
    Change(
        "subskill",
        "removed",
        D1,
        S2,
        old_value="Watch for drift and safety events in production",
    ),
    Change(
        "subskill", "added", D1, S2, new_value="Review trace logs as audit evidence"
    ),
    Change(
        "domain",
        "modified",
        D2,
        old_value={"name": D2, "weight_min": 30, "weight_max": 35},
        new_value={"name": D2, "weight_min": 35, "weight_max": 40},
    ),
    Change(
        "skill",
        "modified",
        D2,
        old_value="Create agents",
        new_value="Create and run agents",
    ),
    Change("skill", "added", D3, new_value="Block unsafe visuals"),
    Change(
        "subskill",
        "added",
        D3,
        "Block unsafe visuals",
        new_value="Stop disallowed pictures from reaching users",
    ),
    Change("skill", "removed", D4, old_value="Add speech capabilities"),
    Change(
        "subskill",
        "removed",
        D4,
        "Add speech capabilities",
        old_value="Convert between speech and text in agent conversations",
    ),
]


def test_diff_reports_every_kind_of_change(baseline_html: str) -> None:
    changes = diff_syllabi(
        parse_syllabus(baseline_html),
        parse_syllabus(load_fixture("ai103_modified.html")),
    )
    assert changes == EXPECTED_CHANGES


def test_modified_content_creates_version_and_preserves_history(
    engine: Engine, baseline_html: str
) -> None:
    ingest_fixture(engine, baseline_html)
    v1_rows = snapshot(engine)
    modified = load_fixture("ai103_modified.html")

    later = T0 + timedelta(days=30)
    result = ingest_fixture(engine, modified, later)
    assert (result.status, result.version_number) == ("created", 2)

    with Session(engine) as session:
        v1, v2 = versions(session)
        # The previous version still rebuilds exactly as it was first stored.
        assert ingest._to_syllabus(v1) == parse_syllabus(baseline_html)
        assert ingest._to_syllabus(v2) == parse_syllabus(modified)
        assert v1.content_hash != v2.content_hash
        assert as_utc(v2.retrieved_at) == later
        assert v2.effective_date == date(2026, 7, 1)
        stored = [
            Change(
                c.level,  # type: ignore[arg-type]
                c.change_type,  # type: ignore[arg-type]
                c.domain_name,
                c.skill_name,
                c.old_value,
                c.new_value,
            )
            for c in v2.changes
        ]
        assert stored == EXPECTED_CHANGES
        assert v1.changes == []

    # Rows belonging to version 1 are untouched.
    for before, after in zip(v1_rows, snapshot(engine), strict=True):
        assert {repr(row) for row in before} <= {repr(row) for row in after}


def test_reverted_content_is_recorded_as_a_new_version(
    engine: Engine, baseline_html: str
) -> None:
    ingest_fixture(engine, baseline_html)
    ingest_fixture(engine, load_fixture("ai103_modified.html"))
    result = ingest_fixture(engine, baseline_html)

    assert (result.status, result.version_number) == ("created", 3)
    with Session(engine) as session:
        v1, _, v3 = versions(session)
        assert v1.content_hash == v3.content_hash
        assert v3.changes


def test_reorder_only_change_is_detected(engine: Engine, baseline_html: str) -> None:
    first = "Produce images from prompts"
    second = "Apply mask‑based edits to generated images"
    swapped = (
        baseline_html.replace(first, "@@").replace(second, first).replace("@@", second)
    )
    ingest_fixture(engine, baseline_html)
    result = ingest_fixture(engine, swapped)

    assert result.status == "created"
    assert [astuple(c)[:2] for c in result.changes] == [("subskill", "reordered")]
    assert (
        result.changes[0].new_value[0] == "Apply mask-based edits to generated images"
    )


def test_added_and_removed_domains_report_their_children(baseline_html: str) -> None:
    old = parse_syllabus(baseline_html)
    renamed = baseline_html.replace(
        "Implement text analysis solutions", "Completely different area of study"
    )
    changes = diff_syllabi(old, parse_syllabus(renamed))
    kinds = {(c.level, c.change_type) for c in changes}
    assert kinds == {
        ("domain", "removed"),
        ("domain", "added"),
        ("skill", "removed"),
        ("skill", "added"),
        ("subskill", "removed"),
        ("subskill", "added"),
    }


def test_every_hash_change_has_a_recorded_difference(baseline_html: str) -> None:
    """A new version must always be explainable."""
    old = parse_syllabus(baseline_html)
    for edit in [("(10–15%)", "(11–15%)"), ("Create agents", "Build agents")]:
        new = parse_syllabus(baseline_html.replace(*edit))
        assert content_hash(old) != content_hash(new)
        assert diff_syllabi(old, new)


# --- Failure handling ---

# The reported truncation: the baseline fixture cut at the first point that used to
# parse as a complete five-domain syllabus, silently missing 2 of its 18 subskills.
ADVERTISED = 5414
DELIVERED = 4502
TRUNCATED_RESPONSES = [
    "advertised-5414-delivered-4502",
    "truncated",
    "invalid-length",
    "chunked-closed-early",
    "no-length-closed-early",
    "short-length/05414",
    f"short-length/{quote('5414, 5414')}",
    # The client stops at the advertised length, so the parser must catch these.
    "length/04502",
    "length/00",
]


class _FakeLearn(BaseHTTPRequestHandler):
    baseline = ""

    def log_message(self, format: str, *args: object) -> None:
        pass

    def _send(
        self,
        status: int,
        content_type: str,
        body: bytes,
        length: int | str | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body) if length is None else length))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        html = "text/html; charset=utf-8"
        if self.path == "/ok":
            self._send(200, html, self.baseline.encode())
        elif self.path == "/modified":
            self._send(200, html, load_fixture("ai103_modified.html").encode())
        elif self.path == "/slow":
            time.sleep(0.5)
            self._send(200, html, self.baseline.encode())
        elif self.path == "/500":
            self._send(500, html, b"oops")
        elif self.path == "/404":
            self._send(404, html, b"gone")
        elif self.path == "/json":
            self._send(200, "application/json", b"{}")
        elif self.path == "/truncated":
            self._send(200, html, b"<html>", length=100000)
        elif self.path == "/advertised-5414-delivered-4502":
            self._send(200, html, self.baseline.encode()[:DELIVERED], length=ADVERTISED)
        elif self.path == "/invalid-length":
            self._send(200, html, self.baseline.encode(), length="not-a-number")
        elif self.path == "/no-length-closed-early":
            self.send_response(200)
            self.send_header("Content-Type", html)
            self.end_headers()
            self.wfile.write(self.baseline.encode()[:DELIVERED])
        elif self.path == "/chunked-closed-early":
            chunk = self.baseline.encode()[:DELIVERED]
            self.send_response(200)
            self.send_header("Content-Type", html)
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
        elif self.path.startswith(("/length/", "/short-length/")):
            # Path carries the raw header value, with "|" separating repeated headers.
            kind, _, values = self.path[1:].partition("/")
            body = self.baseline.encode()
            self.send_response(200)
            self.send_header("Content-Type", html)
            for value in unquote(values).split("|"):
                self.send_header("Content-Length", value)
            self.end_headers()
            self.wfile.write(body[:DELIVERED] if kind == "short-length" else body)
        elif self.path == "/bad-encoding":
            self._send(200, html, b"\xff\xfe\xfa")
        elif self.path == "/empty":
            self._send(200, html, b"")
        elif self.path == "/redesign":
            self._send(
                200, html, b'<html lang="en-us"><main><h1>AI-103</h1></main></html>'
            )


@pytest.fixture
def learn(baseline_html: str) -> Iterator[str]:
    _FakeLearn.baseline = baseline_html
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeLearn)
    # The timeout test disconnects mid-response, which the server would print as an error.
    server.handle_error = lambda *_: None  # type: ignore[method-assign]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def test_run_ingestion_fetches_and_stores(engine: Engine, learn: str) -> None:
    assert run_ingestion(engine, f"{learn}/ok").status == "created"
    assert run_ingestion(engine, f"{learn}/ok").status == "unchanged"
    assert run_ingestion(engine, f"{learn}/modified").version_number == 2


@pytest.mark.parametrize(
    "path",
    ["500", "404", "json", "truncated", "bad-encoding", "empty", "redesign"],
)
def test_failures_leave_existing_data_untouched(
    engine: Engine, learn: str, path: str
) -> None:
    run_ingestion(engine, f"{learn}/ok")
    before = snapshot(engine)

    with pytest.raises(SyllabusError):
        run_ingestion(engine, f"{learn}/{path}")

    assert snapshot(engine) == before


def test_content_length_mismatch_is_reported_with_both_sizes(
    learn: str, baseline_html: str
) -> None:
    assert len(baseline_html.encode()) == ADVERTISED
    with pytest.raises(SyllabusError, match="Content-Length 5414, received 4502 bytes"):
        fetch_html(f"{learn}/advertised-5414-delivered-4502")


@pytest.mark.parametrize(
    "value",
    [
        "5414",
        "05414",
        "0000005414",
        " 05414 ",
        "5414, 5414",
        "05414,5414",
        "5414|05414",
    ],
)
def test_valid_content_length_is_accepted(
    learn: str, baseline_html: str, value: str
) -> None:
    assert fetch_html(f"{learn}/length/{quote(value)}") == baseline_html


def test_leading_zero_content_length_ingests_as_the_same_version(
    engine: Engine, learn: str
) -> None:
    assert run_ingestion(engine, f"{learn}/length/05414").status == "created"
    assert run_ingestion(engine, f"{learn}/ok").status == "unchanged"


@pytest.mark.parametrize(
    "value",
    [
        "+5414",
        "-5414",
        "5_414",
        "5414.0",
        "0x1526",
        "not-a-number",
        "",
        "5414,",
        ",5414",
        "5414 5414",
        "5414\N{SUPERSCRIPT TWO}",
        pytest.param("1" * 5000, id="too-many-digits-for-int"),
    ],
)
def test_malformed_content_length_is_rejected(learn: str, value: str) -> None:
    with pytest.raises(SyllabusError, match="malformed Content-Length"):
        fetch_html(f"{learn}/length/{quote(value)}")


@pytest.mark.parametrize(
    "value", ["5414, 4502", "5414,05415", "5414|4502", "4502|5414"]
)
def test_conflicting_content_length_is_rejected(learn: str, value: str) -> None:
    with pytest.raises(SyllabusError, match="conflicting Content-Length"):
        fetch_html(f"{learn}/length/{quote(value)}")


@pytest.mark.parametrize("value", ["5415", "05415", "5415, 5415", "5415|05415"])
def test_mismatched_content_length_is_rejected(learn: str, value: str) -> None:
    with pytest.raises(SyllabusError, match="Content-Length 5415, received 5414 bytes"):
        fetch_html(f"{learn}/length/{quote(value)}")


def test_leading_zero_content_length_still_detects_truncation(learn: str) -> None:
    with pytest.raises(SyllabusError, match="Content-Length 5414, received 4502 bytes"):
        fetch_html(f"{learn}/short-length/05414")


@pytest.mark.parametrize(
    "path",
    [
        "advertised-5414-delivered-4502",
        "truncated",
        "invalid-length",
        "chunked-closed-early",
        "short-length/05414",
        f"short-length/{quote('5414, 5414')}",
    ],
)
def test_incomplete_response_is_rejected_before_parsing_or_database(
    engine: Engine, learn: str, path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def must_not_run(*_: object) -> None:
        raise AssertionError("reached a step that must not run")

    monkeypatch.setattr(ingest, "parse_syllabus", must_not_run)
    monkeypatch.setattr(ingest, "Session", must_not_run)

    with pytest.raises(SyllabusError):
        run_ingestion(engine, f"{learn}/{path}")


def test_truncation_without_content_length_never_reaches_database(
    engine: Engine, learn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HTTP cannot see this one, so the parser's structural checks must."""

    def must_not_run(*_: object) -> None:
        raise AssertionError("opened a database session")

    monkeypatch.setattr(ingest, "Session", must_not_run)
    with pytest.raises(SyllabusError, match="never closed"):
        run_ingestion(engine, f"{learn}/no-length-closed-early")


@pytest.mark.parametrize("path", TRUNCATED_RESPONSES)
def test_truncation_creates_no_first_version(
    engine: Engine, learn: str, path: str
) -> None:
    with pytest.raises(SyllabusError):
        run_ingestion(engine, f"{learn}/{path}")
    assert all(rows == [] for rows in snapshot(engine))


@pytest.mark.parametrize("path", TRUNCATED_RESPONSES)
def test_truncation_preserves_versions_and_change_history(
    engine: Engine, learn: str, path: str
) -> None:
    run_ingestion(engine, f"{learn}/ok")
    run_ingestion(engine, f"{learn}/modified")
    before = snapshot(engine)
    version_rows, *_, change_rows = before
    assert len(version_rows) == 2
    assert change_rows

    with pytest.raises(SyllabusError):
        run_ingestion(engine, f"{learn}/{path}")

    # Every row is identical, including the latest version's last_checked_at.
    assert snapshot(engine) == before
    # A later complete response still lines up with the untouched latest version.
    result = run_ingestion(engine, f"{learn}/modified")
    assert (result.status, result.version_number) == ("unchanged", 2)


def test_cli_reports_truncation_and_exits_non_zero(
    engine: Engine,
    learn: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_ingestion(engine, f"{learn}/ok")
    before = snapshot(engine)
    monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
    monkeypatch.setattr(ingest, "SOURCE_URL", f"{learn}/advertised-5414-delivered-4502")

    assert ingest.main([]) == 1
    assert "incomplete response" in capsys.readouterr().err
    assert snapshot(engine) == before


def _bullet_to_paragraph(html: str) -> str:
    bullet = "<li><p>Select a retrieval and indexing approach</p>\n</li>\n"
    assert bullet in html
    return html.replace(bullet, "<p>Select a retrieval and indexing approach</p>\n")


def _added_paragraph(html: str) -> str:
    next_skill = '</ul>\n<h4 id="secure-and-monitor-ai-workloads">'
    assert next_skill in html
    return html.replace(
        next_skill, next_skill.replace("</ul>\n", "</ul>\n<p>A new objective</p>\n")
    )


@pytest.mark.parametrize("mutate", [_bullet_to_paragraph, _added_paragraph])
def test_rejected_structure_creates_no_first_version(
    engine: Engine,
    baseline_html: str,
    monkeypatch: pytest.MonkeyPatch,
    mutate: Callable[[str], str],
) -> None:
    def must_not_run(*_: object) -> None:
        raise AssertionError("opened a database session")

    monkeypatch.setattr(ingest, "fetch_html", lambda _: mutate(baseline_html))
    monkeypatch.setattr(ingest, "Session", must_not_run)

    with pytest.raises(SyllabusError, match="unexpected p "):
        run_ingestion(engine, URL)
    assert all(rows == [] for rows in snapshot(engine))


@pytest.mark.parametrize("mutate", [_bullet_to_paragraph, _added_paragraph])
def test_rejected_structure_preserves_versions_and_change_history(
    engine: Engine,
    learn: str,
    baseline_html: str,
    monkeypatch: pytest.MonkeyPatch,
    mutate: Callable[[str], str],
) -> None:
    run_ingestion(engine, f"{learn}/ok")
    run_ingestion(engine, f"{learn}/modified")
    before = snapshot(engine)
    version_rows, *_, change_rows = before
    assert len(version_rows) == 2
    assert change_rows

    with monkeypatch.context() as patch:
        patch.setattr(ingest, "fetch_html", lambda _: mutate(baseline_html))
        with pytest.raises(SyllabusError, match="unexpected p "):
            run_ingestion(engine, URL)

    # Every row is identical, including the latest version's last_checked_at.
    assert snapshot(engine) == before
    result = run_ingestion(engine, f"{learn}/modified")
    assert (result.status, result.version_number) == ("unchanged", 2)


STUDY = "<h2>Study resources</h2>"
BOUNDARY_DEFECTS = [
    pytest.param(
        lambda page: page.replace(
            LAST_SKILL_HEADING, f"<h2 hidden>Notes</h2>{LAST_SKILL_HEADING}"
        ),
        "unexpected h2",
        id="hidden-heading-before-last-skill",
    ),
    pytest.param(
        lambda page: page.replace(LAST_SKILL_HEADING, "<h3>Audience profile</h3>"),
        "out of order",
        id="audience-profile-replaces-last-skill",
    ),
    pytest.param(
        lambda page: last_skill_list_after(
            page, "<h2>Study resources</h2><h2>Notes</h2>"
        ),
        "unexpected h2 ",
        id="early-closing-heading-then-unknown-section",
    ),
    pytest.param(
        lambda page: last_skill_list_after(
            page, "<h2>Study resources</h2><h2>Additional resources</h2>"
        ),
        "unexpected li ",
        id="early-closing-heading-then-known-section",
    ),
    pytest.param(
        lambda page: page.replace(
            LAST_SKILL_HEADING, f"{STUDY}</main>{LAST_SKILL_HEADING}"
        ),
        "expected one <main>",
        id="premature-main-close",
    ),
    pytest.param(
        lambda page: page.replace("</main>", "").replace(
            LAST_SKILL_HEADING, f"{STUDY}</main>{LAST_SKILL_HEADING}"
        ),
        "outside the main content",
        id="premature-main-close-real-close-removed",
    ),
    pytest.param(
        lambda page: page.replace("</main>", "").replace(
            LAST_SKILL_HEADING, f"<h2>Study resources</main>{LAST_SKILL_HEADING}"
        ),
        "<h2> is still open at </main>",
        id="unclosed-heading-then-main-close",
    ),
    pytest.param(
        lambda page: page.replace(
            LAST_SKILL_HEADING, f"{STUDY}<main></main>{LAST_SKILL_HEADING}"
        ),
        "expected one <main>",
        id="nested-main",
    ),
    pytest.param(
        lambda page: page.replace(
            f"<li><p>Subskill 5.2.3</p></li></ul>\n{STUDY}<p>",
            f"<li><p><span>Subskill</p></li></ul>\n{STUDY}<p>5.2.3</span> ",
        ),
        "<span> is still open at </p>",
        id="crossed-element-truncates-last-objective",
    ),
    pytest.param(
        lambda page: page.replace("<li><p>Subskill 5.2.3</p></li>", "").replace(
            "</main>", "</main><ul><li><a href='#'>Subskill 5.2.3</a></li></ul>"
        ),
        "outside the main content: 'Subskill 5.2.3'",
        id="linked-objective-moved-outside-main",
    ),
    pytest.param(
        lambda page: page.replace("Subskill 5.2.3<", "Subskill <!-- 5.2.3 --><"),
        "unexpected hidden",
        id="objective-tail-in-comment",
    ),
    pytest.param(
        lambda page: page.replace(
            f"Subskill 5.2.3</p></li></ul>\n{STUDY}",
            f"Subskill</p></li></ul>\n{STUDY} 5.2.3",
        ),
        "unexpected text after the syllabus section",
        id="objective-tail-after-closing-heading",
    ),
    pytest.param(
        lambda page: page.replace("Subskill 5.2.3<", "Subskill<").replace(
            "</main>", "</main><div>5.2.3</div>"
        ),
        "text outside the main content",
        id="objective-tail-after-main",
    ),
]


@pytest.mark.parametrize(("mutate", "message"), BOUNDARY_DEFECTS)
def test_section_boundary_defect_creates_no_first_version(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    mutate: Callable[[str], str],
    message: str,
) -> None:
    def must_not_run(*_: object) -> None:
        raise AssertionError("opened a database session")

    monkeypatch.setattr(ingest, "fetch_html", lambda _: mutate(official_shape_page()))
    monkeypatch.setattr(ingest, "Session", must_not_run)

    with pytest.raises(SyllabusError, match=message):
        run_ingestion(engine, URL)
    assert all(rows == [] for rows in snapshot(engine))


@pytest.mark.parametrize(("mutate", "message"), BOUNDARY_DEFECTS)
def test_section_boundary_defect_preserves_versions_and_change_history(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    mutate: Callable[[str], str],
    message: str,
) -> None:
    page = official_shape_page()
    latest = page.replace("Subskill 1.1.1<", "Subskill 1.1.1 reworded<")
    for html in (page, latest):
        with monkeypatch.context() as patch:
            patch.setattr(ingest, "fetch_html", lambda _, html=html: html)
            run_ingestion(engine, URL)

    before = snapshot(engine)
    version_rows, _, _, subskill_rows, change_rows = before
    assert len(version_rows) == 2
    assert len(subskill_rows) == 2 * 64
    assert change_rows

    with monkeypatch.context() as patch:
        patch.setattr(ingest, "fetch_html", lambda _: mutate(latest))
        with pytest.raises(SyllabusError, match=message):
            run_ingestion(engine, URL)

    # Every row is identical, including the latest version's last_checked_at.
    assert snapshot(engine) == before
    with monkeypatch.context() as patch:
        patch.setattr(ingest, "fetch_html", lambda _: latest)
        result = run_ingestion(engine, URL)
    assert (result.status, result.version_number) == ("unchanged", 2)


def test_connection_failure_and_timeout_are_reported(learn: str) -> None:
    with pytest.raises(SyllabusError, match="could not fetch"):
        fetch_html("http://127.0.0.1:1/unreachable", timeout=2)
    with pytest.raises(SyllabusError, match="could not fetch"):
        fetch_html(f"{learn}/slow", timeout=0.05)


def test_oversized_response_is_rejected(
    learn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ingest, "MAX_RESPONSE_BYTES", 10)
    with pytest.raises(SyllabusError, match="exceeds"):
        fetch_html(f"{learn}/ok")


def test_failed_write_rolls_back_the_whole_version(
    engine: Engine, baseline_html: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    ingest_fixture(engine, baseline_html)
    before = snapshot(engine)
    build = ingest._to_version

    def broken_change_rows(*args: object) -> SyllabusVersion:
        version = build(*args)  # type: ignore[arg-type]
        version.changes[0].level = None  # type: ignore[assignment]
        return version

    monkeypatch.setattr(ingest, "_to_version", broken_change_rows)
    with pytest.raises(IntegrityError):
        ingest_fixture(engine, load_fixture("ai103_modified.html"))

    assert snapshot(engine) == before


def test_database_rejects_duplicate_version_numbers(
    engine: Engine, baseline_html: str
) -> None:
    ingest_fixture(engine, baseline_html)
    with pytest.raises(IntegrityError), Session(engine) as session, session.begin():
        session.add(
            SyllabusVersion(
                exam_code="AI-103",
                version_number=1,
                source_url=URL,
                retrieved_at=T0,
                last_checked_at=T0,
                effective_date=date(2026, 4, 16),
                content_hash="x" * 64,
            )
        )


# --- CLI ---


def test_cli_exit_codes_and_dry_run_writes_nothing(
    engine: Engine, learn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))

    monkeypatch.setattr(ingest, "SOURCE_URL", f"{learn}/500")
    assert ingest.main([]) == 1
    assert snapshot(engine)[0] == []

    monkeypatch.setattr(ingest, "SOURCE_URL", f"{learn}/ok")
    assert ingest.main(["--dry-run"]) == 0
    assert snapshot(engine)[0] == []

    assert ingest.main([]) == 0
    assert len(snapshot(engine)[0]) == 1


def test_cli_requires_database_url(monkeypatch: pytest.MonkeyPatch, learn: str) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(ingest, "SOURCE_URL", f"{learn}/ok")
    assert ingest.main([]) == 1


# --- Migration (Postgres only) ---


@pytest.mark.skipif(not postgres_test_url(), reason="TEST_DATABASE_URL is not set")
def test_migration_matches_models_and_downgrades_cleanly() -> None:
    url = postgres_test_url()
    assert url
    config = alembic_config(url)
    engine = create_engine(url)
    command.upgrade(config, "head")
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            assert compare_metadata(context, Base.metadata) == []
    finally:
        command.downgrade(config, "base")
    assert not {model.__tablename__ for model in TABLES} & set(
        inspect(engine).get_table_names()
    )
    engine.dispose()
