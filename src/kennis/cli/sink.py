"""The command line's end of the engine's event stream.

Design section 14: **the report is not the log.** One stream, two
subscribers, and the whole difference between them is filtering.

| subscriber | sees | does |
|---|---|---|
| `LogSink` | every event | writes all of it |
| `DisplaySink` | every event | draws the bar, surfaces diagnostics, nothing else |

That asymmetry is the argument for a stream over a progress callback. The log
has to record what the report leaves out - which fifteen documents were
skipped and why each one, rather than the count - and with a stream that is a
difference in what each subscriber ignores rather than a second set of
instrumentation in the engine.

**The per-item lines are not streamed.** They are printed afterwards, from
the report, through `display.details`, which caps them. A docs add of three
hundred pages would otherwise print three hundred lines above the summary
that was the answer to the question. The log keeps all three hundred.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from types import TracebackType
from typing import Final

from kennis.cli import display
from kennis.engine.events import (
    Diagnostic,
    Event,
    OperationFinished,
    Outcome,
    Progress,
    Severity,
)
from kennis.logs import LogSink

# The column glyph each outcome prints under. Layout rather than wording, so
# it lives here and not in `render/`: `display.detail` colours by the marker,
# and what a reader scans down is one character in the same column every time.
_MARKERS: Final[dict[Outcome, str]] = {
    Outcome.ADDED: "+",
    Outcome.REMOVED: "-",
    Outcome.CHANGED: "~",
    Outcome.UNCHANGED: "=",
    Outcome.SKIPPED: ">",
    Outcome.FAILED: "!",
}


def marker_for(outcome: Outcome) -> str:
    """The detail marker one outcome prints under."""
    return _MARKERS[outcome]


class DisplaySink:
    """What the person running the command sees while it runs.

    Three of the five events. `ItemStarted` and `ItemFinished` are the log's
    alone: an item's outcome is reported afterwards from the report, where it
    can be counted and capped.

    The bar is opened on the first `Progress` rather than up front, so a
    command that turns out to have nothing to do does not flash one. That is
    what the `ExitStack` is for, and why this has a lifetime.
    """

    def __init__(self) -> None:
        self._stack = contextlib.ExitStack()
        self._advance: display.ProgressUpdate | None = None

    def __enter__(self) -> DisplaySink:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._close()

    def emit(self, event: Event) -> None:
        match event:
            case Progress():
                self._progress(event)
            case Diagnostic():
                self._diagnostic(event)
            case OperationFinished():
                # The bar has to go before the operation line is printed, or
                # the line lands above a bar that then erases itself and
                # takes the cursor position with it.
                self._close()
            case _:
                return None

    def _progress(self, event: Progress) -> None:
        if self._advance is None:
            self._advance = self._stack.enter_context(
                display.progress_bar(event.operation, event.total)
            )
        self._advance(event.completed, event.total)

    @staticmethod
    def _diagnostic(event: Diagnostic) -> None:
        """Live, not held until the end.

        A diagnostic is the engine saying something is off while it carries
        on; holding it until the report would put it after the operation it
        is about, which is where a reader has stopped looking.
        """
        match event.severity:
            case Severity.ERROR:
                display.failure(event.message)
            case Severity.WARNING:
                display.note(event.message)
            case Severity.HINT:
                display.hint(event.message)
        if event.resolution:
            display.hint(event.resolution)

    def _close(self) -> None:
        self._stack.close()
        self._stack = contextlib.ExitStack()
        self._advance = None


class FanOut:
    """Every event to every subscriber, in the order they were given.

    A sink that raises would otherwise take the command down with it, so the
    display's failure to draw must not stop the log from recording - the log
    is what the failure would be diagnosed from.
    """

    def __init__(self, *sinks: object) -> None:
        self._sinks = sinks

    def emit(self, event: Event) -> None:
        for sink in self._sinks:
            emit = getattr(sink, "emit", None)
            if emit is None:
                continue
            emit(event)


@contextlib.contextmanager
def reporting() -> Iterator[FanOut]:
    """The sink a command hands to the engine, for as long as it runs."""
    with DisplaySink() as shown:
        yield FanOut(shown, LogSink())
