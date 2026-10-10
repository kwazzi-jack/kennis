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
from click.testing import CliRunner
from fastapi.testclient import TestClient
from markupsafe import escape

from kennis.cli.__main__ import main
from kennis.context import existing_corpus
from kennis.engine.corpus.collection import Collection
from kennis.engine.rag.models import Chunk, SearchResult
from kennis.gui import words
from kennis.gui.app import build_app
from kennis.gui.pages import ordered_by
from kennis.gui.snippet import passage_of
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


def test_the_passage_is_the_whole_chunk_once(corpus: Path, client: TestClient):
    """Drawn whole and closed by the script, so opening it reveals text
    that was already there, around the window, rather than fetching or
    repeating it (#415). The last sentence is past any snippet's cut."""
    a_note(corpus, "calibration", LONG_BODY)

    item = items_of(hits_of(client, "antenna"))[0]
    passage = re.search(r'<div class="passage"[^>]*>(.*?)</div>', item, re.S)

    assert passage, item
    text = re.sub(r'<span class="gap"[^>]*>.*?</span>', "", passage.group(1))
    text = re.sub(r"<[^>]+>", "", text)
    assert "would have cut off before it ever reached the reader." in text
    assert "..." not in text
    for sentence in LONG_BODY.split(". "):
        assert text.count(sentence) == 1, sentence


def test_the_window_holds_the_first_match_and_the_rest_is_around_it():
    """A match deep in a chunk is still in what a closed passage shows."""
    body = "Opening words. " * 40 + "The antenna is here. " + "Closing words. " * 40

    passage = passage_of(body, terms=["antenna"])

    assert "<mark>antenna</mark>" in passage.window
    assert passage.before and passage.after
    assert (
        passage.before + passage.window + passage.after
        == passage_of(body, terms=["antenna"], limit=len(body)).window
    )


def test_a_passage_that_fits_has_nothing_to_open(corpus: Path, client: TestClient):
    """Found walking the window: a one-line note under a heading had a
    toggle and a leading ellipsis, because the heading's tags were left
    on the far side of a cut at the very start."""
    a_note(corpus, "calibration", "Calibration solves for antenna gains.")

    item = items_of(hits_of(client, "antenna"))[0]

    assert 'class="toggle"' not in item
    assert re.search(r'<span class="before"></span>', item)


def test_a_tag_open_at_a_boundary_is_closed_on_both_sides():
    body = "Lead text here. *" + "emphasised words " * 30 + "end* tail."

    passage = passage_of(body, terms=[], limit=60)

    # The fixture has to put a boundary inside the emphasis, or the
    # property holds for want of a tag to unbalance (#352).
    assert "<em>" in passage.window and "<em>" in passage.after
    for part in (passage.before, passage.window, passage.after):
        assert part.count("<em>") == part.count("</em>"), part


def test_without_a_script_nothing_is_hidden(corpus: Path, client: TestClient):
    """The server never closes a passage: only `passage.js` adds
    `closed`, so a reader without a script reads the whole chunk."""
    a_note(corpus, "calibration", LONG_BODY)

    page = hits_of(client, "antenna")

    # On class attributes, not the page: the fixture's own prose says
    # "closed", and a textual negative is satisfied by prose (#337).
    classes = " ".join(re.findall(r'class="([^"]*)"', page)).split()
    assert "closed" not in classes
    assert re.search(
        r"\.passage\.closed \.before[^{]*\{[^}]*display: none",
        client.get("/static/kennis.css").text,
    )


def test_the_toggle_is_worded_in_python(corpus: Path, client: TestClient):
    a_note(corpus, "calibration", LONG_BODY)

    item = items_of(hits_of(client, "antenna"))[0]
    toggle = re.search(r'<button[^>]*class="toggle"[^>]*>', item)

    assert toggle, item
    assert f'data-open="{words.SHOW_PASSAGE}"' in toggle.group(0)
    assert f'data-close="{words.HIDE_PASSAGE}"' in toggle.group(0)
    assert toggle.group(0).count("hidden") >= 1


def test_the_passage_script_composes_no_words():
    code = code_of("passage.js")

    assert "dataset.open" in code
    assert "dataset.close" in code
    # A string literal holding a space is a sentence, and words belong
    # to Python.
    assert not re.search(r"\"[A-Za-z]+ [A-Za-z ]+\"", code)


def test_the_passage_script_is_loaded_and_opens_one_at_a_time(client: TestClient):
    page = client.get("/").text

    assert '<script defer src="/static/passage.js">' in page
    assert 'aria-expanded="true"' in code_of("passage.js")


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

    assert page.count('<h2 class="place">') == 2, page
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

    assert "--strength-1: #440154" in light
    assert "--strength-5: #86d549" in light
    assert "--strength-1: #355f8d" in dark
    assert "--strength-5: #fde725" in dark


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


def test_the_order_control_states_its_limit(
    corpus: Path, client: TestClient, hybrid: None
):
    """Reordering three returned hits is not searching by one measure,
    and the best meaning-only hit may not be among them (#406)."""
    control = order_of(
        client.get("/hits", params={"q": "antenna", "scope": "notes"}).text
    )

    assert words.ORDER_LIMIT in control
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
