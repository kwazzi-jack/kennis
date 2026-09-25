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
from kennis.cli.commands.context import require_bundle
from kennis.cli.context import existing_corpus
from kennis.cli.sink import reporting
from kennis.engine.context import remember_in_bundle
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
@click.option("--group", help="Subdirectory within the collection or bundle.")
@click.option(
    "--context",
    "to_context",
    is_flag=True,
    help="Write into this project's .context/ bundle instead of notes.",
)
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
    to_context: bool,
    no_index: bool,
) -> None:
    """Write something down, into notes or this project, and index it.

    **`--context` writes into the workspace, not the corpus.** Notes are
    machine-global; a `.context/` bundle belongs to one project and is
    committed with it. Either way the file is marked `owner: user`, so no
    pack and no sync will ever overwrite it.
    """
    body, origin = _text_and_origin(text, from_path)
    if to_context:
        _remember_in_context(body, title=title, group=group, no_index=no_index)
        return
    context = existing_corpus()
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


def _remember_in_context(
    body: str, *, title: str | None, group: str | None, no_index: bool
) -> None:
    """The bundle path: no corpus, no lock, and no commit.

    The corpus one takes `corpus_lock` and ends in `Repository.commit`.
    Neither applies here. The bundle lives inside a repository kennis does
    not own, so committing to it would take over the user's version control
    - the design says the bundle is committed with the project "if the user
    wants", and the wanting is theirs.
    """
    if no_index:
        # Absent rather than present and ignored, which is the rule #169
        # states: `context index` does not exist yet, so nothing here could
        # honour a flag asking it not to run.
        raise display.CliError(
            "--no-index has nothing to skip for --context; a bundle is not indexed yet."
        )
    bundle = require_bundle()
    note = remember_in_bundle(bundle, body, title=title, group=group)
    if note.outcome is Outcome.UNCHANGED:
        display.operation(
            "Unchanged",
            f"{note.title} is already in this project's context",
            style="unchanged",
        )
        return
    # No `elapsed`: the corpus path's time is dominated by indexing, and
    # there is none here, so every run would report `in 0ms` - a number that
    # answers a question nobody asked of a file write.
    display.operation("Remembered", f"{note.title}, in this project")
    # Prefixed with the bundle's own directory name rather than left bundle-
    # relative, because `decisions/Solver choice.md` does not say which of
    # the two places `remember` writes to it landed in.
    display.detail("+", f"{bundle.name}/{note.relative_path}")


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
