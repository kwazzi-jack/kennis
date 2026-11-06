"""Tags as the window shows them (#625): the tags' page, one tag's page, a
document's tags in its inspector, and the pane's list.

The window belongs to no project, so every listing reads the corpus's tags
and every present project's. A target is named in every form by its
`kennis://` link, which is one shape for a corpus document and a project's
file; `citing.request_for` turns it back into what `tagging` takes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final
from urllib.parse import quote

from kennis.context import Context
from kennis.engine.context.groups import project_group
from kennis.engine.context.projects import known_projects
from kennis.engine.errors import KennisError
from kennis.engine.tags import TAGS_FILENAME, read_tags
from kennis.gui import words
from kennis.gui.pages import passage_href
from kennis.render.tags import target_state
from kennis.tagging import (
    DETACHED,
    MISSING,
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
    remove_label: str


def present_bundles() -> list[Path]:
    """Every listed project whose folder is there; none when the list
    cannot be read, which the pane says for itself."""
    try:
        return [project.bundle for project in known_projects() if project.present]
    except KennisError:
        return []


def tag_href(name: str) -> str:
    return f"/tags?tag={quote(name, safe='')}"


def pane_tags(context: Context) -> tuple[ShownTag, ...]:
    """Each tag and its count, read from the files alone: the pane is on
    every page, and placing passages is the tag page's work."""
    counts: dict[str, int] = {}
    for root in (context.corpus_root, *present_bundles()):
        try:
            held = read_tags(root / TAGS_FILENAME)
        except KennisError:
            continue
        for name, anchors in held.items():
            counts[name] = counts.get(name, 0) + len(anchors)
    return tuple(
        ShownTag(name=name, href=tag_href(name), count=counts[name])
        for name in sorted(counts)
    )


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
    held = tags_held(context, [] if bundle is None else [bundle])
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
    "document_tags",
    "listings",
    "pane_tags",
    "present_bundles",
    "shown_tagged",
    "tag_href",
    "tags_in_use",
]
