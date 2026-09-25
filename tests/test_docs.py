"""The documentation site, checked for the two ways it goes wrong quietly.

Both failures here are silent by nature, which is why they are tested rather
than noticed:

- a generated reference drifts from the code it was generated from, and
  reads as authoritative while being wrong;
- a page renders as literal text instead of markdown, which is valid HTML,
  so a `--strict` build says nothing about it. That happened to the home
  page's card grid and was caught by reading the output, not the build.

Concern #219.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _generator() -> ModuleType:
    """`scripts/` is not a package - the other scripts in it are shell and
    standalone - so the generator is loaded by path rather than imported."""
    path = ROOT / "scripts" / "generate_settings_table.py"
    spec = importlib.util.spec_from_file_location("generate_settings_table", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_settings_table_matches_the_model():
    """`uv run scripts/generate_settings_table.py` regenerates it."""
    generator = _generator()
    committed = (ROOT / generator.PARTIAL).read_text()

    assert committed == generator.render(), (
        "the settings reference has drifted from the model; regenerate it "
        "with `uv run scripts/generate_settings_table.py`"
    )


def test_every_nav_entry_exists():
    """A nav entry with no file is a warning `--strict` catches, but only
    when someone runs the build. This is cheap enough to run always."""
    config = (ROOT / "mkdocs.yml").read_text()
    navigation = config.split("nav:", 1)[1]
    referenced = [
        part.strip()
        for line in navigation.splitlines()
        if ": " in line and line.strip().endswith(".md")
        for part in [line.split(": ", 1)[1]]
    ]

    assert referenced, "no nav entries were parsed, so this test proves nothing"
    missing = [page for page in referenced if not (ROOT / "docs" / page).is_file()]

    assert not missing


@pytest.mark.slow
def test_the_site_builds_with_no_warnings():
    """`--strict` turns a broken internal link into a failure. Marked slow
    because it is a subprocess and a full render."""
    if shutil.which("uv") is None:  # pragma: no cover - environment specific
        pytest.skip("uv is not on PATH")
    result = subprocess.run(
        ["uv", "run", "--group", "docs", "mkdocs", "build", "--strict"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        stdin=subprocess.DEVNULL,
    )

    assert result.returncode == 0, result.stderr[-3000:]


@pytest.mark.slow
def test_the_home_page_grid_renders_as_markdown():
    """`md_in_html` is what makes the card grid's contents parse. Without it
    the markdown is passed through as text inside a valid div, and the build
    stays green while the page shows raw brackets."""
    built = ROOT / "site" / "index.html"
    if not built.is_file():  # pragma: no cover - depends on build order
        pytest.skip("the site has not been built")
    page = built.read_text()

    assert 'class="grid cards"' in page
    assert "](getting-started/install.md)" not in page, (
        "the card grid rendered as literal markdown; `md_in_html` is missing"
    )
