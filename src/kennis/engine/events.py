"""What a long-running engine operation reports while it runs.

Rather than returning only a final result, an operation emits a sequence of
typed events: an item was started, an item finished with a particular outcome
and reason, progress advanced, a diagnostic was produced, the operation
finished with a summary. A front end subscribes and decides what to do with
them.

**One mechanism, four consumers.** The command line prints operation lines and
detail markers and drives the progress bar; the MCP server accumulates events
and returns a summary; a graphical interface updates widgets; and logging is a
subscriber that writes every event to the log file. That last one is the
reason to prefer a stream over a progress callback: the log has to record what
the report omits - which fifteen documents were skipped and why each one -
and with a stream the logging subscriber receives every event by construction,
so the asymmetry between the log and the report is a difference in filtering
rather than a difference in instrumentation.

Events are frozen: an event is a record of something that already happened, so
no subscriber may edit one before the next sees it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar, Protocol


class Outcome(Enum):
    """What became of one item.

    The same vocabulary the report uses: `ADDED`, `REMOVED` and `CHANGED` are
    what the detail markers `+`, `-` and `~` render, `UNCHANGED` is the `=`
    that carries no colour because it is the absence of news, and `SKIPPED`
    and `FAILED` are the two ways an item can be passed over - one deliberate,
    one not.
    """

    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    SKIPPED = "skipped"
    FAILED = "failed"


class Severity(Enum):
    """How much attention a diagnostic is asking for.

    Three, matching the three shapes the terminal has for one: `warning:` and
    `error:` at the margin, and `hint:` indented under the line it follows.
    """

    WARNING = "warning"
    ERROR = "error"
    HINT = "hint"


@dataclass(frozen=True, slots=True)
class ItemStarted:
    """Work began on one item. Named so a front end can show what is in flight
    before there is an outcome to report."""

    operation: str
    item: str


@dataclass(frozen=True, slots=True)
class ItemFinished:
    """Work on one item ended, with an outcome and optionally why.

    The reason is what the log keeps and the report usually drops: the report
    says a fetch skipped fifteen documents, the log says which fifteen and why
    each one.
    """

    operation: str
    item: str
    outcome: Outcome
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class Progress:
    """How far through the operation is.

    `total` is absent where it is not yet known - chunking cannot say how many
    chunks there are until it has finished - and a front end drawing a bar
    renders that as an indeterminate spinner until a later event supplies one.
    """

    operation: str
    completed: int
    total: int | None = None


@dataclass(frozen=True, slots=True)
class DocumentUnsearchable:
    """A corpus document an indexer could not read, so it is left out.

    `problem` is what the reader could say about it and is None when it
    could say nothing, which is a different sentence rather than an
    empty one.
    """

    code: ClassVar[str] = "document-unsearchable"
    problem: str | None
    path: str


@dataclass(frozen=True, slots=True)
class FrontmatterUnreadable:
    """A bundle file whose header would not parse. Indexed without it."""

    code: ClassVar[str] = "frontmatter-unreadable"
    path: str


@dataclass(frozen=True, slots=True)
class TitleDotStripped:
    """A title that looked like a dotfile name, so the dot was dropped."""

    code: ClassVar[str] = "title-dot-stripped"
    title: str


@dataclass(frozen=True, slots=True)
class DocumentSkipped:
    """A document that could not be read while adding, and was not touched.

    Distinct from `DocumentUnsearchable` although both are an unreadable
    document: the consequence differs, and the consequence is what a
    reader needs. One will not be found by a search; this one was left
    exactly as it was.
    """

    code: ClassVar[str] = "document-skipped"
    problem: str


@dataclass(frozen=True, slots=True)
class MetadataUnavailable:
    """A paper whose metadata lookup returned nothing.

    The document is still written - refusing to store a paper because a
    service was unreachable trades a small loss for a total one - so
    this says what was lost rather than that something failed.
    """

    code: ClassVar[str] = "metadata-unavailable"
    identifier: str


@dataclass(frozen=True, slots=True)
class NoPagesDiscovered:
    """A documentation site that yielded nothing.

    `path_prefix` is the surprising half and is None when there was
    none: it is derived from the URL, so a link deeper than the
    documentation root narrows the crawl without anyone asking.
    """

    code: ClassVar[str] = "no-pages-discovered"
    base_url: str
    mode: str
    path_prefix: str | None


# Every condition the engine can report that is not an item's outcome.
# A union rather than a string, so a front end switches on the condition
# and supplies its own words, and mypy tells whoever adds a seventh that
# nothing renders it yet. Each member carries a `code`, which is the
# stable name for anything that has to serialise - an MCP client cannot
# match on a Python class.
type DiagnosticDetail = (
    DocumentUnsearchable
    | FrontmatterUnreadable
    | TitleDotStripped
    | DocumentSkipped
    | MetadataUnavailable
    | NoPagesDiscovered
)


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """Something worth saying that is not an item's outcome.

    **The engine names the condition; it does not phrase it.** `detail`
    says what happened and carries the facts as fields, and `render/`
    turns one into a sentence. This used to be a `message: str` the
    engine composed and the command line printed unchanged, which was
    the one event type that bypassed `render/` entirely - harmless with
    a single front end and wrong the moment there are two. Concern #285.

    `severity` stays here rather than on each condition because it is
    orthogonal: it says how loudly to say a thing, not what the thing
    is, and it is what a front end switches on to choose its prefix.

    `resolution` is the command that would fix it, carried for the same
    reason `KennisError` carries one: the advice is chosen where the
    problem is found, not reconstructed afterwards from state.
    """

    severity: Severity
    detail: DiagnosticDetail
    resolution: str | None = None


@dataclass(frozen=True, slots=True)
class OperationFinished:
    """The operation ended. `counts` is the per-outcome tally the report
    summarises, and `elapsed_seconds` is what the operation line prints as
    `in 1.4s`."""

    operation: str
    elapsed_seconds: float
    counts: Mapping[Outcome, int] = field(default_factory=dict)


type Event = ItemStarted | ItemFinished | Progress | Diagnostic | OperationFinished


class EventSink(Protocol):
    """What an operation is handed to report through.

    One method, because the engine's side of this is deliberately trivial: a
    front end that wants to batch, filter or forward does so in its own
    implementation rather than by being asked for a richer interface.
    """

    def emit(self, event: Event) -> None: ...


class Recorder:
    """An `EventSink` that keeps everything, so a test can assert what an
    operation reported without driving a front end."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    def emit(self, event: Event) -> None:
        self.events.append(event)

    def events_of_type[EventType: Event](
        self, event_type: type[EventType]
    ) -> Sequence[EventType]:
        """Every recorded event of one type, in the order they arrived."""
        return [event for event in self.events if isinstance(event, event_type)]

    def outcomes(self) -> dict[str, Outcome]:
        """What each item ended as. A later outcome for the same item wins,
        which is what a retry means."""
        return {
            event.item: event.outcome
            for event in self.events
            if isinstance(event, ItemFinished)
        }
