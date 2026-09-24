"""Turning a handle a person typed into the document it addresses.

Shared by every command that takes one - `corpus remove`, `corpus move` and
`read` - so that a name working for one works for all of them. It lives here
rather than in one command's module because the second caller made the first
one's private helper a shared rule.

The rule itself: without `--collection` all three are tried, and a handle
resolving in more than one is refused. That is the same rule one collection
applies to its own aliases, applied once more at the level above.
"""

from __future__ import annotations

from collections.abc import Sequence

from kennis.cli.context import Context
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.document import Document
from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.errors import DocumentNotFound


def resolve_document(
    context: Context, handle: str, collection: str | None
) -> tuple[Collection, Document]:
    """The collection holding `handle`, and the document it addresses.

    Without `--collection` all three are tried, and a handle that resolves in
    more than one is refused. That is the same rule one collection applies to
    its own aliases - a key two documents share addresses nothing - applied
    once more at the level above.
    """
    searched = [collection] if collection else list(COLLECTION_NAMES)
    found: list[tuple[Collection, Document]] = []
    for name in searched:
        candidate = Collection(root=context.corpus_root, name=name)
        try:
            found.append((candidate, candidate.resolve(handle)))
        except DocumentNotFound:
            continue

    if not found:
        raise DocumentNotFound(
            f"no document '{handle}' in {named_collections(searched)}",
            resolution="kennis corpus list",
        )
    if len(found) > 1:
        raise DocumentNotFound(
            f"'{handle}' addresses a document in "
            f"{named_collections([name.name for name, _ in found])}",
            resolution="kennis corpus list",
        )
    return found[0]


def named_collections(collections: Sequence[str]) -> str:
    if len(collections) == 1:
        return f"the {collections[0]} collection"
    return f"{', '.join(collections[:-1])} or {collections[-1]}"


__all__ = ["named_collections", "resolve_document"]
