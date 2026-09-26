"""Rule 4.4: a command kennis prints must run as printed.

Concern #233 noticed that nothing checked this, and #265 recorded three
violations inside one milestone - a command named before it existed, a
resolution inherited from a parent that runs and does not help, and a
backticked `corpus sync` that has no implementation. The guard is static
over `src/kennis/`, not over what a test run happens to print, because the
string that goes wrong is the one on the path nobody exercises.

What is checked is that the command **resolves**: the subcommand path is
real and every option named is one that command accepts. Argument values
are not checked - `kennis corpus claim <id>` is a correct thing to print,
and the placeholder is the reader's to fill.

**Two ways a string is read, because prose and commands are not the same
thing.** At a site whose contract is that the string *is* a command - a
`resolution=`, a `default_resolution`, `display.next_step`, `display.hint`
- the whole string is the invocation. Anywhere else only a **backticked**
span counts, because backticks are how this codebase says "this is code"
and a bare sentence beginning with the program name is usually prose:
`KennisError.default_message` is "kennis could not complete the
operation", which is not a command and must not be read as one.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import click
import pytest

from kennis.cli.__main__ import main

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = PROJECT_ROOT / "src" / "kennis"

PROGRAM = "kennis"


@dataclass(frozen=True, slots=True)
class Invocation:
    """One `kennis ...` string found in the source, and where it was."""

    tokens: tuple[str, ...]
    path: Path
    line: int

    def __str__(self) -> str:
        printed = " ".join([PROGRAM, *self.tokens])
        relative = self.path.relative_to(PROJECT_ROOT)
        return f"{relative}:{self.line}: {printed}"


def _literal_prefix(node: ast.expr) -> str | None:
    """The part of a string node that is fixed at author time.

    A plain constant is all of it. An f-string contributes its literal
    pieces up to the first placeholder: `f"kennis pack validate {path}"`
    gives `kennis pack validate `, which is the whole of what rule 4.4 is
    about. Nothing after a placeholder is included, because a token split
    across an interpolation is not a token this test can judge.
    """
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if not isinstance(node, ast.JoinedStr):
        return None
    pieces: list[str] = []
    for part in node.values:
        if isinstance(part, ast.Constant) and isinstance(part.value, str):
            pieces.append(part.value)
            continue
        break
    return "".join(pieces) if pieces else None


# Call sites and attribute names whose contract is that the string they
# carry *is* a command. Nothing else is read whole; see the module
# docstring.
WHOLE_STRING_CALLS = frozenset({"next_step", "hint"})
WHOLE_STRING_KEYWORDS = frozenset({"resolution"})
WHOLE_STRING_ATTRIBUTES = frozenset({"default_resolution"})


def _backticked(text: str) -> list[str]:
    """Every backticked span in one string that begins with the program
    name. Odd indices of a split on the backtick are the spans between a
    pair of them."""
    pieces = text.split("`")
    spans: list[str] = []
    for index in range(1, len(pieces), 2):
        span = pieces[index].strip()
        if span == PROGRAM or span.startswith(f"{PROGRAM} "):
            spans.append(span)
    return spans


def _whole(text: str) -> list[str]:
    stripped = text.strip()
    if stripped == PROGRAM or stripped.startswith(f"{PROGRAM} "):
        return [stripped]
    return []


def _tokens(invocation: str) -> tuple[str, ...]:
    """The invocation's words, without the program name.

    Split on whitespace rather than with `shlex`, because a literal prefix
    can end mid-quote - `f'kennis read "{title}'` - and `shlex` raises on
    that rather than giving back what is there.
    """
    return tuple(invocation.split()[1:])


def _whole_string_nodes(tree: ast.Module) -> set[int]:
    """The `id()` of every string node a designated site carries.

    Collected by walking the calls and assignments rather than by matching
    on the string's own shape, so that a command written as plain prose at
    one of these sites is still checked.
    """
    marked: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else None
            if isinstance(node.func, ast.Name):
                name = node.func.id
            if name in WHOLE_STRING_CALLS:
                for argument in node.args:
                    marked.add(id(argument))
            for keyword in node.keywords:
                if keyword.arg in WHOLE_STRING_KEYWORDS:
                    marked.add(id(keyword.value))
        elif isinstance(node, ast.AnnAssign | ast.Assign):
            targets = (
                [node.target] if isinstance(node, ast.AnnAssign) else list(node.targets)
            )
            named = any(
                isinstance(target, ast.Name) and target.id in WHOLE_STRING_ATTRIBUTES
                for target in targets
            )
            if named and node.value is not None:
                marked.add(id(node.value))
    return marked


def _invocations() -> list[Invocation]:
    found: list[Invocation] = []
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        whole = _whole_string_nodes(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant | ast.JoinedStr):
                continue
            text = _literal_prefix(node)
            if text is None or PROGRAM not in text:
                continue
            candidates = _backticked(text)
            if id(node) in whole:
                candidates += _whole(text)
            for candidate in candidates:
                found.append(
                    Invocation(tokens=_tokens(candidate), path=path, line=node.lineno)
                )
    return found


# Click adds the help option from the context rather than from `params`,
# so it is not discoverable by walking a command's own parameters. Every
# command has it, under both spellings this project configures.
_ALWAYS_ALLOWED = frozenset({"--help", "-h"})


def _option_names(command: click.Command) -> set[str]:
    names = set(_ALWAYS_ALLOWED)
    for parameter in command.params:
        if isinstance(parameter, click.Option):
            names.update(parameter.opts)
            names.update(parameter.secondary_opts)
    return names


def _resolution_failure(invocation: Invocation) -> str | None:
    """Why this invocation would not run, or None when it would.

    Walks the real command tree rather than a list of names written down
    here: a list would be a second place to update, and the failure this
    guards against is precisely the two places disagreeing.
    """
    current: click.Command = main
    consumed: list[str] = []
    remaining = list(invocation.tokens)

    while remaining:
        token = remaining[0]
        if token.startswith("-"):
            break
        if not isinstance(current, click.Group):
            break
        child = current.get_command(click.Context(current), token)
        if child is None:
            named = " ".join([PROGRAM, *consumed]) if consumed else PROGRAM
            return f"'{token}' is not a command of '{named}'"
        current = child
        consumed.append(token)
        remaining.pop(0)

    allowed = _option_names(current)
    for token in remaining:
        if not token.startswith("-"):
            # An argument. Its value is the reader's to supply, and a
            # placeholder such as `<id>` is the correct thing to print.
            continue
        name = token.split("=", 1)[0]
        if name not in allowed:
            named = " ".join([PROGRAM, *consumed]) if consumed else PROGRAM
            return f"'{name}' is not an option of '{named}'"
    return None


INVOCATIONS = _invocations()


def test_the_source_prints_commands_to_check():
    """A collector that silently found nothing would pass this whole module
    and prove none of it. #66: an injection, or a scan, must assert that it
    applied."""
    assert len(INVOCATIONS) >= 20


@pytest.mark.parametrize(
    "invocation", INVOCATIONS, ids=[str(one) for one in INVOCATIONS]
)
def test_a_printed_command_resolves(invocation: Invocation):
    failure = _resolution_failure(invocation)
    assert failure is None, f"{invocation}: {failure}"
