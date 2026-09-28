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

from collections.abc import Sequence
from pathlib import Path
from typing import Final

from kennis.engine.corpus.document import Document
from kennis.engine.corpus.layout import relative_to_corpus
from kennis.engine.corpus.schema import pack_id_of
from kennis.engine.history.freshness import Freshness
from kennis.engine.history.outofband import OutOfBandChange
from kennis.engine.rag.search import DocumentSpan
from kennis.engine.remember import IndexOutcome

# What a bar says while an operation runs. Two entries, because the engine
# emits two operation verbs; a third would have to be added here and that is
# the point - the words are not derived from the verb by a rule that would
# produce "Statusing" the day a third verb appears.
_PARTICIPLES: Final[dict[str, str]] = {"add": "Adding", "index": "Indexing"}

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


def joined(items: Sequence[str]) -> str:
    """Names in a sentence: `a`, `a and b`, `a, b and c`.

    Here rather than at each call site because a comma-separated list read
    aloud in the middle of a sentence - "declared by alpha, beta" - sounds
    like the sentence was cut off.
    """
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


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


def describe_document(collection: str, document: Document, corpus_root: Path) -> str:
    """Which document a whole-document read answered with.

    The title, the identifier and the path, because the three answer
    different questions: what it is, what to type to reach it again, and
    where in the corpus it sits. No chunk range, because there is no span -
    this is the document, all of it.

    **The path is relative to the corpus root**, which is why the root is
    an argument: `Document.md_path` is absolute because the document was
    found by walking the filesystem, while the index records the same file
    relatively. Rendering both forms addressed one corpus two ways, in two
    answers from one command, and sent the user's account name to whoever
    was reading. Concern #299.
    """
    return (
        f"[{collection}] {document.frontmatter.title}  "
        f"({document.id})  {relative_to_corpus(document.md_path, corpus_root)}"
    )


def describe_span(collection: str, span: DocumentSpan, title: str) -> str:
    """Which document was read, and which part of it.

    The title leads, as it does on a search hit and on a whole-document
    read, because that is what a person recognises; the identifier follows
    because that is what they type. The chunk range is named because `read`
    takes `--chunk`, `--before` and `--after`, and a reader who wants more
    has to know where they are before they can ask for the next part.
    """
    chunks = (
        f"chunk {span.chunk_start}"
        if span.chunk_start == span.chunk_end
        else f"chunks {span.chunk_start} to {span.chunk_end}"
    )
    return (
        f"[{collection}] {title}  ({span.document_id})  {span.source_path}  ({chunks})"
    )


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

    A `match` with an arm per value and no fall-through, so a fifth
    outcome added without a word is a type error. It replaced a chain
    of `if`s whose final `return` swallowed `deferred` into the
    sentence meant for `unindexed`, which are two different facts: one
    says there is no index, the other says there is one and somebody
    else is rebuilding it.

    `skipped` deliberately says nothing: the caller asked for no
    indexing and does not need telling what it asked for.
    """
    match outcome:
        case "indexed":
            return f"indexed, {count_of(chunk_count, 'chunk')}"
        case "skipped":
            return ""
        case "unindexed":
            return "not indexed"
        case "deferred":
            return "not indexed - another process is rebuilding it"


def describe_skipped(names: Sequence[str]) -> str:
    """Which scopes a search did not reach, and why.

    One line for every scope sharing a remedy, not one per scope: on
    a corpus with only notes indexed, a warning per collection is two
    thirds of the output before the answer, and a reader learns the
    same thing from one. The grouping is the caller's, because two
    scopes skipped with different commands need different lines.

    The sentence lives here and not on `retrieval.Skipped`, which
    carries the scope and the command as fields. Concern #81.
    """
    return f"not searched, no index yet: {', '.join(names)}"


def describe_lexical_fallback(collection: str) -> str:
    """A scope that ran lexically although more was asked of it.

    Said rather than silently downgraded: a reader comparing result
    quality needs to know they are not comparing against the dense
    index they think they configured.
    """
    return f"the {collection} index has no dense leg, so this ran as a lexical search"


def describe_busy_indexes(collections: Sequence[str]) -> str:
    """Which indexes another process was already rebuilding.

    Said because the alternative was worse than silence: a build that
    reached no collection reports zero documents, and the command line
    then printed "nothing to index" at a corpus that was full. Found by
    running the command. Concern #331.
    """
    one = len(collections) == 1
    return (
        f"{joined(list(collections))} {'is' if one else 'are'} being rebuilt "
        f"by another kennis process, so {'it was' if one else 'they were'} "
        f"left alone"
    )


def describe_uncommitted_build() -> str:
    """A build that finished while something else held the corpus.

    The index is published and searchable; only its commit waits. Said
    rather than swallowed, because a corpus whose history does not
    mention an index it has is a corpus somebody will wonder about.
    """
    return (
        "the corpus was busy, so this index is published but not yet "
        "committed; the next write records it"
    )


def needs_an_index(outcome: IndexOutcome) -> bool:
    """Whether the note that was just written is findable.

    Two ways it is not, and they share a remedy: the collection has no
    index, or one was being rebuilt while this note was written. Both
    are fixed by `kennis corpus index`, so a front end asks this
    rather than listing the values it has to care about - which is how
    `deferred` would otherwise have been missed in three places.
    """
    return outcome in ("unindexed", "deferred")


def fetching_model(model: str) -> str:
    """What is being downloaded, for the line printed before it starts.

    Named rather than numbered: huggingface's own bar counted five files,
    which told a reader nothing about what the pause was for or how much of
    their disk it would take.
    """
    return f"the embedding model {model}"


def progress_label(operation: str) -> str:
    """The name on a progress bar, for an engine operation verb.

    The engine emits `add` and `index` because those are the operation's
    names and a log line reads better with them. A bar is read while the
    work is happening, so it takes the present participle. An operation
    without an entry here is titled rather than guessed at, because a wrong
    participle reads worse than a plain word.
    """
    return _PARTICIPLES.get(operation, operation.capitalize())
