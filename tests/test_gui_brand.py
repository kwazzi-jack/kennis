"""The window's icon: the open book, on every page kennis draws.

Three pages have a `<head>`, and two of them cannot fetch anything: the
locked page is answered without the token that every static file needs,
and the stopped page is drawn as the server exits. So the icon is a
`data:` address carrying the packaged SVG, which each page holds whole,
and which the content policy's `img-src data:` already admits.
"""

from __future__ import annotations

import base64
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.gui.app import build_app

TOKEN = "a-test-token"
FAVICON = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "kennis"
    / "gui"
    / "static"
    / "brand"
    / "favicon.svg"
)
DATA_PREFIX = "data:image/svg+xml;base64,"


class IconLinks(HTMLParser):
    """Every `href` of a `<link>` whose `rel` names an icon."""

    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "link" and "icon" in (attributes.get("rel") or "").split():
            self.hrefs.append(attributes.get("href") or "")


def icon_links(page: str) -> list[str]:
    parser = IconLinks()
    parser.feed(page)
    return parser.hrefs


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    return tmp_path


@pytest.fixture
def client(corpus: Path) -> TestClient:
    return TestClient(build_app(TOKEN, on_quit=lambda: None), follow_redirects=False)


def admitted(client: TestClient) -> TestClient:
    assert client.get("/static/kennis.css", params={"token": TOKEN}).status_code == 200
    return client


def test_the_packaged_favicon_is_an_svg_with_a_title():
    root = ElementTree.fromstring(FAVICON.read_bytes())
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert root.get("viewBox")
    assert root.find("{http://www.w3.org/2000/svg}title") is not None
    # Outlines only: a `<text>` would be drawn in whatever font the
    # browser has, which is not the mark.
    assert list(root.iter("{http://www.w3.org/2000/svg}text")) == []


def page_of(client: TestClient, kind: str) -> str:
    if kind == "workbench":
        return admitted(client).get("/").text
    if kind == "locked":
        return client.get("/", headers={"accept": "text/html"}).text
    return admitted(client).post("/quit").text


@pytest.mark.parametrize("kind", ["workbench", "locked", "stopped"])
def test_every_page_carries_the_open_book_inline(client: TestClient, kind: str):
    (href,) = icon_links(page_of(client, kind))
    assert href.startswith(DATA_PREFIX), href[:40]
    assert base64.b64decode(href.removeprefix(DATA_PREFIX)) == FAVICON.read_bytes()
