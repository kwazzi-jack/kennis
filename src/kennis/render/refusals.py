"""The words for each way an item can be refused, and the way out.

The counterpart of `render/diagnostics.py`, for the other union the
engine reports. `describe_refusal` is exhaustive over `Refusal` by
construction: the `match` has an arm per member and no fall-through, so
a fourteenth refusal added without a sentence is a type error rather
than a blank line in front of a user.

**The remedy is separate from the sentence.** `engine/corpus/add.py`
used to build both together - "Settle it with --identifier, or add it
as a note instead: kennis corpus add -n '<path>'" - and a command
buried mid-sentence can only be offered by a terminal, and only to
someone who will retype it. `remedies_for_refusal` returns the
commands on their own, so the command line can print them and a
graphical interface can make each one a button. It returns only
commands that run exactly as written; where the remedy needs a file
only the user can supply, it returns nothing and the sentence says what
is needed.
"""

from __future__ import annotations

from shlex import quote

from kennis.engine.refusals import (
    AmbiguousIdentity,
    BibliographyIncomplete,
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
from kennis.render.words import count_of


def describe_refusal(refusal: Refusal) -> str:
    """One line for one refusal, with no trailing stop.

    No trailing stop and no leading capital, for the same reason
    `describe_diagnostic` has neither: a front end decides where this
    sits, and a sentence that punctuates itself cannot be embedded in
    another.
    """
    match refusal:
        case Quoted(text=text):
            return text
        case SameContent():
            return "identical content is already in this collection"
        case SamePaper():
            return "this paper is already in this collection"
        case SamePage(project=project, key=key):
            return f"already held as {project}/{key}"
        case NoIdentity():
            # Notes is a real answer here, not a consolation prize:
            # notes have no natural key by design, so a document with no
            # bibliographic identity is exactly what that collection is
            # for.
            return (
                "no arXiv id, DOI or ADS bibcode found on its first page, so "
                "it has no bibliographic identity and cannot go to "
                "literature; supply one with --identifier, or add it as a "
                "note instead"
            )
        case AmbiguousIdentity(kind=kind, values=values):
            offered = ", ".join(values)
            return (
                f"its first page offers more than one {kind} identifier "
                f"({offered}) and kennis cannot tell which names the paper; "
                f"settle it with --identifier, or add it as a note instead"
            )
        case NoPublisherText(kind=kind, value=value):
            # Deliberately not the wording of `NoIdentity`. That one
            # means kennis does not know *what* the paper is and notes is
            # the honest home for it; this one means the paper is
            # identified perfectly well and its text is elsewhere.
            # Offering notes here would file a known paper in the wrong
            # collection.
            named = "a DOI" if kind == "doi" else "an ADS bibcode"
            return (
                f"{named} names a publisher's copy, which kennis cannot "
                f"fetch; supply the document with -l and --identifier "
                f"'{value}'"
            )
        case NoArxivText(named=named, arxiv_id=arxiv_id, declined=declined):
            said = f" ({declined})" if declined else ""
            return (
                f"arXiv has no rendering of '{named}' to fetch{said}; supply "
                f"the document with -l and --identifier '{arxiv_id}'"
            )
        case NotAnInput(identifier=identifier):
            return (
                f"'{identifier}' is not an existing file, a URL, an arXiv "
                f"identifier, a DOI or an ADS bibcode"
            )
        case BibliographyIncomplete(name=name, citekeys=citekeys):
            listed = ", ".join(citekeys)
            return (
                f"{count_of(len(citekeys), 'entry', 'entries')} of '{name}' "
                f"name no document and no arXiv identifier ({listed}), so "
                f"nothing from it was added; give each one a `file =` field, "
                f"or remove it"
            )
        case NothingConverted(name=name, problem=problem):
            if problem:
                return f"could not convert '{name}': {problem}"
            return (
                f"no markdown was produced for '{name}'; the file may be "
                f"empty, encrypted, or an unsupported variant"
            )
        case SymlinkSkipped():
            return "a symbolic link, which the walk does not follow"
        case UnsupportedFormat(suffix=suffix):
            return f"unsupported file type '{suffix}'"


def remedies_for_refusal(refusal: Refusal) -> tuple[str, ...]:
    """The commands that would resolve it, each runnable as written.

    Empty for a refusal with no command-shaped remedy, which is most of
    them: a duplicate needs nothing done, and a paper whose text sits
    behind a publisher needs a file kennis cannot name. Rules.md 4.4
    forbids printing an instruction that fails, and a command with
    `<file>` in it fails.
    """
    match refusal:
        case NoIdentity(named=named) | AmbiguousIdentity(named=named):
            # The unambiguous half of the two ways out. Offering
            # `--identifier` as a command would mean choosing a value on
            # the user's behalf, and for an ambiguous page that is
            # choosing which paper this is.
            return (f"kennis corpus add -n {quote(named)}",)
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
            | UnsupportedFormat()
        ):
            return ()


__all__ = ["describe_refusal", "remedies_for_refusal"]
