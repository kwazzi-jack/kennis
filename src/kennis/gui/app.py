"""The application: one guard, one page, one stylesheet.

**The guard is middleware, not a decorator.** Every request passes it,
including one for a static asset and one for a route that does not
exist. A per-route check is a check a route added in a later unit can
forget, and the route most likely to be forgotten is the one nobody
writes by hand.

**Why there is a guard at all.** The server listens on the loopback
interface, and loopback is not private on a shared machine: any other
process, and any other user account on the same host, can reach
127.0.0.1. A corpus is personal knowledge and cluster login nodes have
other users on them. Concern #309.

The token is minted per launch and never stored. It arrives once as a
query parameter, because that is what can be put in a URL handed to a
browser, and is then held in a cookie so it is not on every subsequent
request line and not in the address bar to be copied into a chat
window by accident.
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Final
from urllib.parse import quote

from fastapi import FastAPI, Request, Response
from fastapi.datastructures import FormData
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from kennis.context import Context, existing_corpus, resolve_context
from kennis.engine.context.bundle import find_bundle
from kennis.engine.context.index import CONTEXT_COLLECTION
from kennis.engine.context.status import bundle_freshness
from kennis.engine.context.sync import BundleSync
from kennis.engine.corpus.add import AddOptions, AddReport
from kennis.engine.corpus.layout import relative_to_corpus
from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.corpus.sync import CorpusSync
from kennis.engine.errors import (
    ContextNotFound,
    CorpusBusy,
    KennisError,
    UnknownCollection,
)
from kennis.engine.events import EventSink
from kennis.engine.history.repository import Repository
from kennis.engine.pack.store import PackInstall
from kennis.gui import history, words
from kennis.gui.jobs import AlreadyRunning, Job, Jobs
from kennis.gui.pages import (
    ShownJob,
    ShownOutcome,
    shown_add,
    shown_bundle_document,
    shown_bundle_sync,
    shown_corpus_sync,
    shown_document,
    shown_groups,
    shown_groups_of,
    shown_index,
    shown_install,
    shown_recents,
    shown_rows,
    shown_skips,
)
from kennis.gui.stream import as_stream, sent_event
from kennis.gui.theme import stylesheet
from kennis.holdings import freshness_of, holdings, installed_packs, revision
from kennis.operations import (
    IndexBuild,
    add_documents,
    build_indexes,
    install_a_pack,
    synchronise_bundle,
    synchronise_corpus,
)
from kennis.render.html import MarkedRange
from kennis.render.packs import describe_holdings
from kennis.retrieval import EVERY_SCOPE, SCOPE_NAMES, chunk_range, sweep
from kennis.writing import write_context_note, write_note

_HERE: Final = Path(__file__).parent
_TEMPLATES: Final = Jinja2Templates(directory=str(_HERE / "templates"))
# A global rather than a per-route context entry: the header is on
# every page, and not every route builds its context through
# `_frame`.
# The sidebar's state is a cookie rather than browser storage, so
# the server renders it and the first byte is already right. Read
# after paint from `localStorage`, a collapsed sidebar would show
# open and then collapse on every page load.
#
# A global **function** taking the request, not a constant and not
# `_frame`: it varies per request, so a constant is wrong, and not
# every route builds its context through `_frame`, so a value put
# there is undefined on the pages that do not.
_SIDEBAR_COOKIE: Final = "sidebar"
_CLOSED: Final = "closed"
_OPEN: Final = "open"


def _sidebar_state(request: Request) -> str:
    """`closed` only for exactly that value. Anything can be in a
    cookie, and the default is the state that shows what is there."""
    return _CLOSED if request.cookies.get(_SIDEBAR_COOKIE) == _CLOSED else _OPEN


_THEME_COOKIE: Final = "theme"
_SYSTEM: Final = "system"


def _theme_choice(request: Request) -> str:
    """Which palette this reader asked for, defaulting to the system.

    Only a value the interface actually offers. Anything can be in a
    cookie, and `data-theme="chartreuse"` would match neither rule -
    which happens to be harmless, but relying on that is relying on
    the cascade to absorb bad input.
    """
    asked = request.cookies.get(_THEME_COOKIE, _SYSTEM)
    offered = {value for value, _ in words.THEME_CHOICES}
    return asked if asked in offered else _SYSTEM


_TEMPLATES.env.globals["theme_choice"] = _theme_choice
_TEMPLATES.env.globals["theme_choices"] = words.THEME_CHOICES
_TEMPLATES.env.globals["theme_label"] = words.THEME_LABEL
_TEMPLATES.env.globals["sidebar_state"] = _sidebar_state
_TEMPLATES.env.globals["sidebar_links"] = words.SIDEBAR_LINKS
_TEMPLATES.env.globals["sidebar_show"] = words.SIDEBAR_SHOW
_TEMPLATES.env.globals["sidebar_hide"] = words.SIDEBAR_HIDE

# The scopes a person may search, in the order they are offered. The
# bundle last because it is the one that is not always there.
SCOPES: Final = (*COLLECTION_NAMES, CONTEXT_COLLECTION)

# The name the cookie is held under. Prefixed because it is kennis's
# and a browser may be holding cookies for other things served from
# loopback on another port - a notebook, someone else's dev server -
# and an unprefixed `token` is exactly the collision that produces.
COOKIE_NAME: Final = "kennis_gui_token"

_UNAUTHORISED: Final = "this interface needs the token it was started with"


def new_token() -> str:
    """A token for one launch.

    `secrets` rather than `random`: this is what stands between a
    personal corpus and every other account on a shared machine.
    """
    return secrets.token_urlsafe(32)


def build_app(token: str) -> FastAPI:
    """The application, guarded by `token`.

    Taken as an argument rather than read from a global, for the reason
    concern #87 gives about the engine: a value two callers can set
    differently in one process is a value a test can set at all.
    """
    app = FastAPI(title="kennis", docs_url=None, redoc_url=None)
    # On the application rather than in a module-level variable, so a
    # test builds its own and two applications in one process do not
    # share a job list.
    app.state.jobs = Jobs()

    @app.middleware("http")
    async def require_token(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        supplied = request.query_params.get("token") or request.cookies.get(COOKIE_NAME)
        if not secrets.compare_digest(supplied or "", token):
            # 401 and not a redirect. A refusal that redirects is a
            # refusal a client follows, and then the test that proves
            # the guard works reports 200 for a request that was
            # turned away.
            return JSONResponse({"detail": _UNAUTHORISED}, status_code=401)
        answer = await call_next(request)
        if request.query_params.get("token"):
            answer.set_cookie(
                COOKIE_NAME,
                token,
                httponly=True,
                samesite="strict",
                # No `secure`: the interface is served over plain HTTP
                # on loopback, and a secure cookie would never be sent
                # back, so the guard would refuse every request after
                # the first.
            )
        return answer

    # Mounted, not routed one file at a time. The guard above is
    # application middleware, so it runs for a mounted app too - which
    # is the case a per-route decorator would have missed, and the one
    # nobody would have thought to check.
    app.mount(
        "/static/vendor",
        StaticFiles(directory=str(_HERE / "static" / "vendor")),
        name="vendor",
    )

    @app.get("/static/kennis.css")
    async def serve_stylesheet() -> PlainTextResponse:
        return PlainTextResponse(stylesheet(), media_type="text/css")

    @app.get("/static/{name}.js")
    async def serve_script(name: str) -> PlainTextResponse:
        # The interface's own scripts, as opposed to the vendored ones
        # under `/static/vendor`. `name` is matched against what is
        # actually there rather than joined into a path, so no request
        # can walk out of this directory.
        available = {path.stem: path for path in (_HERE / "static").glob("*.js")}
        found = available.get(name)
        if found is None:
            return PlainTextResponse("", status_code=404)
        return PlainTextResponse(
            found.read_text(encoding="utf-8"), media_type="text/javascript"
        )

    @app.get("/")
    async def serve_search(
        request: Request, q: str = "", scope: str = EVERY_SCOPE
    ) -> HTMLResponse:
        context = _hits_context(q, scope)
        # Only with no query. With one, the results have that space -
        # a page showing both would put what was looked for before
        # beside what was just found, which is two answers to one
        # question.
        context["recents"] = [] if q.strip() else shown_recents(history.recent())
        context["recents_heading"] = words.RECENTS_HEADING
        context["recents_clear"] = words.RECENTS_CLEAR
        return _TEMPLATES.TemplateResponse(request, "search.html", context)

    @app.post("/history/clear")
    async def clear_history(request: Request) -> HTMLResponse:
        # A POST, because a GET that writes is one a prefetcher will
        # follow and this one destroys. The reader's own words are
        # in here and there has to be a way to remove them.
        history.clear()
        context = _hits_context("", EVERY_SCOPE)
        context["recents"] = []
        context["recents_heading"] = words.RECENTS_HEADING
        context["recents_clear"] = words.RECENTS_CLEAR
        return _TEMPLATES.TemplateResponse(request, "recents.html", context)

    @app.get("/hits")
    async def serve_hits(
        request: Request, q: str = "", scope: str = EVERY_SCOPE
    ) -> HTMLResponse:
        # The partial htmx swaps in. The same context as the page, so
        # a first load and a keystroke cannot disagree about what a
        # result looks like.
        answer = _TEMPLATES.TemplateResponse(
            request, "hits.html", _hits_context(q, scope)
        )
        # **The address the reader should end up at, not the one that
        # was fetched.** `hx-push-url="true"` pushes the request URL,
        # which is this route - so Back and reload rendered the bare
        # fragment with no page around it. Found by walking the
        # interface, not by the suite. Concern #340.
        answer.headers["HX-Push-Url"] = f"/?q={quote(q)}&scope={quote(scope)}"
        return answer

    @app.get("/held")
    async def serve_holdings(request: Request) -> HTMLResponse:
        context = existing_corpus()
        held = holdings(context)
        return _TEMPLATES.TemplateResponse(
            request,
            "holdings.html",
            {
                "rows": shown_rows(held),
                "empty": not any(holding.documents for holding in held),
                "packs": describe_holdings(installed_packs(context)),
                "nothing_held": words.NOTHING_HELD,
                "no_packs": words.NO_PACKS,
                **_frame(context),
            },
        )

    @app.get("/collection/{collection}")
    async def serve_collection(request: Request, collection: str) -> HTMLResponse:
        context = existing_corpus()
        if collection not in COLLECTION_NAMES:
            return _problem(
                request, UnknownCollection(words.unknown_scope(collection, SCOPES))
            )
        groups, unreadable = shown_groups(context.corpus_root, collection)
        held = next(h for h in holdings(context) if h.collection == collection)
        return _TEMPLATES.TemplateResponse(
            request,
            "collection.html",
            {
                "collection": collection,
                "groups": groups,
                "summary": words.describe_count(held),
                "unreadable": words.unreadable_note(unreadable),
                **_frame(context),
            },
        )

    @app.get("/remember")
    async def serve_remember_form(request: Request) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(
            request, "remember.html", _remember_context(None)
        )

    @app.post("/remember")
    async def accept_remembered(request: Request) -> HTMLResponse:
        """Write a note, and answer with the outcome alone.

        **POST, not GET.** A GET that writes is a GET something will
        follow - a prefetcher, a link checker, a restored history
        entry - and each of those would write a note nobody asked
        for.

        Cross-site protection is the token cookie's `samesite=strict`:
        a form on another site cannot make the browser send it, so
        such a request arrives without the token and the guard in
        `require_token` refuses it before this runs.
        """
        form = await request.form()
        text_given = str(form.get("text") or "")
        title = str(form.get("title") or "") or None
        group = str(form.get("group") or "") or None
        to_context = str(form.get("target") or "notes") == "context"
        outcome = _remembered(
            text_given, title=title, group=group, to_context=to_context
        )
        return _TEMPLATES.TemplateResponse(
            request, "outcome.html", {"outcome": outcome}
        )

    @app.get("/revision")
    async def serve_revision() -> JSONResponse:
        # Answered on demand, never pushed. One `git rev-parse`, which
        # is cheap enough to ask when a window regains focus and far
        # too expensive to poll. Concern #311.
        return JSONResponse({"revision": revision(existing_corpus())})

    @app.get("/document/{collection}/{document_id}")
    async def serve_document(
        request: Request,
        collection: str,
        document_id: str,
        images: str = "",
        chunk: str = "",
        q: str = "",
    ) -> HTMLResponse:
        load_remote = images == "on"
        context = existing_corpus()
        marked, withheld = _marked(context, collection, document_id, chunk)
        try:
            document = shown_document(
                context.corpus_root,
                collection,
                document_id,
                load_remote_images=load_remote,
                marked=marked,
            )
        except KennisError as error:
            return _problem(request, error)
        return _TEMPLATES.TemplateResponse(
            request,
            "document.html",
            {
                "document": document,
                "load_remote_images": load_remote,
                "blocked_note": words.IMAGES_BLOCKED,
                "blocked_action": words.LOAD_IMAGES,
                "mark_withheld": words.MARK_WITHHELD if withheld else None,
                "question": q,
                "back_to_search": words.BACK_TO_SEARCH,
            },
        )

    def _started(
        request: Request, kind: str, work: Callable[[EventSink], object]
    ) -> HTMLResponse:
        """Hand the work to a thread and answer with the panel watching it.

        A second operation is refused rather than queued, and says so:
        the corpus lock would refuse it anyway with `timeout=0`, so the
        limit is honest, and dropping a click in silence is not.
        """
        try:
            job = app.state.jobs.start(kind, work)
        except AlreadyRunning as busy:
            return _TEMPLATES.TemplateResponse(
                request,
                "job.html",
                {
                    "job_id": busy.running,
                    "kind": kind,
                    "problem": words.BUSY_WITH_ANOTHER,
                },
            )
        return _TEMPLATES.TemplateResponse(
            request, "job.html", {"job_id": job.id, "kind": job.kind}
        )

    @app.get("/bundle/{relative_path:path}")
    async def serve_bundle_document(
        request: Request,
        relative_path: str,
        images: str = "",
        chunk: str = "",
        q: str = "",
    ) -> HTMLResponse:
        """One note out of this project's bundle.

        A separate route from `/document/...` because it reads a
        separate store: the bundle is in the user's repository and is
        not a collection of the corpus. Linking a context hit into
        the corpus route is what answered a quarter of all searches
        with "unknown collection". Concern #332.
        """
        bundle = find_bundle()
        if bundle is None:
            return _problem(request, ContextNotFound())
        marked, withheld = _marked_in_bundle(bundle, relative_path, chunk)
        load_remote = images == "on"
        try:
            document = shown_bundle_document(
                bundle,
                relative_path,
                load_remote_images=load_remote,
                marked=marked,
            )
        except KennisError as error:
            return _problem(request, error)
        return _TEMPLATES.TemplateResponse(
            request,
            "document.html",
            {
                "document": document,
                "load_remote_images": load_remote,
                "blocked_note": words.IMAGES_BLOCKED,
                "blocked_action": words.LOAD_IMAGES,
                "mark_withheld": words.MARK_WITHHELD if withheld else None,
                "question": q,
                "back_to_search": words.BACK_TO_SEARCH,
            },
        )

    @app.get("/manage")
    async def serve_manage(request: Request) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(request, "manage.html", _manage_context())

    @app.post("/manage/add")
    async def start_add(request: Request) -> HTMLResponse:
        """Start an add and answer with somewhere to watch it.

        Answers at once rather than when the work is done: one PDF is
        twenty seconds of MinerU and a documentation crawl is minutes,
        and a POST that returns at the end is a browser that appears to
        have hung.
        """
        form = await request.form()
        identifiers = _lines(str(form.get("identifiers") or ""))
        destination = str(form.get("collection") or "notes")
        if not identifiers:
            return _refused(request, words.NOTHING_TO_ADD)
        if destination not in COLLECTION_NAMES:
            return _refused(request, words.unknown_collection(destination))
        context = existing_corpus()
        options = _add_options(context, form)
        return _started(
            request,
            "add",
            lambda events: add_documents(
                context, destination, identifiers, options, events=events
            ),
        )

    @app.post("/manage/index")
    async def start_index(request: Request) -> HTMLResponse:
        form = await request.form()
        chosen = str(form.get("collection") or "")
        collection = chosen if chosen in COLLECTION_NAMES else None
        context = existing_corpus()
        return _started(
            request,
            "index",
            lambda events: build_indexes(context, collection, events=events),
        )

    @app.post("/manage/sync")
    async def start_corpus_sync(request: Request) -> HTMLResponse:
        context = existing_corpus()
        return _started(
            request, "sync", lambda events: synchronise_corpus(context, events=events)
        )

    @app.post("/manage/context-sync")
    async def start_bundle_sync(request: Request) -> HTMLResponse:
        context = existing_corpus()
        bundle = find_bundle()
        if bundle is None:
            # `ContextNotFound` carries the command that makes one,
            # which is the whole point of the errors carrying their
            # own resolution: the advice was chosen where the problem
            # is known.
            refusal = ContextNotFound()
            return _refused(request, str(refusal), resolution=refusal.resolution)
        return _started(
            request,
            "context-sync",
            lambda events: synchronise_bundle(bundle, context, events=events),
        )

    @app.post("/manage/pack")
    async def start_pack_install(request: Request) -> HTMLResponse:
        form = await request.form()
        given = str(form.get("path") or "").strip()
        path = Path(given).expanduser()
        if not given or not path.is_file():
            return _refused(request, words.no_such_pack(given))
        context = existing_corpus()
        return _started(
            request, "pack", lambda events: install_a_pack(context, path, events=events)
        )

    @app.get("/job/{job_id}")
    async def serve_job(request: Request, job_id: str) -> HTMLResponse:
        job = app.state.jobs.get(job_id)
        if job is None:
            return _refused(request, words.NO_SUCH_JOB)
        return _TEMPLATES.TemplateResponse(
            request, "job.html", {"job_id": job.id, "kind": job.kind}
        )

    @app.get("/job/{job_id}/events")
    async def serve_job_events(job_id: str) -> StreamingResponse:
        """This job's events, pushed until the operation ends.

        A sync generator on purpose: Starlette runs one in a thread, so
        the blocking `queue.get` inside it never touches the event
        loop, and the alternative is bridging a thread-safe queue into
        asyncio for no gain.
        """
        jobs: Jobs = app.state.jobs
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

    @app.get("/job/{job_id}/outcome")
    async def serve_job_outcome(request: Request, job_id: str) -> HTMLResponse:
        """What the job amounted to, fetched once its stream has closed.

        Rendered here rather than assembled by the script, so every
        word on the page was chosen in Python - including the repair
        forms, which are built from 9e's typed refusals.
        """
        job = app.state.jobs.get(job_id)
        if job is None:
            return _refused(request, words.NO_SUCH_JOB)
        if not job.done.is_set():
            return _refused(request, words.STILL_RUNNING)
        if job.error is not None:
            return _refused(
                request,
                words.CORPUS_BUSY_RETRY
                if isinstance(job.error, CorpusBusy)
                else str(job.error),
                resolution=job.error.resolution,
            )
        return _TEMPLATES.TemplateResponse(
            request, "job-outcome.html", {"shown": _shown_result(job)}
        )

    return app


def _remember_context(outcome: ShownOutcome | None) -> dict[str, object]:
    """What the writing page needs, with or without an answer yet."""
    return {
        "outcome": outcome,
        "preamble": words.REMEMBER_PREAMBLE,
        "placeholder": words.REMEMBER_PLACEHOLDER,
        "title_hint": words.TITLE_HINT,
        "group_hint": words.GROUP_HINT,
        "action": words.REMEMBER_ACTION,
        **_frame(existing_corpus()),
    }


def _remembered(
    text: str, *, title: str | None, group: str | None, to_context: bool
) -> ShownOutcome:
    """Write, and turn whatever happened into something to show.

    Every domain failure becomes an outcome rather than a page: the
    text the person typed is still in the box, and replacing the page
    would lose it. `CorpusBusy` is the case that makes this matter -
    a `corpus index` running in a terminal refuses this write, and it
    is worth retrying rather than worth an error page.
    """
    if not text.strip():
        return ShownOutcome(message=words.NOTHING_TO_REMEMBER, role="role-warning")
    try:
        if to_context:
            note, bundle_name = write_context_note(text, title=title, group=group)
            return words.describe_written_to_bundle(note, bundle_name)
        report = write_note(text, title=title, group=group)
        return words.describe_written(
            report, relative_to_corpus(report.path, existing_corpus().corpus_root)
        )
    except CorpusBusy:
        return ShownOutcome(message=words.CORPUS_BUSY, role="role-warning")
    except KennisError as error:
        return ShownOutcome(
            message=str(error), role="role-error", resolution=error.resolution
        )


def _marked(
    context: Context, collection: str, document_id: str, chunk: str
) -> tuple[MarkedRange | None, bool]:
    """The passage to mark, and whether one was withheld.

    Two `None`s that mean different things, which is why the second
    value exists. *No chunk was asked for* - the reader opened the
    document from a listing - should say nothing. *A chunk was asked
    for and cannot be placed* has to say so, because the reader
    followed a link to a passage and would otherwise be left looking
    for it.

    **The offsets belong to the index, so a stale index withholds
    them.** They address the document as it was when it was indexed,
    and once it has changed they point at text that has moved. A mark
    on the wrong paragraph is worse than no mark: it is a confident
    claim, and the reader has no way to tell it is wrong.
    `unverifiable` withholds too - "kennis cannot check" is not
    "kennis checked and it is fine".
    """
    if not chunk:
        return None, False
    try:
        index = int(chunk)
    except ValueError:
        # Arrived in a query string, so it can be anything. Not an
        # error page: the document is there and is what was asked for.
        return None, False

    freshness = freshness_of(context, Repository(context.corpus_root), collection)
    if freshness is None:
        # No index at all, so there is nothing to place the passage
        # against and nothing was withheld. `chunk_range` would answer
        # None a moment later; asking first keeps it off the disk.
        return None, False
    if freshness.state != "in step":
        return None, True

    found = chunk_range(context, collection, document_id, index)
    if found is None:
        return None, False
    start, end = found
    return MarkedRange(start=start, end=end, anchor=f"chunk-{index}"), False


def _marked_in_bundle(
    bundle: Path, relative_path: str, chunk: str
) -> tuple[MarkedRange | None, bool]:
    """`_marked`, for the scope that is not in the corpus.

    The same three decisions and the same order, over a different
    index and a different freshness: `bundle_freshness` answers the
    question `freshness_of` answers for a collection, and cannot be
    the same function because a bundle has no git history to compare
    against. Written out rather than abstracted over the two, because
    the two only look alike - the shared part is three lines and the
    differing part is every value in them.
    """
    if not chunk:
        return None, False
    try:
        index = int(chunk)
    except ValueError:
        return None, False

    freshness = bundle_freshness(bundle)
    if freshness is None:
        return None, False
    if freshness.state != "in step":
        return None, True

    found = chunk_range(resolve_context(), CONTEXT_COLLECTION, relative_path, index)
    if found is None:
        return None, False
    start, end = found
    return MarkedRange(start=start, end=end, anchor=f"chunk-{index}"), False


def _frame(context: Context) -> dict[str, object]:
    """What every page carries regardless of what it shows.

    The revision is the page's own timestamp, in the only unit that
    matters here: a commit the corpus was at when this was drawn. The
    message travels with it so the script does not compose words.
    """
    return {
        "revision": revision(context) or "",
        "corpus_changed": words.CORPUS_CHANGED,
    }


def _hits_context(question: str, scope: str) -> dict[str, object]:
    """What a search page and its partial both need.

    A failure becomes fields rather than an exception: a search box
    whose scope has no index should say so above the box the person is
    still typing in, not replace the page with an error.

    **Every scope by default**, through the same sweep the command
    line runs. Searching one collection at a time and defaulting to
    notes meant a reader looking for a paper from a cold start was
    answered nothing at all until they knew to change a dropdown.
    Concern #314 is what made one sweep possible.
    """
    context: dict[str, object] = {
        **_frame(existing_corpus()),
        "question": question,
        "scope": scope,
        "scopes": SCOPES,
        "everywhere": EVERY_SCOPE,
        "everywhere_label": words.EVERYWHERE_LABEL,
        # The hint for the scope this page was drawn with, and one for
        # every scope the select offers. Changing the select has to
        # change the box without a round trip, and the words must not
        # move into a script to manage it: each option carries the
        # sentence, and `static/hint.js` copies the selected one.
        "search_hint": words.search_hint_for(scope),
        "scope_hints": {
            name: words.search_hint_for(name) for name in (EVERY_SCOPE, *SCOPES)
        },
        "search_action": words.SEARCH_ACTION,
        "searching": words.SEARCHING,
        "scope_label": words.SCOPE_LABEL,
        "groups": [],
        "skips": [],
        "nothing": words.NOTHING_FOUND,
        "problem": None,
        "resolution": None,
    }
    if not question:
        return context
    if scope not in SCOPES and scope != EVERY_SCOPE:
        context["problem"] = words.unknown_scope(scope, SCOPES)
        return context
    asked = SCOPE_NAMES if scope == EVERY_SCOPE else (scope,)
    try:
        found = sweep(question, scopes=asked, named=scope != EVERY_SCOPE)
        context["groups"] = shown_groups_of(found, question)
        context["skips"] = shown_skips(found)
        # Here rather than in either route, because both run a search
        # and a reload, a Back and a keystroke must all record the
        # same way. A refused search is not recorded: it found
        # nothing because it could not run, which is not something to
        # offer the reader again.
        wanted = existing_corpus().settings.retrieval.default_top_k
        history.record(
            question,
            scope=scope,
            hits=sum(len(hits) for hits in found.groups.values()),
            # Any scope that filled its quota had more to give, so
            # the total is a floor. `default_top_k` is 3 per scope,
            # which is why this is the usual case rather than the
            # exception.
            capped=any(len(hits) >= wanted for hits in found.groups.values()),
        )
    except KennisError as error:
        context["problem"] = str(error)
        context["resolution"] = error.resolution
    return context


def _problem(request: Request, error: KennisError) -> HTMLResponse:
    """A domain failure as a page.

    Design section 20: the engine raises, and each front end turns it
    into what that front end has - an exit code, a tool error, or this.
    """
    return _TEMPLATES.TemplateResponse(
        request,
        "problem.html",
        {"problem": str(error), "resolution": error.resolution},
        status_code=404,
    )


__all__ = ["COOKIE_NAME", "build_app", "new_token"]


def _lines(given: str) -> list[str]:
    """One identifier per line, blank lines ignored.

    A textarea rather than a single field because a batch is the
    ordinary case - a folder of papers arrives as a list - and because
    a space-separated field cannot hold a path with a space in it.
    """
    return [line.strip() for line in given.splitlines() if line.strip()]


def _add_options(context: Context, form: FormData) -> AddOptions:
    """The engine's options, from the form and the settings behind it.

    The settings supply what the form does not ask: a default group, a
    conversion batch size and the politeness delay are configuration
    rather than per-add decisions, and putting them on the page would
    invite changing them per add.
    """
    identifier = str(form.get("identifier") or "") or None
    return AddOptions(
        title=str(form.get("title") or "") or None,
        group=str(form.get("group") or "")
        or context.settings.corpus.default_group
        or None,
        keep_original=context.settings.corpus.keep_original,
        identifier=identifier,
        citekey=str(form.get("citekey") or "") or None,
        project=str(form.get("project") or "") or None,
        batch_size=context.settings.conversion.batch_size,
        request_delay_seconds=context.settings.literature.request_delay,
        extra_file_types=(),
    )


def _shown_result(job: Job) -> ShownJob:
    """One finished job as the shape a page lays out.

    The `match` is on the report's type rather than on `job.kind`,
    because the type is what decides which renderer is correct and a
    string that disagreed with it would be a wrong page rather than an
    error.
    """
    match job.result:
        case AddReport():
            return shown_add(job.result)
        case IndexBuild():
            return shown_index(job.result)
        case CorpusSync():
            return shown_corpus_sync(job.result)
        case BundleSync():
            return shown_bundle_sync(job.result)
        case PackInstall():
            return shown_install(job.result)
        case _:
            return ShownJob(headline=words.NOTHING_TO_SHOW, role="role-muted")


def _refused(
    request: Request, problem: str, *, resolution: str | None = None
) -> HTMLResponse:
    """A refusal inside the panel, not as a page.

    The form the person filled in is still on the page behind this, and
    replacing the page would lose what they typed. `CorpusBusy` is the
    case that makes it matter: something else is writing, nothing was
    changed, and the answer is to try again in a moment.
    """
    return _TEMPLATES.TemplateResponse(
        request,
        "outcome.html",
        {
            "outcome": ShownOutcome(
                message=problem, role="role-warning", resolution=resolution
            )
        },
    )


def _manage_context() -> dict[str, object]:
    """What the management page needs before anything has been asked."""
    context = existing_corpus()
    return {
        "collections": COLLECTION_NAMES,
        "add_preamble": words.ADD_PREAMBLE,
        "add_action": words.ADD_ACTION,
        "index_preamble": words.INDEX_PREAMBLE,
        "index_action": words.INDEX_ACTION,
        "sync_preamble": words.SYNC_PREAMBLE,
        "pack_preamble": words.PACK_PREAMBLE,
        "pack_action": words.PACK_ACTION,
        **_frame(context),
    }
