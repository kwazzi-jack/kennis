"""Long operations: starting one, watching it, and what it amounted to.

`started` is how every route that runs one hands it to the registry -
the add and the backup from their own modules too.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Final, assert_never

from fastapi import APIRouter, Request, Response
from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
    StreamingResponse,
)
from markupsafe import Markup

from kennis.context import existing_corpus
from kennis.engine.backup import BackupReport
from kennis.engine.context.sync import BundleSync
from kennis.engine.corpus.add import AddReport
from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.corpus.sync import CorpusSync
from kennis.engine.errors import (
    ContextNotFound,
    CorpusBusy,
    KennisError,
)
from kennis.engine.events import EventSink
from kennis.engine.history.history import read_history, removed_in
from kennis.engine.history.outofband import OutOfBandChange
from kennis.engine.history.repository import Repository
from kennis.engine.pack.store import PackInstall
from kennis.gui import words
from kennis.gui.pages import (
    ShownJob,
    shown_add,
    shown_backup,
    shown_bundle_sync,
    shown_corpus_sync,
    shown_index,
    shown_install,
)
from kennis.gui.project import bundle_of
from kennis.gui.responses import (
    TEMPLATES,
    PostedForm,
    action_page,
    from_htmx,
    job_state,
    refused,
    refused_a_post,
    refused_in_the_form,
    written,
)
from kennis.gui.stream import as_stream, sent_event
from kennis.operations import (
    IndexBuild,
    build_indexes,
    install_a_pack,
    synchronise_bundle,
    synchronise_corpus,
)
from kennis.protocol.progress import Queued
from kennis.render.words import JOB_KINDS, describe_change, waiting_for
from kennis.service.jobs import (
    CORPUS_LANE,
    INDEX_LANE,
    Job,
    Jobs,
    context_lane,
)

router = APIRouter()


# The jobs whose work ends in a corpus commit, by `started`'s kind.
_COMMITTING_JOBS: Final = frozenset({"add", "index", "sync"})


# What a job started from this window returns. `started` takes only work
# returning one of these, so mypy refuses a job whose report has no page, and
# `_shown_result` matches them exhaustively, so mypy refuses a report added
# here without one - the rule `render/refusals.py` keeps for refusals.
JobReport = (
    AddReport | IndexBuild | CorpusSync | BundleSync | PackInstall | BackupReport
)


def _shown_result(job: Job) -> ShownJob:
    """One finished job as the shape a page lays out.

    The `match` is on the report's type rather than on `job.kind`,
    because the type is what decides which renderer is correct and a
    string that disagreed with it would be a wrong page rather than an
    error.
    """
    report = job.result
    if not isinstance(report, JobReport):
        # A job started without `started` - nothing in the window does.
        return ShownJob(headline=words.NOTHING_TO_SHOW, role="role-muted")
    match report:
        case AddReport():
            return shown_add(report)
        case IndexBuild():
            return shown_index(report)
        case CorpusSync():
            return shown_corpus_sync(report)
        case BundleSync():
            return shown_bundle_sync(report)
        case PackInstall():
            return shown_install(report)
        case BackupReport():
            return shown_backup(report)
        case _:
            assert_never(report)


@dataclass(frozen=True, slots=True)
class ActivityRow:
    """One job as the Activity page lists it."""

    job_id: str
    kind: str
    state: str
    started: str


def _activity_row(job: Job) -> ActivityRow:
    return ActivityRow(
        job_id=job.id,
        kind=JOB_KINDS.get(job.kind, job.kind),
        state=job_state(job),
        started=time.strftime("%H:%M", time.localtime(job.started_wall)),
    )


def started(
    request: Request,
    kind: str,
    work: Callable[[EventSink], JobReport],
    *,
    lane: str = CORPUS_LANE,
    restored: list[OutOfBandChange] | None = None,
) -> Response:
    """Hand the work to its lane and answer with the panel watching it.

    A task asked for while another runs in the same lane waits its turn
    and says what it waits for (14b); it was refused until the service,
    because the corpus lock refused it anyway.
    """
    jobs: Jobs = request.app.state.jobs
    job = jobs.start(kind, work, lane=lane, restored=restored)
    if not from_htmx(request):
        # 303: the answer to a POST that tells the browser to GET,
        # so a reload shows the job rather than starting it again
        # (#412).
        return RedirectResponse(f"/job/{job.id}", status_code=303)
    return TEMPLATES.TemplateResponse(request, "job.html", _shown_unfinished(job))


def _shown_unfinished(job: Job) -> dict[str, object]:
    """What a job's panel is drawn with before it ends: a queued one says
    what it is waiting for, from its first recorded event."""
    shown: dict[str, object] = {"job_id": job.id, "kind": job.kind}
    if job.state == "queued" and job.history and isinstance(job.history[0], Queued):
        queued = job.history[0]
        shown |= {
            "state": "queued",
            "headline": waiting_for(queued.behind, queued.ahead),
        }
    return shown


# Every route that starts a task, and the task it starts: a domain error
# raised by one before its task began is that task, refused (#475).
JOB_ROUTES: Final[dict[str, str]] = {
    "/add": "add",
    "/backup": "backup",
    "/context-sync": "context-sync",
    "/index": "index",
    "/pack": "pack",
    "/sync": "sync",
}


def refused_task(request: Request, kind: str, error: KennisError) -> Response:
    """A task that could not begin, as the bar's job with its panel open.

    A plain form gets the job's page, as every started task does (#412).
    """
    job = request.app.state.jobs.refuse(kind, error)
    if not from_htmx(request):
        return RedirectResponse(f"/job/{job.id}", status_code=303)
    outcome = _outcome(request, job)
    return TEMPLATES.TemplateResponse(
        request,
        "job.html",
        {
            "job_id": job.id,
            "kind": job.kind,
            "state": outcome.state,
            "headline": outcome.headline,
            "outcome": Markup(bytes(outcome.answer.body).decode("utf-8")),
            "open_panel": True,
        },
    )


@router.get("/index")
def serve_index_form(request: Request, collection: str = "") -> HTMLResponse:
    # A collection in the address is checked, as the palette's
    # "Index notes" asks; anything else leaves every collection.
    return action_page(
        request,
        "/index",
        "forms/index.html",
        {
            "collections": COLLECTION_NAMES,
            "chosen": collection if collection in COLLECTION_NAMES else "",
            "index_preamble": words.INDEX_PREAMBLE,
            "index_tip": words.INDEX_TIP,
            "index_action": words.INDEX_ACTION,
        },
    )


@router.post("/index")
def start_index(request: Request, form: PostedForm) -> Response:
    chosen = str(form.get("collection") or "")
    collection = chosen if chosen in COLLECTION_NAMES else None
    context = existing_corpus()
    restored: list[OutOfBandChange] = []
    return started(
        request,
        "index",
        lambda events: build_indexes(
            context, collection, events=events, restored=restored
        ),
        lane=INDEX_LANE,
        restored=restored,
    )


@router.get("/sync")
def serve_sync_form(request: Request) -> HTMLResponse:
    return action_page(
        request,
        "/sync",
        "forms/sync.html",
        {
            "sync_preamble": words.SYNC_PREAMBLE,
            "sync_tip": words.SYNC_TIP,
            "sync_corpus_action": words.SYNC_CORPUS_ACTION,
            "sync_context_action": words.SYNC_CONTEXT_ACTION,
        },
    )


@router.post("/sync")
def start_corpus_sync(request: Request) -> Response:
    context = existing_corpus()
    restored: list[OutOfBandChange] = []
    return started(
        request,
        "sync",
        lambda events: synchronise_corpus(context, events=events, restored=restored),
        restored=restored,
    )


@router.post("/context-sync")
def start_bundle_sync(request: Request) -> Response:
    context = existing_corpus()
    bundle = bundle_of(request)
    if bundle is None:
        # `ContextNotFound` carries the command that makes one,
        # which is the whole point of the errors carrying their
        # own resolution: the advice was chosen where the problem
        # is known.
        return refused_task(request, "context-sync", ContextNotFound())
    return started(
        request,
        "context-sync",
        lambda events: synchronise_bundle(bundle, context, events=events),
        lane=context_lane(str(bundle)),
    )


@router.get("/pack")
def serve_pack_form(request: Request) -> HTMLResponse:
    return action_page(
        request,
        "/pack",
        "forms/pack.html",
        {
            "pack_preamble": words.PACK_PREAMBLE,
            "pack_tip": words.PACK_TIP,
            "pack_action": words.PACK_ACTION,
        },
    )


@router.post("/pack")
def start_pack_install(request: Request, form: PostedForm) -> Response:
    given = str(form.get("path") or "").strip()
    path = Path(given).expanduser()
    if not given or not path.is_file():
        return refused_in_the_form(request, "#pack-problem", words.no_such_pack(given))
    context = existing_corpus()
    return started(
        request, "pack", lambda events: install_a_pack(context, path, events=events)
    )


@router.get("/job/{job_id}")
def serve_job(request: Request, job_id: str) -> HTMLResponse:
    """One job: its panel for htmx, the panel inside the shell otherwise.

    The page is where a scriptless POST is sent (#412), where the
    strip's last-job link and the Activity page lead, and a reload
    of it watches the same job rather than starting another.
    """
    job = request.app.state.jobs.get(job_id)
    if job is None:
        return refused_a_post(request, words.NO_SUCH_JOB)
    shown = _shown_unfinished(job)
    if job.done.is_set():
        outcome = _outcome(request, job)
        shown |= {
            "state": outcome.state,
            "headline": outcome.headline,
            "outcome": Markup(bytes(outcome.answer.body).decode("utf-8")),
        }
    if from_htmx(request):
        return TEMPLATES.TemplateResponse(request, "job.html", shown)
    return TEMPLATES.TemplateResponse(
        request,
        "job-page.html",
        {**shown, "inline": True, "title": JOB_KINDS.get(job.kind, job.kind)},
    )


@router.get("/activity")
def serve_activity(request: Request) -> HTMLResponse:
    """What has run since kennis started, newest first.

    The registry keeps a job for an hour; this lists what it has,
    and says so when that is nothing.
    """
    return TEMPLATES.TemplateResponse(
        request,
        "activity.html",
        {
            "rows": [_activity_row(job) for job in request.app.state.jobs.recent()],
            "nothing_run": words.NOTHING_RUN,
            "changes": _changes(),
            "changes_heading": words.CHANGES_HEADING,
            "no_changes": words.NO_CHANGES,
            "return_here": words.RETURN_HERE,
            "put_back": words.PUT_BACK,
        },
    )


# Enough to see what happened lately; the full record is `kennis history`.
_CHANGES_SHOWN: Final = 30


def _changes() -> list[dict[str, object]]:
    """The corpus's newest commits, whoever made them.

    The jobs above are only this window's, and only for an hour: an add
    from a terminal or a note from an agent was nowhere on this page. A
    history that cannot be read is an empty list here - the page is still
    worth drawing - and the pane says what is wrong with the corpus.
    """
    try:
        repository = Repository(existing_corpus().corpus_root)
        entries = read_history(repository, limit=_CHANGES_SHOWN)
    except KennisError:
        return []
    return [
        {
            "when": entry.when.astimezone().strftime("%Y-%m-%d %H:%M"),
            "what": words.change_line(entry.operation, entry.scope, entry.summary),
            "commit": entry.commit[:7],
            # The newest is where the corpus is: nothing to return to.
            "return_href": f"/corpus/return?commit={entry.commit}" if position else "",
            "removed": (
                removed_in(repository, entry.commit)
                if entry.operation == "remove"
                else []
            ),
            "parent": f"{entry.commit}^",
        }
        for position, entry in enumerate(entries)
    ]


@router.get("/job/{job_id}/events")
def serve_job_events(request: Request, job_id: str) -> StreamingResponse:
    """This job's events, pushed until the operation ends.

    A sync generator on purpose: Starlette runs one in a thread, so
    the blocking `queue.get` inside it never touches the event
    loop, and the alternative is bridging a thread-safe queue into
    asyncio for no gain.
    """
    jobs: Jobs = request.app.state.jobs
    job = jobs.get(job_id)
    if job is None:
        return StreamingResponse(
            iter([sent_event({"kind": "closed", "text": words.NO_SUCH_JOB})]),
            media_type="text/event-stream",
        )
    return StreamingResponse(
        as_stream(iter(jobs.stream(job)), {"kind": "closed"}),
        media_type="text/event-stream",
        # Without this a proxy or a browser may hold the response
        # until it is complete, which is the one thing a progress
        # stream must not allow.
        headers={"cache-control": "no-store", "x-accel-buffering": "no"},
    )


@dataclass(frozen=True, slots=True)
class _Outcome:
    """A finished job's outcome, and what the bar says of it."""

    answer: HTMLResponse
    state: str
    headline: str


def _outcome(request: Request, job: Job) -> _Outcome:
    """What a finished job amounted to, and its state on the bar.

    The state is decided here once and written onto the headline as
    `data-state`, which `progress.js` reads: `failed`, `attention` when the
    reader has something to do or to see - a busy corpus to try again, a
    choice, a command, an item that failed - or `done`.
    """
    if job.crash is not None:
        said = words.job_crashed(job.crash)
        return _Outcome(
            refused(request, said, role="role-error", state="failed"), "failed", said
        )
    if job.error is not None:
        busy = isinstance(job.error, CorpusBusy)
        said = words.CORPUS_BUSY_RETRY if busy else str(job.error)
        # Busy is something to try again, not a failure of the job.
        state = "attention" if busy else "failed"
        answer = refused(
            request,
            said,
            resolution=job.error.resolution,
            role="role-warning" if busy else "role-error",
            state=state,
        )
        return _Outcome(answer, state, said)
    shown = _shown_result(job)
    # What the operation put back before it ran, said where it says what
    # it did: the command line has always said it, and a document
    # reappearing in silence is a surprise of its own.
    put_back = tuple(describe_change(change) for change in job.restored)
    asks = shown.single or any(item.outcome == "failed" for item in shown.items)
    state = "attention" if asks or shown.role == "role-warning" else "done"
    answer = TEMPLATES.TemplateResponse(
        request,
        "job-outcome.html",
        {"shown": replace(shown, notes=(*put_back, *shown.notes)), "state": state},
    )
    return _Outcome(answer, state, shown.headline)


@dataclass(frozen=True, slots=True)
class ShownBarJob:
    """The job the bar shows: running, or the newest that ended, with its
    outcome drawn by the server so a page loaded later need not ask."""

    job_id: str
    kind: str
    state: str
    headline: str = ""
    outcome: Markup = field(default_factory=Markup)


def shown_bar_job(request: Request) -> ShownBarJob | None:
    """The running job, else the newest that ended, for the bar."""
    jobs: Jobs = request.app.state.jobs
    unfinished = jobs.unfinished()
    if unfinished:
        # The newest asked for: what the reader just did, or what a page
        # loaded later finds still going.
        newest = unfinished[-1]
        shown = _shown_unfinished(newest)
        return ShownBarJob(
            newest.id,
            newest.kind,
            newest.state,
            str(shown.get("headline", "")),
        )
    for job in jobs.recent():
        if job.done.is_set():
            outcome = _outcome(request, job)
            return ShownBarJob(
                job.id,
                job.kind,
                outcome.state,
                outcome.headline,
                Markup(bytes(outcome.answer.body).decode("utf-8")),
            )
    return None


TEMPLATES.env.globals["bar_job"] = shown_bar_job


@router.get("/job/{job_id}/outcome")
def serve_job_outcome(request: Request, job_id: str) -> HTMLResponse:
    """What the job amounted to, fetched once its stream has closed.

    Rendered here rather than assembled by the script, so every
    word on the page was chosen in Python - including the repair
    forms, which are built from 9e's typed refusals.
    """
    job = request.app.state.jobs.get(job_id)
    if job is None:
        return refused(request, words.NO_SUCH_JOB)
    if not job.done.is_set():
        return refused(request, words.STILL_RUNNING)
    answer = _outcome(request, job).answer
    # Only a job that commits moves the page's revision: a bundle sync,
    # a pack install and a backup write no corpus history, so a terminal
    # that wrote meanwhile is still news. One that does commit takes the
    # corpus as it stands when the outcome is fetched, which a terminal
    # writing in that same moment would share - a window of the length of
    # one request, against a banner that was wrong after every add.
    return written(answer) if job.kind in _COMMITTING_JOBS else answer
