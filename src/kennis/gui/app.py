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
from typing import Final

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from kennis.gui.theme import stylesheet

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

    @app.get("/static/kennis.css")
    async def serve_stylesheet() -> PlainTextResponse:
        return PlainTextResponse(stylesheet(), media_type="text/css")

    @app.get("/")
    async def serve_page() -> HTMLResponse:
        return HTMLResponse(_PAGE)

    return app


# The shell of a page. Unit 9a serves one static document on purpose:
# what it exists to prove is the process shape, the guard and the
# theme, and a page with features in it would make a failure ambiguous.
_PAGE: Final = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>kennis</title>
<link rel="stylesheet" href="/static/kennis.css">
</head>
<body>
<main>
<h1>kennis</h1>
<p class="role-muted">The interface is running. Nothing is wired to it yet.</p>
</main>
</body>
</html>
"""


__all__ = ["COOKIE_NAME", "build_app", "new_token"]
