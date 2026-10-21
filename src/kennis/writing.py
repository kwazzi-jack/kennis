"""Writing prose into the corpus or into a project's bundle.

The third module beside `context.py`, and there for the reason the
other two are: restoring, writing in a mirror and publishing is a
sequence every front end performs identically, and the graphical
interface may not import the MCP server to get it.

**Two targets, two disciplines.** The corpus write is published and
committed, because the corpus is kennis's own git repository. The bundle
write does neither, because a bundle lives inside a repository kennis
does not own and committing there would take over the user's version
control.

What is *not* here is wording. Each front end says what it says about
a `RememberReport`; this returns the report.
"""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from pathlib import Path

from kennis.context import Context, resolve_context
from kennis.engine.context.notes import BundleNote, remember_in_bundle
from kennis.engine.errors import ContextNotFound, KennisError
from kennis.engine.events import EventSink, Outcome
from kennis.engine.history.history import commit_summary
from kennis.engine.history.outofband import OutOfBandChange
from kennis.engine.history.repository import Repository
from kennis.engine.rag.binding import binding_from
from kennis.engine.remember import (
    INLINE_ORIGIN,
    RememberOptions,
    RememberReport,
    index_note,
)
from kennis.engine.remember import remember as remember_in_notes
from kennis.engine.staging import discard, make_mirror, publish
from kennis.operations import restore_hand_deletions
from kennis.publishing import exclusively

_logger = logging.getLogger(__name__)


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
    """Write into notes: restore, write in a mirror, publish, index.

    The order every mutating command uses, hand deletions included: the
    commit stages with `git add --all .`, so a document deleted by hand
    and not put back first would be recorded as deleted, under
    `remember(notes)`, by whoever wrote a note - an agent included.
    Concern #128. `restored` is filled in place, as `add_documents`
    fills it, for a caller that says what came back.

    **The note is indexed after it is published** (#525 item 2, Brian,
    2026-10-21), holding only the index's own lock. Built before, a failed
    publish left the index naming a note that was not on disk, and a search
    returned a hit nobody could open. After, a failure between the two
    leaves a held note not yet indexed, which is reported as `unindexed` and
    which `corpus status` and the tree already show.

    `origin`, `index` and `events` exist for the command line, which
    reads text from a file (so the origin is a path), offers
    `--no-index` for a bulk import, and shows a progress bar. The
    other two front ends take the defaults.

    **Nothing is published when nothing was written**: `commit` stages
    with `git add --all .`, so committing a repeated note would sweep any
    unrelated change sitting in the corpus - a file someone dropped in, a
    half-finished edit - into a commit labelled `remember(notes)`.
    `publish` returns None for a mirror that did not change.
    """
    started_at = time.monotonic()
    binding = binding_from(context.settings.chunking, context.settings.embedding)
    root = context.corpus_root
    with exclusively(root):
        put_back = restore_hand_deletions(context)
        mirror = make_mirror(root)
    if restored is not None:
        restored.extend(put_back)
    try:
        try:
            report = mirror.rebased(
                remember_in_notes(
                    mirror.root,
                    text,
                    binding=binding,
                    options=RememberOptions(title=title, group=group),
                    origin=origin,
                    index=False,
                )
            )
        except BaseException as error:
            mirror.rebase_error(error)
            raise
        if report.outcome is not Outcome.UNCHANGED:
            with exclusively(root):
                publish(
                    mirror,
                    operation="remember",
                    scope="notes",
                    summary=commit_summary({"documents": 1}),
                )
    finally:
        discard(mirror)
    if report.outcome is Outcome.UNCHANGED or not index:
        return report
    try:
        outcome, chunks = index_note(
            root,
            document_id=report.document_id,
            binding=binding,
            wanted=True,
            embed_batch_size=context.settings.embedding.batch_size,
            repository=Repository(root),
            events=events,
        )
    except (KennisError, OSError):
        # The note is held and committed; only its index failed, which the
        # next build repairs and `corpus status` reports meanwhile. Not
        # `deferred`, whose words say another build holds the index.
        _logger.exception("the note %s was written but not indexed", report.path)
        outcome, chunks = "unindexed", 0
    return replace(
        report,
        index_outcome=outcome,
        chunk_count=chunks,
        elapsed_seconds=time.monotonic() - started_at,
    )


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
