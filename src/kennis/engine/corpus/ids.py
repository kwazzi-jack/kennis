"""Surrogate document identifiers: ten characters, frozen at creation.

A document's identifier is the handle every read echoes back, and it is
*surrogate* so that the document's on-disk name can be the full human-legible
title rather than a parseable key. Retitle it, regroup it, move it between
collections - the handle keeps working, because nothing addresses the document
by path.

**Derived from the natural key where one exists, random otherwise.** Minting
at random is what a surrogate wants in the abstract, and it is exactly wrong
across two machines: machine A fetches `arxiv:1101.1764` and writes one
identifier, machine B fetches the same paper and writes another, the filename
comes from the title so both land at the same path with different bytes, and
git reports an add/add conflict on every paper both machines hold. Nothing in
the content can tell git the two are the same document, because the only thing
that differs is the field that was deliberately made arbitrary.

Deriving from the natural key makes both machines mint the same identifier and
write byte-identical files. Notes keep random identifiers, which is safe: a
note has no natural key by definition and is not a thing two machines
independently create.

**A document has several identifiers; derivation uses exactly one.** The input
is fixed by precedence - arXiv identifier, then DOI, then bibcode - and
recorded in frontmatter as `id_from`, so it is auditable rather than
guessable. If later enrichment discovers a higher-precedence identifier, the
new one is recorded as an ordinary field and the document's identifier does
**not** change; re-minting would break every handle pointing at it. All the
identifiers stay usable for lookup: one decides the identifier, any of them
finds the document.

**Derived from identity, never from content.** Hashing the document's bytes
would change its identifier on every edit, which is the exact failure a
surrogate exists to prevent.
"""

from __future__ import annotations

import hashlib
import secrets
import string
from typing import Final

ID_ALPHABET: Final = string.ascii_lowercase + string.digits
ID_LENGTH: Final = 10

# Retry bound for the collision loop in `mint_id` - a correctness backstop,
# not a load-bearing mechanism: at length 10 over a 36-character alphabet the
# collision probability against any realistic corpus is negligible.
_MAX_MINTING_ATTEMPTS: Final = 100

# blake2b rather than sha256 because the digest size is a parameter rather
# than a truncation. 16 bytes is far more entropy than the ten base-36 digits
# below consume, so the encoding is what bounds the space, not the hash.
_DIGEST_BYTES: Final = 16


def derive_id(natural_key: str) -> str:
    """The identifier `natural_key` always produces, on any machine.

    `natural_key` is namespaced by its kind - `arxiv:`, `doi:`, `bibcode:`,
    `docs:` - so a DOI that happens to spell an arXiv identifier cannot
    collide with it. Build one with `natural_key_for_literature` or
    `natural_key_for_docs` rather than by hand.
    """
    if not natural_key:
        raise ValueError(
            "cannot derive an identifier from an empty natural key; "
            "mint a random one instead"
        )
    digest = hashlib.blake2b(
        natural_key.encode("utf-8"), digest_size=_DIGEST_BYTES
    ).digest()
    number = int.from_bytes(digest, "big")
    base = len(ID_ALPHABET)
    characters: list[str] = []
    for _ in range(ID_LENGTH):
        number, remainder = divmod(number, base)
        characters.append(ID_ALPHABET[remainder])
    return "".join(reversed(characters))


def generate_id() -> str:
    """A fresh random identifier, with no uniqueness check - see `mint_id`."""
    return "".join(secrets.choice(ID_ALPHABET) for _ in range(ID_LENGTH))


def mint_id(taken: set[str]) -> str:
    """A random identifier not already in `taken`.

    For notes, which have no natural key. `taken` should be every identifier
    in the collection, and may usefully include the derived ones: a derived
    identifier and a minted one are indistinguishable by shape, so nothing
    downstream would notice a collision between them, which is precisely why
    it must not happen.
    """
    for _ in range(_MAX_MINTING_ATTEMPTS):
        candidate = generate_id()
        if candidate not in taken:
            return candidate
    raise ValueError(
        f"could not mint an unused {ID_LENGTH}-character identifier after "
        f"{_MAX_MINTING_ATTEMPTS} attempts"
    )


def natural_key_for_literature(
    *, arxiv_id: str | None, doi: str | None, bibcode: str | None
) -> str | None:
    """The one identifier of a paper that decides its surrogate identifier.

    Precedence is arXiv identifier, then DOI, then bibcode, and it is fixed
    rather than "whichever was discovered first" so that two machines
    enriching the same paper in different orders still agree. None when the
    paper carries none of the three, which is a document literature refuses
    elsewhere; here the answer is simply that there is nothing to derive from.
    """
    if arxiv_id:
        return f"arxiv:{arxiv_id}"
    if doi:
        return f"doi:{doi}"
    if bibcode:
        return f"bibcode:{bibcode}"
    return None


def natural_key_for_docs(*, project: str, page: str) -> str:
    """The natural key of one documentation page.

    A page is identified by which project it belongs to and which page of it
    this is, which is stable across a re-crawl in a way a URL is not.
    """
    return f"docs:{project}/{page}"
