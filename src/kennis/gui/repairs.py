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

**Only repairs kennis can actually perform.** A paper whose text sits
behind a publisher needs a file that is not on this machine, and the
interface has no upload, so it gets the sentence and no button. An
offer that cannot work is worse than none.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from urllib.parse import quote

from kennis.engine.refusals import (
    AmbiguousIdentity,
    BibliographyIncomplete,
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

    @property
    def candidates(self) -> tuple[tuple[str, str | None], ...]:
        """Each choice and the page that says which paper it names."""
        return tuple(
            (choice, candidate_address(self.kind, choice) if self.kind else None)
            for choice in self.choices
        )


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


__all__ = ["Repair", "candidate_address", "repairs_for"]
