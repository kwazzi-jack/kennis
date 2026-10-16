"""The window in a real browser: what the rest of the suite cannot see.

Every other GUI test reads markup or a stylesheet as text. That proves the
server says the right thing; it cannot prove the page *does* it - that htmx
swaps the results in, that a script reads the header it is meant to, that a
style rule is not overridden by another one. Several defects were found by
walking the interface in a headless browser and were invisible in the
source (#340, #351, #371); this keeps those walks.

**Deselected by default**, with the `browser` marker, because it needs a
browser: `uv sync --group browser`, then `uv run playwright install
chromium`, then `uv run pytest -m browser`. `KENNIS_TEST_CHROMIUM` names a
Chromium to use instead of Playwright's own.

Each test is one thing a person does, with the server and the browser as
they would run them: `serve.run` on a thread, on loopback, with its token.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.gui import serve, words

playwright = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser

# Long enough for a cold Chromium on a loaded CI runner; a passing check is
# over in well under a second.
_WAIT_MS = 10_000


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    run = CliRunner()
    assert run.invoke(main, ["corpus", "init"]).exit_code == 0
    source = tmp_path / "sources" / "calibration.md"
    source.parent.mkdir(parents=True)
    source.write_text(
        "# Calibration\n\nAntenna gains drift on long tracks.\n\n"
        "The model is $$g(t) = g_0 e^{i \\phi(t)}$$\n\n"
        "| Source | Flux |\n|---|---|\n| J1000+30 | 4 |\n",
        encoding="utf-8",
    )
    assert run.invoke(main, ["corpus", "add", "-n", str(source)]).exit_code == 0
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0
    return tmp_path


@pytest.fixture
def address(corpus: Path) -> Iterator[str]:
    """The address `kennis gui` prints, token and all, for a running server."""
    ready = threading.Event()
    given: list[str] = []

    def note(url: str) -> None:
        given.append(url)
        ready.set()

    runner = threading.Thread(
        target=serve.run, args=(note,), kwargs={"open_browser": False}, daemon=True
    )
    runner.start()
    assert ready.wait(10)
    yield given[0]
    with httpx.Client(timeout=10) as http:
        http.post(given[0].replace("/?", "/quit?"))
    runner.join(timeout=10)


def _benign(text: str) -> bool:
    """Chromium's own note that a page's cross-fade was cut short by the
    next navigation - a test clicks faster than a person. It is the
    browser's, not any script of kennis's - the cross-fade is CSS's
    `@view-transition`, and no script here starts one - and nothing was lost
    by it. Only this message is let through."""
    return text.startswith("Transition was aborted because of invalid state")


@pytest.fixture
def page(address: str) -> Iterator[object]:
    """A tab that has opened the address, failing the test on any error the
    page's own scripts raise or the console reports."""
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(
            executable_path=os.environ.get("KENNIS_TEST_CHROMIUM") or None
        )
        tab = browser.new_page()
        problems: list[str] = []
        # Both channels: Chromium reports the cut-short cross-fade as a
        # console line on one navigation and as an uncaught error on another.
        tab.on(
            "pageerror",
            lambda error: (
                problems.append(str(error)) if not _benign(str(error)) else None
            ),
        )
        tab.on(
            "console",
            lambda message: (
                problems.append(message.text)
                if message.type == "error" and not _benign(message.text)
                else None
            ),
        )
        tab.goto(address)
        yield tab
        browser.close()
        assert problems == []


def test_the_page_is_drawn_in_the_theme(page: playwright.Page) -> None:
    """The stylesheet arrived and applied: the ground is the theme's, not
    the browser's white."""
    ground = page.evaluate("getComputedStyle(document.body).backgroundColor")

    assert ground not in ("rgba(0, 0, 0, 0)", "rgb(255, 255, 255)")


def test_the_bar_draws_the_book_in_each_theme(page: playwright.Page) -> None:
    """The book is a background the theme block chooses, so a test of the
    source can say only that a variable exists. Here it is resolved: drawn
    at a size, and a different drawing on a dark system than a light."""
    drawn: dict[str, str] = {}
    for scheme in ("light", "dark"):
        page.emulate_media(color_scheme=scheme)
        book = page.locator(".wordmark .book")
        box = book.bounding_box()
        assert box is not None and box["width"] >= 16 and box["height"] >= 16
        drawn[scheme] = book.evaluate(
            "element => getComputedStyle(element).backgroundImage"
        )
        assert drawn[scheme].startswith('url("data:image/svg+xml,'), drawn[scheme][:40]
    assert drawn["light"] != drawn["dark"]


def test_typing_a_search_draws_its_results(page: playwright.Page) -> None:
    page.fill("input[name=q]", "antenna")

    page.wait_for_selector("#hits .hit", timeout=_WAIT_MS)

    assert "Antenna gains drift" in page.inner_text("#hits")


def test_a_live_search_is_announced_and_titled(page: playwright.Page) -> None:
    """Results swapped in without a navigation: a screen reader heard
    nothing and the tab still said "kennis"."""
    page.fill("input[name=q]", "antenna")
    page.wait_for_selector("#hits .hit", timeout=_WAIT_MS)
    page.wait_for_function(
        "document.getElementById('hits-status').textContent !== ''",
        timeout=_WAIT_MS,
    )

    assert "antenna" in page.title()
    assert page.inner_text("#hits .summary") in page.text_content("#hits-status")


def test_the_first_tab_stop_skips_to_the_content(page: playwright.Page) -> None:
    first = page.evaluate(
        'document.querySelector(\'a[href], button:not([tabindex="-1"]), '
        'input, select, textarea, [tabindex]:not([tabindex="-1"])\').className'
    )
    assert first == "skip-link"

    page.focus(".skip-link")
    page.keyboard.press("Enter")
    assert page.evaluate("document.activeElement.id") == "main"


def test_a_document_is_typeset(page: playwright.Page) -> None:
    page.fill("input[name=q]", "antenna")
    page.wait_for_selector("#hits .hit a.open", timeout=_WAIT_MS)

    page.click("#hits .hit a.open")

    page.wait_for_selector(".katex", timeout=_WAIT_MS)


def test_a_document_s_table_has_its_cells_kept_apart(page: playwright.Page) -> None:
    """Left to the browser a table had no padding and no rules, and its
    cells ran together: "J1000+30 4"."""
    page.fill("input[name=q]", "antenna")
    page.wait_for_selector("#hits .hit a.open", timeout=_WAIT_MS)
    page.click("#hits .hit a.open")
    page.wait_for_selector("article td", timeout=_WAIT_MS)

    cell = page.evaluate(
        "(() => { const s = getComputedStyle(document.querySelector('article td'));"
        " return [s.paddingRight, s.borderBottomWidth]; })()"
    )

    assert cell[0] != "0px"
    assert cell[1] != "0px"


def test_a_note_written_here_is_not_announced_as_someone_else_s(
    page: playwright.Page,
) -> None:
    """The banner names writers other than this window (#311). Its own
    note does not reload the page, so the page's revision has to move
    with it, or the next focus calls the note a change from elsewhere."""
    page.click("a[href='/remember']")
    page.wait_for_selector("#dialog textarea[name=text]", timeout=_WAIT_MS)
    page.fill("#dialog textarea[name=text]", "Deconvolution needs a clean beam.")

    page.click("#dialog button[type=submit]")
    page.wait_for_selector("#dialog .role-operation", timeout=_WAIT_MS)
    page.evaluate("window.dispatchEvent(new Event('focus'))")
    page.wait_for_timeout(500)

    assert page.is_hidden("#corpus-changed")


def test_after_a_note_focus_is_back_in_the_box(page: playwright.Page) -> None:
    """The submit button is disabled while the write runs, so focus fell
    to the page behind the dialog and the next keystroke went nowhere."""
    page.click("a[href='/remember']")
    page.wait_for_selector("#dialog textarea[name=text]", timeout=_WAIT_MS)
    page.fill("#dialog textarea[name=text]", "Phase closure holds per triangle.")

    page.click("#dialog button[type=submit]")
    page.wait_for_selector("#dialog .role-operation", timeout=_WAIT_MS)
    page.wait_for_timeout(200)

    assert page.evaluate("document.activeElement.id") == "remember-text"


def test_the_note_dialog_s_fields_are_one_line_tall(page: playwright.Page) -> None:
    """A labelled field took the row's flex basis as its height, and the
    Title and Group fields were drawn 190px tall."""
    page.click("a[href='/remember']")
    page.wait_for_selector("#dialog input[name=title]", timeout=_WAIT_MS)

    height = page.evaluate(
        "document.querySelector('#dialog input[name=title]').offsetHeight"
    )

    assert height < 60


def test_a_write_from_a_terminal_is_announced(page: playwright.Page) -> None:
    source = Path(os.environ["KENNIS_CORPUS_ROOT"]).parent / "sources" / "imaging.md"
    source.write_text("# Imaging\n\nDeconvolution.\n", encoding="utf-8")
    assert CliRunner().invoke(main, ["corpus", "add", "-n", str(source)]).exit_code == 0

    page.evaluate("window.dispatchEvent(new Event('focus'))")

    page.wait_for_selector("#corpus-changed:not([hidden])", timeout=_WAIT_MS)
    assert page.inner_text("#corpus-changed") == words.CORPUS_CHANGED


def test_an_index_started_here_reports_its_outcome(page: playwright.Page) -> None:
    page.goto(page.url.split("?")[0] + "index")

    page.click("form[action='/index'] button[type=submit]")

    page.wait_for_selector(f"text={words.JOB_KINDS['index']}", timeout=_WAIT_MS)
    page.wait_for_selector("#job .job-outcome p", timeout=_WAIT_MS)


def test_an_index_starts_without_a_script(address: str) -> None:
    """The window works without a script (11a). Six forms had only
    `hx-post`, so here the button submitted a GET to the page it was on;
    and with that fixed, the origin check refused the POST, because under
    `no-referrer` a plain form's origin is sent as `null`."""
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(
            executable_path=os.environ.get("KENNIS_TEST_CHROMIUM") or None
        )
        tab = browser.new_context(java_script_enabled=False).new_page()
        tab.goto(address)
        tab.goto(address.split("?")[0] + "index")

        tab.click("form[action='/index'] button[type=submit]")

        assert "/job/" in tab.url
        browser.close()


def test_the_pane_closes_and_stays_closed(page: playwright.Page) -> None:
    page.click("#pane-toggle")
    page.reload()

    assert page.evaluate("document.documentElement.dataset.pane") == "closed"


def test_at_phone_width_the_bar_keeps_its_names_and_the_pane_is_a_drawer(
    page: playwright.Page,
) -> None:
    """Below 46rem every action's name was `display: none` - a link with
    no name - and the pane and its toggle were removed outright, taking
    the tree with them. At 400% zoom a laptop is this narrow too."""
    page.set_viewport_size({"width": 390, "height": 844})
    page.reload()

    shown = page.evaluate(
        "[...document.querySelectorAll('.action .label')]"
        ".map(label => getComputedStyle(label).display)"
    )
    assert shown and "none" not in shown
    assert page.is_hidden(".pane")

    page.click("#pane-toggle")
    page.wait_for_selector(".pane", state="visible", timeout=_WAIT_MS)
    page.keyboard.press("Escape")
    page.wait_for_selector(".pane", state="hidden", timeout=_WAIT_MS)


def test_a_row_menu_stays_in_the_window_and_closes_when_focus_leaves(
    page: playwright.Page,
) -> None:
    """Clipped by the pane's edge ("pen", "ove to group"), and left open
    over whatever the keyboard moved on to."""
    # Opened by its property: a click on the row lands on the name,
    # which is a link to the collection's page.
    page.evaluate(
        "document.querySelector('.tree li[data-collection=notes] > details')"
        ".open = true"
    )
    page.wait_for_selector("li.row details.menu summary", timeout=_WAIT_MS)
    page.click("li.row details.menu summary")
    page.wait_for_selector("li.row details.menu[open] .menu-items", timeout=_WAIT_MS)

    left = page.evaluate(
        "document.querySelector('details.menu[open] .menu-items')"
        ".getBoundingClientRect().left"
    )
    assert left >= 0

    page.focus("input[name=q]")
    assert page.query_selector("details.menu[open]") is None


def test_the_search_key_is_not_typed_into_the_empty_box(page: playwright.Page) -> None:
    """The box is focused on arrival, so `/` - the key drawn in it for
    "go to the search" - became the first character of the query."""
    page.focus("input[name=q]")
    page.keyboard.press("/")
    page.keyboard.type("gain")

    assert page.input_value("input[name=q]") == "gain"


def test_a_refused_add_keeps_the_dialog_and_what_was_typed(
    page: playwright.Page,
) -> None:
    """The dialog closed on every submit, so a refusal arrived in the
    strip and everything typed into the form was gone."""
    page.goto(page.url.split("?")[0])
    page.click("a.action[href='/add']")
    page.wait_for_selector("#dialog .add-tab", timeout=_WAIT_MS)
    page.click("#dialog a.tab[href*='kind=group']")
    page.wait_for_selector("#dialog textarea[name=lines-1]", timeout=_WAIT_MS)
    page.fill("#dialog input[name=group-1]", "instruments")
    page.fill("#dialog textarea[name=lines-1]", "a-note.md")

    page.click("#dialog form[action='/add'] button[type=submit]")
    page.wait_for_selector("#add-problem p", timeout=_WAIT_MS)

    assert page.is_visible("#dialog dialog[open], #dialog dialog")
    assert words.CHOOSE_A_COLLECTION in page.inner_text("#add-problem")
    assert page.input_value("#dialog textarea[name=lines-1]") == "a-note.md"


def test_the_palette_finds_a_document_only_once_something_is_typed(
    page: playwright.Page,
) -> None:
    page.keyboard.press("Control+k")
    page.wait_for_selector("#dialog .palette-input", timeout=_WAIT_MS)
    assert page.is_hidden("#dialog [data-typed]")

    page.fill("#dialog .palette-input", "calibration")

    page.wait_for_selector("#dialog [data-typed]:not([hidden])", timeout=_WAIT_MS)
    shown = page.inner_text("#dialog [data-typed]:not([hidden])")
    assert "calibration" in shown.casefold()


def test_the_palette_opens_on_its_shortcut(page: playwright.Page) -> None:
    page.keyboard.press("Control+k")

    page.wait_for_selector("#dialog input", timeout=_WAIT_MS)


# Written by hand: every page a person can reach from the bar, the pane and
# the palette. The `page` fixture fails a test on any console error.
PAGES = [
    "",
    "corpus",
    "collection/notes",
    "settings",
    "activity",
    "add",
    "add?kind=paper",
    "add?kind=site",
    "remember",
    "index",
    "sync",
    "pack",
    "palette",
    "?q=antenna",
]


@pytest.mark.parametrize("path", PAGES)
def test_every_page_opens_without_an_error(page: playwright.Page, path: str) -> None:
    answer = page.goto(page.url.split("?")[0] + path)

    assert answer is not None and answer.status == 200
    assert page.evaluate("document.styleSheets.length") >= 1


# The browser's own link colours, unvisited and visited.
_BROWSER_BLUES = ("rgb(0, 0, 238)", "rgb(85, 26, 139)")


def test_no_link_wears_the_browser_s_own_colour(page: playwright.Page) -> None:
    """The strip's "Last:" link and Activity's job links were the
    browser's blue, about 1.6:1 on the dark strip. A stylesheet test
    cannot see that: the colour was nobody's in the palette. Both links
    exist only once something has run, so an index runs first."""
    root = page.url.split("?")[0]
    page.goto(root + "index")
    page.click("form[action='/index'] button[type=submit]")
    page.wait_for_selector("#job .job-outcome p", timeout=_WAIT_MS)

    seen: set[str] = set()
    for path in PAGES:
        page.goto(root + path)
        seen |= set(
            page.evaluate(
                "[...document.querySelectorAll('a')]"
                ".map(a => getComputedStyle(a).color)"
            )
        )

    assert not seen & set(_BROWSER_BLUES)


def test_an_inline_script_does_not_run(address: str) -> None:
    """What a converted page that escaped the renderer could add: the
    browser refuses it under the window's content policy."""
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(
            executable_path=os.environ.get("KENNIS_TEST_CHROMIUM") or None
        )
        tab = browser.new_page()
        tab.goto(address)

        ran = tab.evaluate(
            """() => {
                const script = document.createElement("script");
                script.textContent = "window.injected = true";
                document.body.appendChild(script);
                return window.injected === true;
            }"""
        )

        assert ran is False
        browser.close()


def test_a_file_chosen_in_the_browsers_picker_is_added(
    page: playwright.Page, corpus: Path, tmp_path: Path
) -> None:
    """The browser's own picker, through the form: the native dialog of the
    computer the reader sits at, which is the one that works when kennis
    runs elsewhere behind `ssh -L`. Recorded as uploaded, not as the
    temporary path it was read from."""
    chosen = tmp_path / "elsewhere" / "beam-model.md"
    chosen.parent.mkdir()
    chosen.write_text("# Beam model\n\nThe primary beam.\n", encoding="utf-8")
    page.goto(page.url.split("?")[0])
    page.click("a.action[href='/add']")
    page.wait_for_selector("#dialog .add-tab", timeout=_WAIT_MS)
    page.click("#dialog a.tab[href*='kind=file']")
    # The Files tab's own picker: the Paper tab, open first, has one too,
    # and a wait that matched it could act on a tab about to be replaced.
    page.wait_for_selector(
        '#dialog .field[data-uploads="both"] input[name=upload][multiple]',
        timeout=_WAIT_MS,
    )

    page.set_input_files("#dialog input[name=upload][multiple]", str(chosen))
    page.click("#dialog .choices label:has(input[value=notes])")
    page.click("#dialog form[action='/add'] button[type=submit]")

    added: list[Path] = []
    for _ in range(100):
        added = [
            path
            for path in (corpus / "corpus" / "notes").rglob("*.md")
            if "Beam model" in path.read_text(encoding="utf-8")
        ]
        if added:
            break
        page.wait_for_timeout(100)
    [document] = added
    assert "from: upload:beam-model.md" in document.read_text(encoding="utf-8")


def test_what_was_chosen_in_the_picker_is_said_back_and_can_be_cleared(
    page: playwright.Page, tmp_path: Path
) -> None:
    """The bare inputs said "Choose File" on both and "No file chosen"
    beside them; the picker now names what it will send."""
    chosen = []
    for name in ("a.md", "b.md", "c.md", "d.md"):
        path = tmp_path / name
        path.write_text(f"# {name}\n", encoding="utf-8")
        chosen.append(str(path))
    folder = tmp_path / "papers"
    (folder / "deep").mkdir(parents=True)
    (folder / "one.md").write_text("# One\n", encoding="utf-8")
    (folder / "deep" / "two.md").write_text("# Two\n", encoding="utf-8")
    page.goto(page.url.split("?")[0])
    page.click("a.action[href='/add']")
    page.wait_for_selector("#dialog .add-tab", timeout=_WAIT_MS)
    page.click("#dialog a.tab[href*='kind=file']")
    page.wait_for_selector(
        '#dialog .field[data-uploads="both"] .uploads[data-enhanced]',
        timeout=_WAIT_MS,
    )
    said = "#dialog .upload-said"

    assert page.inner_text(said) == words.UPLOAD_SAID["none"]
    # Hidden from sight, not from the form or the keyboard.
    assert (
        page.eval_on_selector(
            "#dialog input[name=upload][multiple]", "e => getComputedStyle(e).opacity"
        )
        == "0"
    )

    page.set_input_files("#dialog input[name=upload][multiple]", chosen)
    assert page.inner_text(said) == "4 files: a.md, b.md, c.md and 1 more"

    page.click("#dialog [data-upload-clear]")
    assert page.inner_text(said) == words.UPLOAD_SAID["none"]

    page.set_input_files("#dialog input[name=upload][webkitdirectory]", str(folder))
    assert page.inner_text(said) == "The folder papers, 2 files"


def test_project_shows_on_the_files_tab_only_for_docs(page: playwright.Page) -> None:
    """It names a docs page's directory and nothing else, and was offered
    for every collection."""
    page.goto(page.url.split("?")[0])
    page.click("a.action[href='/add']")
    page.wait_for_selector("#dialog .add-tab", timeout=_WAIT_MS)
    page.click("#dialog a.tab[href*='kind=file']")
    page.wait_for_selector("#dialog .field[data-name=collection]", timeout=_WAIT_MS)
    project = "#dialog .field[data-name=project]"

    assert page.is_hidden(project)
    page.click("#dialog .choices label:has(input[value=notes])")
    assert page.is_hidden(project)
    page.click("#dialog .choices label:has(input[value=docs])")
    assert page.is_visible(project)


def test_the_paper_tab_shows_only_the_way_in_chosen(page: playwright.Page) -> None:
    """The identifier field up front, and a PDF's picker and identifier
    only once PDF is chosen - an arXiv ID was typed into both."""
    page.goto(page.url.split("?")[0])
    page.click("a.action[href='/add']")
    page.wait_for_selector("#dialog .ways", timeout=_WAIT_MS)
    typed = "#dialog .field[data-name=identifiers]"
    pdf = "#dialog .field[data-name=pdf]"
    which = "#dialog .field[data-name=identifier]"

    assert page.is_visible(typed)
    assert page.is_hidden(pdf) and page.is_hidden(which)
    page.click("#dialog .choices label:has(input[value=pdf])")
    assert page.is_hidden(typed)
    assert page.is_visible(pdf) and page.is_visible(which)
