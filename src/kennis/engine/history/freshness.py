"""Whether an index still matches the corpus it was built over.

The index records **the commit it was built from**, so the question is
answered by git rather than by walking the corpus and comparing digests:

    git diff --name-status <built_from> HEAD -- <collection>/
    git status --porcelain -- <collection>/

That is `O(changed files)` rather than `O(corpus)`, exact rather than
digest-by-digest, and the added/changed/gone distinction survives intact
because it is precisely what `--name-status` returns.

Both commands are needed. The diff misses anything not yet committed, and a
document a user edited by hand is a change the index does not know about
just as surely as a committed one.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final, Literal

import yaml

from kennis.engine.frontmatter import split_frontmatter
from kennis.engine.history.repository import Repository
from kennis.engine.rag.binding import document_digest

type IndexState = Literal["in step", "stale", "unverifiable"]

# Why a freshness question could not be answered.
type Unverifiable = Literal["no commit recorded", "commit not in this corpus"]

# Git keeps no empty directories, so each collection holds one of these to
# survive a commit. It is not a document and must not be counted as one.
_PLACEHOLDER: Final = ".gitkeep"

# A document with assets is a directory holding this file.
_WRAPPED: Final = "content.md"


@dataclass(frozen=True, slots=True)
class Freshness:
    """How far an index has fallen behind its collection.

    **Only `stale` is a fault.** Documents *added* since the build are
    counted and deliberately do not make the state stale: between a `corpus
    add` and the `corpus index` that follows it the index holds nothing
    false, it simply holds less than the corpus does. Incomplete is not
    wrong. So serving decides on `stale` alone, while a caller asking whether
    an index is complete reads `added` as well.

    That distinction is also why there is no scheduler: a third state of
    "will be current later" is the one that misleads, because it stays true
    right up until the job did not run.
    """

    state: IndexState
    added: int = 0
    changed: int = 0
    gone: int = 0
    # Which reason applies, for `unverifiable` only. A value rather than a
    # sentence, so the two cases can be worded differently by a front end
    # without the engine knowing how they differ.
    unverifiable: Unverifiable | None = None


def index_freshness(
    repository: Repository,
    *,
    collection: str,
    built_from: str | None,
    indexed: dict[str, str] | None = None,
) -> Freshness:
    """Compare a collection against what its index actually holds.

    **git narrows and the digest decides.** The diff is what makes this
    `O(changed files)` rather than `O(corpus)`, and it is kept for that - but
    it cannot answer the question on its own, because `built_from` is the
    head *before* the indexing command's own commit. A note written and
    indexed by one `kennis remember` is committed afterwards, so the diff
    lists it as added although the index holds it. `indexed` is the manifest's
    `{source path: digest}` map, recorded at build time and keyed the same
    way git reports a path, so it can be looked up from a diff. Comparing
    against it settles each flagged path:

        not recorded          -> added
        recorded, differs     -> changed
        recorded, matches     -> in the index, and nothing to say
        deleted and recorded  -> gone

    Passing `indexed=None` keeps the old behaviour of trusting the diff, and
    is for a caller that has no manifest to hand. Concern #245.
    """
    if built_from is None:
        return Freshness(state="unverifiable", unverifiable="no commit recorded")
    if not repository.has_commit(built_from):
        return Freshness(state="unverifiable", unverifiable="commit not in this corpus")

    scope = f"{collection}/"
    flagged: dict[str, str] = {}
    for source in (
        repository.diff_names(built_from, scope=scope),
        repository.status_names(scope=scope),
    ):
        for status, path in source:
            document = document_of(path, collection)
            if document is None:
                continue
            # A document that was committed as changed and then edited again
            # appears in both answers, and a deletion seen anywhere is a
            # deletion: `D` wins over a later letter for the same document,
            # and otherwise the first classification stands.
            if flagged.get(document) != "D":
                flagged[document] = status

    added: set[str] = set()
    changed: set[str] = set()
    gone: set[str] = set()
    for document, status in flagged.items():
        _classify(
            document,
            status,
            root=repository.root,
            indexed=indexed,
            added=added,
            changed=changed,
            gone=gone,
        )

    return Freshness(
        state="stale" if (changed or gone) else "in step",
        added=len(added),
        changed=len(changed),
        gone=len(gone),
    )


def _classify(
    document: str,
    status: str,
    *,
    root: Path,
    indexed: dict[str, str] | None,
    added: set[str],
    changed: set[str],
    gone: set[str],
) -> None:
    """Sort one flagged document into added, changed, gone or nothing."""
    if status == "D":
        # Absent from the index as well as from the corpus is not a loss.
        if indexed is None or document in indexed:
            gone.add(document)
        return
    if indexed is None:
        (added if status == "A" else changed).add(document)
        return
    # Two spellings, because `document_of` names a wrapped document by its
    # directory while the index records the path of the `content.md` inside
    # it. One document either way.
    recorded = indexed.get(document, indexed.get(f"{document}/{_WRAPPED}"))
    current = _digest_of(root, document)
    if recorded is None:
        added.add(document)
    elif current is not None and recorded != current:
        changed.add(document)
    # A recorded digest that matches, or a document that cannot be read to
    # produce one, falls through. The second is deliberate: reading it is
    # how the digest is obtained, and a document whose frontmatter will not
    # parse is exactly what a corpus in trouble holds - failing here would
    # break the command that diagnoses it, which is concern #21 one layer
    # down. It is reported by `corpus status` in its own right.


def _digest_of(root: Path, document: str) -> str | None:
    """The digest of a document's text now, or None if it cannot be read.

    The same digest `build_index` recorded, so the two are comparable: taken
    over the body alone, because that is what the chunker was given.
    """
    for candidate in (root / document, root / document / _WRAPPED):
        if not candidate.is_file():
            continue
        try:
            _, body = split_frontmatter(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            return None
        return document_digest(body)
    return None


def document_of(path: str, collection: str) -> str | None:
    """The document a changed path belongs to, or None if it is not one.

    Counted per document rather than per file: a document with assets is a
    directory holding `content.md`, so three changed paths under it are one
    changed document, not three.

    **Derived from the path rather than from the filesystem**, because a
    deleted file cannot be examined and deletions are exactly what this has
    to count.
    """
    parts = PurePosixPath(path).parts
    if len(parts) < 2 or parts[0] != collection:
        return None

    relative = PurePosixPath(*parts[1:])
    if relative.name == _PLACEHOLDER:
        return None
    if relative.name == _WRAPPED or relative.suffix != ".md":
        # An asset, or the leaf of a wrapped document: either way the
        # document is the directory it sits in.
        parent = relative.parent
        return f"{collection}/{parent}" if str(parent) != "." else None
    return f"{collection}/{relative}"
