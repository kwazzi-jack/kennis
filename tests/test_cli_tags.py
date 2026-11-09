"""Tags from the command line, through the service (#625, sketch
2026-11-06-tags, part t1).

`kennis tag NAMES PASSAGE...` and `kennis untag` take a passage as `kennis
cite` does; `kennis tags [NAME]` lists. Corpus tags are `tags.yml` at the
corpus root, committed by kennis; a project's are `.context/tags.yml`,
written and left for the person to commit. A passage that can no longer be
found is listed as detached, with the command that removes its tag.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.context import existing_corpus
from kennis.engine.context.bundle import init_bundle
from kennis.engine.corpus.layout import index_root
from kennis.engine.rag.index import load_index
from kennis.engine.tags import Anchor, read_tags
from kennis.links import context_link, link_to

PAPER_ID = "paper00001"

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
  authors: Smirnov, O. M. and Tasse, C.
  year: '2011'
  arxiv_id: '1101.1764'
---

# Revisiting the radio interferometer measurement equation

## Abstract

The measurement equation, revisited for direction-dependent effects, in a
form that carries every effect along the signal path.

## 2.1 Data reduction

The visibilities were flagged for interference before calibration, and the
flags were kept with the data.

## 2.2 Solving

The gains were solved for per antenna and per interval, with a prior that
keeps neighbouring intervals close.
"""

SOLVING = "The gains were solved for per antenna"


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return indexed_paper(tmp_path, monkeypatch)


def indexed_paper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A paper, indexed in small chunks, one section each."""
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    monkeypatch.setenv("KENNIS_CHUNKING_SIZE", "100")
    monkeypatch.setenv("KENNIS_CHUNKING_OVERLAP", "0")
    run("corpus", "init")
    root = existing_corpus().corpus_root
    (root / "literature" / "smirnov.md").write_text(PAPER, encoding="utf-8")
    run("corpus", "index")
    return root


def run(*arguments: str) -> str:
    answered = CliRunner().invoke(main, list(arguments))
    assert answered.exit_code == 0, answered.output
    return " ".join(answered.output.split())


def refused(*arguments: str) -> str:
    answered = CliRunner().invoke(main, list(arguments))
    assert answered.exit_code != 0, answered.output
    return " ".join(answered.output.split())


def chunk_holding(root: Path, words: str) -> int:
    index = load_index(index_root(root), "literature")
    held = [
        chunk.chunk_index
        for chunk in index.chunks
        if chunk.document_id == PAPER_ID and words in " ".join(chunk.text.split())
    ]
    assert len(held) == 1, held
    return held[0]


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        text=True,
        check=True,
        stdin=subprocess.DEVNULL,
        timeout=30,
    ).stdout


# ---------------------------------------------------------------------------
# Tagging the corpus


def test_a_passage_is_tagged_as_search_prints_it(corpus: Path):
    chunk = chunk_holding(corpus, SOLVING)

    said = run("tag", "calibration", f"id={PAPER_ID}", f"chunk={chunk}")

    (anchor,) = read_tags(corpus / "tags.yml")["calibration"]
    assert anchor.document == PAPER_ID
    assert anchor.chunk == chunk
    assert anchor.quote is not None and SOLVING.startswith(anchor.quote[:20])
    assert "calibration" in said


def test_a_tag_is_committed_and_leaves_nothing_unrecorded(corpus: Path):
    run("tag", "calibration", f"id={PAPER_ID}")

    assert "tags.yml" in git(corpus, "show", "--name-only", "--format=", "HEAD")
    assert git(corpus, "status", "--porcelain") == ""


def test_a_whole_document_is_tagged_by_any_handle(corpus: Path):
    run("tag", "to-read", "smirnov2011")

    assert read_tags(corpus / "tags.yml") == {"to-read": (Anchor(PAPER_ID),)}


def test_a_link_names_the_passage(corpus: Path):
    chunk = chunk_holding(corpus, SOLVING)

    run("tag", "calibration", link_to(PAPER_ID, chunk))

    (anchor,) = read_tags(corpus / "tags.yml")["calibration"]
    assert anchor.chunk == chunk


def test_several_names_are_given_with_commas_and_folded(corpus: Path):
    run("tag", "Calibration,to-cite", f"id={PAPER_ID}")

    assert set(read_tags(corpus / "tags.yml")) == {"calibration", "to-cite"}


def test_tagging_again_says_so_and_commits_nothing(corpus: Path):
    run("tag", "calibration", f"id={PAPER_ID}")
    before = git(corpus, "rev-parse", "HEAD")

    said = run("tag", "calibration", f"id={PAPER_ID}")

    assert git(corpus, "rev-parse", "HEAD") == before
    assert "already" in said


def test_untagging_removes_and_drops_an_empty_tag(corpus: Path):
    chunk = chunk_holding(corpus, SOLVING)
    run("tag", "calibration,to-cite", f"id={PAPER_ID}", f"chunk={chunk}")

    run("untag", "calibration", f"id={PAPER_ID}", f"chunk={chunk}")

    assert set(read_tags(corpus / "tags.yml")) == {"to-cite"}


def test_a_chunk_the_index_has_not_got_is_refused_and_nothing_written(corpus: Path):
    said = refused("tag", "calibration", f"id={PAPER_ID}", "chunk=999")

    assert "kennis corpus index" in said
    assert not (corpus / "tags.yml").exists()


def test_one_refused_passage_writes_none_of_the_batch(corpus: Path):
    """All or nothing, so a person fixes the batch once rather than finding
    half of it tagged."""
    said = refused("tag", "calibration", f"id={PAPER_ID}", "chunk=999", "smirnov2011")

    assert "chunk 999" in said
    assert not (corpus / "tags.yml").exists()


def test_a_name_with_a_space_is_refused(corpus: Path):
    refused("tag", "phase calibration", f"id={PAPER_ID}")

    assert not (corpus / "tags.yml").exists()


# ---------------------------------------------------------------------------
# Listing


def test_tags_are_listed_with_their_counts(corpus: Path):
    chunk = chunk_holding(corpus, SOLVING)
    run("tag", "calibration", f"id={PAPER_ID}", f"chunk={chunk}")
    run("tag", "calibration,to-read", f"id={PAPER_ID}")

    said = run("tags")

    assert "calibration 2" in said
    assert "to-read 1" in said


def test_a_tag_lists_each_passage_with_its_title_link_and_words(corpus: Path):
    chunk = chunk_holding(corpus, SOLVING)
    run("tag", "calibration", f"id={PAPER_ID}", f"chunk={chunk}")

    said = run("tags", "calibration")

    assert "Revisiting the radio interferometer measurement equation" in said
    assert link_to(PAPER_ID, chunk) in said
    assert "The gains were solved" in said


def test_a_passage_moved_by_an_edit_is_listed_where_it_is_now(corpus: Path):
    old = chunk_holding(corpus, SOLVING)
    run("tag", "calibration", f"id={PAPER_ID}", f"chunk={old}")
    paper = corpus / "literature" / "smirnov.md"
    paper.write_text(
        paper.read_text(encoding="utf-8").replace(
            "## 2.2 Solving",
            "## 2.15 Interlude\n\nA paragraph added before the solving, long "
            "enough to be a chunk of its own in this index.\n\n## 2.2 Solving",
        ),
        encoding="utf-8",
    )
    run("corpus", "index")
    new = chunk_holding(corpus, SOLVING)
    assert new != old, "the fixture no longer moves the passage"

    said = run("tags", "calibration")

    assert link_to(PAPER_ID, new) in said
    assert "detached" not in said


def test_a_passage_whose_words_are_gone_is_listed_as_detached_with_its_untag(
    corpus: Path,
):
    chunk = chunk_holding(corpus, SOLVING)
    run("tag", "calibration", f"id={PAPER_ID}", f"chunk={chunk}")
    paper = corpus / "literature" / "smirnov.md"
    paper.write_text(
        paper.read_text(encoding="utf-8").replace(
            "The gains were solved for per antenna", "Each antenna's solutions came"
        ),
        encoding="utf-8",
    )
    run("corpus", "index")

    said = run("tags", "calibration")

    assert "detached" in said
    assert f"kennis untag calibration {link_to(PAPER_ID, chunk)}" in said


def test_a_detached_passage_s_untag_works_as_printed(corpus: Path):
    """The printed chunk may no longer exist; untagging must not need it."""
    chunk = chunk_holding(corpus, SOLVING)
    run("tag", "calibration", f"id={PAPER_ID}", f"chunk={chunk}")
    paper = corpus / "literature" / "smirnov.md"
    paper.write_text(
        paper.read_text(encoding="utf-8").split("## 2.2")[0], encoding="utf-8"
    )
    run("corpus", "index")

    run("untag", "calibration", link_to(PAPER_ID, chunk))

    assert read_tags(corpus / "tags.yml") == {}


# ---------------------------------------------------------------------------
# A project's context


@pytest.fixture
def project(corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "pipelines"
    (root / ".git").mkdir(parents=True)
    init_bundle(root)
    (root / ".context" / "ours.md").write_text(
        "---\ntitle: Ours\n---\nWe solve the gains per scan here.\n", encoding="utf-8"
    )
    monkeypatch.chdir(root)
    run("context", "index")
    return root / ".context"


def test_a_context_passage_is_tagged_in_the_project_s_file(project: Path, corpus: Path):
    run("tag", "ours", "path=.context/ours.md", "chunk=0")

    (anchor,) = read_tags(project / "tags.yml")["ours"]
    assert anchor.document == "ours.md"
    assert anchor.chunk == 0
    assert not (corpus / "tags.yml").exists()


def test_tags_in_a_project_are_listed_beside_the_corpus_s(project: Path):
    run("tag", "ours", "path=.context/ours.md", "chunk=0")
    run("tag", "calibration", f"id={PAPER_ID}")

    said = run("tags")

    assert "ours 1" in said
    assert "calibration 1" in said


def test_a_context_passage_is_listed_with_its_context_link(project: Path):
    run("tag", "ours", "path=.context/ours.md", "chunk=0")

    said = run("tags", "ours")

    assert context_link("pipelines", "ours.md", 0) in said
