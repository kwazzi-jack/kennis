"""Tags as the window draws them (#627, sketch 2026-11-06-tag-colours-and-
tab, parts c, s and b).

Each tag wears one of eight measured colours, its name always written; a
hit card shows the tags on its passage and on its document; a bookmark tab
on the card's edge holds Open, Tag and Copy citation; a tag's page chooses
its colour.
"""

from __future__ import annotations

import itertools
import math
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import pytest
from bs4 import BeautifulSoup, Tag

from kennis.engine.context.bundle import init_bundle
from kennis.engine.tags import TAG_COLOURS, TAGS_FILENAME, colour_of, read_store
from kennis.gui import words
from kennis.gui.theme import TAG_COLOURS as TAG_COLOUR_VALUES
from kennis.gui.theme import stylesheet
from kennis.links import link_to
from test_cli_tags import PAPER_ID, SOLVING, chunk_holding, indexed_paper, run
from test_gui_collection_colours import (
    THEMES,
    _contrast,
    _deuteranope,
    _lab,
    _raised,
    _rgb,
)
from test_gui_tags import opened, page_of

if TYPE_CHECKING:
    from kennis.render.html import Band, RunHtml

STATIC = Path(__file__).parent.parent / "src" / "kennis" / "gui" / "static"


# ---------------------------------------------------------------------------
# The colours, measured


def _mixed(
    fore: tuple[float, float, float], back: tuple[float, float, float], share: float
) -> tuple[float, float, float]:
    red, green, blue = (
        share * one + (1 - share) * other for one, other in zip(fore, back, strict=True)
    )
    return red, green, blue


def test_the_window_draws_every_colour_the_engine_stores():
    assert tuple(TAG_COLOUR_VALUES) == TAG_COLOURS
    assert all(set(themes) == set(THEMES) for themes in TAG_COLOUR_VALUES.values())


@pytest.mark.parametrize("theme", sorted(THEMES))
def test_each_colour_is_seen_on_the_ground_and_on_a_card(theme: str):
    """A border and a dot are not text: 3:1 is what they need."""
    ground, palette = THEMES[theme]
    surfaces = (_rgb(ground), _raised(ground, palette["bright_black"]))

    for name, themes in TAG_COLOUR_VALUES.items():
        for surface in surfaces:
            assert _contrast(_rgb(themes[theme]), surface) >= 3, (name, theme)


@pytest.mark.parametrize("theme", sorted(THEMES))
def test_a_name_in_ink_is_legible_on_its_chip_at_rest_and_pointed_at(theme: str):
    ground, palette = THEMES[theme]
    ink = _rgb(palette["white"])
    for name, themes in TAG_COLOUR_VALUES.items():
        for share in (0.12, 0.24):
            tint = _mixed(_rgb(themes[theme]), _rgb(ground), share)
            assert _contrast(ink, tint) >= 4.5, (name, theme, share)


@pytest.mark.parametrize("theme", sorted(THEMES))
def test_every_pair_is_apart_and_none_merges_for_a_deuteranope(theme: str):
    """dE 25 for everyone; for a deuteranope eight hues cannot all stay
    apart, so only that no two become one (dE 5), and the name is always
    written."""
    for (one, first), (other, second) in itertools.combinations(
        TAG_COLOUR_VALUES.items(), 2
    ):
        a, b = _rgb(first[theme]), _rgb(second[theme])
        assert math.dist(_lab(a), _lab(b)) >= 25, (one, other, theme)
        seen = math.dist(_lab(_deuteranope(a)), _lab(_deuteranope(b)))
        assert seen >= 5, (one, other, theme, seen)


def test_each_theme_carries_every_colour_and_one_attribute_chooses_it():
    code = re.sub(r"/\*.*?\*/", "", stylesheet(), flags=re.S)
    for name, themes in TAG_COLOUR_VALUES.items():
        for value in themes.values():
            assert f"--tag-{name}: {value};" in code, (name, value)
        assert re.search(
            rf'\[data-tag-colour="{name}"\] \{{\s*--tag: var\(--tag-{name}\);', code
        ), name


# ---------------------------------------------------------------------------
# A hit card


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return indexed_paper(tmp_path, monkeypatch)


def card_for(page: BeautifulSoup, link: str) -> Tag:
    """The card whose bookmark tab tags `link`."""
    for card in page.select("li.hit"):
        tagging = card.select_one(".bookmark-items a[href^='/tags/add']")
        if tagging is not None and link.replace("://", "%3A//") in str(tagging["href"]):
            return card
    raise AssertionError(f"no card for {link}")


def chips_of(card: Tag) -> list[tuple[str, str, bool]]:
    return [
        (
            chip.get_text(strip=True),
            str(chip["data-tag-colour"]),
            chip.has_attr("data-whole"),
        )
        for chip in card.select(".hit-tags .tag-chip")
    ]


def test_a_card_shows_its_passage_s_tags_and_its_document_s(corpus: Path):
    solving = chunk_holding(corpus, SOLVING)
    run("tag", "calibration", f"id={PAPER_ID}", f"chunk={solving}")
    run("tag", "to-read", f"id={PAPER_ID}")
    run("tag", "to-read", "--colour", "blue")

    page = page_of(opened(), "/?q=gains+solved+visibilities+flagged&scope=literature")

    card = card_for(page, link_to(PAPER_ID, solving))
    assert chips_of(card) == [
        ("calibration", colour_of("calibration", {}), False),
        ("to-read", "blue", True),
    ]
    others = [
        chips_of(other)
        for other in page.select("li.hit")
        if other is not card and other.select_one(".bookmark")
    ]
    assert others and all(chips == [("to-read", "blue", True)] for chips in others)


def test_a_card_whose_chunk_holds_other_words_now_shows_no_tag(corpus: Path):
    """A detached passage keeps its hint; the chunk now at that number must
    not wear the tag."""
    solving = chunk_holding(corpus, SOLVING)
    run("tag", "calibration", f"id={PAPER_ID}", f"chunk={solving}")
    paper = corpus / "literature" / "smirnov.md"
    paper.write_text(
        paper.read_text(encoding="utf-8").replace(
            "The gains were solved for per antenna", "The gains were fitted per antenna"
        ),
        encoding="utf-8",
    )
    run("corpus", "index")

    page = page_of(opened(), "/?q=gains+fitted+antenna&scope=literature")

    assert chips_of(card_for(page, link_to(PAPER_ID, solving))) == []


def test_a_project_s_card_follows_its_passage_after_an_edit(
    corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A project's hints are rewritten only when its tags change, so the
    window places its passages itself."""
    root = tmp_path / "pipelines"
    (root / ".git").mkdir(parents=True)
    init_bundle(root)
    ours = root / ".context" / "ours.md"
    solving = (
        "## Solving\n\nWe solve the gains per scan, with a prior that keeps "
        "neighbouring intervals close and a reference antenna fixed.\n"
    )
    ours.write_text(f"---\ntitle: Ours\n---\n{solving}", encoding="utf-8")
    monkeypatch.chdir(root)
    run("context", "index")
    run("tag", "mine", "path=.context/ours.md", "chunk=0")
    ours.write_text(
        "---\ntitle: Ours\n---\n## First\n\nA section inserted ahead of the "
        "solving section, long enough to be a chunk of its own when the chunks "
        f"are small.\n\n{solving}",
        encoding="utf-8",
    )
    run("context", "index")

    page = page_of(opened(), "/?q=gains+per+scan+prior&scope=context")

    tagged = [card for card in page.select("li.hit") if chips_of(card)]
    assert len(tagged) == 1
    assert "We solve the gains" in tagged[0].get_text()
    assert chips_of(tagged[0])[0][0] == "mine"


# ---------------------------------------------------------------------------
# The bookmark tab


def test_the_tab_holds_open_tag_and_copy_passage_in_that_order(corpus: Path):
    solving = chunk_holding(corpus, SOLVING)
    page = page_of(opened(), "/?q=gains+solved&scope=literature")

    card = card_for(page, link_to(PAPER_ID, solving))
    tab = card.select_one(".bookmark .bookmark-tab")
    entries = card.select(".bookmark-items .item")

    assert tab is not None and tab["aria-label"] == words.PASSAGE_ACTIONS
    assert [entry.get_text(strip=True) for entry in entries] == [
        words.OPEN_AT_PASSAGE,
        words.TAG_PASSAGE,
        words.COPY_PASSAGE,
    ]
    assert all(entry.find("svg") is not None for entry in entries)
    assert card.select_one(".hit-head .tag-hit") is None


def test_a_tagged_passage_s_tab_wears_its_first_tag_s_colour(corpus: Path):
    solving = chunk_holding(corpus, SOLVING)
    run("tag", "calibration", f"id={PAPER_ID}", f"chunk={solving}", "--colour", "pink")

    page = page_of(opened(), "/?q=gains+solved&scope=literature")

    card = card_for(page, link_to(PAPER_ID, solving))
    assert card["data-tag-colour"] == "pink"
    tab = card.select_one(".bookmark-tab")
    assert tab is not None and tab.has_attr("data-tagged")


OPENING = (
    "The gains were solved for per antenna and per interval, with a prior that "
    "keeps neighbouring"
)


def test_copy_passage_is_the_words_in_quotes_then_the_style_s_citation(corpus: Path):
    """The whole chunk, its heading passed over, in typographic quotation
    marks, then the in-text citation `kennis cite` writes with its locator
    (Brian, 2026-11-06)."""
    solving = chunk_holding(corpus, SOLVING)
    client = opened()
    card = card_for(
        page_of(client, "/?q=gains+solved&scope=literature"), link_to(PAPER_ID, solving)
    )
    entry = card.select_one("button.copy-citation")
    assert entry is not None

    text = client.get(str(entry["data-text"]))

    cited = run("cite", f"id={PAPER_ID}", f"chunk={solving}")
    assert text.status_code == 200
    assert text.headers["content-type"].startswith("text/plain")
    citation = "(Smirnov and Tasse, 2011, sec. 2.2)"
    assert citation in cited
    assert text.text == f"\u201c{OPENING}\u201d {citation}"
    assert entry["data-copied"] == words.COPIED_CITATION


def test_the_entry_shows_no_preview_and_opens_no_page(corpus: Path):
    """Brian: no preview on hover or on click, and no page of its own."""
    solving = chunk_holding(corpus, SOLVING)
    client = opened()
    card = card_for(
        page_of(client, "/?q=gains+solved&scope=literature"), link_to(PAPER_ID, solving)
    )
    entry = card.select_one(".copy-citation")
    assert entry is not None

    assert entry.name == "button" and entry["type"] == "button"
    assert not entry.has_attr("title") and not entry.has_attr("href")
    assert OPENING not in str(card.select_one(".bookmark"))
    assert client.get(f"/cite?link={link_to(PAPER_ID, solving)}").status_code == 404


def test_without_a_clipboard_the_entry_is_not_drawn():
    code = re.sub(r"/\*.*?\*/", "", stylesheet(), flags=re.S)

    assert "html:not(.can-copy) .copy-citation { display: none; }" in code


def test_a_citation_of_nothing_held_is_refused(corpus: Path):
    client = opened()

    assert client.get(f"/cite/text?link={link_to('nothing0001', 0)}").status_code == 404


def test_the_copy_script_reads_the_entry_and_carries_no_words():
    code = "\n".join(
        line
        for line in (STATIC / "cite.js").read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )

    assert 'closest("button.copy-citation")' in code
    assert 'classList.add("can-copy")' in code
    assert "dataset.text" in code and "dataset.copied" in code
    assert "navigator.clipboard.writeText" in code
    assert words.COPIED_CITATION not in code


def test_every_page_loads_the_copy_script(corpus: Path):
    page = page_of(opened(), "/")

    assert page.select_one('script[src="/static/cite.js"]') is not None


def test_a_document_page_copies_its_reference(corpus: Path):
    from kennis.citing import CiteRequest, cite
    from kennis.context import existing_corpus

    page = page_of(opened(), f"/document/literature/{PAPER_ID}")

    (reference,) = cite(existing_corpus(), [CiteRequest(PAPER_ID)]).citations
    button = page.select_one(".inspector button.copy-reference")
    assert button is not None
    assert button["data-copy"] == reference.reference
    assert button.has_attr("hidden")
    assert button.get_text(strip=True) == words.COPY_REFERENCE


def test_a_project_file_has_no_reference_to_copy(
    corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "pipelines"
    (root / ".git").mkdir(parents=True)
    init_bundle(root)
    (root / ".context" / "ours.md").write_text(
        "---\ntitle: Ours\n---\nWe solve the gains per scan.\n", encoding="utf-8"
    )
    monkeypatch.chdir(root)
    run("context", "index")

    page = page_of(opened(), "/bundle/ours.md?project=pipelines")

    assert page.select_one("button.copy-reference") is None


# ---------------------------------------------------------------------------
# A tag's colour, chosen on its page


def test_the_tag_page_chooses_a_colour_and_every_chip_wears_it(corpus: Path):
    run("tag", "calibration", f"id={PAPER_ID}")
    client = opened()
    form = page_of(client, "/tags?tag=calibration").select_one("form.tag-colour")
    assert form is not None
    offered = [str(radio["value"]) for radio in form.select("input[name=colour]")]
    assert offered == ["auto", *TAG_COLOURS, "own"]
    checked = form.select_one("input[name=colour][checked]")
    assert checked is not None and checked["value"] == "auto"

    answer = client.post(
        str(form["action"]), data={"tag": "calibration", "colour": "purple"}
    )

    assert answer.status_code == 303
    assert read_store(corpus / TAGS_FILENAME).colours == {"calibration": "purple"}
    page = page_of(client, "/tags?tag=calibration")
    assert page.select_one(".tag-head")["data-tag-colour"] == "purple"
    pane = page.select_one("a.tag-node")
    assert pane is not None and pane["data-tag-colour"] == "purple"


def test_from_its_name_clears_the_chosen_colour(corpus: Path):
    run("tag", "calibration", f"id={PAPER_ID}", "--colour", "purple")
    client = opened()

    answer = client.post(
        "/tags/colour",
        data={"tag": "calibration", "colour": "auto"},
        headers={"HX-Request": "true"},
    )

    assert answer.headers.get("HX-Refresh") == "true"
    assert read_store(corpus / TAGS_FILENAME).colours == {}


def test_a_colour_outside_the_palette_is_refused(corpus: Path):
    run("tag", "calibration", f"id={PAPER_ID}")

    answer = opened().post(
        "/tags/colour", data={"tag": "calibration", "colour": "mauve"}
    )

    assert "is not a tag colour" in answer.text
    assert read_store(corpus / TAGS_FILENAME).colours == {}


def test_a_project_tag_s_colour_is_set_in_its_project(
    corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "pipelines"
    (root / ".git").mkdir(parents=True)
    init_bundle(root)
    (root / ".context" / "ours.md").write_text(
        "---\ntitle: Ours\n---\nWe solve the gains per scan.\n", encoding="utf-8"
    )
    monkeypatch.chdir(root)
    run("context", "index")
    run("tag", "mine", "path=.context/ours.md")

    opened().post("/tags/colour", data={"tag": "mine", "colour": "teal"})

    assert read_store(root / ".context" / TAGS_FILENAME).colours == {"mine": "teal"}
    assert not (corpus / TAGS_FILENAME).exists()


# ---------------------------------------------------------------------------
# A document's tagged passages


class _Nesting(HTMLParser):
    """Whether every element closes in the order it opened: a run and the
    search mark are both wrapped around blocks, and if they crossed a
    browser would close one early and redraw the page its own way."""

    def __init__(self) -> None:
        super().__init__()
        self.open: list[str] = []
        self.crossed: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in ("br", "hr", "img", "input"):
            self.open.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self.open or self.open[-1] != tag:
            self.crossed.append(tag)
        else:
            self.open.pop()


def _runs(html: str) -> list[tuple[str, list[str]]]:
    """Each run's names and the first words of each paragraph inside it."""
    page = BeautifulSoup(html, "html.parser")
    return [
        (
            str(run["data-names"]),
            [paragraph.get_text().split()[0] for paragraph in run.select("p")],
        )
        for run in page.select("div.run")
    ]


def _wrap(names: frozenset[str]) -> RunHtml:
    from kennis.render.html import RunHtml

    named = " ".join(sorted(names))
    return RunHtml(f'<div class="run" data-names="{named}">', "</div>")


THREE = "Alpha one.\n\nBravo two.\n\nCharlie three.\n\nDelta four.\n"


def _band(first: str, last: str, *names: str) -> Band:
    from kennis.render.html import Band

    start = THREE.index(first)
    end = THREE.index("\n", THREE.index(last)) + 1
    return Band(start, end, frozenset(names))


def test_adjacent_passages_with_the_same_tags_are_one_run() -> None:
    """Brian, #50: "chunks next to each other with the same tags ... style
    as one"."""
    from kennis.render.html import to_html

    html = to_html(
        THREE,
        bands=[_band("Alpha", "Alpha", "a"), _band("Bravo", "Bravo", "a")],
        run=_wrap,
    )

    assert _runs(html) == [("a", ["Alpha", "Bravo"])]


def test_a_change_of_tags_starts_a_new_run() -> None:
    from kennis.render.html import to_html

    html = to_html(
        THREE,
        bands=[
            _band("Alpha", "Bravo", "a"),
            _band("Bravo", "Charlie", "b"),
        ],
        run=_wrap,
    )

    assert _runs(html) == [("a", ["Alpha"]), ("a b", ["Bravo"]), ("b", ["Charlie"])]


def test_a_run_never_crosses_the_search_mark() -> None:
    from kennis.render.html import MarkedRange, to_html

    marked = MarkedRange(THREE.index("Bravo"), THREE.index("Delta"), "chunk-1")
    html = to_html(
        THREE, marked=marked, bands=[_band("Alpha", "Delta", "a")], run=_wrap
    )

    nesting = _Nesting()
    nesting.feed(html)
    assert nesting.crossed == [] and nesting.open == []
    assert _runs(html) == [
        ("a", ["Alpha"]),
        ("a", ["Bravo", "Charlie"]),
        ("a", ["Delta"]),
    ]
    page = BeautifulSoup(html, "html.parser")
    (mark,) = page.select(".document-body .chunk, div.chunk")
    assert [run.get_text().split()[0] for run in mark.select("div.run")] == ["Bravo"]


def test_no_bands_leave_the_document_as_it_was() -> None:
    from kennis.render.html import to_html

    assert to_html(THREE, bands=(), run=_wrap) == to_html(THREE)


def test_a_document_shows_a_tagged_passage_as_a_run_with_its_tags(corpus: Path) -> None:
    solving = chunk_holding(corpus, SOLVING)
    run("tag", "calibration", f"id={PAPER_ID}", f"chunk={solving}", "--colour", "teal")
    run("tag", "to-read", f"id={PAPER_ID}")

    page = page_of(opened(), f"/document/literature/{PAPER_ID}")

    (tagged,) = page.select(".document-body .tag-run")
    assert tagged["data-tag-colour"] == "teal"
    chips = tagged.select(".tag-run-head .tag-chip")
    assert [chip.get_text(strip=True) for chip in chips] == ["calibration"]
    assert chips[0]["data-tag-colour"] == "teal"
    words_in_run = " ".join(tagged.get_text().split())
    assert SOLVING in words_in_run
    assert "flagged for interference" not in words_in_run
    # The head is reached from the keyboard, and says what it holds.
    marker = tagged.select_one(".tag-run-head .tag-run-marker")
    assert marker is not None and marker.name == "button"
    assert marker["aria-label"] == words.tags_on_passage(["calibration"])
    assert page.select("aside.chunk-tags") == []


def test_a_passage_with_two_tags_shows_both_and_wears_the_first_s_colour(
    corpus: Path,
) -> None:
    solving = chunk_holding(corpus, SOLVING)
    run("tag", "to-cite", f"id={PAPER_ID}", f"chunk={solving}", "--colour", "blue")
    run("tag", "calibration", f"id={PAPER_ID}", f"chunk={solving}", "--colour", "teal")

    page = page_of(opened(), f"/document/literature/{PAPER_ID}")

    (tagged,) = page.select(".document-body .tag-run")
    chips = tagged.select(".tag-run-head .tag-chip")
    assert [chip.get_text(strip=True) for chip in chips] == ["calibration", "to-cite"]
    assert [chip["data-tag-colour"] for chip in chips] == ["teal", "blue"]
    assert tagged["data-tag-colour"] == "teal"


def test_two_adjacent_passages_with_one_tag_are_one_run_on_the_page(
    corpus: Path,
) -> None:
    reducing = chunk_holding(corpus, "flagged for interference")
    solving = chunk_holding(corpus, SOLVING)
    # Every passage from the one to the other, the section heading between
    # them included: adjacent, one tag each.
    assert solving > reducing, "the fixture no longer orders its passages"
    for chunk in range(reducing, solving + 1):
        run("tag", "calibration", f"id={PAPER_ID}", f"chunk={chunk}")

    page = page_of(opened(), f"/document/literature/{PAPER_ID}")

    (tagged,) = page.select(".document-body .tag-run")
    words_in_run = " ".join(tagged.get_text().split())
    assert "flagged for interference" in words_in_run and SOLVING in words_in_run
    assert len(tagged.select(".tag-run-head")) == 1


def test_a_document_changed_since_its_index_withholds_the_marks(corpus: Path):
    solving = chunk_holding(corpus, SOLVING)
    run("tag", "calibration", f"id={PAPER_ID}", f"chunk={solving}")
    paper = corpus / "literature" / "smirnov.md"
    paper.write_text(
        paper.read_text(encoding="utf-8").replace(
            "## Abstract", "## Preface\n\nNew.\n\n## Abstract"
        ),
        encoding="utf-8",
    )

    page = page_of(opened(), f"/document/literature/{PAPER_ID}")

    assert page.select(".tag-run") == []


# ---------------------------------------------------------------------------
# A colour of one's own (#629)

TYPED = ["#ffe600", "#000000", "#ffffff", "#808080", "#ff00ff", "#1f5fd1", "#00ffff"]


@pytest.mark.parametrize("theme", sorted(THEMES))
@pytest.mark.parametrize("typed", TYPED)
def test_a_typed_colour_is_moved_until_it_is_seen(theme: str, typed: str):
    from kennis.gui.theme import tag_colour_on

    ground, palette = THEMES[theme]
    scheme: Literal["light", "dark"] = "light" if theme == "light" else "dark"
    drawn = _rgb(tag_colour_on(typed, scheme))
    page = _rgb(ground)

    assert _contrast(drawn, page) >= 3
    assert _contrast(drawn, _raised(ground, palette["bright_black"])) >= 3
    assert _contrast(_rgb(palette["white"]), _mixed(drawn, page, 0.24)) >= 4.5


def test_a_typed_colour_that_is_seen_is_drawn_as_typed():
    from kennis.gui.theme import tag_colour_on

    assert tag_colour_on("#1f5fd1", "light") == "#1f5fd1"
    assert tag_colour_on("#ffe600", "dark") == "#ffe600"


def test_a_typed_colour_keeps_its_hue():
    import colorsys

    from kennis.gui.theme import tag_colour_on

    typed = colorsys.rgb_to_hls(*_rgb("#ffe600"))[0]
    drawn = colorsys.rgb_to_hls(*_rgb(tag_colour_on("#ffe600", "light")))[0]

    assert abs(typed - drawn) < 0.01


def test_a_typed_colour_carries_both_themes_and_the_rules_choose_one(corpus: Path):
    from kennis.gui.theme import tag_colour_on

    run("tag", "calibration", f"id={PAPER_ID}", "--colour", "#ffe600")

    page = page_of(opened(), "/tags?tag=calibration")

    head = page.select_one(".tag-head")
    assert head is not None and head.has_attr("data-tag-custom")
    assert f"--tag-on-light: {tag_colour_on('#ffe600', 'light')};" in str(head["style"])
    assert f"--tag-on-dark: {tag_colour_on('#ffe600', 'dark')};" in str(head["style"])
    code = re.sub(r"/\*.*?\*/", "", stylesheet(), flags=re.S)
    assert "[data-tag-custom] { --tag: var(--tag-on-light); }" in code
    assert (
        'html[data-theme="dark"] [data-tag-custom] { --tag: var(--tag-on-dark); }'
        in code
    )


def test_the_picker_sets_a_colour_without_its_radio_being_pressed(corpus: Path):
    """Moving a colour picker does not press the radio beside it, so the
    picker moved since it was drawn is the choice."""
    run("tag", "calibration", f"id={PAPER_ID}")
    client = opened()
    form = page_of(client, "/tags?tag=calibration").select_one("form.tag-colour")
    assert form is not None
    sent = {
        str(field["name"]): str(field.get("value", ""))
        for field in form.select("input[name]")
        if field.get("type") != "radio"
    }
    sent["colour"] = "auto"
    sent["hex"] = "#123456"

    client.post(str(form["action"]), data=sent)

    assert read_store(corpus / TAGS_FILENAME).colours == {"calibration": "#123456"}


def test_the_picker_left_alone_changes_nothing_but_the_radio(corpus: Path):
    run("tag", "calibration", f"id={PAPER_ID}")
    client = opened()
    form = page_of(client, "/tags?tag=calibration").select_one("form.tag-colour")
    assert form is not None
    sent = {
        str(field["name"]): str(field.get("value", ""))
        for field in form.select("input[name]")
        if field.get("type") != "radio"
    }
    sent["colour"] = "pink"

    client.post(str(form["action"]), data=sent)

    assert read_store(corpus / TAGS_FILENAME).colours == {"calibration": "pink"}
