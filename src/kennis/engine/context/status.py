"""What a bundle holds, and whether its index still matches it.

**The freshness question is the same one `corpus status` asks and it cannot
be answered the same way.** `history/freshness.py` opens by explaining why
the corpus uses git: the index records the commit it was built from, so the
answer is a `git diff --name-status` over one collection, which costs
`O(changed files)` rather than `O(corpus)`.

None of that is available here. kennis does not own the repository a bundle
sits in, so `index_bundle` passes no `Repository`, the manifest records no
`built_from`, and `index_freshness` would answer `unverifiable` every time -
which is worse than unhelpful, because the question is perfectly answerable.

It is answered by the digests the manifest already carries. `O(bundle)`
rather than `O(changed files)`, over tens of files rather than thousands,
and against `document_digest` - the same function that wrote them, so the
comparison cannot drift from what was recorded.

`Freshness` itself is reused rather than reinvented: it is the same value
with the same three counts, `render.words.describe_freshness` already words
it, and `unverifiable` simply never occurs for a bundle.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from kennis.engine.context.bundle import index_root_for
from kennis.engine.context.index import CONTEXT_COLLECTION, BundleLoader
from kennis.engine.context.notes import bundle_documents
from kennis.engine.frontmatter import split_frontmatter
from kennis.engine.history.freshness import Freshness
from kennis.engine.rag.binding import document_digest
from kennis.engine.rag.index import read_manifest

_FRONTMATTER_DELIMITER = "---"


@dataclass(frozen=True, slots=True)
class BundleStatus:
    """What a bundle holds, as facts rather than as a report.

    `groups` maps a directory relative to the bundle to how many documents
    it holds, with `""` for the bundle root. `unreadable` names the files
    whose frontmatter block could not be read - they are still indexed, and
    still counted here, because a bundle document's identity is its path and
    losing the header costs metadata rather than the file.
    """

    path: Path
    document_count: int
    groups: dict[str, int]
    unreadable: tuple[str, ...]
    # None when the bundle has never been indexed, which is a different
    # thing from an index that is in step with an empty bundle.
    freshness: Freshness | None


def bundle_status(bundle: Path) -> BundleStatus:
    """Everything `context status` reports, read in one pass."""
    documents = bundle_documents(bundle)
    groups: dict[str, int] = {}
    unreadable: list[str] = []
    for path in documents:
        relative = path.relative_to(bundle)
        directory = relative.parent.as_posix()
        key = "" if directory == "." else directory
        groups[key] = groups.get(key, 0) + 1
        if _header_is_broken(path):
            unreadable.append(relative.as_posix())
    return BundleStatus(
        path=bundle,
        document_count=len(documents),
        groups=groups,
        unreadable=tuple(unreadable),
        freshness=bundle_freshness(bundle),
    )


def bundle_freshness(bundle: Path) -> Freshness | None:
    """How far the bundle's index has fallen behind it, or None if it has none.

    **Only `stale` is a fault, which is the corpus's own rule.** A document
    written since the build leaves the index holding less than the bundle
    does, and incomplete is not wrong; a document edited or removed since
    leaves it holding something false. `remember --context` does not index,
    so a bundle sits in the added-only state routinely rather than briefly -
    which makes the count worth reporting all the more, and makes calling it
    a fault wrong all the same.
    """
    manifest = read_manifest(index_root_for(bundle), CONTEXT_COLLECTION)
    if manifest is None:
        return None
    recorded = manifest.documents
    current = {
        document.source_path: document_digest(document.text)
        for document in BundleLoader(bundle).documents()
    }
    added = {key for key in current if key not in recorded}
    gone = {key for key in recorded if key not in current}
    changed = {
        key
        for key, digest in current.items()
        if key in recorded and recorded[key] != digest
    }
    return Freshness(
        state="stale" if (changed or gone) else "in step",
        added=len(added),
        changed=len(changed),
        gone=len(gone),
    )


def _header_is_broken(path: Path) -> bool:
    """Whether this file opens with a frontmatter block that yielded nothing.

    The same three cases `BundleLoader` reports while indexing - unterminated,
    not a mapping, and not YAML at all - asked here so that a reader who has
    not indexed lately still hears about it. A file with no `---` line is not
    one of them: that is a file without metadata, which is allowed.
    """
    text = path.read_text(encoding="utf-8")
    if not text.lstrip().startswith(_FRONTMATTER_DELIMITER):
        return False
    try:
        frontmatter, _ = split_frontmatter(text)
    except yaml.YAMLError:
        return True
    return not frontmatter


__all__ = ["BundleStatus", "bundle_freshness", "bundle_status"]
