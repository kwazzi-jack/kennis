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

import os
import shlex
import subprocess
from typing import Final
from urllib.parse import quote

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
from kennis.render.words import count_of


def quoted_for_posix(argument: str) -> str:
    """One argument as a POSIX shell reads it."""
    return shlex.quote(argument)


def quoted_for_windows(argument: str) -> str:
    """One argument as cmd.exe and PowerShell both read it.

    `list2cmdline` double-quotes only when the argument needs it. A
    single-quoted path, which is what `shlex.quote` produces for any
    path containing a backslash, is not quoting to cmd.exe at all.
    """
    return subprocess.list2cmdline([argument])


def quoted_for_this_shell(argument: str) -> str:
    """One argument quoted so the remedy runs as printed on this platform."""
    if os.name == "nt":
        return quoted_for_windows(argument)
    return quoted_for_posix(argument)


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
                f"choose one, or add it as a note instead"
            )
        case IdentityMismatch(named=named, kind=kind, stated=stated, found=found):
            offered = ", ".join(f"'{value}'" for value in found)
            return (
                f"the document at '{named}' names the {kind} {offered} and not "
                f"'{stated}', so it may not be the paper you meant; choose the "
                f"identifier it names, or if it is the paper, download it and "
                f"supply the document with -l and --identifier '{stated}'"
            )
        case NoPublisherText(
            kind=kind,
            value=value,
            asked_unpaywall=asked,
            accepted_manuscript=accepted,
        ):
            # Deliberately not the wording of `NoIdentity`. That one
            # means kennis does not know *what* the paper is and notes is
            # the honest home for it; this one means the paper is
            # identified perfectly well and its text is elsewhere.
            # Offering notes here would file a known paper in the wrong
            # collection.
            return _no_publisher_text(kind, value, asked=asked, accepted=accepted)
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
        case KennisOwn():
            return "kennis's own files, which are never added to the corpus"
        case UnsupportedFormat(suffix=suffix):
            return f"unsupported file type '{suffix}'"


def refusal_fact(refusal: Refusal) -> str:
    """What happened, without the terminal's way out.

    `describe_refusal` ends several sentences with what to type - `-l`,
    `--identifier`, "supply that address the same way" - which a reader
    of the window has nowhere to type. The window says this instead and
    offers each way out as a control (`gui/repairs.py`). A test holds
    every refusal to naming no flag here, and to stating the same fact
    as the terminal's sentence begins with.
    """
    match refusal:
        case NoIdentity():
            return (
                "no arXiv id, DOI or ADS bibcode found on its first page, so "
                "it has no bibliographic identity and cannot go to literature"
            )
        case IdentityMismatch(named=named, kind=kind, stated=stated, found=found):
            offered = ", ".join(f"'{value}'" for value in found)
            return (
                f"the document at '{named}' names the {kind} {offered} and not "
                f"'{stated}', so it may not be the paper you meant"
            )
        case NoPublisherText(
            kind=kind, value=value, asked_unpaywall=asked, accepted_manuscript=accepted
        ):
            said = _no_publisher_fact(kind, value, asked=asked)
            if accepted is not None:
                said += (
                    f". The authors' accepted manuscript is open at {accepted} "
                    f"and may differ from the published paper"
                )
            return said
        case NoArxivText(named=named, declined=declined):
            said = f" ({declined})" if declined else ""
            return f"arXiv has no rendering of '{named}' to fetch{said}"
        case (
            Quoted()
            | SameContent()
            | SamePaper()
            | SamePage()
            | AmbiguousIdentity()
            | NotAnInput()
            | BibliographyIncomplete()
            | NothingConverted()
            | SymlinkSkipped()
            | KennisOwn()
            | UnsupportedFormat()
        ):
            # Nothing in these to type: the sentence is the fact.
            return describe_refusal(refusal)


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
            return (f"kennis corpus add -n {quoted_for_this_shell(named)}",)
        case (
            Quoted()
            | SameContent()
            | SamePaper()
            | SamePage()
            | IdentityMismatch()
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


def choices_for_refusal(refusal: Refusal) -> tuple[str, ...]:
    """One command per candidate, for the reader to choose among (#434).

    Not a remedy: `remedies_for_refusal` holds what is right whichever
    way the reader decides, and a single `--identifier` there would be
    kennis deciding which paper this is. Every candidate, in the page's
    order, is the terminal's form of the window's radios with none
    checked; each runs as printed.
    """
    match refusal:
        case AmbiguousIdentity(named=named, values=values):
            return tuple(
                f"kennis corpus add --identifier {quoted_for_this_shell(value)} "
                f"{quoted_for_this_shell(named)}"
                for value in values
            )
        case IdentityMismatch(named=named, found=found):
            return tuple(
                f"kennis corpus add -l --identifier {quoted_for_this_shell(value)} "
                f"{quoted_for_this_shell(named)}"
                for value in found
            )
        case _:
            return ()


# Where a reader opens a paper to download it, by the kind of identifier.
_PAPER_PAGES: Final[dict[str, str]] = {
    "doi": "https://doi.org/{}",
    "bibcode": "https://ui.adsabs.harvard.edu/abs/{}/abstract",
}


def paper_page(kind: str, value: str) -> str:
    """Where a reader opens a paper to download it.

    The value is quoted with only its own slashes kept: a DOI may hold
    `#` or `?`, which would end or reshape the address.
    """
    return _PAPER_PAGES.get(kind, "{}").format(quote(value, safe="/"))


def _no_publisher_fact(kind: str, value: str, *, asked: bool) -> str:
    named = "the DOI" if kind == "doi" else "the ADS bibcode"
    return f"kennis has no copy of {named} '{value}' it can fetch" + (
        ": Unpaywall knows no open copy of the published paper" if asked else ""
    )


def _no_publisher_text(
    kind: str, value: str, *, asked: bool, accepted: str | None
) -> str:
    """A paper kennis has no copy of, with where to get one and how to add
    it - and, where there is one, the manuscript it would not take unasked.
    """
    page = paper_page(kind, value)
    said = (
        _no_publisher_fact(kind, value, asked=asked)
        + f"; download it from {page} and supply the document with -l and "
        f"--identifier '{value}'"
    )
    if accepted is not None:
        said += (
            f". The authors' accepted manuscript is open at {accepted} and may "
            f"differ from the published paper; if it will do, supply that "
            f"address the same way"
        )
    elif kind == "doi" and not asked:
        said += (
            ". Or set literature.unpaywall_email, and kennis will look for a "
            "free, legal copy"
        )
    return said


__all__ = [
    "choices_for_refusal",
    "describe_refusal",
    "paper_page",
    "refusal_fact",
    "remedies_for_refusal",
]
