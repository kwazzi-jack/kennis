"""Walking a pack's content, once, for everything that needs to.

`validate` reads a source to check the digests recorded beside it;
`update` reads the same source to write them; `add` will read it to copy
the files. If each had its own walk they could disagree, and the worst of
those disagreements is silent: `update` writes digests that `validate` then
rejects, and an author caught between two kennis commands has nowhere to
go.

So this module answers **what is under a source**, in facts, and each
caller decides what the facts mean. A file that resolves outside the pack
root is a finding to `validate` and a refusal to `update`; neither decision
belongs here.

**Symlinks are never followed** - not the files, not the directories.
"Not followed" is simpler to state than "followed when the target is safe",
and a pack has no reason to ship one. The walk reports them so a caller can
say which of the two kinds it found: a link out of the pack root is the
zip-slip shape section 7 names, and a link inside it is untidy rather than
dangerous.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from kennis.engine._glob import globstar_regex
from kennis.engine.pack.schema import ContentSource


@dataclass(frozen=True, slots=True)
class SourceContent:
    """What one `source:` holds, as facts rather than as a verdict.

    Every path is relative to the **pack root**, not to the source, so a
    caller reporting one does not have to reassemble the address. The
    digests are the exception: they are keyed relative to the source,
    because that is how `generated.content` records them.
    """

    source: str
    # False when the declared directory is not there at all, which is a
    # different thing from a directory that matched no file.
    exists: bool
    digests: dict[str, str]
    escaping: tuple[str, ...]
    symlinks: tuple[str, ...]
    # Files no `include` pattern matched. **Not** files an `exclude`
    # removed: that was intent, and reporting it every run would be noise
    # the useful case drowns in. This is the one that can be a mistake -
    # the default `**/*.md` dropping a PDF the author meant to ship, with
    # no word said about it. Concern #266.
    unselected: tuple[str, ...]


def content_digest(data: bytes) -> str:
    """The digest a pack records for one of its files.

    sha256 of the bytes. Named here rather than left to each caller because
    a pack is an interchange format that another tool may write without
    kennis, and `state.json`'s `file_sha256` already fixes the family.
    Deliberately not `rag.binding.document_digest`, which is blake2b over
    decoded text and exists to keep chunking stable - a different question
    with a different answer. Concern #257.
    """
    return hashlib.sha256(data).hexdigest()


def read_source(root: Path, source: ContentSource) -> SourceContent:
    """Everything under one declared source, walked once."""
    directory = root / source.source
    if not directory.is_dir():
        return SourceContent(
            source=source.source,
            exists=False,
            digests={},
            escaping=(),
            symlinks=(),
            unselected=(),
        )

    digests: dict[str, str] = {}
    escaping: list[str] = []
    symlinks: list[str] = []
    unselected: list[str] = []
    for relative, path in _walked(directory):
        address = address_of(source.source, relative)
        if not _included(relative, source):
            unselected.append(address)
            continue
        if _excluded(relative, source):
            continue
        if path.is_symlink():
            target = escaping if not resolves_inside(path, root) else symlinks
            target.append(address)
            continue
        if not resolves_inside(path, root):
            escaping.append(address)
            continue
        digests[relative] = content_digest(path.read_bytes())
    return SourceContent(
        source=source.source,
        exists=True,
        digests=digests,
        escaping=tuple(escaping),
        symlinks=tuple(symlinks),
        unselected=tuple(unselected),
    )


def address_of(source: str, relative: str) -> str:
    """A file's path relative to the pack root, for reporting."""
    return (PurePosixPath(source.strip("/")) / relative).as_posix()


def resolves_inside(path: Path, root: Path) -> bool:
    """Whether `path` resolves under the pack root.

    The zip-slip check of section 7. A declared source is validated as a
    string by the model; this is the half only the filesystem can answer.
    """
    return path.resolve().is_relative_to(root.resolve())


def _walked(directory: Path) -> list[tuple[str, Path]]:
    """Every file under `directory`, as a POSIX relative path and a path.

    `os.walk(followlinks=False)` rather than `rglob`, which follows
    directory symlinks and offers no way to say otherwise - so a link to a
    directory outside the pack would have its contents walked in as the
    pack's own.
    """
    found: list[tuple[str, Path]] = []
    for parent, _, names in os.walk(directory, followlinks=False):
        for name in names:
            path = Path(parent) / name
            found.append((path.relative_to(directory).as_posix(), path))
    return sorted(found)


def _included(relative: str, source: ContentSource) -> bool:
    """Whether any `include` pattern takes this file.

    Asked separately from `_excluded` so the caller can tell the two
    rejections apart: one is a pattern the author may not have thought
    about, the other is one they wrote.
    """
    return any(
        globstar_regex(pattern).fullmatch(relative) for pattern in source.include
    )


def _excluded(relative: str, source: ContentSource) -> bool:
    """Whether any `exclude` pattern drops this file."""
    return any(
        globstar_regex(pattern).fullmatch(relative) for pattern in source.exclude
    )


__all__ = [
    "SourceContent",
    "address_of",
    "content_digest",
    "read_source",
    "resolves_inside",
]
