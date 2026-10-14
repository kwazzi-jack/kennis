"""What an add would do, said before it is done.

**A preview is a promise about the add, so it asks the add's own
questions.** The input goes through `identifier_if_reference`, which is
what an add's argument goes through; a held paper is found in
`Uniqueness.of(...).identities`, which is what the add's duplicate check
reads; the citekey is `derive_citekey` and `unique_citekey` against the
citekeys held, which is what `_citekey_for` calls; and a paper the add
would refuse carries the refusal the add would raise. A preview built on
its own reasoning would drift from the add one fix at a time.

**It fetches only what the add would fetch, and only once the input is
whole.** An arXiv identifier is looked up on arXiv, because the add looks
it up; a DOI and a bibcode are not, because the add does not - arXiv's
`doi` field is the journal's, and resolving a DOI through it once stored
the preprint of what was asked for. Nothing is requested for a partial
input, so typing an identifier does not send each keystroke to a third
party, and nothing for a paper already held.

**A site is named locally and probed only when asked.** The probe is
several requests to someone else's server; a preview that ran it on
every keystroke would be a crawler with a text box.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx

from kennis.engine.corpus.add import Uniqueness
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.intake import looks_like_url
from kennis.engine.docs.discover import discovery_mode
from kennis.engine.docs.sites import project_name_from_url
from kennis.engine.errors import InputError
from kennis.engine.literature.citekeys import derive_citekey, unique_citekey
from kennis.engine.literature.identifiers import (
    PaperIdentifier,
    identifier_if_reference,
)
from kennis.engine.literature.metadata import lookup_arxiv_metadata
from kennis.engine.refusals import NoPublisherText, SamePaper


@dataclass(frozen=True, slots=True)
class PaperPreview:
    """What adding `asked` to a literature collection would come to.

    `recognised` is None for anything that is not a whole identifier,
    which includes a file (`is_file`) and an address. `title`, `authors`
    and `year` are arXiv's and are None when arXiv was not asked or did
    not answer; `looked_up` says which. `refusal` is the refusal the add
    would raise, foreseen.
    """

    asked: str
    recognised: PaperIdentifier | None = None
    is_file: bool = False
    is_address: bool = False
    looked_up: bool = False
    title: str | None = None
    authors: str | None = None
    year: str | None = None
    citekey: str | None = None
    held_title: str | None = None
    refusal: SamePaper | NoPublisherText | None = None


def preview_paper(
    collection: Collection,
    asked: str,
    *,
    citekey: str | None = None,
    title: str | None = None,
    client: httpx.Client | None = None,
) -> PaperPreview:
    """What an add of one paper would do, fetching only what it would."""
    candidate = asked.strip()
    if not candidate:
        return PaperPreview(asked=asked)
    if Path(candidate).expanduser().is_file():
        return PaperPreview(asked=asked, is_file=True)
    recognised = identifier_if_reference(candidate)
    if recognised is None:
        return PaperPreview(asked=asked, is_address=looks_like_url(candidate))

    record = Uniqueness.of(collection)
    held = record.identities.get(recognised.value.lower())
    if held is not None:
        return PaperPreview(
            asked=asked,
            recognised=recognised,
            held_title=record.titles.get(held),
            refusal=SamePaper(document_id=held),
        )
    if recognised.kind != "arxiv":
        # The add records a DOI or a bibcode as given and has no text to
        # store for one: a publisher's copy needs a browser session
        # kennis does not have. So the add would refuse it unless a file
        # comes with it, and the preview says so now.
        return PaperPreview(
            asked=asked,
            recognised=recognised,
            citekey=citekey,
            refusal=NoPublisherText(kind=recognised.kind, value=recognised.value),
        )

    metadata = lookup_arxiv_metadata(recognised.value, client=client)
    if metadata is None:
        return PaperPreview(
            asked=asked, recognised=recognised, looked_up=True, citekey=citekey
        )
    named = title or metadata.title
    base = citekey or derive_citekey(
        authors=metadata.authors, year=metadata.year, title=named
    )
    return PaperPreview(
        asked=asked,
        recognised=recognised,
        looked_up=True,
        title=metadata.title,
        authors=metadata.authors,
        year=metadata.year,
        citekey=unique_citekey(base, record.citekeys),
    )


@dataclass(frozen=True, slots=True)
class SitePreview:
    """What adding a documentation site would be filed as, and found by.

    `project` is None when no name can be made from the address, which
    the add would refuse. `discovery` is None until the site is probed.
    """

    address: str
    project: str | None
    discovery: str | None = None


def preview_site(
    address: str,
    *,
    project: str | None = None,
    probe: bool = False,
    client: httpx.Client | None = None,
) -> SitePreview:
    """The project a site would be filed under, and, when asked, how its
    pages would be found."""
    candidate = address.strip()
    named = project
    if named is None and looks_like_url(candidate):
        try:
            named = project_name_from_url(candidate)
        except InputError:
            named = None
    if not probe or not looks_like_url(candidate):
        return SitePreview(address=address, project=named)
    owned = client is None
    asking = client if client is not None else httpx.Client(follow_redirects=True)
    try:
        mode = discovery_mode(asking, candidate)
    except httpx.HTTPError:
        mode = None
    finally:
        if owned:
            asking.close()
    return SitePreview(address=address, project=named, discovery=mode)


type LineKind = Literal[
    "arxiv", "doi", "bibcode", "address", "file", "folder", "nothing"
]


@dataclass(frozen=True, slots=True)
class LineCheck:
    """One line of a group, as its own tab would recognise it.

    Local only: twenty lines would be twenty requests to arXiv for a
    check, so a line is recognised and looked for among what is held,
    and the lookup waits for the add.
    """

    line: str
    kind: LineKind
    held: str | None = None


def check_lines(collection: Collection, lines: Sequence[str]) -> list[LineCheck]:
    """Each non-empty line: what it is, and the document holding it if
    one already does."""
    record = Uniqueness.of(collection)
    checks: list[LineCheck] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        path = Path(line).expanduser()
        if path.is_dir():
            checks.append(LineCheck(line=line, kind="folder"))
            continue
        if path.is_file():
            checks.append(LineCheck(line=line, kind="file"))
            continue
        recognised = identifier_if_reference(line)
        if recognised is not None:
            checks.append(
                LineCheck(
                    line=line,
                    kind=recognised.kind,
                    held=record.identities.get(recognised.value.lower()),
                )
            )
            continue
        if looks_like_url(line):
            checks.append(LineCheck(line=line, kind="address"))
            continue
        checks.append(LineCheck(line=line, kind="nothing"))
    return checks


__all__ = [
    "LineCheck",
    "LineKind",
    "PaperPreview",
    "SitePreview",
    "check_lines",
    "preview_paper",
    "preview_site",
]
