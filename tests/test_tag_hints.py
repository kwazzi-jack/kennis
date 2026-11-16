"""A selection's hint kept current, and its chunks derived (#626, #50;
sketches 2026-11-06-tag-hints and 2026-11-16-annotations).

A selection is found again by its words, and where they occur more than
once the surroundings and then the stored hint decide. So the hint is
rewritten to where the selection is now in every store a tag change
writes. An index build writes nothing to a store: which chunks carry a
selection is derived for each build. A project's file is rewritten only
when its tags change, because it is the person's file in their
repository.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from annotating import ANNOTATIONS, tagged
from kennis.engine.context.bundle import init_bundle
from kennis.engine.context.index import load_bundle_index
from test_cli_tags import (
    PAPER,
    PAPER_ID,
    SOLVING,
    chunk_holding,
    git,
    indexed_paper,
    run,
)

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


def test_an_index_build_moves_the_links_and_leaves_the_store_alone(corpus: Path):
    """Which chunk carries a selection is derived per build, so the build
    follows the passage without writing the reader's file."""
    before = chunk_holding(corpus, SOLVING)
    run("tag", "calibration", f"id={PAPER_ID}", f"chunk={before}")
    stored = (corpus / ANNOTATIONS).read_text(encoding="utf-8")
    edited(corpus)

    run("corpus", "index")

    after = chunk_holding(corpus, SOLVING)
    assert after != before, "the edit no longer moves the passage"
    (anchor,) = tagged(corpus)["calibration"]
    assert anchor.chunk == after
    assert (corpus / ANNOTATIONS).read_text(encoding="utf-8") == stored
    assert git(corpus, "status", "--porcelain") == ""
    assert ANNOTATIONS not in git(corpus, "show", "--name-only", "--format=", "HEAD")


def test_an_index_build_that_moves_no_passage_leaves_the_file_alone(corpus: Path):
    solving = chunk_holding(corpus, SOLVING)
    run("tag", "calibration", f"id={PAPER_ID}", f"chunk={solving}")

    run("corpus", "index")

    touching = git(corpus, "log", "--format=%s", "--", ANNOTATIONS).splitlines()
    assert [subject.split("(")[0] for subject in touching] == ["tag"]


def test_a_tag_change_rewrites_every_hint_in_its_store(corpus: Path):
    """A hint written wrong by hand stands until the next tag change to the
    corpus, which finds every selection and writes where each is now."""
    solving = chunk_holding(corpus, SOLVING)
    run("tag", "calibration", f"id={PAPER_ID}", f"chunk={solving}")
    store = json.loads((corpus / ANNOTATIONS).read_text(encoding="utf-8"))
    (selection,) = [each["selector"] for each in store["annotations"]]
    right = (selection["start"], selection["end"])
    selection.update(start=0, end=len(selection["exact"]))
    (corpus / ANNOTATIONS).write_text(json.dumps(store), encoding="utf-8")

    run("tag", "to-read", f"id={PAPER_ID}")

    rewritten = json.loads((corpus / ANNOTATIONS).read_text(encoding="utf-8"))
    (selection,) = [
        each["selector"] for each in rewritten["annotations"] if "selector" in each
    ]
    assert (selection["start"], selection["end"]) == right
    (target,) = tagged(corpus)["calibration"]
    assert target.chunk == solving


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
    stored = (project / ANNOTATIONS).read_text(encoding="utf-8")
    (project / "ours.md").write_text(
        _ours(
            "## First\n\nA section inserted ahead of the solving section, long "
            "enough to be a chunk of its own when the chunks are small.\n\n"
        ),
        encoding="utf-8",
    )

    run("context", "index")

    assert (project / ANNOTATIONS).read_text(encoding="utf-8") == stored
    after = solving_in(project)
    assert after != before, "the edit no longer moves the passage"

    run("tag", "other", "path=.context/theirs.md")

    (anchor,) = tagged(project)["mine"]
    assert anchor.chunk == after
