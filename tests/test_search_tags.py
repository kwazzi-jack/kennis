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
from kennis.engine.rag.models import Chunk
from kennis.engine.rag.search import _CANDIDATES
from kennis.engine.tags import Anchor, admitting
from kennis.retrieval import sweep

DOCUMENT = "k3v9x0a2mq"


def a_chunk(number: int, text: str, document: str = DOCUMENT) -> Chunk:
    return Chunk(
        id=f"{document}::{number}",
        collection="notes",
        document_id=document,
        chunk_index=number,
        text=text,
        source_path="notes/a.md",
        char_start=0,
        char_end=len(text),
    )


# ---------------------------------------------------------------------------
# What a tag admits


def test_a_document_tag_admits_every_chunk_of_it_and_no_other():
    chunks = [a_chunk(0, "a"), a_chunk(1, "b"), a_chunk(0, "c", "other00001")]

    admits = admitting({"t": (Anchor(DOCUMENT),)}, ("t",), chunks)

    assert [admits(chunk) for chunk in chunks] == [True, True, False]


def test_a_passage_tag_admits_the_chunk_it_is_placed_at_now():
    chunks = [a_chunk(0, "Intro."), a_chunk(1, "New."), a_chunk(2, "Gains drift.")]
    moved = Anchor(DOCUMENT, chunk=1, quote="Gains drift.")

    admits = admitting({"t": (moved,)}, ("t",), chunks)

    assert [admits(chunk) for chunk in chunks] == [False, False, True]


def test_a_detached_passage_admits_nothing():
    chunks = [a_chunk(0, "Intro."), a_chunk(1, "Other words.")]
    gone = Anchor(DOCUMENT, chunk=1, quote="Gains drift.")

    admits = admitting({"t": (gone,)}, ("t",), chunks)

    assert not any(admits(chunk) for chunk in chunks)


def test_several_tags_admit_what_all_of_them_name():
    chunks = [a_chunk(0, "a"), a_chunk(1, "b"), a_chunk(2, "c")]
    held = {
        "x": (Anchor(DOCUMENT),),
        "y": (Anchor(DOCUMENT, chunk=1, quote="b"),),
    }

    admits = admitting(held, ("x", "y"), chunks)

    assert [admits(chunk) for chunk in chunks] == [False, True, False]


def test_a_tag_the_store_does_not_hold_admits_nothing():
    chunks = [a_chunk(0, "a")]

    assert not admitting({"x": (Anchor(DOCUMENT),)}, ("x", "y"), chunks)(chunks[0])


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
