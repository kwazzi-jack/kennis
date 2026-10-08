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
import hashlib
import inspect
import textwrap
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from kennis.engine.atomic import replace_file
from kennis.engine.corpus.inputs import split_at_anchor
from kennis.engine.corpus.intake import convert_local_file, read_text_file
from kennis.engine.history.git import git as run_git
from kennis.engine.history.repository import initialise_corpus
from kennis.engine.pack.content import content_digest
from kennis.engine.pack.schema import ContentSource
from kennis.render.refusals import quoted_for_posix, quoted_for_windows

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
# What git's output is decoded with
# ---------------------------------------------------------------------------


def _subprocess_runs(function: object) -> list[ast.Call]:
    """Every `<something>.run(...)` call in `function`, as syntax.

    Shared by the two tests below so neither can be satisfied by the prose
    that explains it - concern #387, and #388 for the inverted case."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    found = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "run"
    ]
    assert found, ast.dump(tree)
    return found


def test_git_output_is_decoded_as_utf8():
    """`subprocess.run(text=True)` with no `encoding=` decodes using the
    *locale* encoding: UTF-8 here, the ANSI code page on Windows. Git emits
    paths as UTF-8, so a corpus document with an accent in its name came
    back mojibake there and the status parse disagreed with the filesystem.

    Read from the syntax tree for #387's reason: a docstring explaining the
    argument would satisfy a text search. Concern #388."""
    for call in _subprocess_runs(run_git):
        named = {
            keyword.arg: keyword.value
            for keyword in call.keywords
            if keyword.arg is not None
        }
        assert "encoding" in named, ast.unparse(call)
        given = named["encoding"]
        assert isinstance(given, ast.Constant) and given.value == "utf-8", ast.unparse(
            call
        )


def test_git_does_not_silently_repair_a_path_it_cannot_decode():
    """`errors="replace"` would turn an undecodable byte into `?` and kennis
    would then use that string to address a file. A path that will not
    decode has to raise. Concern #388.

    From the syntax tree, like its neighbour, and for a reason worth
    recording: the first version searched the source for `errors=` and the
    comment *explaining* that there is no `errors=` contains the string. So
    a textual negative is satisfied by prose just as a textual positive is -
    #387 from the other side, and the same remedy answers both."""
    for call in _subprocess_runs(run_git):
        named = [keyword.arg for keyword in call.keywords]
        assert "errors" not in named, ast.unparse(call)


def test_a_name_outside_ascii_survives_the_round_trip(tmp_path: Path):
    """The property, which holds here whatever the codec is - this locale is
    UTF-8 - and is the one that means something on Windows.

    `--porcelain -z` already disables git's octal quoting, and the parser
    already reads records rather than splitting on ` -> `, so the decode was
    all that was left. Concern #388."""
    root = tmp_path / "corpus"
    root.mkdir()
    repository = initialise_corpus(root)
    accented = root / "notes" / "\u00e9t\u00e9.md"
    accented.parent.mkdir(parents=True, exist_ok=True)
    accented.write_text("# Ete\n", encoding="utf-8", newline="\n")

    # `status_names` is what kennis parses. `ls-files` is used by no
    # production path and *does* quote a non-ASCII name as
    # `"\303\251t\303\251.md"`, which is exactly what `-z` avoids.
    changed = [path for _, path in repository.status_names(scope="notes")]

    assert any("\u00e9t\u00e9.md" in path for path in changed), changed
    assert all((root / path).exists() for path in changed), changed


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


# ---------------------------------------------------------------------------
# What git is told about line endings
# ---------------------------------------------------------------------------


def test_the_corpus_tells_git_to_keep_line_endings(tmp_path: Path):
    """v0.7c made kennis write LF. This is the other half: git writes the
    working tree too.

    `core.autocrlf=true` is the Git for Windows default and rewrites LF as
    CRLF on checkout - including the per-path `git checkout` in
    `Repository.restore`, which `operations.py` runs on three of the five
    mutating operations. So a document deleted by hand and put back would
    come back CRLF however carefully kennis wrote it, and its digest would
    stop matching the pack. Concern #386.

    Asserted on the file a real `corpus init` writes, not on the constant,
    because the constant being right is not the property."""
    root = tmp_path / "corpus"
    root.mkdir()
    initialise_corpus(root)

    rules = (root / ".gitattributes").read_text(encoding="utf-8").splitlines()
    declared = [line for line in rules if line and not line.startswith("#")]

    assert "* text=auto eol=lf" in declared, declared
    # And it is first, because a later rule wins and the index's rules have
    # to be able to override it.
    assert declared[0] == "* text=auto eol=lf", declared


def test_the_generated_index_is_not_left_to_content_sniffing(tmp_path: Path):
    """`text=auto` decides text from content, which is reliable but is a
    guess about files kennis knows are binary. The index's own rules come
    after the `*` rule, so they win."""
    root = tmp_path / "corpus"
    root.mkdir()
    initialise_corpus(root)

    rules = (root / ".gitattributes").read_text(encoding="utf-8").splitlines()
    declared = [line for line in rules if line and not line.startswith("#")]

    assert "*.npy binary" in declared, declared
    assert "index/** -diff -text" in declared, declared
    assert declared.index("* text=auto eol=lf") < declared.index("*.npy binary")


# The first Windows run, 2026-10-08. Each of these failed on Linux before its
# fix, because each builds the Windows case explicitly rather than waiting
# for a platform to supply it.


def test_a_digest_does_not_see_line_endings():
    """Git for Windows checks a pack's files out as CRLF by default, so a
    digest of the raw bytes reported a pack built on Linux as tampered
    with. Brian decided on 2026-10-08 that the digest normalises CRLF."""
    assert content_digest(b"# A\r\n\r\nBody.\r\n") == content_digest(b"# A\n\nBody.\n")


def test_a_digest_of_lf_text_is_the_sha256_it_always_was():
    """Every pack built so far is LF, so normalising must not move one
    digest - a hand-written statement of the format, not kennis against
    itself."""
    assert content_digest(b"Body.\n") == hashlib.sha256(b"Body.\n").hexdigest()


def test_a_digest_still_sees_a_change_of_content():
    assert content_digest(b"Body.\r\n") != content_digest(b"Edited.\r\n")


def test_a_crlf_source_is_read_as_lf(tmp_path: Path):
    """#384 said reading needed nothing because universal newlines
    normalise on the way in. `read_text_file` decodes `read_bytes()`,
    so it never did, on any platform."""
    path = tmp_path / "a.md"
    path.write_bytes(b"# A note\r\n\r\nBody.\r\n")

    assert read_text_file(path) == "# A note\n\nBody.\n"


def test_a_lone_carriage_return_is_a_line_ending_too(tmp_path: Path):
    """What universal newlines do, so a file reads the same whichever way
    kennis opens it."""
    path = tmp_path / "a.md"
    path.write_bytes(b"one\rtwo\n")

    assert read_text_file(path) == "one\ntwo\n"


def test_a_crlf_markdown_document_reaches_the_body_as_lf(tmp_path: Path):
    path = tmp_path / "A note.md"
    path.write_bytes(b"# A note\r\n\r\nBody.\r\n")

    assert "\r" not in convert_local_file(path).markdown


@pytest.mark.parametrize(
    "source",
    ["C:\\Windows", "C:notes", "\\etc\\passwd", "..\\outside", "notes\\..\\..\\up"],
    ids=["drive-root", "drive-relative", "rooted", "parent", "parent-inside"],
)
def test_a_windows_shaped_source_is_refused_on_every_platform(source: str):
    """A pack is data written on one platform and installed on another, so
    the host's `Path` is the wrong question: on Linux every one of these is
    a single harmless filename, and on Windows each leaves the pack."""
    with pytest.raises(ValueError):
        ContentSource(source=source)


def test_a_posix_root_is_refused_where_windows_would_call_it_relative():
    """`PureWindowsPath("/etc/passwd")` has no drive and is not absolute,
    which is how this passed the check on Windows. Asked of both flavours
    it is refused everywhere."""
    assert not PureWindowsPath("/etc/passwd").is_absolute()
    with pytest.raises(ValueError):
        ContentSource(source="/etc/passwd")


def test_an_ordinary_nested_source_is_still_accepted():
    assert ContentSource(source="notes/recipes/").source == "notes/recipes/"


def test_a_windows_remedy_is_double_quoted_where_it_has_to_be():
    """cmd.exe does not treat a single quote as quoting, so a POSIX-quoted
    path is not a command that runs as printed there."""
    assert quoted_for_windows(r"C:\Users\a b\paper.md") == r'"C:\Users\a b\paper.md"'


def test_a_windows_remedy_is_bare_where_it_can_be():
    assert quoted_for_windows(r"C:\Users\ab\paper.md") == r"C:\Users\ab\paper.md"


def test_a_posix_remedy_is_shell_quoted():
    assert quoted_for_posix("/tmp/a b/paper.md") == "'/tmp/a b/paper.md'"
