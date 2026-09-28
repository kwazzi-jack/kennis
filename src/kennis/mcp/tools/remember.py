"""`remember`: the one tool in this server that changes the machine.

Design section 12. Every other tool answers a question; this writes a
file into a store that outlives the conversation, so the shape of it is
mostly about what an agent must not be able to do by accident.

**No interactive path, so everything unresolved is an argument.** The
plan names a write from an agent as the first thing a decision channel
would want, and says this server implements that channel by refusing.
The command line's other two routes for text - `--from` and standard
input - do not cross: both are ways of getting prose into a *process*,
and a tool call already has it.

**One note per call.** The read tools batch because reading four things
is one intention. Writing four is four intentions, and a batch
multiplies what a single misunderstanding puts into a machine-global
store. Repeating a call is cheap regardless: `remember` deduplicates on
the digest of the text, so an agent saying the same thing twice writes
one note.

**Two engine functions, two disciplines.** The corpus write takes the
lock and commits, because the corpus is kennis's own git repository.
The bundle write does neither, because a bundle lives inside a
repository kennis does not own and committing there would take over the
user's version control.
"""

from __future__ import annotations

from typing import Final

from kennis.context import existing_corpus
from kennis.engine.corpus.layout import relative_to_corpus
from kennis.engine.errors import InputError
from kennis.engine.events import Outcome
from kennis.render.words import index_state, needs_an_index
from kennis.writing import write_context_note, write_note

# The longest note this tool will write. Neither front end had a cap
# before, and the command line does not need one: a person typing prose
# is self-limiting and `--from` is a deliberate act on a file they chose.
# A model emitting a large blob into a machine-global corpus is neither,
# and git then keeps it forever. The number is a judgement rather than a
# measurement - roughly a long section of prose, with room to spare - and
# it refuses rather than truncating, because half a remembered decision
# is worse than none.
_MAX_CHARACTERS: Final = 10_000


def remember(
    text: str,
    title: str | None = None,
    group: str | None = None,
    to_context: bool = False,
) -> str:
    """Write something down so it is still here in a later session.

    **This is durable and it is not a scratchpad.** A note goes into the
    user's corpus, is committed to its history, and will come back in
    searches months from now. Use it for what the user has decided,
    corrected or asked you to keep - not for working state, not for a
    summary of what you just did, and not without their say-so.

    `to_context=True` writes into this project's `.context/` bundle
    instead: for a convention or a decision that belongs to this
    repository rather than to the user everywhere. It fails when there
    is no bundle here rather than falling back to notes, because
    recording a project decision somewhere machine-global and reporting
    success would be worse than not recording it.

    `title` overrides the first line, and `group` puts the note in a
    subdirectory. The answer carries the `document_id` a `read_*` tool
    takes.
    """
    body = text.strip()
    if not body:
        raise InputError(
            "there is nothing to remember - no text was given",
            resolution="kennis remember --help",
        )
    if len(body) > _MAX_CHARACTERS:
        raise InputError(
            f"that is {len(body)} characters and the limit is {_MAX_CHARACTERS}; "
            "remember the decision rather than the document it came from",
            resolution="kennis remember --from <file>",
        )
    if to_context:
        return _into_bundle(body, title=title, group=group)
    return _into_notes(body, title=title, group=group)


def _into_notes(body: str, *, title: str | None, group: str | None) -> str:
    """The corpus path, and what to say about what it did.

    The sequence - lock, write, index, commit - is
    `kennis.writing.write_note`, shared with the graphical front end
    because it is identical in both and neither owns it. What is left
    here is the wording, which is this front end's.
    """
    report = write_note(body, title=title, group=group)
    where = relative_to_corpus(report.path, existing_corpus().corpus_root)
    if report.outcome is Outcome.UNCHANGED:
        return f"already remembered: {report.title}  ({report.document_id})  {where}"
    # `unindexed` needs a command rather than a clause: the note is
    # written, it is not findable, and nothing the caller can pass to
    # this tool changes that. The state word is dropped in that case
    # rather than printed as well - "[not indexed]" on one line and
    # "it is not searchable yet" on the next is one fact twice.
    if needs_an_index(report.index_outcome):
        # Two reasons, one remedy, and the distinction is worth the
        # extra clause: "there is no index" is a thing the user has
        # never done, and "one is being rebuilt" is a thing that will
        # have finished by the time they read this.
        why = (
            "the notes collection has no index"
            if report.index_outcome == "unindexed"
            else "another process was rebuilding the index"
        )
        return (
            f"remembered: {report.title}  ({report.document_id})  {where}\n"
            f"It is not searchable yet - {why}. "
            "Ask the user to run `kennis corpus index`."
        )
    state = index_state(report.index_outcome, report.chunk_count)
    return f"remembered: {report.title}  ({report.document_id})  {where}" + (
        f"  [{state}]" if state else ""
    )


def _into_bundle(body: str, *, title: str | None, group: str | None) -> str:
    """The bundle path: no corpus, no lock, no commit.

    `kennis.writing.write_context_note` raises `ContextNotFound` when
    there is no bundle here rather than falling back to notes.
    """
    note, bundle_name = write_context_note(body, title=title, group=group)
    verb = (
        "already in this project" if note.outcome is Outcome.UNCHANGED else "remembered"
    )
    # Prefixed with the bundle's own directory name rather than left
    # bundle-relative, because `decisions/Solver choice.md` does not say
    # which of the two places `remember` writes to it landed in.
    return f"{verb}: {note.title}  {bundle_name}/{note.relative_path}"


__all__ = ["remember"]
