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
from pathlib import Path

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


def test_the_tab_holds_open_tag_and_copy_citation_in_that_order(corpus: Path):
    solving = chunk_holding(corpus, SOLVING)
    page = page_of(opened(), "/?q=gains+solved&scope=literature")

    card = card_for(page, link_to(PAPER_ID, solving))
    tab = card.select_one(".bookmark .bookmark-tab")
    entries = card.select(".bookmark-items a.item")

    assert tab is not None and tab["aria-label"] == words.PASSAGE_ACTIONS
    assert [entry.get_text(strip=True) for entry in entries] == [
        words.OPEN_AT_PASSAGE,
        words.TAG_PASSAGE,
        words.COPY_CITATION,
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


def test_copy_citation_fetches_what_kennis_cite_writes(corpus: Path):
    solving = chunk_holding(corpus, SOLVING)
    client = opened()
    card = card_for(
        page_of(client, "/?q=gains+solved&scope=literature"), link_to(PAPER_ID, solving)
    )
    entry = card.select_one("a.copy-citation")
    assert entry is not None

    text = client.get(str(entry["data-text"]))
    page = page_of(client, str(entry["href"]))

    cited = run("cite", f"id={PAPER_ID}", f"chunk={solving}")
    assert text.status_code == 200
    assert text.headers["content-type"].startswith("text/plain")
    assert text.text and text.text in cited
    assert text.text in page.get_text()
    assert entry["data-copied"] == words.COPIED_CITATION


def test_a_citation_of_nothing_held_is_refused(corpus: Path):
    client = opened()

    assert client.get(f"/cite/text?link={link_to('nothing0001', 0)}").status_code == 404
    assert client.get(f"/cite?link={link_to('nothing0001', 0)}").status_code == 404


def test_the_copy_script_reads_the_entry_and_carries_no_words():
    code = "\n".join(
        line
        for line in (STATIC / "cite.js").read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )

    assert 'closest("a.copy-citation")' in code
    assert "dataset.text" in code and "dataset.copied" in code
    assert "navigator.clipboard.writeText" in code
    assert words.COPIED_CITATION not in code


def test_every_page_loads_the_copy_script(corpus: Path):
    page = page_of(opened(), "/")

    assert page.select_one('script[src="/static/cite.js"]') is not None


# ---------------------------------------------------------------------------
# A tag's colour, chosen on its page


def test_the_tag_page_chooses_a_colour_and_every_chip_wears_it(corpus: Path):
    run("tag", "calibration", f"id={PAPER_ID}")
    client = opened()
    form = page_of(client, "/tags?tag=calibration").select_one("form.tag-colour")
    assert form is not None
    offered = [str(radio["value"]) for radio in form.select("input[name=colour]")]
    assert offered == ["auto", *TAG_COLOURS]
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


def test_a_note_is_set_before_the_block_its_offset_falls_in():
    from kennis.render.html import MarginNote, to_html

    markdown = "First paragraph.\n\nSecond paragraph.\n\nThird.\n"
    second = markdown.index("Second")

    html = to_html(markdown, margins=[MarginNote(second + 3, "<aside>N</aside>")])

    assert html.index("First") < html.index("<aside>N</aside>") < html.index("Second")
    assert to_html(markdown, margins=()) == to_html(markdown)


def test_a_document_shows_each_tagged_passage_s_tags_beside_it(corpus: Path):
    solving = chunk_holding(corpus, SOLVING)
    run("tag", "calibration", f"id={PAPER_ID}", f"chunk={solving}", "--colour", "teal")
    run("tag", "to-read", f"id={PAPER_ID}")

    page = page_of(opened(), f"/document/literature/{PAPER_ID}")

    (margin,) = page.select("aside.chunk-tags")
    assert margin["data-chunk"] == str(solving)
    assert [chip.get_text(strip=True) for chip in margin.select(".tag-chip")] == [
        "calibration"
    ]
    assert margin.select_one(".tag-chip")["data-tag-colour"] == "teal"
    following = margin.find_next("p")
    assert following is not None and SOLVING in " ".join(following.get_text().split())


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

    assert page.select("aside.chunk-tags") == []
