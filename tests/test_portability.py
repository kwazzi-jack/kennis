"""What kennis writes, and where it starts looking, on a platform that is
not this one.

Both subjects here are Windows defects (concern #363) that no test could
have caught, for the same reason in two forms: the suite runs on Linux, and
on Linux both the wrong answer and the right one look identical.

- **A newline kennis writes.** `Path.write_text` and `os.fdopen(..., "w")`
  translate `\\n` to `os.linesep`, which is `\\n` here and `\\r\\n` there. So
  a test that writes a document and reads it back sees LF whatever the code
  does, and the defect only appears where a *digest over the bytes* is
  compared across platforms. What is asserted is therefore the argument,
  and each test says so rather than pretending to measure the bytes.
- **A root a pattern starts from.** `Path(r"C:\\a\\b")` on Linux is one
  filename with backslashes in it, so the Windows case cannot be built from
  a string. `PureWindowsPath` builds it directly, which is what makes
  `split_at_anchor` take a path rather than the text it came from.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from kennis.engine.atomic import replace_file
from kennis.engine.corpus.inputs import split_at_anchor

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src/kennis"

# **Discovered, not listed.** The first version of this named six modules
# under `engine/` and would have kept passing while
# `cli/commands/config.py` wrote a settings file with the platform's
# newline - which is exactly what it was doing. A rule that holds for
# every writer has to be checked against every writer.
SOURCES = sorted(PACKAGE.rglob("*.py"))


# ---------------------------------------------------------------------------
# The newline
# ---------------------------------------------------------------------------


def test_the_atomic_writer_names_the_newline_it_writes():
    """**The argument, not the bytes.** On Linux the default and `"\\n"`
    produce identical files, so a test that writes and reads back passes
    either way. The defect is a corpus document written on Windows landing
    as CRLF, `content_digest` hashing `read_bytes()`, and a pack built here
    failing validation there - reported as the file having been tampered
    with. Concern #384.

    Read from the syntax tree rather than from the text. The first version
    searched `inspect.getsource` for `newline="\\n"` and the function's own
    docstring says that, so removing it from the call changed nothing the
    test could see. Concern #337 for the fourth time, and the fourth
    remedy is the same one: assert against code, never against the file.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(replace_file)))
    opens = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "fdopen"
    ]
    text_mode = [
        call
        for call in opens
        if any(
            isinstance(argument, ast.Constant) and argument.value == "w"
            for argument in call.args
        )
    ]
    assert text_mode, ast.dump(tree)
    for call in text_mode:
        named = {
            keyword.arg: keyword.value
            for keyword in call.keywords
            if keyword.arg is not None
        }
        assert "newline" in named, ast.unparse(call)
        given = named["newline"]
        assert isinstance(given, ast.Constant) and given.value == "\n", ast.unparse(
            call
        )


def test_nothing_writes_text_without_naming_the_newline():
    """`Path.write_text`'s newline argument is optional and its default is
    the platform's, so every call has to pass it or what kennis writes
    depends on where it is running.

    Every module in the package, because the rule is not `engine/`'s: the
    listed version of this test missed `cli/commands/config.py`, which was
    writing a settings file the platform's way."""
    offenders: list[str] = []
    for source in SOURCES:
        lines = source.read_text(encoding="utf-8").splitlines()
        for number, text in enumerate(lines):
            if ".write_text(" not in text:
                continue
            # The call may wrap, so read the statement rather than the line.
            statement = "\n".join(lines[number : number + 5])
            if 'newline="\\n"' not in statement:
                offenders.append(
                    f"{source.relative_to(ROOT)}:{number + 1}\n{statement}"
                )
    assert not offenders, "\n\n".join(offenders)


def test_the_scan_looks_at_the_files_it_claims_to():
    """A `rglob` that matched nothing would make the test above pass for
    every possible defect, which is #66's shape written as a fixture."""
    assert len(SOURCES) > 50, len(SOURCES)
    assert any("write_text(" in path.read_text(encoding="utf-8") for path in SOURCES)


def test_a_written_document_holds_no_carriage_returns(tmp_path: Path):
    """The property itself, which on Linux holds with the defect present.

    It is here so that the CI matrix asserts it where it can fail: this is
    the one test in the pair that means something on Windows, and the one
    above is the one that means something here."""
    target = tmp_path / "note.md"

    replace_file(target, "# Rivers\n\nRivers carry sediment.\n")

    assert b"\r" not in target.read_bytes()


# ---------------------------------------------------------------------------
# The root a pattern starts from
# ---------------------------------------------------------------------------


def test_a_drive_letter_is_an_anchor():
    """The defect. `_expand_pattern` asked `text.startswith("/")`, which is
    true of `/a/b` and false of `C:/a/b`, so every absolute Windows pattern
    was searched for beneath the working directory - `./C:/papers` - and
    refused with "matched no files". Concern #385."""
    anchor, segments = split_at_anchor(PureWindowsPath(r"C:\papers\*.pdf"))

    assert anchor == "C:\\"
    assert segments == ["papers", "*.pdf"]


def test_a_posix_root_is_an_anchor():
    """The case that already worked, asserted so the change cannot fix one
    platform by breaking the other."""
    anchor, segments = split_at_anchor(PurePosixPath("/home/brian/papers/*.pdf"))

    assert anchor == "/"
    assert segments == ["home", "brian", "papers", "*.pdf"]


@pytest.mark.parametrize(
    "relative",
    [PurePosixPath("papers/*.pdf"), PureWindowsPath(r"papers\*.pdf")],
)
def test_a_relative_pattern_has_no_anchor(relative: PurePosixPath | PureWindowsPath):
    """An empty anchor is what tells the caller to start at the working
    directory, and it must be empty rather than "." - the caller builds a
    `Path` from it and `Path("")` is `Path(".")`, which would make the two
    cases indistinguishable to anything downstream."""
    anchor, segments = split_at_anchor(relative)

    assert anchor == ""
    assert segments == ["papers", "*.pdf"]


def test_no_segment_is_empty():
    """The empty segment is what the two fudges in `_expand_pattern` were
    for: splitting `/a/b` on `/` yields a leading `""`, so the caller
    filtered it out of the literal segments and then skipped it again by
    hand when computing the remainder. Stripping the anchor first means
    there is none, and both fudges go."""
    for pattern in (
        PurePosixPath("/a/b/*.pdf"),
        PureWindowsPath(r"C:\a\b\*.pdf"),
        PurePosixPath("a/*.pdf"),
    ):
        _, segments = split_at_anchor(pattern)
        assert all(segments), (pattern, segments)


def test_a_bare_anchor_has_no_segments():
    """`/` and `C:\\` name a directory and no pattern. Nothing calls this
    with one, but returning `[""]` would make the caller build `root / ""`
    and the failure would appear somewhere else entirely."""
    assert split_at_anchor(PurePosixPath("/")) == ("/", [])
    assert split_at_anchor(PureWindowsPath("C:\\")) == ("C:\\", [])
