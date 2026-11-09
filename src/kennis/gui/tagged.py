"""Tags as the window shows them (#625): the tags' page, one tag's page, a
document's tags in its inspector, and the pane's list.

The window belongs to no project, so every listing reads the corpus's tags
and every present project's. A target is named in every form by its
`kennis://` link, which is one shape for a corpus document and a project's
file; `citing.request_for` turns it back into what `tagging` takes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from urllib.parse import quote

from kennis.context import Context
from kennis.engine.context.groups import project_group
from kennis.engine.context.projects import known_projects, project_names
from kennis.engine.errors import KennisError
from kennis.engine.rag.models import Chunk
from kennis.engine.tags import (
    TAGS_FILENAME,
    Tags,
    TagStore,
    colour_of,
    read_store,
    rehinted,
    tags_on,
)
from kennis.gui import words
from kennis.gui.pages import ChipsOf, ShownChip, passage_href
from kennis.render.tags import target_state
from kennis.tagging import (
    DETACHED,
    MISSING,
    PLACED,
    TaggedTarget,
    TagListing,
    tags_held,
)

PASSAGE: Final = "passage"
DOCUMENT: Final = "document"


@dataclass(frozen=True, slots=True)
class ShownTag:
    """A tag in a list: its name, its page and how much it holds."""

    name: str
    href: str
    count: int
    colour: str


@dataclass(frozen=True, slots=True)
class ShownTagged:
    """One target of a tag, as its page shows it.

    `href` is the way into the document at the passage, or None when the
    document is no longer held; `trouble` says what is wrong, if anything.
    """

    kind: str
    state: str
    title: str
    href: str | None
    link: str
    quote: str | None
    trouble: str | None
    remove_label: str


@dataclass(frozen=True, slots=True)
class ShownDocumentTag:
    """A tag on the document a page shows, with what it is on."""

    name: str
    href: str
    link: str
    chunk: int | None
    # The passage's opening words, which tell two tagged passages apart;
    # None for the whole document.
    quote: str | None
    colour: str
    remove_label: str
    # Whether `chunk` is where the passage's words are now, which is what a
    # mark beside the chunk in the text needs (#627).
    placed: bool = False


def present_bundles() -> list[Path]:
    """Every listed project whose folder is there; none when the list
    cannot be read, which the pane says for itself."""
    try:
        return [project.bundle for project in known_projects() if project.present]
    except KennisError:
        return []


def tag_href(name: str) -> str:
    return f"/tags?tag={quote(name, safe='')}"


def _stores(context: Context, bundles: Sequence[Path]) -> list[tuple[Path, TagStore]]:
    """Each readable store, the corpus's first; one that cannot be read is
    left out, and its page says why."""
    read: list[tuple[Path, TagStore]] = []
    for root in (context.corpus_root, *bundles):
        try:
            read.append((root, read_store(root / TAGS_FILENAME)))
        except KennisError:
            continue
    return read


def chosen_colours(stores: Sequence[tuple[Path, TagStore]]) -> dict[str, str]:
    """The colour chosen for each tag: where two stores chose differently,
    the corpus's, then the first project's (#627)."""
    chosen: dict[str, str] = {}
    for _, store in stores:
        for name, colour in store.colours.items():
            chosen.setdefault(name, colour)
    return chosen


def chosen_colours_here(context: Context) -> dict[str, str]:
    """The colours chosen in the corpus and every present project."""
    return chosen_colours(_stores(context, present_bundles()))


def tag_colours(context: Context) -> dict[str, str]:
    """The colour each tag in use is drawn in, chosen or derived."""
    stores = _stores(context, present_bundles())
    chosen = chosen_colours(stores)
    return {name: colour_of(name, chosen) for _, store in stores for name in store.tags}


def pane_tags(context: Context) -> tuple[ShownTag, ...]:
    """Each tag and its count, read from the files alone: the pane is on
    every page, and placing passages is the tag page's work."""
    stores = _stores(context, present_bundles())
    chosen = chosen_colours(stores)
    counts: dict[str, int] = {}
    for _, store in stores:
        for name, anchors in store.tags.items():
            counts[name] = counts.get(name, 0) + len(anchors)
    return tuple(
        ShownTag(
            name=name,
            href=tag_href(name),
            count=counts[name],
            colour=colour_of(name, chosen),
        )
        for name in sorted(counts)
    )


def chips_finder(context: Context, bundles: Sequence[Path]) -> ChipsOf:
    """What a results page asks of each hit: the tags on its chunk (#627).

    The stores are read once per page. The corpus's hints are current
    (#626) and trusted; a project's are rewritten only when its tags
    change, so its store is placed in memory against its index first.
    """
    from kennis.engine.context.groups import project_of_group

    stores = _stores(context, bundles)
    chosen = chosen_colours(stores)
    corpus = stores[0][1].tags if stores and stores[0][0] == context.corpus_root else {}
    projects: dict[str, Tags] = {}
    for root, store in stores:
        if root == context.corpus_root or not store.tags:
            continue
        projects[project_names([root])[root]] = rehinted(
            store.tags, _bundle_chunks(root)
        )

    def chips_of(collection: str, chunk: Chunk) -> tuple[ShownChip, ...]:
        project = project_of_group(collection)
        held = corpus if project is None else projects.get(project, {})
        return tuple(
            ShownChip(
                name=name,
                href=tag_href(name),
                colour=colour_of(name, chosen),
                whole=whole,
            )
            for name, whole in tags_on(held, chunk)
        )

    return chips_of


def _bundle_chunks(bundle: Path) -> list[Chunk]:
    from kennis.engine.context.index import load_bundle_index

    try:
        return load_bundle_index(bundle).chunks
    except KennisError:
        return []


def listings(context: Context) -> list[TagListing]:
    return tags_held(context, present_bundles())


def shown_tagged(listing: TagListing) -> list[ShownTagged]:
    """A tag's targets: passages first, then documents, and those that need
    attention - detached, or no longer held - last."""
    shown = [_shown(listing.name, target) for target in listing.targets]
    return sorted(
        shown,
        key=lambda one: (one.state in (DETACHED, MISSING), one.kind != PASSAGE),
    )


def _shown(name: str, target: TaggedTarget) -> ShownTagged:
    title = target.title or target.document
    if target.project is not None:
        title = f"{title} ({target.project})"
    return ShownTagged(
        kind=PASSAGE if target.chunk is not None else DOCUMENT,
        state=target.state,
        title=title,
        href=_way_in(target),
        link=target.link,
        quote=target.quote,
        trouble=target_state(target),
        remove_label=words.remove_tag_from(name, title),
    )


def _way_in(target: TaggedTarget) -> str | None:
    if target.state == MISSING:
        return None
    if target.project is not None:
        return passage_href(
            project_group(target.project), target.document, target.chunk
        )
    if target.collection is None:
        return None
    return passage_href(target.collection, target.document, target.chunk)


def document_tags(
    context: Context, *, document: str, project: str | None, bundle: Path | None
) -> list[ShownDocumentTag]:
    """The tags on one document, whole or by passage, in order of name."""
    bundles = [] if bundle is None else [bundle]
    held = tags_held(context, bundles)
    chosen = chosen_colours(_stores(context, bundles))
    shown: list[ShownDocumentTag] = []
    for listing in held:
        for target in listing.targets:
            if target.document != document or target.project != project:
                continue
            shown.append(
                ShownDocumentTag(
                    name=listing.name,
                    href=tag_href(listing.name),
                    link=target.link,
                    chunk=target.chunk,
                    quote=target.quote,
                    colour=colour_of(listing.name, chosen),
                    placed=target.state == PLACED,
                    remove_label=words.remove_tag_from(
                        listing.name, target.title or target.document
                    ),
                )
            )
    return shown


def tags_in_use(context: Context) -> list[str]:
    """Every tag's name, for the dialog's suggestions."""
    return [tag.name for tag in pane_tags(context)]


__all__ = [
    "DOCUMENT",
    "PASSAGE",
    "ShownDocumentTag",
    "ShownTag",
    "ShownTagged",
    "chips_finder",
    "chosen_colours",
    "chosen_colours_here",
    "document_tags",
    "listings",
    "pane_tags",
    "present_bundles",
    "shown_tagged",
    "tag_colours",
    "tag_href",
    "tags_in_use",
]
