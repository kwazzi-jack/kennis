"""A passage tag's chunk hint kept current (#626, sketch 2026-11-06-tag-hints).

A passage is found again by its quotation, and where the words occur in
several chunks the one nearest the stored hint is taken. So the hint is
rewritten to where the passage is now: in every store a tag change writes,
and in the corpus's `tags.yml` after an index build, inside that build's
commit. A project's file is rewritten only when its tags change, because it
is the person's file in their repository.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kennis.engine.context.bundle import init_bundle
from kennis.engine.context.index import load_bundle_index
from kennis.engine.rag.models import Chunk
from kennis.engine.tags import (
    TAGS_FILENAME,
    Anchor,
    Placed,
    placed,
    read_tags,
    rehinted,
    with_tags,
    written,
)
from test_cli_tags import (
    PAPER,
    PAPER_ID,
    SOLVING,
    chunk_holding,
    git,
    indexed_paper,
    run,
)

DOCUMENT = "k3v9x0a2mq"
REPEATED = "The gains are solved per scan."


def a_chunk(number: int, text: str, document: str = DOCUMENT) -> Chunk:
    return Chunk(
        id=f"{document}::{number}",
        collection="literature",
        document_id=document,
        chunk_index=number,
        text=text,
        source_path="literature/a.md",
        char_start=0,
        char_end=len(text),
    )


def repeated_at(*numbers: int) -> list[Chunk]:
    """Fourteen chunks, the repeated words at `numbers`, other words elsewhere."""
    return [
        a_chunk(number, REPEATED if number in numbers else f"Section {number}.")
        for number in range(14)
    ]


# ---------------------------------------------------------------------------
# The engine


def test_a_hint_rewritten_after_each_edit_follows_its_passage():
    """Words at chunks 2 and 8, the passage at 8; each edit inserts two
    chunks before both. Left at 8, the hint is nearer 6 than 12 after two
    edits; rewritten after the first, it stays with the passage."""
    tagged = Anchor(DOCUMENT, chunk=8, quote="The gains are solved")
    first_edit, second_edit = repeated_at(4, 10), repeated_at(6, 12)
    assert placed(tagged, second_edit) == Placed(6), "the fixture no longer drifts"

    (after_first,) = rehinted({"a": (tagged,)}, first_edit)["a"]

    assert after_first == Anchor(DOCUMENT, chunk=10, quote="The gains are solved")
    assert placed(after_first, second_edit) == Placed(12)


def test_a_detached_or_unchecked_passage_keeps_its_hint():
    gone = Anchor(DOCUMENT, chunk=3, quote="Words no chunk holds")
    elsewhere = Anchor("other00001", chunk=5, quote="The gains")
    held = {"a": (gone, elsewhere)}

    assert rehinted(held, repeated_at(1)) == held


def test_a_whole_document_tag_is_left_as_it_is():
    held = {"a": (Anchor(DOCUMENT),)}

    assert rehinted(held, repeated_at(1)) == held


def test_two_targets_that_land_on_one_chunk_are_kept_once():
    first = Anchor(DOCUMENT, chunk=4, quote="The gains are solved")
    second = Anchor(DOCUMENT, chunk=9, quote="The gains are solved")

    assert rehinted({"a": (first, second)}, repeated_at(6)) == {
        "a": (Anchor(DOCUMENT, chunk=6, quote="The gains are solved"),)
    }


# ---------------------------------------------------------------------------
# The corpus

INSERTED = (
    "## Preface\n\nA section inserted ahead of the abstract, long enough to be "
    "a chunk of its own when the chunks are small, so that every later chunk "
    "of the paper is numbered one higher than it was.\n\n## Abstract"
)


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return indexed_paper(tmp_path, monkeypatch)


def edited(root: Path) -> None:
    """The paper with a section ahead of the others, so its chunks move."""
    (root / "literature" / "smirnov.md").write_text(
        PAPER.replace("## Abstract", INSERTED, 1), encoding="utf-8"
    )


def test_an_index_build_rewrites_the_hints_inside_its_own_commit(corpus: Path):
    before = chunk_holding(corpus, SOLVING)
    run("tag", "calibration", f"id={PAPER_ID}", f"chunk={before}")
    edited(corpus)

    run("corpus", "index")

    after = chunk_holding(corpus, SOLVING)
    assert after != before, "the edit no longer moves the passage"
    (anchor,) = read_tags(corpus / TAGS_FILENAME)["calibration"]
    assert anchor.chunk == after
    assert git(corpus, "status", "--porcelain") == ""
    subject = git(corpus, "log", "-1", "--format=%s")
    assert subject.startswith("index(")
    assert TAGS_FILENAME in git(corpus, "show", "--name-only", "--format=", "HEAD")


def test_an_index_build_that_moves_no_passage_leaves_the_file_alone(corpus: Path):
    solving = chunk_holding(corpus, SOLVING)
    run("tag", "calibration", f"id={PAPER_ID}", f"chunk={solving}")

    run("corpus", "index")

    touching = git(corpus, "log", "--format=%s", "--", TAGS_FILENAME).splitlines()
    assert [subject.split("(")[0] for subject in touching] == ["tag"]


def test_a_tag_change_rewrites_every_hint_in_its_store(corpus: Path):
    """A hint written wrong by hand stands until the next tag change to the
    corpus, which places every passage and writes where each is now."""
    solving = chunk_holding(corpus, SOLVING)
    stale = Anchor(PAPER_ID, chunk=0, quote=SOLVING)
    (corpus / TAGS_FILENAME).write_text(
        written(with_tags({}, ("calibration",), stale), colours={}), encoding="utf-8"
    )

    run("tag", "to-read", f"id={PAPER_ID}")

    assert read_tags(corpus / TAGS_FILENAME)["calibration"] == (
        Anchor(PAPER_ID, chunk=solving, quote=SOLVING),
    )


# ---------------------------------------------------------------------------
# A project


@pytest.fixture
def project(corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "pipelines"
    (root / ".git").mkdir(parents=True)
    init_bundle(root)
    (root / ".context" / "ours.md").write_text(_ours(), encoding="utf-8")
    (root / ".context" / "theirs.md").write_text(
        "---\ntitle: theirs\n---\nWe flag the data first.\n", encoding="utf-8"
    )
    monkeypatch.chdir(root)
    run("context", "index")
    return root / ".context"


def _ours(inserted: str = "") -> str:
    return (
        "---\ntitle: ours\n---\n"
        f"{inserted}"
        "## Solving\n\nWe solve the gains per scan, with a prior that keeps "
        "neighbouring intervals close and a reference antenna fixed.\n"
    )


def solving_in(project: Path) -> int:
    held = [
        chunk.chunk_index
        for chunk in load_bundle_index(project).chunks
        if chunk.document_id == "ours.md" and "We solve the gains" in chunk.text
    ]
    assert len(held) == 1, held
    return held[0]


def test_a_project_s_hints_wait_for_its_next_tag_change(project: Path):
    before = solving_in(project)
    run("tag", "mine", "path=.context/ours.md", f"chunk={before}")
    stored = (project / TAGS_FILENAME).read_text(encoding="utf-8")
    (project / "ours.md").write_text(
        _ours(
            "## First\n\nA section inserted ahead of the solving section, long "
            "enough to be a chunk of its own when the chunks are small.\n\n"
        ),
        encoding="utf-8",
    )

    run("context", "index")

    assert (project / TAGS_FILENAME).read_text(encoding="utf-8") == stored
    after = solving_in(project)
    assert after != before, "the edit no longer moves the passage"

    run("tag", "other", "path=.context/theirs.md")

    (anchor,) = read_tags(project / TAGS_FILENAME)["mine"]
    assert anchor.chunk == after
