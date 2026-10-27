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

The token is minted per launch. It is stored in one place only: the
window's record in the state directory, readable by this account alone,
so a second `kennis gui` can open this window or stop it
(`protocol/record.py`, #484). It arrives once as a
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
from fastapi.responses import (
    JSONResponse,
    PlainTextResponse,
)
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from kennis.engine.errors import (
    KennisError,
)
from kennis.gui import words
from kennis.gui.responses import TEMPLATES, from_htmx, refused
from kennis.gui.routes import (
    add,
    corpus,
    documents,
    jobs,
    remember,
    search,
    settings,
    shell,
    supply,
)
from kennis.gui.theme import stylesheet
from kennis.service.jobs import Jobs

_HERE: Final = Path(__file__).parent

# Sent with every answer: no page kennis serves tells another site where
# its reader came from (11e).
_REFERRER_POLICY: Final = "no-referrer"

# The name the cookie is held under, before its port. Prefixed because it
# is kennis's and a browser may be holding cookies for other things served
# from loopback on another port - a notebook, someone else's dev server -
# and an unprefixed `token` is exactly the collision that produces.
COOKIE_NAME: Final = "kennis_gui_token"

_UNAUTHORISED: Final = "this interface needs the token it was started with"

_CROSS_ORIGIN: Final = "this interface accepts changes only from its own pages"

# The methods that change nothing, and so need not come from kennis's own
# pages. Every write is a POST (11e).
_SAFE_METHODS: Final = frozenset({"GET", "HEAD", "OPTIONS"})


def content_policy(request: Request) -> str:
    """What a page of this window may load and run, as `Content-Security-Policy`.

    **A second wall behind the renderer.** A corpus holds converted web
    pages and papers, and `render/html.py` escapes their markup and blocks
    their images; this says the same to the browser, so a defect in either
    is not a script running with the reader's token or a pixel reporting
    to a remote host that the reader opened a document.

    - scripts only from here: every script is a file under `/static`;
    - styles from here and inline, because KaTeX draws with `style=`, the
      pane's sizes are a `style` on `<html>`, and the stopped page carries
      its stylesheet inline (the server is gone when it arrives);
    - images from here and `data:`, and from anywhere only on the page the
      reader asked to load them on (`images=on`, #420's "nothing fetched on
      the reader's behalf");
    - no frame may hold it, so another page on loopback cannot dress it up
      and have the reader click.
    """
    images = "'self' data:"
    if request.query_params.get("images") == "on":
        images += " http: https:"
    return "; ".join(
        (
            "default-src 'self'",
            "script-src 'self'",
            "style-src 'self' 'unsafe-inline'",
            f"img-src {images}",
            "font-src 'self' data:",
            "connect-src 'self'",
            "object-src 'none'",
            "base-uri 'none'",
            "form-action 'self'",
            "frame-ancestors 'none'",
        )
    )


def cookie_name(request: Request) -> str:
    """The token cookie's name for the address this request was sent to.

    **Per port, because a cookie is not.** A browser sends a cookie set by
    `127.0.0.1:A` to `127.0.0.1:B` as well, so a second `kennis gui` - one
    per project is the ordinary case (#407) - overwrote the first one's
    token, and every request from the first tab was refused. The port is
    the one the browser addressed, read from `Host`, which over `ssh -L` is
    the forwarded port rather than the server's own.
    """
    port = request.url.port
    return COOKIE_NAME if port is None else f"{COOKIE_NAME}_{port}"


def from_elsewhere(request: Request) -> bool:
    """Whether a request that writes was sent by a page kennis did not serve.

    **`samesite=strict` is not enough on loopback.** A site is a scheme and
    a host, with no port, so a page served from `127.0.0.1` on any other
    port - a notebook, another account's server on a shared machine - is the
    same site, and the browser sends the token cookie with its POSTs. The
    browser states where a request came from in `Origin`, which every
    current browser sends with a POST, and in `Sec-Fetch-Site`; either one
    naming somewhere other than this address refuses the write. A request
    carrying neither came from no browser, and a client outside a browser
    with the token is the person.
    """
    if request.method in _SAFE_METHODS:
        return False
    origin = request.headers.get("origin")
    if origin is not None and origin != "null":
        here = f"{request.url.scheme}://{request.headers.get('host', '')}"
        return origin != here
    # **`Origin: null` is what kennis's own plain forms send.** Every
    # answer carries `Referrer-Policy: no-referrer`, and under it a
    # browser withholds the origin of a form's POST as well as its
    # referrer - so the check refused every form posted without a script,
    # which a test in a real browser found and the suite could not.
    # `Sec-Fetch-Site` is not withheld, and says the same thing.
    fetched = request.headers.get("sec-fetch-site")
    if fetched is not None:
        return fetched not in {"same-origin", "none"}
    # A browser that hid where the request came from and said nothing else.
    return origin == "null"


def _locked(request: Request) -> Response:
    """The answer to a request without the token.

    A page for a browser, saying what to do, rather than a line of JSON:
    a reader who opened a bookmarked address after a restart met
    `{"detail": ...}` and nothing else. Its stylesheet is inline, because
    a request for the stylesheet is refused for the same reason. Anything
    that is not a page asked for by a browser keeps the short answer.
    """
    wants_page = "text/html" in request.headers.get("accept", "")
    if request.method != "GET" or from_htmx(request) or not wants_page:
        return JSONResponse({"detail": _UNAUTHORISED}, status_code=401)
    return TEMPLATES.TemplateResponse(
        request,
        "locked.html",
        {
            "heading": words.LOCKED_HEADING,
            "locked": words.LOCKED,
            "stylesheet": stylesheet(),
        },
        status_code=401,
    )


def bearer_token(request: Request) -> str | None:
    """The token a client of the service sends, as `Authorization: Bearer`.

    A header rather than the query or a cookie: the command line and the
    MCP server are not browsers, and a token in a query string is a token
    in any log that records the address (14b).
    """
    scheme, _, credential = request.headers.get("authorization", "").partition(" ")
    return credential if scheme.lower() == "bearer" and credential else None


def new_token() -> str:
    """A token for one launch.

    `secrets` rather than `random`: this is what stands between a
    personal corpus and every other account on a shared machine.
    """
    return secrets.token_urlsafe(32)


def _keep_running() -> None:
    """The default `on_quit`, for an application nobody launched."""


def build_app(token: str, on_quit: Callable[[], None] = _keep_running) -> FastAPI:
    """The application, guarded by `token`.

    Taken as an argument rather than read from a global, for the reason
    concern #87 gives about the engine: a value two callers can set
    differently in one process is a value a test can set at all.

    `on_quit` is how a POST to `/quit` reaches whoever is running the
    server. The application cannot stop the server itself - uvicorn owns
    it - so it says it has been asked to and the launcher does the rest.
    """
    app = FastAPI(title="kennis", docs_url=None, redoc_url=None)
    # On the application rather than in a module-level variable, so a
    # test builds its own and two applications in one process do not
    # share a job list.
    app.state.jobs = Jobs()
    # Read by `/quit`, which answers and then asks whoever runs the server
    # to stop: uvicorn owns the server, so the application cannot.
    app.state.on_quit = on_quit

    @app.middleware("http")
    async def require_token(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        cookie = cookie_name(request)
        supplied = (
            request.query_params.get("token")
            or request.cookies.get(cookie)
            or bearer_token(request)
        )
        if not secrets.compare_digest(supplied or "", token):
            # 401 and not a redirect. A refusal that redirects is a
            # refusal a client follows, and then the test that proves
            # the guard works reports 200 for a request that was
            # turned away.
            refusal = _locked(request)
            refusal.headers["Referrer-Policy"] = _REFERRER_POLICY
            return refusal
        if from_elsewhere(request):
            refusal = JSONResponse({"detail": _CROSS_ORIGIN}, status_code=403)
            refusal.headers["Referrer-Policy"] = _REFERRER_POLICY
            return refusal
        answer = await call_next(request)
        # On every answer, so a link followed out of kennis - a candidate's
        # registry page, a citation in a converted paper - does not tell
        # the remote site where the reader was. The browser's default
        # already withholds the path across sites; this states the rule
        # rather than relying on the default (11e).
        answer.headers["Referrer-Policy"] = _REFERRER_POLICY
        answer.headers["Content-Security-Policy"] = content_policy(request)
        if request.query_params.get("token"):
            answer.set_cookie(
                cookie,
                token,
                httponly=True,
                samesite="strict",
                # No `secure`: the interface is served over plain HTTP
                # on loopback, and a secure cookie would never be sent
                # back, so the guard would refuse every request after
                # the first.
            )
        return answer

    @app.exception_handler(KennisError)
    def drawn_as_a_problem(request: Request, error: Exception) -> Response:
        """A domain failure no route turned into something of its own.

        Design section 20: the engine raises, and each front end turns it
        into what that front end has. A route that reads the settings is
        nearly every route, so a `config.toml` holding one value out of range
        answered every page with a bare "Internal Server Error" - the
        sentence saying which value, and the command that shows it, were
        both in the error and neither reached the reader.
        """
        if not isinstance(error, KennisError):
            raise error
        # A route that starts a task answers into the bar, where a bare
        # sentence was drawn beside the job: the error is that task (#475).
        kind = jobs.JOB_ROUTES.get(request.url.path)
        if kind is not None and request.method == "POST":
            return jobs.refused_task(request, kind, error)
        if from_htmx(request):
            return refused(request, str(error), resolution=error.resolution)
        return TEMPLATES.TemplateResponse(
            request,
            "problem.html",
            {"problem": str(error), "resolution": error.resolution},
            status_code=500,
        )

    @app.exception_handler(StarletteHTTPException)
    def drawn_as_not_found(request: Request, error: Exception) -> Response:
        """An address with no page, as a page in the window.

        It was FastAPI's own `{"detail": "Not Found"}`, raw JSON in a tab
        with no way back. Only for a page a browser asked for: a fragment
        htmx asked for, or any other failure, keeps the plain answer.
        """
        if not isinstance(error, StarletteHTTPException):
            raise error
        if error.status_code != 404 or from_htmx(request) or request.method != "GET":
            return JSONResponse({"detail": error.detail}, status_code=error.status_code)
        return TEMPLATES.TemplateResponse(
            request,
            "problem.html",
            {
                "heading": words.NOT_FOUND_HEADING,
                "problem": words.no_page_at(request.url.path),
                "resolution": None,
            },
            status_code=404,
        )

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
    def serve_stylesheet() -> PlainTextResponse:
        return PlainTextResponse(stylesheet(), media_type="text/css")

    @app.get("/static/{name}.js")
    def serve_script(name: str) -> PlainTextResponse:
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

    for routes in (
        shell,
        search,
        corpus,
        documents,
        remember,
        add,
        jobs,
        settings,
        supply,
    ):
        app.include_router(routes.router)

    return app


__all__ = [
    "COOKIE_NAME",
    "bearer_token",
    "build_app",
    "content_policy",
    "cookie_name",
    "from_elsewhere",
    "new_token",
]
