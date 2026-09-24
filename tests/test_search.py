"""Ranked search over a built index.

Two retrievers over one ordered chunk list, fused by reciprocal rank fusion.
Fusion is over positions rather than scores because the two scales are not
comparable: BM25 is unbounded and corpus-relative, cosine similarity lives in
[-1, 1], and normalising one to the other would mean knowing both
distributions at every build.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from kennis.engine.corpus.add import AddOptions, add_notes
from kennis.engine.corpus.collection import Collection
from kennis.engine.errors import NothingToIndex, SearchUnavailable
from kennis.engine.rag.binding import Binding
from kennis.engine.rag.chunking import ChunkParameters
from kennis.engine.rag.embedding import ModelBinding
from kennis.engine.rag.index import build_index, load_index
from kennis.engine.rag.loaders import CollectionLoader
from kennis.engine.rag.models import Filter
from kennis.engine.rag.search import ChunkRange, read_span, search

DIM = 8


class WordEmbedder:
    """Vectors that a test can predict.

    Each text is placed on an axis chosen by which keyword it contains, so a
    query for that keyword is exactly parallel to it and the cosine ordering
    is known in advance.
    """

    axes = ("calibration", "imaging", "spectroscopy", "pipeline")

    def embed(self, texts: list[str]) -> np.ndarray:
        rows = []
        for text in texts:
            vector = np.zeros(DIM, dtype=np.float32)
            lowered = text.lower()
            for position, word in enumerate(self.axes):
                if word in lowered:
                    vector[position] = 1.0
            if not vector.any():
                vector[len(self.axes)] = 1.0
            rows.append(vector)
        return np.array(rows, dtype=np.float32)


@pytest.fixture
def notes(tmp_path: Path) -> Collection:
    return Collection(root=tmp_path / "corpus", name="notes")


@pytest.fixture
def index_root(tmp_path: Path) -> Path:
    return tmp_path / "index"


def a_binding(*, dense: bool = True) -> Binding:
    return Binding(
        chunking=ChunkParameters(),
        model=ModelBinding(kind="fastembed", model="test", dim=DIM) if dense else None,
    )


def a_note(
    notes: Collection, tmp_path: Path, name: str, body: str, group: str | None = None
) -> None:
    source = tmp_path / "sources" / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(body, encoding="utf-8")
    add_notes(notes, [str(source)], AddOptions(group=group) if group else None)


def built(notes: Collection, index_root: Path, *, dense: bool = True) -> object:
    build_index(
        CollectionLoader(notes),
        index_root=index_root,
        binding=a_binding(dense=dense),
        embedder=WordEmbedder() if dense else None,
    )
    return load_index(index_root, "notes")


def a_corpus(notes: Collection, tmp_path: Path) -> None:
    a_note(
        notes,
        tmp_path,
        "cal.md",
        "# Calibration\n\nSolving for antenna gains.\n",
        "radio",
    )
    a_note(
        notes,
        tmp_path,
        "img.md",
        "# Imaging\n\nDeconvolution of the dirty map.\n",
        "radio",
    )
    a_note(
        notes,
        tmp_path,
        "spec.md",
        "# Spectroscopy\n\nLine profiles and redshift.\n",
        "optical",
    )


# ---------------------------------------------------------------------------
# Finding what was indexed
# ---------------------------------------------------------------------------


def test_a_query_returns_the_document_that_was_indexed(
    notes: Collection, tmp_path: Path, index_root: Path
):
    """The plan's test, stated plainly."""
    a_corpus(notes, tmp_path)
    index = built(notes, index_root)

    hits = search(index, "calibration", embedder=WordEmbedder())

    assert hits
    assert "Calibration" in hits[0].chunk.text


def test_results_come_back_best_first(
    notes: Collection, tmp_path: Path, index_root: Path
):
    a_corpus(notes, tmp_path)
    index = built(notes, index_root)

    scores = [hit.score for hit in search(index, "imaging", embedder=WordEmbedder())]

    assert scores == sorted(scores, reverse=True)


def test_no_more_than_top_k_results_are_returned(
    notes: Collection, tmp_path: Path, index_root: Path
):
    a_corpus(notes, tmp_path)
    index = built(notes, index_root)

    assert len(search(index, "calibration", top_k=2, embedder=WordEmbedder())) <= 2


# ---------------------------------------------------------------------------
# What a result can say about itself
# ---------------------------------------------------------------------------


def test_a_hit_records_which_legs_found_it(
    notes: Collection, tmp_path: Path, index_root: Path
):
    """'Why is this first' is a question a maintainer asks, and a fused score
    alone cannot answer it."""
    a_corpus(notes, tmp_path)
    index = built(notes, index_root)

    hit = search(index, "calibration", embedder=WordEmbedder())[0]

    assert hit.bm25_rank == 1
    assert hit.dense_rank == 1
    assert hit.bm25_score is not None
    assert hit.dense_score is not None


def test_a_leg_that_did_not_run_reports_nothing_rather_than_zero(
    notes: Collection, tmp_path: Path, index_root: Path
):
    """Zero is a score a leg could legitimately give. Absent is not."""
    a_corpus(notes, tmp_path)
    index = built(notes, index_root)

    hit = search(index, "calibration", mode="bm25", embedder=WordEmbedder())[0]

    assert hit.dense_rank is None
    assert hit.dense_score is None
    assert hit.bm25_score is not None


def test_every_hit_of_a_dense_search_carries_its_cosine(
    notes: Collection, tmp_path: Path, index_root: Path
):
    """`dense_score` is the hit's similarity to the query, not "the score it
    happened to have inside the dense candidate window".

    A hybrid hit fused in by the lexical leg alone used to carry None here,
    which made a relevance band say nothing about a hit it could perfectly
    well have measured. Cosine is defined for every chunk; the window is a
    retrieval budget, not a limit on what is known.
    """
    a_corpus(notes, tmp_path)
    index = built(notes, index_root)

    # More notes than the 50-candidate window, all equidistant from the
    # query under WordEmbedder, so the last of them cannot be in the dense
    # window: ties break by position. Only the lexical leg reaches it.
    for number in range(60):
        a_note(notes, tmp_path, f"filler{number}.md", f"# Filler {number}\n\nprose")
    a_note(notes, tmp_path, "rare.md", "# Rare\n\nzzuniquetoken appears here")
    index = built(notes, index_root)

    hits = search(index, "zzuniquetoken", top_k=10, embedder=WordEmbedder())

    found = next(hit for hit in hits if hit.chunk.source_path.endswith("rare.md"))
    assert found.dense_rank is None, "the fixture no longer exercises the case"
    assert found.dense_score is not None
    assert all(hit.dense_score is not None for hit in hits)


# ---------------------------------------------------------------------------
# Fusion
# ---------------------------------------------------------------------------


def test_a_chunk_found_by_both_legs_outranks_one_found_by_either(
    notes: Collection, tmp_path: Path, index_root: Path
):
    """The whole point of fusing: agreement between two different notions of
    relevance counts for more than a strong showing in one."""
    a_note(notes, tmp_path, "both.md", "# Calibration\n\nCalibration of the array.\n")
    a_note(
        notes, tmp_path, "lexical.md", "# Notes\n\nThe word calibration appears here.\n"
    )
    a_note(notes, tmp_path, "dense.md", "# Imaging\n\nUnrelated wording.\n")
    index = built(notes, index_root)

    hits = search(index, "calibration", embedder=WordEmbedder())

    assert "Calibration of the array." in hits[0].chunk.text


def test_a_query_with_no_lexical_overlap_still_returns_dense_results(
    notes: Collection, tmp_path: Path, index_root: Path
):
    """Step 1 drops zero-scored BM25 padding, so a lexically unmatched query
    leaves an empty lexical leg and fusion falls through to dense alone."""
    a_corpus(notes, tmp_path)
    index = built(notes, index_root)

    hits = search(index, "zzzqqq calibration", embedder=WordEmbedder())

    assert hits
    assert all(hit.bm25_rank is not None or hit.dense_rank is not None for hit in hits)


def test_a_single_leg_returns_that_legs_ordering(
    notes: Collection, tmp_path: Path, index_root: Path
):
    a_corpus(notes, tmp_path)
    index = built(notes, index_root)

    fused = [
        hit.chunk.id
        for hit in search(index, "imaging", mode="bm25", embedder=WordEmbedder())
    ]
    direct = [
        index.chunks[position].id
        for position, _ in index.bm25.retrieve("imaging", k=50)
    ]

    assert fused == direct[: len(fused)]


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


def test_a_filter_restricts_the_results(
    notes: Collection, tmp_path: Path, index_root: Path
):
    a_corpus(notes, tmp_path)
    index = built(notes, index_root)

    hits = search(
        index,
        "calibration imaging spectroscopy",
        filters=[Filter(field="group", op="glob", value="optical")],
        embedder=WordEmbedder(),
    )

    assert hits
    assert all(hit.chunk.metadata["group"] == "optical" for hit in hits)


def test_a_filter_matching_nothing_returns_nothing(
    notes: Collection, tmp_path: Path, index_root: Path
):
    a_corpus(notes, tmp_path)
    index = built(notes, index_root)

    assert (
        search(
            index,
            "calibration",
            filters=[Filter(field="group", op="eq", value="nonexistent")],
            embedder=WordEmbedder(),
        )
        == []
    )


def test_a_selective_filter_can_starve_the_result(
    notes: Collection, tmp_path: Path, index_root: Path
):
    """Recorded as a test because it is the surprising consequence of
    filtering after retrieval: matching chunks that rank below the candidate
    window are never seen, so the answer can be empty while the corpus holds
    matches. Nothing false is returned; it is incompleteness, not error."""
    for number in range(80):
        a_note(
            notes,
            tmp_path,
            f"common{number}.md",
            f"# Calibration {number}\n\nCalibration notes number {number}.\n",
            "common",
        )
    a_note(
        notes, tmp_path, "rare.md", "# Rare\n\nAn unrelated topic entirely.\n", "rare"
    )
    index = built(notes, index_root)

    hits = search(
        index,
        "calibration",
        filters=[Filter(field="group", op="eq", value="rare")],
        embedder=WordEmbedder(),
    )

    assert hits == []
    assert any(chunk.metadata["group"] == "rare" for chunk in index.chunks)


# ---------------------------------------------------------------------------
# Modes an index cannot serve
# ---------------------------------------------------------------------------


def test_a_lexical_only_index_can_still_be_searched(
    notes: Collection, tmp_path: Path, index_root: Path
):
    a_corpus(notes, tmp_path)
    index = built(notes, index_root, dense=False)

    hits = search(index, "calibration", mode="bm25")

    assert hits


def test_asking_a_lexical_only_index_for_dense_results_names_the_mode_that_works(
    notes: Collection, tmp_path: Path, index_root: Path
):
    a_corpus(notes, tmp_path)
    index = built(notes, index_root, dense=False)

    with pytest.raises(SearchUnavailable) as raised:
        search(index, "calibration", mode="hybrid")

    assert "bm25" in str(raised.value)


def test_searching_a_collection_with_no_index_says_how_to_build_one(
    index_root: Path,
):
    with pytest.raises(NothingToIndex) as raised:
        load_index(index_root, "notes")

    # The whole command, not a prefix of it: `kennis index` is what this
    # asserted while that was not a command at all (concern #124).
    # The whole invocation, not a prefix: this asserted `kennis index`, which
    # was never a command, and then `kennis corpus index notes`, which is one
    # that refuses a positional argument (concern #124).
    assert any(
        "kennis corpus index --collection notes" in note
        for note in raised.value.__notes__
    )


# ---------------------------------------------------------------------------
# Reading around a hit
# ---------------------------------------------------------------------------


def test_a_span_stitches_chunks_back_into_continuous_text(
    notes: Collection, tmp_path: Path, index_root: Path
):
    a_note(notes, tmp_path, "long.md", "# Long\n\n" + ("word " * 900))
    index = built(notes, index_root)
    document_id = index.chunks[0].document_id

    span = read_span(index, document_id, chunks=ChunkRange(0, 3))

    assert span.text.count("word word") > 0
    assert span.chunk_start == 0


def test_stitching_a_whole_document_gives_back_the_document(
    notes: Collection, tmp_path: Path, index_root: Path
):
    """The property, not an example. Chunks overlap by design and their
    offsets index the original exactly, so a naive concatenation would repeat
    text - appending only what is not yet covered must reconstruct it."""
    body = "# Long\n\n" + " ".join(f"token{number}" for number in range(900))
    a_note(notes, tmp_path, "long.md", body)
    index = built(notes, index_root)
    held = notes.contents().documents[0]

    span = read_span(index, held.id, chunks=ChunkRange())

    assert span.text.strip() == held.body.strip()


def test_a_span_reports_the_sections_it_covers(
    notes: Collection, tmp_path: Path, index_root: Path
):
    a_note(notes, tmp_path, "sections.md", "# One\n\nFirst.\n\n## Two\n\nSecond.\n")
    index = built(notes, index_root)
    held = notes.contents().documents[0]

    span = read_span(index, held.id, chunks=ChunkRange())

    assert span.sections == ["One", "Two"]


def test_a_negative_index_counts_from_the_end_of_the_document(
    notes: Collection, tmp_path: Path, index_root: Path
):
    """Of *this document*, not of the index. The range is resolved against
    the chunks the document has, so the last chunk of a short note is its
    own last chunk and not the last row of a corpus-wide table."""
    a_note(notes, tmp_path, "long.md", "# Long\n\n" + ("word " * 900))
    a_note(notes, tmp_path, "other.md", "# Other\n\nUnrelated.")
    index = built(notes, index_root)
    held = next(
        document
        for document in notes.contents().documents
        if document.md_path.name.startswith("long")
    )
    every = read_span(index, held.id, chunks=ChunkRange())

    last = read_span(index, held.id, chunks=ChunkRange(-1, None))

    assert last.chunk_start == last.chunk_end == every.chunk_end
    assert last.chunk_start > 0, "the fixture no longer has several chunks"


def test_an_open_ended_range_runs_to_the_end(
    notes: Collection, tmp_path: Path, index_root: Path
):
    a_note(notes, tmp_path, "long.md", "# Long\n\n" + ("word " * 900))
    index = built(notes, index_root)
    held = notes.contents().documents[0]
    every = read_span(index, held.id, chunks=ChunkRange())

    tail = read_span(index, held.id, chunks=ChunkRange(1, None))

    assert tail.chunk_start == 1
    assert tail.chunk_end == every.chunk_end


def test_a_range_past_the_end_is_clamped_rather_than_refused(
    notes: Collection, tmp_path: Path, index_root: Path
):
    """`slice.indices` clamps, which is what python does and so what a
    reader who wrote `0:999` expects."""
    a_note(notes, tmp_path, "long.md", "# Long\n\n" + ("word " * 900))
    index = built(notes, index_root)
    held = notes.contents().documents[0]
    every = read_span(index, held.id, chunks=ChunkRange())

    generous = read_span(index, held.id, chunks=ChunkRange(0, 999))

    assert generous.text == every.text


def test_a_range_that_selects_nothing_says_so(
    notes: Collection, tmp_path: Path, index_root: Path
):
    """A legal slice can be empty. Returning empty text would show a reader a
    blank screen and let them conclude the document was empty."""
    a_note(notes, tmp_path, "long.md", "# Long\n\n" + ("word " * 900))
    index = built(notes, index_root)
    held = notes.contents().documents[0]

    with pytest.raises(SearchUnavailable) as raised:
        read_span(index, held.id, chunks=ChunkRange(2, 2))

    assert "select" in str(raised.value)


def test_reading_a_document_that_is_not_in_the_index_is_refused(
    notes: Collection, tmp_path: Path, index_root: Path
):
    a_corpus(notes, tmp_path)
    index = built(notes, index_root)

    with pytest.raises(SearchUnavailable):
        read_span(index, "nosuchdoc1", chunks=ChunkRange(0, 1))


def test_position_within_a_leg_changes_the_fused_score(
    notes: Collection, tmp_path: Path, index_root: Path
):
    """What reciprocal rank fusion actually does, and what an earlier version
    of these tests did not check: a chunk ranked first in a leg must score
    above one ranked fifth in the same leg. Counting appearances rather than
    weighting positions passes every other test in this file.
    """
    for number in range(6):
        a_note(
            notes,
            tmp_path,
            f"note{number}.md",
            f"# Calibration {number}\n\nCalibration text number {number}.\n",
        )
    index = built(notes, index_root)

    hits = search(index, "calibration", mode="bm25", embedder=WordEmbedder())

    assert len(hits) >= 3
    assert hits[0].score > hits[1].score > hits[2].score


def test_the_fused_score_is_the_reciprocal_of_the_rank(
    notes: Collection, tmp_path: Path, index_root: Path
):
    """Stated numerically, so the constant cannot drift unnoticed: a chunk
    found only at rank one scores 1 / (60 + 1)."""
    a_note(notes, tmp_path, "one.md", "# Calibration\n\nCalibration only here.\n")
    index = built(notes, index_root)

    hit = search(index, "calibration", mode="bm25", embedder=WordEmbedder())[0]

    assert hit.score == pytest.approx(1.0 / 61.0)
