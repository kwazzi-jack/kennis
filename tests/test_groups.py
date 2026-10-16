"""A group is a folder inside its collection, and nothing else.

Found while 11f gave the window a Move form: no writer checked a group.
`corpus add --group ../../outside` wrote beside the corpus, `remember
--group /abs` wrote at an absolute path, and the MCP `remember` tool hands
an agent's `group` to the same code. A pack's `group` was unchecked while
its `source` beside it was checked against exactly this.

Every test here asserts that nothing was written outside, not only that
something was refused: a refusal raised after the write is the defect
with a message attached.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.context import existing_corpus
from kennis.engine.corpus.add import AddOptions
from kennis.engine.errors import InputError, PackInvalid
from kennis.engine.groups import checked_group, group_directory, group_problem
from kennis.engine.pack.schema import load_pack
from kennis.engine.remember import RememberOptions
from kennis.mcp.tools.remember import remember

# Written by hand (#373): each way out, in both path flavours.
LEAVING = [
    "../outside",
    "a/../../outside",
    "/absolute",
    "~/home",
    "C:/drive",
    "C:\\drive",
    "..\\outside",
    "\\\\server\\share",
    ".hidden",
    "a/.hidden/b",
]
STAYING = ["", "botany", "a/b", "a/b/c", "with space", "x.y", "a/x.y/b"]


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    monkeypatch.delenv("KENNIS_CONTEXT_DIR", raising=False)
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    return tmp_path


def markdown_outside(root: Path, inside: Path) -> list[Path]:
    """Every markdown file under `root` that is not under `inside`."""
    return [
        path
        for path in root.rglob("*.md")
        if not path.is_relative_to(inside) and path.name != "source.md"
    ]


# ---------------------------------------------------------------------------
# The rule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("group", LEAVING)
def test_a_group_that_leaves_is_refused(group: str):
    assert group_problem(group) is not None
    with pytest.raises(InputError, match="group"):
        checked_group(group)


@pytest.mark.parametrize("group", STAYING)
def test_a_group_inside_is_kept(group: str):
    assert group_problem(group) is None
    assert checked_group(group) == group


def test_no_group_is_the_top_level(tmp_path: Path):
    assert group_directory(tmp_path, None) == tmp_path
    assert group_directory(tmp_path, "") == tmp_path
    assert group_directory(tmp_path, "a/b") == tmp_path / "a" / "b"


@pytest.mark.parametrize("group", LEAVING)
def test_joining_a_group_that_leaves_is_refused(tmp_path: Path, group: str):
    with pytest.raises(InputError):
        group_directory(tmp_path, group)


def test_the_options_refuse_before_anything_runs():
    """Before a download, a conversion or a lock: at the options."""
    with pytest.raises(InputError):
        AddOptions(group="../outside")
    with pytest.raises(InputError):
        RememberOptions(group="/absolute")


# ---------------------------------------------------------------------------
# Every writer
# ---------------------------------------------------------------------------


def test_corpus_add_writes_nothing_outside(isolated: Path):
    source = isolated / "source.md"
    source.write_text("# Escape\n\nBody.\n", encoding="utf-8")

    added = CliRunner().invoke(
        main, ["corpus", "add", "-n", str(source), "--group", "../../outside"]
    )

    assert added.exit_code != 0
    assert "group" in added.output
    assert markdown_outside(isolated, isolated / "corpus") == []


def test_remember_writes_nothing_outside(isolated: Path):
    elsewhere = isolated / "elsewhere"
    told = CliRunner().invoke(
        main, ["remember", "hello there", "--group", str(elsewhere)]
    )

    assert told.exit_code != 0
    assert not elsewhere.exists()
    assert markdown_outside(isolated, isolated / "corpus") == []


def test_the_mcp_tool_writes_nothing_outside(isolated: Path):
    """The case that matters most: the group is an agent's argument."""
    with pytest.raises(InputError):
        remember("a decision", group="../../outside")

    assert markdown_outside(isolated, isolated / "corpus") == []


def test_a_bundle_note_writes_nothing_outside(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
):
    project = isolated / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    subprocess.run(
        ["git", "init", "-q"], cwd=project, check=True, stdin=subprocess.DEVNULL
    )
    assert CliRunner().invoke(main, ["context", "init"]).exit_code == 0

    told = CliRunner().invoke(
        main, ["remember", "a decision", "--context", "--group", "../../outside"]
    )

    assert told.exit_code != 0
    assert [
        path
        for path in markdown_outside(isolated, project / ".context")
        if not path.is_relative_to(isolated / "corpus")
    ] == []


def test_a_move_writes_nothing_outside(isolated: Path):
    source = isolated / "source.md"
    source.write_text("# Stay\n\nBody.\n", encoding="utf-8")
    assert CliRunner().invoke(main, ["corpus", "add", "-n", str(source)]).exit_code == 0
    notes = existing_corpus().corpus_root / "notes"
    held = next(notes.glob("*.md"))
    handle = held.read_text(encoding="utf-8").split("id: ", 1)[1].split()[0]

    moved = CliRunner().invoke(
        main, ["corpus", "move", handle, "--group", "../../outside"]
    )

    assert moved.exit_code != 0
    assert held.exists()
    assert markdown_outside(isolated, isolated / "corpus") == []


PACK_WITH_GROUP = """
kennis:
  schema_version: 1
pack:
  id: a
  name: n
  version: "1"
corpus:
  notes:
    - source: n/
      group: "{group}"
"""


@pytest.mark.parametrize(
    "group", ["../outside", "/absolute", "..\\\\outside", ".hidden"]
)
def test_a_pack_group_that_leaves_is_refused(group: str):
    """A pack is data from outside; its `source` was checked and its
    `group` beside it was not."""
    with pytest.raises(PackInvalid, match="group"):
        load_pack(PACK_WITH_GROUP.format(group=group))


def test_a_pack_group_inside_is_kept():
    pack = load_pack(PACK_WITH_GROUP.format(group="stimela/cabs"))

    assert pack.corpus.notes[0].group == "stimela/cabs"


PACK_WITH_PROJECT = """
kennis:
  schema_version: 1
pack:
  id: a
  name: n
  version: "1"
corpus:
  docs:
    - project: "{project}"
      base_url: https://example.org/
"""


@pytest.mark.parametrize("project", ["../outside", "/absolute", ".hidden"])
def test_a_pack_docs_project_that_leaves_is_refused(project: str):
    """A project is the directory a page is written to: a group by
    another name, and it reached the same join unchecked."""
    with pytest.raises(PackInvalid, match="project"):
        load_pack(PACK_WITH_PROJECT.format(project=project))


def test_a_docs_project_option_that_leaves_is_refused():
    with pytest.raises(InputError):
        AddOptions(project="../outside")


@pytest.mark.parametrize(
    ("group", "reason"),
    [
        ("../outside", "climbs out of its collection"),
        ("/absolute", "is absolute"),
        ("~/home", "names a home directory"),
        (".hidden", "beginning with a dot"),
    ],
)
def test_a_refusal_says_which_way_out_it_was(group: str, reason: str):
    """`..` begins with a dot as well, so without this the climb would be
    refused for being hidden - true, and not what the reader needs told."""
    problem = group_problem(group)

    assert problem is not None
    assert reason in problem


# A docs project is one folder (Brian, 2026-10-16): every page of a site is
# written directly inside it, and the window offers groups within groups
# everywhere else. Written by hand, in both separators.
NESTED_PROJECTS = ["numpy/indexing", "numpy\\indexing", "a/b/c"]


@pytest.mark.parametrize("project", NESTED_PROJECTS)
def test_a_docs_project_option_with_more_than_one_part_is_refused(project: str):
    with pytest.raises(InputError, match="one folder"):
        AddOptions(project=project)


@pytest.mark.parametrize("project", NESTED_PROJECTS)
def test_a_pack_docs_project_with_more_than_one_part_is_refused(project: str):
    with pytest.raises(PackInvalid, match="one folder"):
        load_pack(PACK_WITH_PROJECT.format(project=project.replace("\\", "\\\\")))


def test_a_group_may_still_hold_groups():
    assert AddOptions(group="radio/calibration").group == "radio/calibration"
    assert AddOptions(project="numpy").project == "numpy"
