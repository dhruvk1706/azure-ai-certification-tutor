"""Fetch, parse and store the AI-103 syllabus.

Run with: python -m app.syllabus.ingest [--dry-run]

The page is fetched and fully validated before a database session opens, and all
writes share one transaction, so a failure at any step leaves existing data untouched.
"""

import argparse
import http.client
import os
import sys
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.syllabus.diff import Change, diff_syllabi
from app.syllabus.models import (
    SyllabusChange,
    SyllabusDomain,
    SyllabusSkill,
    SyllabusSubskill,
    SyllabusVersion,
)
from app.syllabus.parser import (
    EXAM_CODE,
    Domain,
    Skill,
    Syllabus,
    SyllabusError,
    content_hash,
    parse_syllabus,
)

SOURCE_URL = (
    "https://learn.microsoft.com/en-us/credentials/certifications/resources/"
    "study-guides/ai-103"
)
FETCH_TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class IngestionResult:
    status: Literal["created", "unchanged"]
    version_number: int
    content_hash: str
    changes: list[Change] = field(default_factory=list)


def _advertised_length(header_values: list[str]) -> int | None:
    """Read Content-Length per RFC 9112: digits only, repeats only if all equal."""
    values = [part.strip() for value in header_values for part in value.split(",")]
    if not values:
        return None
    try:
        # isascii and isdigit first, since int() also takes "+1", "1_0" and Unicode digits.
        if not all(value.isascii() and value.isdigit() for value in values):
            raise ValueError("not digits")
        lengths = {int(value) for value in values}
    except ValueError as exc:
        raise SyllabusError(f"malformed Content-Length: {header_values!r}") from exc
    if len(lengths) > 1:
        raise SyllabusError(f"conflicting Content-Length: {header_values!r}")
    return lengths.pop()


def fetch_html(url: str, timeout: float = FETCH_TIMEOUT_SECONDS) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html",
            "Accept-Language": "en-US",
            "User-Agent": "azure-ai-certification-tutor-syllabus-ingest",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get_content_type()
            if content_type != "text/html":
                raise SyllabusError(f"expected text/html, got {content_type}")
            # A sized read returns short at EOF instead of raising IncompleteRead, so
            # a dropped connection must be caught by comparing against Content-Length.
            # Chunked bodies do raise, and they ignore Content-Length.
            body: bytes = response.read(MAX_RESPONSE_BYTES + 1)
            charset = response.headers.get_content_charset() or "utf-8"
            length_headers: list[str] = response.headers.get_all("Content-Length", [])
            chunked = response.headers.get("Transfer-Encoding") is not None
    except (OSError, http.client.HTTPException) as exc:
        raise SyllabusError(f"could not fetch {url}: {exc}") from exc

    if len(body) > MAX_RESPONSE_BYTES:
        raise SyllabusError(f"response exceeds {MAX_RESPONSE_BYTES} bytes")
    advertised = None if chunked else _advertised_length(length_headers)
    if advertised is not None and advertised != len(body):
        raise SyllabusError(
            f"incomplete response from {url}: "
            f"Content-Length {advertised}, received {len(body)} bytes"
        )
    try:
        return body.decode(charset)
    except (LookupError, UnicodeDecodeError) as exc:
        raise SyllabusError(f"could not decode response as {charset}: {exc}") from exc


def _to_syllabus(version: SyllabusVersion) -> Syllabus:
    return Syllabus(
        version.exam_code,
        version.effective_date,
        tuple(
            Domain(
                domain.name,
                domain.weight_min,
                domain.weight_max,
                tuple(
                    Skill(
                        skill.name,
                        tuple(subskill.text for subskill in skill.subskills),
                    )
                    for skill in domain.skills
                ),
            )
            for domain in version.domains
        ),
    )


def _to_version(
    syllabus: Syllabus,
    number: int,
    digest: str,
    source_url: str,
    retrieved_at: datetime,
    changes: list[Change],
) -> SyllabusVersion:
    return SyllabusVersion(
        exam_code=syllabus.exam_code,
        version_number=number,
        source_url=source_url,
        retrieved_at=retrieved_at,
        last_checked_at=retrieved_at,
        effective_date=syllabus.effective_date,
        content_hash=digest,
        domains=[
            SyllabusDomain(
                position=domain_position,
                name=domain.name,
                weight_min=domain.weight_min,
                weight_max=domain.weight_max,
                skills=[
                    SyllabusSkill(
                        position=skill_position,
                        name=skill.name,
                        subskills=[
                            SyllabusSubskill(position=position, text=text)
                            for position, text in enumerate(skill.subskills, 1)
                        ],
                    )
                    for skill_position, skill in enumerate(domain.skills, 1)
                ],
            )
            for domain_position, domain in enumerate(syllabus.domains, 1)
        ],
        changes=[
            SyllabusChange(
                position=position,
                level=change.level,
                change_type=change.change_type,
                domain_name=change.domain_name,
                skill_name=change.skill_name,
                old_value=change.old_value,
                new_value=change.new_value,
            )
            for position, change in enumerate(changes, 1)
        ],
    )


def store_syllabus(
    session: Session, syllabus: Syllabus, source_url: str, retrieved_at: datetime
) -> IngestionResult:
    """Add a new version only if the normalized content differs from the latest one.

    Compares against the latest version only, so reverting to earlier content is
    recorded as a new version. Racing runs are stopped by the unique version number.
    """
    digest = content_hash(syllabus)
    latest = session.scalar(
        select(SyllabusVersion)
        .where(SyllabusVersion.exam_code == syllabus.exam_code)
        .order_by(SyllabusVersion.version_number.desc())
        .limit(1)
    )
    if latest and latest.content_hash == digest:
        latest.last_checked_at = retrieved_at
        return IngestionResult("unchanged", latest.version_number, digest)

    # The first version is the baseline, so it has nothing to be compared with.
    changes = diff_syllabi(_to_syllabus(latest), syllabus) if latest else []
    number = latest.version_number + 1 if latest else 1
    session.add(
        _to_version(syllabus, number, digest, source_url, retrieved_at, changes)
    )
    return IngestionResult("created", number, digest, changes)


def run_ingestion(engine: Engine, url: str) -> IngestionResult:
    syllabus = parse_syllabus(fetch_html(url))
    with Session(engine) as session, session.begin():
        return store_syllabus(session, syllabus, url, datetime.now(UTC))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"Ingest the {EXAM_CODE} syllabus")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch and parse the live page without touching the database",
    )
    args = parser.parse_args(argv)

    try:
        if args.dry_run:
            syllabus = parse_syllabus(fetch_html(SOURCE_URL))
            skills = [skill for domain in syllabus.domains for skill in domain.skills]
            print(
                f"parsed {len(syllabus.domains)} domains, {len(skills)} skills, "
                f"{sum(len(skill.subskills) for skill in skills)} subskills, "
                f"effective {syllabus.effective_date}, "
                f"hash {content_hash(syllabus)}"
            )
            return 0

        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise SyllabusError("DATABASE_URL is not set")
        result = run_ingestion(create_engine(database_url), SOURCE_URL)
    except (SyllabusError, SQLAlchemyError) as exc:
        print(f"syllabus ingestion failed, no data changed: {exc}", file=sys.stderr)
        return 1

    print(
        f"{result.status}: {EXAM_CODE} version {result.version_number}, "
        f"{len(result.changes)} changes, hash {result.content_hash}"
    )
    for change in result.changes:
        path = " > ".join(p for p in (change.domain_name, change.skill_name) if p)
        print(
            f"  {change.change_type} {change.level} [{path}]: "
            f"{change.old_value!r} -> {change.new_value!r}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
