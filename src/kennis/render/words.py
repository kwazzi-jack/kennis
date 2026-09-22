"""What to say about an engine value.

The engine names things and this phrases them. The rule it exists to enforce:
**where a value already carries the facts as fields, it must not also carry a
sentence built from them** - because the sentence would be what a front end
reaches for, and then the command line could not put a path in its own theme
role, wrap it for a narrow terminal, or collapse three similar reports into
one line.

Two kinds of string stay in the engine and are not this module's business. A
`resolution` that is a command is data that happens to be readable. Text
kennis is *quoting* rather than composing - a converter's output, git's
stderr, pydantic's complaint - was not written here and cannot be structured
here.
"""

from __future__ import annotations

from kennis.engine.corpus.schema import pack_id_of
from kennis.engine.history.freshness import Freshness
from kennis.engine.history.outofband import OutOfBandChange


def count_of(number: int, noun: str, plural: str | None = None) -> str:
    """`number` with `noun`, pluralised.

    Small, and here rather than at each call site because "1 documents" is
    the kind of thing that survives review and then appears in a screenshot.
    """
    if number == 1:
        return f"1 {noun}"
    return f"{number} {plural or noun + 's'}"


def describe_change(change: OutOfBandChange) -> str:
    """One sentence about a change kennis did not make."""
    if change.kind == "created":
        return (
            f"{change.path} is in the corpus but is not a document: it has no "
            "frontmatter kennis wrote, so nothing indexes or serves it"
        )
    if change.kind == "deleted":
        if change.restored:
            return f"{change.path} was deleted outside kennis and has been restored"
        return f"{change.path} was deleted outside kennis and could not be restored"
    if change.owner is not None and pack_id_of(change.owner) is not None:
        return (
            f"{change.path} is owned by {change.owner} and was edited outside "
            "kennis; the edit has been left alone"
        )
    return f"{change.path} was edited outside kennis, so the index is behind it"


def remedies_for(change: OutOfBandChange) -> tuple[str, ...]:
    """The commands that resolve a change, as commands.

    A tuple of command strings rather than one sentence containing two of
    them, so a front end can list them, number them, or offer them as a
    choice - which is what the decision channel will want.
    """
    if change.kind == "created":
        return (f"kennis corpus add '{change.path}'",)
    if change.kind == "deleted":
        return ("kennis corpus remove",)
    if change.owner is not None and pack_id_of(change.owner) is not None:
        handle = change.document_id or change.path
        return (
            f"kennis corpus restore {handle}",
            f"kennis corpus claim {handle}",
        )
    return ("kennis index",)


def describe_freshness(freshness: Freshness, collection: str) -> str:
    """One sentence about how far an index has fallen behind."""
    if freshness.state == "unverifiable":
        if freshness.unverifiable == "commit not in this corpus":
            return (
                f"the {collection} index was built somewhere else, so whether it "
                "is current cannot be checked here"
            )
        return (
            f"the {collection} index does not record the commit it was built "
            "from, so whether it is current cannot be checked"
        )

    if freshness.state == "stale":
        # Additions are named here as well as in the `in step` branch below.
        # A moved document is read as one gone and one added - git's rename
        # detection is a similarity heuristic, so the safe reading is the
        # only one available - and a sentence that mentioned only the
        # departure would report a move as a loss.
        counts = [
            count_of(freshness.changed, "document") + " changed"
            if freshness.changed
            else "",
            count_of(freshness.gone, "document") + " gone" if freshness.gone else "",
            count_of(freshness.added, "document") + " added" if freshness.added else "",
        ]
        return f"the {collection} index is stale: " + ", ".join(
            part for part in counts if part
        )

    if freshness.added:
        # Deliberately not "stale". Incomplete is not wrong: between a
        # `corpus add` and the `corpus index` that follows it, the index
        # holds nothing false, it holds less.
        return (
            f"the {collection} index is in step, with "
            + count_of(freshness.added, "document")
            + " not yet indexed"
        )
    return f"the {collection} index is in step"
