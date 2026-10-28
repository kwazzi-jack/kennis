"""The Add dialog's shapes: its tabs, their fields, a preview and the chooser.

**A tab is a kind of thing to add, and shows only that kind's fields.**
Every tab posts to the one `/add` route with the field names it has
always read, so a tab is a form that leaves out what does not apply
rather than a second implementation of adding (#413).

**Every field says whether it is required, and an optional one says what
empty becomes.** "Optional" alone leaves the reader to guess what kennis
will do instead, and the answer is usually something specific - a
citekey made from the authors, a project named from the address.

**The chooser lists the computer kennis runs on**, because that is the
computer `corpus add` reads from. Under `ssh -L` a native chooser would
list the laptop's files and hand kennis a path that does not exist where
it runs (#420). Names only: it never opens a file.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final, Literal
from urllib.parse import quote

from kennis.engine.corpus.preview import LineCheck, PaperPreview, SitePreview
from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.literature.names import split_names, unbraced
from kennis.gui import words
from kennis.gui.repairs import WayOut, ways_out_for
from kennis.render.refusals import refusal_fact

ADD_KINDS: Final[tuple[str, ...]] = tuple(kind for kind, _ in words.ADD_TABS)

# The collection a tab adds to, where the tab decides it.
FIXED_COLLECTIONS: Final[dict[str, str]] = {"paper": "literature", "site": "docs"}

# The field naming the place within the collection, per tab: a docs
# page's directory is its project (#101). Several by group has none,
# because each of its blocks names its own.
PLACE_FIELDS: Final[dict[str, str]] = {
    "paper": "group",
    "site": "project",
    "file": "group",
}


def destination_of(kind: str, given: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    """Where an add on this tab will go, as `(field, value)` parts.

    The field is what the window keeps each part in step with; the value
    is what the form holds when it is drawn - the fixed collection, or
    the place the dialog was opened on. Empty for Several by group.
    """
    if kind not in PLACE_FIELDS:
        return ()
    collection = FIXED_COLLECTIONS.get(kind, given.get("collection", ""))
    place = PLACE_FIELDS[kind]
    return (("collection", collection), (place, given.get(place, "")))


# The field names the chooser may write into: the add form's, and the
# backup folder on the settings page. Echoed into an attribute, so only
# names kennis drew are taken rather than escaping whatever was sent and
# hoping.
_TARGET: Final = re.compile(r"identifiers|lines-[0-9]{1,3}|backup\.folder|path")

# How many blocks the group tab draws before "Another group" is used.
FIRST_BLOCKS: Final[tuple[int, ...]] = (1, 2)

# `flag` is a checkbox: on or off, for one add.
type Widget = Literal["text", "number", "choice", "ways", "flag"]
type Upload = Literal["file", "both"]


@dataclass(frozen=True, slots=True)
class ShownTab:
    kind: str
    label: str
    href: str
    current: bool
    icon: str


def add_kind(asked: str) -> str:
    """The tab asked for, or the first. A tab is a link, and the worst a
    wrong one can do is open the first tab."""
    return asked if asked in ADD_KINDS else ADD_KINDS[0]


def add_tabs(kind: str) -> list[ShownTab]:
    return [
        ShownTab(
            kind=each,
            label=label,
            href=f"/add?kind={each}",
            current=each == kind,
            icon=words.ADD_TAB_ICONS[each],
        )
        for each, label in words.ADD_TABS
    ]


@dataclass(frozen=True, slots=True)
class ShownChoice:
    """One of a choice field's options: what it posts and what it says."""

    value: str
    label: str
    icon: str | None = None


@dataclass(frozen=True, slots=True)
class ShownField:
    """One form field, with what a reader needs to fill it in.

    `empty` is what an optional field left empty becomes, and None for a
    required one. `preview` is the route the field asks as it is typed;
    `upload` says whether the browser's own picker may send files, or files
    or a whole folder. `when` is the Paper tab's way in that the field
    belongs to, shown only while that way is chosen.
    """

    name: str
    label: str
    required: bool
    widget: Widget = "text"
    empty: str | None = None
    upload: Upload | None = None
    preview: str | None = None
    choices: tuple[ShownChoice, ...] = ()
    when: str | None = None
    # What the field holds when it is drawn: empty, unless the reader
    # opened the dialog from a place in the tree (11f).
    value: str = ""


def filled(fields: Sequence[ShownField], given: Mapping[str, str]) -> list[ShownField]:
    """`fields` with the values `given` for them, and only for them.

    Filled as given. Jinja escapes the value; a choice the field does not
    offer checks no radio, which is the field left empty; and the add
    refuses a wrong value exactly as it would refuse it typed.
    """
    return [
        replace(field, value=given[field.name]) if given.get(field.name) else field
        for field in fields
    ]


def add_fields(kind: str, *, default_group: str | None) -> list[ShownField]:
    """The fields one tab shows, in the order it shows them."""
    labels = words.FIELD_LABELS
    empty = words.EMPTY_MEANS
    group = ShownField(
        name="group",
        label=labels["group"],
        required=False,
        empty=words.group_empty_means(default_group),
    )
    if kind == "paper":
        return [
            ShownField(
                name="source",
                label=labels["source"],
                required=True,
                widget="ways",
                preview="/add/preview/paper",
                choices=tuple(
                    ShownChoice(value, label, icon)
                    for value, label, icon in words.SOURCE_CHOICES
                ),
                value="identifier",
            ),
            ShownField(
                name="identifiers",
                label=labels["paper"],
                required=True,
                preview="/add/preview/paper",
                when="identifier",
            ),
            ShownField(
                name="pdf",
                label=labels["pdf"],
                # One of the two is needed: a PDF chosen in the picker, or
                # its address or path typed in the fold under it.
                required=True,
                upload="file",
                preview="/add/preview/paper",
                when="pdf",
            ),
            ShownField(
                name="identifier",
                label=labels["identifier"],
                required=False,
                empty=empty["identifier"],
                preview="/add/preview/paper",
                when="pdf",
            ),
            ShownField(
                name="title",
                label=labels["title"],
                required=False,
                empty=empty["title"],
            ),
            ShownField(
                name="citekey",
                label=labels["citekey"],
                required=False,
                empty=empty["citekey"],
                preview="/add/preview/paper",
            ),
            group,
        ]
    if kind == "site":
        return [
            ShownField(
                name="identifiers",
                label=labels["site"],
                required=True,
                preview="/add/preview/site",
            ),
            ShownField(
                name="project",
                label=labels["project"],
                required=False,
                empty=empty["project"],
                preview="/add/preview/site",
            ),
            ShownField(
                name="version",
                label=labels["version"],
                required=False,
                empty=empty["version"],
                preview="/add/preview/site",
            ),
            ShownField(
                name="max_pages",
                label=labels["max_pages"],
                required=False,
                widget="number",
                empty=empty["max_pages"],
            ),
            ShownField(
                name="max_depth",
                label=labels["max_depth"],
                required=False,
                widget="number",
                empty=empty["max_depth"],
            ),
            ShownField(
                name="refresh",
                label=labels["refresh"],
                required=False,
                widget="flag",
                empty=empty["refresh"],
            ),
        ]
    return [
        ShownField(
            name="identifiers",
            label=labels["file"],
            required=True,
            upload="both",
        ),
        ShownField(
            name="collection",
            label=labels["collection"],
            required=True,
            widget="choice",
            choices=tuple(ShownChoice(name, name) for name in COLLECTION_NAMES),
        ),
        ShownField(
            name="title",
            label=labels["title"],
            required=False,
            empty=empty["file_title"],
        ),
        group,
        ShownField(
            name="project",
            label=labels["project"],
            required=False,
            empty=empty["file_project"],
        ),
        ShownField(
            name="version",
            label=labels["version"],
            required=False,
            empty=empty["file_version"],
        ),
    ]


@dataclass(frozen=True, slots=True)
class ShownLine:
    """One sentence of a preview, and the role it is shown in."""

    text: str
    role: str = ""


@dataclass(frozen=True, slots=True)
class ShownFound:
    """The paper a preview found, laid out as a card.

    `title` is set only when the Title field is not already showing it.
    `authors` is the byline shortened; `every_author` is the whole list,
    for its tooltip.
    """

    label: str
    href: str
    year: str
    authors: str
    every_author: str
    title: str | None


def shown_paper_found(
    preview: PaperPreview, *, in_fields: frozenset[str] = frozenset()
) -> ShownFound | None:
    """The card for the paper arXiv named, or None when it named none."""
    if preview.recognised is None or preview.title is None or preview.refusal:
        return None
    names = [unbraced(name) for name in split_names(preview.authors or "")]
    identifier = preview.recognised.value
    return ShownFound(
        label=words.found_on_arxiv(identifier),
        href=f"https://arxiv.org/abs/{identifier}",
        year=preview.year or "",
        authors=words.shortened_authors(names) if names else "",
        every_author=", ".join(names),
        title=None if "title" in in_fields else preview.title,
    )


def paper_prefill(
    preview: PaperPreview, *, several: bool, kept: frozenset[str]
) -> list[tuple[str, str]]:
    """The Title and Citekey fields to redraw, each with its new value.

    `kept` names the fields not to redraw: one the reader typed, and the
    one whose input asked for this preview, which the reader is in. Any
    other is kennis's, and is filled from the preview or emptied when it
    found nothing, so a changed identifier never leaves the last paper's
    title behind. Several papers fill nothing: a title names one.
    """
    found = not several and preview.refusal is None and preview.title is not None
    values = {
        "title": preview.title if found else None,
        "citekey": preview.citekey if found else None,
    }
    return [(name, value or "") for name, value in values.items() if name not in kept]


def preview_ways(preview: PaperPreview) -> tuple[WayOut, ...]:
    """What the reader can do about the refusal a preview foresees."""
    return () if preview.refusal is None else ways_out_for(preview.refusal)


def shown_paper_preview(
    preview: PaperPreview, *, in_fields: frozenset[str] = frozenset()
) -> list[ShownLine]:
    """What a paper's preview says, in the order a reader wants it.

    A refusal is worded by `render/refusals.py`, the same sentence the add
    would print, so the preview and the add cannot disagree about why.
    What `in_fields` names is already in its field and is not repeated.
    """
    if not preview.asked.strip():
        return []
    if preview.is_file:
        return [ShownLine(words.PREVIEW_FILE)]
    if preview.recognised is None:
        if preview.is_address:
            return [ShownLine(words.PREVIEW_ADDRESS)]
        return [ShownLine(words.PREVIEW_UNRECOGNISED, "role-muted")]
    if preview.refusal is not None:
        # The window's words; its ways out are `preview_ways`, as controls.
        return [ShownLine(refusal_fact(preview.refusal), "role-warning")]
    # What arXiv named is the card's, drawn by `shown_paper_found`.
    lines: list[ShownLine] = []
    if preview.title is None and preview.looked_up:
        lines.append(ShownLine(words.ARXIV_SILENT, "role-warning"))
    if preview.citekey is not None and "citekey" not in in_fields:
        lines.append(
            ShownLine(words.previewed_citekey(preview.citekey), "role-command")
        )
    return lines


def shown_site_preview(preview: SitePreview, *, probed: bool) -> list[ShownLine]:
    if not preview.address.strip():
        return []
    lines = [
        ShownLine(words.previewed_project(preview.project))
        if preview.project is not None
        else ShownLine(words.PROJECT_UNNAMED, "role-warning"),
        ShownLine(words.previewed_version(preview.version))
        if preview.version is not None
        else ShownLine(words.VERSION_UNNAMED, "role-warning"),
    ]
    if probed:
        lines.append(
            ShownLine(words.DISCOVERY_WORDS[preview.discovery])
            if preview.discovery is not None
            else ShownLine(words.SITE_UNREACHABLE, "role-warning")
        )
    return lines


@dataclass(frozen=True, slots=True)
class ShownCheck:
    line: str
    kind: str
    recognised: bool
    held: bool


def shown_checks(checks: Sequence[LineCheck]) -> list[ShownCheck]:
    return [
        ShownCheck(
            line=check.line,
            kind=words.LINE_KINDS[check.kind],
            recognised=check.kind != "nothing",
            held=check.held is not None,
        )
        for check in checks
    ]


def chooser_target(asked: str) -> str | None:
    """The field a chosen path is written into, if it is one kennis drew."""
    return asked if _TARGET.fullmatch(asked) else None


@dataclass(frozen=True, slots=True)
class ShownEntry:
    name: str
    path: str
    folder: bool
    href: str | None


@dataclass(frozen=True, slots=True)
class ShownListing:
    """One folder of the computer kennis runs on, names only."""

    path: str
    parent_href: str | None
    entries: list[ShownEntry]
    truncated: str | None = None
    problem: str | None = None


def _browse_href(target: str, path: Path, *, folders: bool) -> str:
    chosen = "&folders=1" if folders else ""
    return f"/browse?target={target}{chosen}&path={quote(str(path))}"


def _is_folder(entry: os.DirEntry[str]) -> bool:
    # A broken link or a folder kennis may not stat is listed as a file,
    # which is the one it cannot open, rather than dropped unexplained.
    try:
        return entry.is_dir()
    except OSError:
        return False


def listing_of(asked: str, *, target: str, folders: bool) -> ShownListing:
    """The folders and then the files in one folder, dotfiles left out.

    Starts at the home directory. `os.scandir` reads the directory's
    entries and nothing in them, so the chooser can say what is there
    without opening a file.
    """
    place = Path(asked).expanduser() if asked else Path.home()
    if not place.is_absolute():
        place = Path.home() / place
    parent = (
        _browse_href(target, place.parent, folders=folders)
        if place.parent != place
        else None
    )
    try:
        with os.scandir(place) as listed:
            found = [entry for entry in listed if not entry.name.startswith(".")]
    except OSError:
        return ShownListing(
            path=str(place),
            parent_href=parent,
            entries=[],
            problem=words.not_a_folder(str(place)),
        )

    sorted_entries = sorted(
        ((entry.name, _is_folder(entry)) for entry in found),
        key=lambda pair: (not pair[1], pair[0].casefold()),
    )
    shown = sorted_entries[: words.CHOOSER_SHOWN_AT_MOST]
    entries = [
        ShownEntry(
            name=name,
            path=str(place / name),
            folder=folder,
            href=_browse_href(target, place / name, folders=folders)
            if folder
            else None,
        )
        for name, folder in shown
    ]
    return ShownListing(
        path=str(place),
        parent_href=parent,
        entries=entries,
        truncated=words.chooser_truncated(len(shown), len(sorted_entries))
        if len(shown) < len(sorted_entries)
        else None,
    )


__all__ = [
    "ADD_KINDS",
    "FIRST_BLOCKS",
    "FIXED_COLLECTIONS",
    "PLACE_FIELDS",
    "ShownCheck",
    "ShownChoice",
    "ShownEntry",
    "ShownField",
    "ShownFound",
    "ShownLine",
    "ShownListing",
    "ShownTab",
    "add_fields",
    "add_kind",
    "add_tabs",
    "chooser_target",
    "destination_of",
    "filled",
    "listing_of",
    "paper_prefill",
    "shown_checks",
    "shown_paper_found",
    "shown_paper_preview",
    "shown_site_preview",
]
