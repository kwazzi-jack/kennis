"""The service every command reaches, built in the test's own process (14c).

`kennis.client.connection.connect` is replaced, for every test, by
`InProcessServices.connect`: a `TestClient` over `build_service_app` for
the corpus asked for, built once per corpus root per test, because a test
can initialise a corpus and then use it. In this process, so every
monkeypatch, the network guard and the offline embedding still apply to
the work - a started service would have none of them (#503).
"""

from __future__ import annotations

from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kennis.protocol.wire import API_VERSION
from kennis.service.app import build_service_app

TOKEN = "the-in-process-token"


class InProcessServices:
    """One application per corpus root, for one test."""

    def __init__(self) -> None:
        self._apps: dict[Path, FastAPI] = {}

    def app(self, corpus_root: Path) -> FastAPI:
        root = Path(corpus_root).expanduser().resolve()
        if root not in self._apps:
            self._apps[root] = build_service_app(TOKEN, root)
        return self._apps[root]

    def connect(self, corpus_root: Path) -> httpx.Client:
        return TestClient(
            self.app(corpus_root),
            base_url=f"http://testserver/api/{API_VERSION}/",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )


__all__ = ["InProcessServices"]
