"""`remember`: prose the user is telling kennis now, stored and made findable.

Design section 12. Every other write path takes an identifier or a file and
converts it; this one takes the text itself, so there is nothing to convert
and nothing to fetch. What it adds over `add_notes` is therefore not a
conversion but two promises:

*It is marked as remembered.* `source.via: remember` distinguishes a thing
the user said from a document kennis ingested, and `owner: user` means no
pack and no sync will ever overwrite it.

*It indexes its own write*, so the thing just remembered can be searched for
without a second command - but only into a collection that already has an
index. That restriction is about cost rather than correctness: with a
manifest present the vector cache already holds every existing chunk and only
the new ones are embedded, whereas a first build of an unindexed collection
would make one remembered line pay for the whole corpus. Section 15 measures
that at 50s for 1942 chunks.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from kennis.engine.corpus.add import Uniqueness, duplicate_of, write_note
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.intake import Converted, sha256_of, title_from_markdown
from kennis.engine.corpus.layout import index_root
from kennis.engine.errors import InputError
from kennis.engine.events import EventSink, Outcome
from kennis.engine.history.repository import Repository
from kennis.engine.rag.binding import Binding
from kennis.engine.rag.index import build_index, index_id_for, read_manifest
from kennis.engine.rag.loaders import CollectionLoader

# Where the text came from when it was given directly rather than read out of
# a file. The `<prefix>:<value>` shape is what every other `source.from`
# uses; the value is `inline` because there is no path and no URL to name -
# the text was part of the request.
INLINE_ORIGIN = "remember:inline"

# How long a title derived from the first line may be. A note is addressed by
# its identifier, but its filename comes from its title, and a filename the
# width of a paragraph is unreadable in `corpus tree` and awkward in a shell.
_TITLE_LIMIT = 60

# `indexed` - the note is searchable now. `unindexed` - the collection has no
# index yet, so it is not, and building one is a separate deliberate act.
# `skipped` - the caller asked for no indexing.
#
# A value rather than a sentence: the engine names things and does not phrase
# them, so what this means in words lives in `render/`. Invariant #81.
type IndexOutcome = Literal["indexed", "unindexed", "skipped"]


@dataclass(frozen=True, slots=True)
class RememberOptions:
    """Everything one `remember` invocation can vary."""

    title: str | None = None
    group: str | None = None


@dataclass(frozen=True, slots=True)
class RememberReport:
    """What one `remember` invocation did."""

    outcome: Outcome
    document_id: str
    title: str
    path: Path
    index_outcome: IndexOutcome
    # Chunks in the collection's index after the rebuild, not in this note:
    # a per-note count would be the number 1 every time, and what a caller
    # wants to say afterwards is how big the index now is. Zero when nothing
    # was built.
    chunk_count: int
    elapsed_seconds: float


def remember(
    corpus_root: Path,
    text: str,
    *,
    binding: Binding,
    options: RememberOptions | None = None,
    origin: str = INLINE_ORIGIN,
    index: bool = True,
    embed_batch_size: int = 64,
    repository: Repository | None = None,
    events: EventSink | None = None,
) -> RememberReport:
    """Write `text` into the notes collection, and index it if it can.

    `binding` arrives as a value rather than being read from settings here,
    which is concern #87's rule: an engine that consults a global is an
    engine two callers cannot use differently in one process.
    """
    started_at = time.monotonic()
    options = options or RememberOptions()

    body = text.strip()
    if not body:
        raise InputError(
            "there is nothing to remember - no text was given",
            resolution="kennis remember --help",
        )

    collection = Collection(root=corpus_root, name="notes")
    record = Uniqueness.of(collection)
    converted = Converted(
        markdown=body,
        via="remember",
        format="markdown",
        origin=origin,
        # Set deliberately, so saying the same thing twice is recognised as
        # the same thing. An agent repeating itself is the expected case once
        # the MCP server exists, and two identical notes would both be
        # returned by every search that matched either.
        sha256=sha256_of(body.encode("utf-8")),
    )

    existing = duplicate_of(record, converted)
    if existing is not None:
        return RememberReport(
            outcome=Outcome.UNCHANGED,
            document_id=existing,
            title=collection.resolve(existing).frontmatter.title,
            path=collection.resolve(existing).md_path,
            index_outcome="skipped",
            chunk_count=0,
            elapsed_seconds=time.monotonic() - started_at,
        )

    title = options.title or title_for(body)
    document_id, path = write_note(
        collection,
        record,
        converted=converted,
        title=title,
        group=options.group,
    )

    outcome, chunks = _index(
        collection,
        corpus_root,
        binding=binding,
        wanted=index,
        embed_batch_size=embed_batch_size,
        repository=repository,
        events=events,
    )
    return RememberReport(
        outcome=Outcome.ADDED,
        document_id=document_id,
        title=title,
        path=path,
        index_outcome=outcome,
        chunk_count=chunks,
        elapsed_seconds=time.monotonic() - started_at,
    )


def _index(
    collection: Collection,
    corpus_root: Path,
    *,
    binding: Binding,
    wanted: bool,
    embed_batch_size: int,
    repository: Repository | None,
    events: EventSink | None,
) -> tuple[IndexOutcome, int]:
    """Rebuild the collection's index, when there is already one to rebuild."""
    root = index_root(corpus_root)
    if not wanted:
        return "skipped", 0
    manifest = read_manifest(root, collection.name)
    # The binding, not merely the presence of an index. A user who indexed
    # lexically and then set an embedding backend has a manifest, but it is
    # for a different index: building into the new one would download a model
    # and re-embed every existing chunk - 33s plus 50s by section 15's
    # measurements - inside a command that looked like it would cost nothing.
    # Both causes leave the note out of the published index, which is the one
    # thing the reader needs to know, so both report `unindexed`.
    if manifest is None or manifest.index_id != index_id_for(binding):
        return "unindexed", 0
    report = build_index(
        CollectionLoader(collection),
        index_root=root,
        binding=binding,
        events=events,
        embed_batch_size=embed_batch_size,
        repository=repository,
    )
    return "indexed", report.chunk_count


def title_for(body: str) -> str:
    """The note's own title: its heading, or its first line, trimmed.

    Trimmed between words rather than through one, because the result is a
    filename somebody has to recognise. `title_filename` already falls back
    to `untitled.md`, so a first line that cleans away to nothing is a plain
    filename rather than a failure.
    """
    first_line = next(
        (line.strip() for line in body.splitlines() if line.strip()),
        "",
    )
    heading = title_from_markdown(body, first_line)
    if len(heading) > _TITLE_LIMIT:
        heading = heading[:_TITLE_LIMIT].rsplit(" ", 1)[0] or heading[:_TITLE_LIMIT]
    # Remembered prose is a sentence and ends in a full stop, and
    # `title_filename` appends `.md` to whatever it is given - so an
    # unstripped one lands on disk as `... solutions..md`. Only a derived
    # title is trimmed this way; one the caller chose is what it asked for.
    return heading.rstrip(" .,;:")


__all__ = [
    "INLINE_ORIGIN",
    "IndexOutcome",
    "RememberOptions",
    "RememberReport",
    "remember",
    "title_for",
]
