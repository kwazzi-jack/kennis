"""Checking a `.ken.yml` against this kennis and against its own content.

Unit 1's models answer "is this a well-formed pack". Four questions need
more than the models, and each needs something the file cannot carry:

1. **the two version refusals** - this kennis's own version and the schema
   version it understands;
2. **overlapping `source:` trees** - the declared sources compared against
   each other;
3. **path hygiene** - what the filesystem says a path resolves to;
4. **the generated digests** - the content on disk.

**Only the parse failure raises.** Everything else is a finding about a pack
that exists, and `pack validate` must be able to report several at once: an
author with three stale digests is better served by three lines than by
three runs. `PackInvalid` is raised when there is no pack to report on.

**The engine names these things and does not phrase them** (concern #81).
A problem carries a `kind` and the fields that kind needs - a path, the two
digests, the other source - and `render/` turns it into a sentence.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from packaging.version import InvalidVersion, Version

from kennis import __version__
from kennis.engine._glob import globstar_regex
from kennis.engine.errors import PackInvalid
from kennis.engine.pack.schema import (
    SCHEMA_VERSION,
    ContentSource,
    GeneratedSource,
    Pack,
    load_pack,
)

type ProblemKind = Literal[
    "overlapping-sources",
    "source-missing",
    "escapes-root",
    "symlink",
    "digest-mismatch",
    "digest-absent",
    "undigested",
]

type RefusalKind = Literal["schema-too-new", "kennis-too-old"]

# The sections whose content is walked, and the name each one has in the
# generated block. `docs` and `literature` are declarations rather than
# content: nothing is copied, so there is nothing on disk to check.
_CONTENT_SECTIONS: tuple[str, ...] = ("notes", "context")


@dataclass(frozen=True, slots=True)
class PackProblem:
    """One finding about a pack's content, as fields rather than a sentence."""

    kind: ProblemKind
    # Relative to the pack root, so two packs' reports are comparable and
    # nothing leaks the absolute path of the machine that ran the check.
    path: str
    # The second tree, for an overlap. Nothing else uses it.
    other: str | None = None
    # The two sides of a digest disagreement.
    recorded: str | None = None
    actual: str | None = None


@dataclass(frozen=True, slots=True)
class VersionRefusal:
    """The pack is well-formed and this kennis may not read it.

    Separate from a `PackProblem` because the fix is different: section 5
    step 1 refuses these with "upgrade kennis", and an author who edits the
    file in response has misunderstood the message.
    """

    kind: RefusalKind
    required: str
    available: str


@dataclass(frozen=True, slots=True)
class PackReport:
    """What `pack validate` found, and what it was able to look at."""

    path: Path
    pack: Pack
    refusal: VersionRefusal | None
    problems: tuple[PackProblem, ...]
    # False when there was no `generated` block to check against, which is a
    # valid pack and a different thing from a pack whose digests all agreed.
    digests_checked: bool

    @property
    def ok(self) -> bool:
        return self.refusal is None and not self.problems


def content_digest(data: bytes) -> str:
    """The digest a pack records for one of its files.

    sha256 of the bytes. Named here rather than left to the caller because a
    pack is an interchange format that another tool may write without kennis,
    and `state.json`'s `file_sha256` already fixes the family. Deliberately
    not `rag.binding.document_digest`, which is blake2b over decoded text and
    exists to keep chunking stable - a different question with a different
    answer.
    """
    return hashlib.sha256(data).hexdigest()


def validate_pack(path: Path) -> PackReport:
    """Read the pack at `path` and check it against kennis and its content.

    Raises `PackInvalid` when there is no pack to report on: the file is
    missing, unreadable, or does not parse.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise PackInvalid(f"{path} could not be read: {error}") from error
    pack = load_pack(text)

    refusal = _version_refusal(pack)
    if refusal is not None:
        # A newer schema may use sections this kennis cannot interpret, so
        # judging its content would be judging it by rules that do not apply.
        return PackReport(
            path=path,
            pack=pack,
            refusal=refusal,
            problems=(),
            digests_checked=False,
        )

    root = path.parent
    problems = list(_overlapping(pack))
    checked = pack.generated is not None
    for section, source in _content_sources(pack):
        problems.extend(_checked_source(root, section, source, pack))
    return PackReport(
        path=path,
        pack=pack,
        refusal=None,
        problems=tuple(problems),
        digests_checked=checked,
    )


def _version_refusal(pack: Pack) -> VersionRefusal | None:
    """Whether this kennis may read this pack at all."""
    if pack.kennis.schema_version > SCHEMA_VERSION:
        return VersionRefusal(
            kind="schema-too-new",
            required=str(pack.kennis.schema_version),
            available=str(SCHEMA_VERSION),
        )
    required = pack.kennis.min_version
    if required is None:
        return None
    try:
        wanted = Version(required)
    except InvalidVersion:
        # Not a version at all is a defect in the file, not a refusal, and
        # the models cannot check it without importing `packaging` into the
        # schema. Reported as the refusal it most resembles, with the string
        # the author wrote, so the message names the field they must fix.
        return VersionRefusal(
            kind="kennis-too-old", required=required, available=__version__
        )
    # `packaging.version.Version`, never a string comparison: `0.10` sorts
    # before `0.2` lexicographically and after it numerically, so a string
    # comparison installs a pack that needs a kennis nobody has.
    if wanted > Version(__version__):
        return VersionRefusal(
            kind="kennis-too-old", required=required, available=__version__
        )
    return None


def _content_sources(pack: Pack) -> list[tuple[str, ContentSource]]:
    """Every source whose files are copied, with the section it belongs to."""
    return [("notes", source) for source in pack.corpus.notes] + [
        ("context", source) for source in pack.context
    ]


def _overlapping(pack: Pack) -> list[PackProblem]:
    """Sources within one section where one tree contains another.

    Compared as declared prefixes rather than as matched file sets: the
    ambiguity is a property of the declaration, and comparing files would
    make this check need the content to be present.

    **Across sections is not an overlap.** Section 5's diff key carries the
    section, so the same tree shipped to `notes` and to `context` has two
    distinct destinations. Odd, but decidable.
    """
    problems: list[PackProblem] = []
    for section in _CONTENT_SECTIONS:
        declared = [
            source.source for name, source in _content_sources(pack) if name == section
        ]
        for index, first in enumerate(declared):
            for second in declared[index + 1 :]:
                if _contains(first, second) or _contains(second, first):
                    problems.append(
                        PackProblem(
                            kind="overlapping-sources", path=first, other=second
                        )
                    )
    return problems


def _contains(outer: str, inner: str) -> bool:
    """Whether `inner` is `outer` or sits under it, as declared paths."""
    outer_parts = PurePosixPath(outer.strip("/")).parts
    inner_parts = PurePosixPath(inner.strip("/")).parts
    return inner_parts[: len(outer_parts)] == outer_parts


def _checked_source(
    root: Path, section: str, source: ContentSource, pack: Pack
) -> list[PackProblem]:
    """Walk one source: hygiene on every file, then digests if there are any."""
    directory = root / source.source
    if not directory.is_dir():
        return [PackProblem(kind="source-missing", path=source.source)]

    problems: list[PackProblem] = []
    on_disk: dict[str, str] = {}
    for relative, path in _walked(directory):
        if not _selected(relative, source):
            continue
        address = _address(source.source, relative)
        if path.is_symlink():
            # Not followed, so the two cases are told apart by where the link
            # points rather than by whether it was read.
            kind: ProblemKind = (
                "symlink" if _resolves_inside(path, root) else "escapes-root"
            )
            problems.append(PackProblem(kind=kind, path=address))
            continue
        if not _resolves_inside(path, root):
            problems.append(PackProblem(kind="escapes-root", path=address))
            continue
        on_disk[relative] = content_digest(path.read_bytes())

    recorded = _recorded_digests(pack, section, source.source)
    if recorded is None:
        return problems
    return problems + _compared(source.source, on_disk, recorded)


def _walked(directory: Path) -> list[tuple[str, Path]]:
    """Every file under `directory`, as a POSIX relative path and a path.

    `followlinks=False` so a symlinked directory is not descended into: the
    link itself is reported by the caller and its contents never become the
    pack's. `os.walk` rather than `rglob` because `rglob` follows directory
    symlinks and offers no way to say otherwise.
    """
    found: list[tuple[str, Path]] = []
    for parent, _, names in os.walk(directory, followlinks=False):
        for name in sorted(names):
            path = Path(parent) / name
            found.append((path.relative_to(directory).as_posix(), path))
    return sorted(found)


def _selected(relative: str, source: ContentSource) -> bool:
    """Whether `include` takes this file and `exclude` does not drop it."""
    included = any(
        globstar_regex(pattern).fullmatch(relative) for pattern in source.include
    )
    excluded = any(
        globstar_regex(pattern).fullmatch(relative) for pattern in source.exclude
    )
    return included and not excluded


def _address(source: str, relative: str) -> str:
    """A file's path relative to the pack root, for reporting."""
    return (PurePosixPath(source.strip("/")) / relative).as_posix()


def _resolves_inside(path: Path, root: Path) -> bool:
    """Whether `path` resolves under the pack root.

    The zip-slip check of section 7: a declared source is validated as a
    string by the model, and this is the half that only the filesystem can
    answer.
    """
    return path.resolve().is_relative_to(root.resolve())


def _recorded_digests(pack: Pack, section: str, source: str) -> dict[str, str] | None:
    """The digest map for one source, or None when there is no block at all.

    A `generated` block that exists and does not mention this source records
    an empty map rather than nothing: the author ran `pack update` and this
    tree contributed no files, so every file found under it now is genuinely
    undigested.
    """
    if pack.generated is None:
        return None
    sources: list[GeneratedSource] = getattr(pack.generated.content, section)
    for entry in sources:
        if _contains(entry.source, source) and _contains(source, entry.source):
            return entry.files
    return {}


def _compared(
    source: str, on_disk: dict[str, str], recorded: dict[str, str]
) -> list[PackProblem]:
    """The three ways a digest map and a directory can disagree."""
    problems: list[PackProblem] = []
    for relative, digest in sorted(on_disk.items()):
        if relative not in recorded:
            problems.append(
                PackProblem(kind="undigested", path=_address(source, relative))
            )
        elif recorded[relative] != digest:
            problems.append(
                PackProblem(
                    kind="digest-mismatch",
                    path=_address(source, relative),
                    recorded=recorded[relative],
                    actual=digest,
                )
            )
    for relative in sorted(recorded):
        if relative not in on_disk:
            problems.append(
                PackProblem(kind="digest-absent", path=_address(source, relative))
            )
    return problems


__all__ = [
    "PackProblem",
    "PackReport",
    "ProblemKind",
    "RefusalKind",
    "VersionRefusal",
    "content_digest",
    "validate_pack",
]
