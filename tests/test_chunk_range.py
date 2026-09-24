"""Parsing and resolving `--chunks`.

The syntax is kennis's rather than the terminal's, so both the parse and the
resolution live in the engine: an MCP tool taking `chunks="0:3"` must get the
same answer as the command line, and a second parser is how two front ends
come to disagree about what `-1` means. Concern #205.
"""

from __future__ import annotations

import pytest

from kennis.engine.errors import InputError
from kennis.engine.rag.search import ChunkRange, parse_chunk_range

# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3", ChunkRange(start=3, stop=4)),
        ("0", ChunkRange(start=0, stop=1)),
        ("-1", ChunkRange(start=-1, stop=None)),
        ("0:3", ChunkRange(start=0, stop=3)),
        ("2:", ChunkRange(start=2, stop=None)),
        (":3", ChunkRange(start=None, stop=3)),
        (":", ChunkRange(start=None, stop=None)),
        ("-3:", ChunkRange(start=-3, stop=None)),
        ("0:-1", ChunkRange(start=0, stop=-1)),
        (" 1 : 4 ", ChunkRange(start=1, stop=4)),
    ],
)
def test_a_range_parses_as_python_would_read_it(text: str, expected: ChunkRange):
    assert parse_chunk_range(text) == expected


def test_a_bare_index_selects_exactly_that_chunk():
    """`3` is what a person types and what `[3]` meant in the proposal, so it
    is one chunk and not "from 3 onwards"."""
    assert parse_chunk_range("3") == ChunkRange(start=3, stop=4)


def test_a_bare_final_index_has_no_stop_to_give():
    """`-1` is the last chunk, and its half-open stop would be 0, which
    python reads as "before the beginning" and which selects nothing. None is
    the only spelling of "to the end"."""
    assert parse_chunk_range("-1") == ChunkRange(start=-1, stop=None)


@pytest.mark.parametrize("text", ["0:3:2", "::2", "1:2:1", "1:2:"])
def test_a_step_is_refused(text: str):
    """A stepped selection stitches non-adjacent chunks into one passage:
    holes presented as continuous prose, with `char_start` and `char_end`
    describing a range the text does not fill. Concern #205.

    `1:2:` is here too. Python accepts an empty step, so it is a range in
    python's eyes - but it is written by somebody who is reaching for a step,
    and telling them a passage is contiguous answers what they were about to
    ask."""
    with pytest.raises(InputError) as raised:
        parse_chunk_range(text)

    assert "contiguous" in str(raised.value)


@pytest.mark.parametrize("text", ["", "abc", "1:x", "1-4", "[0:3]", "2..4"])
def test_nonsense_is_refused_with_the_forms_that_work(text: str):
    with pytest.raises(InputError) as raised:
        parse_chunk_range(text)

    assert "0:3" in str(raised.value)


def test_a_bracketed_range_says_to_drop_the_brackets():
    """The syntax that was proposed and rejected. Somebody will try it, and
    the shell will often have eaten it first - so when it does arrive intact,
    the error should name the form that works rather than call it nonsense.
    """
    with pytest.raises(InputError) as raised:
        parse_chunk_range("[0:3]")

    assert "0:3" in str(raised.value)
