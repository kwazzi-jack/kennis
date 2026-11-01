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


# --- showing a passage in a window already open ---------------------------
#
# `kennis open` asks the service to show a passage in a window already open
# (Brian, 2026-11-01). The service sends a `show` event down the most
# recently opened stream and waits for the page to acknowledge it; a window
# that does not answer in time is left alone, and a new tab is opened.


def shown_event(chunk: str) -> dict[str, str]:
    import json

    lines = dict(line.split(": ", 1) for line in chunk.strip().splitlines())
    assert lines["event"] == "show", chunk
    found: dict[str, str] = json.loads(lines["data"])
    return found


def test_with_no_window_nothing_is_shown_and_nothing_waits():
    import time

    presence = Presence()
    began = time.monotonic()

    assert presence.show("/document/notes/abc", wait=5) is False
    assert time.monotonic() - began < 1


def held_in_a_thread(
    presence: Presence, count: int = 1
) -> tuple[list[str], threading.Thread]:
    """`count` streams held on a loop of their own, as uvicorn holds them,
    each one's chunks after OPENED collected in order of arrival."""
    said: list[str] = []
    opened = threading.Event()

    async def hold_all() -> None:
        async def hold(position: int) -> None:
            stream = presence.held()
            await anext(stream)
            if presence.open_windows() == count:
                opened.set()
            async for chunk in stream:
                said.append(f"{position}:{chunk}")

        await asyncio.gather(*(hold(position) for position in range(count)))

    runner = threading.Thread(
        target=lambda: asyncio.run(asyncio.wait_for(hold_all(), timeout=10)),
        daemon=True,
    )
    runner.start()
    assert opened.wait(5)
    return said, runner


def test_a_window_that_acknowledges_is_shown_the_path():
    presence = Presence()
    said, runner = held_in_a_thread(presence)

    def acknowledge_when_told() -> None:
        while not said:
            threading.Event().wait(0.01)
        nonce = shown_event(said[0].split(":", 1)[1])["nonce"]
        assert presence.acknowledge(nonce)

    threading.Thread(target=acknowledge_when_told, daemon=True).start()

    assert presence.show("/document/notes/abc?chunk=2#chunk-2", wait=5) is True
    assert shown_event(said[0].split(":", 1)[1])["path"] == (
        "/document/notes/abc?chunk=2#chunk-2"
    )
    presence.end()
    runner.join(5)


def test_a_window_that_does_not_answer_in_time_is_not_counted_as_shown():
    presence = Presence()
    said, runner = held_in_a_thread(presence)

    assert presence.show("/document/notes/abc", wait=0.2) is False

    # Told too late: the page must not move, since a new tab was opened.
    nonce = shown_event(said[0].split(":", 1)[1])["nonce"]
    assert presence.acknowledge(nonce) is False
    presence.end()
    runner.join(5)


def test_an_acknowledgement_nobody_asked_for_is_refused():
    assert Presence().acknowledge("0123456789abcdef") is False


def test_only_the_most_recently_opened_window_is_asked():
    presence = Presence()
    said, runner = held_in_a_thread(presence, count=2)

    presence.show("/document/notes/abc", wait=0.1)

    # gather starts stream 0 first, so stream 1 is the newer.
    assert [chunk.split(":", 1)[0] for chunk in said] == ["1"]
    presence.end()
    runner.join(5)


def test_the_acknowledgement_route_says_whether_it_was_still_wanted(corpus: Path):
    app = build_app(TOKEN)
    with TestClient(app) as client:
        answer = client.post(
            "/shown/0123456789abcdef", headers={"Authorization": f"Bearer {TOKEN}"}
        )

    assert answer.status_code == 410


def test_the_script_navigates_only_once_the_service_still_wants_it():
    code = code_of("presence.js")

    assert 'addEventListener("show"' in code
    assert '"/shown/" + ' in code
    assert "location.assign(" in code
    # The page moves only on the service's yes, never on the event alone.
    assert code.index('"/shown/" + ') < code.index("location.assign(")
