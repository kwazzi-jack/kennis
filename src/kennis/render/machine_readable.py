"""Documents for a program to read, rather than lines for a person.

A rendering like the rest of `render/`, for a reader that parses instead of
reads. The models carry facts and never a sentence built from them: a
consumer that wanted the holdings line can compose it from `name` and
`description`, and one that did not is not made to split it apart.

`format_version` is raised when a field is removed or changes meaning, so a
consumer can refuse a document it does not know rather than misread it.
Adding a field does not raise it.
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, ConfigDict

from kennis.engine.pack.installed import InstalledPack, PackListing

PACK_LIST_FORMAT_VERSION: Final = 1

_FORBID = ConfigDict(extra="forbid", frozen=True)


class ListedPack(BaseModel):
    """One installed pack.

    `name` and `description` are None when the copied declaration will not
    parse; the pack is still installed and still holds files, so it is
    listed by what the store knows without it.
    """

    model_config = _FORBID

    id: str
    version: str
    files: int
    verified: bool
    name: str | None
    description: str | None


class PackListDocument(BaseModel):
    """What `kennis pack list --json` prints."""

    model_config = _FORBID

    format_version: int
    packs: list[ListedPack]
    unreadable: list[str]


def listed_pack(installed: InstalledPack) -> ListedPack:
    """One pack's facts, as the document carries them."""
    state = installed.state
    identity = installed.declaration.pack if installed.declaration else None
    return ListedPack(
        id=state.pack_id,
        version=state.pack_version,
        files=len(state.files),
        verified=installed.verified,
        name=identity.name if identity else None,
        description=identity.description if identity else None,
    )


def pack_list_document(listing: PackListing) -> PackListDocument:
    """The listing as a document, packs ordered by id as the rows are."""
    ordered = sorted(listing.packs, key=lambda one: one.state.pack_id)
    return PackListDocument(
        format_version=PACK_LIST_FORMAT_VERSION,
        packs=[listed_pack(installed) for installed in ordered],
        unreadable=list(listing.unreadable),
    )
