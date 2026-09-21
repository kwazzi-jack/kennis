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


def _surname_part(authors: str) -> str:
    first = authors.split(" and ")[0].strip()
    if "," in first:
        # "Last, First M." - the convention a Zotero export writes.
        surname = first.split(",")[0].strip()
    else:
        # "First M. Last" - what arXiv's Atom API returns, and the real caller
        # when a bare arXiv identifier was all there was.
        parts = first.split()
        surname = parts[-1].strip() if parts else ""
    surname = re.sub(r"[^A-Za-z]", "", surname) or _NO_AUTHOR
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
