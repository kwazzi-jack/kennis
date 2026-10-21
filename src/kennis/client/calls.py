"""Calling an operation, and following a job to its end (14c).

A read is one request. A write answers with a job, whose events are read
from the stream as they come and handed to the caller's `EventSink`, so a
terminal draws them as it drew the engine's own events in-process. A job
that waits behind others says so first, through `on_waiting`.

**A refusal is raised as the error it was**, its class, message,
resolution and notes rebuilt by `load_error`, so the command line prints
it exactly as it printed one raised in its own process.

**Ctrl-C stops the watching, never the work** (Brian's default 3). The
job goes on in the service; `JobDetached` names it and the command that
follows it again.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import cast

import httpx

from kennis.engine.errors import KennisError
from kennis.engine.events import Event, EventSink
from kennis.engine.history.outofband import OutOfBandChange
from kennis.protocol.progress import Began, Elapsed, Queued
from kennis.protocol.wire import Json, dump, load, load_error


class JobDetached(KennisError):
    """The person stopped watching a job, which goes on in the service."""

    def __init__(self, job: str) -> None:
        self.message = "stopped watching; the task goes on in the kennis service"
        super().__init__(self.message, resolution=f"kennis service watch {job}")
        self.job = job


@dataclass(frozen=True, slots=True)
class Answered:
    """An operation's result, and what it put back that had been deleted by
    hand (a write's; always empty for a read)."""

    result: object
    restored: list[OutOfBandChange] = field(default_factory=list)


class _Unwatched:
    def emit(self, event: Event) -> None:
        pass


def call(
    connection: httpx.Client,
    name: str,
    arguments: Mapping[str, object],
    *,
    returns: object,
    events: EventSink | None = None,
    on_waiting: Callable[[Queued | Began], None] | None = None,
) -> Answered:
    """Call the operation `name` with `arguments`, and read its result as
    `returns`. A write is followed to its end."""
    answer = connection.post(
        f"call/{name}",
        json={"arguments": {key: dump(value) for key, value in arguments.items()}},
    )
    said = _document(answer)
    if "error" in said:
        raise load_error(said["error"])
    if "job" in said:
        return watch(
            connection,
            str(said["job"]),
            returns=returns,
            events=events,
            on_waiting=on_waiting,
        )
    return Answered(result=load(said["result"], returns))


def watch(
    connection: httpx.Client,
    job: str,
    *,
    returns: object,
    events: EventSink | None = None,
    on_waiting: Callable[[Queued | Began], None] | None = None,
) -> Answered:
    """Follow the job `job` from its beginning to its end."""
    sink = events if events is not None else _Unwatched()
    try:
        final: dict[str, Json] = {}
        for message in _messages(connection, job):
            if "event" not in message:
                final = message
                continue
            event = load(message["event"], Event | Queued | Began | Elapsed)
            if isinstance(event, Queued | Began):
                if on_waiting is not None:
                    on_waiting(event)
            elif not isinstance(event, Elapsed):
                sink.emit(cast(Event, event))
    except KeyboardInterrupt:
        raise JobDetached(job) from None
    if "error" in final:
        raise load_error(final["error"])
    if "result" not in final:
        raise KennisError(
            f"the kennis service ended task {job} without an outcome",
            resolution="kennis service status",
        )
    restored = load(final.get("restored", []), list[OutOfBandChange])
    return Answered(
        result=load(final["result"], returns),
        restored=cast(list[OutOfBandChange], restored),
    )


@dataclass(frozen=True, slots=True)
class Task:
    """A task the service holds: its id, its kind and where it is."""

    id: str
    kind: str
    state: str


def task(connection: httpx.Client, job: str) -> Task:
    """The task `job`, or the refusal naming it when the service has none.

    A task that failed is still a task: its failure is its outcome, which
    `watch` reports, and not a reason this cannot say what it is.
    """
    answer = connection.get(f"job/{job}")
    said = _document(answer)
    if answer.status_code == 404:
        raise load_error(said["error"])
    return Task(id=str(said["id"]), kind=str(said["kind"]), state=str(said["state"]))


def unfinished_tasks(connection: httpx.Client) -> list[Task]:
    """The tasks queued or running, oldest first."""
    said = _document(connection.get("jobs"))
    listed = said.get("jobs")
    if not isinstance(listed, list):
        return []
    return [
        Task(id=str(entry["id"]), kind=str(entry["kind"]), state=str(entry["state"]))
        for entry in listed
        if isinstance(entry, dict)
    ]


def _messages(connection: httpx.Client, job: str) -> Iterator[dict[str, Json]]:
    with connection.stream("GET", f"job/{job}/events") as answer:
        if answer.status_code != 200:
            answer.read()
            said = _document(answer)
            raise load_error(said.get("error"))
        for line in answer.iter_lines():
            if line.startswith("data: "):
                message = json.loads(line.removeprefix("data: "))
                if isinstance(message, dict):
                    yield message


def _document(answer: httpx.Response) -> dict[str, Json]:
    try:
        document = answer.json()
    except ValueError:
        raise KennisError(
            f"the kennis service answered {answer.status_code} without a reason",
            resolution="kennis service status",
        ) from None
    if not isinstance(document, dict):
        raise KennisError(
            "the kennis service answered something that is not a document",
            resolution="kennis service status",
        )
    return document


__all__ = [
    "Answered",
    "JobDetached",
    "Task",
    "call",
    "task",
    "unfinished_tasks",
    "watch",
]
