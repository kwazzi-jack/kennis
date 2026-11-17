"""The setup wizard in a browser (#682, unit 2): four steps walked by
pressing only each step's main button, the page's own scripts raising
nothing, and the last step sending the browser to the window.
"""

from __future__ import annotations

import os
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn

from kennis import setting_up
from kennis.gui import words
from kennis.gui.setup_app import build_setup_app
from kennis.service.serve import ANY_PORT, HOST, port_of
from test_gui_browser import _benign

playwright = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser

_WAIT_MS = 10_000
# Where the last step sends the browser: this server's own page for the
# done step, standing in for the corpus service.
_WINDOW = "/?step=done&arrived=yes"


@pytest.fixture
def started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[str, list[Path]]]:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.delenv("KENNIS_EMBEDDING_BACKEND", raising=False)
    monkeypatch.setattr(setting_up, "mcp_installed", lambda: True)
    monkeypatch.setattr(setting_up, "claude_on_path", lambda: False)

    def no_claude(arguments: list[str]) -> subprocess.CompletedProcess[str]:
        raise AssertionError("claude was run")

    monkeypatch.setattr(setting_up, "claude_code", no_claude)
    services: list[Path] = []

    def start(root: Path) -> str:
        services.append(root)
        return _WINDOW

    token = "setup-browser-token"
    server = uvicorn.Server(
        uvicorn.Config(
            build_setup_app(token, start_service=start),
            host=HOST,
            port=ANY_PORT,
            log_level="warning",
        )
    )
    runner = threading.Thread(target=server.run, daemon=True)
    runner.start()
    port = port_of(server)
    yield f"http://{HOST}:{port}/?token={token}", services
    server.should_exit = True
    runner.join(timeout=10)


def test_the_four_steps_are_walked_with_their_main_buttons_alone(
    started: tuple[str, list[Path]], tmp_path: Path
) -> None:
    address, services = started
    problems: list[str] = []
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(
            executable_path=os.environ.get("KENNIS_TEST_CHROMIUM") or None
        )
        page = browser.new_page()
        page.on(
            "pageerror",
            lambda error: None if _benign(str(error)) else problems.append(str(error)),
        )
        page.goto(address)

        labels = dict(words.SETUP_STEPS)
        for step in labels:
            current = page.locator(".setup-steps [aria-current='step']")
            assert current.inner_text() == labels[step]
            page.click("main button.primary")
            page.wait_for_load_state()

        page.wait_for_url(f"**{_WINDOW}", timeout=_WAIT_MS)
        browser.close()

    assert problems == []
    assert (tmp_path / "config" / "config.toml").is_file()
    assert (tmp_path / "corpus" / ".git").is_dir()
    assert services == [tmp_path / "corpus"]
