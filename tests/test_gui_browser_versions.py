"""Choosing docs versions in a real browser (#489, unit V3).

The choice is checkboxes inside the search form, and htmx runs the search
again when one changes - a trigger only a browser can show is wired.
Deselected by default with the `browser` marker, as `test_gui_browser.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from test_gui_browser import _WAIT_MS, address, page

playwright = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser

__all__ = ["address", "page"]


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    run = CliRunner()
    assert run.invoke(main, ["corpus", "init"]).exit_code == 0
    for version in ("2.12", "2.14"):
        source = tmp_path / version / "models.md"
        source.parent.mkdir()
        source.write_text(
            f"# Models\n\nValidators changed in release {version}.\n",
            encoding="utf-8",
        )
        adding = ["corpus", "add", "-d", "--project", "pydantic", "--version"]
        assert run.invoke(main, [*adding, version, str(source)]).exit_code == 0
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0
    return tmp_path


def test_ticking_a_version_searches_it_again(page: playwright.Page) -> None:
    page.fill("input[name=q]", "validators")
    page.wait_for_selector("#hits .hit-version", timeout=_WAIT_MS)
    assert "2.12" not in page.inner_text("#hits")

    page.click(".searchbox .versions > summary")
    page.check('.versions input[value="pydantic=2.12"]')

    # A locator rather than `wait_for_function`: the page's policy
    # refuses a script evaluated from a string.
    page.locator("#hits .hit-version", has_text="pydantic 2.12").wait_for(
        timeout=_WAIT_MS
    )
    assert "version=pydantic%3D2.12" in page.url
