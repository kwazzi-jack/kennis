"""A path a person types into kennis may arrive in quotes (#4).

A shell removes the quotes from an argument; a prompt or a field does not.
Windows Explorer's "Copy as path" wraps a path in double quotes, and a
Linux terminal pastes a dropped file in single ones.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kennis.engine.typed import without_quotes
from kennis.gui.adding import listing_of
from kennis.gui.routes.add import _lines

WINDOWS_PATH = r"C:\Users\User\Downloads\LHW Mortality Book Review.pdf"


@pytest.mark.parametrize(
    ("typed", "meant"),
    [
        (f'"{WINDOWS_PATH}"', WINDOWS_PATH),
        ("'/home/someone/a paper.pdf' ", "/home/someone/a paper.pdf"),
        ('  "~/papers/x.pdf"  ', "~/papers/x.pdf"),
        (WINDOWS_PATH, WINDOWS_PATH),
    ],
)
def test_one_pair_of_quotes_around_the_whole_answer_is_removed(typed: str, meant: str):
    assert without_quotes(typed) == meant


@pytest.mark.parametrize(
    "typed",
    [
        '"unmatched.pdf',
        "'mixed.pdf\"",
        '"',
        'a "quoted" word.pdf',
        "'it''s.pdf",
    ],
)
def test_a_quote_that_does_not_wrap_the_answer_is_kept(typed: str):
    """A name may hold a quote; only a pair around the whole is the
    clipboard's."""
    assert without_quotes(typed) == typed.strip()


def test_nothing_else_is_unescaped():
    """A backslash is a Windows separator, never an escape."""
    assert without_quotes(r'"C:\new\table.pdf"') == r"C:\new\table.pdf"


def test_the_add_dialog_reads_each_line_without_its_quotes():
    typed = f"\"{WINDOWS_PATH}\"\n\n  '10.1000/xyz'  \n"

    assert _lines(typed) == [WINDOWS_PATH, "10.1000/xyz"]


def test_the_chooser_opens_a_folder_typed_in_quotes(tmp_path: Path):
    folder = tmp_path / "a folder"
    folder.mkdir()
    (folder / "paper.pdf").write_bytes(b"%PDF-1.4\n")

    quoted = listing_of(f'"{folder}"', target="pdf", folders=False)
    plain = listing_of(str(folder), target="pdf", folders=False)

    assert quoted == plain
