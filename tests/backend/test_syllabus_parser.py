import re
from collections.abc import Callable, Iterable
from datetime import date

import pytest
from conftest import (
    LAST_SKILL_HEADING,
    last_skill_list_after,
    load_fixture,
    official_shape_page,
)

from app.syllabus.parser import (
    SyllabusError,
    content_hash,
    normalize_text,
    parse_syllabus,
)


def test_parses_hierarchy_weights_and_order(baseline_html: str) -> None:
    syllabus = parse_syllabus(baseline_html)

    assert syllabus.exam_code == "AI-103"
    assert syllabus.effective_date == date(2026, 4, 16)
    assert [(d.name, d.weight_min, d.weight_max) for d in syllabus.domains] == [
        ("Plan and manage an Azure AI solution", 25, 30),
        ("Implement generative AI and agentic solutions", 30, 35),
        ("Implement computer vision solutions", 10, 15),
        ("Implement text analysis solutions", 10, 15),
        ("Implement information extraction solutions", 10, 15),
    ]
    first = syllabus.domains[0]
    assert [skill.name for skill in first.skills] == [
        "Select Foundry services",
        "Secure and monitor AI workloads",
    ]
    assert first.skills[0].subskills == (
        "Pick a model that fits each workload",
        "Select a retrieval and indexing approach",
    )
    assert len(first.skills[1].subskills) == 3
    assert sum(len(s.subskills) for d in syllabus.domains for s in d.skills) == 18


def test_excludes_content_outside_the_syllabus(baseline_html: str) -> None:
    subskills = {
        text
        for domain in parse_syllabus(baseline_html).domains
        for skill in domain.skills
        for text in skill.subskills
    }
    for outside in ("Sign in.", "Planning solutions.", "Privacy", "Study resources"):
        assert outside not in subskills


def test_normalizes_entities_and_typography(baseline_html: str) -> None:
    domains = parse_syllabus(baseline_html).domains
    assert domains[1].skills[0].subskills[0] == (
        "Add retrieval-augmented answers to an application"
    )
    assert domains[3].skills[0].subskills[1] == (
        "Flag sentiment & the user's sensitive content"
    )
    assert (
        normalize_text("  a\N{NO-BREAK SPACE}b\n\tc\N{EN DASH}d\N{ZERO WIDTH SPACE} ")
        == "a b c-d"
    )


def test_html_churn_does_not_change_the_hash(baseline_html: str) -> None:
    baseline = parse_syllabus(baseline_html)
    churned = parse_syllabus(load_fixture("ai103_html_churn.html"))
    assert churned == baseline
    assert content_hash(churned) == content_hash(baseline)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda h: h.replace("Pick a model", "Choose a model"),
        lambda h: h.replace("(25–30%)", "(25–31%)"),
        lambda h: h.replace("April 16, 2026", "April 17, 2026"),
        lambda h: h.replace("Select Foundry services", "Select Foundry tools"),
        # Same content, different order.
        lambda h: (
            h.replace("Produce images from prompts", "@@")
            .replace(
                "Apply mask‑based edits to generated images",
                "Produce images from prompts",
            )
            .replace("@@", "Apply mask-based edits to generated images")
        ),
    ],
    ids=["subskill-text", "weight", "effective-date", "skill-name", "order"],
)
def test_meaningful_edits_change_the_hash(
    baseline_html: str, mutate: Callable[[str], str]
) -> None:
    assert content_hash(parse_syllabus(mutate(baseline_html))) != content_hash(
        parse_syllabus(baseline_html)
    )


def _drop_last_domain(html: str) -> str:
    html = re.sub(r"<li><p>Implement information extraction[^<]*</p>\s*</li>", "", html)
    return re.sub(
        r'<h3 id="implement-information.*?(?=<h2 id="study)', "", html, flags=re.DOTALL
    )


MALFORMED: list[tuple[str, Callable[[str], str], str]] = [
    ("empty-page", lambda h: "", "not English"),
    ("not-html", lambda h: "<<<>>>not a page", "not English"),
    (
        "no-main",
        lambda h: h.replace("<main", "<div").replace("</main", "</div"),
        "AI-103",
    ),
    (
        "other-locale",
        lambda h: h.replace('lang="en-us"', 'lang="de-de"'),
        "not English",
    ),
    ("other-exam", lambda h: h.replace("Exam AI-103", "Exam AI-102"), "AI-103"),
    (
        "no-section",
        lambda h: h.replace("Skills measured as of", "Topics as of"),
        "one 'Skills",
    ),
    (
        "two-sections",
        lambda h: h.replace(
            '<h2 id="study-resources">Study resources',
            "<h2>Skills measured prior to May 1, 2026",
        ),
        "one 'Skills",
    ),
    ("undated", lambda h: h.replace(" as of April 16, 2026", ""), "effective date"),
    ("bad-date", lambda h: h.replace("April 16, 2026", "Soon"), "effective date"),
    (
        "domain-lost-weight",
        lambda h: h.replace(
            "agentic solutions (30–35%)</h3>", "agentic solutions</h3>"
        ),
        "unexpected section heading",
    ),
    ("domain-missing", _drop_last_domain, "expected 5 domains"),
    (
        "glance-mismatch",
        lambda h: h.replace("solutions (30–35%)</p>", "solutions (30–40%)</p>"),
        "at-a-glance",
    ),
    (
        "glance-missing",
        lambda h: re.sub(
            r'<h3 id="skills-at-a-glance">.*?(?=<h3 id="plan)', "", h, flags=re.DOTALL
        ),
        "at-a-glance",
    ),
    ("impossible-weights", lambda h: h.replace("10–15%", "40–45%"), "total 100"),
    ("inverted-weight", lambda h: h.replace("25–30%", "30–25%"), "invalid weight"),
    (
        "skill-without-subskills",
        lambda h: re.sub(
            r'(<h4 id="understand-visual-content">[^<]*</h4>).*?(?=<h3)',
            r"\1",
            h,
            flags=re.DOTALL,
        ),
        "no subskills",
    ),
    (
        "domain-without-skills",
        lambda h: re.sub(
            r'(<h3 id="implement-text-analysis[^>]*>[^<]*</h3>).*?(?=<h3)',
            r"\1",
            h,
            flags=re.DOTALL,
        ),
        "no skills",
    ),
    (
        "duplicate-subskill",
        lambda h: h.replace(
            "Select a retrieval and indexing approach",
            "Pick a model that fits each workload",
        ),
        "duplicate subskill",
    ),
    (
        "duplicate-skill",
        lambda h: h.replace(
            "Secure and monitor AI workloads", "Select Foundry services"
        ),
        "duplicate skill",
    ),
    (
        "subskill-before-skill",
        lambda h: h.replace(
            '<h4 id="select-foundry-services">Select Foundry services</h4>', ""
        ),
        "unexpected li",
    ),
    (
        "blank-subskill",
        lambda h: h.replace("Produce images from prompts", " "),
        "blank",
    ),
    (
        "nested-list",
        lambda h: h.replace(
            "<li><p>Produce images from prompts</p>",
            "<li><p>Produce images from prompts</p><ul><li>Nested</li></ul>",
        ),
        "unexpected nested-list",
    ),
    (
        "extra-depth",
        lambda h: h.replace(
            "Generate visual media</h4>",
            "Generate visual media</h4><h5>Deeper</h5>",
        ),
        "unexpected h5",
    ),
    (
        "list-never-closed",
        lambda h: re.sub(
            r'</ul>\s*(<h4 id="understand-visual-content">)', r"\1", h, count=1
        ),
        "unexpected unclosed-list",
    ),
    (
        "main-never-closed",
        lambda h: h.replace("</main>", ""),
        "main content is never closed",
    ),
    (
        "nothing-after-syllabus",
        lambda h: re.sub(
            r'<h2 id="study-resources">.*?(?=</main>)', "", h, flags=re.DOTALL
        ),
        "ends inside the syllabus section",
    ),
    (
        "redesign-without-headings",
        lambda h: re.sub(r"<(/?)h[34]\b", r"<\1div", h),
        "unexpected div",
    ),
]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [case[1:] for case in MALFORMED],
    ids=[case[0] for case in MALFORMED],
)
def test_rejects_malformed_or_unexpected_pages(
    baseline_html: str, mutate: Callable[[str], str], message: str
) -> None:
    with pytest.raises(SyllabusError, match=message):
        parse_syllabus(mutate(baseline_html))


BULLET_TEXT = "Select a retrieval and indexing approach"
BULLET = f"<li><p>{BULLET_TEXT}</p>\n</li>\n"
ONLY_BULLET_IN_SKILL = (
    "<ul>\n<li><p>Caption single or multiple images</p>\n</li>\n</ul>"
)
LIST_END = '</ul>\n<h4 id="secure-and-monitor-ai-workloads">'
SKILL_HEADING = "Select Foundry services</h4>"
DOMAIN_HEADING = "Plan and manage an Azure AI solution (25–30%)</h3>"
SECTION_HEADING = "Skills measured as of April 16, 2026</h2>"
NEW = "Review trace logs as audit evidence"


def _after(anchor: str, inserted: str) -> Callable[[str], str]:
    return lambda h: h.replace(anchor, anchor + inserted, 1)


def _before_next_skill(inserted: str) -> Callable[[str], str]:
    return lambda h: h.replace(
        LIST_END, LIST_END.replace("</ul>\n", f"</ul>\n{inserted}")
    )


UNSUPPORTED: list[tuple[str, Callable[[str], str], str]] = [
    # Finding 1: a bullet turned into a paragraph kept its text but lost the objective.
    (
        "bullet-to-paragraph-inside-list",
        lambda h: h.replace(BULLET, f"<p>{BULLET_TEXT}</p>\n"),
        f"unexpected p .*{BULLET_TEXT}",
    ),
    (
        "bullet-to-paragraph-after-list",
        lambda h: h.replace(BULLET, "").replace(
            LIST_END, LIST_END.replace("</ul>\n", f"</ul>\n<p>{BULLET_TEXT}</p>\n")
        ),
        f"unexpected p .*{BULLET_TEXT}",
    ),
    (
        "only-bullet-to-paragraph",
        lambda h: h.replace(
            ONLY_BULLET_IN_SKILL, "<p>Caption single or multiple images</p>"
        ),
        "unexpected p .*Caption",
    ),
    # Finding 2: an added paragraph left the hash unchanged.
    (
        "paragraph-after-list",
        _before_next_skill(f"<p>{NEW}</p>\n"),
        f"unexpected p .*{NEW}",
    ),
    (
        "paragraph-under-skill",
        _after(SKILL_HEADING, f"<p>{NEW}</p>"),
        f"unexpected p .*{NEW}",
    ),
    (
        "paragraph-under-domain",
        _after(DOMAIN_HEADING, f"<p>{NEW}</p>"),
        f"unexpected p .*{NEW}",
    ),
    (
        "paragraph-under-section",
        _after(SECTION_HEADING, f"<p>{NEW}</p>"),
        f"unexpected p .*{NEW}",
    ),
    (
        "paragraph-without-end-tag",
        _before_next_skill(f"<p>{NEW}\n"),
        f"unexpected p .*{NEW}",
    ),
    (
        "paragraph-in-glance",
        _after('<h3 id="skills-at-a-glance">Skills at a glance</h3>', f"<p>{NEW}</p>"),
        f"unexpected p .*{NEW}",
    ),
    # Other text outside a heading or bullet.
    (
        "bare-text-after-list",
        _before_next_skill(f"{NEW}\n"),
        f"unexpected text .*{NEW}",
    ),
    (
        "bare-text-between-bullets",
        lambda h: h.replace(BULLET, f"{BULLET}{NEW}\n"),
        f"unexpected text .*{NEW}",
    ),
    (
        "inline-element-outside-bullet",
        _before_next_skill(f"<strong>{NEW}</strong>\n"),
        f"unexpected text .*{NEW}",
    ),
    # Comments that can be swallowed content, indistinguishable from a real comment.
    (
        "comment-inside-text",
        lambda h: h.replace("Select a retrieval", "Select a <!-- note -->retrieval"),
        "unexpected hidden .*note",
    ),
    (
        "comment-hiding-markup",
        _before_next_skill("<!-- <li>Not an objective</li> -->"),
        "unexpected hidden .*Not an objective",
    ),
    # Other elements.
    (
        "table",
        _before_next_skill(f"<table><tr><td>{NEW}</td></tr></table>"),
        "unexpected table",
    ),
    (
        "definition-list",
        _before_next_skill(f"<dl><dt>{NEW}</dt></dl>"),
        "unexpected dl",
    ),
    (
        "blockquote",
        _before_next_skill(f"<blockquote>{NEW}</blockquote>"),
        "unexpected blockquote",
    ),
    ("details", _before_next_skill(f"<details>{NEW}</details>"), "unexpected details"),
    ("pre", _before_next_skill(f"<pre>{NEW}</pre>"), "unexpected pre"),
    ("div-with-text", _before_next_skill(f"<div>{NEW}</div>"), "unexpected div"),
    (
        "section-wrapper",
        lambda h: h.replace(LIST_END, LIST_END.replace("<h4 ", "<section><h4 ")),
        "unexpected section",
    ),
    ("image-text", _before_next_skill(f'<img alt="{NEW}">'), "unexpected img"),
    (
        "struck-out-text",
        lambda h: h.replace(BULLET, f"<li><del>{NEW}</del></li>"),
        "unexpected del",
    ),
    # Objectives that would run together inside one bullet.
    (
        "two-paragraphs-in-bullet",
        lambda h: h.replace(BULLET, f"<li><p>{BULLET_TEXT}</p><p>{NEW}</p></li>\n"),
        "unexpected p ",
    ),
    (
        "second-paragraph-without-end-tag",
        lambda h: h.replace(BULLET, f"<li><p>{BULLET_TEXT}<p>{NEW}</li>\n"),
        "unexpected p ",
    ),
    (
        "text-before-paragraph-in-bullet",
        lambda h: h.replace(BULLET, f"<li>{NEW}<p>{BULLET_TEXT}</p></li>\n"),
        "unexpected p ",
    ),
    (
        "text-after-paragraph-in-bullet",
        lambda h: h.replace(BULLET, f"<li><p>{BULLET_TEXT}</p>{NEW}</li>\n"),
        f"unexpected text .*{NEW}",
    ),
    (
        "div-in-bullet",
        lambda h: h.replace(BULLET, f"<li><div>{BULLET_TEXT}</div></li>\n"),
        "unexpected div",
    ),
    (
        "paragraph-in-heading",
        lambda h: h.replace(SKILL_HEADING, "<p>Select Foundry services</p></h4>"),
        "unexpected p ",
    ),
    # The skipped audience section is not a place to hide objectives.
    (
        "skill-heading-in-audience",
        _after('<h3 id="audience-profile">Audience profile</h3>', f"<h4>{NEW}</h4>"),
        "unexpected h4",
    ),
    (
        "table-in-audience",
        _after('<h3 id="audience-profile">Audience profile</h3>', "<table></table>"),
        "unexpected table",
    ),
]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [case[1:] for case in UNSUPPORTED],
    ids=[case[0] for case in UNSUPPORTED],
)
def test_rejects_content_the_hierarchy_cannot_represent(
    baseline_html: str, mutate: Callable[[str], str], message: str
) -> None:
    mutated = mutate(baseline_html)
    assert mutated != baseline_html
    with pytest.raises(SyllabusError, match=message):
        parse_syllabus(mutated)


def _footer(items: str) -> str:
    return f'<footer><ul data-bi-name="footerlinks">{items}</ul></footer>'


SUPPORTED: list[tuple[str, Callable[[str], str]]] = [
    (
        "uppercase-tags",
        lambda h: re.sub(r"</?(?:main|h[1-6]|ul|li|p)\b", lambda m: m[0].upper(), h),
    ),
    ("no-li-end-tags", lambda h: h.replace("</li>", "")),
    ("no-p-end-tags", lambda h: h.replace("</p>", "")),
    ("no-li-or-p-end-tags", lambda h: h.replace("</li>", "").replace("</p>", "")),
    (
        "li-without-p",
        lambda h: h.replace("<li><p>", "<li>").replace("</p>\n</li>", "</li>"),
    ),
    ("attributes", lambda h: h.replace("<li>", '<li class="x" data-y="1">')),
    (
        "attributes-on-paragraphs",
        lambda h: h.replace("<li><p>", '<li><p class="x" lang="en">'),
    ),
    ("comment-between-blocks", _before_next_skill("<!-- note -->\n")),
    (
        "inline-formatting-in-bullet",
        lambda h: h.replace(
            BULLET_TEXT,
            'Select a <strong>retrieval</strong> and <a href="/x"><em>indexing</em></a>'
            " <code>approach</code>",
        ),
    ),
    (
        "inline-formatting-in-heading",
        lambda h: h.replace(
            SKILL_HEADING, "<span>Select</span> <b>Foundry</b> services</h4>"
        ),
    ),
    (
        "line-break-in-bullet",
        lambda h: h.replace("Select a retrieval", "Select a<br>retrieval"),
    ),
    ("whitespace-entity-between-blocks", _before_next_skill("&nbsp;\n")),
    ("empty-paragraph-between-blocks", _before_next_skill("<p></p>\n")),
    (
        "empty-paragraph-before-text-in-bullet",
        lambda h: h.replace("<li><p>Select a", "<li><p></p><p>Select a"),
    ),
    ("ordered-list", lambda h: re.sub(r"(</?)ul\b", r"\1ol", h)),
    (
        "no-audience-section",
        lambda h: re.sub(
            r'<h3 id="audience-profile">.*?(?=<h3 id="skills-at)',
            "",
            h,
            flags=re.DOTALL,
        ),
    ),
    (
        "no-optional-table-end-tags",
        lambda h: re.sub(r"</(?:td|th|tr|thead|tbody)>", "", h),
    ),
    (
        "no-optional-end-tags-at-main-close",
        lambda h: h.replace("</li></ul>\n", "</ul>\n"),
    ),
    (
        "main-tags-in-comment",
        lambda h: h.replace("<body", "<!-- <main></main> --><body"),
    ),
    (
        "main-tags-in-script",
        lambda h: h.replace(
            "Study resources</h2>",
            'Study resources</h2><script>var s = "</main><main>";</script>',
        ),
    ),
    (
        "uppercase-main",
        lambda h: h.replace("<main", "<MAIN").replace("</main>", "</MAIN>"),
    ),
    (
        "self-closed-void-elements",
        lambda h: h.replace("</main>", "<hr /><img src=x></main>"),
    ),
    (
        "footer-copyright-after-main",
        lambda h: h.replace(
            "</main>", f"</main>{_footer('<li>© Microsoft 2026</li>')}"
        ),
    ),
    (
        "footer-links-after-main",
        lambda h: h.replace(
            "</main>",
            f"</main>{_footer('<li><a href=x>Blog</a></li><li hidden></li>')}",
        ),
    ),
    (
        "footer-theme-menu-after-main",
        lambda h: h.replace(
            "</main>",
            "</main><footer><div role=menu><ul role=none>"
            "<li><button>Light</button></li></ul></div></footer>",
        ),
    ),
    (
        "stray-end-tag-outside-main",
        lambda h: h.replace("</footer>", "</footer></footer></span>"),
    ),
    (
        "browser-notice-before-main",
        lambda h: h.replace(
            "<main",
            '<div id="unsupported-browser"><p>Browser notice</p></div><main',
            1,
        ),
    ),
    (
        "implied-paragraph-close-by-block",
        lambda h: h.replace(
            "Study resources</h2>", "Study resources</h2><p>Intro<div><hr></div>"
        ),
    ),
    (
        "implied-table-cell-and-row-closes",
        lambda h: h.replace(
            "Study resources</h2>",
            "Study resources</h2><table><thead><tr><th>A<th>B<tbody><tr><td>1<td>2"
            "<tr><td><p>3<td>4</table>",
        ),
    ),
    (
        "nested-inline-formatting",
        lambda h: h.replace(
            "Select a retrieval and",
            "Select <a href=x><strong><em>a</em> retrieval</strong></a> and",
        ),
    ),
    (
        "void-elements-with-end-events",
        lambda h: h.replace("Select a retrieval", "Select a<br/>retrieval"),
    ),
]


@pytest.mark.parametrize(
    "mutate", [case[1] for case in SUPPORTED], ids=[case[0] for case in SUPPORTED]
)
def test_valid_markup_variations_parse_identically(
    baseline_html: str, mutate: Callable[[str], str]
) -> None:
    mutated = mutate(baseline_html)
    assert mutated != baseline_html
    baseline = parse_syllabus(baseline_html)
    assert parse_syllabus(mutated) == baseline
    assert content_hash(parse_syllabus(mutated)) == content_hash(baseline)


def _shape(html: str) -> tuple[int, int]:
    domains = parse_syllabus(html).domains
    skills = [skill for domain in domains for skill in domain.skills]
    return len(skills), sum(len(skill.subskills) for skill in skills)


def test_official_shape_loses_the_last_skill_to_a_section_boundary() -> None:
    """Pins what Codex found: the cut point leaves a valid-looking 13/61 syllabus."""
    page = official_shape_page()
    assert _shape(page) == (14, 64)

    closing = page[page.index("<h2>Study resources</h2>") :]
    assert _shape(page[: page.index(LAST_SKILL_HEADING)] + closing) == (13, 61)


@pytest.mark.parametrize(
    ("heading", "message"),
    [
        ("<h2 hidden>Notes</h2>", "unexpected h2 .*Notes"),
        ("<h2>Notes</h2>", "unexpected h2 .*Notes"),
        ("<H2 HIDDEN>Notes</H2>", "unexpected h2 .*Notes"),
        ('<h2 style="display:none">Notes</h2>', "unexpected h2 .*Notes"),
        ("<h1 hidden>Notes</h1>", "unexpected h1 .*Notes"),
        ("<h1>Notes</h1>", "unexpected h1 .*Notes"),
        ("<h2></h2>", "unexpected h2"),
        ("<h2>Study resources</h2>", "unexpected h4 after the syllabus section"),
        ("<h2 hidden>Study resources</h2>", "unexpected h4 after the syllabus section"),
    ],
)
def test_heading_before_last_skill_cannot_hide_objectives(
    heading: str, message: str
) -> None:
    page = official_shape_page().replace(
        LAST_SKILL_HEADING, heading + LAST_SKILL_HEADING
    )
    with pytest.raises(SyllabusError, match=message):
        parse_syllabus(page)


AUDIENCE = "<h3>Audience profile</h3>"
LAST_LIST_END = "</ul>\n<h2>Study resources</h2>"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.replace(LAST_SKILL_HEADING, AUDIENCE),
        lambda p: p.replace(LAST_SKILL_HEADING, AUDIENCE + LAST_SKILL_HEADING),
        lambda p: p.replace(
            LAST_SKILL_HEADING, '<h3 hidden class="x">Audience profile</h3>'
        ),
        lambda p: p.replace(LAST_LIST_END, "</ul>" + AUDIENCE + LAST_LIST_END),
        lambda p: p.replace(
            LAST_LIST_END,
            f"</ul>{AUDIENCE}<ul><li>Hidden objective</li>{LAST_LIST_END}",
        ),
        lambda p: p.replace("<h3>Domain 3 ", AUDIENCE + "<h3>Domain 3 "),
    ],
    ids=[
        "replaces-last-skill-heading",
        "before-last-skill",
        "hidden",
        "after-last-objective",
        "takes-over-a-new-list",
        "between-domains",
    ],
)
def test_audience_profile_cannot_be_reentered_after_objectives_begin(
    mutate: Callable[[str], str],
) -> None:
    page = official_shape_page()
    mutated = mutate(page)
    assert mutated != page
    with pytest.raises(SyllabusError, match="'Audience profile' .*out of order"):
        parse_syllabus(mutated)


LAST_UPDATED = "<li>Last updated on 2026-11-05</li>"
GLANCE_HEADING = '<h3 id="skills-at-a-glance">Skills at a glance</h3>'
FIRST_DOMAIN = '<h3 id="plan-and-manage-an-azure-ai-solution-2530">'
SECOND_DOMAIN = '<h3 id="implement-generative-ai-and-agentic-solutions-3035">'
SECOND_SKILL = '<h4 id="secure-and-monitor-ai-workloads">'
CLOSING = '<h2 id="study-resources">Study resources</h2>'
LAST_ITEM = "Combine OCR with layout analysis and field extraction</p>\n</li>\n"
GLANCE_LIST = re.compile(rf"{GLANCE_HEADING}.*?(?={FIRST_DOMAIN})", flags=re.DOTALL)


def _glance_after_first_domain(html: str) -> str:
    glance = GLANCE_LIST.search(html)
    assert glance
    return GLANCE_LIST.sub("", html).replace(SECOND_DOMAIN, glance[0] + SECOND_DOMAIN)


BOUNDARIES: list[tuple[str, Callable[[str], str], str]] = [
    (
        "h2-before-glance",
        lambda h: h.replace(GLANCE_HEADING, "<h2>Notes</h2>" + GLANCE_HEADING),
        "unexpected h2 .*Notes",
    ),
    (
        "h2-before-first-domain",
        lambda h: h.replace(FIRST_DOMAIN, "<h2>Notes</h2>" + FIRST_DOMAIN),
        "unexpected h2 .*Notes",
    ),
    (
        "h2-between-domains",
        lambda h: h.replace(SECOND_DOMAIN, "<h2>Notes</h2>" + SECOND_DOMAIN),
        "unexpected h2 .*Notes",
    ),
    (
        "h2-between-skills",
        lambda h: h.replace(SECOND_SKILL, "<h2>Notes</h2>" + SECOND_SKILL),
        "unexpected h2 .*Notes",
    ),
    (
        "h2-after-all-objectives",
        lambda h: h.replace(CLOSING, "<h2>Notes</h2>" + CLOSING),
        "unexpected h2 .*Notes",
    ),
    (
        "h2-inside-list",
        lambda h: h.replace(BULLET, "<h2>Notes</h2>" + BULLET),
        "unexpected h2 .*Notes",
    ),
    (
        "closing-heading-renamed",
        lambda h: h.replace(CLOSING, "<h2>Learning paths</h2>"),
        "unexpected h2 .*Learning paths",
    ),
    (
        "closing-heading-early-then-domain",
        lambda h: h.replace(SECOND_DOMAIN, "<h2>Study resources</h2>" + SECOND_DOMAIN),
        "unexpected h3 after the syllabus section",
    ),
    (
        "closing-heading-early-then-bullets",
        lambda h: h.replace(BULLET, f"</ul><h2>Study resources</h2><ul>{BULLET}"),
        "unexpected li after the syllabus section",
    ),
    (
        "heading-after-closing",
        lambda h: h.replace(CLOSING, CLOSING + "<h4>Late skill</h4>"),
        "unexpected h4 after the syllabus section",
    ),
    (
        "heading-after-later-section",
        lambda h: h.replace("</main>", "<h4>Late skill</h4></main>"),
        "unexpected h4 after the syllabus section",
    ),
    (
        "h1-after-closing",
        lambda h: h.replace(CLOSING, CLOSING + "<h1>Late</h1>"),
        "unexpected h1 after the syllabus section",
    ),
    (
        "unknown-section-after-closing",
        lambda h: h.replace(CLOSING, CLOSING + "<h2>Learning paths</h2>"),
        "unexpected h2 after the syllabus section: 'Learning paths'",
    ),
    (
        "unknown-section-after-additional",
        lambda h: h.replace("</main>", "<h2>Feedback</h2></main>"),
        "unexpected h2 after the syllabus section: 'Feedback'",
    ),
    (
        "additional-section-renamed",
        lambda h: h.replace(">Additional resources</h2>", ">More resources</h2>"),
        "unexpected h2 after the syllabus section: 'More resources'",
    ),
    (
        "additional-section-repeated",
        lambda h: h.replace("</main>", "<h2>Additional resources</h2></main>"),
        "unexpected h2 after the syllabus section",
    ),
    (
        "closing-section-repeated",
        lambda h: h.replace(CLOSING, CLOSING + "<h2>Study resources</h2>"),
        "unexpected h2 after the syllabus section",
    ),
    (
        "sections-in-wrong-order",
        lambda h: h.replace(CLOSING, "<h2>Additional resources</h2>" + CLOSING),
        "unexpected h2 in syllabus section: 'Additional resources'",
    ),
    (
        "bullet-in-closing-section",
        lambda h: h.replace(CLOSING, CLOSING + "<ul><li>An objective</li></ul>"),
        "unexpected li after the syllabus section: 'An objective'",
    ),
    (
        "objective-bullet-in-additional",
        lambda h: h.replace(LAST_UPDATED, LAST_UPDATED + "<li>An objective</li>"),
        "unexpected li after the syllabus section: 'An objective'",
    ),
    (
        "objective-starting-like-the-date-bullet",
        lambda h: h.replace(LAST_UPDATED, "<li>Last updated on an objective</li>"),
        "unexpected li after the syllabus section",
    ),
    (
        "paragraph-in-additional",
        lambda h: h.replace("</main>", "<p>An objective</p></main>"),
        "unexpected p after the syllabus section: 'An objective'",
    ),
    (
        "bare-text-in-additional",
        lambda h: h.replace("</main>", "An objective</main>"),
        "unexpected text after the syllabus section: 'An objective'",
    ),
    (
        "table-in-additional",
        lambda h: h.replace(
            "</main>", "<table><tr><td>An objective</td></tr></table></main>"
        ),
        "unexpected table-text after the syllabus section: 'An objective'",
    ),
    (
        "second-audience",
        lambda h: h.replace(
            GLANCE_HEADING, "<h3>Audience profile</h3>" + GLANCE_HEADING
        ),
        "'Audience profile' .*out of order",
    ),
    (
        "audience-after-glance",
        lambda h: h.replace(FIRST_DOMAIN, "<h3>Audience profile</h3>" + FIRST_DOMAIN),
        "'Audience profile' .*out of order",
    ),
    (
        "second-glance",
        lambda h: h.replace(FIRST_DOMAIN, "<h3>Skills at a glance</h3>" + FIRST_DOMAIN),
        "'Skills at a glance' .*out of order",
    ),
    (
        "glance-after-domain",
        _glance_after_first_domain,
        "'Skills at a glance' .*out of order",
    ),
]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [case[1:] for case in BOUNDARIES],
    ids=[case[0] for case in BOUNDARIES],
)
def test_rejects_invalid_section_transitions(
    baseline_html: str, mutate: Callable[[str], str], message: str
) -> None:
    mutated = mutate(baseline_html)
    assert mutated != baseline_html
    with pytest.raises(SyllabusError, match=message):
        parse_syllabus(mutated)


@pytest.mark.parametrize(
    ("headings", "message"),
    [
        ("<h2>Study resources</h2><h2>Notes</h2>", "unexpected h2 .*Notes"),
        (
            "<h2 hidden>Study resources</h2><h2 hidden>Notes</h2>",
            "unexpected h2 .*Notes",
        ),
        ("<h2>Study resources</h2><h2>Study resources</h2>", "unexpected h2 "),
        (
            "<h2>Study resources</h2><h2>Additional resources</h2>",
            "unexpected li .*Subskill 5.2.1",
        ),
        (
            "<h2 hidden>Study resources</h2><h2 hidden>Additional resources</h2>",
            "unexpected li .*Subskill 5.2.1",
        ),
        ("<h2>Additional resources</h2>", "unexpected h2 in syllabus section"),
    ],
)
def test_early_closing_headings_cannot_strand_objectives(
    headings: str, message: str
) -> None:
    with pytest.raises(SyllabusError, match=message):
        parse_syllabus(last_skill_list_after(official_shape_page(), headings))


# The closing markup of the live page, which is only page chrome.
LIVE_CLOSING_SECTION = """<div class="display-none-print"><hr class="hr" hidden />
<h2 id="ms--additional-resources-mobile-heading" class="title is-3" hidden>
    Additional resources
</h2>
<section id="right-rail-recommendations-mobile" hidden></section>
<section id="right-rail-training-mobile" hidden></section>
<section id="right-rail-events-mobile" hidden></section>
</div>
<div id="article-metadata-footer" class="page-metadata-container">
<hr class="hr" />
<ul class="metadata page-metadata" data-bi-name="page info" lang="en-us" dir="ltr">
    <li class="visibility-hidden-visual-diff">
        <span class="badge badge-sm text-wrap-pretty">
            <span>Last updated on <local-time format="twoDigitNumeric"
                datetime="2026-10-31T01:16:00.000Z" class="is-invisible"
            >
                2026-10-31
            </local-time></span>
        </span>
    </li>
</ul>
</div>
"""
ADDITIONAL_SECTION = re.compile(r'<h2 id="ms--additional.*?(?=</main>)', re.DOTALL)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda h: ADDITIONAL_SECTION.sub(lambda _: LIVE_CLOSING_SECTION, h),
        lambda h: ADDITIONAL_SECTION.sub("", h),
        lambda h: h.replace(LAST_UPDATED, ""),
        lambda h: h.replace("2026-11-05", "2030-01-31"),
        lambda h: h.replace(CLOSING, CLOSING + "<p>Intro</p><div><hr></div>"),
    ],
    ids=[
        "live-page-markup",
        "no-additional-section",
        "no-date-bullet",
        "different-date",
        "prose-in-closing-section",
    ],
)
def test_legitimate_closing_sections_are_allowed(
    baseline_html: str, mutate: Callable[[str], str]
) -> None:
    mutated = mutate(baseline_html)
    assert mutated != baseline_html
    assert parse_syllabus(mutated) == parse_syllabus(baseline_html)


def test_syllabus_hash_is_stable_for_unchanged_source(baseline_html: str) -> None:
    assert content_hash(parse_syllabus(baseline_html)) == (
        "c2c641c5cc1e1c39a54a0dc8d91c06afacb6aec49d9ab7b9e0974cb53255bea7"
    )


STUDY = "<h2>Study resources</h2>"


def _before_last_skill(inserted: str) -> Callable[[str], str]:
    return lambda p: p.replace(LAST_SKILL_HEADING, inserted + LAST_SKILL_HEADING)


def _moved_close(inserted: str) -> Callable[[str], str]:
    """Insert before the last skill and remove the real close, so the tags still balance."""
    return lambda p: _before_last_skill(inserted)(p.replace("</main>", ""))


def _wrapped_in_div(page: str) -> str:
    return page.replace("<main>", "<main><div>").replace("</main>", "</div></main>")


MAIN_BOUNDARIES: list[tuple[str, Callable[[str], str], str]] = [
    # Case 1: a premature close.
    ("premature-close", _before_last_skill(f"{STUDY}</main>"), "expected one <main>"),
    (
        "premature-close-real-close-removed",
        _moved_close(f"{STUDY}</main>"),
        "outside the main content: 'Skill 5.2'",
    ),
    (
        "premature-close-inside-open-element",
        lambda p: _moved_close(f"{STUDY}</main>")(_wrapped_in_div(p)),
        "<div> is still open at </main>",
    ),
    (
        "premature-close-then-bullets-only",
        lambda p: last_skill_list_after(p.replace("</main>", ""), f"{STUDY}</main>"),
        "outside the main content: 'Subskill 5.2.1'",
    ),
    (
        "stray-close-before-main",
        lambda p: p.replace("<main>", "</main><main>"),
        "expected one",
    ),
    (
        "second-close-at-end",
        lambda p: p.replace("</main>", "</main></main>"),
        "expected one",
    ),
    # Case 2: an unclosed heading.
    (
        "unclosed-heading",
        _before_last_skill("<h2>Study resources</main>"),
        "expected one <main>",
    ),
    (
        "unclosed-heading-real-close-removed",
        _moved_close("<h2>Study resources</main>"),
        "<h2> is still open at </main>",
    ),
    (
        "unclosed-skill-heading",
        _moved_close("<h4>A new skill</main>"),
        "page ends inside the syllabus section",
    ),
    # Case 3: nested and duplicate main elements.
    (
        "nested-and-closed",
        _before_last_skill(f"{STUDY}<main></main>"),
        "expected one <main>",
    ),
    ("nested-left-open", _before_last_skill(f"{STUDY}<main>"), "expected one <main>"),
    (
        "nested-real-close-removed",
        _moved_close(f"{STUDY}<main></main>"),
        "expected one <main>",
    ),
    (
        "nested-around-content",
        lambda p: p.replace("<main>", "<main><main>"),
        "expected one",
    ),
    (
        "uppercase-nested",
        _before_last_skill(f"{STUDY}<MAIN></MAIN>"),
        "expected one <main>",
    ),
    (
        "duplicate-before",
        lambda p: p.replace("<main>", "<main></main><main>"),
        "expected one",
    ),
    (
        "duplicate-after",
        lambda p: p.replace("</main>", "</main><main></main>"),
        "expected one",
    ),
    # Other syllabus content stranded outside a correctly closed main.
    (
        "weighted-domain-after-main",
        lambda p: p.replace("</main>", "</main><h3>Domain 6 (10–15%)</h3>"),
        "outside the main content: 'Domain 6",
    ),
    (
        "skill-after-main",
        lambda p: p.replace("</main>", "</main><h4>A skill</h4>"),
        "outside the main content: 'A skill'",
    ),
    (
        "plain-bullet-after-main",
        lambda p: p.replace("</main>", "</main><ul><li>An objective</li></ul>"),
        "outside the main content: 'An objective'",
    ),
    (
        "paragraph-after-main",
        lambda p: p.replace("</main>", "</main><p>An objective</p>"),
        "outside the main content: 'An objective'",
    ),
    (
        "skill-before-main",
        lambda p: p.replace(
            "<main>", "<h4>A skill</h4><ul><li>An objective</li></ul><main>"
        ),
        "outside the main content: 'A skill'",
    ),
    (
        "plain-bullet-before-main",
        lambda p: p.replace("<main>", "<ul><li>An objective</li></ul><main>"),
        "outside the main content: 'An objective'",
    ),
    # Elements left open or closed twice by a moved boundary.
    (
        "list-left-open-at-close",
        lambda p: p.replace(
            "Additional resources</h2><ul>", "Additional resources</h2><ul><ul>"
        ),
        "<ul> is still open at </main>",
    ),
    (
        "stray-closing-element",
        lambda p: p.replace("</main>", "</div></main>"),
        "</div> has no matching open element",
    ),
]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [case[1:] for case in MAIN_BOUNDARIES],
    ids=[case[0] for case in MAIN_BOUNDARIES],
)
def test_rejects_invalid_main_boundaries(
    mutate: Callable[[str], str], message: str
) -> None:
    page = official_shape_page()
    assert parse_syllabus(page)
    mutated = mutate(page)
    assert mutated != page
    with pytest.raises(SyllabusError, match=message):
        parse_syllabus(mutated)


LAST_BULLET = "<li><p>Subskill 5.2.3</p></li></ul>"
CLOSING_HEADING = "<h2>Study resources</h2>"


def _truncated_by(opening: str, closing: str) -> Callable[[str], str]:
    """Open an element inside the last bullet and close it in the closing section's intro,
    where prose is allowed, so only the crossed nesting can reveal the moved tail.
    """

    def mutate(page: str) -> str:
        cut_at = f"{LAST_BULLET}\n{CLOSING_HEADING}<p>"
        assert cut_at in page
        return page.replace(
            cut_at,
            f"<li><p>{opening}Subskill</p></li></ul>\n{CLOSING_HEADING}"
            f"<p>5.2.3{closing} ",
        )

    return mutate


CROSSED: list[tuple[str, Callable[[str], str], str]] = [
    # The "Implement analyzers" truncation: balanced tags, but crossed.
    ("span", _truncated_by("<span>", "</span>"), "<span> is still open at </p>"),
    (
        "strong",
        _truncated_by("<strong>", "</strong>"),
        "<strong> is still open at </p>",
    ),
    ("anchor", _truncated_by("<a href=x>", "</a>"), "<a> is still open at </p>"),
    (
        "crossed-inline-keeping-text",
        lambda p: p.replace("Subskill 5.2.3", "<b><i>Subskill 5.2.3</b></i>"),
        "<i> is still open at </b>",
    ),
    (
        "list-closed-inside-open-span",
        lambda p: p.replace(LAST_BULLET, "<li><span>Subskill 5.2.3</ul></span>"),
        "<span> is still open at </ul>",
    ),
    (
        "stray-paragraph-close",
        lambda p: p.replace(LAST_BULLET, "<li>Subskill 5.2.3</p></li></ul>"),
        "</p> has no matching open element",
    ),
    (
        "stray-inline-close",
        lambda p: p.replace(LAST_BULLET, "<li>Subskill 5.2.3</b></li></ul>"),
        "</b> has no matching open element",
    ),
    (
        "unclosed-skill-heading-before-list",
        lambda p: p.replace("<h4>Skill 5.2</h4>", "<h4>Skill 5.2"),
        "<h4> is still open at </main>",
    ),
]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [case[1:] for case in CROSSED],
    ids=[case[0] for case in CROSSED],
)
def test_rejects_crossed_or_prematurely_closed_elements(
    mutate: Callable[[str], str], message: str
) -> None:
    page = official_shape_page()
    mutated = mutate(page)
    assert mutated != page
    with pytest.raises(SyllabusError, match=message):
        parse_syllabus(mutated)


def _linked_objective_after_main(wrapper: str, page: str) -> str:
    """Move the last objective out of main as a link, taking 64 down to 63."""
    moved = "<li><a href='#'>Subskill 5.2.3</a></li>"
    return page.replace("<li><p>Subskill 5.2.3</p></li>", "").replace(
        "</main>", "</main>" + wrapper.format(moved)
    )


def test_linked_objective_leaves_a_valid_looking_syllabus_behind() -> None:
    """Pins what Codex found: without the moved bullet, 63 objectives still validate."""
    remaining = official_shape_page().replace("<li><p>Subskill 5.2.3</p></li>", "")
    assert _shape(remaining) == (14, 63)


@pytest.mark.parametrize(
    "wrapper",
    [
        pytest.param("<ul>{}</ul>", id="bare-list"),
        pytest.param("<div><ul>{}</ul></div>", id="in-div"),
        pytest.param("<aside><ul>{}</ul></aside>", id="in-aside"),
        pytest.param("<nav><ul>{}</ul></nav>", id="in-nav"),
        pytest.param("<header><ul>{}</ul></header>", id="in-header"),
        pytest.param("<footer><ul>{}</ul></footer>", id="in-footer-other-list"),
        pytest.param(
            '<ul data-bi-name="footerlinks">{}</ul>',
            id="footer-list-name-outside-footer",
        ),
        pytest.param(
            '<footer><ul data-bi-name="other">{}</ul></footer>',
            id="in-footer-wrong-list",
        ),
        pytest.param(
            "<footer><div role=menu><ul>{}</ul></div></footer>", id="link-in-theme-menu"
        ),
    ],
)
def test_linked_objective_is_rejected_outside_its_structural_context(
    wrapper: str,
) -> None:
    with pytest.raises(
        SyllabusError, match="outside the main content: 'Subskill 5.2.3'"
    ):
        parse_syllabus(_linked_objective_after_main(wrapper, official_shape_page()))


@pytest.mark.parametrize(
    ("before", "after", "message"),
    [
        ("<nav><ul><li><a href=x>Item</a></li></ul></nav>", "", "li outside .*Item"),
        ("<h2>Menu</h2>", "", "h2 outside .*Menu"),
        ("<nav><h1>Menu</h1></nav>", "", "h1 outside .*Menu"),
        ("<p>A paragraph</p>", "", "p outside .*A paragraph"),
        ("<div id=other><p>A paragraph</p></div>", "", "p outside .*A paragraph"),
        ("", '<div id="unsupported-browser"><p>Note</p></div>', "p outside .*Note"),
        ("", "<h3>In this article</h3>", "h3 outside .*In this article"),
        ("", "<aside><h3>Other</h3></aside>", "h3 outside .*Other"),
        ("", "<aside><h4>In this article</h4></aside>", "h4 outside .*In this article"),
        ("", "<footer><p>A paragraph</p></footer>", "p outside .*A paragraph"),
        ("", _footer("<li>A plain bullet</li>"), "li outside .*A plain bullet"),
        ("", _footer("<li><button>Light</button></li>"), "li outside .*Light"),
        (
            "",
            "<footer><div role=menu><ul><li>Plain</li></ul></div></footer>",
            "li outside .*Plain",
        ),
    ],
)
def test_rejects_content_outside_main_without_its_structural_context(
    before: str, after: str, message: str
) -> None:
    page = official_shape_page().replace("<main>", f"{before}<main>")
    with pytest.raises(SyllabusError, match=message):
        parse_syllabus(page.replace("</main>", f"</main>{after}"))


# The markup around <main> on the live page, which is only page chrome.
LIVE_PAGE_CHROME_BEFORE_MAIN = """<header><div>
    <a href="#main">Skip to main content</a>
    <div id="unsupported-browser" hidden>
    <p>This browser is no longer supported.</p><p>Upgrade to a newer one.</p>
    <div><a href="https://example.test/edge">Download Microsoft Edge</a></div></div>
</div></header>
<header class="layout-body-header"></header><nav data-bi-name="x"></nav>"""
LIVE_PAGE_CHROME_AFTER_MAIN = """<aside id="layout-body-aside" data-bi-name="aside">
    <div id="ms--additional-resources" data-bi-name="pageactions">
    <div id="affixed-right-container" data-bi-name="right-column">
    <nav id="side-doc-outline" data-bi-name="intopic toc"><h3>In this article</h3></nav>
    </div></div>
</aside>
<div data-bi-name="layout-footer">
<footer id="footer" data-bi-name="footer" role="contentinfo">
    <a href="#" data-bi-name="select-locale">Locale</a>
    <div class="dropdown-menu" id="{{ themeMenuId }}" role="menu">
        <ul class="theme-selector" role="none">
            <li role="presentation"><button role="menuitem"><span>Light</span></button></li>
            <li role="presentation"><button role="menuitem"><span>Dark</span></button></li>
        </ul>
    </div>
    <ul class="links" data-bi-name="footerlinks">
        <li class="manage-cookies-holder" hidden=""></li>
        <li><a href="https://example.test/ai" data-bi-name="aiDisclaimer">AI Disclaimer</a></li>
        <li><a href="https://example.test/blog" data-bi-name="bloglink">Blog</a></li>
        <li>© Microsoft 2026</li>
    </ul>
</footer></footer>
</div>"""


def test_live_page_chrome_around_main_is_allowed() -> None:
    page = official_shape_page()
    framed = page.replace("<main>", f"{LIVE_PAGE_CHROME_BEFORE_MAIN}<main>").replace(
        "</main>", f"</main>{LIVE_PAGE_CHROME_AFTER_MAIN}"
    )
    assert parse_syllabus(framed) == parse_syllabus(page)


TAIL = "5.2.3"
WHOLE_OBJECTIVE = "Subskill 5.2.3</p></li></ul>"
CUT_OBJECTIVE = "Subskill</p></li></ul>"


def _tail_inside_bullet(token: str) -> Callable[[str], str]:
    """Keep the tail in the bullet, inside a token the HTML parser never reports as text."""
    return lambda p: p.replace("Subskill 5.2.3<", f"Subskill {token}<")


def _tail_moved(old: str, new: str) -> Callable[[str], str]:
    """Cut the tail out of the last objective and leave it elsewhere on the page."""
    return lambda p: p.replace(WHOLE_OBJECTIVE, CUT_OBJECTIVE).replace(old, new, 1)


TAIL_LOSS: list[tuple[str, Callable[[str], str], str]] = [
    ("comment", _tail_inside_bullet(f"<!-- {TAIL} -->"), "unexpected hidden .*5.2.3"),
    (
        "comment-bang-close",
        _tail_inside_bullet(f"<!-- {TAIL} --!>"),
        "unexpected hidden .*5.2.3",
    ),
    ("declaration", _tail_inside_bullet(f"<!{TAIL}>"), "unexpected hidden .*5.2.3"),
    (
        "processing-instruction",
        _tail_inside_bullet(f"<?{TAIL}>"),
        "unexpected hidden .*5.2.3",
    ),
    ("cdata", _tail_inside_bullet(f"<![CDATA[{TAIL}]]>"), "unexpected hidden .*5.2.3"),
    ("bogus-end-tag", _tail_inside_bullet(f"</ {TAIL}>"), "unexpected hidden .*5.2.3"),
    (
        "stray-comment-open-swallows-next-bullet",
        lambda p: p.replace(
            "Subskill 5.2.2</p></li>", "Subskill 5.2.2 <!--</p></li>"
        ).replace("Subskill 5.2.3</p>", "--></p>"),
        "unexpected hidden .*<!--</p></li>",
    ),
    (
        "stray-comment-between-bullets",
        lambda p: p.replace(
            "<li><p>Subskill 5.2.3</p></li>", "<!--<li><p>Subskill 5.2.3</p></li>-->"
        ),
        "unexpected hidden .*Subskill 5.2.3",
    ),
    (
        "unterminated-attribute-quote",
        lambda p: p.replace(
            "<li><p>Subskill 5.2.2</p>",
            '<li><p>Subskill <span class="a 5.2.2</span></p>',
        ).replace("Subskill 5.2.3<", 'Subskill <span class="b">5.2.3</span><'),
        "unexpected hidden .*5.2.2",
    ),
    (
        "bare-text-after-closing-heading",
        _tail_moved(STUDY, f"{STUDY} {TAIL}"),
        "unexpected text after the syllabus section: '5.2.3'",
    ),
    (
        "inline-after-closing-heading",
        _tail_moved(STUDY, f"{STUDY}<span>{TAIL}</span>"),
        "unexpected text after the syllabus section: '5.2.3'",
    ),
    (
        "div-after-closing-heading",
        _tail_moved(STUDY, f"{STUDY}<div>{TAIL}</div>"),
        "unexpected text after the syllabus section: '5.2.3'",
    ),
    (
        "paragraph-after-closing-heading",
        _tail_moved(STUDY, f"{STUDY}<p>{TAIL}</p>"),
        "unexpected p after the syllabus section",
    ),
    (
        "paragraph-after-intro",
        _tail_moved("</p>\n<table>", f"</p><p>{TAIL}</p>\n<table>"),
        "unexpected p after the syllabus section: '5.2.3'",
    ),
    (
        "bare-text-after-main",
        _tail_moved("</main>", f"</main>{TAIL}"),
        "text outside the main content: '5.2.3'",
    ),
    (
        "div-after-main",
        _tail_moved("</main>", f"</main><div>{TAIL}</div>"),
        "text outside the main content: '5.2.3'",
    ),
    (
        "link-after-main",
        _tail_moved("</main>", f"</main><a href=x>{TAIL}</a>"),
        "text outside the main content: '5.2.3'",
    ),
    (
        "span-before-main",
        _tail_moved("<main>", f"<span>{TAIL}</span><main>"),
        "text outside the main content: '5.2.3'",
    ),
    (
        "link-in-aside",
        _tail_moved("</main>", f"</main><aside><a href=x>{TAIL}</a></aside>"),
        "text outside the main content: '5.2.3'",
    ),
]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [case[1:] for case in TAIL_LOSS],
    ids=[case[0] for case in TAIL_LOSS],
)
def test_rejects_objective_tail_lost_to_malformed_markup(
    mutate: Callable[[str], str], message: str
) -> None:
    page = official_shape_page()
    mutated = mutate(page)
    assert mutated != page
    with pytest.raises(SyllabusError, match=message):
        parse_syllabus(mutated)


def test_objective_tail_cut_alone_is_a_valid_looking_syllabus() -> None:
    """Pins why the moved tail must be caught: what remains parses, one word short."""
    syllabus = parse_syllabus(
        official_shape_page().replace(WHOLE_OBJECTIVE, CUT_OBJECTIVE)
    )
    assert syllabus.domains[-1].skills[-1].subskills[-1] == "Subskill"


def _accepted(pages: Iterable[tuple[int, str]]) -> list[int]:
    accepted = []
    for cut, page in pages:
        try:
            parse_syllabus(page)
        except SyllabusError:
            continue
        accepted.append(cut)
    return accepted


def _cut_points(raw: bytes, end: int) -> list[int]:
    """Each side of every tag delimiter, where the parser's state can change."""
    delimiters = [m.start() for m in re.finditer(rb"[<>]", raw[:end])]
    return sorted({4502, *delimiters, *(d + 1 for d in delimiters)})


@pytest.mark.parametrize(
    "fixture",
    ["ai103_baseline.html", "ai103_html_churn.html", "ai103_modified.html"],
)
def test_no_truncation_before_main_closes_is_accepted(fixture: str) -> None:
    """A complete-looking prefix used to pass: 836 cut points in the baseline alone."""
    raw = load_fixture(fixture).encode()
    main_end = raw.index(b"</main>") + len(b"</main>")
    cuts = [cut for cut in _cut_points(raw, main_end) if cut < main_end]

    assert not _accepted((cut, raw[:cut].decode(errors="ignore")) for cut in cuts)
    assert parse_syllabus(raw[:main_end].decode()) == parse_syllabus(raw.decode())


def test_truncated_page_is_rejected_even_if_something_closes_its_tags() -> None:
    raw = load_fixture("ai103_baseline.html").encode()
    syllabus_end = raw.index(b'<h2 id="study-resources"')
    cuts = [cut for cut in _cut_points(raw, syllabus_end) if cut < syllabus_end]

    assert not _accepted(
        (cut, raw[:cut].decode(errors="ignore") + "</ul></div></main></body></html>")
        for cut in cuts
    )


def test_subskill_count_is_not_fixed(baseline_html: str) -> None:
    """Completeness comes from page structure, so the syllabus may grow or shrink."""

    def count(html: str) -> int:
        domains = parse_syllabus(html).domains
        return sum(len(skill.subskills) for d in domains for skill in d.skills)

    item = "<li><p>Select a retrieval and indexing approach</p>\n</li>\n"
    assert item in baseline_html
    assert count(baseline_html) == 18
    assert count(baseline_html.replace(item, "")) == 17
    assert count(baseline_html.replace(item, item + "<li><p>A new one</p></li>")) == 19
