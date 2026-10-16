"""A refusal as a form the reader can submit.

Unit 9e made a refusal carry its facts as fields precisely so that
this could exist: `NoIdentity` knows the path, `AmbiguousIdentity`
knows every value it found, and a form can be built from either
without parsing a sentence.

**A second exhaustive `match`, and that is the design rather than
duplication.** `render/refusals.py` turns a refusal into words and a
command; this turns one into a control. Each front end renders for
itself, and mypy makes both of them answer when a fourteenth refusal
is added.

**Only repairs kennis can actually perform.** An offer that cannot
work is worse than none. A paper whose text sits behind a publisher
needs a file that is not on this machine; that was a sentence and no
button while the window had no upload. The Paper tab's PDF way in
(11d) is one, so such a paper is now a way out: its page, to download
it from, and the Add dialog opened on that way in with the identifier
filled - two links, because the download is the reader's to do.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from urllib.parse import quote, urlencode

from kennis.engine.refusals import (
    AmbiguousIdentity,
    BibliographyIncomplete,
    IdentityMismatch,
    KennisOwn,
    NoArxivText,
    NoIdentity,
    NoPublisherText,
    NotAnInput,
    NothingConverted,
    Quoted,
    Refusal,
    SameContent,
    SamePage,
    SamePaper,
    SymlinkSkipped,
    UnsupportedFormat,
)
from kennis.render.refusals import paper_page

# The labels of the ways out, beside the repairs' own: `words` imports
# `pages`, which imports this module.
OPEN_THE_PAPER: Final = "Open the paper's page"
ADD_FROM_A_PDF: Final = "Add it from a PDF"
SET_UNPAYWALL: Final = "Set an email for Unpaywall"
ADD_ACCEPTED: Final = "Add the accepted manuscript"


@dataclass(frozen=True, slots=True)
class Repair:
    """One thing the reader can do about a refusal, as a filled form.

    `choices` is empty for a repair that needs no decision and holds
    every candidate for one that does. A form with choices renders one
    radio per choice and sends the chosen value as `identifier`; kennis
    never picks for the reader, because for an ambiguous first page
    picking is deciding which paper this is.
    """

    label: str
    collection: str
    identifiers: str
    choices: tuple[str, ...] = ()
    # The kind every choice is, so each can link to its registry's page
    # for the reader to decide by (11e).
    kind: str | None = None
    # Any other field the add needs, posted as it is: an accepted
    # manuscript is added by the Paper tab's PDF way in, with the
    # identifier already established.
    fields: tuple[tuple[str, str], ...] = ()

    @property
    def candidates(self) -> tuple[tuple[str, str | None], ...]:
        """Each choice and the page that says which paper it names."""
        return tuple(
            (choice, candidate_address(self.kind, choice) if self.kind else None)
            for choice in self.choices
        )


@dataclass(frozen=True, slots=True)
class WayOut:
    """A way out that is a place to go rather than a form to post.

    `outside` is a page beyond kennis, opened in a tab that cannot reach
    back and is not told where the reader came from; otherwise it is a
    route of this window, opened in the dialog.
    """

    label: str
    href: str
    outside: bool = False


def ways_out_for(refusal: Refusal) -> tuple[WayOut, ...]:
    """Every link the interface can offer for one refusal."""
    match refusal:
        case NoPublisherText(
            kind=kind, value=value, asked_unpaywall=asked, accepted_manuscript=accepted
        ):
            ways = [
                WayOut(OPEN_THE_PAPER, paper_page(kind, value), outside=True),
                _from_a_pdf(value),
            ]
            if kind == "doi" and not asked and accepted is None:
                ways.append(WayOut(SET_UNPAYWALL, _UNPAYWALL_SETTING))
            return tuple(ways)
        case NoArxivText(arxiv_id=arxiv_id):
            return (_from_a_pdf(arxiv_id),)
        case IdentityMismatch(stated=stated):
            return (_from_a_pdf(stated),)
        case (
            Quoted()
            | SameContent()
            | SamePaper()
            | SamePage()
            | NoIdentity()
            | AmbiguousIdentity()
            | NotAnInput()
            | BibliographyIncomplete()
            | NothingConverted()
            | SymlinkSkipped()
            | KennisOwn()
            | UnsupportedFormat()
        ):
            return ()


# The setting's row on the settings page, by the id its field carries.
_UNPAYWALL_SETTING: Final = "/settings#setting-literature.unpaywall_email"


def _from_a_pdf(identifier: str) -> WayOut:
    """The Add dialog on Paper, PDF chosen, the identifier filled."""
    query = urlencode({"kind": "paper", "source": "pdf", "identifier": identifier})
    return WayOut(ADD_FROM_A_PDF, f"/add?{query}")


def repairs_for(refusal: Refusal) -> tuple[Repair, ...]:
    """Every repair the interface can offer for one refusal."""
    match refusal:
        case NoIdentity(named=named):
            # Notes is a real answer, not a consolation prize: notes
            # have no natural key by design, so a document with no
            # bibliographic identity is exactly what that collection
            # is for.
            return (_as_a_note(named),)
        case AmbiguousIdentity(named=named, kind=kind, values=values):
            return (
                Repair(
                    label="Use this identifier",
                    collection="literature",
                    identifiers=named,
                    choices=values,
                    kind=kind,
                ),
                _as_a_note(named),
            )
        case IdentityMismatch(named=named, kind=kind, found=found):
            return (
                Repair(
                    label="Use the identifier it names",
                    collection="literature",
                    identifiers=named,
                    choices=found,
                    kind=kind,
                ),
            )
        case NoPublisherText(value=value, accepted_manuscript=str(accepted)):
            return (
                Repair(
                    label=ADD_ACCEPTED,
                    collection="literature",
                    identifiers="",
                    fields=(
                        ("kind", "paper"),
                        ("source", "pdf"),
                        ("pdf", accepted),
                        ("identifier", value),
                    ),
                ),
            )
        case (
            Quoted()
            | SameContent()
            | SamePaper()
            | SamePage()
            | NoPublisherText()
            | NoArxivText()
            | NotAnInput()
            | BibliographyIncomplete()
            | NothingConverted()
            | SymlinkSkipped()
            | KennisOwn()
            | UnsupportedFormat()
        ):
            return ()


# Where each kind of identifier is answered by its own registry. The
# public page for the paper, not an API: the reader is deciding which
# paper this is, and that is decided by reading its title and authors.
_REGISTRY_PAGES: Final[dict[str, str]] = {
    "arxiv": "https://arxiv.org/abs/{}",
    "doi": "https://doi.org/{}",
    "bibcode": "https://ui.adsabs.harvard.edu/abs/{}/abstract",
}


def candidate_address(kind: str, value: str) -> str:
    """The registry's page for one candidate identifier.

    Composed here rather than in a template, because a template choosing
    by kind would be a template deciding where a paper lives (#332). A DOI
    may hold `#`, `?` and brackets, which would end or reshape a path, so
    the value is quoted with only its own slashes kept.
    """
    return _REGISTRY_PAGES[kind].format(quote(value, safe="/"))


def _as_a_note(named: str) -> Repair:
    return Repair(
        label="Add it to notes instead", collection="notes", identifiers=named
    )


__all__ = [
    "ADD_ACCEPTED",
    "ADD_FROM_A_PDF",
    "OPEN_THE_PAPER",
    "SET_UNPAYWALL",
    "Repair",
    "WayOut",
    "candidate_address",
    "repairs_for",
    "ways_out_for",
]
