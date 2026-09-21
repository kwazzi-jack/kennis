"""Recognising the many ways a paper can be named.

A paper arrives as `2409.19750`, `arXiv:2409.19750`, `2409.19750v1.pdf`, an
abs or pdf URL, a pre-2007 `astro-ph/0601234`, a DOI in one of several
spellings, or an ADS bibcode. Passing whatever string was typed straight to an
API means only the bare form works, and the rest fail with "no entry found" -
which reads like the paper does not exist rather than like the identifier was
not understood.

**Nothing here touches the network.** `metadata` is the module that does, and
the split is what lets every function below be tested with no injected client
at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal
from urllib.parse import urlparse

# Post-2007 arXiv identifiers: YYMM.NNNNN, four or five digits after the dot,
# with an optional version suffix.
_MODERN_ARXIV: Final = re.compile(r"(?<!\d)(\d{4}\.\d{4,5})(v\d+)?(?!\d)")

# Pre-2007: archive[.subject-class]/YYMMNNN, e.g. astro-ph/0601234.
_LEGACY_ARXIV: Final = re.compile(
    r"(?<![\w/])([a-z-]+(?:\.[A-Za-z]{2})?/\d{7})(v\d+)?(?![\w])"
)

# A DOI is "10." followed by a registrant code, a slash, and a suffix that
# runs to the end of the token.
_DOI: Final = re.compile(r"(10\.\d{4,9}/[^\s\"'<>]+)")

# An ADS bibcode: 19 characters, fixed-width, dot-padded. It is the
# astronomy-native identifier and the answer for anything older than arXiv - a
# 1974 paper has no preprint identifier and often no DOI either, but it always
# has a bibcode, printed on the scan by ADS itself.
#
#     YYYY  JJJJJ  VVVV  M  PPPP  A
#     year  journal volume qualifier page first-author initial
#     1974  A&AS.  ..15  .  .417  H
#
# The qualifier stays letters-or-dot rather than allowing digits: that costs
# only the `2020arXiv200101234S` eprint form, which carries an arXiv identifier
# worth matching instead, and it keeps the pattern from matching arbitrary
# 19-character runs of text. Bounded by a lookaround rather than `\b`, since a
# bibcode both contains and may abut a dot - which also means a bibcode at the
# end of a sentence, with a full stop against it, is not matched. That is the
# safe direction to fail in.
_ADS_BIBCODE: Final = re.compile(
    r"(?<![\w.])((?:19|20)\d{2}[A-Za-z0-9&.]{5}[0-9.]{4}[A-Za-z.][0-9.]{4}[A-Za-z])"
    r"(?![\w.])"
)

_ARXIV_HOSTS: Final = (
    "arxiv.org",
    "ar5iv.labs.arxiv.org",
    "ar5iv.org",
    "browse.arxiv.org",
)


def normalize_arxiv_id(identifier: str) -> str | None:
    """Extract a bare, unversioned arXiv identifier from any of its spellings.

    **Searches** rather than matching, which is right when reading an
    identifier out of a paper's own text and wrong for something a user typed
    - see `arxiv_id_if_reference`.

    The version suffix is deliberately dropped. The corpus tracks a paper, not
    a snapshot of one, and keeping the version would make `2409.19750v1` and
    `v2` look like two different documents to duplicate detection while
    fetching near-identical text twice.
    """
    candidate = identifier.strip()
    if not candidate:
        return None

    # A URL counts only when it is an arXiv-family host, so an unrelated page
    # whose path happens to contain digits is not misread as a paper.
    if "://" in candidate:
        parsed = urlparse(candidate)
        if not any(parsed.netloc.endswith(host) for host in _ARXIV_HOSTS):
            return None
        candidate = parsed.path

    modern = _MODERN_ARXIV.search(candidate)
    if modern is not None:
        return modern.group(1)
    legacy = _LEGACY_ARXIV.search(candidate)
    return legacy.group(1) if legacy is not None else None


def arxiv_id_if_reference(identifier: str) -> str | None:
    """`identifier` as an arXiv identifier, but only when the whole of it is one.

    Any filename carrying a date-shaped run of digits - `my-paper-2409.19750.md`
    - contains an arXiv identifier by the searching reading, and answering a
    mistyped path by silently fetching an unrelated paper of that number is the
    worst failure this module can produce.

    A URL is still matched loosely, because `normalize_arxiv_id` already
    requires an arXiv-family host. Everything else must be the bare identifier,
    optionally `arXiv:`-prefixed, version-suffixed, or named `.pdf` - exactly
    the spellings arXiv itself hands out.
    """
    candidate = identifier.strip()
    if not candidate:
        return None
    if "://" in candidate:
        return normalize_arxiv_id(candidate)

    lowered = candidate.lower()
    if lowered.startswith("arxiv:"):
        candidate = candidate[len("arxiv:") :].strip()
    if candidate.lower().endswith(".pdf"):
        candidate = candidate[: -len(".pdf")]

    for pattern in (_MODERN_ARXIV, _LEGACY_ARXIV):
        matched = pattern.fullmatch(candidate)
        if matched is not None:
            return matched.group(1)
    return None


def normalize_bibcode(identifier: str) -> str | None:
    """`identifier` as an ADS bibcode, or None.

    Recorded but never resolved: turning a bibcode into bibliographic metadata
    needs the ADS API and a key, which kennis deliberately does not ask anyone
    for. Its value here is identity - it gives a pre-arXiv paper something to
    be deduplicated on.
    """
    matched = _ADS_BIBCODE.search(identifier.strip())
    return matched.group(1) if matched is not None else None


def normalize_doi(identifier: str) -> str | None:
    """Extract a bare DOI from `10.x/y`, `doi:10.x/y`, or a doi.org URL."""
    matched = _DOI.search(identifier.strip())
    if matched is None:
        return None
    # Sentence-cased citations carry a trailing full stop in with them.
    return matched.group(1).rstrip(".")


def looks_like_bibtex(identifier: str) -> bool:
    return identifier.lower().endswith(".bib")


@dataclass(frozen=True, slots=True)
class BibEntry:
    """One parsed BibTeX record."""

    citekey: str
    title: str
    authors: str = ""
    year: str = ""
    doi: str | None = None
    arxiv_id: str | None = None
    # A `file = {...}` path, the convention Zotero and JabRef use to point at a
    # local PDF. Followed when present, so a `.bib` export doubles as a batch
    # of documents to ingest.
    file_path: str | None = None


_BIB_ENTRY: Final = re.compile(r"@(\w+)\s*\{\s*([^,]+),(.*?)(?=\n@|\Z)", re.S)
_BIB_FIELD: Final = re.compile(
    r"(\w+)\s*=\s*(\{(?:[^{}]|\{[^{}]*\})*\}|\"[^\"]*\"|[^,\n]+)"
)


def _clean_bib_value(raw: str) -> str:
    value = raw.strip().rstrip(",").strip()
    if (value.startswith("{") and value.endswith("}")) or (
        value.startswith('"') and value.endswith('"')
    ):
        value = value[1:-1]
    # The inner braces protect capitalisation for LaTeX and mean nothing here.
    return " ".join(value.replace("{", "").replace("}", "").split())


def parse_bibtex(text: str) -> list[BibEntry]:
    """Parse a BibTeX file into entries.

    Deliberately a regular expression rather than a dependency: kennis needs
    six fields out of each entry, and a full BibTeX parser is a heavy addition
    for that. Malformed entries are skipped rather than raising, so one bad
    record in a large export does not block the rest.
    """
    entries: list[BibEntry] = []
    for _entry_type, citekey, body in _BIB_ENTRY.findall(text):
        fields = {
            name.lower(): _clean_bib_value(value)
            for name, value in _BIB_FIELD.findall(body)
        }
        title = fields.get("title", "")
        if not title:
            continue

        arxiv_id: str | None = None
        for key in ("eprint", "archiveprefix", "arxivid", "arxiv"):
            if key in fields:
                arxiv_id = normalize_arxiv_id(fields[key]) or arxiv_id
        if arxiv_id is None and "url" in fields:
            arxiv_id = normalize_arxiv_id(fields["url"])

        doi_field = fields.get("doi", "")
        entries.append(
            BibEntry(
                citekey=citekey.strip(),
                title=title,
                authors=fields.get("author", ""),
                year=fields.get("year", ""),
                doi=normalize_doi(doi_field) if doi_field else None,
                arxiv_id=arxiv_id,
                file_path=_file_path_of(fields.get("file")),
            )
        )
    return entries


def _file_path_of(file_field: str | None) -> str | None:
    """The path out of Zotero's `file = {Title:/abs/path.pdf:application/pdf}`."""
    if not file_field:
        return None
    parts = file_field.split(":")
    if len(parts) >= 2 and parts[1]:
        return parts[1]
    return parts[0] or None


def parse_bibtex_file(path: Path) -> list[BibEntry]:
    return parse_bibtex(path.read_text(encoding="utf-8", errors="replace"))


type IdentifierKind = Literal["arxiv", "doi", "bibcode"]


@dataclass(frozen=True, slots=True)
class PaperIdentifier:
    """A bibliographic identifier, read off a page or typed by a person.

    The point of finding one is that a local PDF otherwise has no identity at
    all: its citekey has to be derived from its title, and duplicate detection
    - which leans on the bibliographic identifiers - has nothing to compare.
    """

    kind: IdentifierKind
    value: str


def _all_matches(pattern: re.Pattern[str], text: str) -> list[str]:
    """Every distinct group-1 match, in order of first appearance."""
    seen: dict[str, None] = {}
    for matched in pattern.finditer(text):
        seen.setdefault(matched.group(1), None)
    return list(seen)


def find_paper_identifiers(text: str) -> list[PaperIdentifier]:
    """Every identifier `text` offers, most likely first - never just one.

    kennis does not decide which of these names the document, and cannot: a
    first page can carry the paper's own arXiv stamp, its journal DOI, an ADS
    bibcode, and a DOI belonging to something it cites, and no amount of
    pattern work distinguishes the last from the first three. Picking one and
    writing it into the corpus would be a guess recorded as a fact, so the
    list goes to whoever can actually tell.

    Ranked by kind first - arXiv, then DOI, then bibcode - which is the order
    of how much each can be turned into: an arXiv identifier resolves to full
    metadata over a keyless public API, a DOI may resolve to a preprint, a
    bibcode is identity only. Within a kind, order of appearance; and since
    the caller hands over page furniture before body text, a margin stamp
    sorts above something mentioned in a paragraph.
    """
    if not text.strip():
        return []
    found: list[PaperIdentifier] = []
    for value in _all_matches(_MODERN_ARXIV, text) + _all_matches(_LEGACY_ARXIV, text):
        found.append(PaperIdentifier(kind="arxiv", value=value))
    for value in _all_matches(_DOI, text):
        found.append(PaperIdentifier(kind="doi", value=value.rstrip(".,;)")))
    for value in _all_matches(_ADS_BIBCODE, text):
        found.append(PaperIdentifier(kind="bibcode", value=value))
    return found


def parse_identifier(identifier: str) -> PaperIdentifier | None:
    """One identifier a person supplied, classified.

    Whole-argument rather than a search: an identifier given by hand is an
    answer, not a page to scan, so `10.1093/x` is a DOI and not "a string
    containing one".
    """
    candidate = identifier.strip()
    if not candidate:
        return None
    arxiv_id = normalize_arxiv_id(candidate)
    if arxiv_id is not None:
        return PaperIdentifier(kind="arxiv", value=arxiv_id)
    doi = normalize_doi(candidate)
    if doi is not None:
        return PaperIdentifier(kind="doi", value=doi)
    bibcode = normalize_bibcode(candidate)
    if bibcode is not None:
        return PaperIdentifier(kind="bibcode", value=bibcode)
    return None


def identifier_if_reference(identifier: str) -> PaperIdentifier | None:
    """`identifier` as a paper's name, but only when the whole of it is one.

    What an argument on a command line is put through, so a path that happens
    to contain digits is not mistaken for a paper. The arXiv case is the
    dangerous one and has its own whole-argument matcher; a DOI and a bibcode
    are distinctive enough that the searching forms are safe, but they are
    anchored here anyway so that every argument is judged the same way.
    """
    candidate = identifier.strip()
    if not candidate:
        return None
    arxiv_id = arxiv_id_if_reference(candidate)
    if arxiv_id is not None:
        return PaperIdentifier(kind="arxiv", value=arxiv_id)

    bare = (
        candidate[len("doi:") :].strip()
        if candidate.lower().startswith("doi:")
        else candidate
    )
    if _DOI.fullmatch(bare.rstrip(".")) or bare.lower().startswith("https://doi.org/"):
        doi = normalize_doi(bare)
        if doi is not None:
            return PaperIdentifier(kind="doi", value=doi)

    if _ADS_BIBCODE.fullmatch(candidate):
        return PaperIdentifier(kind="bibcode", value=candidate)
    return None
