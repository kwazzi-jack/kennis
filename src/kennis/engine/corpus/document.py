"""Reading, writing, moving and removing one corpus document.

A document is a markdown file with validated frontmatter, optionally wrapped
in a directory beside its assets. Validation happens at both boundaries: a
model on the way to disk, the collection's model on the way back. A document
that fails it is refused with its path named, because a corrupted or
hand-broken document should fail loudly rather than sort silently under a
degenerate key.

Every write goes through `replace_file`, so a reader sees either the old
document or the new one and never a truncation. Each document is its own
atomic unit rather than the collection being one, which is what makes an
interrupted fetch resumable: fifteen papers written before a Ctrl-C are
fifteen whole papers.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from kennis.engine._atomic import replace_file
from kennis.engine.corpus.layout import WRAPPED_DOCUMENT_FILENAME
from kennis.engine.corpus.schema import (
    DocumentFrontmatter,
    collection_of,
    parse_frontmatter,
    unparse_frontmatter,
)
from kennis.engine.errors import DocumentInvalid
from kennis.engine.frontmatter import join_frontmatter, split_frontmatter


@dataclass(frozen=True, slots=True)
class Document:
    """One document as it exists on disk, read and validated."""

    id: str
    collection: str
    md_path: Path
    # The asset-wrapper directory, when this document has assets; None for a
    # bare file.
    wrapper_dir: Path | None
    frontmatter: DocumentFrontmatter
    body: str


@dataclass(frozen=True, slots=True)
class DocumentFacts:
    """What can be known about a document without requiring it to be valid.

    The two facts a batch needs - the surrogate identifier and the content
    checksum - are plain YAML keys, so they survive a document that fails
    validation. That is what lets an unreadable document keep its identifier
    reserved and keep answering for its content, instead of being skipped and
    then having its identifier reissued to something else.
    """

    md_path: Path
    wrapper_dir: Path | None
    identifier: str | None
    checksum: str | None
    # One line saying why the document is not valid, or None when it is.
    problem: str | None

    @property
    def reserved_filename(self) -> str:
        """The name this document occupies in its parent directory.

        A wrapped document's own file is always `content.md`, so what a new
        document's candidate filename would collide with is the wrapper
        directory's name, not the file inside it.
        """
        if self.wrapper_dir is not None:
            return f"{self.wrapper_dir.name}.md"
        return self.md_path.name


def _load(md_path: Path) -> tuple[dict[str, Any], str]:
    """Bytes to mapping and body, with every failure a domain exception.

    The one place a read can go wrong, so the one place the translation
    happens. `frontmatter.split_frontmatter` raises `yaml.YAMLError` and is
    right to - it is a codec at the level of `json.loads`, and naming the
    document is the job of the module that owns the concept.
    """
    try:
        text = md_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise DocumentInvalid(f"{md_path}: could not be read: {error}") from error
    try:
        mapping, body = split_frontmatter(text)
    except yaml.YAMLError as error:
        raise DocumentInvalid(
            f"{md_path}: frontmatter is not valid YAML: {_one_line(error)}"
        ) from error
    if not mapping:
        raise DocumentInvalid(f"{md_path}: no frontmatter")
    return mapping, body


def _one_line(error: Exception) -> str:
    """A multi-line library message reduced to something a `error:` line can
    carry. The whole of it is still on the exception this is chained from."""
    return " ".join(str(error).split())


def _wrapper_of(md_path: Path) -> Path | None:
    return md_path.parent if md_path.name == WRAPPED_DOCUMENT_FILENAME else None


def read_document(md_path: Path, *, collection: str) -> Document:
    """Parse and validate one on-disk document.

    Raises `DocumentInvalid`, naming the path, when the file cannot be read or
    decoded, its frontmatter is not valid YAML, it has no frontmatter, it is
    missing a required field, or it carries a value kennis does not recognise
    - an `owner` from an older vocabulary, for instance. The caller sees a
    domain exception rather than a library's, because the engine raises domain
    exceptions and a front end is what renders them.

    Use `inspect_document` where failing is not an option.
    """
    mapping, body = _load(md_path)
    try:
        frontmatter = parse_frontmatter(collection, mapping)
    except ValidationError as error:
        raise DocumentInvalid(f"{md_path}: {_first_problem(error)}") from error

    return Document(
        id=frontmatter.id,
        collection=collection,
        md_path=md_path,
        wrapper_dir=_wrapper_of(md_path),
        frontmatter=frontmatter,
        body=body,
    )


def inspect_document(md_path: Path, *, collection: str) -> DocumentFacts:
    """What is knowable about one document, without requiring it to be valid.

    Never raises. A caller uses this precisely because it cannot afford to
    fail on a document it was not asked about: one hand-edited note must not
    cost every other operation on the collection. What it could not read comes
    back as `problem`, for the caller to report rather than swallow.
    """
    wrapper_dir = _wrapper_of(md_path)
    try:
        mapping, _ = _load(md_path)
    except DocumentInvalid as error:
        return DocumentFacts(
            md_path=md_path,
            wrapper_dir=wrapper_dir,
            identifier=None,
            checksum=None,
            problem=str(error),
        )

    source = mapping.get("source")
    problem: str | None = None
    try:
        parse_frontmatter(collection, mapping)
    except ValidationError as error:
        problem = f"{md_path}: {_first_problem(error)}"

    return DocumentFacts(
        md_path=md_path,
        wrapper_dir=wrapper_dir,
        identifier=_text(mapping.get("id")),
        checksum=_text(source.get("sha256")) if isinstance(source, dict) else None,
        problem=problem,
    )


def _text(value: object) -> str | None:
    """A frontmatter value as a string, when it is one worth having."""
    return value if isinstance(value, str) and value else None


def _first_problem(error: ValidationError) -> str:
    """The offending field and why, in one line.

    pydantic's own rendering is several lines with a documentation URL, which
    reads badly inside a one-line error a front end is about to prefix with
    `error:`. The remaining problems are still on the exception it is chained
    from.
    """
    problems = error.errors()
    if not problems:
        return str(error)
    first = problems[0]
    location = ".".join(str(part) for part in first["loc"]) or "frontmatter"
    return f"{location}: {first['msg']}"


def write_document(
    md_path: Path,
    *,
    frontmatter: DocumentFrontmatter,
    body: str,
    assets: dict[str, bytes] | None = None,
) -> Document:
    """Write a new document, or overwrite an existing one, at `md_path`.

    `md_path` is always the bare-file target. When `assets` is given, the
    write lands one level deeper - `{parent}/{Title}/content.md` alongside
    each asset - so the caller never has to compute that path itself.

    The collection is taken from the frontmatter's own type rather than passed
    separately, so the model and the directory cannot disagree.
    """
    collection = collection_of(frontmatter)
    text = join_frontmatter(unparse_frontmatter(frontmatter), body)

    if assets:
        wrapper_dir = md_path.parent / md_path.stem
        leaf_path = wrapper_dir / WRAPPED_DOCUMENT_FILENAME
        _refuse_overwriting_another_document(leaf_path, frontmatter.id)
        wrapper_dir.mkdir(parents=True, exist_ok=True)
        replace_file(leaf_path, text)
        for asset_name, asset_bytes in assets.items():
            replace_file(wrapper_dir / asset_name, asset_bytes)
        return Document(
            id=frontmatter.id,
            collection=collection,
            md_path=leaf_path,
            wrapper_dir=wrapper_dir,
            frontmatter=frontmatter,
            body=body,
        )

    _refuse_overwriting_another_document(md_path, frontmatter.id)
    replace_file(md_path, text)
    return Document(
        id=frontmatter.id,
        collection=collection,
        md_path=md_path,
        wrapper_dir=None,
        frontmatter=frontmatter,
        body=body,
    )


def move_document(
    document: Document,
    *,
    target_md_path: Path,
    updates: dict[str, Any] | None = None,
) -> Document:
    """Relocate or rename a document, keeping its identifier and body intact.

    This is what the surrogate identifier buys: the document's location and
    its filename are both free to change, and every handle pointing at it
    stays valid because none of them address it by path.

    `target_md_path` is the bare-file target; a wrapped document moves its
    whole wrapper directory, so the assets travel with it. `updates` is merged
    into the frontmatter before writing, for the fields a move implies - a new
    title, or the `docs.project` that has to follow a page into a different
    project group.
    """
    mapping = {**unparse_frontmatter(document.frontmatter), **(updates or {})}
    if mapping.get("id") != document.id:
        raise ValueError("a move must not change a document's identifier")
    frontmatter = parse_frontmatter(document.collection, mapping)
    text = join_frontmatter(unparse_frontmatter(frontmatter), document.body)

    if document.wrapper_dir is not None:
        # The assets live beside content.md, so the unit that moves is the
        # directory, not the file inside it.
        target_dir = target_md_path.parent / target_md_path.stem
        if target_dir.resolve() != document.wrapper_dir.resolve():
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            document.wrapper_dir.rename(target_dir)
        leaf_path = target_dir / WRAPPED_DOCUMENT_FILENAME
        replace_file(leaf_path, text)
        return Document(
            id=document.id,
            collection=document.collection,
            md_path=leaf_path,
            wrapper_dir=target_dir,
            frontmatter=frontmatter,
            body=document.body,
        )

    replace_file(target_md_path, text)
    if target_md_path.resolve() != document.md_path.resolve():
        document.md_path.unlink()
    return Document(
        id=document.id,
        collection=document.collection,
        md_path=target_md_path,
        wrapper_dir=None,
        frontmatter=frontmatter,
        body=document.body,
    )


def remove_document(document: Document) -> None:
    """Delete a document, and its assets when it has any.

    A wrapped document's whole directory goes: the assets are part of the
    document rather than neighbours of it, and leaving them would leave a
    directory that classifies as a group holding nothing.
    """
    if document.wrapper_dir is not None:
        shutil.rmtree(document.wrapper_dir)
        return
    document.md_path.unlink(missing_ok=True)


def _refuse_overwriting_another_document(md_path: Path, document_id: str) -> None:
    """Refuse to overwrite an existing document that carries a different
    identifier.

    A wrapper directory's name is title-derived, so - rarely, but not
    impossibly - a new document's wrapper can coincide with an unrelated
    existing one. A same-identifier write is a legitimate update and passes
    through unchanged.
    """
    if not md_path.is_file():
        return
    try:
        mapping, _ = _load(md_path)
    except DocumentInvalid as error:
        # If kennis cannot tell whether the file in the way is the same
        # document, clobbering it is precisely the data loss this guard
        # exists to prevent.
        raise ValueError(
            f"refusing to overwrite {md_path}, which kennis cannot read: "
            f"{_one_line(error)}"
        ) from error
    existing_id = mapping.get("id")
    if existing_id and existing_id != document_id:
        raise ValueError(
            f"refusing to overwrite {md_path} (id={existing_id}) with a "
            f"different document (id={document_id})"
        )
