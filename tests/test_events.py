"""The event stream an engine operation reports through, and the sink tests
use to assert what it reported."""

from __future__ import annotations

import dataclasses

import pytest

from kennis.engine.events import (
    Diagnostic,
    ItemFinished,
    ItemStarted,
    OperationFinished,
    Outcome,
    Progress,
    Recorder,
    Severity,
)

EVENT_TYPES = (ItemStarted, ItemFinished, Progress, Diagnostic, OperationFinished)


@pytest.mark.parametrize("event_type", EVENT_TYPES, ids=lambda cls: cls.__name__)
def test_every_event_is_a_frozen_dataclass(event_type: type[object]):
    """An event is a record of something that already happened, so a
    subscriber must not be able to edit it before the next one sees it."""
    assert dataclasses.is_dataclass(event_type)
    assert getattr(event_type, "__dataclass_params__").frozen  # noqa: B009


def test_an_item_outcome_carries_a_reason():
    event = ItemFinished(
        operation="index",
        item="welman2024",
        outcome=Outcome.SKIPPED,
        reason="no text layer",
    )

    assert event.outcome is Outcome.SKIPPED
    assert event.reason == "no text layer"


def test_an_item_outcome_needs_no_reason():
    event = ItemFinished(operation="index", item="welman2024", outcome=Outcome.ADDED)

    assert event.reason is None


def test_outcomes_are_the_vocabulary_the_report_uses():
    assert {outcome.value for outcome in Outcome} == {
        "added",
        "removed",
        "changed",
        "unchanged",
        "skipped",
        "failed",
    }


def test_severities_are_the_three_diagnostic_shapes():
    assert {severity.value for severity in Severity} == {"warning", "error", "hint"}


def test_progress_may_run_without_a_known_total():
    """Chunking cannot say how many chunks there are until it has finished."""
    event = Progress(operation="index", completed=3)

    assert event.total is None


def test_the_recorder_keeps_events_in_the_order_they_were_emitted():
    recorder = Recorder()

    recorder.emit(ItemStarted(operation="index", item="a"))
    recorder.emit(Progress(operation="index", completed=1, total=2))
    recorder.emit(ItemFinished(operation="index", item="a", outcome=Outcome.ADDED))

    assert [type(event) for event in recorder.events] == [
        ItemStarted,
        Progress,
        ItemFinished,
    ]


def test_the_recorder_selects_events_by_type():
    recorder = Recorder()
    recorder.emit(ItemStarted(operation="index", item="a"))
    recorder.emit(ItemFinished(operation="index", item="a", outcome=Outcome.ADDED))
    recorder.emit(ItemFinished(operation="index", item="b", outcome=Outcome.SKIPPED))

    finished = recorder.events_of_type(ItemFinished)

    assert [event.item for event in finished] == ["a", "b"]


def test_the_recorder_summarises_outcomes_by_item():
    recorder = Recorder()
    recorder.emit(ItemFinished(operation="index", item="a", outcome=Outcome.ADDED))
    recorder.emit(ItemFinished(operation="index", item="b", outcome=Outcome.SKIPPED))

    assert recorder.outcomes() == {"a": Outcome.ADDED, "b": Outcome.SKIPPED}


def test_the_recorder_collects_diagnostics_whatever_their_severity():
    recorder = Recorder()
    recorder.emit(Diagnostic(severity=Severity.WARNING, message="index is stale"))
    recorder.emit(
        Diagnostic(
            severity=Severity.HINT,
            message="rebuild it",
            resolution="kennis corpus index",
        )
    )

    diagnostics = recorder.events_of_type(Diagnostic)

    assert [event.severity for event in diagnostics] == [
        Severity.WARNING,
        Severity.HINT,
    ]
    assert diagnostics[1].resolution == "kennis corpus index"


def test_an_operation_reports_what_it_finished_with():
    event = OperationFinished(
        operation="index",
        elapsed_seconds=71.4,
        counts={Outcome.ADDED: 2, Outcome.UNCHANGED: 17},
    )

    assert event.counts[Outcome.ADDED] == 2
    assert event.elapsed_seconds == pytest.approx(71.4)


def test_an_operation_that_touched_nothing_still_reports_counts():
    event = OperationFinished(operation="index", elapsed_seconds=0.0)

    assert event.counts == {}
