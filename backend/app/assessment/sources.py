"""Attach Microsoft Learn pages to syllabus objectives, as the evidence questions cite.

Run with:
    python -m app.assessment.sources add --subskill 12 --subskill 13 <learn URL>
    python -m app.assessment.sources list [--version N]

Like syllabus ingestion, the page is fetched and validated before a database session
opens, and all writes share one transaction, so a failure changes nothing. Only
https://learn.microsoft.com pages are accepted. The API never fetches pages.
"""

import argparse
import hashlib
import os
import sys
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit

from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.assessment.models import LearnSource, ObjectiveSource, Question
from app.syllabus.ingest import fetch_html
from app.syllabus.models import (
    SyllabusDomain,
    SyllabusSkill,
    SyllabusSubskill,
    SyllabusVersion,
)
from app.syllabus.parser import EXAM_CODE, SyllabusError, normalize_text

LEARN_HOST = "learn.microsoft.com"
MIN_CONTENT_CHARS = 200
_SKIPPED = frozenset({"script", "style", "nav", "header", "footer", "aside", "form"})
_VOID = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "wbr"}
)
_BLOCKS = frozenset(
    {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "pre", "dd", "dt"}
)


class SourceError(Exception):
    """The page could not be used as a source."""


def check_learn_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme != "https" or parts.hostname != LEARN_HOST or parts.port:
        raise SourceError(f"only https://{LEARN_HOST} pages are accepted: {url!r}")
    # Fragments and queries don't change the page, so they'd only make duplicates.
    return f"https://{LEARN_HOST}{parts.path}"


class _MainText(HTMLParser):
    """Text of `<main>`, one line per block, without navigation, scripts or hidden UI.

    Learn articles keep their text in `<div class="content">` blocks, beside buttons
    and notices that are also inside `<main>`. Text in those blocks is kept apart, so
    it can be preferred whenever a page has them.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.main_blocks: list[str] = []
        self.content_blocks: list[str] = []
        self._main_depth = 0
        # One skipped element (and same-named ones nested in it) at a time.
        self._skip: tuple[str, int] | None = None
        self._content_divs = 0
        self._in_title = False
        self._in_h1 = False
        self._current: list[str] = []

    def _flush(self) -> None:
        text = normalize_text("".join(self._current))
        if text:
            self.main_blocks.append(text)
            if self._content_divs:
                self.content_blocks.append(text)
        self._current = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if self._skip:
            name, depth = self._skip
            if tag == name:
                self._skip = (name, depth + 1)
            return
        # A void element has no end tag, so it can't open a region to skip.
        if (
            self._main_depth
            and tag not in _VOID
            and (
                tag in _SKIPPED
                or "hidden" in values
                or values.get("aria-hidden") == "true"
            )
        ):
            self._skip = (tag, 1)
            return
        if tag == "main":
            self._main_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "div" and self._main_depth:
            if self._content_divs:
                self._content_divs += 1
            elif "content" in (values.get("class") or "").split():
                self._content_divs = 1
        if tag == "h1" and self._main_depth:
            self._in_h1 = True
        if tag in _BLOCKS or tag == "br":
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if self._skip:
            name, depth = self._skip
            if tag == name:
                self._skip = (name, depth - 1) if depth > 1 else None
            return
        if tag in _BLOCKS or tag == "div":
            if tag == "h1" and self._in_h1 and self._current:
                self.title = normalize_text("".join(self._current))
                self._in_h1 = False
            self._flush()
        if tag == "div" and self._content_divs:
            self._content_divs -= 1
        elif tag == "main" and self._main_depth:
            self._main_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title and not self.title:
            self.title = normalize_text(data)
        elif self._main_depth and not self._skip:
            self._current.append(data)


def extract_text(html: str) -> tuple[str, str]:
    """Title and article text. Rejects a page with too little text to verify anything."""
    parser = _MainText()
    parser.feed(html)
    parser.close()
    parser._flush()
    content = "\n".join(parser.content_blocks or parser.main_blocks)
    if len(content) < MIN_CONTENT_CHARS:
        raise SourceError("the page has no usable <main> text")
    return parser.title or "Microsoft Learn page", content


def store_source(
    session: Session,
    url: str,
    title: str,
    content: str,
    subskill_ids: list[int],
    now: datetime,
) -> LearnSource:
    """Reuse the stored row when the text is unchanged, otherwise add a new one."""
    unknown = set(subskill_ids) - set(
        session.scalars(
            select(SyllabusSubskill.id).where(SyllabusSubskill.id.in_(subskill_ids))
        )
    )
    if unknown:
        raise SourceError(f"no syllabus objective with id {sorted(unknown)}")
    digest = hashlib.sha256(content.encode()).hexdigest()
    source = session.scalar(
        select(LearnSource).where(
            LearnSource.url == url, LearnSource.content_hash == digest
        )
    )
    if not source:
        source = LearnSource(
            url=url, title=title, content=content, content_hash=digest, retrieved_at=now
        )
        session.add(source)
        session.flush()
    linked = set(
        session.scalars(
            select(ObjectiveSource.subskill_id).where(
                ObjectiveSource.source_id == source.id
            )
        )
    )
    for subskill_id in dict.fromkeys(subskill_ids):
        if subskill_id not in linked:
            session.add(
                ObjectiveSource(
                    subskill_id=subskill_id, source_id=source.id, created_at=now
                )
            )
    return source


def add_source(engine: Engine, url: str, subskill_ids: list[int]) -> LearnSource:
    clean_url = check_learn_url(url)
    try:
        title, content = extract_text(fetch_html(clean_url))
    except SyllabusError as exc:
        raise SourceError(str(exc)) from exc
    with Session(engine, expire_on_commit=False) as session, session.begin():
        return store_source(
            session, clean_url, title, content, subskill_ids, datetime.now(UTC)
        )


def coverage(
    session: Session, version_number: int | None
) -> list[tuple[str, int, int]]:
    """Per objective: label, attached sources and active questions."""
    version_query = select(SyllabusVersion.id).where(
        SyllabusVersion.exam_code == EXAM_CODE
    )
    version_query = (
        version_query.where(SyllabusVersion.version_number == version_number)
        if version_number
        else version_query.order_by(SyllabusVersion.version_number.desc()).limit(1)
    )
    version_id = session.scalar(version_query)
    if version_id is None:
        raise SourceError("no such syllabus version")
    sources = (
        select(func.count())
        .where(ObjectiveSource.subskill_id == SyllabusSubskill.id)
        .scalar_subquery()
    )
    questions = (
        select(func.count())
        .where(Question.subskill_id == SyllabusSubskill.id, Question.status == "active")
        .scalar_subquery()
    )
    rows = session.execute(
        select(
            SyllabusDomain.position,
            SyllabusSkill.position,
            SyllabusSubskill.position,
            SyllabusSubskill.id,
            SyllabusSubskill.text,
            sources,
            questions,
        )
        .join(SyllabusSkill, SyllabusSkill.domain_id == SyllabusDomain.id)
        .join(SyllabusSubskill, SyllabusSubskill.skill_id == SyllabusSkill.id)
        .where(SyllabusDomain.version_id == version_id)
        .order_by(
            SyllabusDomain.position, SyllabusSkill.position, SyllabusSubskill.position
        )
    )
    return [
        (f"{d}.{s}.{o} [id {sid}] {text}", source_count, question_count)
        for d, s, o, sid, text, source_count, question_count in rows
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage Microsoft Learn sources")
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add", help="fetch a Learn page and attach it")
    add.add_argument("url")
    add.add_argument(
        "--subskill",
        type=int,
        action="append",
        required=True,
        help="objective id (repeatable), as printed by `list`",
    )
    listing = commands.add_parser(
        "list", help="show sources and questions per objective"
    )
    listing.add_argument("--version", type=int)
    args = parser.parse_args(argv)

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1
    engine = create_engine(database_url)
    try:
        if args.command == "add":
            source = add_source(engine, args.url, args.subskill)
            print(f"stored source {source.id}: {source.title} ({source.url})")
        else:
            with Session(engine) as session:
                for label, source_count, question_count in coverage(
                    session, args.version
                ):
                    print(
                        f"{source_count} sources, {question_count} questions  {label}"
                    )
    except (SourceError, SQLAlchemyError) as exc:
        print(f"failed, no data changed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
