"""The command line's end of the engine's event stream.

One stream, two subscribers, and the whole difference between them is
filtering. These tests are about what the display subscriber ignores as much
as what it acts on.
"""

from __future__ import annotations

import contextlib
import io
from collections.abc import Iterator

import pytest
from rich.console import Console

from kennis.cli import display, sink
from kennis.cli.display import ProgressUpdate
from kennis.engine.events import (
    FETCH_MODEL,
    Diagnostic,
    DocumentUnsearchable,
    ItemFinished,
    ItemStarted,
    OperationFinished,
    Outcome,
    Progress,
    Severity,
)
from kennis.engine.refusals import SameContent


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
        self.items: list[str] = []
        self.closed = 0

    def __call__(
        self, description: str, total: int | None
    ) -> contextlib.AbstractContextManager[ProgressUpdate]:
        self.opened.append((description, total))

        def update(
            completed: int | None = None,
            total: int | None = None,
            *,
            item: str | None = None,
        ) -> None:
            if item is not None:
                self.items.append(item)
                return
            self.advanced.append((completed, total))

        @contextlib.contextmanager
        def opened() -> Iterator[ProgressUpdate]:
            try:
                yield update
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
                detail=DocumentUnsearchable(problem=None, path="notes/a.md"),
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
                refusal=SameContent(document_id="aaaaaaaaaa"),
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


def test_a_model_fetch_is_the_one_item_the_report_shows(
    capsys: pytest.CaptureFixture[str],
):
    """Every other `ItemStarted` is the log's alone, because an item's
    outcome is reported afterwards from the report. A model fetch has no
    later line to account for it, and without one a reader watches sixty
    seconds of nothing. Concern #209."""
    from kennis.engine.events import FETCH_MODEL

    with sink.DisplaySink() as shown:
        shown.emit(ItemStarted(operation=FETCH_MODEL, item="BAAI/bge-small-en-v1.5"))

    written = capsys.readouterr()
    assert "Downloading" in written.out
    assert "BAAI/bge-small-en-v1.5" in written.out


def test_an_ordinary_item_still_prints_nothing(capsys: pytest.CaptureFixture[str]):
    """The exception is one operation, not the event type."""
    with sink.DisplaySink() as shown:
        shown.emit(ItemStarted(operation="add", item="trees.md"))

    written = capsys.readouterr()
    assert "trees.md" not in written.out + written.err


# ---------------------------------------------------------------------------
# What the bar is working on (Brian, 2026-10-27)
# ---------------------------------------------------------------------------


def test_the_bar_names_the_item_in_hand(bar: RecordingBar):
    """A sync's bar said `Synchronising 3/14` and nothing of what it was
    doing for a minute of MinerU; each item event names what is in hand."""
    with sink.DisplaySink() as shown:
        shown.emit(Progress(operation="corpus-sync", completed=0, total=2))
        shown.emit(ItemStarted(operation="add", item="doi:10.1017/pasa.2025.10128"))
        shown.emit(Progress(operation="corpus-sync", completed=1, total=2))
        shown.emit(
            ItemFinished(
                operation="pack-describe",
                item="doi:10.1093/mnras/stae303",
                outcome=Outcome.ADDED,
            )
        )

    assert bar.items == ["doi:10.1017/pasa.2025.10128", "doi:10.1093/mnras/stae303"]


def test_an_item_named_before_the_bar_opens_is_shown_when_it_does(
    bar: RecordingBar,
):
    with sink.DisplaySink() as shown:
        shown.emit(ItemStarted(operation="add", item="trees.md"))
        shown.emit(Progress(operation="add", completed=0, total=1))

    assert bar.items == ["trees.md"]


def test_a_model_fetch_is_not_an_item_of_the_bar(bar: RecordingBar):
    with sink.DisplaySink() as shown:
        shown.emit(Progress(operation="index", completed=0, total=1))
        shown.emit(ItemStarted(operation=FETCH_MODEL, item="a-model"))

    assert bar.items == []


def test_the_drawn_bar_carries_the_item_on_its_own_line():
    """Drawn, not only passed: rendered to a string, the item is the line
    between the label and the bar."""
    written = io.StringIO()
    console = Console(file=written, width=60, color_system=None)
    stacked = display._StackedProgress(console=console, transient=True)
    stacked.add_task("Synchronising", total=2, item="doi:10.1017/pasa.2025.10128")

    console.print(stacked.get_renderable())
    lines = [line.strip() for line in written.getvalue().splitlines()]

    assert lines[0].endswith("Synchronising")
    assert lines[1] == "doi:10.1017/pasa.2025.10128"


def test_progress_bar_passes_the_item_to_what_it_draws(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    drawn: list[display._StackedProgress] = []

    class Kept(display._StackedProgress):
        def __enter__(self) -> Kept:
            drawn.append(self)
            return self

        def __exit__(self, *raised: object) -> None:
            return None

    monkeypatch.setattr(display, "progress_wanted", lambda: True)
    monkeypatch.setattr(display, "_StackedProgress", Kept)
    with display.progress_bar("Synchronising", 2) as update:
        update(item="trees.md")
        update(1, 2)

    (task,) = drawn[0].tasks
    assert task.fields["item"] == "trees.md"
    assert task.completed == 1


# ---------------------------------------------------------------------------
# The keys under a task's bar (Brian, 2026-10-27)
# ---------------------------------------------------------------------------


def test_a_started_task_names_its_keys_under_the_bar(
    monkeypatch: pytest.MonkeyPatch,
):
    from kennis.client.calls import Started

    monkeypatch.setattr(sink.sys, "platform", "linux")
    sink.say_waiting(Started(job="a-job"))
    written = io.StringIO()
    console = Console(file=written, width=200, color_system=None)
    stacked = display._StackedProgress(console=console, transient=True)
    stacked.add_task("Synchronising", total=2)

    console.print(stacked.get_renderable())
    drawn = written.getvalue()

    assert "Ctrl-C cancels the task" in drawn
    assert "Ctrl-Z" in drawn
    assert "kennis service watch a-job" in drawn
    display.set_verbosity()
    assert display._task_keys is None


def test_windows_is_not_offered_ctrl_z(monkeypatch: pytest.MonkeyPatch):
    from kennis.client.calls import Started

    monkeypatch.setattr(sink.sys, "platform", "win32")
    sink.say_waiting(Started(job="a-job"))
    try:
        assert display._task_keys is not None
        assert "Ctrl-Z" not in display._task_keys
        assert "kennis service watch a-job" in display._task_keys
    finally:
        display.set_verbosity()
