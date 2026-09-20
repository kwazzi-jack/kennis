"""The on-disk shape shared by every corpus collection.

Directory-as-group, full-title filenames, and a recursive file-versus-
directory rule that tells a document from a user-created group by filesystem
shape alone - no metadata field, no reserved bucket name:

- a `.md` file is a document;
- a directory holding `content.md` is a document with assets;
- any other directory is a group, and the walk descends into it.

This is the one place that rule is implemented.

Every function that touches disk takes its root as an argument. Settings
arrive in a later milestone and will supply it; until then
`default_corpus_root()` is the only source, and a test passes its own
directory so nothing reads the real store.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from platformdirs import user_data_dir

from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.errors import UnknownCollection

# Filesystem entries that are corpus bookkeeping, not documents or groups -
# skipped outright by `iter_documents` before `classify_child` sees them.
_SKIPPED_NAME_PREFIXES: Final = (".",)

# Characters illegal, or awkward, in a filename on at least one common
# filesystem. Stripped from a title before it becomes one - not lowercased or
# hyphenated, since nothing parses this filename as a key: the surrogate
# identifier is what every read handle addresses.
_ILLEGAL_FILENAME_CHARS: Final = re.compile(r'[/\\:*?"<>|\x00-\x1f]')

type DocumentShape = Literal["leaf-bare", "leaf-wrapped", "group"]

# A wrapped document's markdown always lives at this fixed filename inside its
# wrapper directory - `Foo/content.md`, never `Foo/Foo.md`. Matching the
# wrapper's own name would make classification ambiguous: a document titled
# the same as an existing group would turn that whole group into a single
# leaf, hiding every sibling already in it. A fixed name decouples
# classification from the wrapper's title-derived, and so collision-prone,
# name entirely.
WRAPPED_DOCUMENT_FILENAME: Final = "content.md"


def default_corpus_root() -> Path:
    """Where the machine-global corpus lives: `~/.local/share/kennis` on
    Linux. Machine-global rather than per-project, because a paper read for
    one project is the same paper in the next."""
    return Path(user_data_dir("kennis"))


def collection_root(corpus_root: Path, collection: str) -> Path:
    """The directory holding one collection's documents."""
    if collection not in COLLECTION_NAMES:
        raise UnknownCollection(
            f"unknown collection '{collection}'; "
            f"expected one of {', '.join(COLLECTION_NAMES)}"
        )
    return corpus_root / collection


def classify_child(path: Path) -> DocumentShape:
    """Classify one child of a corpus directory by filesystem shape alone.

    Callers pre-filter dotfiles and non-markdown files before calling this;
    see `iter_documents`.
    """
    if path.is_file():
        if path.suffix == ".md":
            return "leaf-bare"
        raise ValueError(f"not a document or group: {path}")
    if path.is_dir():
        if (path / WRAPPED_DOCUMENT_FILENAME).is_file():
            return "leaf-wrapped"
        return "group"
    raise ValueError(f"neither a file nor a directory: {path}")


@dataclass(frozen=True, slots=True)
class DocumentLocation:
    """One document found by `iter_documents`."""

    md_path: Path
    # The asset-wrapper directory, when this is a wrapped document; None for a
    # bare file.
    wrapper_dir: Path | None


def _is_bookkeeping(path: Path) -> bool:
    if path.name.startswith(_SKIPPED_NAME_PREFIXES):
        return True
    return path.is_file() and path.suffix != ".md"


def _walk(directory: Path) -> Iterator[DocumentLocation]:
    for child in sorted(directory.iterdir()):
        if _is_bookkeeping(child):
            continue
        shape = classify_child(child)
        if shape == "leaf-bare":
            yield DocumentLocation(md_path=child, wrapper_dir=None)
        elif shape == "leaf-wrapped":
            yield DocumentLocation(
                md_path=child / WRAPPED_DOCUMENT_FILENAME, wrapper_dir=child
            )
        else:
            yield from _walk(child)


def iter_documents(root: Path) -> Iterator[DocumentLocation]:
    """Walk `root` per the group rule, yielding one location per document at
    any nesting depth.

    Yields nothing for a root that does not exist yet, which is a fresh
    machine with nothing fetched rather than an error.
    """
    if not root.is_dir():
        return
    yield from _walk(root)


def _clean_title(title: str) -> str:
    cleaned = _ILLEGAL_FILENAME_CHARS.sub("", title).strip()
    return re.sub(r"\s+", " ", cleaned)


def title_filename(title: str) -> str:
    """The on-disk `.md` filename for a document titled `title`.

    The title verbatim, with filesystem-illegal characters stripped and
    internal whitespace collapsed - not lowercased or hyphenated.

    A leading `.` is stripped too: any dot-prefixed name is treated as corpus
    bookkeeping rather than a document, so an unstripped dotfile-derived title
    would write successfully and then be permanently invisible to every future
    walk.
    """
    return f"{_clean_title(title).lstrip('.').strip() or 'untitled'}.md"


def title_needs_dot_stripped(title: str) -> bool:
    """True when `title_filename` had to strip a leading dot. A caller that
    wants to warn about it checks this before writing."""
    return _clean_title(title).startswith(".")


def unique_filename(base_name: str, taken: set[str]) -> str:
    """`base_name`, or the first `<stem> (n)<suffix>` not already taken.

    Uniqueness is collection-wide, so `taken` should be every document's
    filename in the collection rather than one group's.

    `WRAPPED_DOCUMENT_FILENAME` is always treated as taken, whatever `taken`
    says: a bare document titled "content" claiming that exact name would make
    its own parent directory classify as a wrapped document the next time
    something is added alongside it, hiding every sibling already there.
    """
    if base_name not in taken and base_name != WRAPPED_DOCUMENT_FILENAME:
        return base_name

    dot_index = base_name.rfind(".")
    stem, suffix = (
        (base_name[:dot_index], base_name[dot_index:])
        if dot_index > 0
        else (base_name, "")
    )

    counter = 2
    while True:
        candidate = f"{stem} ({counter}){suffix}"
        if candidate not in taken:
            return candidate
        counter += 1
