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


def read_document(md_path: Path, *, collection: str) -> Document:
    """Parse and validate one on-disk document.

    Raises `DocumentInvalid`, naming the path, when the file has no
    frontmatter, is missing a required field, or carries a value kennis does
    not recognise - an `owner` from an older vocabulary, for instance. The
    caller sees a domain exception rather than pydantic's, because the engine
    raises domain exceptions and a front end is what renders them.
    """
    text = md_path.read_text(encoding="utf-8")
    mapping, body = split_frontmatter(text)
    if not mapping:
        raise DocumentInvalid(f"{md_path}: no frontmatter")
    try:
        frontmatter = parse_frontmatter(collection, mapping)
    except ValidationError as error:
        raise DocumentInvalid(f"{md_path}: {_first_problem(error)}") from error

    wrapper_dir = md_path.parent if md_path.name == WRAPPED_DOCUMENT_FILENAME else None
    return Document(
        id=frontmatter.id,
        collection=collection,
        md_path=md_path,
        wrapper_dir=wrapper_dir,
        frontmatter=frontmatter,
        body=body,
    )


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
    mapping, _ = split_frontmatter(md_path.read_text(encoding="utf-8"))
    existing_id = mapping.get("id")
    if existing_id and existing_id != document_id:
        raise ValueError(
            f"refusing to overwrite {md_path} (id={existing_id}) with a "
            f"different document (id={document_id})"
        )
