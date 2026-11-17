"""An agent tags a quotation, not only a chunk (#50, unit 4, sketch
2026-11-17-tag-a-quotation).

The words must be found exactly once - in the chunk named, or in the whole
document when none is - or the request is refused at its position and,
the batch being all or nothing, nothing is written.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from annotating import ANNOTATIONS
from kennis.engine.annotations import Annotation, read_annotations
from kennis.engine.context.bundle import init_bundle
from kennis.mcp.tools.tags import TagRequest, tag
from test_cli_tags import PAPER_ID, chunk_holding, indexed_paper, run


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return indexed_paper(tmp_path, monkeypatch)


def stored(root: Path) -> list[Annotation]:
    return list(read_annotations(root / ANNOTATIONS).annotations)


def test_a_quote_in_its_chunk_selects_those_words(corpus: Path):
    chunk = chunk_holding(corpus, "solved for per antenna")

    said = tag(
        [TagRequest(document_id=PAPER_ID, chunk=chunk, quote="solved for per antenna")],
        ["calibration"],
    )

    (annotation,) = stored(corpus)
    assert annotation.selector is not None
    assert annotation.selector.exact == "solved for per antenna"
    assert annotation.tags == ("calibration",)
    assert said.startswith("[1] Revisiting the radio interferometer")
    assert "tagged: calibration" in said


def test_a_quote_without_a_chunk_is_looked_for_in_the_whole_document(
    corpus: Path,
):
    """Across a line break, given with a space, as a snippet gives it."""
    tag(
        [TagRequest(document_id=PAPER_ID, quote="in a form that carries")],
        ["form"],
    )

    (annotation,) = stored(corpus)
    assert annotation.selector is not None
    assert annotation.selector.exact == "in a\nform that carries"


def test_a_quote_found_more_than_once_is_refused_with_the_count(corpus: Path):
    said = tag([TagRequest(document_id=PAPER_ID, quote="were")], ["x"])

    assert "[1]" in said
    assert "3 times" in said
    assert not (corpus / ANNOTATIONS).exists()


def test_a_quote_not_in_the_document_is_refused(corpus: Path):
    said = tag([TagRequest(document_id=PAPER_ID, quote="no such words here")], ["x"])

    assert "not in" in said
    assert not (corpus / ANNOTATIONS).exists()


def test_a_quote_not_in_the_chunk_named_is_refused_with_the_way_out(
    corpus: Path,
):
    elsewhere = chunk_holding(corpus, "flagged for interference")

    said = tag(
        [
            TagRequest(
                document_id=PAPER_ID, chunk=elsewhere, quote="solved for per antenna"
            )
        ],
        ["x"],
    )

    assert "chunk" in said
    assert not (corpus / ANNOTATIONS).exists()


def test_one_refused_quote_writes_none_of_the_batch(corpus: Path):
    said = tag(
        [
            TagRequest(document_id=PAPER_ID, quote="solved for per antenna"),
            TagRequest(document_id=PAPER_ID, quote="were"),
        ],
        ["x"],
    )

    assert "[2]" in said
    assert "[1]" not in said
    assert not (corpus / ANNOTATIONS).exists()


def test_the_same_quote_again_gains_the_name(corpus: Path):
    asked = [TagRequest(document_id=PAPER_ID, quote="solved for per antenna")]
    tag(asked, ["a"])

    said = tag(asked, ["b"])

    (annotation,) = stored(corpus)
    assert annotation.tags == ("a", "b")
    assert "tagged: b" in said


def test_removing_with_a_quote_takes_the_name_from_that_selection_alone(
    corpus: Path,
):
    chunk = chunk_holding(corpus, "solved for per antenna")
    tag([TagRequest(document_id=PAPER_ID, chunk=chunk)], ["x"])
    tag([TagRequest(document_id=PAPER_ID, quote="solved for per antenna")], ["x"])

    said = tag(
        [TagRequest(document_id=PAPER_ID, quote="solved for per antenna")],
        ["x"],
        remove=True,
    )

    (left,) = stored(corpus)
    assert left.selector is not None
    assert left.selector.exact != "solved for per antenna"
    assert left.tags == ("x",)
    assert "untagged: x" in said


def test_a_projects_file_is_tagged_by_a_quote(
    corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "pipelines"
    (root / ".git").mkdir(parents=True)
    init_bundle(root)
    (root / ".context" / "ours.md").write_text(
        "---\ntitle: ours\n---\nWe solve the gains per scan, then smooth them.\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(root)
    run("context", "index")

    tag([TagRequest(path=".context/ours.md", quote="then smooth them")], ["mine"])

    (annotation,) = stored(root / ".context")
    assert annotation.document == "ours.md"
    assert annotation.selector is not None
    assert annotation.selector.exact == "then smooth them"
    assert not (corpus / ANNOTATIONS).exists()
