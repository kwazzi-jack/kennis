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
from typing import TYPE_CHECKING, Final, Literal

from kennis.engine.context.groups import pack_of_group, project_of_group
from kennis.engine.corpus.layout import relative_to_corpus
from kennis.engine.corpus.schema import pack_id_of

if TYPE_CHECKING:
    from kennis.engine.corpus.document import Document
    from kennis.engine.docs.versions import ProjectVersions
    from kennis.engine.history.freshness import Freshness
    from kennis.engine.history.history import ReturnChanges
    from kennis.engine.history.outofband import OutOfBandChange
    from kennis.engine.rag.search import DocumentSpan
    from kennis.engine.remember import IndexOutcome

# How a hit's relevance is shown: in words, as the raw scores, or not at
# all. Here rather than in `hits.py` so that a client offering the choice
# imports none of the search (#535).
type ScoreStyle = Literal["human", "raw", "none"]

SCORE_STYLES: Final[tuple[str, ...]] = ("human", "raw", "none")

# What a bar says while an operation runs. One entry per verb the engine
# emits with a `Progress`; a new verb has to be added here, and that is
# the point - the words are not derived from the verb by a rule that would
# produce "Statusing" the day a third verb appears.
_PARTICIPLES: Final[dict[str, str]] = {
    "add": "Adding",
    "index": "Indexing",
    "backup": "Backing up",
    "corpus-sync": "Synchronising",
}

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


# `kennis corpus version` when no docs project is held by version.
NO_DOCS_VERSIONS: Final = "no documentation is held by version"


def describe_held_versions(versions: ProjectVersions) -> str:
    """A project's versions in order, the one searched by default marked:
    `2.12  2.14 (current)`."""
    return "  ".join(
        f"{version} (current)" if version == versions.current else version
        for version in versions.held
    )


def describe_current_version(project: str, version: str) -> str:
    return f"{project} {version} is the version searched by default"


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
        # Put the pack's text back, or keep the edit as a note of one's
        # own first: a pack's note is not edited in place (#514).
        return (f"kennis corpus copy {handle}", f"kennis corpus restore {handle}")
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
        #
        # **Not "in step, with 1 document not yet indexed"**, which is
        # what this said and reads as a contradiction: in step is what
        # a reader understands as synchronised. The distinction from
        # stale is kept and stated as what it is - a gap rather than an
        # error. Concern #345.
        return (
            f"the {collection} index is missing "
            + count_of(freshness.added, "document")
            + "; nothing in it is out of date"
        )
    # "Up to date", the words a reader is told wherever an index is
    # current; "in step" is the engine's state and nobody reads it.
    return f"the {collection} index is up to date"


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


def group_name(name: str) -> str:
    """A search group's name: `notes`, `context`, `context thesis` for
    another project's notes, or `pack alpha` for a pack's context, each
    searched in its own group (14g)."""
    pack = pack_of_group(name)
    if pack is not None:
        return f"pack {pack}"
    project = project_of_group(name)
    return f"context {project}" if project is not None else name


def group_title(name: str) -> str:
    """`group_name` as a heading: `Notes`, `Pack alpha`."""
    return group_name(name).capitalize()


def describe_skipped(names: Sequence[str], *, installed: bool = True) -> str:
    """Which scopes a search did not reach, and why.

    One line for every scope sharing a remedy, not one per scope: on
    a corpus with only notes indexed, a warning per collection is two
    thirds of the output before the answer, and a reader learns the
    same thing from one. The grouping is the caller's, because two
    scopes skipped with different commands need different lines.

    The sentence lives here and not on `retrieval.Skipped`, which
    carries the scope and the command as fields. Concern #81.
    """
    if not installed:
        return f"not searched, declared but not installed: {', '.join(names)}"
    return f"not searched, no index yet: {', '.join(names)}"


def describe_lexical_fallback(collection: str) -> str:
    """A scope that ran lexically although more was asked of it.

    Said rather than silently downgraded: a reader comparing result
    quality needs to know they are not comparing against the dense
    index they think they configured.
    """
    # In the words the mode control uses, "Keywords only", so the
    # warning names the choice it made for the reader (#417).
    return (
        f"the {group_name(collection)} index has no meaning leg, so this "
        "matched keywords only"
    )


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


# What each kind of job is called where a person reads it: the window's
# strip and Activity page, and a terminal waiting its turn. The keys are
# the kinds the service starts jobs under.
JOB_KINDS: Final[dict[str, str]] = {
    "add": "Add",
    "index": "Index",
    "sync": "Corpus sync",
    "context-sync": "Project context sync",
    "context": "Project context change",
    "context-index": "Project context index",
    "pack": "Pack install",
    "backup": "Backup",
    "remember": "Note",
    "copy": "Copy",
    "move": "Move",
    "remove": "Removal",
    "restore": "Putting back",
    "return": "Return",
    "version": "Docs version change",
}


def put_back_at_start(operation: str) -> str:
    """The service found a write a killed service left half made, and put
    the corpus back as it was before it (14e, #507)."""
    name = JOB_KINDS.get(operation, operation).lower()
    article = "an" if name[:1] in "aeiou" else "a"
    return (
        f"The kennis service stopped part way through {article} {name} and has "
        "put the corpus back as it was before it. Run it again."
    )


def waiting_for(behind: str, ahead: int) -> str:
    """What a job asked for behind others in its lane says until its turn
    (14b): the nearest by name, and how many more."""
    name = JOB_KINDS.get(behind, behind).lower()
    more = ahead - 1
    return f"Waiting for the {name} to finish" + (
        f", and {count_of(more, 'task')} before it" if more else ""
    )


def running_for(seconds: float) -> str:
    """How long a job has been running, for a clock that ticks once a second.

    Whole seconds, because it changes every second and a tenth that
    flickers is noise; hours and minutes past an hour, because by then the
    seconds no longer matter to anyone watching.
    """
    whole = int(seconds)
    if whole < 60:
        return f"{whole}s"
    minutes, remainder = divmod(whole, 60)
    if minutes < 60:
        return f"{minutes}m{remainder:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def progress_label(operation: str) -> str:
    """The name on a progress bar, for an engine operation verb.

    The engine emits `add` and `index` because those are the operation's
    names and a log line reads better with them. A bar is read while the
    work is happening, so it takes the present participle. An operation
    without an entry here is titled rather than guessed at, because a wrong
    participle reads worse than a plain word.
    """
    return _PARTICIPLES.get(operation, operation.capitalize())


# The published documentation, as `mkdocs.yml`'s `site_url` names it; a
# test holds the two together. A page's address is this, the page's path
# under `docs/` without `.md`, and a heading's fragment.
DOCS_SITE: Final = "https://kwazzi-jack.github.io/kennis/"


# The service that owns the corpus (milestone 14), as `kennis gui` and
# `kennis service` speak of it.
SERVICE_NOT_RUNNING: Final = "no kennis service is running for this corpus"
TOKEN_IN_THE_ADDRESS: Final = (
    "The token is in the address, and lasts as long as the service runs."
)
SERVICE_STOPS_ITSELF: Final = (
    "It stops by itself when idle, and the next command starts it again."
)


def service_running(pid: int, started: str, version: str) -> str:
    """One service, as `kennis service status` reports it."""
    return f"process {pid}, started {started}, kennis {version}"


def waiting_for_another_version(version: str, own: str) -> str:
    """Said once while a busy service of another kennis version, or of an
    earlier installation of this one (#537), finishes its task before it is
    replaced."""
    running = (
        "was started from an earlier installation of this version"
        if version == own
        else f"is version {version}"
    )
    return (
        f"the kennis service running {running} and is busy; "
        "waiting for its task to finish before replacing it"
    )


# How many titles a line about a return names before it counts the rest.
_RETURN_TITLES_SHOWN: Final = 8


def describe_return_changes(changes: ReturnChanges) -> list[str]:
    """What returning to a point would do, one line per kind of change,
    each naming its documents by title; nothing to say is said as such."""
    if changes.nothing:
        return [f"the documents are already as they were at {changes.commit[:8]}"]
    lines: list[str] = []
    for verb, held in (
        ("puts back", changes.added),
        ("removes", changes.removed),
        ("changes back", changes.changed),
    ):
        if not held:
            continue
        named = [one.title for one in held[:_RETURN_TITLES_SHOWN]]
        if len(held) > _RETURN_TITLES_SHOWN:
            named.append(f"{len(held) - _RETURN_TITLES_SHOWN} more")
        lines.append(f"{verb} {count_of(len(held), 'document')}: {joined(named)}")
    return lines


def describe_returned(commit: str, *, added: int, removed: int, changed: int) -> str:
    """What a return did, in the words `describe_return_changes` used."""
    if not (added or removed or changed):
        return f"already as at {commit[:8]}, so nothing changed"
    parts = [
        f"{count_of(count, 'document')} {verb}"
        for verb, count in (
            ("put back", added),
            ("removed", removed),
            ("changed back", changed),
        )
        if count
    ]
    return f"to {commit[:8]}: {', '.join(parts)}"


# After a return, search still reads the index built before it: the
# command line's hint closes with this, after the command.
RETURN_NEEDS_AN_INDEX: Final = "so search sees what the return changed"
