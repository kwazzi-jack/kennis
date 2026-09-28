"""An event on its way to a browser.

Server-sent events, which is a push and not a poll: the server writes
a line when something happens and the connection closes when the
operation ends. The invariant that a long-lived view checks on focus
rather than on a timer is about a page that sits open forever; this is
bounded by one operation and pushes rather than asks.

**The words are chosen here, in Python.** An event becomes a small
object whose `text` is already a sentence, so `static/progress.js`
appends lines and moves a bar without composing anything. A script
that built "3 of 12" out of two numbers would be a second place words
live, and a front end's words belong in one.

The wire format is the standard one: `data: <json>\\n\\n` per event.
Written out rather than taken from a library, because it is two lines
and the alternative is a dependency for two lines.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Final

from kennis.engine.events import (
    Diagnostic,
    Event,
    ItemFinished,
    ItemStarted,
    OperationFinished,
    Outcome,
    Progress,
)
from kennis.render.diagnostics import describe_diagnostic
from kennis.render.refusals import describe_refusal
from kennis.render.words import count_of

# The marker each outcome is shown under, the same vocabulary the
# command line prints. Not imported from `cli/`, which `gui/` may not
# touch: the same three characters chosen twice is the price of the
# peer rule, and a test asserts they agree.
MARKERS: Final[dict[Outcome, str]] = {
    Outcome.ADDED: "+",
    Outcome.REMOVED: "-",
    Outcome.CHANGED: "~",
    Outcome.UNCHANGED: "=",
    Outcome.SKIPPED: ">",
    Outcome.FAILED: "!",
}


# The same, for a sync's verdicts, which are not `Outcome`s: a sync
# distinguishes `edited` from `yours` and the outcome vocabulary does
# not. `">"` for anything unmapped, so a verdict added later shows
# rather than raising in front of a reader.
SYNC_MARKERS: Final[dict[str, str]] = {
    "write": "+",
    "rewrite": "~",
    "adopt": "~",
    "delete": "-",
    "keep": "=",
    "edited": ">",
    "yours": ">",
}


def as_message(event: Event) -> dict[str, object] | None:
    """One event as something a page can draw, or None to ignore it.

    `ItemStarted` is dropped: an item that has started has no outcome
    yet, and a line that appears and is then replaced by its own result
    reads as a list twice as long as the work.
    """
    match event:
        case ItemStarted():
            return None
        case ItemFinished():
            return {
                "kind": "item",
                "marker": MARKERS[event.outcome],
                "outcome": event.outcome.value,
                "text": event.item,
                "detail": (
                    describe_refusal(event.refusal)
                    if event.refusal is not None
                    else None
                ),
            }
        case Progress():
            return {
                "kind": "progress",
                "completed": event.completed,
                "total": event.total,
                # An indeterminate step still has something to say, and
                # a bar with no total needs words more than one with a
                # total does.
                "text": (
                    f"{event.completed} of {event.total}"
                    if event.total is not None
                    else f"{count_of(event.completed, 'step')} so far"
                ),
            }
        case Diagnostic():
            return {
                "kind": "diagnostic",
                "severity": event.severity.value,
                "text": describe_diagnostic(event.detail),
                "resolution": event.resolution,
            }
        case OperationFinished():
            return {
                "kind": "finished",
                "text": f"{event.operation} finished",
                "elapsed_seconds": round(event.elapsed_seconds, 3),
            }


def sent_event(message: dict[str, object]) -> str:
    """One message in the `text/event-stream` format."""
    return f"data: {json.dumps(message)}\n\n"


def as_stream(events: Iterator[Event], closing: dict[str, object]) -> Iterator[str]:
    """Every event as a wire message, then one that says it is over.

    The closing message is always sent, including when the operation
    raised: a stream that simply stops leaves a page showing a spinner
    with no way to tell a finished job from a dropped connection.
    """
    for event in events:
        message = as_message(event)
        if message is not None:
            yield sent_event(message)
    yield sent_event(closing)


__all__ = ["MARKERS", "SYNC_MARKERS", "as_message", "as_stream", "sent_event"]
