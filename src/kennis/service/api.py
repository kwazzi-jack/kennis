"""The routes a client of the service calls, under `/api/<version>/` (14b).

Answers are JSON written by `protocol/wire.py`. Besides the service's own
two questions - who are you, and will you stop - a client calls the
operations in `calls.py` by name and watches a write's job.

- `POST call/<name>` with `{"arguments": {...}}`: a read answers
  `{"result": ...}`, a write `202 {"job": <id>}`. Arguments the function
  does not take, or does not take in that form, are refused with 400.
- `GET job/<id>/events`: server-sent events, one `data:` message per
  event, `{"event": ...}`, ending with `{"result": ..., "restored": ...}`
  or `{"error": ...}`. From the job's beginning, whenever the watcher
  arrives.
- `GET job/<id>`: where the job is, and its outcome once it has one, for a
  client that stopped watching and came back.
- `POST job/<id>/cancel`: ask the job to stop; it ends with `TaskStopped`
  unless it had already begun to publish, which it then finishes.

A refusal is `{"error": ...}` as `dump_error` writes it: 400 for a request
the wire cannot read, 404 for a name nobody knows, 422 for a refusal the
operation itself raised.
"""

from __future__ import annotations

import inspect
import json
import os
import typing
from collections.abc import Iterator
from typing import Final

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from kennis import __version__
from kennis.build import build_of_this_process
from kennis.engine.errors import KennisError, ServiceBusy
from kennis.engine.events import EventSink
from kennis.engine.history.outofband import OutOfBandChange
from kennis.protocol.wire import API_VERSION, Json, WireError, dump, dump_error, load
from kennis.service.calls import OPERATIONS, SERVICE_PARAMETERS, Operation
from kennis.service.jobs import Job, Jobs

PREFIX: Final = f"/api/{API_VERSION}"

router = APIRouter(prefix=PREFIX)


@router.get("/hello")
def hello(request: Request) -> JSONResponse:
    """What a client checks before it uses a service: whose corpus, which
    kennis, which build of it, which API. A client of another version or
    build replaces an idle service rather than speaking to it."""
    return JSONResponse(
        {
            "kennis": __version__,
            # The code this process loaded, taken at its start (#537).
            "build": build_of_this_process(),
            "api": API_VERSION,
            "corpus": str(request.app.state.corpus_root),
            "pid": os.getpid(),
            "busy": bool(request.app.state.jobs.unfinished()),
            # Once, to whichever client asks first after a start that put
            # back a publish a killed service left half done.
            "recovered": request.app.state.recovered.take(),
        }
    )


@router.post("/stop")
def stop(request: Request) -> JSONResponse:
    """Stop once this answer is sent, unless a job is queued or running.

    Refused then, as the window's Quit is (#420): a job is a daemon thread
    and would die wherever it is, and everything it prepared would be lost
    (14e); one killed while publishing is put back at the next start.
    """
    if request.app.state.jobs.unfinished():
        return JSONResponse({"error": dump_error(ServiceBusy())}, status_code=409)
    return JSONResponse(
        {"stopping": True}, background=BackgroundTask(request.app.state.on_stop)
    )


def _refused(error: BaseException, status: int) -> JSONResponse:
    return JSONResponse({"error": dump_error(error)}, status_code=status)


def _arguments_for(operation: Operation, given: Json) -> dict[str, object]:
    """`given` read against the function's own signature.

    Raises `WireError` for a name it does not take, one of the service's
    own, a required one missing, or a value not of the declared type.
    """
    if not isinstance(given, dict):
        raise WireError(f"arguments are an object, not {given!r}")
    hints = typing.get_type_hints(operation.function)
    parameters = inspect.signature(operation.function).parameters
    for name in given:
        if name not in parameters or name in SERVICE_PARAMETERS:
            raise WireError(f"{operation.function.__name__} takes no {name!r}")
    for name, parameter in parameters.items():
        if (
            name in SERVICE_PARAMETERS
            or parameter.default is not inspect.Parameter.empty
        ):
            continue
        if name not in given:
            raise WireError(f"{operation.function.__name__} needs {name!r}")
    return {name: load(value, hints[name]) for name, value in given.items()}


@router.post("/call/{name}")
async def call(name: str, request: Request) -> JSONResponse:
    operation = OPERATIONS.get(name)
    if operation is None:
        return _refused(KennisError(f"there is no operation {name!r}"), 404)
    try:
        body = await request.json()
        arguments = _arguments_for(
            operation, body.get("arguments", {}) if isinstance(body, dict) else body
        )
    except (WireError, ValueError) as unreadable:
        return _refused(unreadable, 400)
    if operation.kind is not None:
        return _started(request.app.state.jobs, operation, operation.kind, arguments)
    return await _answered(operation, arguments)


async def _answered(operation: Operation, arguments: dict[str, object]) -> JSONResponse:
    """A read, on a worker thread so the event loop keeps serving."""
    try:
        result = await run_in_threadpool(operation.function, **arguments)
    except KennisError as refused:
        return _refused(refused, 422)
    return JSONResponse({"result": dump(result)})


def _started(
    jobs: Jobs, operation: Operation, kind: str, arguments: dict[str, object]
) -> JSONResponse:
    restored: list[OutOfBandChange] = []
    takes = inspect.signature(operation.function).parameters

    def work(events: EventSink) -> object:
        given = dict(arguments)
        if "events" in takes:
            given["events"] = events
        if "restored" in takes:
            given["restored"] = restored
        return operation.function(**given)

    job = jobs.start(kind, work, lane=operation.lane(arguments), restored=restored)
    return JSONResponse({"job": job.id}, status_code=202)


def _outcome(job: Job) -> dict[str, Json]:
    if job.error is not None:
        return {"error": dump_error(job.error)}
    if job.crash is not None:
        return {"error": dump_error(job.crash)}
    return {"result": dump(job.result), "restored": dump(job.restored)}


@router.get("/jobs")
def unfinished_jobs(request: Request) -> JSONResponse:
    """The tasks queued or running, oldest first: where a person who
    stopped watching one finds its id again."""
    unfinished: list[Job] = request.app.state.jobs.unfinished()
    return JSONResponse(
        {
            "jobs": [
                {"id": job.id, "kind": job.kind, "state": job.state}
                for job in unfinished
            ]
        }
    )


@router.get("/job/{job_id}")
def job_now(job_id: str, request: Request) -> JSONResponse:
    job = request.app.state.jobs.get(job_id)
    if job is None:
        return _refused(KennisError(f"there is no job {job_id!r}"), 404)
    said: dict[str, Json] = {"id": job.id, "kind": job.kind, "state": job.state}
    if job.done.is_set():
        said.update(_outcome(job))
    return JSONResponse(said)


@router.post("/job/{job_id}/cancel")
def cancel_job(job_id: str, request: Request) -> JSONResponse:
    """Ask a task to stop. `202 {"cancelling": true}` when it was asked, and
    `{"cancelling": false}` when it had already finished; its stream then
    ends with `TaskStopped`, or with whatever it finished as."""
    jobs: Jobs = request.app.state.jobs
    job = jobs.get(job_id)
    if job is None:
        return _refused(KennisError(f"there is no job {job_id!r}"), 404)
    asked = jobs.cancel(job)
    return JSONResponse({"cancelling": asked}, status_code=202 if asked else 200)


@router.get("/job/{job_id}/events")
def job_events(job_id: str, request: Request) -> Response:
    jobs: Jobs = request.app.state.jobs
    job = jobs.get(job_id)
    if job is None:
        return _refused(KennisError(f"there is no job {job_id!r}"), 404)

    def messages() -> Iterator[str]:
        for event in jobs.stream(job):
            yield _message({"event": dump(event)})
        yield _message(_outcome(job))

    return StreamingResponse(messages(), media_type="text/event-stream")


def _message(document: dict[str, Json]) -> str:
    return f"data: {json.dumps(document)}\n\n"


__all__ = ["PREFIX", "router"]
