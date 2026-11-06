"""Tagging documents and passages, and listing what is tagged (#625).

What `kennis tag`, `kennis untag`, `kennis tags` and the MCP tool `tag`
answer. A passage is named as for `cite` - a `CiteRequest`, which
`client/passages.py` makes from a link or a `path=` - and resolved the same
way: a corpus handle through `finding.resolve_document`, a bundle path by
membership (`citing.bundle_member`). Beside `citing.py` for that reason.

**A batch is all or nothing.** Every request is resolved before any store is
written; one refusal writes nothing, and each refusal is said at its own
position, so a person or an agent fixes them all at once rather than one per
run.

**Tagging needs the chunk's words; untagging does not.** A tag on a passage
quotes it, so its chunk must be in the current index. An untag must work as
`kennis tags` prints it for a detached passage, whose chunk may be gone and
whose document may be removed, so it matches what is stored: the chunk it
was tagged at, or where it is placed now.

The corpus's store is written under the corpus's exclusive hold and
committed (`operations.place_corpus_tags`); a project's is written and left
for the person to commit, as every bundle write is.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from kennis.citing import CiteRequest, bundle_member
from kennis.context import Context
from kennis.engine.errors import DocumentNotFound, KennisError, SearchUnavailable
from kennis.engine.rag.models import Chunk
from kennis.engine.tags import (
    TAGS_FILENAME,
    Anchor,
    Detached,
    Placed,
    Tags,
    Unchecked,
    placed,
    quote_of,
    read_tags,
    tag_name,
    with_tags,
    without_tags,
    written,
)
from kennis.links import context_link, link_to

# A target's state, as `TaggedTarget.state` carries it.
PLACED: Final = "placed"
DETACHED: Final = "detached"
UNCHECKED: Final = "unchecked"
MISSING: Final = "missing"

# Every tag write in this process, held from reading the stores to writing
# them: the window writes on its request's thread and the command line and
# agents through the `tags` lane, and two read-modify-writes of one file
# interleaved would lose one of them.
_WRITING: Final = threading.Lock()

# How a target in one store is linked: the corpus by identifier, a
# project by its name and the path.
type _Linker = Callable[[str, int | None], str]


@dataclass(frozen=True, slots=True)
class TagChange:
    """One passage or document, and which of the names changed on it."""

    position: int
    handle: str
    title: str | None
    link: str
    changed: tuple[str, ...]
    unchanged: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TagRefusal:
    """A request that could not be tagged, and why."""

    position: int
    handle: str
    message: str
    resolution: str | None


@dataclass(frozen=True, slots=True)
class Tagged:
    """A batch's outcome: every change, or the refusals and nothing written."""

    changes: list[TagChange]
    refused: list[TagRefusal]


@dataclass(frozen=True, slots=True)
class TaggedTarget:
    """One target of a tag as it stands now.

    `project` is None for the corpus. `chunk` is where the passage is
    placed, or the chunk it was tagged at when it is not placed; `link`
    names that chunk. `state` is `placed`, `detached` (its words are gone),
    `unchecked` (no index holds the document) or `missing` (the document
    is not held).
    """

    project: str | None
    # The corpus collection holding it, for the window's way in; None for a
    # project's file or a document no longer held.
    collection: str | None
    document: str
    title: str | None
    chunk: int | None
    quote: str | None
    state: str
    link: str


@dataclass(frozen=True, slots=True)
class TagListing:
    """One tag and its targets, the corpus's first."""

    name: str
    targets: list[TaggedTarget]


# ---------------------------------------------------------------------------
# Changing


@dataclass(frozen=True, slots=True)
class _Named:
    """A request resolved: its store, the anchor, and how it is shown."""

    store: Path
    anchor: Anchor
    title: str | None
    link: str
    # The index's chunks of the document, for an untag to match where a
    # stored passage is placed now; empty when there is none to read.
    chunks: tuple[Chunk, ...]


def change_tags(
    context: Context,
    requests: Sequence[CiteRequest],
    names: Sequence[str],
    *,
    remove: bool,
) -> Tagged:
    """Tag, or untag, every request with every name, or refuse the batch."""
    with _WRITING:
        return _changed_tags(context, requests, names, remove=remove)


def _changed_tags(
    context: Context,
    requests: Sequence[CiteRequest],
    names: Sequence[str],
    *,
    remove: bool,
) -> Tagged:
    from kennis.operations import place_corpus_tags

    folded = tuple(dict.fromkeys(tag_name(name) for name in names))
    if not folded:
        raise KennisError("no tag was named", resolution="kennis tag --help")
    held: dict[Path, Tags] = {}
    named: list[_Named] = []
    refused: list[TagRefusal] = []
    for position, request in enumerate(requests):
        try:
            one = _named(context, request, held, remove=remove)
        except KennisError as error:
            refused.append(
                TagRefusal(position, request.handle, str(error), error.resolution)
            )
            continue
        named.append(one)
    if refused:
        return Tagged(changes=[], refused=refused)

    before = {store: dict(tags) for store, tags in held.items()}
    changes: list[TagChange] = []
    for position, (request, one) in enumerate(zip(requests, named, strict=True)):
        tags = held[one.store]
        changed: list[str] = []
        unchanged: list[str] = []
        for name in folded:
            stored = _stored_as(tags.get(name, ()), one, remove=remove)
            if remove:
                if stored is None:
                    unchanged.append(name)
                    continue
                tags = without_tags(tags, (name,), stored)
            else:
                if stored is not None:
                    unchanged.append(name)
                    continue
                tags = with_tags(tags, (name,), one.anchor)
            changed.append(name)
        held[one.store] = tags
        changes.append(
            TagChange(
                position=position,
                handle=request.handle,
                title=one.title,
                link=one.link,
                changed=tuple(changed),
                unchanged=tuple(unchanged),
            )
        )

    corpus_store = _corpus_store(context)
    for store, tags in held.items():
        if tags == before[store]:
            continue
        text = written(tags)
        if store == corpus_store:
            place_corpus_tags(
                context,
                text,
                counts=_counts(changes, named, store, remove=remove),
            )
        else:
            _place_bundle_tags(store, text)
    return Tagged(changes=changes, refused=[])


def _stored_as(
    anchors: Sequence[Anchor], one: _Named, *, remove: bool
) -> Anchor | None:
    """The stored target `one` names, if any.

    Tagging asks for the same document and chunk. Untagging also accepts
    the chunk a stored passage is placed at now, because that is the chunk
    `kennis tags` prints for it.
    """
    for anchor in anchors:
        if anchor.names_the_same(one.anchor):
            return anchor
        if (
            remove
            and anchor.document == one.anchor.document
            and anchor.chunk is not None
            and one.anchor.chunk is not None
            and placed(anchor, one.chunks) == Placed(one.anchor.chunk)
        ):
            return anchor
    return None


def _counts(
    changes: Sequence[TagChange],
    named: Sequence[_Named],
    store: Path,
    *,
    remove: bool,
) -> dict[str, int]:
    total = sum(
        len(change.changed)
        for change, one in zip(changes, named, strict=True)
        if one.store == store
    )
    return {"untagged" if remove else "tagged": total}


def _place_bundle_tags(store: Path, text: str) -> None:
    from kennis.engine.atomic import remove_file, replace_file

    if text:
        replace_file(store, text)
    else:
        remove_file(store, missing_ok=True)


def _corpus_store(context: Context) -> Path:
    return context.corpus_root / TAGS_FILENAME


def _named(
    context: Context,
    request: CiteRequest,
    held: dict[Path, Tags],
    *,
    remove: bool,
) -> _Named:
    if request.bundle is not None:
        return _named_in_bundle(request, request.bundle, held, remove=remove)
    from kennis.engine.corpus.layout import index_root
    from kennis.engine.rag.index import load_index
    from kennis.finding import resolve_document

    store = _corpus_store(context)
    tags = _held(store, held)
    try:
        where, document = resolve_document(context, request.handle, None)
    except DocumentNotFound:
        # A document removed since it was tagged can still be untagged by
        # the identifier `kennis tags` printed for it.
        if remove and _names_a_stored_document(tags, request.handle):
            anchor = Anchor(request.handle, request.chunk)
            return _Named(
                store, anchor, None, link_to(request.handle, request.chunk), ()
            )
        raise
    title = _text(document.frontmatter.title)
    link = link_to(document.id, request.chunk)
    if request.chunk is None:
        return _Named(store, Anchor(document.id), title, link, ())
    try:
        chunks = tuple(
            chunk
            for chunk in load_index(index_root(context.corpus_root), where.name).chunks
            if chunk.document_id == document.id
        )
    except KennisError:
        if not remove:
            raise
        chunks = ()
    return _Named(
        store,
        _passage_anchor(
            document.id,
            request.chunk,
            chunks,
            remove=remove,
            unindexed=f"'{request.handle}' has no chunk {request.chunk} in the "
            f"'{where.name}' index",
            resolution="kennis corpus index",
        ),
        title,
        link,
        chunks,
    )


def _named_in_bundle(
    request: CiteRequest, bundle: Path, held: dict[Path, Tags], *, remove: bool
) -> _Named:
    from kennis.engine.context.index import load_bundle_index

    store = bundle / TAGS_FILENAME
    tags = _held(store, held)
    try:
        project, file = bundle_member(bundle, request.handle)
    except DocumentNotFound:
        if remove and _names_a_stored_document(tags, request.handle):
            from kennis.engine.context.projects import project_names

            project = project_names([bundle])[bundle]
            link = context_link(project, request.handle, request.chunk)
            anchor = Anchor(request.handle, request.chunk)
            return _Named(store, anchor, None, link, ())
        raise
    title = bundle_title(file)
    link = context_link(project, request.handle, request.chunk)
    if request.chunk is None:
        return _Named(store, Anchor(request.handle), title, link, ())
    try:
        chunks = tuple(
            chunk
            for chunk in load_bundle_index(bundle).chunks
            if chunk.document_id == request.handle
        )
    except KennisError:
        if not remove:
            raise
        chunks = ()
    return _Named(
        store,
        _passage_anchor(
            request.handle,
            request.chunk,
            chunks,
            remove=remove,
            unindexed=f"'{request.handle}' has no chunk {request.chunk} in the "
            f"project {project}'s index",
            resolution="kennis context index",
        ),
        title,
        link,
        chunks,
    )


def _passage_anchor(
    document: str,
    number: int,
    chunks: Sequence[Chunk],
    *,
    remove: bool,
    unindexed: str,
    resolution: str,
) -> Anchor:
    """The anchor for chunk `number`, quoting it; an untag needs no words."""
    if remove:
        return Anchor(document, number)
    chunk = next((one for one in chunks if one.chunk_index == number), None)
    if chunk is None:
        raise SearchUnavailable(unindexed, resolution=resolution)
    return Anchor(document, number, quote_of(chunk.text))


def _held(store: Path, held: dict[Path, Tags]) -> Tags:
    if store not in held:
        held[store] = read_tags(store)
    return held[store]


def _names_a_stored_document(tags: Tags, document: str) -> bool:
    return any(
        anchor.document == document for anchors in tags.values() for anchor in anchors
    )


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def bundle_title(file: Path) -> str:
    import yaml

    from kennis.engine.frontmatter import split_frontmatter

    try:
        frontmatter, _ = split_frontmatter(file.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        frontmatter = {}
    return _text(frontmatter.get("title")) or file.stem


# ---------------------------------------------------------------------------
# Listing


def tags_held(context: Context, bundles: Sequence[Path]) -> list[TagListing]:
    """Every tag in the corpus and in each project of `bundles`, with each
    target as it stands now; in order of name, the corpus's targets first.

    The command line passes the project it runs in; the window, which
    belongs to no project, every project it lists.
    """
    listed: dict[str, list[TaggedTarget]] = {}
    corpus_store = _corpus_store(context)
    if corpus_store.is_file():
        _listed_corpus(context, read_tags(corpus_store), listed)
    for bundle in bundles:
        if (bundle / TAGS_FILENAME).is_file():
            _listed_bundle(bundle, read_tags(bundle / TAGS_FILENAME), listed)
    return [TagListing(name, listed[name]) for name in sorted(listed)]


def _listed_corpus(
    context: Context, tags: Tags, listed: dict[str, list[TaggedTarget]]
) -> None:
    from kennis.engine.corpus.layout import index_root
    from kennis.engine.rag.index import load_index
    from kennis.finding import resolve_document
    from kennis.publishing import shared

    indexes: dict[str, tuple[Chunk, ...] | None] = {}
    with shared(context.corpus_root):
        for name, anchors in tags.items():
            for anchor in anchors:
                try:
                    where, document = resolve_document(context, anchor.document, None)
                except DocumentNotFound:
                    listed.setdefault(name, []).append(
                        _target(None, anchor, None, MISSING, link_to)
                    )
                    continue
                if where.name not in indexes:
                    try:
                        loaded = load_index(index_root(context.corpus_root), where.name)
                        indexes[where.name] = tuple(loaded.chunks)
                    except KennisError:
                        indexes[where.name] = None
                listed.setdefault(name, []).append(
                    _placed_target(
                        None,
                        anchor,
                        _text(document.frontmatter.title),
                        indexes[where.name],
                        link_to,
                        where.name,
                    )
                )


def _listed_bundle(
    bundle: Path, tags: Tags, listed: dict[str, list[TaggedTarget]]
) -> None:
    from kennis.engine.context.index import load_bundle_index
    from kennis.engine.context.projects import project_names

    project = project_names([bundle])[bundle]

    def linked(path: str, chunk: int | None) -> str:
        return context_link(project, path, chunk)

    try:
        chunks: tuple[Chunk, ...] | None = tuple(load_bundle_index(bundle).chunks)
    except KennisError:
        chunks = None
    for name, anchors in tags.items():
        for anchor in anchors:
            try:
                _, file = bundle_member(bundle, anchor.document)
            except DocumentNotFound:
                listed.setdefault(name, []).append(
                    _target(project, anchor, None, MISSING, linked)
                )
                continue
            listed.setdefault(name, []).append(
                _placed_target(project, anchor, bundle_title(file), chunks, linked)
            )


def _placed_target(
    project: str | None,
    anchor: Anchor,
    title: str | None,
    chunks: tuple[Chunk, ...] | None,
    linked: _Linker,
    collection: str | None = None,
) -> TaggedTarget:
    placement = Unchecked() if chunks is None else placed(anchor, chunks)
    match placement:
        case Placed(chunk=chunk):
            moved = Anchor(anchor.document, chunk, anchor.quote)
            return _target(project, moved, title, PLACED, linked, collection)
        case Detached():
            return _target(project, anchor, title, DETACHED, linked, collection)
        case Unchecked():
            return _target(project, anchor, title, UNCHECKED, linked, collection)


def _target(
    project: str | None,
    anchor: Anchor,
    title: str | None,
    state: str,
    linked: _Linker,
    collection: str | None = None,
) -> TaggedTarget:
    return TaggedTarget(
        project=project,
        collection=collection,
        document=anchor.document,
        title=title,
        chunk=anchor.chunk,
        quote=anchor.quote,
        state=state,
        link=linked(anchor.document, anchor.chunk),
    )


__all__ = [
    "DETACHED",
    "MISSING",
    "PLACED",
    "UNCHECKED",
    "TagChange",
    "TagListing",
    "TagRefusal",
    "Tagged",
    "TaggedTarget",
    "bundle_title",
    "change_tags",
    "tags_held",
]
