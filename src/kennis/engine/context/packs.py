"""A pack's context, searched where it lives (14g, #513).

A pack's `context:` content is advice for the projects that use the pack.
It is kept once, in the store `kennis pack add` fills, and a project that
declares the pack searches it there: nothing is copied into a project, so
a pack's release reaches every project at once, no project's repository
changes for text it did not write, and a search across projects meets each
passage once.

**Each pack has its own index, in the store** (`packs/<id>/.index`), built
the first time a project searches it. A reinstall replaces the pack's
folder whole, so an index that no longer matches its pack cannot outlive
the release that made it stale. Lexical, as a bundle's is by default: the
content is short advice, and building it must not wait on a model.

**A project replaces one of a pack's files** by copying it into its bundle
as its own, with `replaces: pack:<id>/<address>` in its header. The copy
is the project's note like any other; the original is left out of that
project's search and no other's.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import yaml

from kennis.engine.atomic import replace_file
from kennis.engine.context.bundle import declared_packs, is_bundle_dir
from kennis.engine.context.notes import bundle_documents
from kennis.engine.context.reset import USER_OWNER
from kennis.engine.errors import (
    ContextNotFound,
    DocumentNotFound,
    InputError,
    NothingToIndex,
    PackNotInstalled,
)
from kennis.engine.events import EventSink
from kennis.engine.frontmatter import Frontmatter, join_frontmatter, split_frontmatter
from kennis.engine.pack.installed import (
    InstalledPack,
    declared_content,
    list_installed,
)
from kennis.engine.pack.store import pack_root
from kennis.engine.rag.binding import Binding
from kennis.engine.rag.chunking import ChunkParameters
from kennis.engine.rag.index import BuildReport, LoadedIndex, build_index, load_index
from kennis.engine.rag.models import Document, Metadata

# A pack's context group in a search, and the prefix of what a project's
# copy says it replaces.
PACK_GROUP_PREFIX: Final = "pack:"
INDEX_DIRNAME: Final = ".index"
_COLLECTION: Final = "context"


def pack_group(pack_id: str) -> str:
    return f"{PACK_GROUP_PREFIX}{pack_id}"


def pack_of_group(name: str) -> str | None:
    """The pack id a search group is named for, or None for any other
    group."""
    return (
        name.removeprefix(PACK_GROUP_PREFIX)
        if name.startswith(PACK_GROUP_PREFIX)
        else None
    )


def pack_context_index_root(corpus_root: Path, pack_id: str) -> Path:
    return pack_root(corpus_root, pack_id) / INDEX_DIRNAME


@dataclass(frozen=True, slots=True)
class PacksOfAProject:
    """The packs a project declares, split by whether this machine has
    them."""

    installed: tuple[InstalledPack, ...]
    missing: tuple[str, ...]


def packs_of(bundle: Path, corpus_root: Path) -> PacksOfAProject:
    declared = declared_packs(bundle)
    held = {one.state.pack_id: one for one in list_installed(corpus_root).packs}
    return PacksOfAProject(
        installed=tuple(held[pack] for pack in declared if pack in held),
        missing=tuple(pack for pack in declared if pack not in held),
    )


@dataclass(frozen=True, slots=True)
class PackFile:
    """One of a pack's context files: where a project would put it, and
    where the store holds it."""

    address: str
    pack_id: str
    path: Path


def pack_files(corpus_root: Path, pack: InstalledPack) -> dict[str, PackFile]:
    """The pack's own markdown context files, by address.

    One pack alone, so no other pack's claim on an address defers it: a
    project that declares two packs shipping one address sees both, each
    in its own group.
    """
    declarations = declared_content(corpus_root, (pack,), "context").declarations
    return {
        address: PackFile(address=address, pack_id=declaration.pack_id, path=path)
        for address, declaration in declarations.items()
        if (path := declaration.store_path) is not None and path.suffix == ".md"
    }


class PackContextLoader:
    """One pack's context content, as retrievable documents."""

    def __init__(self, corpus_root: Path, pack: InstalledPack) -> None:
        self._corpus_root = corpus_root
        self._pack = pack

    @property
    def name(self) -> str:
        return _COLLECTION

    def documents(self, *, events: EventSink | None = None) -> list[Document]:
        return [
            _document(file)
            for file in pack_files(self._corpus_root, self._pack).values()
        ]


def load_pack_context_index(corpus_root: Path, pack: InstalledPack) -> LoadedIndex:
    """The pack's context index, built first if this is its first search."""
    root = pack_context_index_root(corpus_root, pack.state.pack_id)
    try:
        return load_index(root, _COLLECTION)
    except NothingToIndex:
        build_pack_context_index(corpus_root, pack)
        return load_index(root, _COLLECTION)


def build_pack_context_index(corpus_root: Path, pack: InstalledPack) -> BuildReport:
    return build_index(
        PackContextLoader(corpus_root, pack),
        index_root=pack_context_index_root(corpus_root, pack.state.pack_id),
        binding=Binding(chunking=ChunkParameters(), model=None),
    )


def replaced_in(bundle: Path) -> frozenset[str]:
    """Every `pack:<id>/<address>` a file of this bundle replaces."""
    replaced: set[str] = set()
    for path in bundle_documents(bundle):
        try:
            header, _ = split_frontmatter(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        named = header.get("replaces")
        if isinstance(named, str) and named.startswith(PACK_GROUP_PREFIX):
            replaced.add(named)
    return frozenset(replaced)


def copy_pack_file(bundle: Path, corpus_root: Path, reference: str) -> Path:
    """Copy `<pack id>/<address>` into the bundle as the project's own file.

    The copy keeps the shipped body, is owned by the person, and names what
    it replaces, so this project's search reads it in place of the pack's.
    Refused when the address is taken in the bundle, rather than writing
    over a file the person may have made.
    """
    if not is_bundle_dir(bundle):
        raise ContextNotFound
    pack_id, _, address = reference.partition("/")
    if not address:
        raise InputError(
            f"'{reference}' names no file: write it as <pack id>/<address>",
            resolution="kennis context copy --help",
        )
    held = {one.state.pack_id: one for one in list_installed(corpus_root).packs}
    if pack_id not in held:
        raise PackNotInstalled(f"no pack '{pack_id}' is installed")
    file = pack_files(corpus_root, held[pack_id]).get(address)
    if file is None:
        raise DocumentNotFound(
            f"the pack '{pack_id}' ships no context file '{address}'",
            resolution=None,
        )
    target = bundle / address
    if target.exists():
        raise InputError(
            f"{target} exists already; move it aside to copy the pack's file there",
            resolution=None,
        )
    shipped, body = split_frontmatter(file.path.read_text(encoding="utf-8"))
    header: Frontmatter = {
        "title": shipped.get("title", Path(address).stem),
        "description": shipped.get("description", ""),
        "owner": USER_OWNER,
        "replaces": f"{pack_group(pack_id)}/{address}",
        "source": {
            "via": "copy",
            "pack": pack_id,
            "address": address,
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
        },
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    replace_file(target, join_frontmatter(header, body))
    return target


def _document(file: PackFile) -> Document:
    text = file.path.read_text(encoding="utf-8")
    try:
        header, body = split_frontmatter(text)
    except yaml.YAMLError:
        header, body = {}, text
    metadata: Metadata = dict(header)
    metadata.setdefault("title", Path(file.address).stem)
    directory = Path(file.address).parent.as_posix()
    metadata["group"] = "" if directory == "." else directory
    metadata["pack"] = file.pack_id
    # What a project's copy names in `replaces`, which a search filters on.
    metadata["address"] = file.address
    return Document(
        id=file.address,
        text=body,
        source_path=file.address,
        metadata=metadata,
    )


__all__ = [
    "PACK_GROUP_PREFIX",
    "PackContextLoader",
    "PackFile",
    "PacksOfAProject",
    "build_pack_context_index",
    "copy_pack_file",
    "load_pack_context_index",
    "pack_context_index_root",
    "pack_files",
    "pack_group",
    "pack_of_group",
    "packs_of",
    "replaced_in",
]
