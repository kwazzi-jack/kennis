"""The guard on the skips.

A skip is the only thing in a suite that can remove coverage and leave it
green. An unconditional one disables its tests on *every* platform and
reports it in a line nobody reads, which is strictly worse than the
failure it replaced: a failure is at least loud.

So these assert three things about `tests/platforms.py`: that nothing it
defines skips anything here, that every marker says why, and that the
list the first two iterate is complete. The third is what stops a new
marker being added and checked by nothing - the same hole
`gui/words.py`'s `__all__` test exists for.
"""

from __future__ import annotations

import os

import pytest

import platforms


def _condition(marker: pytest.MarkDecorator) -> object:
    """The `skipif` condition, as it was given."""
    assert marker.mark.args, marker
    return marker.mark.args[0]


def test_nothing_is_skipped_on_this_platform():
    """The one that matters. Every marker here names something Windows
    cannot express, so on a POSIX platform each condition must be false -
    and it fails if a condition is inverted, dropped, or replaced by a
    bare `pytest.mark.skip`, all of which look identical in a green run.

    `os.name` rather than a mock, because what is being asserted is that
    these markers do not fire *where this suite is running*."""
    if os.name == "nt":
        pytest.skip("this assertion is about the platforms that are not Windows")

    for marker in platforms.MARKERS:
        assert marker.mark.name == "skipif", marker
        assert _condition(marker) is False, marker


def test_every_marker_says_why():
    """A skip with no reason is a test that disappeared. pytest prints the
    reason with `-rs` and in the summary, and it is the only trace left of
    what stopped being covered."""
    for marker in platforms.MARKERS:
        reason = marker.mark.kwargs.get("reason")
        assert isinstance(reason, str) and reason.strip(), marker
        # Long enough to be a sentence rather than a word. "windows" alone
        # says what, never why, and why is the part a reader needs.
        assert len(reason.split()) >= 8, reason


def test_every_marker_the_module_defines_is_checked():
    """`MARKERS` is what the two tests above iterate, so a marker left out
    of it is one nothing guards. Discovered from the module rather than
    listed, for the same reason the newline scan is (concern #384)."""
    defined = {
        name: value
        for name, value in vars(platforms).items()
        if isinstance(value, pytest.MarkDecorator) and not name.startswith("_")
    }

    assert defined, vars(platforms).keys()
    for name, marker in defined.items():
        assert marker in platforms.MARKERS, f"{name} is in no MARKERS entry"
    assert len(platforms.MARKERS) == len(defined), (
        sorted(defined),
        len(platforms.MARKERS),
    )


def test_every_marker_is_exported():
    """`__all__` is what a reader and a linter see. A marker missing from
    it reads as private and gets copied instead of imported."""
    for name, value in vars(platforms).items():
        if isinstance(value, pytest.MarkDecorator) and not name.startswith("_"):
            assert name in platforms.__all__, name
