"""Tagging documents and passages, and listing what is tagged (#625, #50).

A tag is carried by an annotation (`engine/annotations.py`): tagging a
passage puts the names on the annotation over that chunk's span, making it
when there is none.

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
selects its text, so its chunk must be in the current index. An untag must
work as `kennis tags` prints it for a detached passage, whose chunk may be
gone and whose document may be removed, so it takes the names from the
annotations that begin in that chunk: where each is placed now, or the
chunk it was last placed in.

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
from kennis.engine.annotations import (
    ANNOTATIONS_FILENAME,
    Annotation,
    AnnotationLinks,
    AnnotationStore,
    Detached,
    Placed,
    Selector,
    Unchecked,
    annotated,
    annotation_named,
    indexed_text,
    links,
    located,
    occurrences,
    own_end,
    placed,
    read_annotations,
    rehinted,
    removed,
    revised,
    selector_of,
    with_tags,
    without_tags,
    written,
)
from kennis.engine.errors import DocumentNotFound, KennisError, SearchUnavailable
from kennis.engine.rag.models import Chunk, Filter
from kennis.engine.tags import colour_of, tag_colour, tag_name
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
WRITING_TAGS: Final = threading.Lock()

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
class TagColoured:
    """A colour chosen, or cleared: the tags, the colour each is drawn in
    now, and how many stores were written."""

    names: tuple[str, ...]
    # None when the colour derived from the name was asked for.
    colour: str | None
    shown: dict[str, str]
    stores: int


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
    # The annotation's selected words; None for the whole document.
    quote: str | None
    state: str
    link: str
    annotation: str


@dataclass(frozen=True, slots=True)
class TagListing:
    """One tag and its targets, the corpus's first."""

    name: str
    targets: list[TaggedTarget]


# ---------------------------------------------------------------------------
# Changing


@dataclass(frozen=True, slots=True)
class _Named:
    """A request resolved: its store, what it selects, and how it is shown."""

    store: Path
    document: str
    # The chunk asked for; None for the whole document.
    chunk: int | None
    # The selection a tag is put on; None for the whole document, and for
    # an untag, which matches by chunk instead.
    selector: Selector | None
    title: str | None
    link: str
    # The index's chunks of the document, for an untag to find the
    # annotations linked to the chunk; empty when there is none to read.
    chunks: tuple[Chunk, ...]
    # The annotation named by its id (`annotation=<id>`), which needs no
    # chunk: how a detached selection is untagged.
    annotation: str | None = None
    # Whether `selector` is a quotation's words (#50, unit 4): an untag then
    # takes names from the annotation selecting those words alone.
    quoted: bool = False


def change_tags(
    context: Context,
    requests: Sequence[CiteRequest],
    names: Sequence[str],
    *,
    remove: bool,
) -> Tagged:
    """Tag, or untag, every request with every name, or refuse the batch."""
    with WRITING_TAGS:
        return _changed_tags(context, requests, names, remove=remove)


def _changed_tags(
    context: Context,
    requests: Sequence[CiteRequest],
    names: Sequence[str],
    *,
    remove: bool,
) -> Tagged:
    folded = tuple(dict.fromkeys(tag_name(name) for name in names))
    if not folded:
        raise KennisError("no tag was named", resolution="kennis tag --help")
    held: dict[Path, AnnotationStore] = {}
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

    before = dict(held)
    changes: list[TagChange] = []
    for position, (request, one) in enumerate(zip(requests, named, strict=True)):
        store = held[one.store]
        if remove:
            store, changed = without_tags(store, _untagged_by(store, one), folded)
        else:
            store, changed = with_tags(store, one.document, one.selector, folded)
        held[one.store] = store
        changes.append(
            TagChange(
                position=position,
                handle=request.handle,
                title=one.title,
                link=one.link,
                changed=changed,
                unchanged=tuple(name for name in folded if name not in changed),
            )
        )

    for path, store in held.items():
        if store == before[path]:
            continue
        _write_store(
            context,
            path,
            store,
            counts=_counts(changes, named, path, remove=remove),
        )
    return Tagged(changes=changes, refused=[])


def _write_store(
    context: Context, store: Path, held: AnnotationStore, *, counts: dict[str, int]
) -> None:
    """Write one store, the corpus's committed, a project's left for the
    person to commit.

    Every hint in it is first set to where its passage is now (#626): only
    the nearest occurrence of repeated words is found by the hint, and a
    stale one can be nearer another.
    """
    from kennis.operations import place_corpus_annotations

    corpus = store == _corpus_store(context)
    chunks = corpus_chunks(context) if corpus else _bundle_chunks(store.parent)
    text = written(rehinted(held, chunks))
    if corpus:
        place_corpus_annotations(context, text, counts=counts)
    else:
        _place_bundle_tags(store, text)


@dataclass(frozen=True, slots=True)
class Shown:
    """The document a page shows: a corpus document by its collection and
    handle, or a file of a project's bundle by its path in the bundle."""

    document: str
    collection: str | None = None
    bundle: Path | None = None


@dataclass(frozen=True, slots=True)
class ShownBody:
    """A shown document's identity as a store names it, and its body - the
    text a page draws and an annotation's offsets address."""

    document: str
    body: str


def shown_body(context: Context, shown: Shown) -> ShownBody:
    """The body of the document a page shows, read as the page reads it."""
    if shown.bundle is not None:
        import yaml

        from kennis.engine.context.notes import bundle_documents
        from kennis.engine.frontmatter import split_frontmatter

        held = {
            path.relative_to(shown.bundle).as_posix(): path
            for path in bundle_documents(shown.bundle)
        }
        path = held.get(shown.document)
        if path is None:
            raise DocumentNotFound(
                f"'{shown.document}' is not in this project's bundle",
                resolution="kennis context status",
            )
        text = path.read_text(encoding="utf-8")
        try:
            _, body = split_frontmatter(text)
        except yaml.YAMLError:
            # As the page does: a bundle file's identity is its path, so
            # an unreadable header costs its metadata, not its text.
            body = text
        return ShownBody(shown.document, body)
    from kennis.engine.corpus.collection import Collection

    if shown.collection is None:
        raise DocumentNotFound(
            f"'{shown.document}' names no collection",
            resolution="kennis corpus list",
        )
    document = Collection(root=context.corpus_root, name=shown.collection).resolve(
        shown.document
    )
    return ShownBody(document.id, document.body)


def annotate(
    context: Context,
    shown: Shown,
    *,
    start: int,
    end: int,
    exact: str,
    tags: Sequence[str],
    comment: str | None,
) -> Annotation:
    """Annotate `body[start:end]` of the shown document with `tags` and
    `comment` (#50), in the project's store or the corpus's.

    `exact` is the text the selection was found as when the reader made
    it; if the document no longer holds it there, nothing is written and
    the reader is asked to select again.
    """
    folded = tuple(dict.fromkeys(tag_name(name) for name in tags))
    found = shown_body(context, shown)
    if not 0 <= start < end <= len(found.body) or found.body[start:end] != exact:
        raise KennisError(
            "the document changed since the text was selected",
            resolution="select the text again",
        )
    store = _store_of(context, shown.bundle)
    with WRITING_TAGS:
        held, made = annotated(
            read_annotations(store),
            found.document,
            selector_of(found.body, start, end),
            folded,
            comment,
        )
        _write_store(context, store, held, counts={"annotated": 1})
    return made


def revise_annotation(
    context: Context,
    annotation_id: str,
    *,
    bundle: Path | None,
    tags: Sequence[str],
    comment: str | None,
) -> None:
    """Give the annotation `annotation_id` exactly `tags` and `comment`;
    left with neither, it is removed. Looked for in the project's store
    when one is named, then in the corpus's."""
    folded = tuple(dict.fromkeys(tag_name(name) for name in tags))
    with WRITING_TAGS:
        store, held = _store_holding(context, annotation_id, bundle)
        _write_store(
            context,
            store,
            revised(held, annotation_id, folded, comment),
            counts={"revised": 1},
        )


def delete_annotation(
    context: Context, annotation_id: str, *, bundle: Path | None
) -> None:
    """Remove the annotation `annotation_id`, looked for as
    `revise_annotation` looks."""
    with WRITING_TAGS:
        store, held = _store_holding(context, annotation_id, bundle)
        _write_store(
            context, store, removed(held, annotation_id), counts={"removed": 1}
        )


def find_annotation(
    context: Context, annotation_id: str, *, bundle: Path | None
) -> Annotation:
    """The annotation `annotation_id`, looked for as `revise_annotation`
    looks."""
    _, held = _store_holding(context, annotation_id, bundle)
    return annotation_named(held, annotation_id)


def _store_of(context: Context, bundle: Path | None) -> Path:
    return _corpus_store(context) if bundle is None else bundle / ANNOTATIONS_FILENAME


def _store_holding(
    context: Context, annotation_id: str, bundle: Path | None
) -> tuple[Path, AnnotationStore]:
    stores = [_corpus_store(context)]
    if bundle is not None:
        stores.insert(0, bundle / ANNOTATIONS_FILENAME)
    for store in stores:
        held = read_annotations(store)
        if any(annotation.id == annotation_id for annotation in held.annotations):
            return store, held
    raise KennisError(
        f"no annotation has the id '{annotation_id}'", resolution="kennis tags"
    )


def colour_tags(
    context: Context,
    names: Sequence[str],
    colour: str | None,
    bundles: Sequence[Path],
) -> TagColoured:
    """Choose `colour` for each of `names`, or with None go back to the
    one derived from the name, in every store - the corpus's and each of
    `bundles` - that holds the tag (#627)."""
    with WRITING_TAGS:
        folded = tuple(dict.fromkeys(tag_name(name) for name in names))
        if not folded:
            raise KennisError("no tag was named", resolution="kennis tag --help")
        if colour is not None:
            colour = tag_colour(colour)
        stores = [
            _corpus_store(context),
            *(bundle / ANNOTATIONS_FILENAME for bundle in bundles),
        ]
        held = {store: read_annotations(store) for store in stores}
        nowhere = [
            name
            for name in folded
            if not any(name in one.tag_names() for one in held.values())
        ]
        if nowhere:
            raise KennisError(
                f"nothing is tagged {', '.join(nowhere)}", resolution="kennis tags"
            )
        changed = 0
        for store, one in held.items():
            colours = dict(one.colours)
            in_use = one.tag_names()
            for name in folded:
                if name not in in_use:
                    continue
                if colour is None:
                    colours.pop(name, None)
                else:
                    colours[name] = colour
            if colours == one.colours:
                continue
            changed += 1
            _write_store(
                context,
                store,
                AnnotationStore(one.annotations, colours),
                counts={"coloured": len(folded)},
            )
        return TagColoured(
            names=folded,
            colour=colour,
            shown={
                name: colour_of(name, {name: colour} if colour else {})
                for name in folded
            },
            stores=changed,
        )


def _untagged_by(store: AnnotationStore, one: _Named) -> list[str]:
    """The ids of the annotations an untag of `one` takes names from.

    The one named by its id; for a document, its whole-document
    annotations; for a chunk, every annotation linked to it - so a hit
    that shows a tag can always have it removed, a selection across two
    chunks included.
    """
    if one.annotation is not None:
        return [one.annotation]
    if one.quoted and one.selector is not None:
        # The annotation selecting the quoted words, wherever it now is.
        text = indexed_text(one.chunks)
        quoted = located(one.selector, text)
        return [
            annotation.id
            for annotation in store.annotations
            if annotation.document == one.document
            and annotation.selector is not None
            and located(annotation.selector, text) == quoted
        ]
    if one.chunk is None:
        return [
            annotation.id
            for annotation in store.annotations
            if annotation.document == one.document and annotation.selector is None
        ]
    chunk = next((each for each in one.chunks if each.chunk_index == one.chunk), None)
    if chunk is None:
        return []
    return list(links(store, one.chunks).by_chunk.get(chunk.id, ()))


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
    return context.corpus_root / ANNOTATIONS_FILENAME


def corpus_chunks(context: Context) -> list[Chunk]:
    """The chunks of every corpus collection with an index here."""
    from kennis.engine.corpus.layout import index_root
    from kennis.engine.corpus.schema import COLLECTION_NAMES
    from kennis.engine.rag.index import load_chunks

    chunks: list[Chunk] = []
    for name in COLLECTION_NAMES:
        try:
            chunks.extend(load_chunks(index_root(context.corpus_root), name))
        except KennisError:
            continue
    return chunks


def _bundle_chunks(bundle: Path) -> list[Chunk]:
    from kennis.engine.context.index import load_bundle_index

    try:
        return load_bundle_index(bundle).chunks
    except KennisError:
        return []


def _named(
    context: Context,
    request: CiteRequest,
    held: dict[Path, AnnotationStore],
    *,
    remove: bool,
) -> _Named:
    if request.annotation:
        return _named_annotation(context, request, held)
    if request.bundle is not None:
        return _named_in_bundle(request, request.bundle, held, remove=remove)
    from kennis.engine.corpus.layout import index_root
    from kennis.engine.rag.index import load_chunks
    from kennis.finding import resolve_document

    store = _corpus_store(context)
    tags = _held(store, held)
    try:
        where, document = resolve_document(context, request.handle, None)
    except DocumentNotFound:
        # A document removed since it was tagged can still be untagged by
        # the identifier `kennis tags` printed for it.
        if remove and _names_a_stored_document(tags, request.handle):
            return _Named(
                store,
                request.handle,
                request.chunk,
                None,
                None,
                link_to(request.handle, request.chunk),
                (),
            )
        raise
    title = _text(document.frontmatter.title)
    link = link_to(document.id, request.chunk)
    if request.chunk is None and request.quote is None:
        return _Named(store, document.id, None, None, title, link, ())
    try:
        chunks = tuple(
            chunk
            for chunk in load_chunks(index_root(context.corpus_root), where.name)
            if chunk.document_id == document.id
        )
    except KennisError:
        if not remove or request.quote is not None:
            raise
        chunks = ()
    if request.quote is not None:
        return _Named(
            store,
            document.id,
            request.chunk,
            _quoted_selector(
                request.quote,
                chunks,
                request.chunk,
                handle=request.handle,
                resolution="kennis corpus index",
            ),
            title,
            link,
            chunks,
            quoted=True,
        )
    assert request.chunk is not None, "neither a quote nor a chunk is whole, above"
    return _Named(
        store,
        document.id,
        request.chunk,
        _passage_selector(
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


def _named_annotation(
    context: Context, request: CiteRequest, held: dict[Path, AnnotationStore]
) -> _Named:
    """An annotation named by its id: in the project's store when the
    request names one, then in the corpus's."""
    stores = [_corpus_store(context)]
    if request.bundle is not None:
        stores.insert(0, request.bundle / ANNOTATIONS_FILENAME)
    for store in stores:
        found = next(
            (
                annotation
                for annotation in _held(store, held).annotations
                if annotation.id == request.handle
            ),
            None,
        )
        if found is None:
            continue
        if request.bundle is not None and store.parent == request.bundle:
            from kennis.engine.context.projects import project_names

            project = project_names([request.bundle])[request.bundle]
            link = context_link(project, found.document, None)
        else:
            link = link_to(found.document, None)
        return _Named(
            store,
            found.document,
            None,
            found.selector,
            None,
            link,
            (),
            annotation=found.id,
        )
    raise KennisError(
        f"no annotation has the id '{request.handle}'", resolution="kennis tags"
    )


def _named_in_bundle(
    request: CiteRequest,
    bundle: Path,
    held: dict[Path, AnnotationStore],
    *,
    remove: bool,
) -> _Named:
    from kennis.engine.context.index import load_bundle_index

    store = bundle / ANNOTATIONS_FILENAME
    tags = _held(store, held)
    try:
        project, file = bundle_member(bundle, request.handle)
    except DocumentNotFound:
        if remove and _names_a_stored_document(tags, request.handle):
            from kennis.engine.context.projects import project_names

            project = project_names([bundle])[bundle]
            link = context_link(project, request.handle, request.chunk)
            return _Named(store, request.handle, request.chunk, None, None, link, ())
        raise
    title = bundle_title(file)
    link = context_link(project, request.handle, request.chunk)
    if request.chunk is None and request.quote is None:
        return _Named(store, request.handle, None, None, title, link, ())
    try:
        chunks = tuple(
            chunk
            for chunk in load_bundle_index(bundle).chunks
            if chunk.document_id == request.handle
        )
    except KennisError:
        if not remove or request.quote is not None:
            raise
        chunks = ()
    if request.quote is not None:
        return _Named(
            store,
            request.handle,
            request.chunk,
            _quoted_selector(
                request.quote,
                chunks,
                request.chunk,
                handle=request.handle,
                resolution="kennis context index",
            ),
            title,
            link,
            chunks,
            quoted=True,
        )
    assert request.chunk is not None, "neither a quote nor a chunk is whole, above"
    return _Named(
        store,
        request.handle,
        request.chunk,
        _passage_selector(
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


def _passage_selector(
    number: int,
    chunks: Sequence[Chunk],
    *,
    remove: bool,
    unindexed: str,
    resolution: str,
) -> Selector | None:
    """The selection of chunk `number`'s span; an untag needs no words."""
    if remove:
        return None
    chunk = next((one for one in chunks if one.chunk_index == number), None)
    if chunk is None:
        raise SearchUnavailable(unindexed, resolution=resolution)
    return selector_of(indexed_text(chunks), chunk.char_start, own_end(chunks, chunk))


def _quoted_selector(
    quote: str,
    chunks: Sequence[Chunk],
    number: int | None,
    *,
    handle: str,
    resolution: str,
) -> Selector:
    """The selection of `quote`'s words: in chunk `number` of the document's
    indexed text, or anywhere in it when there is none (#50, unit 4).

    **Exactly once, or refused**: tagging the first of several would be a
    guess the agent cannot see, and the remedy - its chunk, or more of the
    words - is the agent's to give. The selector is made from the indexed
    text, which is what `located` finds it in again.
    """
    if not chunks:
        raise SearchUnavailable(
            f"'{handle}' is not in the index, so its words cannot be found",
            resolution=resolution,
        )
    text = indexed_text(chunks)
    where = f"'{handle}'"
    start, end = 0, len(text)
    if number is not None:
        chunk = next((one for one in chunks if one.chunk_index == number), None)
        if chunk is None:
            raise SearchUnavailable(
                f"'{handle}' has no chunk {number} in the index",
                resolution=resolution,
            )
        start, end = chunk.char_start, chunk.char_end
        where = f"chunk {number} of '{handle}'"
    found = occurrences(quote, text, start, end)
    if not found:
        beyond = (
            "; leave out `chunk` to look in the whole document"
            if number is not None
            else ""
        )
        raise KennisError(f"the words quoted are not in {where}{beyond}")
    if len(found) > 1:
        raise KennisError(
            f"the words quoted appear {len(found)} times in {where}; "
            "give the chunk or quote more of the passage"
        )
    return selector_of(text, found[0].start, found[0].end)


def _held(store: Path, held: dict[Path, AnnotationStore]) -> AnnotationStore:
    if store not in held:
        held[store] = read_annotations(store)
    return held[store]


def _names_a_stored_document(store: AnnotationStore, document: str) -> bool:
    return any(annotation.document == document for annotation in store.annotations)


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
        _listed_corpus(context, read_annotations(corpus_store), listed)
    for bundle in bundles:
        if (bundle / ANNOTATIONS_FILENAME).is_file():
            _listed_bundle(
                bundle, read_annotations(bundle / ANNOTATIONS_FILENAME), listed
            )
    return [TagListing(name, listed[name]) for name in sorted(listed)]


@dataclass(frozen=True, slots=True)
class FoundComment:
    """An annotation whose comment matched a question, as it stands now.

    `rank` is its place among every comment that matched, from one, and
    `score` its BM25 score: lexical alone, because comments are ranked per
    search and never embedded (sketch 2026-11-17-search-comments).
    """

    target: TaggedTarget
    comment: str
    tags: tuple[str, ...]
    rank: int
    score: float
    # The project's bundle the annotation is in; None for the corpus's.
    bundle: Path | None


def comments_matching(
    context: Context,
    bundles: Sequence[Path],
    question: str,
    *,
    top_k: int,
    tags: Sequence[str] = (),
    filters: list[Filter] | None = None,
) -> list[FoundComment]:
    """The `top_k` annotations whose comment best matches `question`, from
    the corpus's store and each bundle's, ranked together.

    `tags` keeps only annotations carrying every one; `filters` test the
    annotated document's chunks as they test any chunk, so an annotation
    whose document no index holds is kept only when nothing filters.

    **Ranked first, resolved after, in rank order and only until `top_k`
    are kept**: resolving reads a collection's index, which a search over
    the comments of one collection should not pay for every collection.
    """
    from contextlib import ExitStack

    from kennis.engine.annotations import comments_ranked
    from kennis.engine.rag.models import combine_filters
    from kennis.publishing import shared

    wanted = set(tags)
    candidates: list[tuple[Annotation, _CorpusTargets | _BundleTargets]] = []
    corpus_store = _corpus_store(context)
    holds_corpus = corpus_store.is_file()
    if holds_corpus:
        store = read_annotations(corpus_store)
        corpus_targets = _CorpusTargets(context, store)
        candidates.extend((each, corpus_targets) for each in store.annotations)
    for bundle in bundles:
        if (bundle / ANNOTATIONS_FILENAME).is_file():
            store = read_annotations(bundle / ANNOTATIONS_FILENAME)
            bundle_targets = _BundleTargets(bundle, store)
            candidates.extend((each, bundle_targets) for each in store.annotations)
    candidates = [
        (annotation, resolver)
        for annotation, resolver in candidates
        if wanted <= set(annotation.tags)
    ]
    ranked = comments_ranked(
        [annotation for annotation, _ in candidates], question, len(candidates)
    )
    admits = combine_filters(filters)
    found: list[FoundComment] = []
    with ExitStack() as holding:
        if holds_corpus:
            holding.enter_context(shared(context.corpus_root))
        for rank, (position, score) in enumerate(ranked, start=1):
            if len(found) == top_k:
                break
            annotation, resolver = candidates[position]
            target, chunks = resolver.target(annotation)
            if admits is not None and not any(admits(chunk) for chunk in chunks):
                continue
            found.append(
                FoundComment(
                    target=target,
                    comment=annotation.comment or "",
                    tags=annotation.tags,
                    rank=rank,
                    score=score,
                    bundle=resolver.bundle,
                )
            )
    return found


def _listed_corpus(
    context: Context, store: AnnotationStore, listed: dict[str, list[TaggedTarget]]
) -> None:
    from kennis.publishing import shared

    resolver = _CorpusTargets(context, store)
    with shared(context.corpus_root):
        for annotation in store.annotations:
            if not annotation.tags:
                continue
            target, _ = resolver.target(annotation)
            for name in annotation.tags:
                listed.setdefault(name, []).append(target)


def _listed_bundle(
    bundle: Path, store: AnnotationStore, listed: dict[str, list[TaggedTarget]]
) -> None:
    resolver = _BundleTargets(bundle, store)
    for annotation in store.annotations:
        if not annotation.tags:
            continue
        target, _ = resolver.target(annotation)
        for name in annotation.tags:
            listed.setdefault(name, []).append(target)


class _CorpusTargets:
    """The corpus's annotations as they stand now, each collection's index
    read once, when the first annotation of a document in it is asked for.
    The caller holds the corpus shared."""

    def __init__(self, context: Context, store: AnnotationStore) -> None:
        self._context = context
        self._store = store
        self._indexes: dict[str, _Placing | None] = {}
        self.bundle: Path | None = None

    def target(self, annotation: Annotation) -> tuple[TaggedTarget, tuple[Chunk, ...]]:
        """The annotation's target, and its document's chunks in the index
        (none when no index holds it)."""
        from kennis.engine.corpus.layout import index_root
        from kennis.engine.rag.index import load_chunks
        from kennis.finding import resolve_document

        try:
            where, document = resolve_document(self._context, annotation.document, None)
        except DocumentNotFound:
            return _target(None, annotation, None, None, MISSING, link_to), ()
        if where.name not in self._indexes:
            try:
                self._indexes[where.name] = _Placing.of(
                    self._store,
                    load_chunks(index_root(self._context.corpus_root), where.name),
                )
            except KennisError:
                self._indexes[where.name] = None
        placing = self._indexes[where.name]
        return (
            _placed_target(
                None,
                annotation,
                _text(document.frontmatter.title),
                placing,
                link_to,
                where.name,
            ),
            () if placing is None else placing.of_document(annotation.document),
        )


class _BundleTargets:
    """A project's annotations as they stand now, its index read once."""

    def __init__(self, bundle: Path, store: AnnotationStore) -> None:
        from kennis.engine.context.index import load_bundle_index
        from kennis.engine.context.projects import project_names

        self._bundle = bundle
        self.bundle: Path | None = bundle
        self.project = project_names([bundle])[bundle]
        try:
            self._placing: _Placing | None = _Placing.of(
                store, load_bundle_index(bundle).chunks
            )
        except KennisError:
            self._placing = None

    def _linked(self, path: str, chunk: int | None) -> str:
        return context_link(self.project, path, chunk)

    def target(self, annotation: Annotation) -> tuple[TaggedTarget, tuple[Chunk, ...]]:
        try:
            _, file = bundle_member(self._bundle, annotation.document)
        except DocumentNotFound:
            return (
                _target(self.project, annotation, None, None, MISSING, self._linked),
                (),
            )
        placing = self._placing
        return (
            _placed_target(
                self.project, annotation, bundle_title(file), placing, self._linked
            ),
            () if placing is None else placing.of_document(annotation.document),
        )


@dataclass(frozen=True, slots=True)
class _Placing:
    """One index's chunks and their links to a store, computed once for a
    listing rather than once per annotation."""

    chunks: tuple[Chunk, ...]
    linked: AnnotationLinks
    numbers: dict[str, int]

    @classmethod
    def of(cls, store: AnnotationStore, chunks: Sequence[Chunk]) -> _Placing:
        return cls(
            tuple(chunks),
            links(store, chunks),
            {chunk.id: chunk.chunk_index for chunk in chunks},
        )

    def of_document(self, document: str) -> tuple[Chunk, ...]:
        return tuple(chunk for chunk in self.chunks if chunk.document_id == document)


def _placed_target(
    project: str | None,
    annotation: Annotation,
    title: str | None,
    placing: _Placing | None,
    linked: _Linker,
    collection: str | None = None,
) -> TaggedTarget:
    """`annotation` as it stands in an index: a placed selection at the
    first chunk linked to it, a whole document at none."""
    if placing is None:
        return _target(project, annotation, None, title, UNCHECKED, linked, collection)
    match placed(annotation, placing.chunks):
        case Placed(span=None):
            return _target(project, annotation, None, title, PLACED, linked, collection)
        case Placed():
            chunk = min(
                placing.numbers[each]
                for each in placing.linked.by_annotation.get(annotation.id, ())
            )
            return _target(
                project, annotation, chunk, title, PLACED, linked, collection
            )
        case Detached():
            return _target(
                project, annotation, None, title, DETACHED, linked, collection
            )
        case Unchecked():
            return _target(
                project, annotation, None, title, UNCHECKED, linked, collection
            )


def _target(
    project: str | None,
    annotation: Annotation,
    chunk: int | None,
    title: str | None,
    state: str,
    linked: _Linker,
    collection: str | None = None,
) -> TaggedTarget:
    return TaggedTarget(
        project=project,
        collection=collection,
        document=annotation.document,
        title=title,
        chunk=chunk,
        quote=None if annotation.selector is None else annotation.selector.exact,
        state=state,
        link=linked(annotation.document, chunk),
        annotation=annotation.id,
    )


__all__ = [
    "DETACHED",
    "MISSING",
    "PLACED",
    "UNCHECKED",
    "WRITING_TAGS",
    "FoundComment",
    "Shown",
    "ShownBody",
    "TagChange",
    "TagColoured",
    "TagListing",
    "TagRefusal",
    "Tagged",
    "TaggedTarget",
    "annotate",
    "bundle_title",
    "change_tags",
    "colour_tags",
    "comments_matching",
    "corpus_chunks",
    "delete_annotation",
    "find_annotation",
    "revise_annotation",
    "shown_body",
    "tags_held",
]
