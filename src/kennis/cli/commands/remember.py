"""`kennis remember`: the one verb that takes prose rather than identifiers.

`corpus add` is given files and URLs and converts them. This is given what
the user is saying now, so the text arrives by one of three routes - an
argument, `--from`, or standard input - and all three reach the same engine
call. Design section 12.

The order is the one every mutating command uses: take the lock, call the
engine, commit.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from kennis.cli import display
from kennis.cli.context import existing_corpus
from kennis.cli.sink import reporting
from kennis.engine.events import Outcome
from kennis.engine.history.history import commit_summary
from kennis.engine.history.repository import Repository
from kennis.engine.locking import corpus_lock
from kennis.engine.rag.binding import binding_from
from kennis.engine.remember import (
    INLINE_ORIGIN,
    RememberOptions,
    RememberReport,
    remember,
)
from kennis.render.words import index_state


@click.command(name="remember")
@click.argument("text", required=False)
@click.option(
    "--from",
    "from_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Read the text from this file instead of the argument.",
)
@click.option("--title", help="Title for the note, overriding its first line.")
@click.option("--group", help="Subdirectory within the notes collection.")
@click.option(
    "--no-index",
    is_flag=True,
    help="Write the note without rebuilding the notes index.",
)
def remember_command(
    text: str | None,
    from_path: Path | None,
    title: str | None,
    group: str | None,
    no_index: bool,
) -> None:
    """Write something down, into notes, and index it."""
    context = existing_corpus()
    body, origin = _text_and_origin(text, from_path)
    binding = binding_from(context.settings.chunking, context.settings.embedding)

    with corpus_lock(context.corpus_root), reporting() as events:
        report = remember(
            context.corpus_root,
            body,
            binding=binding,
            options=RememberOptions(title=title, group=group),
            origin=origin,
            index=not no_index,
            embed_batch_size=context.settings.embedding.batch_size,
            repository=Repository(context.corpus_root),
            events=events,
        )
        Repository(context.corpus_root).commit(
            "remember",
            scope="notes",
            summary=commit_summary({"documents": 1}),
        )

    _report(report)


def _text_and_origin(text: str | None, from_path: Path | None) -> tuple[str, str]:
    """The prose to remember, and where it came from.

    Two routes given at once is an error rather than a precedence rule: a
    caller that supplied both meant one of them, and guessing which would
    silently discard the other.
    """
    if text is not None and from_path is not None:
        raise display.CliError("pass the text as an argument or with --from, not both.")
    if from_path is not None:
        return from_path.read_text(encoding="utf-8"), f"path:{from_path}"
    if text is not None:
        return text, INLINE_ORIGIN
    # Standard input is the third route, and the one an agent or a shell
    # script uses. A terminal is not a route: waiting for a person to type
    # into a command they gave no text to looks like a hang.
    if sys.stdin.isatty():
        raise display.CliError("there is nothing to remember - no text was given.")
    return sys.stdin.read(), INLINE_ORIGIN


def _report(report: RememberReport) -> None:
    """One operation line, and the step that makes the note findable."""
    if report.outcome is Outcome.UNCHANGED:
        display.operation(
            "Unchanged", f"{report.title} is already remembered", style="unchanged"
        )
        return

    state = index_state(report.index_outcome, report.chunk_count)
    display.operation(
        "Remembered",
        report.title + (f", {state}" if state else ""),
        elapsed=report.elapsed_seconds,
    )
    display.detail("+", str(report.path))
    if report.index_outcome == "unindexed":
        display.next_step("kennis corpus index", note="to make it searchable")


__all__ = ["remember_command"]
