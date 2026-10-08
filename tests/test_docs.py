"""The documentation site, checked for the ways it goes wrong quietly.

Every failure here is silent by nature, which is why they are tested rather
than noticed:

- a generated reference drifts from the code it was generated from, and
  reads as authoritative while being wrong;
- a page renders as literal text instead of markdown, which is valid HTML,
  so a `--strict` build says nothing about it. That happened to the home
  page's card grid and was caught by reading the output, not the build;
- a documented command stops being one the installed version accepts.
  rules.md 4.4 says a printed command runs as printed, and it was enforced
  for a `KennisError`'s resolution and for `remedies_for` while the place
  kennis prints the most commands - and a reader is most likely to copy one
  - went unchecked. 157 of them, across fifteen pages;
- a page is written and never reaches the navigation, which is the same as
  not having written it.

Concerns #219 and #327.
"""

from __future__ import annotations

import importlib.util
import shlex
import shutil
import subprocess
from pathlib import Path
from types import ModuleType

import click
import pytest

from kennis.cli.__main__ import main

ROOT = Path(__file__).resolve().parent.parent
DOCS_ROOT = ROOT / "docs"

# What ends a command and begins something the shell does with it.
# `kennis read x > x.md` is a redirection: the command is the part in
# front, and the rest is the shell's. Matched against whole words after
# `shlex` has run, so a `>` inside a quoted question is safe.
_SHELL_OPERATORS = frozenset({"|", ">", ">>", "&&", ";", "2>"})

# A parse failure that is about the reader's filesystem rather than about
# the command. `--from` is a `click.Path(exists=True)`, so a documented
# example naming a file cannot parse anywhere the reader has not already
# made it. The option name and the shape of the command are still checked;
# only this one message is allowed.
_ABOUT_THE_FILESYSTEM = "does not exist"

# Fence tags whose blocks hold something other than commands to copy.
# `text` is this project's mark for a synopsis - notation describing a
# command rather than one that runs.
_NOT_COPYABLE = frozenset({"text", "yaml", "toml", "json", "markdown"})

# A prompt a reader is meant to ignore, and the runner a contributor uses
# in a checkout. Both are stripped so the command underneath is parsed.
_PREFIXES = ("$ ", "uv run ", "uvx --from kennis ")


def _generator() -> ModuleType:
    """`scripts/` is not a package - the other scripts in it are shell and
    standalone - so the generator is loaded by path rather than imported."""
    path = ROOT / "scripts" / "generate_settings_table.py"
    spec = importlib.util.spec_from_file_location("generate_settings_table", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_settings_table_matches_the_model():
    """`uv run scripts/generate_settings_table.py` regenerates it."""
    generator = _generator()
    committed = (ROOT / generator.PARTIAL).read_text()

    assert committed == generator.render(), (
        "the settings reference has drifted from the model; regenerate it "
        "with `uv run scripts/generate_settings_table.py`"
    )


def navigation() -> list[str]:
    """Every page the nav names, in the order it names them."""
    config = (ROOT / "mkdocs.yml").read_text()
    section = config.split("nav:", 1)[1]
    return [
        part.strip()
        for line in section.splitlines()
        if ": " in line and line.strip().endswith(".md")
        for part in [line.split(": ", 1)[1]]
    ]


def test_every_nav_entry_exists():
    """A nav entry with no file is a warning `--strict` catches, but only
    when someone runs the build. This is cheap enough to run always."""
    referenced = navigation()

    assert referenced, "no nav entries were parsed, so this test proves nothing"
    missing = [page for page in referenced if not (ROOT / "docs" / page).is_file()]

    assert not missing


def test_every_page_is_reachable_from_the_navigation():
    """The other direction, and the one that let two pages go missing: a
    page not in the nav is a page nobody reaches, which is the same as not
    having written it. `kennis serve` and `kennis gui` were both built and
    neither was documented anywhere a reader could arrive at. Concern
    #327."""
    written = {
        path.relative_to(DOCS_ROOT).as_posix()
        for path in DOCS_ROOT.rglob("*.md")
        # A leading underscore names a fragment another page includes
        # rather than a page of its own.
        if not path.name.startswith("_")
    }

    assert written - set(navigation()) == set()


@pytest.mark.slow
def test_the_site_builds_with_no_warnings():
    """`--strict` turns a broken internal link into a failure. Marked slow
    because it is a subprocess and a full render."""
    if shutil.which("uv") is None:  # pragma: no cover - environment specific
        pytest.skip("uv is not on PATH")
    result = subprocess.run(
        ["uv", "run", "--group", "docs", "mkdocs", "build", "--strict"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        stdin=subprocess.DEVNULL,
    )

    assert result.returncode == 0, result.stderr[-3000:]


@pytest.mark.slow
def test_the_home_page_grid_renders_as_markdown():
    """`md_in_html` is what makes the card grid's contents parse. Without it
    the markdown is passed through as text inside a valid div, and the build
    stays green while the page shows raw brackets."""
    built = ROOT / "site" / "index.html"
    if not built.is_file():  # pragma: no cover - depends on build order
        pytest.skip("the site has not been built")
    page = built.read_text()

    assert 'class="grid cards"' in page
    assert "](getting-started/install.md)" not in page, (
        "the card grid rendered as literal markdown; `md_in_html` is missing"
    )


# ---------------------------------------------------------------------------
# A printed command runs as printed
# ---------------------------------------------------------------------------


def markdown_files() -> list[Path]:
    """Every page a reader could open, including the README."""
    return [*sorted(DOCS_ROOT.rglob("*.md")), ROOT / "README.md"]


def invocations(text: str) -> list[tuple[int, str]]:
    """Every `kennis ...` command in a copyable block, with its line number.

    **Fenced blocks only.** Prose says things like "run `kennis corpus add`"
    without its arguments, and holding an illustrative fragment mid-sentence
    to the same standard as a block a reader will copy would make the rule
    unusable rather than strict.

    **And not a block tagged `text`**, which is this project's mark for a
    synopsis: `kennis corpus add <sources>... --collection
    <literature|docs|notes>` is notation describing a command, not one that
    runs, and the tag says so to the reader as well as to this test.

    A line ending in a backslash continues onto the next, as it does in a
    shell. Without joining them a wrapped command is read as two fragments,
    neither of which parses.
    """
    found: list[tuple[int, str]] = []
    # Two flags rather than one. A closing fence carries no tag, so a single
    # "inside" toggle that also read the tag would treat the close of a
    # `text` block as the opening of a copyable one - and then every
    # paragraph after it as a command. It did, which is how "kennis crawls
    # from that page" came to be parsed as an invocation.
    inside = False
    copyable = False
    continued: list[str] = []
    started = 0
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("```"):
            if inside:
                inside, copyable = False, False
            else:
                inside = True
                copyable = stripped[3:].strip() not in _NOT_COPYABLE
            continued = []
            continue
        if not copyable:
            continue
        command = line.strip()
        if continued:
            continued.append(command.removesuffix("\\").strip())
            if command.endswith("\\"):
                continue
            found.append((started, " ".join(continued)))
            continued = []
            continue
        for prefix in _PREFIXES:
            if command.startswith(prefix):
                command = command[len(prefix) :].strip()
        if not command.startswith("kennis ") and command != "kennis":
            continue
        if command.endswith("\\"):
            continued = [command.removesuffix("\\").strip()]
            started = number
            continue
        found.append((number, command))
    return found


def command_accepts(invocation: str) -> str:
    """Empty if the command line would accept `invocation`, else why not.

    The same parse-don't-run check `tests/test_render.py` and
    `tests/test_refusals.py` use for the two families of remedies. Repeated
    rather than shared for the reason given there: a helper imported between
    test modules is one more thing that can be changed for the wrong file's
    sake.
    """
    try:
        # `comments=True` drops a trailing `# what this does`, which a shell
        # drops too, and does so with quoting respected - so a `#` inside a
        # quoted question survives.
        words = shlex.split(invocation, comments=True)
    except ValueError as unbalanced:
        return f"does not parse as a shell word list: {unbalanced}"
    for position, word in enumerate(words):
        if word in _SHELL_OPERATORS:
            words = words[:position]
            break
    if not words or words[0] != "kennis":
        return f"does not start with kennis: {invocation}"

    node: click.Command = main
    rest = words[1:]
    # Descend only through words that could be a subcommand. `kennis --help`
    # is a real invocation of the group itself, and treating `--help` as a
    # missing subcommand would fail the one line every reader tries first.
    while rest and not rest[0].startswith("-") and isinstance(node, click.Group):
        found = node.commands.get(rest[0])
        if found is None:
            return f"no command '{rest[0]}' in '{node.name}'"
        node, rest = found, rest[1:]

    try:
        with node.make_context(node.name, list(rest), resilient_parsing=False):
            return ""
    except click.exceptions.Exit as done:
        # `--help` and `--version` are eager: they print during parsing and
        # leave by this route rather than returning a context. A zero exit
        # is the command working.
        return "" if done.exit_code == 0 else f"exits {done.exit_code}"
    except click.ClickException as refused:
        message = refused.format_message()
        return "" if _ABOUT_THE_FILESYSTEM in message else message


@pytest.mark.parametrize("page", markdown_files(), ids=lambda path: path.name)
def test_every_command_in_the_documentation_runs_as_printed(page: Path):
    """rules.md 4.4, where it matters most.

    A placeholder is still a real invocation as far as `click` is concerned
    - `<file>` parses as an argument - which is right: the reader replaces
    it and the surrounding options must still be the ones the command takes.
    """
    broken = [
        f"{page.relative_to(ROOT)}:{number}: {invocation}: {why}"
        for number, invocation in invocations(page.read_text(encoding="utf-8"))
        if (why := command_accepts(invocation))
    ]
    assert not broken, "\n".join(broken)


def test_the_scanner_actually_finds_the_commands():
    """The hollowness this file is most exposed to.

    Every command test above checks what the scanner hands it, so a scanner
    that stopped finding any - a changed fence convention, a broken state
    machine, a renamed directory - would leave the file green while checking
    nothing. A hundred is well under what the pages hold and well over what
    a broken scanner returns.
    """
    found = sum(
        len(invocations(page.read_text(encoding="utf-8"))) for page in markdown_files()
    )

    assert found > 100, found
