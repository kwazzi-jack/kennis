"""Minting a name for a paper that arrived without one.

Derivation is the fallback, never the rule. A paper that came with a citekey
keeps it, because that key is what the user's own bibliography already cites
and a new one would break every reference in their writing. This module is for
the other case: a bare arXiv identifier, or a PDF with no bibliography at all.
"""

from __future__ import annotations

import re
from typing import Final

# Words a title contributes nothing by including.
_STOPWORDS: Final = frozenset(
    {"a", "an", "the", "of", "for", "and", "with", "in", "on", "to", "using", "at"}
)

# Stands in for the surname when there is no author to take one from - a local
# PDF carries no bibliography, so the key is title-derived and reads
# `paperRadioInterferometry2018`. Deliberately a real word rather than a
# marker, because the key is something a person will read and type.
_NO_AUTHOR: Final = "paper"

# How many meaningful title words a key carries. Three, which is Better
# BibTeX's `shorttitle(3,3)` and therefore what a Zotero export already
# produces - the whole point of the style is that a derived key sits beside an
# exported one without looking out of place.
#
# boepie takes two, and its own docstring example
# (`smirnovRevisitingRadioInterferometer2011`) needs three, so its code and its
# documentation disagree. Three is the one that matches the keys in a real
# library.
_TITLE_WORDS: Final = 3


def derive_citekey(*, authors: str, year: str, title: str) -> str:
    """A short slug: surname, then leading title words, then year.

    Collisions are `unique_citekey`'s problem, not this function's.
    """
    return f"{_surname_part(authors)}{_title_part(title)}{year}"


def literature_stem(*, title: str, authors: str, year: str) -> str:
    """What a paper is called on disk: `title - authors - year`.

    The title alone is not enough to tell two papers apart in a directory
    listing: reviews and proceedings repeat titles, and the same work appears
    as a preprint and as a published version. The authors and the year are
    what a person actually scans for. Concern #190.

    **Only the first surname**, with `et al` past one author: an astronomy
    paper's full author list is not a filename. **A part that is not known is
    omitted rather than left empty**, so a paper with neither degrades to the
    title alone rather than to `Title -  - `, which reads as a fault rather
    than as an absence.

    The result is a stem. `title_filename` sanitises it and adds the
    extension, as it does for every other collection.
    """
    parts = [title.strip()]
    if authors.strip():
        parts.append(_named_authors(authors))
    if year.strip():
        parts.append(year.strip())
    return " - ".join(part for part in parts if part)


def _named_authors(authors: str) -> str:
    """The first author's surname, and whether there are others.

    Surnames only, because the given names of a first author vary between
    the sources kennis reads the same paper from - `Pan, Rui`, `Rui Pan`,
    `R. Pan` - and a filename that changes with the source is not a name.
    """
    surname = _surname_of(authors)
    if not surname:
        return ""
    return f"{surname} et al" if " and " in authors else surname


def _surname_of(authors: str) -> str:
    """The first author's surname, spelled as it was given.

    Two conventions reach here and both have to parse: `Last, First M.` from
    a Zotero export, and `First M. Last` from arXiv's Atom API.
    """
    first = authors.split(" and ")[0].strip()
    if "," in first:
        return first.split(",")[0].strip()
    parts = first.split()
    return parts[-1].strip() if parts else ""


def _surname_part(authors: str) -> str:
    """The surname as a citekey fragment: letters only, lowercase initial.

    A citekey is a slug and is typed by hand, so `Hallowes-Welman` becomes
    `hallowesWelman`. A *filename* keeps the hyphen, which is why
    `literature_stem` uses `_surname_of` and not this.
    """
    surname = re.sub(r"[^A-Za-z]", "", _surname_of(authors)) or _NO_AUTHOR
    return surname[:1].lower() + surname[1:]


def _title_part(title: str) -> str:
    words = [
        word
        for word in re.findall(r"[A-Za-z]+", title)
        if word.lower() not in _STOPWORDS
    ]
    return "".join(word.capitalize() for word in words[:_TITLE_WORDS])


def unique_citekey(base: str, taken: set[str]) -> str:
    """`base`, or the first unused `<base><suffix>`.

    Letters first, which mirrors the disambiguation Zotero itself applies to
    same-author, same-year keys. Past `z` the convention has nothing more to
    say, and raising would abort a whole batch over one document - so the
    twenty-seventh is numbered. Title-derived keys, which is what a folder of
    PDFs with no bibliography produces, collide far more readily than the
    author-and-year keys the lettering was written for.
    """
    if base not in taken:
        return base
    for letter in "abcdefghijklmnopqrstuvwxyz":
        candidate = f"{base}{letter}"
        if candidate not in taken:
            return candidate
    suffix = 27
    while f"{base}{suffix}" in taken:
        suffix += 1
    return f"{base}{suffix}"
