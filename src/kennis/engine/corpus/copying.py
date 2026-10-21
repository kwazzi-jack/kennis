"""A person's own version of a document kennis obtained (14g, #514).

What kennis obtained is not edited in place: a person who wants their own
version gets a new note, theirs, with a new identifier, and the original is
left as its source gave it. The note records what it was copied from in
`source.from` - `copy:<identifier>` - which is the field that says how any
document came to hold its text, so nothing beside it is needed.

`via: copy` and never `via: pack`, because a corpus sync finds a pack's
notes by that field: a copy carrying it would be taken for the pack's own
note at the same address.
"""

from __future__ import annotations

from typing import Final

from kennis.engine.corpus.add import Uniqueness, write_note
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.document import Document, read_document
from kennis.engine.corpus.intake import Converted
from kennis.engine.pack.content import content_digest

COPY_ORIGIN_SCHEME: Final = "copy:"


def copied_note(notes: Collection, record: Uniqueness, document: Document) -> Document:
    """A new note of the person's holding `document`'s title and text,
    filed at the top of the notes; `document` is not touched."""
    _, path = write_note(
        notes,
        record,
        converted=Converted(
            markdown=document.body,
            via="copy",
            format="markdown",
            origin=f"{COPY_ORIGIN_SCHEME}{document.id}",
            sha256=content_digest(document.body.encode("utf-8")),
        ),
        title=document.frontmatter.title,
        group=None,
    )
    return read_document(path, collection=notes.name)


__all__ = ["COPY_ORIGIN_SCHEME", "copied_note"]
