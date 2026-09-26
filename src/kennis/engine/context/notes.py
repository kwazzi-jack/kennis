"""Writing prose into a `.context/` bundle.

The bundle half of design section 12. `engine/remember.py` does this for the
corpus; the two are separate because a bundle is not a collection:

- its files are addressed by **path**, so there is no surrogate identifier to
  mint and no `Uniqueness` record to reserve a name against;
- its repository is **the user's**, so nothing here commits. Every corpus
  mutation ends in `Repository.commit`; doing that here would take over
  version control of a repository kennis does not own. The design says the
  bundle is committed with the project "if the user wants" - the user
  commits. This is the one place symmetry with the corpus would be wrong.

What *is* shared is the filename rule, from `corpus/layout.py`, because it
is the same question in both scopes - including the leading-dot strip.
In the corpus a dotted name is bookkeeping and invisible to the walk; in a
bundle it is excluded from the index. A note titled `.env notes` must not be
written and then be unfindable forever.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

from kennis.engine._atomic import replace_file
from kennis.engine.context.bundle import INDEX_DIRNAME, LANDING_FILENAME
from kennis.engine.corpus.intake import sha256_of
from kennis.engine.corpus.layout import title_filename, unique_filename
from kennis.engine.errors import InputError
from kennis.engine.events import Outcome
from kennis.engine.frontmatter import split_frontmatter
from kennis.engine.remember import title_for, titled_body


@dataclass(frozen=True, slots=True)
class BundleNote:
    """What one `remember --context` did.

    `relative_path` rather than only the absolute one, because a bundle file
    is addressed by its path within the project and that is what a report,
    a search hit and a commit message all want to say.
    """

    outcome: Outcome
    title: str
    path: Path
    relative_path: str
    elapsed_seconds: float


def remember_in_bundle(
    bundle: Path,
    text: str,
    *,
    title: str | None = None,
    group: str | None = None,
) -> BundleNote:
    """Write `text` into `bundle` as a markdown file, unless it is already there.

    Takes no lock and makes no commit. See the module docstring for why the
    second one is deliberate.
    """
    started_at = time.monotonic()
    body = text.strip()
    if not body:
        raise InputError(
            "there is nothing to remember - no text was given",
            resolution="kennis remember --help",
        )

    digest = sha256_of(body.encode("utf-8"))
    existing = _holding(bundle, digest)
    if existing is not None:
        return BundleNote(
            outcome=Outcome.UNCHANGED,
            title=_title_of(existing),
            path=existing,
            relative_path=existing.relative_to(bundle).as_posix(),
            elapsed_seconds=time.monotonic() - started_at,
        )

    chosen = title or title_for(body)
    directory = bundle / group if group else bundle
    directory.mkdir(parents=True, exist_ok=True)
    taken = {path.name for path in directory.iterdir() if path.is_file()}
    path = directory / unique_filename(title_filename(chosen), taken)

    replace_file(path, _document(chosen, titled_body(title, body), digest))
    return BundleNote(
        outcome=Outcome.ADDED,
        title=chosen,
        path=path,
        relative_path=path.relative_to(bundle).as_posix(),
        elapsed_seconds=time.monotonic() - started_at,
    )


def bundle_documents(bundle: Path) -> list[Path]:
    """Every markdown file in `bundle` that counts as knowledge.

    Excludes anything dot-prefixed at any depth - `.index/`, `.skeleton.md`,
    and whatever a user renamed to hide - and `LANDING.md`, which is a map
    rather than an answer. That pair is the *whole* exclusion rule; boepie
    needed a hardcoded name list beside the dot check because its templates
    were not dotted, and an undotted template matches every query about its
    own section while answering none of them. Concern #227.
    """
    return sorted(
        path
        for path in bundle.rglob("*.md")
        if path.name != LANDING_FILENAME
        and not any(part.startswith(".") for part in path.relative_to(bundle).parts)
    )


def bundle_files(bundle: Path) -> list[Path]:
    """Every markdown file under `bundle`, hidden ones included.

    The wider walk, and the difference from `bundle_documents` is the
    point of having both. That one answers *what is indexed*, and so
    drops a dot-prefixed path, because renaming a file to one is the
    documented way to keep it out of the index. This one answers *what is
    there*, which is what a caller deciding whether kennis wrote a file
    needs: a file the user hid is hidden from search, not from kennis.

    Only `.index/` is excluded, because kennis owns it and nothing in it
    is a document. Callers that must protect the scaffolding -
    `LANDING.md` and `.skeleton.md` - exclude it by name, since this walk
    no longer does so by side effect.
    """
    return sorted(
        path
        for path in bundle.rglob("*.md")
        if INDEX_DIRNAME not in path.relative_to(bundle).parts
    )


def _holding(bundle: Path, digest: str) -> Path | None:
    """The bundle file already holding this text, if there is one.

    A full scan. The corpus dedupes through its `Uniqueness` record; a
    bundle has no identifiers to build one from, and it is small enough that
    reading it is cheaper than maintaining one.

    **Against the recorded digest where there is one, and the body
    otherwise.** `titled_body` may put a heading above the prose that was
    given, so the stored body is no longer the text to compare - which would
    silently stop recognising a repeat and write a second copy. A file kennis
    wrote records the digest of what it was given; a hand-written one records
    nothing and never had a heading added, so hashing its body is right for
    it.
    """
    for path in bundle_documents(bundle):
        if _digest_of(path) == digest:
            return path
    return None


def _digest_of(path: Path) -> str:
    """The digest of the text this file was remembered from."""
    try:
        frontmatter, body = split_frontmatter(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return sha256_of(_body_of(path).strip().encode("utf-8"))
    source = frontmatter.get("source")
    if isinstance(source, dict):
        recorded = source.get("sha256")
        if isinstance(recorded, str):
            return recorded
    return sha256_of(body.strip().encode("utf-8"))


def _body_of(path: Path) -> str:
    """The file's text without its frontmatter, or the whole file when the
    frontmatter cannot be read.

    `split_frontmatter` raises `yaml.YAMLError` on a header that is not
    valid YAML, which the corpus path wants - a corpus document without its
    frontmatter has no identity. Here it must not: one hand-broken header
    anywhere in the bundle would otherwise take down every later write, and
    a write has nothing to do with that file. Concern #239.
    """
    text = path.read_text(encoding="utf-8")
    try:
        _, body = split_frontmatter(text)
    except yaml.YAMLError:
        return text
    return body


def _title_of(path: Path) -> str:
    """The file's recorded title, or its filename when it has none - and a
    header that will not parse counts as having none. See `_body_of`."""
    try:
        frontmatter, _ = split_frontmatter(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return path.stem
    recorded = frontmatter.get("title")
    return str(recorded) if recorded else path.stem


def _document(title: str, body: str, digest: str) -> str:
    """The file as it lands on disk.

    The shape `.skeleton.md` shows, so a remembered note and a hand-written
    one are the same kind of file. `description` is left empty rather than
    invented: the prose is one paragraph and a summary of it would be the
    paragraph again.

    `source.sha256` is the digest of the text that was given, which is what
    the corpus records for the same reason: `body` here may carry a heading
    `titled_body` added, so the file is no longer its own dedup key.
    """
    written_at = datetime.now(UTC).isoformat(timespec="seconds")
    return (
        "---\n"
        f"title: {title}\n"
        "description: ''\n"
        "owner: user\n"
        "source:\n"
        "  via: remember\n"
        f"  at: '{written_at}'\n"
        f"  sha256: {digest}\n"
        "---\n"
        "\n"
        f"{body}\n"
    )


__all__ = ["BundleNote", "bundle_documents", "bundle_files", "remember_in_bundle"]
