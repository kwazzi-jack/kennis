"""Splitting a document into retrievable spans.

Chunking is block-aware: a markdown parse locates atomic block boundaries -
tables, fenced code, display math, lists, headings - and the packer never
bisects one. Only prose is split. Every chunk keeps character offsets back
into the original text, because a result has to be able to say where it was
found.
"""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

from kennis.engine.rag.chunking import ChunkParameters, chunk_document
from kennis.engine.rag.models import Document


def a_document(text: str, *, base_path: str | None = None) -> Document:
    return Document(
        id="doc1",
        text=text,
        source_path="/corpus/notes/A Note.md",
        base_path=base_path,
    )


def chunks_of(text: str, **overrides: int) -> list[str]:
    parameters = ChunkParameters(**overrides) if overrides else ChunkParameters()
    return [
        chunk.text
        for chunk in chunk_document(
            a_document(text), collection="notes", parameters=parameters
        )
    ]


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_a_chunk_knows_where_it_came_from():
    chunks = chunk_document(
        a_document("# Title\n\nSome prose.\n"),
        collection="notes",
        parameters=ChunkParameters(),
    )

    chunk = chunks[0]
    assert chunk.collection == "notes"
    assert chunk.document_id == "doc1"
    assert chunk.id == "doc1::0"
    assert chunk.source_path == "/corpus/notes/A Note.md"


def test_the_offsets_index_back_into_the_original_text():
    """The offsets are the whole provenance claim: a result says where it was
    found, and that is only true if the span really is the text there."""
    text = "# Title\n\nSome prose here.\n\n## Second\n\nMore prose.\n"

    for chunk in chunk_document(
        a_document(text), collection="notes", parameters=ChunkParameters()
    ):
        assert text[chunk.char_start : chunk.char_end] == chunk.text


def test_chunks_are_numbered_in_order():
    text = "# A\n\n" + ("word " * 400) + "\n\n# B\n\n" + ("other " * 400)
    chunks = chunk_document(
        a_document(text), collection="notes", parameters=ChunkParameters()
    )

    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert len(chunks) > 1


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def test_the_nearest_preceding_heading_labels_the_chunk():
    text = "# Overview\n\nFirst part.\n\n## Details\n\nSecond part.\n"
    chunks = chunk_document(
        a_document(text), collection="notes", parameters=ChunkParameters()
    )

    labelled = {chunk.section for chunk in chunks}
    assert labelled == {"Overview", "Details"}


def test_text_before_any_heading_has_no_section():
    text = "Preamble with no heading.\n\n# Later\n\nBody.\n"
    chunks = chunk_document(
        a_document(text), collection="notes", parameters=ChunkParameters()
    )

    assert chunks[0].section is None


def test_a_comment_inside_a_code_fence_is_not_a_heading():
    """kennis fences an ingested source file with its language, so a corpus of
    notes made from code is full of lines that look like ATX headings to a
    regex. Treating one as a heading both mislabels the chunk and splits the
    fence the packer is written never to bisect."""
    text = (
        "# Real heading\n\n"
        "Prose.\n\n"
        "```python\n"
        "# Load the measurement set\n"
        "ms = open_ms(path)\n"
        "# Apply the gains\n"
        "apply(ms)\n"
        "```\n\n"
        "## Second real heading\n\n"
        "More prose.\n"
    )
    chunks = chunk_document(
        a_document(text), collection="notes", parameters=ChunkParameters()
    )

    assert {chunk.section for chunk in chunks} == {
        "Real heading",
        "Second real heading",
    }
    fenced = [chunk for chunk in chunks if "ms = open_ms(path)" in chunk.text]
    assert len(fenced) == 1
    assert "# Apply the gains" in fenced[0].text


# ---------------------------------------------------------------------------
# What must never be split
# ---------------------------------------------------------------------------


def test_an_oversized_table_is_kept_whole():
    """One over-long chunk beats a bisected table: half a table is not
    something a reader or a retriever can use."""
    rows = "\n".join(f"| row {index} | value {index} |" for index in range(120))
    text = f"# Data\n\n| a | b |\n| --- | --- |\n{rows}\n"

    chunks = chunks_of(text, size=200, overlap=20)
    holding = [chunk for chunk in chunks if "row 0" in chunk]
    assert len(holding) == 1
    assert "row 119" in holding[0]


def test_an_oversized_code_fence_is_kept_whole():
    body = "\n".join(f"call_number_{index}()" for index in range(120))
    text = f"# Code\n\n```python\n{body}\n```\n"

    holding = [
        chunk
        for chunk in chunks_of(text, size=200, overlap=20)
        if "call_number_0()" in chunk
    ]
    assert len(holding) == 1
    assert "call_number_119()" in holding[0]


def test_an_oversized_display_equation_is_kept_whole():
    equation = " + ".join(f"a_{{{index}}} x_{{{index}}}" for index in range(80))
    text = f"# Maths\n\nThe model is\n\n$$\n{equation}\n$$\n"

    holding = [
        chunk for chunk in chunks_of(text, size=200, overlap=20) if "a_{0}" in chunk
    ]
    assert len(holding) == 1
    assert "a_{79}" in holding[0]


def test_oversized_prose_is_the_one_thing_that_is_split():
    text = "# Prose\n\n" + ("word " * 500)
    assert len(chunks_of(text, size=200, overlap=20)) > 1


# ---------------------------------------------------------------------------
# The sliding window
# ---------------------------------------------------------------------------


def test_a_window_does_not_cut_a_word_in_half():
    text = "# Prose\n\n" + " ".join(f"token{index}" for index in range(300))

    for chunk in chunks_of(text, size=200, overlap=20):
        stripped = chunk.strip()
        if stripped.startswith("token") and not stripped.startswith("token0 "):
            assert " " in stripped


def test_windows_overlap_so_a_phrase_across_a_boundary_survives():
    text = "# Prose\n\n" + " ".join(f"token{index}" for index in range(300))
    chunks = chunks_of(text, size=200, overlap=80)

    assert any(
        set(first.split()) & set(second.split()) for first, second in pairwise(chunks)
    )


def test_a_document_of_nothing_but_whitespace_produces_no_chunk():
    assert chunks_of("   \n\n \t \n") == []


def test_a_heading_with_no_body_is_still_a_chunk():
    """A heading is content. `# Calibration` with nothing under it is worth
    retrieving, and dropping it would lose the only text in that section."""
    assert chunks_of("# A\n\n   \n\n# B\n\n   \n") == ["# A\n", "# B\n"]


def test_an_empty_document_produces_no_chunks():
    assert chunks_of("") == []


# ---------------------------------------------------------------------------
# Line offsets
# ---------------------------------------------------------------------------


def test_a_form_feed_does_not_desynchronise_the_offsets():
    """A form feed is what a PDF-to-markdown page break leaves behind. Python
    breaks lines on it and markdown-it does not, so counting lines with
    `splitlines` would misplace every block boundary after the first one."""
    text = "# Title\n\nBefore the break.\n\n\x0c\n\n## After\n\nAfter the break.\n"

    for chunk in chunk_document(
        a_document(text), collection="notes", parameters=ChunkParameters()
    ):
        assert text[chunk.char_start : chunk.char_end] == chunk.text
    assert any(
        chunk.section == "After"
        for chunk in chunk_document(
            a_document(text), collection="notes", parameters=ChunkParameters()
        )
    )


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------


def test_an_image_reference_that_resolves_is_recorded(tmp_path: Path):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "figure1.png").write_bytes(b"png")
    text = "# Figures\n\nSee ![a figure](figure1.png) here.\n"

    chunks = chunk_document(
        a_document(text, base_path=str(tmp_path)),
        collection="notes",
        parameters=ChunkParameters(),
    )

    assert chunks[0].metadata["images"] == [str(tmp_path / "images" / "figure1.png")]


def test_an_image_reference_with_no_file_is_not_recorded(tmp_path: Path):
    text = "# Figures\n\nSee ![a figure](missing.png) here.\n"

    chunks = chunk_document(
        a_document(text, base_path=str(tmp_path)),
        collection="notes",
        parameters=ChunkParameters(),
    )

    assert chunks[0].metadata["images"] == []


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------


def test_the_chunker_version_is_part_of_the_parameters():
    """Identical size and overlap run through a changed packing algorithm
    produce different chunks, so a cache keyed on the numbers alone would
    serve vectors for text that no longer exists."""
    assert ChunkParameters(size=1500, overlap=200, version=1) != ChunkParameters(
        size=1500, overlap=200, version=2
    )


def test_a_smaller_chunk_size_produces_more_chunks():
    text = "# Prose\n\n" + ("word " * 600)

    assert len(chunks_of(text, size=200, overlap=20)) > len(
        chunks_of(text, size=1500, overlap=200)
    )
