"""No chunk is longer than its ceiling, and nothing is lost to splitting (#577).

The chunker kept an atomic block whole however long it was, so a docs page's
code block became a 98,579-character chunk and OpenAI refused the batch it
was in. A block is now kept whole up to twice `chunk_size` and split at its
own boundaries past that: a list between items, anything else between lines.
"""

from __future__ import annotations

from itertools import pairwise

import pytest

from kennis.engine.rag.chunking import ChunkParameters, chunk_document
from kennis.engine.rag.models import Chunk, Document

SIZE = 200
PARAMETERS = ChunkParameters(size=SIZE, overlap=20)
CEILING = PARAMETERS.ceiling


def chunks_of(text: str, parameters: ChunkParameters = PARAMETERS) -> list[Chunk]:
    document = Document(id="doc1", text=text, source_path="/corpus/notes/a.md")
    return chunk_document(document, collection="notes", parameters=parameters)


def texts_of(text: str) -> list[str]:
    return [chunk.text for chunk in chunks_of(text)]


def assert_nothing_lost(text: str, chunks: list[Chunk]) -> None:
    """Every character that is not whitespace lies inside some chunk."""
    covered = [False] * len(text)
    for chunk in chunks:
        assert text[chunk.char_start : chunk.char_end] == chunk.text
        for position in range(chunk.char_start, chunk.char_end):
            covered[position] = True
    missing = [
        position
        for position, character in enumerate(text)
        if not character.isspace() and not covered[position]
    ]
    assert missing == [], text[missing[0] : missing[0] + 40] if missing else ""


def a_table(rows: int) -> str:
    body = "\n".join(f"| row {index} | value {index} |" for index in range(rows))
    return f"| a | b |\n| --- | --- |\n{body}\n"


# ---------------------------------------------------------------------------
# The ceiling
# ---------------------------------------------------------------------------


def test_the_ceiling_is_twice_the_size():
    assert ChunkParameters(size=1500, overlap=200).ceiling == 3000


def test_the_ceiling_leaves_room_for_a_window_s_snap():
    """A prose window may run 80 characters past `size` to end on a space."""
    assert ChunkParameters(size=50, overlap=0).ceiling == 130


def test_the_new_rule_is_a_new_chunker_version():
    """Every index and cached vector is rebuilt over the new boundaries."""
    assert ChunkParameters().version == 3


# ---------------------------------------------------------------------------
# Kept whole up to the ceiling
# ---------------------------------------------------------------------------


def test_a_table_over_the_size_and_under_the_ceiling_is_kept_whole():
    table = a_table(9)
    assert SIZE < len(table) <= CEILING

    holding = [chunk for chunk in texts_of(f"# Data\n\n{table}") if "row 0" in chunk]

    assert len(holding) == 1
    assert "row 8" in holding[0]


# ---------------------------------------------------------------------------
# Split past it, at the block's own boundaries
# ---------------------------------------------------------------------------


def test_a_table_past_the_ceiling_is_split_between_rows():
    table = a_table(120)
    text = f"# Data\n\n{table}"

    chunks = chunks_of(text)

    assert len(chunks) > 1
    assert all(len(chunk.text) <= CEILING for chunk in chunks)
    rows = [line for chunk in chunks for line in chunk.text.splitlines()]
    assert [line for line in rows if line.startswith("| row")] == [
        f"| row {index} | value {index} |" for index in range(120)
    ]
    assert_nothing_lost(text, chunks)


def test_a_fence_past_the_ceiling_is_split_between_lines():
    body = "\n".join(f"call_number_{index}()" for index in range(120))
    text = f"# Code\n\n```python\n{body}\n```\n"

    chunks = chunks_of(text)

    assert len(chunks) > 1
    assert all(len(chunk.text) <= CEILING for chunk in chunks)
    for chunk in chunks:
        for line in chunk.text.strip("\n").splitlines():
            assert line.startswith(("call_number_", "```", "# Code")) or not line
            if line.startswith("call_number_"):
                assert line.endswith("()")
    assert_nothing_lost(text, chunks)


def test_display_maths_past_the_ceiling_is_split_between_lines():
    lines = "\n".join(f"a_{{{index}}} x_{{{index}}} +" for index in range(80))
    text = f"# Maths\n\n$$\n{lines}\n$$\n"

    chunks = chunks_of(text)

    assert len(chunks) > 1
    assert all(len(chunk.text) <= CEILING for chunk in chunks)
    assert_nothing_lost(text, chunks)


def test_a_list_past_the_ceiling_is_split_between_its_items():
    """An item of two lines is never cut between them."""
    items = "\n".join(
        f"- item {index} says\n  something on a second line" for index in range(40)
    )
    text = f"# Changes\n\n{items}\n"

    chunks = chunks_of(text)

    assert len(chunks) > 1
    assert all(len(chunk.text) <= CEILING for chunk in chunks)
    for chunk in chunks:
        assert chunk.text.count("- item") == chunk.text.count(
            "something on a second line"
        )
    assert_nothing_lost(text, chunks)


def test_one_line_past_the_ceiling_is_cut_by_the_window():
    text = "```\n" + "x" * 5000 + "\n```\n"

    chunks = chunks_of(text)

    assert all(len(chunk.text) <= CEILING for chunk in chunks)
    assert_nothing_lost(text, chunks)


def test_a_heading_opens_the_first_piece_of_a_split_table():
    chunks = texts_of(f"# Data\n\n{a_table(120)}")

    assert chunks[0].startswith("# Data\n\n| a | b |")
    assert all(chunk.strip() != "# Data" for chunk in chunks)


def test_the_pieces_of_a_split_block_do_not_overlap():
    chunks = chunks_of(f"# Data\n\n{a_table(120)}")

    for earlier, later in pairwise(chunks):
        assert earlier.char_end <= later.char_start


# ---------------------------------------------------------------------------
# The property, over a document of every kind
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("size", [100, 200, 1500])
def test_no_chunk_passes_the_ceiling_and_nothing_is_lost(size: int):
    parameters = ChunkParameters(size=size, overlap=min(200, size // 4))
    text = (
        "# Everything\n\n"
        + ("prose word " * 900)
        + "\n\n"
        + a_table(400)
        + "\n```python\n"
        + "\n".join(f"line_{index} = {index}" for index in range(600))
        + "\n```\n\n"
        + "\n".join(f"- item {index}\n  continued" for index in range(300))
        + "\n\n$$\n"
        + "\n".join(f"y_{index} = x_{index}" for index in range(300))
        + "\n$$\n\n> "
        + ("quoted " * 900)
        + "\n\n"
        + "y" * 9000
        + "\n"
    )

    chunks = chunks_of(text, parameters)

    assert max(len(chunk.text) for chunk in chunks) <= parameters.ceiling
    assert_nothing_lost(text, chunks)
