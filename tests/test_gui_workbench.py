"""The window's frame: the bar, the pane, the strip, and two faces.

Unit 11a replaced the sidebar and its pages with three panes. The bar
holds the actions and every action has one route: `GET /add` is the
form, as a dialog when htmx asks and as a page when nothing does, and
`POST /add` starts the add. The pane lists the collections and the
context bundle; a collection's documents are fetched when it is opened,
because drawing every document on every page costs about 0.7 ms a
document. The strip is where every operation reports.

**One variable was doing two jobs.** `--gutter` was the face of the
margin and also what `code, pre` was set in. The split kept: what
kennis composed wears `--gutter`, what must be read or typed verbatim
wears `--mono`.

**The pane's state is a cookie, not browser storage**, so the server
renders it and nothing flashes open before collapsing.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
from bs4 import BeautifulSoup, Tag
from click.testing import CliRunner
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.routing import BaseRoute

from kennis.cli.__main__ import main
from kennis.gui import words
from kennis.gui.app import build_app
from kennis.gui.theme import stylesheet
from kennis.writing import write_context_note, write_note

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
# The bar: every action, one route each
# ---------------------------------------------------------------------------

# Written by hand, not read from `words`. A test that compared the page
# against the list it was rendered from would agree with it however the
# list changed - concern #373. This is what Brian asked the bar to hold.
EXPECTED_ACTIONS = [
    ("/add", "Add"),
    ("/remember", "Note"),
    ("/index", "Index"),
    ("/sync", "Sync"),
    ("/pack", "Pack"),
]


def bar_actions(page: str) -> list[tuple[str, str]]:
    """Each action in the bar as (href, label), in order."""
    bar = re.search(r'<header class="bar"[^>]*>(.*?)</header>', page, re.DOTALL)
    assert bar is not None, "the page has no bar"
    return re.findall(
        r'<a class="action[^"]*" href="([^"]+)"[^>]*>'
        r'.*?<span class="label">([^<]+)</span>',
        bar.group(1),
        re.DOTALL,
    )


def test_the_bar_offers_every_action_in_order(corpus: Path, client: TestClient):
    admitted(client)

    assert bar_actions(client.get("/").text) == EXPECTED_ACTIONS


def test_every_action_is_a_page_for_a_reader_without_a_script(
    corpus: Path, client: TestClient
):
    """The action is an ordinary link. htmx turns it into a fetch into
    the dialog; without htmx it is followed, and the same form arrives
    inside the whole window. #366's rule, widened from the search box
    to every action."""
    admitted(client)

    for href, _ in EXPECTED_ACTIONS:
        page = client.get(href)
        assert page.status_code == 200, href
        assert "<html" in page.text, href
        assert '<header class="bar"' in page.text, href
        assert "<form" in page.text, href


def test_every_action_is_a_dialog_when_htmx_asks(corpus: Path, client: TestClient):
    admitted(client)

    for href, _ in EXPECTED_ACTIONS:
        fragment = client.get(href, headers={"HX-Request": "true"})
        assert fragment.status_code == 200, href
        assert fragment.text.lstrip().startswith("<dialog"), href
        assert "<html" not in fragment.text, href


def test_each_action_posts_to_the_path_it_is_shown_at(corpus: Path, client: TestClient):
    """One route per action: the form at `/add` starts an add at
    `/add`. A second path doing the same work is a second
    implementation waiting to drift."""
    admitted(client)

    for href, _ in EXPECTED_ACTIONS:
        dialog = client.get(href, headers={"HX-Request": "true"}).text
        posts = re.findall(r'hx-post="([^"]+)"', dialog)
        assert href in posts, (href, posts)


def test_a_dialog_is_headed_by_the_words_its_action_is_called(
    corpus: Path, client: TestClient
):
    """The same discipline as the old navigation labels against page
    headings (#346), one level down: a button saying "Index" that
    opens a dialog headed "Rebuild" is one thing with two names."""
    admitted(client)

    for href, label in EXPECTED_ACTIONS:
        dialog = client.get(href, headers={"HX-Request": "true"}).text
        heading = re.search(r"<h2[^>]*>([^<]+)</h2>", dialog)
        assert heading is not None, href
        assert label.lower() in heading.group(1).lower(), (href, heading.group(1))


def test_the_manage_page_and_the_holdings_page_are_gone(
    corpus: Path, client: TestClient
):
    """Removed, not redirected: kennis keeps no old paths (CLAUDE.md,
    global: no compatibility shims)."""
    admitted(client)

    assert client.get("/manage").status_code == 404
    assert client.get("/held").status_code == 404
    refused = client.post("/manage/add", data={"identifiers": "x"})
    assert refused.status_code in (404, 405)


# ---------------------------------------------------------------------------
# Every page is the whole window
# ---------------------------------------------------------------------------

PAGES = ("/", "/corpus", "/collection/notes", "/remember", "/add", "/index")


def test_every_page_carries_the_bar_the_pane_and_the_strip(
    corpus: Path, client: TestClient
):
    """The shell is rendered from `request` by Jinja globals, so a
    route that built its response another way would raise at template
    time rather than fail a test. Every page is loaded here."""
    admitted(client)

    for path in PAGES:
        page = client.get(path)
        assert page.status_code == 200, path
        assert '<header class="bar"' in page.text, path
        assert '<nav class="pane"' in page.text, path
        assert '<footer class="strip"' in page.text, path


def test_every_page_has_somewhere_for_an_operation_to_report(
    corpus: Path, client: TestClient
):
    """A dialog posts its job panel to `#job`. A dialog opened from a
    page without one would start the work and show nothing - the
    defect #405 is about."""
    admitted(client)

    for path in PAGES:
        strip = re.search(
            r'<footer class="strip".*?</footer>', client.get(path).text, re.DOTALL
        )
        assert strip is not None, path
        assert 'id="job"' in strip.group(0), path


# ---------------------------------------------------------------------------
# The pane
# ---------------------------------------------------------------------------


def pane_of(page: str) -> str:
    found = re.search(r'<nav class="pane".*?</nav>', page, re.DOTALL)
    assert found is not None, "the page has no pane"
    return found.group(0)


def collection_states(page: str) -> dict[str, str]:
    return dict(
        re.findall(r'data-collection="([^"]+)"[^>]*data-state="([^"]+)"', pane_of(page))
    )


def test_the_pane_lists_every_collection(corpus: Path, client: TestClient):
    admitted(client)

    assert list(collection_states(client.get("/").text)) == [
        "literature",
        "docs",
        "notes",
    ]


# Written by hand: the places the pane's kennis section offers, as the
# mockup lists them, and where each leads (#373).
EXPECTED_KENNIS_PLACES = [
    ("/", "Recent searches"),
    ("/activity", "Activity"),
    ("/corpus#packs", "Packs"),
    ("/settings", "Settings"),
]


def test_the_pane_offers_the_mockups_places(corpus: Path, client: TestClient):
    admitted(client)
    pane = BeautifulSoup(pane_of(client.get("/").text), "html.parser")
    section = pane.find_all("section")[-1]
    places = [
        (str(link["href"]), link.find(class_="name").get_text(strip=True))
        for link in section.select("a.node")
    ]

    assert places == EXPECTED_KENNIS_PLACES
    for href, _ in places:
        assert client.get(href.split("#")[0]).status_code == 200


def test_the_pane_says_how_much_is_held_and_what_its_dots_mean(
    corpus: Path, client: TestClient
):
    admitted(client)
    write_note("Calibration converged after three rounds.")

    pane = BeautifulSoup(pane_of(client.get("/").text), "html.parser")
    text = " ".join(pane.get_text(" ").split())

    assert words.documents_held(1) in text
    legend = pane.find(class_="legend")
    assert isinstance(legend, Tag)
    shown = legend.get_text(" ")
    assert words.PANE_STATES["current"] in shown
    assert words.PANE_STATES["behind"] in shown


def test_the_pane_says_which_collections_need_indexing(
    corpus: Path, client: TestClient
):
    """Four states, and the two that are easy to conflate are kept
    apart: an empty collection has nothing to index, and a collection
    never indexed is not *stale* - concern #245's distinction."""
    admitted(client)
    write_note("Calibration converged after three rounds.")
    never = collection_states(client.get("/").text)

    # The first index of a collection is a deliberate act: `remember`
    # rebuilds an index that exists and never builds the first one.
    indexing = ["corpus", "index", "--collection", "notes"]
    assert CliRunner().invoke(main, indexing).exit_code == 0
    indexed = collection_states(client.get("/").text)

    write_note("A second note, deliberately left out.", index=False)
    behind = collection_states(client.get("/").text)

    assert never["literature"] == "empty"
    assert never["notes"] == "none"
    assert indexed["notes"] == "current"
    assert behind["notes"] == "behind"


def test_the_documents_are_not_drawn_on_every_page(corpus: Path, client: TestClient):
    """Measured on Brian's corpus: the whole tree is about 0.7 ms a
    document, so a thousand documents would be most of a second on
    every page. A collection's documents are fetched when it is
    opened; the page carries only the address to fetch them from."""
    admitted(client)
    write_note("Calibration converged after three rounds.")

    pane = pane_of(client.get("/").text)

    assert 'hx-get="/tree/notes"' in pane
    assert "/document/notes/" not in pane


def test_an_opened_collection_lists_its_groups_and_documents(
    corpus: Path, client: TestClient
):
    admitted(client)
    write_note("Calibration converged after three rounds.", group="observing")

    tree = client.get("/tree/notes").text

    assert "observing" in tree
    assert re.search(r'href="/document/notes/[^"]+"', tree)
    assert "<html" not in tree


def test_a_collection_name_is_a_link_for_a_reader_without_a_script(
    corpus: Path, client: TestClient
):
    """Opening a `<details>` fetches its documents only with htmx.
    The name itself links to the collection's page, which is the way
    in without it."""
    admitted(client)

    assert 'href="/collection/notes"' in pane_of(client.get("/").text)


def test_the_tree_route_is_guarded(corpus: Path, client: TestClient):
    """The guard is middleware and covers it; asserted rather than
    assumed, because the tree lists every title held."""
    assert client.get("/tree/notes").status_code == 401


def test_the_context_is_named_after_its_project(
    corpus: Path, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The bundle's manifest carries no name, and `.context` is the
    same in every project. The directory that holds it is the
    project's name (#407)."""
    project = tmp_path / "boepie"
    project.mkdir()
    monkeypatch.chdir(project)
    assert CliRunner().invoke(main, ["context", "init"]).exit_code == 0
    # A fresh bundle holds only its landing page and hidden scaffolding,
    # neither of which `bundle_documents` counts.
    write_context_note("Solution intervals are per scan.", title="Intervals")
    admitted(client)

    pane = pane_of(client.get("/").text)

    assert re.search(r'class="project"[^>]*>boepie<', pane), pane
    assert 'hx-get="/tree/context"' in pane
    assert re.search(r'href="/bundle/[^"]+\.md"', client.get("/tree/context").text)


def test_without_a_bundle_the_context_section_says_so(corpus: Path, client: TestClient):
    admitted(client)

    assert words.NO_CONTEXT in pane_of(client.get("/").text)


# ---------------------------------------------------------------------------
# Search from anywhere
# ---------------------------------------------------------------------------


def search_form(page: str) -> str:
    found = re.search(r'<form class="searchbox"[^>]*>', page)
    assert found is not None, "the bar has no search form"
    return found.group(0)


def test_the_search_form_reaches_the_search_page_from_any_page(
    corpus: Path, client: TestClient
):
    """The form is in the bar now, so it is on every page. With no
    `action`, a scriptless search from `/corpus` would go to
    `/corpus?q=`. Never `/hits`, which answers a bare fragment."""
    admitted(client)

    for path in PAGES:
        assert 'action="/"' in search_form(client.get(path).text), path


def test_only_the_search_page_searches_as_you_type(corpus: Path, client: TestClient):
    """Live search swaps into `#hits`, which only the search page has.
    Elsewhere the form is a plain navigation to `/`."""
    admitted(client)

    assert 'hx-get="/hits"' in search_form(client.get("/").text)
    assert "hx-get" not in search_form(client.get("/corpus").text)


# ---------------------------------------------------------------------------
# Collapsing the pane, and where the state lives
# ---------------------------------------------------------------------------


def test_the_pane_state_is_rendered_by_the_server_from_the_cookie(
    corpus: Path, client: TestClient
):
    """Read after paint from `localStorage`, the pane would show open
    and then collapse on every page load. A cookie is on the request,
    so the first byte is already right."""
    admitted(client)

    opened = client.get("/").text
    client.cookies.set("pane", "closed")
    closed = client.get("/").text

    assert 'data-pane="open"' in opened
    assert 'data-pane="closed"' in closed


def test_an_unknown_cookie_value_is_open(corpus: Path, client: TestClient):
    admitted(client)
    client.cookies.set("pane", "sideways")

    assert 'data-pane="open"' in client.get("/").text


def test_the_toggle_is_in_the_bar_and_not_in_what_it_hides(
    corpus: Path, client: TestClient
):
    """A collapsed pane that took its own toggle with it could not be
    reopened. The toggle lives in the bar, which never collapses."""
    admitted(client)
    page = client.get("/").text

    bar = re.search(r'<header class="bar".*?</header>', page, re.DOTALL)
    assert bar is not None
    assert 'id="pane-toggle"' in bar.group(0)
    assert 'id="pane-toggle"' not in pane_of(page)


def test_the_toggle_carries_both_its_names_from_python(
    corpus: Path, client: TestClient
):
    admitted(client)

    page = client.get("/").text

    assert f'data-show="{words.PANE_SHOW}"' in page
    assert f'data-hide="{words.PANE_HIDE}"' in page


def test_the_scripts_compose_nothing():
    for script in ("pane.js", "dialog.js"):
        code = code_of(script)
        for name in words.__all__:
            text = getattr(words, name)
            if isinstance(text, str) and len(text) > 12:
                assert text not in code, (script, name)


def test_the_cookie_the_script_writes_is_scoped_and_samesite():
    code = code_of("pane.js")

    assert "samesite=strict" in code.lower()
    assert "path=/" in code


# ---------------------------------------------------------------------------
# Icons
# ---------------------------------------------------------------------------

ICONS = STATIC / "vendor" / "icons"


def icons_named() -> set[str]:
    """Every icon a template or `words` asks for by name."""
    named: set[str] = set()
    for template in TEMPLATES.glob("*.html"):
        named |= set(
            re.findall(r"icon\(\"([a-z-]+)\"\)", template.read_text(encoding="utf-8"))
        )
    for _, _, icon_name in words.ACTIONS:
        named.add(icon_name)
    named |= set(words.COLLECTION_ICONS.values())
    named |= set(words.MEASURE_ICONS.values())
    named |= {icon_name for _, _, icon_name in words.SOURCE_CHOICES}
    named |= set(words.STATUS_ICONS.values())
    return named


def test_every_icon_asked_for_is_vendored():
    vendored = {path.stem for path in ICONS.glob("*.svg")}

    assert icons_named() <= vendored, sorted(icons_named() - vendored)


def test_every_vendored_icon_is_used():
    """Declared, present, *and used*: a vendored file nothing asks for
    is shipped for nothing and declared for nothing (#357)."""
    vendored = {path.stem for path in ICONS.glob("*.svg")}

    assert vendored <= icons_named(), sorted(vendored - icons_named())


def test_an_icon_is_inlined_so_it_takes_the_text_colour(
    corpus: Path, client: TestClient
):
    """An `<img>` cannot inherit `currentColor`, so an icon in an
    `<img>` would be one colour in both themes."""
    admitted(client)
    page = client.get("/").text

    assert re.search(r'<svg class="icon"[^>]*stroke="currentColor"', page)
    assert '<img src="/static/vendor/icons' not in page


def test_each_collection_has_an_icon_for_its_kind():
    assert set(words.COLLECTION_ICONS) == {"literature", "docs", "notes"}


# ---------------------------------------------------------------------------
# The layout
# ---------------------------------------------------------------------------


def test_the_window_is_sized_by_the_viewport_and_not_by_arithmetic():
    """The mockup sized the shell as `calc(100% - 2.3rem)`, and the
    strip clipped at the bottom as soon as the bar above it wrapped.
    Brian saw it. A grid sized by the dynamic viewport puts the strip
    at the bottom whatever is above it."""
    assert "100dvh" in rules_for(".shell")
    assert "calc(100%" not in rules_for(".shell")


# ---------------------------------------------------------------------------
# Nothing a route does stops the server
# ---------------------------------------------------------------------------


# Written by hand: how many routes the window answers. The walk below is
# what both tests read, and an included router it failed to enter would
# otherwise leave them asserting over nothing.
# 48th and 49th: GET and POST /docs/remove-version (#489); 50th to 54th: GET
# and POST /document/remove and /corpus/return, POST /corpus/restore
EXPECTED_ROUTES = 54


def every_route(routes: Sequence[BaseRoute]) -> Iterator[APIRoute]:
    """Each route, inside the routers `build_app` includes as well."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        included = getattr(route, "original_router", None)
        if included is not None:
            yield from every_route(included.routes)


def test_every_route_is_found():
    assert len(list(every_route(build_app(TOKEN).routes))) == EXPECTED_ROUTES


def test_no_route_runs_on_the_event_loop():
    """An `async` route runs on the event loop, and every route here reads
    the corpus, starts git or renders the pane - 600 ms a page at a thousand
    documents. One of them running stopped every other request, a job's
    progress stream included. A plain `def` runs on a worker thread; the
    form a POST carries is read by an `async` dependency instead."""
    on_the_loop = [
        route.path
        for route in every_route(build_app(TOKEN).routes)
        if inspect.iscoroutinefunction(route.endpoint)
    ]

    assert on_the_loop == []
