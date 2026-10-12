"""Unit 11c: a search hit as the workbench shows it.

The measures sit above the title, each named by an icon and shown as a
five-cell bar beside its word; there is no rank number; one passage
element opens in place to the whole chunk; one key at the head of the
results says what the measures are, instead of a basis line per group.
The lexical measure is called "keywords" in every front end (#417).

The words are still `render/hits.py`'s: the window lays out `title` and
`measures` where the command line prints `headline` and `detail`, and
those two stay byte-identical between the command line and an agent.
"""

from __future__ import annotations

import math
import re
from itertools import pairwise
from pathlib import Path

import pytest
from bs4 import BeautifulSoup, Tag
from click.testing import CliRunner
from fastapi.testclient import TestClient
from markupsafe import escape

from kennis.cli.__main__ import main
from kennis.context import existing_corpus
from kennis.engine.corpus.collection import Collection
from kennis.engine.rag.models import Chunk, SearchResult
from kennis.gui import words
from kennis.gui.app import build_app
from kennis.gui.icons import icon
from kennis.gui.pages import ordered_by
from kennis.gui.theme import STRENGTH_SCALES, stylesheet
from kennis.render.hits import Hit, relevance_phrase, rendered_hit
from kennis.retrieval import Sweep

TOKEN = "a-test-token"
STATIC = Path(__file__).parent.parent / "src" / "kennis" / "gui" / "static"

LONG_BODY = (
    "Calibration solves for antenna gains against a sky model. "
    "Each solution interval fits one complex gain per antenna and "
    "polarisation, and the residual visibilities are what the next "
    "imaging step sees. Direction-dependent effects need a gain per "
    "facet as well, which is where self-calibration earns its cost. "
    "The final sentence of this passage is the one a closed snippet "
    "would have cut off before it ever reached the reader."
)


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    return tmp_path


@pytest.fixture
def client(corpus: Path) -> TestClient:
    opened = TestClient(build_app(TOKEN), follow_redirects=False)
    assert opened.get("/", params={"token": TOKEN}).status_code == 200
    return opened


def a_note(tmp_path: Path, name: str, body: str) -> str:
    run = CliRunner()
    source = tmp_path / "sources" / f"{name}.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(f"# {name}\n\n{body}\n", encoding="utf-8")
    assert run.invoke(main, ["corpus", "add", "-n", str(source)]).exit_code == 0
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0
    held = Collection(root=existing_corpus().corpus_root, name="notes").contents()
    return next(d.id for d in held.documents if d.frontmatter.title == name)


def hits_of(client: TestClient, question: str) -> str:
    answer = client.get("/hits", params={"q": question, "scope": "notes"})
    assert answer.status_code == 200
    return answer.text


def items_of(page: str) -> list[str]:
    return re.findall(
        r'<li class="hit">(.*?)</li>\s*(?=<li class="hit">|</ol>)', page, re.S
    )


def code_of(name: str) -> str:
    """A script with its comment lines removed (#337, #373)."""
    script = (STATIC / name).read_text(encoding="utf-8")
    return "\n".join(
        line for line in script.splitlines() if not line.strip().startswith("//")
    )


def a_result(*, bm25_score: float | None, title: str = "Rivers") -> SearchResult:
    return SearchResult(
        chunk=Chunk(
            id="zrf1299xo1::0",
            collection="notes",
            document_id="zrf1299xo1",
            chunk_index=0,
            text="Rivers carry sediment.",
            source_path="notes/Rivers.md",
            char_start=0,
            char_end=22,
            section="Deposition",
            metadata={"title": title},
        ),
        score=0.016,
        bm25_score=bm25_score,
        dense_score=None,
    )


# ---------------------------------------------------------------------------
# The words: keywords, in every front end
# ---------------------------------------------------------------------------


def test_the_lexical_measure_reads_keywords():
    hit = Hit(collection="notes", result=a_result(bm25_score=4.0), model=None)

    rendered = rendered_hit(hit, rank=1, style="human", best=4.0, snippet="none")

    assert rendered.detail.startswith("keywords: very high")
    assert "lexical" not in rendered.detail
    assert (
        relevance_phrase({"lexical"}) == "keywords as a fraction of the best match here"
    )


def test_the_command_line_says_keywords_too(corpus: Path):
    """One renderer, so the terminal and an agent change with the window."""
    a_note(corpus, "calibration", "Calibration solves for antenna gains.")

    printed = CliRunner().invoke(main, ["search", "antenna", "--collection", "notes"])

    assert printed.exit_code == 0, printed.output
    assert "keywords: " in printed.output
    assert "lexical:" not in printed.output
    assert "lexical as" not in printed.output


def test_the_title_is_the_headline_without_its_rank():
    hit = Hit(collection="notes", result=a_result(bm25_score=4.0), model=None)

    rendered = rendered_hit(hit, rank=3, style="human", best=4.0, snippet="none")

    assert rendered.headline == "[3] Rivers - Deposition"
    assert rendered.title == "Rivers - Deposition"
    assert rendered.measures == (("lexical", "very high"),)


def test_the_mode_control_names_the_search_by_what_it_matches():
    # Written by hand: the control's whole vocabulary (#417).
    assert [label for _, label in words.MODE_CHOICES] == [
        "As configured",
        "Keywords and meaning",
        "Keywords only",
        "Meaning only",
    ]


# ---------------------------------------------------------------------------
# A hit, laid out
# ---------------------------------------------------------------------------


def test_a_hit_carries_no_rank_number(corpus: Path, client: TestClient):
    """The fused order is reciprocal rank, so a place number claims a
    measurement nobody can rely on (#342, #406)."""
    a_note(corpus, "calibration", "Calibration solves for antenna gains.")

    page = hits_of(client, "antenna")

    assert items_of(page)
    assert not re.search(r"\[\d+\]", page)


def test_the_title_is_the_command_lines_headline_less_its_rank(
    corpus: Path, client: TestClient
):
    """Compared as whole lines, for #297's reason: a page that composed
    its own title would pass a check that it merely mentions the query."""
    a_note(corpus, "calibration", "Calibration solves for antenna gains.")
    printed = CliRunner().invoke(
        main, ["search", "antenna", "--collection", "notes", "--snippet", "none"]
    )
    headlines = [
        line.strip()
        for line in printed.output.splitlines()
        if line.strip().startswith("[")
    ]

    page = hits_of(client, "antenna")

    assert headlines, printed.output
    for headline in headlines:
        title = re.sub(r"^\[\d+\] ", "", headline)
        assert f">{title}</a>" in page, title


def test_the_measures_come_before_the_title(corpus: Path, client: TestClient):
    a_note(corpus, "calibration", "Calibration solves for antenna gains.")

    for item in items_of(hits_of(client, "antenna")):
        assert item.index('class="measures"') < item.index('class="title"')


def test_a_measure_is_an_icon_a_word_and_a_bar(corpus: Path, client: TestClient):
    """The one hit in a one-note collection is its own best keyword
    match, so it is "very high" and all five cells are filled."""
    a_note(corpus, "calibration", "Calibration solves for antenna gains.")

    item = items_of(hits_of(client, "antenna"))[0]
    measure = re.search(
        r'<span class="measure"[^>]*>(.*?)</span>\s*</span>', item, re.S
    )

    assert measure, item
    assert 'title="keywords"' in measure.group(0)
    assert "<svg" in measure.group(1)
    assert "very high" in measure.group(1)
    cells = re.findall(r'<i class="cell( on)?"', measure.group(1))
    assert len(cells) == 5
    assert cells.count(" on") == 5
    assert 'data-step="5"' in measure.group(0)


def test_the_document_is_opened_by_a_named_icon(corpus: Path, client: TestClient):
    document_id = a_note(corpus, "calibration", "Calibration solves for antenna gains.")

    item = items_of(hits_of(client, "antenna"))[0]
    opener = re.search(r'<a class="open"[^>]*>.*?</a>', item, re.S)

    assert opener, item
    assert f'aria-label="{words.OPEN_AT_PASSAGE}"' in opener.group(0)
    assert f"/document/notes/{document_id}" in opener.group(0)
    assert "<svg" in opener.group(0)


# ---------------------------------------------------------------------------
# One passage, opened in place
# ---------------------------------------------------------------------------


TABLE_BODY = (
    "The scores are in the table.\n\n"
    "| Model | Score |\n"
    "| --- | --- |\n"
    "| antenna-7B | 50.3 |\n"
    "| antenna-8B | 72.9 |\n\n" + LONG_BODY
)


def passage_in(item: str) -> Tag:
    found = BeautifulSoup(item, "html.parser").find(class_="passage")
    assert isinstance(found, Tag), item
    return found


def part_of(passage: Tag, name: str) -> Tag:
    found = passage.find(class_=name)
    assert isinstance(found, Tag), passage
    return found


def test_a_passage_opens_by_a_disclosure_and_no_script(
    corpus: Path, client: TestClient
):
    """`<details>` holds only the control; its `open` is what the
    stylesheet reads, and `name` closes the others (#454)."""
    a_note(corpus, "calibration", LONG_BODY)

    passage = passage_in(items_of(hits_of(client, "antenna"))[0])
    control = passage.find("details")

    assert "clamped" in (passage.get("class") or [])
    assert isinstance(control, Tag)
    assert control.get("name") == "passages" and not control.has_attr("open")


def test_a_closed_passage_is_moved_to_its_first_mark_by_a_loaded_script(
    client: TestClient,
):
    """A table is one block, so a mark in its twentieth row cannot be
    reached by parting the passage, and the closed view showed the head
    of the table and none of the reader's words. `passage.js` moves the
    clipped body to the first mark; it measures and composes no words,
    and runs again when a passage closes or results are swapped in."""
    code = code_of("passage.js")

    assert '<script defer src="/static/passage.js">' in client.get("/").text
    assert ".passage.clamped .body" in code and 'querySelector("mark")' in code
    assert "scrollTop" in code
    assert '"htmx:afterSwap"' in code
    assert '"transitionend"' in code, "closing is measured once it has shrunk"
    assert re.search(r'addEventListener\(\s*"toggle".*?\},\s*true\s*\)', code, re.S), (
        "toggle does not bubble, so it is heard only in the capture phase"
    )
    assert not re.search(r'"[A-Z][a-z]+ [a-z]+', code), "no sentence in the script"


def test_a_moved_passage_fades_at_both_ends(client: TestClient):
    css = client.get("/static/kennis.css").text

    rule = re.search(r"\.passage\.clamped \.body\[data-shifted\][^{]*\{([^}]*)\}", css)
    assert rule, css
    assert "transparent," in rule.group(1) and "currentColor" in rule.group(1)


def test_a_heading_in_a_passage_is_the_size_of_its_text(client: TestClient):
    """A chunk that is only a heading drew "2 Data" at a document's title
    size inside the list of results."""
    css = client.get("/static/kennis.css").text

    rule = re.search(
        r"\.passage \.full :is\(h1, h2, h3, h4, h5, h6\)\s*\{([^}]*)\}", css
    )
    assert rule, css
    assert "font-size: 1em" in rule.group(1)


def test_the_chunk_is_on_the_page_once_whichever_way_it_is_open(
    corpus: Path, client: TestClient
):
    """Drawn once and windowed by the stylesheet: no sentence twice."""
    a_note(corpus, "calibration", LONG_BODY)

    passage = passage_in(items_of(hits_of(client, "antenna"))[0])
    text = " ".join(part_of(passage, "full").get_text(" ").split())

    for sentence in LONG_BODY.split(". "):
        assert text.count(sentence.rstrip(".")) == 1, sentence


def test_a_closed_passage_starts_at_the_readers_words(corpus: Path, client: TestClient):
    """The paragraphs before the first match are the part that grows in
    when the passage opens."""
    body = "An opening paragraph about weather.\n\n" + LONG_BODY
    a_note(corpus, "calibration", body)

    passage = passage_in(items_of(hits_of(client, "antenna"))[0])

    assert "weather" in part_of(passage, "lead").get_text()
    assert part_of(passage, "body").find("mark") is not None


def test_the_stylesheet_hides_the_lead_and_cuts_the_body_until_opened(
    client: TestClient,
):
    css = client.get("/static/kennis.css").text

    assert re.search(r"\.passage\.clamped \.lead\s*\{[^}]*max-height: 0", css)
    assert re.search(
        r"\.passage\.clamped \.body\s*\{[^}]*max-height: 6lh[^}]*mask-image", css
    )
    opened = re.search(
        r"\.passage\.clamped:has\(details\[open\]\) \.lead,\s*"
        r"\.passage\.clamped:has\(details\[open\]\) \.body\s*\{([^}]*)\}",
        css,
    )
    assert opened, css
    assert "max-height: max-content" in opened.group(1)
    assert "mask-image: none" in opened.group(1)


def test_an_opened_passage_is_one_colour(client: TestClient):
    """Brian, 2026-10-12: the text around the window was drawn muted, so an
    opened passage read as two kinds of text. Nothing in it is muted."""
    css = client.get("/static/kennis.css").text
    rules = re.findall(r"([^{}]*\.(?:full|lead|body)\b[^{}]*)\{([^}]*)\}", css)

    assert rules
    for selector, body in rules:
        if ".passage" in selector or ".full" in selector:
            # The text's colour; the card's rule may be the muted grey.
            assert not re.search(r"(?<![-\w])color:[^;]*muted", body), selector


def test_a_table_in_a_chunk_is_a_table_closed_or_open(corpus: Path, client: TestClient):
    """Brian, 2026-10-12: a table in a closed passage arrived as pipes.
    It is the same table either way now, and a passage holding one
    always opens, since its height is not its length."""
    a_note(corpus, "scores", TABLE_BODY)

    passage = passage_in(items_of(hits_of(client, "antenna"))[0])
    table = part_of(passage, "full").find("table")

    assert isinstance(table, Tag)
    assert [cell.get_text(strip=True) for cell in table.find_all("th")] == [
        "Model",
        "Score",
    ]
    assert len(table.find_all("tr")) == 3
    assert "|" not in part_of(passage, "full").get_text()
    assert passage.find("details") is not None


def test_the_readers_words_are_marked_in_text_and_code_and_never_in_maths(
    corpus: Path, client: TestClient
):
    """A search for `antenna` names the code too; inside maths a `<mark>`
    is markup KaTeX renders or refuses."""
    a_note(
        corpus,
        "calibration",
        LONG_BODY + "\n\nThe antenna gain, see `antenna` and $antenna$ here.",
    )

    whole = part_of(passage_in(items_of(hits_of(client, "antenna"))[0]), "full")

    code = whole.find("code")
    assert isinstance(code, Tag) and code.find("mark") is not None
    maths = whole.find(class_="math")
    assert isinstance(maths, Tag) and maths.find("mark") is None
    assert whole.find("p") is not None and whole.find("p").find("mark") is not None


def test_a_passage_that_fits_has_nothing_to_open(corpus: Path, client: TestClient):
    a_note(corpus, "calibration", "Calibration solves for antenna gains.")

    item = items_of(hits_of(client, "antenna"))[0]
    passage = passage_in(item)

    assert "<details" not in item
    assert "clamped" not in (passage.get("class") or [])


def test_a_hit_has_one_way_to_its_document_and_a_chevron_to_open_it(
    corpus: Path, client: TestClient
):
    """Brian, 2026-10-12: the arrow by the title opened the document and
    so did a line of text under the passage; symbols, and one of each.
    The toggle's words stay in Python and on the page for a screen
    reader, hidden from sight; only the chevron is drawn."""
    document_id = a_note(corpus, "calibration", LONG_BODY)

    item = BeautifulSoup(items_of(hits_of(client, "antenna"))[0], "html.parser")
    links = [
        link
        for link in item.find_all("a")
        if f"/document/notes/{document_id}" in str(link.get("href"))
    ]
    passage = item.find(class_="passage")
    assert isinstance(passage, Tag)
    summary = passage.find("summary")
    assert isinstance(summary, Tag)

    assert {" ".join(link.get("class") or []) for link in links} == {"title", "open"}
    assert passage.find("a") is None or not any(
        f"/document/notes/{document_id}" in str(link.get("href"))
        for link in passage.find_all("a")
    )
    assert summary.find("svg") is not None
    hidden = [span.get_text(strip=True) for span in summary.select(".visually-hidden")]
    assert hidden == [words.SHOW_PASSAGE, words.HIDE_PASSAGE]
    assert summary.get_text(strip=True) == "".join(hidden), "no visible words"


def test_the_passage_is_a_card_set_apart_from_its_title(client: TestClient):
    """Brian, 2026-10-12: "a little hard to see that it is quoted text".
    A surface, a border and a rule down the left, as a quotation has;
    the rule turns to the brand when the passage is open."""
    css = client.get("/static/kennis.css").text
    card = re.search(r"^\.passage \.full \{([^}]*)\}", css, re.M)

    assert card, css
    for declaration in ("background: var(--raised)", "border: 1px solid var(--rule)"):
        assert declaration in card.group(1)
    assert "border-radius" in card.group(1)
    assert re.search(r"border-left: 3px solid var\(--role-muted\)", card.group(1))
    assert re.search(
        r"\.passage:has\(details\[open\]\) \.full \{[^}]*border-left-color: "
        r"var\(--brand\)",
        css,
    )


# ---------------------------------------------------------------------------
# One key
# ---------------------------------------------------------------------------


def test_one_key_heads_the_results_and_no_group_repeats_a_basis(
    corpus: Path, client: TestClient
):
    """#408, agreed 2026-10-09: the scale is shown once and
    systematically. Two collections answer, because with one a key
    drawn per group is also drawn once."""
    a_note(corpus, "calibration", "Calibration solves for antenna gains.")
    source = corpus / "sources" / "paper.md"
    source.write_text("# Paper\n\nAn antenna paper.\n", encoding="utf-8")
    run = CliRunner()
    added = run.invoke(main, ["corpus", "add", "-d", "--project", "radio", str(source)])
    assert added.exit_code == 0, added.output
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0

    page = client.get("/hits", params={"q": "antenna", "scope": "all"}).text

    assert page.count('<h2 class="group-head">') == 2, page
    assert page.count('<details class="key">') == 1
    assert 'class="basis"' not in page
    assert page.index('<details class="key">') < page.index('<li class="hit">')


def test_the_key_explains_each_measure_present(corpus: Path, client: TestClient):
    a_note(corpus, "calibration", "Calibration solves for antenna gains.")

    key = re.search(
        r'<details class="key">(.*?)</details>', hits_of(client, "antenna"), re.S
    )

    assert key
    assert words.KEY_SUMMARY in key.group(1)
    assert "keywords as a fraction of the best match here" in key.group(1)
    # No dense leg ran in this corpus, so meaning is not explained.
    assert "absolute cosine" not in key.group(1)


def test_the_key_shows_the_same_five_steps_as_the_bars(
    corpus: Path, client: TestClient
):
    a_note(corpus, "calibration", "Calibration solves for antenna gains.")

    key = re.search(
        r'<details class="key">(.*?)</details>', hits_of(client, "antenna"), re.S
    )

    assert key
    steps = re.findall(r'<i class="cell on" data-step="(\d)"', key.group(1))
    assert steps == ["1", "2", "3", "4", "5"]


def test_nothing_found_shows_no_key(corpus: Path, client: TestClient):
    a_note(corpus, "calibration", "Calibration solves for antenna gains.")

    assert '<details class="key">' not in hits_of(client, "zzzqqq")


# ---------------------------------------------------------------------------
# The strength scales
# ---------------------------------------------------------------------------


def _linear(channel: float) -> float:
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def _encoded(channel: float) -> float:
    channel = min(max(channel, 0.0), 1.0)
    return (
        12.92 * channel
        if channel <= 0.0031308
        else 1.055 * channel ** (1 / 2.4) - 0.055
    )


def _rgb(colour: str) -> tuple[float, float, float]:
    digits = colour.lstrip("#")
    red, green, blue = (int(digits[i : i + 2], 16) / 255 for i in (0, 2, 4))
    return red, green, blue


def _lab(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    red, green, blue = (_linear(channel) for channel in rgb)
    x = 0.4124 * red + 0.3576 * green + 0.1805 * blue
    y = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    z = 0.0193 * red + 0.1192 * green + 0.9505 * blue

    def transfer(value: float) -> float:
        return value ** (1 / 3) if value > 0.008856 else 7.787 * value + 16 / 116

    fx, fy, fz = (
        transfer(component / reference)
        for component, reference in zip((x, y, z), (0.95047, 1.0, 1.08883), strict=True)
    )
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


# Machado, Oliveira and Fernandes (2009), deuteranopia at severity 1.0,
# applied to linear RGB. Deuteranopia because it is the commonest form
# of the deficiency that makes red against green unreadable.
_DEUTERANOPIA = (
    (0.367322, 0.860646, -0.227968),
    (0.280085, 0.672501, 0.047413),
    (-0.011820, 0.042940, 0.968881),
)


def _as_a_deuteranope_sees(colour: str) -> tuple[float, float, float]:
    linear = [_linear(channel) for channel in _rgb(colour)]
    simulated = [
        sum(m * c for m, c in zip(row, linear, strict=True)) for row in _DEUTERANOPIA
    ]
    red, green, blue = (_encoded(channel) for channel in simulated)
    return red, green, blue


def _difference(
    one: tuple[float, float, float], other: tuple[float, float, float]
) -> float:
    return math.dist(_lab(one), _lab(other))


SCALE_CASES = [
    (name, theme) for name in sorted(STRENGTH_SCALES) for theme in ("light", "dark")
]


@pytest.mark.parametrize(("name", "theme"), SCALE_CASES)
def test_every_scale_changes_lightness_steadily(name: str, theme: str):
    """Ordered by lightness, so the order survives greyscale and every
    form of colour blindness."""
    lightness = [_lab(_rgb(colour))[0] for colour in STRENGTH_SCALES[name][theme]]

    rising = all(b > a for a, b in pairwise(lightness))
    falling = all(b < a for a, b in pairwise(lightness))
    assert rising or falling, lightness


@pytest.mark.parametrize(("name", "theme"), SCALE_CASES)
def test_adjacent_steps_stay_apart_for_a_deuteranope(name: str, theme: str):
    seen = [_as_a_deuteranope_sees(colour) for colour in STRENGTH_SCALES[name][theme]]

    gaps = [_difference(a, b) for a, b in pairwise(seen)]
    assert min(gaps) >= 10, gaps


def test_every_scale_has_five_steps_in_both_themes():
    assert set(STRENGTH_SCALES) == {"viridis", "cividis", "plasma", "magma", "greys"}
    for themes in STRENGTH_SCALES.values():
        assert set(themes) == {"light", "dark"}
        assert all(len(steps) == 5 for steps in themes.values())


def test_viridis_is_the_scale_the_page_carries():
    """Written by hand, from matplotlib's viridis sampled at five steps
    over [0, 0.82] on a light ground and [0.3, 1] on a dark one."""
    sheet = stylesheet()
    light = sheet[: sheet.index("@media")]
    dark = sheet[sheet.index("@media") :]

    assert "--scale-viridis-1: #440154" in light
    assert "--scale-viridis-5: #86d549" in light
    assert "--scale-viridis-1: #355f8d" in dark
    assert "--scale-viridis-5: #fde725" in dark
    # And the bars point at it until the reader chooses another (12a).
    assert "--strength-1: var(--scale-viridis-1);" in light


# ---------------------------------------------------------------------------
# Reordering within a collection by one measure (#406)
# ---------------------------------------------------------------------------

CALIBRATED = "BAAI/bge-small-en-v1.5"


def a_hybrid(
    title: str, *, bm25_rank: int | None, dense_rank: int | None, index: int
) -> Hit:
    return Hit(
        collection="notes",
        result=SearchResult(
            chunk=Chunk(
                id=f"doc{index}::0",
                collection="notes",
                document_id=f"doc{index}",
                chunk_index=0,
                text=f"{title} carries the word antenna.",
                source_path=f"notes/{title}.md",
                char_start=0,
                char_end=10,
                section=None,
                metadata={"title": title},
            ),
            score=0.016,
            bm25_rank=bm25_rank,
            dense_rank=dense_rank,
            bm25_score=None if bm25_rank is None else 10.0 - bm25_rank,
            dense_score=None if dense_rank is None else 0.82 - dense_rank / 50,
        ),
        model=CALIBRATED,
    )


# Fused order first; each leg's own rank says something else.
FUSED = [
    a_hybrid("Alpha", bm25_rank=2, dense_rank=3, index=1),
    a_hybrid("Beta", bm25_rank=None, dense_rank=1, index=2),
    a_hybrid("Gamma", bm25_rank=1, dense_rank=2, index=3),
]


@pytest.fixture
def hybrid(monkeypatch: pytest.MonkeyPatch) -> None:
    """A search where both measures scored, which this suite's corpus
    cannot produce without downloading a model."""

    def swept(question: str, **_: object) -> Sweep:
        return Sweep(
            groups={"notes": list(FUSED)},
            searched=("notes",),
            skipped=(),
            degraded=(),
        )

    monkeypatch.setattr("kennis.gui.app.sweep", swept)


def titles_in(page: str) -> list[str]:
    return re.findall(r'<a class="title" [^>]*>([^<]+)</a>', page)


def order_of(page: str) -> str:
    found = re.search(r'<nav class="order"[^>]*>(.*?)</nav>', page, re.S)
    assert found, page
    return found.group(1)


def test_reordering_sorts_by_that_measures_own_rank():
    """A hit the leg did not find goes last, in the fused order."""
    assert [hit.result.chunk.metadata["title"] for hit in ordered_by(FUSED, "")] == [
        "Alpha",
        "Beta",
        "Gamma",
    ]
    by_keywords = ordered_by(FUSED, "lexical")
    assert [hit.result.chunk.metadata["title"] for hit in by_keywords] == [
        "Gamma",
        "Alpha",
        "Beta",
    ]
    by_meaning = ordered_by(FUSED, "meaning")
    assert [hit.result.chunk.metadata["title"] for hit in by_meaning] == [
        "Beta",
        "Gamma",
        "Alpha",
    ]


def test_the_page_is_in_the_order_asked_for(
    corpus: Path, client: TestClient, hybrid: None
):
    ranked = client.get("/hits", params={"q": "antenna", "scope": "notes"}).text
    by_meaning = client.get(
        "/hits", params={"q": "antenna", "scope": "notes", "order": "meaning"}
    ).text

    assert titles_in(ranked) == ["Alpha", "Beta", "Gamma"]
    assert titles_in(by_meaning) == ["Beta", "Gamma", "Alpha"]


def test_the_order_control_names_each_order_and_the_current_one(
    corpus: Path, client: TestClient, hybrid: None
):
    page = client.get(
        "/hits", params={"q": "antenna", "scope": "notes", "order": "lexical"}
    ).text
    control = order_of(page)

    links = re.findall(r"<a ([^>]*)>([^<]+)</a>", control)
    assert [label for _, label in links] == [label for _, label in words.ORDER_CHOICES]
    current = [
        label for attributes, label in links if 'aria-current="true"' in attributes
    ]
    assert current == [dict(words.ORDER_CHOICES)["lexical"]]
    for attributes, _ in links:
        assert "q=antenna" in attributes and "scope=notes" in attributes


def test_the_order_control_states_its_limit_once_it_has_reordered(
    corpus: Path, client: TestClient, hybrid: None
):
    """Reordering three returned hits is not searching by one measure,
    and the best meaning-only hit may not be among them (#406). Said
    when the page is reordered, which is when it describes the page."""
    ranked = client.get("/hits", params={"q": "antenna", "scope": "notes"}).text
    reordered = client.get(
        "/hits", params={"q": "antenna", "scope": "notes", "order": "meaning"}
    ).text

    assert words.ORDER_LIMIT not in ranked
    assert words.ORDER_LIMIT in reordered
    assert words.MODE_LABEL in words.ORDER_LIMIT


def test_with_one_measure_there_is_nothing_to_reorder(corpus: Path, client: TestClient):
    """A lexical-only search is already in the keywords' own order."""
    a_note(corpus, "calibration", "Calibration solves for antenna gains.")

    assert '<nav class="order"' not in hits_of(client, "antenna")


def test_an_unknown_order_is_named(corpus: Path, client: TestClient, hybrid: None):
    page = client.get(
        "/hits", params={"q": "antenna", "scope": "notes", "order": "loudness"}
    ).text

    assert escape(words.unknown_order("loudness")) in page
    assert '<li class="hit">' not in page


# ---------------------------------------------------------------------------
# The head of the results and of each group (#447)
# ---------------------------------------------------------------------------


def head_of(page: str) -> Tag:
    found = BeautifulSoup(page, "html.parser").find(class_="results-head")
    assert isinstance(found, Tag), page
    return found


def test_the_count_is_said_as_found_or_as_a_floor():
    assert words.results_for(1, capped=False, question="antenna") == (
        '1 result for "antenna"'
    )
    assert words.results_for(9, capped=True, question="selfcal") == (
        '9+ results for "selfcal"'
    )


def test_the_head_says_how_many_were_found_and_for_what(
    corpus: Path, client: TestClient
):
    a_note(corpus, "calibration", "Calibration solves for antenna gains.")

    text = " ".join(head_of(hits_of(client, "antenna")).get_text(" ").split())

    assert words.results_for(1, capped=False, question="antenna") in text


def test_a_scope_that_filled_its_quota_makes_the_count_a_floor(
    corpus: Path, client: TestClient
):
    """`default_top_k` is 3 per scope, so three hits in one scope say
    nothing about a fourth (#348)."""
    for name in ("one", "two", "three"):
        a_note(corpus, name, f"The antenna note called {name}.")

    text = " ".join(head_of(hits_of(client, "antenna")).get_text(" ").split())

    assert words.results_for(3, capped=True, question="antenna") in text


def test_the_order_control_is_in_the_head(
    corpus: Path, client: TestClient, hybrid: None
):
    head = head_of(client.get("/hits", params={"q": "antenna", "scope": "notes"}).text)

    assert head.find("nav", class_="order") is not None


def test_a_group_is_headed_by_its_collections_icon_name_and_count(
    corpus: Path, client: TestClient
):
    a_note(corpus, "calibration", "Calibration solves for antenna gains.")

    page = hits_of(client, "antenna")
    raw = re.search(r'<h2 class="group-head">(.*?)</h2>', page, re.S)
    assert raw, page
    head = BeautifulSoup(raw.group(0), "html.parser")
    name = head.find(class_="name")
    count = head.find(class_="count")

    assert str(icon(words.COLLECTION_ICONS["notes"])) in raw.group(1)
    assert isinstance(name, Tag) and name.get_text(strip=True) == "notes"
    assert isinstance(count, Tag) and count.get_text(strip=True) == "1"


def test_the_handle_is_on_the_measures_row(corpus: Path, client: TestClient):
    """Where the mockup puts the citekey: beside the measures, not under
    the passage. The words are the command line's last field (#297)."""
    a_note(corpus, "calibration", "Calibration solves for antenna gains.")

    item = BeautifulSoup(items_of(hits_of(client, "antenna"))[0], "html.parser")
    row = item.find(class_="measures")

    assert isinstance(row, Tag)
    handle = row.find(class_="handle")
    assert isinstance(handle, Tag)
    assert handle.get_text(strip=True).startswith("id=")
    assert len(item.find_all(class_="handle")) == 1


def test_a_title_is_drawn_in_the_operation_colour(client: TestClient):
    css = client.get("/static/kennis.css").text

    assert re.search(r"\.hit \.title\s*\{[^}]*color: var\(--role-operation\)", css)
