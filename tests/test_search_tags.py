"""A search filtered by tags (#625, sketch 2026-11-06-tags, part t2).

A tag keeps the hits it names - every chunk of a tagged document, and the
chunk a tagged passage is placed at now - and changes no ranking. Several
tags keep what all of them name. **The filter must not lose a tagged chunk
that ranks below the candidate window**: `search` filters each leg's top
`_CANDIDATES` chunks, and a tag is the most selective filter there is.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.context import existing_corpus
from kennis.engine.context.bundle import init_bundle
from kennis.engine.corpus.collection import Collection
from kennis.engine.rag.search import _CANDIDATES
from kennis.retrieval import sweep

# ---------------------------------------------------------------------------
# Searching


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """More notes about gains than the candidate window holds, each saying
    it more often than the one long note that is tagged."""
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    run("corpus", "init")
    sources = tmp_path / "sources"
    sources.mkdir()
    paths: list[str] = []
    for number in range(_CANDIDATES + 10):
        path = sources / f"loud{number:03d}.md"
        path.write_text(
            f"# Loud {number}\n\nGains, gains and gains again: gains.\n",
            encoding="utf-8",
        )
        paths.append(str(path))
    quiet = sources / "quiet.md"
    filler = " ".join(f"word{index}" for index in range(300))
    quiet.write_text(f"# Quiet\n\nThe gains once. {filler}\n", encoding="utf-8")
    paths.append(str(quiet))
    run("corpus", "add", "-n", *paths)
    run("corpus", "index")
    return existing_corpus().corpus_root


def run(*arguments: str) -> str:
    answered = CliRunner().invoke(main, list(arguments))
    assert answered.exit_code == 0, answered.output
    return " ".join(answered.output.split())


def note_id(root: Path, title: str) -> str:
    (document,) = [
        one
        for one in Collection(root=root, name="notes").contents().documents
        if one.frontmatter.title == title
    ]
    return document.id


def found_ids(
    question: str, *, tags: tuple[str, ...] = (), top_k: int = 5
) -> list[str]:
    swept = sweep(
        question,
        scopes=["notes"],
        named=True,
        top_k=top_k,
        bundle=None,
        tags=tags,
    )
    return [hit.result.chunk.document_id for hit in swept.groups.get("notes", [])]


def test_a_tagged_note_below_the_candidate_window_is_still_found(corpus: Path):
    quiet = note_id(corpus, "quiet")
    assert quiet not in found_ids("gains", top_k=_CANDIDATES), (
        "the fixture no longer puts the tagged note below the window"
    )
    run("tag", "drift", quiet)

    assert found_ids("gains", tags=("drift",)) == [quiet]


def test_a_tag_changes_no_ranking(corpus: Path):
    kept = [note_id(corpus, f"loud{number:03d}") for number in (3, 17, 40)]
    for document in kept:
        run("tag", "some", document)

    everything = found_ids("gains", top_k=_CANDIDATES + 20)

    assert found_ids("gains", tags=("some",)) == [
        one for one in everything if one in kept
    ]


def test_several_tags_keep_what_all_of_them_name(corpus: Path):
    first, second = note_id(corpus, "loud001"), note_id(corpus, "loud002")
    run("tag", "a,b", first)
    run("tag", "a", second)

    assert found_ids("gains", tags=("a", "b")) == [first]


def test_a_tag_nothing_carries_is_refused_naming_the_listing(corpus: Path):
    answered = CliRunner().invoke(main, ["search", "gains", "--tag", "nowhere"])

    assert answered.exit_code != 0
    assert "kennis tags" in answered.output


def test_kennis_search_takes_tags(corpus: Path):
    quiet = note_id(corpus, "quiet")
    run("tag", "Drift", quiet)

    said = run("search", "gains", "--collection", "notes", "--tag", "drift")

    assert f"id={quiet}" in said
    assert "loud0" not in said


def test_a_tagged_passage_keeps_only_its_chunk(corpus: Path):
    from kennis.engine.corpus.layout import index_root
    from kennis.engine.rag.index import load_index

    quiet = note_id(corpus, "quiet")
    chunks = [
        chunk
        for chunk in load_index(index_root(corpus), "notes").chunks
        if chunk.document_id == quiet
    ]
    assert len(chunks) > 1, "the fixture no longer gives the note two chunks"
    run("tag", "drift", f"id={quiet}", f"chunk={chunks[-1].chunk_index}")

    swept = sweep(
        "word299 gains",
        scopes=["notes"],
        named=True,
        top_k=10,
        bundle=None,
        tags=("drift",),
    )

    assert [
        (hit.result.chunk.document_id, hit.result.chunk.chunk_index)
        for hit in swept.groups["notes"]
    ] == [(quiet, chunks[-1].chunk_index)]


# ---------------------------------------------------------------------------
# A project's context


def test_a_project_s_tags_filter_its_context(
    corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "pipelines"
    (root / ".git").mkdir(parents=True)
    init_bundle(root)
    for name in ("ours", "theirs"):
        (root / ".context" / f"{name}.md").write_text(
            f"---\ntitle: {name}\n---\nWe solve the gains per scan.\n",
            encoding="utf-8",
        )
    monkeypatch.chdir(root)
    run("context", "index")
    run("tag", "mine", "path=.context/ours.md")

    said = run("search", "gains", "--collection", "context", "--tag", "mine")

    assert "path=.context/ours.md" in said
    assert "theirs.md" not in said
