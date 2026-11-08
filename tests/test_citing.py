"""Citations: what `kennis cite` and the MCP tool `cite` return (#572, #592).

For each passage asked for: the citation in the configured CSL style with
the chunk's locator, the bibliography entry, and the `kennis://` link. The
agent composes neither (#572). Curly quotes are the style's typography, so
they are written here as escapes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.citing import CiteRequest
from kennis.cli.__main__ import main
from kennis.client import api
from kennis.context import existing_corpus
from kennis.engine.citing.locators import Locator
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.layout import index_root
from kennis.engine.rag.index import load_index
from kennis.mcp.tools.cite import CiteRequest as ToolRequest
from kennis.mcp.tools.cite import cite as cite_tool

PAPER_ID = "paper00001"
PAGE_ID = "page000001"

PAPER = f"""\
---
id: {PAPER_ID}
title: Revisiting the radio interferometer measurement equation
owner: user
source:
  from: 'arxiv:1101.1764'
  via: verbatim
  format: markdown
  at: '2026-11-01T00:00:00Z'
id_from: 'arxiv:1101.1764'
bib:
  citekey: smirnov2011
  authors: Smirnov, O. M. and Tasse, C. and Other, A.
  year: '2011'
  arxiv_id: '1101.1764'
---

# Revisiting the radio interferometer measurement equation

## Abstract

The measurement equation, revisited for direction-dependent effects, in a
form that carries every effect along the signal path.

## 2 Method

## 2.1 Data reduction

The visibilities were flagged for interference before calibration, and the
flags were kept with the data.

## 2.2 Solving

The gains were solved for per antenna and per interval, with a prior that
keeps neighbouring intervals close.
"""

PAGE = f"""\
---
id: {PAGE_ID}
title: Partitioning Guide
owner: user
source:
  from: 'url:https://xarray-ms.readthedocs.io/en/latest/partitioning.html'
  via: html
  format: html
  at: '2026-11-01T00:00:00Z'
id_from: 'docs:xarray-ms/latest/partitioning'
docs:
  project: xarray-ms
  page: partitioning
  base_url: 'https://xarray-ms.readthedocs.io/en/latest/'
  version: latest
---

# Partitioning Guide

## Partitioning schemes

A measurement set is partitioned by field and spectral window.
"""


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A paper, a docs page and a note, indexed."""
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    # Small chunks, so each section of the paper is a chunk of its own.
    monkeypatch.setenv("KENNIS_CHUNKING_SIZE", "100")
    monkeypatch.setenv("KENNIS_CHUNKING_OVERLAP", "0")
    run = CliRunner()
    assert run.invoke(main, ["corpus", "init"]).exit_code == 0
    root = existing_corpus().corpus_root
    (root / "literature" / "smirnov.md").write_text(PAPER, encoding="utf-8")
    page = root / "docs" / "xarray-ms" / "latest" / "Partitioning Guide.md"
    page.parent.mkdir(parents=True)
    page.write_text(PAGE, encoding="utf-8")
    source = tmp_path / "Gains.md"
    source.write_text("# Gains\n\nGains drift slowly.\n", encoding="utf-8")
    assert run.invoke(main, ["corpus", "add", "-n", str(source)]).exit_code == 0
    indexed = run.invoke(main, ["corpus", "index"])
    assert indexed.exit_code == 0, indexed.output
    return root


def chunk_holding(root: Path, collection: str, document_id: str, words: str) -> int:
    """The chunk of a document whose text holds `words`, asserted unique."""
    index = load_index(index_root(root), collection)
    held = [
        chunk.chunk_index
        for chunk in index.chunks
        if chunk.document_id == document_id and words in chunk.text
    ]
    assert len(held) == 1, held
    return held[0]


def note_id(root: Path) -> str:
    (document,) = Collection(root=root, name="notes").contents().documents
    return document.id


def test_a_paper_is_cited_with_its_section_and_linked_to_its_chunk(corpus: Path):
    chunk = chunk_holding(corpus, "literature", PAPER_ID, "flagged for interference")

    cited = api.cite(corpus, [CiteRequest(PAPER_ID, chunk)])

    (citation,) = cited.citations
    assert citation.citation == "(Smirnov, Tasse and Other, 2011, sec. 2.1)"
    assert citation.locator == Locator("section", "2.1")
    assert citation.link == f"kennis://open/{PAPER_ID}/{chunk}"
    assert citation.collection == "literature"
    assert citation.reference == (
        "Smirnov, O.M., Tasse, C. and Other, A. (2011) "
        "\u201cRevisiting the radio interferometer measurement equation\u201d. "
        "Available at: https://arxiv.org/abs/1101.1764."
    )
    assert cited.refused == []


def test_the_markdown_is_the_citation_linked(corpus: Path):
    chunk = chunk_holding(corpus, "literature", PAPER_ID, "solved for per antenna")

    (citation,) = api.cite(corpus, [CiteRequest(PAPER_ID, chunk)]).citations

    assert citation.markdown == f"[{citation.citation}]({citation.link})"


def test_a_handle_other_than_the_identifier_is_accepted(corpus: Path):
    """The resolution `kennis read` uses: here the citekey."""
    (citation,) = api.cite(corpus, [CiteRequest("smirnov2011", None)]).citations

    assert citation.document_id == PAPER_ID
    assert citation.link == f"kennis://open/{PAPER_ID}"


def test_a_whole_document_is_cited_without_a_locator(corpus: Path):
    (citation,) = api.cite(corpus, [CiteRequest(PAPER_ID, None)]).citations

    assert citation.citation == "(Smirnov, Tasse and Other, 2011)"
    assert citation.locator is None


def test_a_docs_page_is_cited_by_its_project(corpus: Path):
    chunk = chunk_holding(corpus, "docs", PAGE_ID, "partitioned by field")

    (citation,) = api.cite(corpus, [CiteRequest(PAGE_ID, chunk)]).citations

    assert citation.citation == "(xarray-ms, no date, sec. Partitioning schemes)"
    assert "https://xarray-ms.readthedocs.io/en/latest/partitioning.html" in (
        citation.reference
    )


def test_a_note_is_cited_by_its_title(corpus: Path):
    identifier = note_id(corpus)

    (citation,) = api.cite(corpus, [CiteRequest(identifier, 0)]).citations

    assert citation.citation == '"Gains"'
    assert citation.link == f"kennis://open/{identifier}/0"


def test_passages_in_different_sections_are_not_marked_alike(corpus: Path):
    """Each section reads differently, and the same place asked for twice
    is the same citation rather than two that read alike."""
    flagged = chunk_holding(corpus, "literature", PAPER_ID, "flagged for interference")
    solved = chunk_holding(corpus, "literature", PAPER_ID, "solved for per antenna")

    cited = api.cite(
        corpus,
        [
            CiteRequest(PAPER_ID, None),
            CiteRequest(PAPER_ID, flagged),
            CiteRequest(PAPER_ID, solved),
            CiteRequest("smirnov2011", None),
        ],
    )

    alike = [citation.alike for citation in cited.citations]
    # The first and last name the same place, so they are not "alike": they
    # are the same citation. Different sections read differently.
    assert alike == [[], [], [], []]


def test_passages_with_the_same_words_and_different_links_are_marked(
    corpus: Path,
):
    whole = CiteRequest(PAPER_ID, None)
    abstract = chunk_holding(corpus, "literature", PAPER_ID, "direction-dependent")

    cited = api.cite(corpus, [whole, CiteRequest(PAPER_ID, abstract)])

    first, second = cited.citations
    assert second.locator == Locator("section", "Abstract")
    assert first.alike == second.alike == []

    # Two chunks of a note: a note has no locator, so they read the same.
    identifier = note_id(corpus)
    cited = api.cite(
        corpus, [CiteRequest(identifier, 0), CiteRequest(identifier, None)]
    )
    assert [citation.alike for citation in cited.citations] == [[1], [0]]


def test_a_request_that_fails_does_not_cost_the_others(corpus: Path):
    cited = api.cite(
        corpus, [CiteRequest("zzzzzzzzzz", 0), CiteRequest(PAPER_ID, None)]
    )

    assert [citation.document_id for citation in cited.citations] == [PAPER_ID]
    (refusal,) = cited.refused
    assert refusal.position == 0
    assert "zzzzzzzzzz" in refusal.message


def test_a_chunk_the_document_has_not_got_is_refused(corpus: Path):
    cited = api.cite(corpus, [CiteRequest(PAPER_ID, 999)])

    assert cited.citations == []
    (refusal,) = cited.refused
    assert "999" in refusal.message


# --- the style -------------------------------------------------------------

TITLE_ONLY = """\
<?xml version="1.0" encoding="utf-8"?>
<style xmlns="http://purl.org/net/xbiblio/csl" class="in-text" version="1.0">
  <info><title>Title only</title><id>title-only</id>
  <updated>2026-11-01T00:00:00+00:00</updated></info>
  <citation><layout prefix="[" suffix="]">
    <text variable="title"/><text variable="locator" prefix=" @"/>
  </layout></citation>
  <bibliography><layout><text variable="title"/></layout></bibliography>
</style>
"""


def test_a_style_named_by_the_setting_formats_the_citation(
    corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    style = tmp_path / "title-only.csl"
    style.write_text(TITLE_ONLY, encoding="utf-8")
    monkeypatch.setenv("KENNIS_LITERATURE_CITATION_STYLE", str(style))
    chunk = chunk_holding(corpus, "literature", PAPER_ID, "flagged for interference")

    (citation,) = api.cite(corpus, [CiteRequest(PAPER_ID, chunk)]).citations

    assert citation.citation == (
        "[Revisiting the radio interferometer measurement equation @2.1]"
    )


def test_a_style_that_cannot_be_read_is_refused_naming_the_setting(
    corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv(
        "KENNIS_LITERATURE_CITATION_STYLE", str(tmp_path / "missing.csl")
    )

    result = CliRunner().invoke(main, ["cite", PAPER_ID])

    assert result.exit_code != 0
    assert "literature.citation_style" in result.output


# --- kennis cite -------------------------------------------------------------


def test_kennis_cite_takes_a_hit_s_handle_as_search_prints_it(corpus: Path):
    chunk = chunk_holding(corpus, "literature", PAPER_ID, "flagged for interference")

    result = CliRunner().invoke(main, ["cite", f"id={PAPER_ID}", f"chunk={chunk}"])

    assert result.exit_code == 0, result.output
    assert "(Smirnov, Tasse and Other, 2011, sec. 2.1)" in result.output
    assert f"kennis://open/{PAPER_ID}/{chunk}" in result.output


def test_a_long_reference_wraps_under_its_link(corpus: Path):
    """Every line after a citation's own is indented, so a wrapped reference
    does not run back to the margin where the next citation begins."""
    result = CliRunner().invoke(main, ["cite", PAPER_ID], terminal_width=60)

    assert result.exit_code == 0, result.output
    lines = [line for line in result.output.splitlines() if line.strip()]
    assert lines[0].startswith("Cited ")
    assert len(lines) > 3, "the reference did not wrap at this width"
    assert all(line.startswith("  ") for line in lines[1:]), lines


def test_kennis_cite_takes_links_and_handles_together(corpus: Path):
    chunk = chunk_holding(corpus, "docs", PAGE_ID, "partitioned by field")

    result = CliRunner().invoke(
        main, ["cite", f"kennis://open/{PAGE_ID}/{chunk}", "smirnov2011"]
    )

    assert result.exit_code == 0, result.output
    assert "(xarray-ms, no date, sec. Partitioning schemes)" in result.output
    assert "(Smirnov, Tasse and Other, 2011)" in result.output


def test_kennis_cite_refuses_a_chunk_with_nothing_before_it(corpus: Path):
    result = CliRunner().invoke(main, ["cite", "chunk=3"])

    assert result.exit_code != 0
    assert "chunk=3" in result.output


def test_kennis_cite_reports_a_refusal_and_fails(corpus: Path):
    result = CliRunner().invoke(main, ["cite", "zzzzzzzzzz", PAPER_ID])

    assert result.exit_code != 0
    assert "zzzzzzzzzz" in result.output
    assert "(Smirnov, Tasse and Other, 2011)" in result.output


# --- the MCP tool ------------------------------------------------------------


def test_the_tool_gives_each_citation_ready_to_write(corpus: Path):
    chunk = chunk_holding(corpus, "literature", PAPER_ID, "flagged for interference")

    answer = cite_tool([ToolRequest(document_id=PAPER_ID, chunk=chunk)])

    link = f"kennis://open/{PAPER_ID}/{chunk}"
    assert f"[(Smirnov, Tasse and Other, 2011, sec. 2.1)]({link})" in answer
    assert f"link: {link}" in answer
    assert "locator: section 2.1" in answer
    assert "reference: Smirnov, O.M., Tasse, C. and Other, A. (2011)" in answer


def test_the_tool_says_which_citations_read_the_same(corpus: Path):
    identifier = note_id(corpus)

    answer = cite_tool(
        [
            ToolRequest(document_id=identifier, chunk=0),
            ToolRequest(document_id=identifier),
        ]
    )

    assert "reads the same as [2]" in answer
    assert "reads the same as [1]" in answer


def test_the_tool_answers_the_others_when_one_fails(corpus: Path):
    answer = cite_tool(
        [ToolRequest(document_id="zzzzzzzzzz"), ToolRequest(document_id=PAPER_ID)]
    )

    assert "zzzzzzzzzz" in answer
    assert "(Smirnov, Tasse and Other, 2011)" in answer


def test_the_tool_refuses_an_empty_batch(corpus: Path):
    assert cite_tool([]) == "no requests"


# ---------------------------------------------------------------------------
# The passage a citation quotes (#629's follow-up, sketch
# 2026-11-06-copy-passage-with-citation)


def test_a_citation_carries_its_passage_s_words_and_a_document_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from kennis.citing import cite
    from test_cli_tags import PAPER_ID, SOLVING, chunk_holding, indexed_paper

    root = indexed_paper(tmp_path, monkeypatch)
    solving = chunk_holding(root, SOLVING)

    passage, whole = cite(
        existing_corpus(), [CiteRequest(PAPER_ID, solving), CiteRequest(PAPER_ID)]
    ).citations

    assert passage.passage is not None
    assert passage.passage.startswith(SOLVING)
    assert "#" not in passage.passage and "\n" not in passage.passage
    assert whole.passage is None


def test_a_project_passage_carries_its_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from kennis.citing import cite
    from kennis.engine.context.bundle import init_bundle
    from test_cli_tags import indexed_paper, run

    indexed_paper(tmp_path, monkeypatch)
    project = tmp_path / "pipelines"
    (project / ".git").mkdir(parents=True)
    init_bundle(project)
    (project / ".context" / "ours.md").write_text(
        "---\ntitle: Ours\n---\nWe solve the gains\nper scan.\n", encoding="utf-8"
    )
    monkeypatch.chdir(project)
    run("context", "index")

    (citation,) = cite(
        existing_corpus(), [CiteRequest("ours.md", 0, bundle=project / ".context")]
    ).citations

    assert citation.passage == "We solve the gains per scan."
