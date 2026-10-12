"""Unit 11b: the window says what it is doing, at every time scale.

About 0.1 s feels immediate, about 1 s keeps attention, and past about
10 s a person needs a report (#405). So: a button changes the moment it
is pressed, the strip names the item in hand and how long the job has
run, a job stays visible on every page until it ends, and a page lists
what ran.

And #412: a form sent without a script reached its route and was
answered with a fragment for a strip the browser had never drawn. A
POST that did not come from htmx now answers with a page.
"""

from __future__ import annotations

import re
import threading
import time
from itertools import pairwise
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from click.testing import CliRunner
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.engine.corpus.sync import CorpusSync
from kennis.engine.events import EventSink, ItemFinished, ItemStarted, Outcome
from kennis.engine.history.repository import Repository
from kennis.engine.pack.resolve import Action
from kennis.engine.rag.embedding import FETCH_MODEL
from kennis.engine.refusals import Quoted
from kennis.gui import words
from kennis.gui.app import build_app
from kennis.gui.jobs import Elapsed, Jobs
from kennis.gui.pages import shown_corpus_sync
from kennis.gui.stream import as_message
from kennis.render.words import running_for

TOKEN = "a-test-token"
STATIC = Path(__file__).parent.parent / "src" / "kennis" / "gui" / "static"
HTMX = {"HX-Request": "true"}


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    return tmp_path


@pytest.fixture
def app(corpus: Path) -> FastAPI:
    return build_app(TOKEN)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    opened = TestClient(app, follow_redirects=False)
    assert opened.get("/", params={"token": TOKEN}).status_code == 200
    return opened


def code_of(name: str) -> str:
    """A script with its comment lines removed, so prose cannot satisfy
    an assertion about code (#337, #373)."""
    script = (STATIC / name).read_text(encoding="utf-8")
    return "\n".join(
        line for line in script.splitlines() if not line.strip().startswith("//")
    )


def strip_of(page: str) -> str:
    start = page.index('<footer class="strip">')
    return page[start : page.index("</footer>", start)]


def held(app: FastAPI, kind: str = "add") -> tuple[threading.Event, str]:
    """A job that runs until the test lets it go."""
    holding = threading.Event()
    job = app.state.jobs.start(kind, lambda events: holding.wait(20))
    return holding, job.id


# ---------------------------------------------------------------------------
# Immediate: the button changes before the server answers
# ---------------------------------------------------------------------------

# Written by hand, not read from the templates: which forms post, per
# dialog. A form added without the attribute fails below; a form dropped
# from a dialog fails here (#373).
POSTING_FORMS = {"/add": 1, "/index": 1, "/sync": 2, "/pack": 1, "/remember": 1}


@pytest.mark.parametrize(("route", "expected"), sorted(POSTING_FORMS.items()))
def test_every_form_that_posts_disables_its_button_while_it_waits(
    client: TestClient, route: str, expected: int
):
    dialog = client.get(route, headers=HTMX).text
    forms = re.findall(r"<form\b[^>]*\bhx-post=[^>]*>", dialog)

    assert len(forms) == expected
    for form in forms:
        # The submit button by type: `find` takes the first match, and
        # the Add tabs put a Browse button ahead of it (11d).
        assert 'hx-disabled-elt="find button[type=submit]"' in form, form


def test_a_waiting_form_looks_busy(client: TestClient):
    """htmx puts `htmx-request` on the form while its request is out;
    without a rule for it the disabled button is the only sign."""
    stylesheet = client.get("/static/kennis.css").text

    assert re.search(r"\.htmx-request[^{]*button[^{]*\{", stylesheet)


# ---------------------------------------------------------------------------
# Seconds: what is in hand, and for how long
# ---------------------------------------------------------------------------


def test_an_item_that_has_started_is_named():
    """It was dropped, so a single PDF read "0 of 1" for twenty seconds
    of MinerU with no name on it."""
    message = as_message(ItemStarted(operation="add", item="arXiv:1101.2268"))

    assert message == {"kind": "current", "text": "Adding arXiv:1101.2268"}


def test_a_model_download_is_named_as_one():
    message = as_message(ItemStarted(operation=FETCH_MODEL, item="bge-small-en"))

    assert message is not None
    assert message["kind"] == "current"
    assert "bge-small-en" in str(message["text"])
    assert str(message["text"]).startswith("Downloading")


def test_elapsed_time_is_worded_in_python():
    assert running_for(0.4) == "0s"
    assert running_for(41.9) == "41s"
    assert running_for(125) == "2m05s"
    assert running_for(3725) == "1h02m"
    assert as_message(Elapsed(seconds=41.2)) == {"kind": "elapsed", "text": "41s"}


def test_the_stream_reports_elapsed_time_while_a_job_runs():
    """Once a second, from the stream's own clock, and only while the
    job runs: a finished job's stream still ends."""
    jobs = Jobs()
    holding = threading.Event()
    job = jobs.start("add", lambda events: holding.wait(20))
    releaser = threading.Timer(2.6, holding.set)
    releaser.start()

    began = time.monotonic()
    ticks = [item for item in jobs.stream(job) if isinstance(item, Elapsed)]
    took = time.monotonic() - began

    assert len(ticks) >= 2
    assert all(later.seconds > earlier.seconds for earlier, later in pairwise(ticks))
    assert took < 10


def test_a_watcher_that_arrives_mid_job_sees_what_was_already_reported():
    """Found by walking the window: a job's events were one queue, and
    each watcher *took* from it. The strip on a page drawn mid-job
    attached after the item had been named and showed nothing; two
    pages watching at once would have split the events between them.
    Every watcher must see every event, from the start."""
    jobs = Jobs()
    named = threading.Event()
    holding = threading.Event()

    def work(events: EventSink) -> None:
        events.emit(ItemStarted(operation="add", item="first"))
        named.set()
        holding.wait(20)
        events.emit(ItemStarted(operation="add", item="second"))

    job = jobs.start("add", work)
    assert named.wait(10)
    early: list[str] = []
    early_reader = threading.Thread(
        target=lambda: early.extend(
            item.item for item in jobs.stream(job) if isinstance(item, ItemStarted)
        )
    )
    early_reader.start()
    time.sleep(0.5)
    late = threading.Thread(target=holding.set)
    late.start()
    seen_late = [
        item.item for item in jobs.stream(job) if isinstance(item, ItemStarted)
    ]
    early_reader.join(10)

    assert early == ["first", "second"]
    assert seen_late == ["first", "second"]


def test_the_script_shows_the_item_and_the_clock_without_wording_either():
    code = code_of("progress.js")

    assert '"current"' in code
    assert '"elapsed"' in code
    # No unit is spelled in the script: the seconds arrive as words.
    assert not re.search(r"[\"'](s|sec|seconds|m)[\"']", code)


def test_a_sync_line_says_what_happened_not_the_verdict_name():
    """Brian, 2026-10-12: a corpus sync read "= c.md - keep"."""
    for operation in ("corpus-sync", "context-sync"):
        message = as_message(
            ItemFinished(
                operation=operation,
                item="c.md",
                outcome=Outcome.UNCHANGED,
                refusal=Quoted("keep"),
            )
        )
        assert message is not None
        assert message["detail"] == "unchanged", operation


def test_the_outcome_line_does_not_repeat_its_name():
    """It read "= c.md - c.md: unchanged"; the name is first already."""
    action = Action(address="c.md", verdict="keep", declaration=None, existing=None)
    shown = shown_corpus_sync(
        CorpusSync(actions=(action,), counts={"keep": 1}, deferred=(), edited=())
    )

    assert shown.items[0].detail == "unchanged"
    assert shown.headline == "1 document unchanged"


def test_the_live_lines_give_way_to_an_outcome_that_lists_its_items():
    """The outcome is the record and the live lines were progress, so a
    finished sync listed every document twice. Only item lines go: a
    warning raised while the job ran is not repeated by the outcome."""
    code = code_of("progress.js")
    finish = re.search(r"function finish\(\) \{(.*?)\n    \}\n", code, re.S)

    assert finish, code
    assert re.search(
        r'if \(outcome\.querySelector\("\.items"\)\) \{\s*'
        r'lines\.querySelectorAll\("li\[data-item\]"\)',
        finish.group(1),
    )
    assert 'if (message.kind === "item") { item.dataset.item = "yes"; }' in code
    assert "lines.remove()" not in code


# ---------------------------------------------------------------------------
# Long, or elsewhere: the strip on every page
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("route", ["/", "/corpus", "/activity", "/add"])
def test_a_page_drawn_while_a_job_runs_carries_it_in_the_strip(
    app: FastAPI, client: TestClient, route: str
):
    holding, job_id = held(app)
    try:
        page = client.get(route).text
    finally:
        holding.set()

    assert f'data-job="{job_id}"' in strip_of(page)


def test_the_script_watches_every_panel_not_only_the_first():
    """The job's own page and the strip both draw a panel for it."""
    assert "querySelectorAll" in code_of("progress.js")


def test_an_idle_strip_says_where_the_corpus_stands(client: TestClient):
    strip = strip_of(client.get("/").text)

    assert "data-job" not in strip
    assert "0 of 3 collections searchable" in strip


def test_an_idle_strip_says_the_commit_what_waits_and_the_last_change(
    corpus: Path, client: TestClient
):
    """Plan 11b's four: the corpus's commit, what is searchable, what needs
    indexing and the last change, which is read from the corpus history
    so that it survives a restart and covers the command line too."""
    source = corpus / "a.md"
    source.write_text("# A\n\nSome words.\n", encoding="utf-8")
    assert CliRunner().invoke(main, ["corpus", "add", "-n", str(source)]).exit_code == 0
    head = Repository(corpus / "corpus").head()
    assert head is not None

    strip = BeautifulSoup(strip_of(client.get("/").text), "html.parser")
    text = " ".join(strip.get_text(" ").split())

    assert words.corpus_at(head[:7]) in text
    assert words.documents_waiting(1) in text
    assert "1 added" in text and "notes" in text


def test_the_strip_counts_what_was_added_since_the_last_index(
    corpus: Path, client: TestClient
):
    """A collection with an index waits for what was added since, not
    for every document it holds - and an index that holds everything
    leaves nothing waiting."""
    for name in ("a", "b"):
        (corpus / f"{name}.md").write_text(f"# {name}\n\nWords.\n", encoding="utf-8")
    adding = ["corpus", "add", "-n", str(corpus / "a.md")]
    assert CliRunner().invoke(main, adding).exit_code == 0
    indexing = ["corpus", "index", "--collection", "notes"]
    assert CliRunner().invoke(main, indexing).exit_code == 0
    current = " ".join(strip_of(client.get("/").text).split())

    adding = ["corpus", "add", "-n", str(corpus / "b.md")]
    assert CliRunner().invoke(main, adding).exit_code == 0
    behind = " ".join(strip_of(client.get("/").text).split())

    assert "need" not in current
    assert words.documents_waiting(1) in behind


def test_how_long_ago_is_said_in_the_largest_whole_unit():
    assert words.time_ago(-5) == "just now"
    assert words.time_ago(59) == "just now"
    assert words.time_ago(60) == "1 minute ago"
    assert words.time_ago(3599) == "59 minutes ago"
    assert words.time_ago(7200) == "2 hours ago"
    assert words.time_ago(3 * 86400 + 5) == "3 days ago"


def test_a_change_kennis_did_not_record_is_quoted_whole():
    assert words.last_change(None, None, "tidy up by hand", 120) == (
        "Last change: tidy up by hand, 2 minutes ago"
    )


def test_an_idle_strip_links_the_last_job(app: FastAPI, client: TestClient):
    holding, job_id = held(app, "index")
    holding.set()
    assert app.state.jobs.get(job_id).done.wait(10)

    strip = strip_of(client.get("/").text)

    assert f'href="/job/{job_id}"' in strip
    assert words.JOB_KINDS["index"] in strip


# ---------------------------------------------------------------------------
# Activity
# ---------------------------------------------------------------------------


def test_activity_lists_what_ran_newest_first(app: FastAPI, client: TestClient):
    first, first_id = held(app, "index")
    first.set()
    assert app.state.jobs.get(first_id).done.wait(10)
    second, second_id = held(app, "sync")
    try:
        page = client.get("/activity").text
    finally:
        second.set()

    assert page.index(f'href="/job/{second_id}"') < page.index(
        f'href="/job/{first_id}"'
    )
    assert words.JOB_KINDS["sync"] in page
    assert words.JOB_KINDS["index"] in page
    assert f"<h1>{words.ACTIVITY_HEADING}</h1>" in page


def test_activity_with_nothing_run_says_so(client: TestClient):
    assert words.NOTHING_RUN in client.get("/activity").text


def test_the_pane_names_activity_as_its_page_does(client: TestClient):
    pane = client.get("/").text
    pane = pane[pane.index('<nav class="pane"') : pane.index("</nav>")]

    assert re.search(
        r'<a class="node" href="/activity">.*?' + re.escape(words.ACTIVITY_HEADING),
        pane,
        re.DOTALL,
    )


# ---------------------------------------------------------------------------
# #412: a POST without a script answers a page
# ---------------------------------------------------------------------------


def test_a_job_started_without_htmx_goes_to_its_page(client: TestClient):
    """303 so the browser follows with a GET, and a reload does not
    start the job a second time."""
    started = client.post("/index", data={"collection": "notes"})

    assert started.status_code == 303
    location = started.headers["location"]
    assert re.fullmatch(r"/job/[\w-]+", location)
    page = client.get(location).text
    assert 'class="shell"' in page
    assert f'data-job="{location.rsplit("/", 1)[1]}"' in page


def test_with_htmx_a_started_job_is_still_a_fragment(client: TestClient):
    started = client.post("/index", data={"collection": "notes"}, headers=HTMX)

    assert started.status_code == 200
    assert 'class="shell"' not in started.text
    assert "data-job" in started.text


def test_a_refusal_without_htmx_is_a_page(client: TestClient):
    refused = client.post("/add", data={"identifiers": "", "collection": "notes"})

    assert 'class="shell"' in refused.text
    assert words.NOTHING_TO_ADD in refused.text


def test_a_note_written_without_htmx_answers_the_note_page(client: TestClient):
    written = client.post(
        "/remember", data={"text": "A note written without a script."}
    )

    assert written.status_code == 200
    assert 'class="shell"' in written.text
    assert 'id="outcome"' in written.text


def test_clearing_recent_searches_without_htmx_returns_to_search(client: TestClient):
    cleared = client.post("/history/clear")

    assert cleared.status_code == 303
    assert cleared.headers["location"] == "/"
