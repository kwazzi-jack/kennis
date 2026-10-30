"""An open window keeps the service, and says when it has gone.

Each window holds one stream, `GET /presence`, that sends nothing until the
service stops. The idle timer counts an open request as work, so the service
stays while a window is open; when it stops, the stream ends,
the page asks once more, is told no, and opens a dialog drawn with every
word. The real process is tested in
`test_service_process.py` and the page in `test_gui_browser.py`.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from click.testing import CliRunner
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.gui import words
from kennis.gui.app import build_app
from kennis.gui.presence import OPENED, Presence

TOKEN = "a-test-token"
STATIC = Path(__file__).resolve().parent.parent / "src" / "kennis" / "gui" / "static"


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    return tmp_path


def code_of(name: str) -> str:
    """A script with its comment lines removed, so prose cannot satisfy a
    test about code (#373)."""
    script = (STATIC / name).read_text(encoding="utf-8")
    return "\n".join(
        line for line in script.splitlines() if not line.strip().startswith("//")
    )


def test_a_held_stream_opens_and_ends_only_when_ended():
    """Ended from another thread, as the service's stop is."""
    presence = Presence()

    async def hold() -> list[str]:
        said: list[str] = []
        stream = presence.held()
        said.append(await anext(stream))
        assert presence.open_windows() == 1
        threading.Timer(0.05, presence.end).start()
        said.extend([chunk async for chunk in stream])
        return said

    # Bounded, so a stream the end never reaches fails rather than hangs.
    said = asyncio.run(asyncio.wait_for(hold(), timeout=2))

    assert said == [OPENED]
    assert presence.open_windows() == 0


def test_a_stream_begun_after_the_end_ends_at_once():
    presence = Presence()
    presence.end()

    async def hold() -> list[str]:
        return [chunk async for chunk in presence.held()]

    assert asyncio.run(asyncio.wait_for(hold(), timeout=2)) == [OPENED]


def test_a_stream_that_is_given_up_is_no_longer_counted():
    """A window closing ends its stream from the reader's side."""
    presence = Presence()

    async def hold() -> None:
        stream = presence.held()
        await anext(stream)
        await stream.aclose()

    asyncio.run(hold())

    assert presence.open_windows() == 0


def test_once_ended_the_route_answers_no_content(corpus: Path):
    """EventSource takes a 204 as final: a page asking after the stop is
    told nothing more rather than held while the server shuts down."""
    app = build_app(TOKEN)
    client = TestClient(app)
    app.state.presence.end()

    answer = client.get("/presence", params={"token": TOKEN})

    assert answer.status_code == 204


def test_every_page_carries_the_dialog_with_its_words(corpus: Path):
    client = TestClient(build_app(TOKEN))

    page = BeautifulSoup(client.get("/", params={"token": TOKEN}).text, "html.parser")

    dialog = page.find("dialog", id="service-gone")
    assert dialog is not None
    text = dialog.get_text(" ", strip=True)
    assert words.SERVICE_GONE_HEADING in text
    assert words.SERVICE_GONE in text
    assert words.SERVICE_GONE_COMMAND in text
    assert page.find("script", src="/static/presence.js") is not None


def test_the_stopped_page_watches_nothing(corpus: Path):
    """What Quit answers: nothing is left to watch, and its own stylesheet
    is inline because the server will not answer for one."""
    stopped = BeautifulSoup(
        TestClient(build_app(TOKEN)).post("/quit", params={"token": TOKEN}).text,
        "html.parser",
    )

    assert stopped.find("script", src="/static/presence.js") is None


def test_the_script_composes_no_words_and_shares_one_connection():
    code = code_of("presence.js")

    assert "SharedWorker" in code
    assert 'ADDRESS = "/presence"' in code
    assert "new EventSource(ADDRESS)" in code
    assert "if (opened) { connect(); } else { report(); }" in code
    assert "setTimeout" not in code and "setInterval" not in code
    for sentence in (words.SERVICE_GONE_HEADING, words.SERVICE_GONE):
        assert sentence not in code
