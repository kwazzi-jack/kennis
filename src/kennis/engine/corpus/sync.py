"""`corpus sync`: converging the corpus with every installed pack.

Design section 5, steps 4, 4a and 6, against the second destination. The
table is `engine/pack/resolve.py` and is not repeated here; what differs
is the two functions either side of it.

**A corpus document is not addressed by where it lives.** Its filename
comes from its title and its identity is a minted surrogate identifier
that every read handle depends on, so the address a pack declared has to
be recorded *in* the document - `source.from: pack:<id>/<address>`. A
sync that could not find the document it wrote last time would write a
second one on every run, and re-minting the identifier would break every
handle pointing at the first.

**Two digests, for the same reason the bundle needs two.** `sha256` is
the body kennis wrote, which a user edit moves; `pack_sha256` is the
store file it came from, which a provider release moves. A pack file
carrying its own frontmatter has that header read and replaced, so the
two are different bytes and one value cannot answer both questions.

**This module writes and does not commit.** The corpus is kennis's own
repository and every mutation is committed by its command, once per
invocation - so the caller holding the lock decides what history records.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from kennis.engine.corpus.add import Uniqueness, write_note
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.document import Document, write_document
from kennis.engine.corpus.intake import Converted
from kennis.engine.corpus.schema import NoteFrontmatter, Source
from kennis.engine.errors import DocumentInvalid
from kennis.engine.events import EventSink, ItemFinished, OperationFinished, Outcome
from kennis.engine.frontmatter import split_frontmatter
from kennis.engine.pack.content import content_digest
from kennis.engine.pack.installed import (
    declared_content,
    list_installed,
    refuse_damaged_packs,
)
from kennis.engine.pack.resolve import Action, Declaration, Existing, Verdict, resolve
from kennis.engine.remember import title_for

OPERATION = "corpus-sync"

# The `source.from` scheme that says a pack supplied this document. The
# rest of the value is `<pack id>/<address>`, which is what makes the
# document findable again by the address rather than by its path.
ORIGIN_SCHEME = "pack:"

_OUTCOMES: dict[Verdict, Outcome] = {
    "write": Outcome.ADDED,
    "rewrite": Outcome.CHANGED,
    "adopt": Outcome.CHANGED,
    "delete": Outcome.REMOVED,
    "keep": Outcome.UNCHANGED,
    "edited": Outcome.SKIPPED,
    "yours": Outcome.SKIPPED,
}


@dataclass(frozen=True, slots=True)
class CorpusSync:
    """What one `corpus sync` did, by verdict.

    `edited` carries the surrogate identifier of each document kennis
    declined to rewrite, which the bundle's equivalent has no use for: a
    corpus document is addressed by that identifier and `corpus claim`
    is the only handle on it, so the report cannot name the command to
    run without it. Section 5 step 4a names that command for exactly
    this case.
    """

    actions: tuple[Action, ...]
    counts: dict[Verdict, int]
    deferred: tuple[tuple[str, str], ...]
    edited: tuple[str, ...]


def sync_corpus(corpus_root: Path, *, events: EventSink | None = None) -> CorpusSync:
    """Converge the notes collection with every installed pack.

    Raises `PackInvalid` while any installed pack is damaged, before
    anything is written. Literature and documentation are declarations a
    fetch resolves rather than content a copy materialises, and neither is
    handled here yet.
    """
    started = time.monotonic()
    packs = list_installed(corpus_root).packs
    refuse_damaged_packs(packs)
    union = declared_content(corpus_root, packs, "notes")

    collection = Collection(root=corpus_root, name="notes")
    held = _held(collection)
    actions = resolve(union.declarations, {one: held[one][0] for one in held})

    record = Uniqueness.of(collection)
    for action in actions:
        _applied(collection, record, action, held)
    counts = Counter(action.verdict for action in actions)
    _reported(events, actions, started)
    return CorpusSync(
        actions=actions,
        counts=dict(counts),
        deferred=union.deferred,
        edited=tuple(
            held[action.address][1].id
            for action in actions
            if action.verdict == "edited"
        ),
    )


def _held(collection: Collection) -> dict[str, tuple[Existing, Document]]:
    """Every note a pack supplied, keyed by the address it was declared at.

    Read from `source.from` rather than from the path, because the path
    follows the title. A document the user wrote is not here at all: it
    sits at no pack's address, so it is not a sync's business - not even
    to report.
    """
    found: dict[str, tuple[Existing, Document]] = {}
    for document in collection.contents().documents:
        source = document.frontmatter.source
        if source.via != "pack" or not source.origin.startswith(ORIGIN_SCHEME):
            continue
        address = source.origin[len(ORIGIN_SCHEME) :].split("/", 1)[-1]
        found[address] = (
            Existing(
                address=address,
                owner=document.frontmatter.owner,
                body_digest=content_digest(document.body.encode("utf-8")),
                written_digest=source.sha256,
                pack_digest=source.pack_sha256,
            ),
            document,
        )
    return found


def _applied(
    collection: Collection,
    record: Uniqueness,
    action: Action,
    held: dict[str, tuple[Existing, Document]],
) -> None:
    """Carry out one action. `keep`, `yours` and `edited` write nothing."""
    if action.verdict == "delete":
        collection.remove(held[action.address][1])
        return
    if action.verdict not in {"write", "rewrite", "adopt"}:
        return
    declaration = action.declaration
    assert declaration is not None
    title, body = _content_of(declaration)
    if action.verdict == "write":
        _written(collection, record, declaration, title=title, body=body)
        return
    _rewritten(held[action.address][1], declaration, title=title, body=body)


def _content_of(declaration: Declaration) -> tuple[str, str]:
    """The title and body for one declared note.

    A pack ships plain markdown. When its file carries its own
    frontmatter that block supplies the title and the rest is the body -
    never nested, never two blocks in one document. Otherwise the title
    comes from the prose the way `remember` derives one, so a pack note
    and a remembered one are named by the same rule.
    """
    content = declaration.store_path.read_text(encoding="utf-8")
    shipped, body = split_frontmatter(content)
    declared_title = shipped.get("title")
    title = str(declared_title) if declared_title else title_for(body)
    return title, body


def _written(
    collection: Collection,
    record: Uniqueness,
    declaration: Declaration,
    *,
    title: str,
    body: str,
) -> None:
    """A note this corpus has not held before, with a minted identifier.

    **Deliberately not deduplicated against the user's notes.** A pack
    shipping prose somebody already remembered is a different document
    with a different owner, and folding the two together would hand a
    user's note to a pack - or leave the pack's declaration pointing at a
    document the pack does not own. `remember`'s deduplication exists to
    stop an agent saying the same thing twice; two sources saying it once
    each is not that.
    """
    write_note(
        collection,
        record,
        converted=Converted(
            markdown=body,
            via="pack",
            format="markdown",
            origin=f"{ORIGIN_SCHEME}{declaration.pack_id}/{declaration.address}",
            sha256=content_digest(body.encode("utf-8")),
        ),
        title=title,
        group=None,
        owner=f"pack:{declaration.pack_id}",
        pack_sha256=declaration.digest,
    )


def _rewritten(
    document: Document, declaration: Declaration, *, title: str, body: str
) -> None:
    """A note this corpus already holds, kept at its own identifier.

    The file is rewritten where it stands. Its filename came from the
    title it had when it was first written and is left alone even when
    the title moves: renaming is `corpus move`'s job, it is not what a
    sync was asked to do, and the filename is not the identity.
    """
    frontmatter = NoteFrontmatter(
        id=document.id,
        title=title,
        owner=f"pack:{declaration.pack_id}",
        source=Source(
            origin=f"{ORIGIN_SCHEME}{declaration.pack_id}/{declaration.address}",
            via="pack",
            format="markdown",
            sha256=content_digest(body.encode("utf-8")),
            pack_sha256=declaration.digest,
        ),
        id_from=document.frontmatter.id_from,
    )
    write_document(document.md_path, frontmatter=frontmatter, body=body)


def claim_document(corpus_root: Path, handle: str) -> Document:
    """Move a document from its pack to the user. Design section 6.

    **`source` is left alone**, which is what keeps the document at its
    address: the next sync still finds it, sees `owner: user`, and
    reports it under `yours:` rather than rewriting it. A claim that
    erased the origin would make the next sync write a second copy of the
    same note.

    Claiming a document the user already owns is harmless and does
    nothing, because the end state is what was asked for.
    """
    collection = Collection(root=corpus_root, name="notes")
    document = collection.resolve(handle)
    if document.frontmatter.owner == "user":
        return document
    return _reowned(document, "user")


def disown_document(corpus_root: Path, handle: str) -> Document:
    """Hand a document back to the pack it came from. Design section 6.

    Only a document that came from one: the pack is read back out of
    `source.from`, and there is nothing to read for a note the user
    wrote. Inventing a pack would be a claim about provenance that is not
    true, and the next sync would then delete the document, because no
    pack declares it.
    """
    collection = Collection(root=corpus_root, name="notes")
    document = collection.resolve(handle)
    source = document.frontmatter.source
    if source.via != "pack" or not source.origin.startswith(ORIGIN_SCHEME):
        raise DocumentInvalid(
            f"'{handle}' did not come from a pack, so there is none to hand it back to",
            resolution="kennis corpus list",
        )
    pack_id = source.origin[len(ORIGIN_SCHEME) :].split("/", 1)[0]
    return _reowned(document, f"pack:{pack_id}")


def _reowned(document: Document, owner: str) -> Document:
    """Rewrite one document with a new `owner` and nothing else changed."""
    frontmatter = document.frontmatter.model_copy(update={"owner": owner})
    return write_document(document.md_path, frontmatter=frontmatter, body=document.body)


def _reported(
    events: EventSink | None, actions: tuple[Action, ...], started: float
) -> None:
    if events is None:
        return
    counts: Counter[Outcome] = Counter()
    for action in actions:
        outcome = _OUTCOMES[action.verdict]
        counts[outcome] += 1
        events.emit(
            ItemFinished(
                operation=OPERATION,
                item=action.address,
                outcome=outcome,
                reason=action.verdict,
            )
        )
    events.emit(
        OperationFinished(
            operation=OPERATION,
            elapsed_seconds=time.monotonic() - started,
            counts=dict(counts),
        )
    )


__all__ = [
    "OPERATION",
    "ORIGIN_SCHEME",
    "CorpusSync",
    "claim_document",
    "disown_document",
    "sync_corpus",
]
