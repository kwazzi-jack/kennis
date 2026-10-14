"""Why one item was not added, as data rather than as a sentence.

**The engine names the refusal; it does not phrase it.** This is the
treatment concern #285 gave `Diagnostic.detail`, applied to the other
place the engine was composing English: `AddOutcome.reason` and
`ItemFinished.reason` were strings built in `engine/corpus/add.py`, and
several of them had a command line embedded mid-sentence - "Settle it
with --identifier, or add it as a note instead: kennis corpus add -n
'<path>'". A graphical interface cannot offer that as a button without
parsing the sentence back apart, which is the work this union exists to
make unnecessary.

Each member carries the facts a caller would need to *act*: which
identifiers were found, which citekeys are incomplete, which document
the new one duplicates. `render/refusals.py` turns one into words, and
returns the remedy separately as a command string.

`code` is the stable name, for anything that has to serialise: an MCP
client cannot match on a Python class. It is also what a reader greps
for across runs of the log.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True, slots=True)
class Quoted:
    """Text kennis is repeating rather than composing.

    The escape hatch, and a narrow one. It holds a `KennisError` message,
    an exception's own words, or a verdict name produced elsewhere in the
    engine and passed through - the third of the three standing
    exceptions to the phrasing rule. It must never hold a sentence
    written for a user at the point of refusal; that is what the other
    members are for.
    """

    code: ClassVar[str] = "quoted"
    text: str


@dataclass(frozen=True, slots=True)
class SameContent:
    """A document whose bytes are already held, under another name."""

    code: ClassVar[str] = "same-content"
    document_id: str


@dataclass(frozen=True, slots=True)
class SamePaper:
    """A paper already held under the same bibliographic identity.

    Distinct from `SameContent` although both are a duplicate: this one
    matched on arXiv id, DOI or bibcode, so the *document* may well
    differ - a published version against a preprint - and saying
    "identical content" about it would be false.
    """

    code: ClassVar[str] = "same-paper"
    document_id: str


@dataclass(frozen=True, slots=True)
class SamePage:
    """A documentation page already held under the same natural key."""

    code: ClassVar[str] = "same-page"
    project: str
    key: str


@dataclass(frozen=True, slots=True)
class NoIdentity:
    """A paper whose first page states no arXiv id, DOI or bibcode.

    `named` is what to put in the remedy - the path where there is one,
    the identifier otherwise - so a front end can offer both ways out
    without reconstructing them.
    """

    code: ClassVar[str] = "no-identity"
    named: str


@dataclass(frozen=True, slots=True)
class AmbiguousIdentity:
    """A first page offering several identifiers of the same kind.

    Every value is carried, not the count: the remedy is to pick one, and
    a chooser cannot be built from "more than one".
    """

    code: ClassVar[str] = "ambiguous-identity"
    named: str
    kind: str
    values: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IdentityMismatch:
    """A fetched document whose first page names a different paper.

    The identifier the reader gave is taken as fact, so kennis does not
    swap it for the one the page shows; it asks. Every value found is
    carried, so the reader can choose one of them instead.
    """

    code: ClassVar[str] = "identity-mismatch"
    named: str
    kind: str
    stated: str
    found: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NoPublisherText:
    """An identified paper whose text sits behind a publisher.

    kennis does not fetch from publishers, so the remedy is a local file
    plus the identifier already established - which is why both the kind
    and the value are here.
    """

    code: ClassVar[str] = "no-publisher-text"
    kind: str
    value: str
    # Whether Unpaywall was asked for an open copy and knew of none. When it
    # was not, setting the reader's email for it is one more remedy.
    asked_unpaywall: bool = False
    # The authors' accepted manuscript, when that is the only open copy.
    # Offered rather than fetched: it may differ from the published paper
    # the identifier names, so whether it will do is the reader's call.
    accepted_manuscript: str | None = None


@dataclass(frozen=True, slots=True)
class NoArxivText:
    """An arXiv paper with no rendering to fetch.

    `declined` is what arXiv said, when it said anything, and is None
    otherwise: a throttled batch and a batch nobody preprinted fail
    identically unless this distinguishes them.
    """

    code: ClassVar[str] = "no-arxiv-text"
    named: str
    arxiv_id: str
    declined: str | None = None


@dataclass(frozen=True, slots=True)
class NotAnInput:
    """An identifier that names nothing kennis can add."""

    code: ClassVar[str] = "not-an-input"
    identifier: str


@dataclass(frozen=True, slots=True)
class BibliographyIncomplete:
    """A bibliography with entries that can produce no document.

    Every incomplete citekey is carried, because a bibliography is
    accepted or refused whole: naming one would have the user fix it and
    meet the next.
    """

    code: ClassVar[str] = "bibliography-incomplete"
    name: str
    citekeys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NothingConverted:
    """A file the converter read and produced no markdown from.

    `problem` is the converter's own account where it gave one.
    """

    code: ClassVar[str] = "nothing-converted"
    name: str
    problem: str | None = None


@dataclass(frozen=True, slots=True)
class SymlinkSkipped:
    """A symbolic link met while walking a directory, left alone."""

    code: ClassVar[str] = "symlink-skipped"


@dataclass(frozen=True, slots=True)
class KennisOwn:
    """A directory kennis writes its own files into, met while walking.

    The corpus, the configuration, the state or the log: adding one would
    copy the corpus into itself, or make API keys and the reader's search
    history documents an agent can read.
    """

    code: ClassVar[str] = "kennis-own"


@dataclass(frozen=True, slots=True)
class UnsupportedFormat:
    """A file whose extension names no format kennis can convert."""

    code: ClassVar[str] = "unsupported-format"
    suffix: str


# Every way an item can end as something other than written. A union
# rather than a string, so a front end switches on the refusal and
# supplies its own words - and so `kennis gui` can build a form from the
# fields rather than from a sentence. mypy tells whoever adds a
# fourteenth that nothing renders it yet.
type Refusal = (
    Quoted
    | SameContent
    | SamePaper
    | SamePage
    | NoIdentity
    | AmbiguousIdentity
    | IdentityMismatch
    | NoPublisherText
    | NoArxivText
    | NotAnInput
    | BibliographyIncomplete
    | NothingConverted
    | SymlinkSkipped
    | KennisOwn
    | UnsupportedFormat
)


__all__ = [
    "AmbiguousIdentity",
    "BibliographyIncomplete",
    "IdentityMismatch",
    "KennisOwn",
    "NoArxivText",
    "NoIdentity",
    "NoPublisherText",
    "NotAnInput",
    "NothingConverted",
    "Quoted",
    "Refusal",
    "SameContent",
    "SamePage",
    "SamePaper",
    "SymlinkSkipped",
    "UnsupportedFormat",
]
