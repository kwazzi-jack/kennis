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

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from kennis.context import Context, existing_corpus
from kennis.engine.context.index import CONTEXT_COLLECTION
from kennis.engine.corpus.layout import relative_to_corpus
from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.errors import CorpusBusy, KennisError, UnknownCollection
from kennis.gui import words
from kennis.gui.pages import (
    ShownOutcome,
    shown_document,
    shown_groups,
    shown_hits,
    shown_rows,
)
from kennis.gui.theme import stylesheet
from kennis.holdings import holdings, installed_packs, revision
from kennis.render.packs import describe_holdings
from kennis.retrieval import search_scope
from kennis.writing import write_context_note, write_note

_HERE: Final = Path(__file__).parent
_TEMPLATES: Final = Jinja2Templates(directory=str(_HERE / "templates"))

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
        request: Request, q: str = "", scope: str = "notes"
    ) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(
            request, "search.html", _hits_context(q, scope)
        )

    @app.get("/hits")
    async def serve_hits(
        request: Request, q: str = "", scope: str = "notes"
    ) -> HTMLResponse:
        # The partial htmx swaps in. The same context as the page, so
        # a first load and a keystroke cannot disagree about what a
        # result looks like.
        return _TEMPLATES.TemplateResponse(
            request, "hits.html", _hits_context(q, scope)
        )

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
        request: Request, collection: str, document_id: str, images: str = ""
    ) -> HTMLResponse:
        load_remote = images == "on"
        try:
            document = shown_document(
                existing_corpus().corpus_root,
                collection,
                document_id,
                load_remote_images=load_remote,
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
            },
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
    """
    context: dict[str, object] = {
        **_frame(existing_corpus()),
        "question": question,
        "scope": scope,
        "scopes": SCOPES,
        "hits": [],
        "nothing": words.NOTHING_FOUND,
        "problem": None,
        "resolution": None,
    }
    if not question:
        return context
    if scope not in SCOPES:
        context["problem"] = words.unknown_scope(scope, SCOPES)
        return context
    try:
        context["hits"] = shown_hits(search_scope(scope, question))
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
