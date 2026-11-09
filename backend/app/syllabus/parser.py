"""Parse the Microsoft Learn AI-103 study guide into a normalized syllabus.

Fails closed: anything that does not look like the expected page raises
SyllabusError, so a redesigned page can never replace good data with bad.
"""

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date, datetime
from html.parser import HTMLParser

EXAM_CODE = "AI-103"
EXPECTED_DOMAIN_COUNT = 5

_BLOCK_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "li"}
_LIST_TAGS = {"ul", "ol"}
# Formatting that keeps its text inside the surrounding block. Anything else is reported,
# so an unfamiliar element fails the parse instead of its content being dropped.
_INLINE_TAGS = {
    "a",
    "abbr",
    "b",
    "bdi",
    "bdo",
    "br",
    "cite",
    "code",
    "dfn",
    "em",
    "i",
    "kbd",
    "mark",
    "q",
    "samp",
    "small",
    "span",
    "strong",
    "sub",
    "sup",
    "time",
    "u",
    "var",
    "wbr",
}
_NESTED_LIST = "nested-list"
_UNCLOSED_LIST = "unclosed-list"
_LOOSE_TEXT = "text"
_TABLE_TEXT = "table-text"
_HIDDEN = "hidden"
_PARAGRAPH = "p"
_AUDIENCE_CONTENT = {_PARAGRAPH, _LOOSE_TEXT, "li"}
_SECTION_PREFIX = "skills measured"
_DATED_SECTION = re.compile(r"skills measured as of (.+)", re.IGNORECASE)
_WEIGHTED_NAME = re.compile(r"(.+?)\s*\(\s*(\d+)\s*-\s*(\d+)\s*%\s*\)")
_SKIPPED_HEADING = "Audience profile"
_GLANCE_HEADING = "Skills at a glance"
_SECTION_END_HEADING = "Study resources"
_ADDITIONAL_HEADING = "Additional resources"
_DATE_BULLET = re.compile(r"Last updated on \d{4}-\d{2}-\d{2}")
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
# Elements HTML allows to end without an end tag, and the start tags that end them. Any
# other element must be closed explicitly and in order.
_OPTIONAL_END_TAGS = {
    "caption",
    "colgroup",
    "dd",
    "dt",
    "li",
    "optgroup",
    "option",
    _PARAGRAPH,
    "rp",
    "rt",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
}
_TABLE_CELL_CONTENT = {_PARAGRAPH, "td", "th"}
_TABLE_ROW_CONTENT = _TABLE_CELL_CONTENT | {"tr"}
_TABLE_SECTION_CONTENT = _TABLE_ROW_CONTENT | {
    "caption",
    "colgroup",
    "tbody",
    "tfoot",
    "thead",
}
_PARAGRAPH_ENDING_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "details",
    "div",
    "dl",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    *_HEADING_TAGS,
    "header",
    "hgroup",
    "hr",
    "main",
    "menu",
    "nav",
    "ol",
    _PARAGRAPH,
    "pre",
    "section",
    "table",
    "ul",
}
_IMPLICIT_CLOSES: dict[str, set[str]] = {
    **{tag: {_PARAGRAPH} for tag in _PARAGRAPH_ENDING_TAGS},
    "li": {_PARAGRAPH, "li"},
    "dd": {_PARAGRAPH, "dd", "dt"},
    "dt": {_PARAGRAPH, "dd", "dt"},
    "option": {"option"},
    "optgroup": {"option", "optgroup"},
    "rp": {"rp", "rt"},
    "rt": {"rp", "rt"},
    "td": _TABLE_CELL_CONTENT,
    "th": _TABLE_CELL_CONTENT,
    "tr": _TABLE_ROW_CONTENT,
    "thead": _TABLE_SECTION_CONTENT,
    "tbody": _TABLE_SECTION_CONTENT,
    "tfoot": _TABLE_SECTION_CONTENT,
    "colgroup": {"caption", "colgroup"},
}
# Outside <main>, only these can hold text that passes for syllabus content.
_OUTSIDE_MAIN_BLOCKS = _HEADING_TAGS | {"li", _PARAGRAPH}
_OUTSIDE_MAIN_HEADING = "In this article"
_BROWSER_NOTICE_ID = "unsupported-browser"
_FOOTER_LINKS_NAME = "footerlinks"
_COPYRIGHT_BULLET = re.compile(r"© Microsoft \d{4}")
_STAGE_START = "start"
_STAGE_AUDIENCE = "audience"
_STAGE_GLANCE = "glance"
_STAGE_DOMAINS = "domains"
_TYPOGRAPHY = str.maketrans(
    {
        "\N{HYPHEN}": "-",
        "\N{NON-BREAKING HYPHEN}": "-",
        "\N{FIGURE DASH}": "-",
        "\N{EN DASH}": "-",
        "\N{EM DASH}": "-",
        "\N{LEFT SINGLE QUOTATION MARK}": "'",
        "\N{RIGHT SINGLE QUOTATION MARK}": "'",
        "\N{LEFT DOUBLE QUOTATION MARK}": '"',
        "\N{RIGHT DOUBLE QUOTATION MARK}": '"',
        "\N{SOFT HYPHEN}": None,
        "\N{ZERO WIDTH SPACE}": None,
    }
)


class SyllabusError(Exception):
    """The syllabus could not be fetched or the page was not as expected."""


@dataclass(frozen=True)
class Skill:
    name: str
    subskills: tuple[str, ...]


@dataclass(frozen=True)
class Domain:
    name: str
    weight_min: int
    weight_max: int
    skills: tuple[Skill, ...]


@dataclass(frozen=True)
class Syllabus:
    exam_code: str
    effective_date: date
    domains: tuple[Domain, ...]


def normalize_text(text: str) -> str:
    """Fold whitespace and typographic variants that carry no syllabus meaning."""
    return " ".join(unicodedata.normalize("NFKC", text).translate(_TYPOGRAPHY).split())


def content_hash(syllabus: Syllabus) -> str:
    """Hash the parsed syllabus, so page chrome and markup can never affect it."""
    canonical = json.dumps(
        asdict(syllabus),
        default=str,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class _OutsideMainBlock:
    tag: str
    text: str
    ancestors: tuple[tuple[str, dict[str, str | None]], ...]
    has_link: bool
    has_button: bool
    after_main: bool


class _BlockExtractor(HTMLParser):
    """Flatten everything inside <main> into (tag, text) pairs, in document order.

    Headings and list items carry their text. Everything else that has content is
    recorded too, because only the section parser knows whether it is allowed there.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lang = ""
        self.blocks: list[tuple[str, str]] = []
        self.main_closed = False
        self.main_opens = 0
        self.main_closes = 0
        self.nesting_error: str | None = None
        self.outside_main: list[_OutsideMainBlock] = []
        self._in_main = False
        self._list_depth = 0
        self._open_tag: str | None = None
        self._text: list[str] = []
        self._list_item_paragraph_ended = False
        self._open_elements: list[str] = []
        self._outside_elements: list[tuple[str, dict[str, str | None]]] = []
        self._outside_tag: str | None = None
        self._outside_tag_ancestors: tuple[tuple[str, dict[str, str | None]], ...] = ()
        self._outside_text: list[str] = []
        self._outside_has_link = False
        self._outside_has_button = False

    def _open_element(self, tag: str) -> None:
        """Track nesting inside <main>, ending elements the new start tag implicitly ends."""
        implicitly_closed = _IMPLICIT_CLOSES.get(tag, set())
        while self._open_elements and self._open_elements[-1] in implicitly_closed:
            self._open_elements.pop()
        if tag not in _VOID_TAGS:
            self._open_elements.append(tag)

    def _close_element(self, tag: str) -> None:
        """Close the nearest match. Only optional-end elements may be closed by this."""
        if tag in _VOID_TAGS:
            return
        if tag != "main" and tag not in self._open_elements:
            self._report_nesting(f"</{tag}> has no matching open element inside <main>")
            return
        while self._open_elements:
            element = self._open_elements.pop()
            if element == tag:
                return
            if element not in _OPTIONAL_END_TAGS:
                self._report_nesting(f"<{element}> is still open at </{tag}>")

    def _report_nesting(self, problem: str) -> None:
        self.nesting_error = self.nesting_error or problem

    def _close_outside_block(self) -> None:
        if self._outside_tag:
            self.outside_main.append(
                _OutsideMainBlock(
                    self._outside_tag,
                    normalize_text("".join(self._outside_text)),
                    self._outside_tag_ancestors,
                    self._outside_has_link,
                    self._outside_has_button,
                    self.main_opens > 0,
                )
            )
        self._outside_tag = None
        self._outside_text = []
        self._outside_has_link = False
        self._outside_has_button = False

    def _start_outside_element(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag in _OUTSIDE_MAIN_BLOCKS:
            self._close_outside_block()
            self._outside_tag = tag
            self._outside_tag_ancestors = tuple(self._outside_elements)
        elif tag == "a" and dict(attrs).get("href"):
            self._outside_has_link = True
        elif tag == "button":
            self._outside_has_button = True
        if tag not in _VOID_TAGS:
            self._outside_elements.append((tag, dict(attrs)))

    def _end_outside_element(self, tag: str) -> None:
        """Lenient by design: the live page has stray end tags outside <main>."""
        if tag == self._outside_tag:
            self._close_outside_block()
        for index in range(len(self._outside_elements) - 1, -1, -1):
            if self._outside_elements[index][0] == tag:
                del self._outside_elements[index:]
                break

    def close(self) -> None:
        super().close()
        self._close_outside_block()

    def _open_text(self) -> str:
        return normalize_text("".join(self._text))

    def _close_block(self) -> None:
        text = self._open_text()
        # An empty paragraph holds nothing that could be lost, so it is not reported.
        if self._open_tag and (text or self._open_tag != _PARAGRAPH):
            self.blocks.append((self._open_tag, text))
        self._open_tag = None
        self._text = []
        self._list_item_paragraph_ended = False

    def _start_paragraph(self) -> None:
        if self._open_tag == "li":
            # One wrapping <p> is normal. More would run separate objectives together.
            if self._open_text():
                self.blocks.append((_PARAGRAPH, "more than one block in a list item"))
        elif self._open_tag in {None, _PARAGRAPH}:
            self._close_block()
            self._open_tag = _PARAGRAPH
        else:
            self.blocks.append((_PARAGRAPH, f"inside {self._open_tag}"))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # Markup inside a tag means a missing quote or ">" swallowed what followed it.
        if any("<" in f"{name}{value}" for name, value in attrs):
            self._report_hidden(self.get_starttag_text() or tag)
        if self._in_main and tag != "main":
            self._open_element(tag)
        if tag == "html":
            self.lang = dict(attrs).get("lang") or ""
        elif tag == "main":
            self._close_outside_block()
            self.main_opens += 1
            self.main_closed = False
            self._in_main = True
        elif not self._in_main:
            self._start_outside_element(tag, attrs)
        elif tag in _INLINE_TAGS:
            if tag == "br":
                self._text.append(" ")
        elif tag in _LIST_TAGS:
            self._list_depth += 1
            if self._list_depth > 1:
                self._close_block()
                self.blocks.append((_NESTED_LIST, ""))
            elif self._open_tag == _PARAGRAPH:
                self._close_block()
        elif tag == _PARAGRAPH:
            self._start_paragraph()
        elif tag in _BLOCK_TAGS:
            self._close_block()
            if tag != "li" and self._list_depth:
                # Headings never sit inside a list, so the list's end has gone missing.
                self.blocks.append((_UNCLOSED_LIST, ""))
                self._list_depth = 0
            self._open_tag = tag
        else:
            self.blocks.append((tag, ""))

    def handle_endtag(self, tag: str) -> None:
        if self._in_main:
            self._close_element(tag)
        if tag == "main":
            self._close_block()
            self.main_closes += 1
            self.main_closed = self.main_closed or self._in_main
            self._in_main = False
        elif not self._in_main:
            self._end_outside_element(tag)
        elif tag in _LIST_TAGS:
            self._close_block()
            self._list_depth = max(0, self._list_depth - 1)
        elif tag == _PARAGRAPH and self._open_tag == "li":
            self._list_item_paragraph_ended = bool(self._open_text())
        elif tag == self._open_tag:
            self._close_block()

    def handle_data(self, data: str) -> None:
        text = normalize_text(data)
        if self._open_tag:
            if self._list_item_paragraph_ended and text:
                self.blocks.append((_LOOSE_TEXT, text))
            self._text.append(data)
        elif self._in_main:
            # A script's or style's content is not page text, and only they can be raw.
            if text and self._open_elements[-1:] not in (["script"], ["style"]):
                in_table = "table" in self._open_elements
                self.blocks.append((_TABLE_TEXT if in_table else _LOOSE_TEXT, text))
        elif self._outside_tag:
            self._outside_text.append(data)
        elif text:
            self.outside_main.append(
                _OutsideMainBlock(
                    _LOOSE_TEXT,
                    text,
                    tuple(self._outside_elements),
                    False,
                    False,
                    self.main_opens > 0,
                )
            )

    def _report_hidden(self, source: str) -> None:
        """Record markup whose content never reaches handle_data, so it can hide text."""
        if self._in_main:
            self.blocks.append((_HIDDEN, source))

    def handle_comment(self, data: str) -> None:
        # A note between blocks is harmless. Inside an objective it could be the lost
        # tail, and one holding markup could be a stray "<!--" swallowing whole bullets.
        if self._open_tag in _BLOCK_TAGS or "<" in data:
            self._report_hidden(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        self._report_hidden(f"<!{decl}>")

    def handle_pi(self, data: str) -> None:
        self._report_hidden(f"<?{data}>")

    def unknown_decl(self, data: str) -> None:
        self._report_hidden(f"<![{data}]>")


def _is_site_chrome(block: _OutsideMainBlock) -> bool:
    """Decide from where a block sits, matching the structure of the live page.

    A link alone proves nothing, since an objective can be written as a link.
    """
    ancestors = block.ancestors
    tags = {tag for tag, _ in ancestors}
    if block.tag == _LOOSE_TEXT:
        # Live chrome text is document metadata or a control in the header or footer.
        chrome_parents = {"footer"} if block.after_main else {"header", "nav"}
        return bool(tags & {"title", "script", "style"}) or bool(
            tags & {"a", "button"} and tags & chrome_parents
        )
    if block.tag == _PARAGRAPH:
        in_notice = any(attrs.get("id") == _BROWSER_NOTICE_ID for _, attrs in ancestors)
        return not block.text or (in_notice and not block.after_main)
    if block.tag != "li":
        return (
            block.tag == "h3"
            and block.after_main
            and "aside" in tags
            and block.text == _OUTSIDE_MAIN_HEADING
        )
    if not block.text:
        return True
    if not block.after_main or "footer" not in tags:
        return False
    if any(attrs.get("role") == "menu" for _, attrs in ancestors):
        return block.has_button
    parent_list = next(
        (attrs for tag, attrs in reversed(ancestors) if tag in _LIST_TAGS), {}
    )
    return parent_list.get("data-bi-name") == _FOOTER_LINKS_NAME and (
        block.has_link or bool(_COPYRIGHT_BULLET.fullmatch(block.text))
    )


def _validate_main_region(extractor: _BlockExtractor) -> None:
    """Prove <main> holds the whole syllabus, not just the part before a moved boundary.

    Elements must nest correctly inside it, because an element left open across a bullet
    can carry the rest of an objective somewhere it would be ignored. Nothing outside it
    may hold syllabus-like content unless it sits where the live page has site chrome.
    """
    if extractor.nesting_error:
        raise SyllabusError(f"invalid nesting: {extractor.nesting_error}")
    for block in extractor.outside_main:
        if not _is_site_chrome(block):
            raise SyllabusError(
                f"syllabus-like {block.tag} outside the main content: {block.text!r}"
            )


def _parse_weighted_name(text: str) -> tuple[str, int, int] | None:
    match = _WEIGHTED_NAME.fullmatch(text)
    if not match:
        return None
    return match[1], int(match[2]), int(match[3])


def _skills_section(
    blocks: list[tuple[str, str]],
) -> tuple[date, list[tuple[str, str]]]:
    """Find the single dated 'Skills measured' section and its effective date."""
    starts = [
        index
        for index, (tag, text) in enumerate(blocks)
        if tag == "h2" and text.lower().startswith(_SECTION_PREFIX)
    ]
    if len(starts) != 1:
        raise SyllabusError(
            f"expected one 'Skills measured' section, found {len(starts)}"
        )

    heading = blocks[starts[0]][1]
    dated = _DATED_SECTION.fullmatch(heading)
    if not dated:
        raise SyllabusError(f"no effective date in heading: {heading!r}")
    try:
        effective_date = datetime.strptime(dated[1], "%B %d, %Y").date()
    except ValueError as exc:
        raise SyllabusError(f"unreadable effective date: {dated[1]!r}") from exc

    following = blocks[starts[0] + 1 :]
    for index, (tag, text) in enumerate(following):
        if tag not in {"h1", "h2"}:
            continue
        # Only the known closing heading may end the section. Stopping at any heading
        # would silently drop whatever objectives come after it.
        if (tag, text) != ("h2", _SECTION_END_HEADING):
            raise SyllabusError(f"unexpected {tag} in syllabus section: {text!r}")
        _validate_closing_sections(following[index + 1 :])
        return effective_date, following[:index]
    # Only the closing heading proves the last skill's list was not cut short.
    raise SyllabusError("page ends inside the syllabus section, content may be lost")


def _validate_closing_sections(after_section: list[tuple[str, str]]) -> None:
    """Catch a closing heading that sits too early, with objectives still to come.

    Everything after it must match the live page: the closing section holds one intro
    paragraph and tables, but no bullets or bare text, so an objective's tail can't land
    there unnoticed. It may be followed by one further section, which holds only page
    chrome and the date bullet.
    """
    in_additional_section = False
    has_intro = False
    for tag, text in after_section:
        if tag == "h2" and text == _ADDITIONAL_HEADING and not in_additional_section:
            in_additional_section = True
        elif (
            tag in _HEADING_TAGS
            or tag == _LOOSE_TEXT
            or (
                tag == "li"
                and not (in_additional_section and _DATE_BULLET.fullmatch(text))
            )
            or (tag == _PARAGRAPH and (in_additional_section or has_intro))
            or (tag == _TABLE_TEXT and in_additional_section)
        ):
            raise SyllabusError(
                f"unexpected {tag} after the syllabus section: {text!r}"
            )
        has_intro = has_intro or tag == _PARAGRAPH


def _parse_section(
    section: list[tuple[str, str]],
) -> tuple[list[tuple[str, int, int]], list[Domain]]:
    """Walk the section's headings. Returns the at-a-glance list and the domains.

    The section only moves forward: audience, then at-a-glance, then domains. Going back
    would let a late heading turn the objectives after it into ignored content.
    """
    glance: list[tuple[str, int, int]] = []
    domains: list[tuple[tuple[str, int, int], list[tuple[str, list[str]]]]] = []
    stage = _STAGE_START

    for tag, text in section:
        if tag == "h3":
            if text == _SKIPPED_HEADING and stage == _STAGE_START:
                stage = _STAGE_AUDIENCE
            elif text == _GLANCE_HEADING and stage in {_STAGE_START, _STAGE_AUDIENCE}:
                stage = _STAGE_GLANCE
            elif text in {_SKIPPED_HEADING, _GLANCE_HEADING}:
                raise SyllabusError(f"{text!r} section is out of order")
            else:
                weighted = _parse_weighted_name(text)
                if not weighted:
                    raise SyllabusError(f"unexpected section heading: {text!r}")
                domains.append((weighted, []))
                stage = _STAGE_DOMAINS
        elif stage == _STAGE_AUDIENCE and tag in _AUDIENCE_CONTENT:
            continue
        elif stage == _STAGE_GLANCE and tag == "li":
            weighted = _parse_weighted_name(text)
            if not weighted:
                raise SyllabusError(f"unexpected at-a-glance item: {text!r}")
            glance.append(weighted)
        elif stage == _STAGE_DOMAINS and tag == "h4":
            domains[-1][1].append((text, []))
        elif stage == _STAGE_DOMAINS and tag == "li" and domains[-1][1]:
            domains[-1][1][-1][1].append(text)
        else:
            raise SyllabusError(f"unexpected {tag} in syllabus section: {text!r}")

    return glance, [
        Domain(
            name,
            weight_min,
            weight_max,
            tuple(Skill(skill, tuple(subskills)) for skill, subskills in skills),
        )
        for (name, weight_min, weight_max), skills in domains
    ]


def _require_unique(names: list[str], what: str) -> None:
    if not all(names) or len(set(names)) != len(names):
        raise SyllabusError(f"blank or duplicate {what}: {names!r}")


def _validate(domains: list[Domain], glance: list[tuple[str, int, int]]) -> None:
    if len(domains) != EXPECTED_DOMAIN_COUNT:
        raise SyllabusError(
            f"expected {EXPECTED_DOMAIN_COUNT} domains, found {len(domains)}"
        )
    summary = [
        (domain.name, domain.weight_min, domain.weight_max) for domain in domains
    ]
    if glance != summary:
        raise SyllabusError(
            f"at-a-glance {glance!r} does not match domains {summary!r}"
        )
    if any(not low <= high <= 100 for _, low, high in summary):
        raise SyllabusError(f"invalid weight range: {summary!r}")
    if not sum(low for _, low, _ in summary) <= 100 <= sum(h for _, _, h in summary):
        raise SyllabusError(f"weights cannot total 100%: {summary!r}")

    _require_unique([domain.name for domain in domains], "domain")
    for domain in domains:
        if not domain.skills:
            raise SyllabusError(f"domain has no skills: {domain.name!r}")
        _require_unique([skill.name for skill in domain.skills], "skill")
        for skill in domain.skills:
            if not skill.subskills:
                raise SyllabusError(f"skill has no subskills: {skill.name!r}")
            _require_unique(list(skill.subskills), "subskill")


def parse_syllabus(html: str) -> Syllabus:
    extractor = _BlockExtractor()
    extractor.feed(html)
    extractor.close()

    if not extractor.lang.lower().startswith("en"):
        raise SyllabusError(f"page is not English: lang={extractor.lang!r}")
    title = next((text for tag, text in extractor.blocks if tag == "h1"), "")
    if EXAM_CODE not in title:
        raise SyllabusError(f"page is not the {EXAM_CODE} study guide: {title!r}")
    if not extractor.main_closed:
        raise SyllabusError("page is incomplete: main content is never closed")
    if (extractor.main_opens, extractor.main_closes) != (1, 1):
        raise SyllabusError(
            f"expected one <main> element, found {extractor.main_opens} opening "
            f"and {extractor.main_closes} closing tags"
        )

    effective_date, section = _skills_section(extractor.blocks)
    glance, domains = _parse_section(section)
    _validate(domains, glance)
    _validate_main_region(extractor)
    return Syllabus(EXAM_CODE, effective_date, tuple(domains))
