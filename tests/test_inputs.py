"""Turning what was typed into a concrete list of files.

This module handles only the part that is the same for every collection and
needs neither the network nor the corpus. An arXiv identifier, a DOI or a URL
must pass through it completely untouched, because resolving one means
fetching it and that belongs to the collection's own resolver.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kennis.engine.corpus.inputs import resolve_inputs
from kennis.engine.errors import InputError


def make_file(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Pass-through
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argument",
    [
        "arxiv:1101.1764",
        "1101.1764",
        "10.1088/0004-637X/1",
        "https://numpy.org/doc/quickstart",
        "welman2024",
    ],
)
def test_an_identifier_this_module_cannot_judge_passes_through_untouched(
    argument: str,
):
    """Only the collection's own resolver can say what these are, so they
    arrive there exactly as typed, and fail there with a message that knows
    what was tried."""
    resolved = resolve_inputs([argument])

    assert [item.identifier for item in resolved.items] == [argument]
    assert resolved.items[0].origin == "argument"


def test_an_existing_path_passes_through_as_itself(tmp_path: Path):
    path = make_file(tmp_path / "notes.md")

    resolved = resolve_inputs([str(path)])

    assert [item.identifier for item in resolved.items] == [str(path)]


def test_an_existing_path_wins_over_pattern_interpretation(tmp_path: Path):
    """A filename may legitimately contain `[` or `?`, and if it is really
    there on disk the user cannot have meant it as a pattern."""
    path = make_file(tmp_path / "notes[1].md")

    resolved = resolve_inputs([str(path)])

    assert [item.identifier for item in resolved.items] == [str(path)]
    assert resolved.items[0].origin == "argument"


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------


def test_a_pattern_the_shell_did_not_expand_is_expanded_here(tmp_path: Path):
    """What makes the command behave the same under bash, zsh and fish - they
    disagree about `**` - and on Windows, where the shell never expands
    arguments for a program at all."""
    make_file(tmp_path / "a.md")
    make_file(tmp_path / "b.md")
    make_file(tmp_path / "c.txt")

    resolved = resolve_inputs([f"{tmp_path}/*.md"])

    assert [Path(item.identifier).name for item in resolved.items] == ["a.md", "b.md"]
    assert {item.origin for item in resolved.items} == {"pattern"}


def test_an_expansion_remembers_the_argument_it_came_from(tmp_path: Path):
    """So a report can say which pattern produced a file rather than only
    naming the file."""
    make_file(tmp_path / "a.md")

    resolved = resolve_inputs([f"{tmp_path}/*.md"])

    assert resolved.items[0].from_argument == f"{tmp_path}/*.md"


def test_a_globstar_crosses_directories(tmp_path: Path):
    make_file(tmp_path / "a.md")
    make_file(tmp_path / "deep" / "b.md")

    resolved = resolve_inputs([f"{tmp_path}/**/*.md"])

    assert {Path(item.identifier).name for item in resolved.items} == {"a.md", "b.md"}


def test_a_single_star_stays_at_one_level(tmp_path: Path):
    make_file(tmp_path / "a.md")
    make_file(tmp_path / "deep" / "b.md")

    resolved = resolve_inputs([f"{tmp_path}/*.md"])

    assert {Path(item.identifier).name for item in resolved.items} == {"a.md"}


def test_the_expansion_is_ordered(tmp_path: Path):
    for name in ("c.md", "a.md", "b.md"):
        make_file(tmp_path / name)

    resolved = resolve_inputs([f"{tmp_path}/*.md"])

    assert [Path(item.identifier).name for item in resolved.items] == [
        "a.md",
        "b.md",
        "c.md",
    ]


def test_a_pattern_matching_nothing_is_an_error(tmp_path: Path):
    """Quietly adding nothing is the one outcome that looks like success and
    is not."""
    with pytest.raises(InputError) as raised:
        resolve_inputs([f"{tmp_path}/*.md"])

    assert "*.md" in str(raised.value)
    assert raised.value.resolution


def test_a_relative_pattern_is_anchored_where_it_was_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    make_file(tmp_path / "notes" / "a.md")
    monkeypatch.chdir(tmp_path)

    resolved = resolve_inputs(["notes/*.md"])

    assert [Path(item.identifier).name for item in resolved.items] == ["a.md"]


# ---------------------------------------------------------------------------
# Directories
# ---------------------------------------------------------------------------


def test_a_directory_is_walked(tmp_path: Path):
    make_file(tmp_path / "a.md")
    make_file(tmp_path / "b.py")

    resolved = resolve_inputs([str(tmp_path)])

    assert {Path(item.identifier).name for item in resolved.items} == {"a.md", "b.py"}
    assert {item.origin for item in resolved.items} == {"directory"}


def test_a_walk_mirrors_the_directory_structure_onto_groups(tmp_path: Path):
    """Walking `code/` files `code/gains/x.py` under `gains`, and any `--group`
    supplies the prefix above that."""
    make_file(tmp_path / "top.md")
    make_file(tmp_path / "gains" / "x.py")
    make_file(tmp_path / "gains" / "deep" / "y.py")

    resolved = resolve_inputs([str(tmp_path)])
    groups = {Path(item.identifier).name: item.group for item in resolved.items}

    assert groups == {"top.md": "", "x.py": "gains", "y.py": "gains/deep"}


def test_a_walk_declines_a_file_it_cannot_convert_and_says_so(tmp_path: Path):
    """A walk that silently ignored half a directory would leave the user
    believing the corpus holds something it does not."""
    make_file(tmp_path / "a.md")
    make_file(tmp_path / "binary.so")

    resolved = resolve_inputs([str(tmp_path)])

    assert [Path(item.identifier).name for item in resolved.items] == ["a.md"]
    assert [Path(skip.identifier).name for skip in resolved.skipped] == ["binary.so"]
    assert "unsupported" in resolved.skipped[0].reason


def test_a_walk_declines_a_file_with_no_extension(tmp_path: Path):
    """A Makefile is real text, but so is every extensionless binary, and a
    walk cannot tell them apart by name."""
    make_file(tmp_path / "a.md")
    make_file(tmp_path / "Makefile")

    resolved = resolve_inputs([str(tmp_path)])

    assert [Path(item.identifier).name for item in resolved.items] == ["a.md"]


def test_an_extra_file_type_is_added_to_the_accept_list_not_substituted(
    tmp_path: Path,
):
    """The common need is one more extension, not a replacement for the sixty
    kennis already knows."""
    make_file(tmp_path / "a.md")
    make_file(tmp_path / "b.ipynb")

    resolved = resolve_inputs([str(tmp_path)], extra_file_types=[".ipynb"])

    assert {Path(item.identifier).name for item in resolved.items} == {
        "a.md",
        "b.ipynb",
    }


def test_an_extra_file_type_may_be_given_without_its_dot(tmp_path: Path):
    make_file(tmp_path / "b.ipynb")

    resolved = resolve_inputs([str(tmp_path)], extra_file_types=["ipynb"])

    assert len(resolved.items) == 1


def test_a_walk_does_not_descend_into_a_hidden_directory(tmp_path: Path):
    make_file(tmp_path / "a.md")
    make_file(tmp_path / ".git" / "config.md")

    resolved = resolve_inputs([str(tmp_path)])

    assert [Path(item.identifier).name for item in resolved.items] == ["a.md"]


@pytest.mark.parametrize("pruned", ["__pycache__", "node_modules", "build", "venv"])
def test_a_walk_prunes_the_directories_nobody_means(tmp_path: Path, pruned: str):
    """Not for safety - the accept-list already excludes their contents - but
    because there is no reason to walk a `node_modules` to discard every file
    in it."""
    make_file(tmp_path / "a.md")
    make_file(tmp_path / pruned / "b.md")

    resolved = resolve_inputs([str(tmp_path)])

    assert [Path(item.identifier).name for item in resolved.items] == ["a.md"]


def test_a_walk_skips_a_symlinked_file(tmp_path: Path):
    """A link can point outside the tree the user named, and `corpus add
    code/` should mean what is under `code/`."""
    target = make_file(tmp_path / "outside" / "real.md")
    inside = tmp_path / "inside"
    inside.mkdir()
    make_file(inside / "a.md")
    (inside / "link.md").symlink_to(target)

    resolved = resolve_inputs([str(inside)])

    assert [Path(item.identifier).name for item in resolved.items] == ["a.md"]
    assert resolved.skipped[0].reason == "symlink"


def test_a_walk_skips_a_symlinked_directory(tmp_path: Path):
    make_file(tmp_path / "outside" / "real.md")
    inside = tmp_path / "inside"
    inside.mkdir()
    make_file(inside / "a.md")
    (inside / "vendor").symlink_to(tmp_path / "outside")

    resolved = resolve_inputs([str(inside)])

    assert [Path(item.identifier).name for item in resolved.items] == ["a.md"]


def test_a_directory_holding_nothing_convertible_is_an_error(tmp_path: Path):
    make_file(tmp_path / "binary.so")

    with pytest.raises(InputError) as raised:
        resolve_inputs([str(tmp_path)])

    assert "1 skipped" in str(raised.value)


def test_an_empty_directory_is_an_error(tmp_path: Path):
    (tmp_path / "empty").mkdir()

    with pytest.raises(InputError):
        resolve_inputs([str(tmp_path / "empty")])


# ---------------------------------------------------------------------------
# Several arguments together
# ---------------------------------------------------------------------------


def test_several_arguments_of_different_kinds_resolve_together(tmp_path: Path):
    make_file(tmp_path / "a.md")
    make_file(tmp_path / "walk" / "b.py")

    resolved = resolve_inputs(
        ["arxiv:1101.1764", str(tmp_path / "a.md"), str(tmp_path / "walk")]
    )

    assert [item.origin for item in resolved.items] == [
        "argument",
        "argument",
        "directory",
    ]


def test_no_arguments_resolve_to_nothing():
    resolved = resolve_inputs([])

    assert resolved.items == []
    assert resolved.skipped == []
