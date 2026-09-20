"""One shell-pattern dialect, shared by everything that matches paths.

Two callers want the same semantics for different things: search filters
indexed documents on their group, and `corpus add` expands a pattern into the
files it names. They must agree, or `--group 'quartical/*'` and
`corpus add 'quartical/*'` would select different sets from the same words.

The dialect is the .gitignore reading: `*` and `?` stop at a separator, `**`
crosses them. Plain `fnmatch` cannot express this - its `*` crosses `/` -
which is why the implementation is a regex translation.
"""

from __future__ import annotations

import pytest

from kennis.engine._glob import globstar_regex, looks_like_pattern


@pytest.mark.parametrize("candidate", ["*.md", "a?b", "notes/[abc].md", "**/x"])
def test_a_wildcard_makes_an_argument_a_pattern(candidate: str):
    assert looks_like_pattern(candidate) is True


@pytest.mark.parametrize("candidate", ["notes.md", "a/b/c.py", "", "arxiv:1101.1764"])
def test_everything_else_is_a_literal_path(candidate: str):
    """Telling the two apart is what lets `corpus add` say "you typed a
    pattern that matched nothing" rather than "no such file", which are
    different mistakes with different fixes."""
    assert looks_like_pattern(candidate) is False


@pytest.mark.parametrize(
    ("pattern", "path"),
    [
        ("*.md", "notes.md"),
        ("notes/*.md", "notes/a.md"),
        ("**/gains", "gains"),
        ("**/gains", "a/b/gains"),
        ("**/*.py", "a/b/c.py"),
        ("a?c.md", "abc.md"),
        ("quartical/*", "quartical/install"),
    ],
)
def test_a_pattern_matches_what_it_should(pattern: str, path: str):
    assert globstar_regex(pattern).fullmatch(path) is not None


@pytest.mark.parametrize(
    ("pattern", "path"),
    [
        # A single star stops at a separator; this is the whole reason the
        # translation exists rather than a call to fnmatch.
        ("*.md", "notes/a.md"),
        ("notes/*.md", "notes/deep/a.md"),
        ("a?c.md", "abcc.md"),
        ("quartical/*", "quartical/deep/install"),
    ],
)
def test_a_single_star_does_not_cross_a_separator(pattern: str, path: str):
    assert globstar_regex(pattern).fullmatch(path) is None


def test_a_leading_globstar_is_an_optional_run_of_segments():
    """`**/gains` matching a top-level `gains` is the .gitignore reading, and
    the one anybody typing it expects."""
    pattern = globstar_regex("**/gains")

    assert pattern.fullmatch("gains") is not None
    assert pattern.fullmatch("a/gains") is not None
    assert pattern.fullmatch("a/b/gains") is not None
    assert pattern.fullmatch("gains/x") is None


def test_regex_metacharacters_in_a_pattern_are_literal():
    """A path may contain a `.` or a `+`, and neither is a wildcard here."""
    pattern = globstar_regex("a.b+c.md")

    assert pattern.fullmatch("a.b+c.md") is not None
    assert pattern.fullmatch("axbxc.md") is None
