"""Where a moved document lands, and the move a docs page cannot make.

Shared by every front end that moves a document: the command line's
`corpus move` and the window's tree. It was the command line's own until
the window needed it, and a second copy of a naming rule is the rule
drifting one fix at a time.
"""

from __future__ import annotations

from pathlib import Path

from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.document import Document
from kennis.engine.corpus.layout import title_filename, unique_filename
from kennis.engine.errors import InputError
from kennis.engine.groups import group_directory


def refuse_regrouping_docs(collection: Collection, group: str | None) -> None:
    """A docs page's directory is its project, so a group cannot be set.

    Notes and literature are filed into whatever group the user names, and
    their identifiers are minted independently of it. A docs page is not:
    `add_docs` writes it to `docs/<project>/` and derives its identifier
    from `(project, page)`, so moving the file alone would leave the
    directory, the `docs.project` field and the identifier disagreeing
    about which project the page belongs to.

    Changing the project properly would change the derived identifier,
    which is the one thing `move_document` refuses - every handle pointing
    at the document addresses it by that identifier. Concern #101.
    """
    if collection.name == "docs" and group is not None:
        raise InputError(
            "a docs page's directory is its project, which is part of its "
            "identity; its group cannot be changed."
        )


def move_target(
    collection: Collection,
    document: Document,
    *,
    group: str | None,
    title: str | None,
) -> Path:
    """Where the moved document lands, as a bare-file path.

    Always the bare form, even for a wrapped document: `move_document`
    turns `<dir>/<name>.md` into `<dir>/<name>/content.md` itself, because
    the unit that moves is the wrapper directory and its assets travel
    with it.

    Each half defaults to what the document already has, so a group alone
    keeps the title and a title alone keeps the directory. An empty group
    is the collection's own top level. Recomputing the filename uses the
    two functions `add` uses - `title_filename` and `unique_filename` - so
    a moved document lands where an added one would, rather than the
    corpus having a second naming rule reachable only by moving.
    """
    directory = (
        group_directory(collection.path, group)
        if group is not None
        else holding(document)
    )
    if title is None:
        return directory / f"{stem(document)}.md"

    taken = {
        stem(other) + ".md"
        for other in collection.contents().documents
        if other.id != document.id
    }
    return directory / unique_filename(title_filename(title), taken)


def holding(document: Document) -> Path:
    """The directory the document sits in, as a move would name it.

    A wrapped document's own `md_path.parent` is its wrapper, which is part
    of the document rather than where it is filed.
    """
    return (document.wrapper_dir or document.md_path).parent


def stem(document: Document) -> str:
    """The document's name without the suffix, in bare-file terms.

    A wrapped document's markdown is always `content.md`, so its own
    filename says nothing about which document it is; the wrapper's name
    does.
    """
    if document.wrapper_dir is not None:
        return document.wrapper_dir.name
    return document.md_path.stem


__all__ = ["holding", "move_target", "refuse_regrouping_docs", "stem"]
