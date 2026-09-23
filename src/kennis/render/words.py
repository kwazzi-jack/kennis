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

from typing import Final

from kennis.engine.corpus.schema import pack_id_of
from kennis.engine.history.freshness import Freshness
from kennis.engine.history.outofband import OutOfBandChange
from kennis.engine.rag.models import SearchResult
from kennis.engine.rag.search import DocumentSpan
from kennis.engine.remember import IndexOutcome

# How much of a hit to show by default. Long enough to recognise the passage,
# short enough that ten hits fit on a screen.
_SNIPPET_CHARACTERS: Final = 240


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
            "frontmatter kennis wrote, so nothing indexes or serves it. Move "
            "it outside the corpus and add it from there"
        )
    if change.kind == "deleted":
        if change.restored:
            return f"{change.path} was deleted outside kennis and has been restored"
        # Not "could not be restored". A reporting command does not attempt
        # one, and describing an untried thing as failed is a false claim
        # about what kennis did. The commands that write put it back; this
        # sentence is for the one that only looks. Concern #128.
        return f"{change.path} was deleted outside kennis and is still in history"
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
        # No command. `corpus add` on a path inside the corpus *copies* it:
        # the inert file stays where it is and a second document appears
        # beside it as `dropped (2).md`. Adopting a hand-created file in
        # place is not something v0.1 can do, so naming a command that
        # duplicates it would be worse than naming none - rules.md 4.4.
        # `describe_change` says in words what to do instead. Concern #129.
        return ()
    if change.kind == "deleted":
        # `restore` rather than `remove`: the file is already gone, so the
        # action a reader needs named is the one that puts it back. Any
        # command that writes does it for them anyway (#128); this is for
        # someone who has only run `status`. With the handle, because both
        # commands take one.
        return (f"kennis corpus restore {change.document_id or change.path}",)
    if change.owner is not None and pack_id_of(change.owner) is not None:
        handle = change.document_id or change.path
        # `kennis corpus claim` is the second way forward and `design.md`
        # describes it, but it is not built. Naming it here would print an
        # instruction that fails - rules.md 4.4. It joins this tuple when the
        # command lands.
        return (f"kennis corpus restore {handle}",)
    return ("kennis corpus index",)


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


def describe_hit(collection: str, result: SearchResult) -> str:
    """One search hit, named well enough to go and read it.

    The title rather than the path, because a person recognises what they
    added by its name; the identifier because that is what `kennis read`
    takes; and the section because a long document's hit is much easier to
    place when it says which part matched.
    """
    chunk = result.chunk
    title = str(chunk.metadata.get("title") or chunk.document_id)
    # A short document's only heading is its title, and "Rivers - Rivers"
    # reads as a stutter rather than as a location.
    section = chunk.section if chunk.section != title else None
    where = f" - {section}" if section else ""
    return f"[{collection}] {title}{where}  ({chunk.document_id})"


def describe_span(collection: str, span: DocumentSpan) -> str:
    """Which document was read, and which part of it.

    The chunk range is named because `read` takes `--chunk`, `--before` and
    `--after`: a reader who wants more has to know where they are before
    they can ask for the next part.
    """
    chunks = (
        f"chunk {span.chunk_start}"
        if span.chunk_start == span.chunk_end
        else f"chunks {span.chunk_start} to {span.chunk_end}"
    )
    return f"[{collection}] {span.document_id}  {span.source_path}  ({chunks})"


def snippet_of(text: str, *, full: bool, limit: int = _SNIPPET_CHARACTERS) -> str:
    """As much of a hit's text as was asked for, cut at a word boundary.

    Cutting mid-word makes a snippet look corrupted rather than shortened,
    and the last partial word carries nothing: a reader scanning hits is
    matching on the words that are whole.
    """
    collapsed = " ".join(text.split())
    if full or len(collapsed) <= limit:
        return collapsed
    cut = collapsed[:limit]
    spaced = cut.rsplit(" ", 1)[0] if " " in cut else cut
    return f"{spaced} ..."


def describe_setting(key: str, value: object) -> str:
    """One setting, as a line a person reads.

    An empty string is shown as `(unset)` rather than as nothing: a blank
    after the equals sign is indistinguishable from a rendering fault, and
    "unset" is a real state that several settings are legitimately in.
    """
    if isinstance(value, bool):
        shown = "true" if value else "false"
    elif value == "":
        shown = "(unset)"
    else:
        shown = str(value)
    return f"{key} = {shown}"


def conversion_cost(cents: float | None) -> str:
    """What a hosted conversion cost, as a person reads it.

    `None` is "no converter reported a cost", which is what a local run
    always means, and it produces no words at all rather than a free one.
    `0.0` is a real answer - the server returns it for a document it has
    already converted - and says only that, because kennis is not told
    whether it was a cache hit or an allowance.

    Sub-dollar amounts stay in cents: a 19-page paper is 7.6 cents, and
    `$0.08` would round away the only digits that vary between documents.
    """
    if cents is None:
        return ""
    if cents == 0.0:
        return "no charge"
    if cents < 100.0:
        return f"{cents:.1f}c"
    return f"${cents / 100.0:.2f}"


def conversion_repairs(count: int) -> str:
    """How many ligature repairs a conversion made, as a person reads it.

    Nothing at all when there were none, which is the ordinary case: a
    `0 ligatures repaired` on every add would be noise, and the absence of
    the phrase is itself the good news.
    """
    if count <= 0:
        return ""
    return f"{count} ligature{'s' if count != 1 else ''} repaired"


def index_state(outcome: IndexOutcome, chunk_count: int) -> str:
    """What became of the index after a note was remembered.

    `unindexed` deliberately says nothing here: the collection has no index
    at all, and what the reader needs then is the command that builds one,
    which is a next step rather than a clause in a report line.
    """
    if outcome == "indexed":
        return f"indexed, {count_of(chunk_count, 'chunk')}"
    if outcome == "skipped":
        return ""
    return "not indexed"
