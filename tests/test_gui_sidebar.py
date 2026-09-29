"""The frame around the reading column: the sidebar, and two faces.

**One variable was doing two jobs.** `--gutter` was the face of the
margin - provenance, counts, labels, buttons - and also what
`code, pre` was set in. Making the margin a system sans, which is
what Brian asked for, would have put every code block in a
proportional face and quietly undone v0.6g's syntax highlighting.
So the split is the work, and the division is the one the interface
already makes: what kennis composed wears `--gutter`, what must be
read or typed verbatim wears `--mono`.

**`.role-command` had no face at all.** It is a generated colour
role, so a printed command inherited its surroundings - monospace
inside `.skipped`, the serif body face in `problem.html` and
`outcome.html`. The same command read two ways depending on which
page refused it.

**The sidebar's state is a cookie, not browser storage**, so the
server renders it and nothing flashes open before collapsing.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.gui import words
from kennis.gui.app import build_app
from kennis.gui.theme import stylesheet

TOKEN = "a-test-token"
TEMPLATES = Path(__file__).resolve().parents[1] / "src/kennis/gui/templates"
STATIC = Path(__file__).resolve().parents[1] / "src/kennis/gui/static"


@pytest.fixture
def client() -> TestClient:
    return TestClient(build_app(TOKEN), follow_redirects=False)


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    run = CliRunner()
    assert run.invoke(main, ["corpus", "init"]).exit_code == 0
    return tmp_path


def admitted(app_client: TestClient) -> TestClient:
    assert app_client.get("/", params={"token": TOKEN}).status_code == 200
    return app_client


def code_of(name: str) -> str:
    """A script with its comment lines removed.

    Every assertion about a script in this module goes through this.
    The cookie test did not, and passed against a version that had
    dropped `path=/` from the code - because the sentence explaining
    why it is there was still in the comment above. That is concern
    #337 exactly: a substring of the prose standing in for the thing
    the prose is about. Found by injection, not by review."""
    script = (STATIC / name).read_text(encoding="utf-8")
    return "\n".join(
        line for line in script.splitlines() if not line.strip().startswith("//")
    )


def rules_for(selector: str) -> str:
    """Every rule whose selector list is exactly this, joined.

    All of them, not the first: CSS cascades, and a property set for
    a selector may be set in a later rule. `.role-command` is
    generated with its colour and weight and given its face in the
    layout block, so asking only the first rule reports the absence
    of something that is present on the page. That was this helper's
    first version and it failed against working CSS."""
    found = re.findall(
        rf"(?:^|\}}|\*/)\s*{re.escape(selector)}\s*\{{([^}}]*)\}}",
        stylesheet(),
        re.MULTILINE,
    )
    assert found, f"no rule for {selector!r}"
    return "\n".join(found)


# ---------------------------------------------------------------------------
# Two faces
# ---------------------------------------------------------------------------


def test_the_two_faces_are_declared_and_are_different():
    css = stylesheet()

    assert "--gutter:" in css
    assert "--mono:" in css
    gutter = re.search(r"--gutter:([^;]*);", css)
    mono = re.search(r"--mono:([^;]*);", css)
    assert gutter is not None and mono is not None
    assert gutter.group(1).strip() != mono.group(1).strip()


def test_the_margin_is_not_monospace_and_code_is():
    """Brian asked for the small face to stop being monospace. The
    thing that makes that safe is that code no longer shares it."""
    gutter = re.search(r"--gutter:([^;]*);", stylesheet())
    mono = re.search(r"--mono:([^;]*);", stylesheet())
    assert gutter is not None and mono is not None

    assert "monospace" not in gutter.group(1)
    assert "monospace" in mono.group(1)


def test_code_wears_the_monospace_face():
    """Not `--gutter`, which is the whole hazard: one edit to that
    variable would set every code block in a proportional face, and
    the syntax highlighting of v0.6g with it. Nothing would fail."""
    assert "var(--mono)" in rules_for("code, pre")
    assert "var(--gutter)" not in rules_for("code, pre")


def test_a_printed_command_wears_the_monospace_face():
    """It had no face of its own, so it inherited: monospace inside
    `.skipped`, the serif body face in `problem.html` and
    `outcome.html`. rules.md 4.4 says a printed command must run as
    printed, and it should read as one wherever it appears."""
    assert "var(--mono)" in rules_for(".role-command")


def test_the_chrome_wears_the_gutter_face():
    """A sample of what kennis composed rather than quotes. If these
    moved to `--mono` the split would have gone the wrong way."""
    for selector in (".hits .detail", ".count", ".searching", "button"):
        assert "var(--gutter)" in rules_for(selector), selector


# ---------------------------------------------------------------------------
# The sidebar
# ---------------------------------------------------------------------------


def test_the_wordmark_keeps_its_ink_inside_the_sidebar():
    """`.sidebar a` is one class plus an element and `.wordmark` is
    one class, so the more specific rule wins and the name of the
    interface rendered in the grey meant for navigation. Measured in
    the browser: rgb(106, 112, 120) against a body of rgb(26, 28,
    31).

    A stylesheet test can only check that the rule which restores it
    is there. What found it was opening the page, which is the
    second time for this class of defect - concern #351 was the
    first, and neither was visible in the source."""
    css = stylesheet()
    restored = re.search(r"\.sidebar \.wordmark[^{]*\{([^}]*)\}", css, re.MULTILINE)

    assert restored is not None, "nothing restores the wordmark's colour"
    assert "var(--ink)" in restored.group(1)


def test_the_sidebar_lists_every_destination_in_order(corpus: Path, client: TestClient):
    admitted(client)

    page = client.get("/").text
    links = re.findall(
        r'<a\b[^>]*class="[^"]*sidebar-link[^"]*"[^>]*>([^<]*)</a>', page
    )

    assert links == [label for _, label in words.SIDEBAR_LINKS]


def test_every_sidebar_link_points_where_it_says(corpus: Path, client: TestClient):
    admitted(client)

    page = client.get("/").text

    for href, label in words.SIDEBAR_LINKS:
        assert f'href="{href}"' in page, (href, label)


def test_a_shortcut_reaches_a_section_that_exists(corpus: Path, client: TestClient):
    """`/manage#add` is only a shortcut if the page has an `add`. A
    fragment naming nothing lands the reader at the top with no sign
    anything was meant to happen."""
    admitted(client)

    manage = client.get("/manage").text

    for href, _ in words.SIDEBAR_LINKS:
        path, _, fragment = href.partition("#")
        if not fragment:
            continue
        assert path == "/manage", href
        assert f'id="{fragment}"' in manage, href


def test_a_shortcut_is_called_what_its_section_is_called():
    """The same discipline as the navigation labels one level down:
    a link saying "Add documents" that lands on a heading saying
    "Add" is the page having two names for one thing."""
    manage = (TEMPLATES / "manage.html").read_text(encoding="utf-8")

    for href, label in words.SIDEBAR_LINKS:
        _, _, fragment = href.partition("#")
        if not fragment:
            continue
        section = re.search(rf'id="{fragment}"[^>]*>\s*<h2>([^<]+)</h2>', manage)
        assert section is not None, fragment
        assert section.group(1) == label, fragment


def test_the_sidebar_reaches_everything_it_was_asked_to():
    """The tests above compare the page against `SIDEBAR_LINKS`, so
    they agree with each other however that list changes - dropping
    an entry drops it from both and nothing fails. Found by
    injection.

    This one names the destinations instead. Four of them are what
    Brian asked to have one click away, and two of those are
    sections of Manage rather than pages of their own."""
    reached = {href for href, _ in words.SIDEBAR_LINKS}

    assert {
        "/",
        "/held",
        "/remember",
        "/manage",
        "/manage#add",
        "/manage#index",
    } <= reached, sorted(reached)


def test_the_page_labels_come_from_the_navigation_and_are_not_repeated():
    """`NAV_LABELS` is what the existing test ties to each page's
    `<h1>`. A sidebar that spelled the same labels again would drift
    from the headings while that test kept passing."""
    labels = {label for _, label in words.SIDEBAR_LINKS}

    assert set(words.NAV_LABELS.values()) <= labels


# ---------------------------------------------------------------------------
# Collapsing, and where the state lives
# ---------------------------------------------------------------------------


def test_the_state_is_rendered_by_the_server_from_the_cookie(
    corpus: Path, client: TestClient
):
    """Read after paint from `localStorage`, the sidebar would show
    open and then collapse on every page load. A cookie is on the
    request, so the first byte is already right."""
    admitted(client)

    opened = client.get("/").text
    client.cookies.set("sidebar", "closed")
    closed = client.get("/").text

    assert 'data-sidebar="open"' in opened
    assert 'data-sidebar="closed"' in closed


def test_an_unknown_cookie_value_is_open(corpus: Path, client: TestClient):
    """Anything can be in a cookie. The default is the state that
    shows the reader what is there."""
    admitted(client)
    client.cookies.set("sidebar", "sideways")

    assert 'data-sidebar="open"' in client.get("/").text


def test_every_page_carries_the_sidebar(corpus: Path, client: TestClient):
    """It is rendered from `request`, which Starlette puts in the
    context of a `TemplateResponse` - so a route that builds its
    response another way would raise at template time rather than
    fail a test. Every page is loaded here, not one."""
    admitted(client)

    for path in ("/", "/held", "/remember", "/manage"):
        page = client.get(path)
        assert page.status_code == 200, path
        assert 'data-sidebar="' in page.text, path
        assert 'class="sidebar"' in page.text, path


def test_the_toggle_is_reachable_when_the_sidebar_is_closed():
    """ "Always present for the user to open" is the requirement. A
    collapsed sidebar that hides its own toggle cannot be reopened."""
    css = stylesheet()
    closed = re.findall(r'(\[data-sidebar="closed"\][^{]*)\{([^}]*)\}', css)

    assert closed, "nothing is styled differently when it is closed"

    # The rail keeps a width, or there is nothing left to click.
    widths = [
        re.search(r"--sidebar:\s*([^;]+);", body)
        for selector, body in closed
        if "--sidebar" in body
    ]
    assert widths and widths[0] is not None, "the closed state sets no width"
    assert not widths[0].group(1).strip().startswith("0"), widths[0].group(1)

    # And nothing in the closed state hides the toggle.
    for selector, body in closed:
        if "display: none" in body:
            assert "sidebar-toggle" not in selector, selector
            assert ".bars" not in selector, selector


def test_the_toggle_carries_both_its_names_from_python(
    corpus: Path, client: TestClient
):
    """Its label changes with the state, and the script must not be
    where either sentence lives."""
    admitted(client)

    page = client.get("/").text

    assert f'data-show="{words.SIDEBAR_SHOW}"' in page
    assert f'data-hide="{words.SIDEBAR_HIDE}"' in page


def test_the_sidebar_script_composes_nothing():
    code = code_of("sidebar.js")

    assert words.SIDEBAR_SHOW not in code
    assert words.SIDEBAR_HIDE not in code


def test_the_cookie_the_script_writes_is_scoped_and_samesite():
    """It is written by the script rather than by a round trip, so
    the attributes are the script's responsibility. `samesite=strict`
    for the same reason the token cookie has it, and a path so it is
    not scoped to whichever page happened to set it."""
    code = code_of("sidebar.js")

    assert "samesite=strict" in code.lower()
    assert "path=/" in code
