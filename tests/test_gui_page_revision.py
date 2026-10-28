"""Every page the window draws knows which commit it was drawn at.

Brian, 2026-10-27: "The kennis gui keeps showing the ... reload popup ... at
random moments, e.g. clicking a hyperlink on the markdown to open a new tab
works, but shows the reload popup." `revision.js` compares the corpus's
commit on focus with the page's `data-revision`; a page drawn with none
reads as changed on its first focus, every time.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from click.testing import CliRunner
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.context import existing_corpus
from kennis.gui.app import build_app
from kennis.writing import write_note

TOKEN = "a-test-token"


@pytest.fixture
def window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    client = TestClient(build_app(TOKEN), follow_redirects=False)
    assert client.get("/", params={"token": TOKEN}).status_code == 200
    return client


def drawn_revision(page: str) -> str | None:
    """The notice's revision, or None for a page without the notice; a
    notice missing any of its words is reported as such."""
    dialog = BeautifulSoup(page, "html.parser").find(id="corpus-changed")
    if dialog is None:
        return None
    parts = [dialog.find("h2"), dialog.find("p"), *dialog.find_all("button")]
    if len(parts) != 4 or any(
        part is None or not part.get_text(strip=True) for part in parts
    ):
        return "drawn without its words"
    value = dialog.get("data-revision")
    return value if isinstance(value, str) else ""


def test_every_page_with_the_notice_was_drawn_at_the_corpus_s_commit(
    window: TestClient,
):
    written = write_note(existing_corpus(), "A note to open.", title="Opened")
    head = drawn_revision(window.get("/").text)
    assert head

    unanchored: list[str] = []
    for address in (
        "/",
        "/?q=note",
        "/remember",
        "/sync",
        "/index",
        "/pack",
        "/corpus",
        "/activity",
        "/settings",
        "/palette",
        "/add",
        f"/document/notes/{written.document_id}",
    ):
        answer = window.get(address)
        assert answer.status_code == 200, address
        found = drawn_revision(answer.text)
        if found is not None and found != head:
            unanchored.append(f"{address}: {found!r}")

    assert unanchored == []
