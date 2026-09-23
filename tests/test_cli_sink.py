"""The command line's end of the engine's event stream.

One stream, two subscribers, and the whole difference between them is
filtering. These tests are about what the display subscriber ignores as much
as what it acts on.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator

import pytest

from kennis.cli import display, sink
from kennis.cli.display import ProgressUpdate
from kennis.engine.events import (
    Diagnostic,
    ItemFinished,
    ItemStarted,
    OperationFinished,
    Outcome,
    Progress,
    Severity,
)


class RecordingBar:
    """Stands in for `display.progress_bar`, recording its whole lifetime.

    A bar that is drawn is untestable through `CliRunner` - stdout is never a
    terminal there, so `progress_wanted()` is always False and the real bar
    is a no-op. What matters is not what it paints but that the sink opens
    one, advances it, and closes it, which is what this records.
    """

    def __init__(self) -> None:
        self.opened: list[tuple[str, int | None]] = []
        self.advanced: list[tuple[int | None, int | None]] = []
        self.closed = 0

    def __call__(
        self, description: str, total: int | None
    ) -> contextlib.AbstractContextManager[ProgressUpdate]:
        self.opened.append((description, total))

        @contextlib.contextmanager
        def opened() -> Iterator[ProgressUpdate]:
            try:
                yield lambda completed=None, total=None: self.advanced.append(
                    (completed, total)
                )
            finally:
                self.closed += 1

        return opened()


@pytest.fixture
def bar(monkeypatch: pytest.MonkeyPatch) -> RecordingBar:
    recorder = RecordingBar()
    monkeypatch.setattr(display, "progress_bar", recorder)
    return recorder


def test_no_progress_event_draws_no_bar(bar: RecordingBar):
    """A command that turns out to have nothing to do must not flash one."""
    with sink.DisplaySink() as shown:
        shown.emit(ItemStarted(operation="add", item="trees.md"))
        shown.emit(
            ItemFinished(operation="add", item="trees.md", outcome=Outcome.ADDED)
        )

    assert bar.opened == []


def test_the_bar_is_opened_once_and_advanced_by_every_progress_event(
    bar: RecordingBar,
):
    with sink.DisplaySink() as shown:
        shown.emit(Progress(operation="index", completed=0, total=3))
        shown.emit(Progress(operation="index", completed=2, total=3))
        shown.emit(Progress(operation="index", completed=3, total=3))

    # `Indexing`, not `index`: the engine emits the operation's name and
    # `render.progress_label` turns it into what a bar says while it runs.
    assert bar.opened == [("Indexing", 3)]
    assert bar.advanced == [(0, 3), (2, 3), (3, 3)]


def test_the_bar_closes_when_the_operation_finishes(bar: RecordingBar):
    """Before the operation line is printed, or the line lands above a bar
    that then erases itself and takes the cursor position with it."""
    with sink.DisplaySink() as shown:
        shown.emit(Progress(operation="index", completed=1, total=2))
        assert bar.closed == 0
        shown.emit(OperationFinished(operation="index", elapsed_seconds=0.1))
        assert bar.closed == 1


def test_a_second_operation_opens_a_second_bar(bar: RecordingBar):
    """`corpus index` builds three collections in one command, so the sink
    has to be reusable after it has closed a bar rather than silently
    dropping every later `Progress`."""
    with sink.DisplaySink() as shown:
        shown.emit(Progress(operation="notes", completed=1, total=1))
        shown.emit(OperationFinished(operation="notes", elapsed_seconds=0.1))
        shown.emit(Progress(operation="docs", completed=1, total=1))

    assert [description for description, _ in bar.opened] == ["Notes", "Docs"]
    assert bar.closed == 2


def test_an_unfinished_operation_still_closes_its_bar(bar: RecordingBar):
    """A command that raises must not leave a live bar behind: rich would
    keep redrawing it over whatever the error handler prints."""
    with contextlib.suppress(RuntimeError), sink.DisplaySink() as shown:
        shown.emit(Progress(operation="index", completed=1, total=2))
        raise RuntimeError("the build failed")

    assert bar.closed == 1


def test_a_diagnostic_is_shown_as_it_happens(
    bar: RecordingBar, capsys: pytest.CaptureFixture[str]
):
    """Holding it until the report would put it after the operation it is
    about, which is where a reader has stopped looking."""
    with sink.DisplaySink() as shown:
        shown.emit(
            Diagnostic(
                severity=Severity.WARNING,
                message="one document could not be read",
                resolution="kennis corpus status",
            )
        )

    written = capsys.readouterr()
    assert "could not be read" in written.out + written.err
    assert "kennis corpus status" in written.out + written.err


def test_item_events_are_the_logs_alone(
    bar: RecordingBar, capsys: pytest.CaptureFixture[str]
):
    """An item's outcome is reported afterwards from the report, where it can
    be counted and capped. Streaming it would put three hundred lines above
    the summary that was the answer."""
    with sink.DisplaySink() as shown:
        shown.emit(ItemStarted(operation="add", item="trees.md"))
        shown.emit(
            ItemFinished(
                operation="add",
                item="trees.md",
                outcome=Outcome.SKIPPED,
                reason="already in the corpus",
            )
        )

    written = capsys.readouterr()
    assert "trees.md" not in written.out + written.err


def test_the_fan_out_reaches_every_subscriber():
    """The log records what the report leaves out, so it has to see the same
    events rather than a filtered copy."""

    class Counting:
        def __init__(self) -> None:
            self.seen: list[object] = []

        def emit(self, event: object) -> None:
            self.seen.append(event)

    first, second = Counting(), Counting()
    event = Progress(operation="index", completed=1, total=2)
    sink.FanOut(first, second).emit(event)

    assert first.seen == [event]
    assert second.seen == [event]
