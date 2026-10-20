"""Writing prose into the corpus or into a project's bundle.

The third module beside `context.py`, and there for the reason the
other two are: taking the corpus lock, calling the engine and
committing is a sequence every front end performs identically, and the
graphical interface may not import the MCP server to get it.

**Two targets, two disciplines.** The corpus write takes the lock and
commits, because the corpus is kennis's own git repository. The bundle
write does neither, because a bundle lives inside a repository kennis
does not own and committing there would take over the user's version
control.

What is *not* here is wording. Each front end says what it says about
a `RememberReport`; this returns the report.
"""

from __future__ import annotations

from pathlib import Path

from kennis.context import Context, resolve_context
from kennis.engine.context.notes import BundleNote, remember_in_bundle
from kennis.engine.errors import ContextNotFound
from kennis.engine.events import EventSink, Outcome
from kennis.engine.history.history import commit_summary
from kennis.engine.history.outofband import OutOfBandChange
from kennis.engine.history.repository import Repository
from kennis.engine.locking import corpus_lock
from kennis.engine.rag.binding import binding_from
from kennis.engine.remember import (
    INLINE_ORIGIN,
    RememberOptions,
    RememberReport,
)
from kennis.engine.remember import remember as remember_in_notes
from kennis.operations import committed_if_interrupted, restore_hand_deletions


def write_note(
    context: Context,
    text: str,
    *,
    title: str | None = None,
    group: str | None = None,
    origin: str = INLINE_ORIGIN,
    index: bool = True,
    events: EventSink | None = None,
    restored: list[OutOfBandChange] | None = None,
) -> RememberReport:
    """Write into notes: lock, restore, write, index, commit.

    The order every mutating command uses, hand deletions included: the
    commit stages with `git add --all .`, so a document deleted by hand
    and not put back first would be recorded as deleted, under
    `remember(notes)`, by whoever wrote a note - an agent included.
    Concern #128. `restored` is filled in place, as `add_documents`
    fills it, for a caller that says what came back. The lock refuses at
    once with `CorpusBusy` when another process holds the corpus, unless
    the caller is inside `waiting_for_the_corpus`, as a service job is.

    `origin`, `index` and `events` exist for the command line, which
    reads text from a file (so the origin is a path), offers
    `--no-index` for a bulk import, and shows a progress bar. The
    other two front ends take the defaults.

    **The commit is skipped when nothing was written**, and not for
    the reason it looks like. `Repository.commit` already returns None
    on a clean tree, so an empty commit was never the risk - that
    claim was in this docstring and was false.

    What the guard actually prevents: `commit` stages with `git add
    --all .`, so it records whatever is in the working tree. A
    repeated note writes nothing, and committing anyway would sweep
    any unrelated change sitting in the corpus - a file someone
    dropped in, a half-finished edit - into a commit labelled
    `remember(notes)`, attributing it to something the user did not
    do.
    """
    binding = binding_from(context.settings.chunking, context.settings.embedding)
    with corpus_lock(context.corpus_root):
        put_back = restore_hand_deletions(context)
        if restored is not None:
            restored.extend(put_back)
        with committed_if_interrupted(context, "remember", scope="notes"):
            report = remember_in_notes(
                context.corpus_root,
                text,
                binding=binding,
                options=RememberOptions(title=title, group=group),
                origin=origin,
                index=index,
                embed_batch_size=context.settings.embedding.batch_size,
                repository=Repository(context.corpus_root),
                events=events,
            )
        if report.outcome is not Outcome.UNCHANGED:
            Repository(context.corpus_root).commit(
                "remember",
                scope="notes",
                summary=commit_summary({"documents": 1}),
            )
    return report


def write_context_note(
    text: str,
    *,
    title: str | None = None,
    group: str | None = None,
    bundle: Path | None,
) -> tuple[BundleNote, str]:
    """Write into this project's bundle, and say which bundle.

    No lock and no commit. The bundle sits in a repository kennis does
    not own; writing a file there is the request, and committing it is
    taking over the user's version control.

    Raises `ContextNotFound` when there is no bundle here, rather than
    falling back to notes: a caller recording something about *this
    project* and told it succeeded, when it went somewhere
    machine-global, has been told something false.

    `bundle` is the one the client found where its person works, or None
    outside a project (#508).
    """
    resolve_context()
    if bundle is None:
        raise ContextNotFound
    return remember_in_bundle(bundle, text, title=title, group=group), bundle.name


__all__ = ["write_context_note", "write_note"]
