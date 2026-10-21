"""The service's application: the window's pages and the clients' API (14b).

**One application, one guard.** The window's routes are built by
`gui.app.build_app`, whose middleware checks the token on every request;
the API under `/api/1/` is added to the same application, so it passes the
same check - a client sends the token as `Authorization: Bearer`. Section
20's "no front end is privileged" holds because a page and a client reach
the same jobs in the same lanes.

**Every request is counted while it is open**, by plain ASGI middleware
rather than Starlette's, because Starlette's returns as soon as a streamed
answer has started and an event stream is exactly the request that must
keep the service alive.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI
from starlette.types import ASGIApp, Receive, Scope, Send

from kennis.gui.app import build_app
from kennis.service import api
from kennis.service.idle import IdleTimer
from kennis.service.jobs import Jobs


class CountingRequests:
    """Tells the idle timer when each request begins and ends."""

    def __init__(self, app: ASGIApp, idle: IdleTimer) -> None:
        self._app = app
        self._idle = idle

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        self._idle.request_began()
        try:
            await self._app(scope, receive, send)
        finally:
            self._idle.request_ended()


def _keep_running() -> None:
    """The default `on_stop`, for an application nobody launched."""


class Recovered:
    """The operation the service put back at its start (`staging.recover`),
    told to the first client that asks and to no other (#507)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._operation: str | None = None

    def put(self, operation: str | None) -> None:
        with self._lock:
            self._operation = operation

    def take(self) -> str | None:
        with self._lock:
            operation, self._operation = self._operation, None
            return operation


def build_service_app(
    token: str,
    corpus_root: Path,
    *,
    on_stop: Callable[[], None] = _keep_running,
    idle: IdleTimer | None = None,
) -> FastAPI:
    """The service for the corpus at `corpus_root`, guarded by `token`.

    `on_stop` is how a stop request, the window's Quit and the idle timer
    reach whoever runs the server: uvicorn owns it, so the application can
    only say it has been asked.
    """
    app = build_app(token, on_quit=on_stop)
    app.state.corpus_root = corpus_root
    app.state.recovered = Recovered()
    app.state.on_stop = on_stop
    app.state.jobs = Jobs(on_change=idle.touch if idle is not None else None)
    app.include_router(api.router)
    if idle is not None:
        app.add_middleware(CountingRequests, idle=idle)
    return app


__all__ = [
    "CountingRequests",
    "Recovered",
    "build_service_app",
]
