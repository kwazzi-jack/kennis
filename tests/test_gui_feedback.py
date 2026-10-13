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
from kennis.engine.corpus.add import AddOutcome, AddReport
from kennis.engine.corpus.sync import CorpusSync
from kennis.engine.events import EventSink, ItemFinished, ItemStarted, Outcome
from kennis.engine.history.repository import Repository
from kennis.engine.pack.resolve import Action
from kennis.engine.rag.embedding import FETCH_MODEL
from kennis.engine.refusals import Quoted
from kennis.gui import words
from kennis.gui.app import build_app
from kennis.gui.jobs import Elapsed, Jobs
from kennis.gui.pages import shown_add, shown_corpus_sync
from kennis.gui.responses import TEMPLATES
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


def test_two_jobs_started_within_one_clock_tick_are_listed_newest_first():
    """Windows' monotonic clock ticks every 16 ms or so, so two jobs started
    together carry the same start time there; the tie is made by hand here
    so that it holds on every platform."""
    jobs = Jobs()
    first = jobs.start("index", lambda events: None)
    assert first.done.wait(10)
    second = jobs.start("sync", lambda events: None)
    assert second.done.wait(10)
    second.started_at = first.started_at

    assert [job.id for job in jobs.recent()] == [second.id, first.id]


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


# ---------------------------------------------------------------------------
# After a job, the shell says what is true now (#457)
# ---------------------------------------------------------------------------


def a_waiting_note(corpus: Path) -> None:
    source = corpus / "sources" / "rivers.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("# rivers\n\nRivers carry sediment.\n", encoding="utf-8")
    assert CliRunner().invoke(main, ["corpus", "add", "-n", str(source)]).exit_code == 0


def indexed_through_the_window(client: TestClient) -> str:
    started = client.post("/index", data={"collection": ""}, headers=HTMX)
    job = BeautifulSoup(started.text, "html.parser").find(attrs={"data-job": True})
    assert job is not None, started.text
    with client.stream("GET", f"/job/{job['data-job']}/events") as answer:
        for _ in answer.iter_lines():
            pass
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        outcome = client.get(f"/job/{job['data-job']}/outcome", headers=HTMX).text
        if words.STILL_RUNNING not in outcome:
            return outcome
    raise AssertionError("the job never finished")


def test_a_finished_job_redraws_the_strip_and_the_pane(
    corpus: Path, client: TestClient
):
    """An index finished with "Indexed 14 documents" while the status
    under it still said "14 documents need indexing" and the pane's dot
    was amber. The outcome asks for each again, where the page has it."""
    a_waiting_note(corpus)
    before = client.get("/").text
    assert words.documents_waiting(1) in before

    outcome = BeautifulSoup(indexed_through_the_window(client), "html.parser")
    hooks = {
        str(hook["data-redraw-id"]): str(hook["data-redraw-route"])
        for hook in outcome.find_all(attrs={"data-redraw-id": True})
    }

    expected = {"strip-status", "pane-documents"} | {
        f"pane-row-{name}" for name in ("literature", "docs", "notes")
    }
    assert expected <= set(hooks), hooks
    page = BeautifulSoup(before, "html.parser")
    for element, route in hooks.items():
        assert page.find(id=element) is not None, f"the page has no #{element}"
        drawn = BeautifulSoup(client.get(route, headers=HTMX).text, "html.parser")
        top = drawn.find(True)
        assert top is not None and top.get("id") == element, route
    status = client.get(hooks["strip-status"], headers=HTMX).text
    assert words.documents_waiting(1) not in status
    row = BeautifulSoup(
        client.get(hooks["pane-row-notes"], headers=HTMX).text, "html.parser"
    )
    assert row.find(class_="state-current") is not None


def test_a_redrawn_row_is_the_summary_so_an_open_folder_stays_open(client: TestClient):
    page = BeautifulSoup(client.get("/").text, "html.parser")
    row = page.find(id="pane-row-notes")

    assert row is not None and row.name == "summary"


def test_the_status_line_is_drawn_while_a_job_runs(app: FastAPI, client: TestClient):
    """A job that finishes on this page needs a status line to redraw."""
    holding, _ = held(app)
    try:
        page = client.get("/").text
    finally:
        holding.set()

    assert BeautifulSoup(page, "html.parser").find(id="strip-status") is not None


def test_a_note_written_from_the_dialog_redraws_them_too(
    corpus: Path, client: TestClient
):
    """A note is not a job and has no stream; its answer carries the
    fresh elements for htmx to swap in by id."""
    answer = client.post(
        "/remember",
        data={"text": "Rivers carry sediment.", "target": "notes"},
        headers=HTMX,
    )
    swapped = BeautifulSoup(answer.text, "html.parser")

    for element in ("strip-status", "pane-documents", "pane-row-notes"):
        found = swapped.find(id=element)
        assert found is not None, element
        assert found.get("hx-swap-oob") == "true", element
    count = swapped.find(id="pane-documents")
    assert count is not None and "1" in count.get_text()


# ---------------------------------------------------------------------------
# A job that dies of something that is not a KennisError
# ---------------------------------------------------------------------------


def test_a_job_that_crashes_is_reported_as_failed(app: FastAPI, client: TestClient):
    """A full disk is an `OSError`, not a `KennisError`. Uncaught, the
    thread died, the traceback went to the terminal, and the page said the
    operation finished without reporting anything."""

    def fills_the_disk(events: EventSink) -> object:
        raise OSError(28, "No space left on device")

    job = app.state.jobs.start("add", fills_the_disk)
    assert job.done.wait(5)

    outcome = client.get(f"/job/{job.id}/outcome", headers=HTMX).text
    activity = BeautifulSoup(client.get("/activity").text, "html.parser")

    assert "No space left on device" in outcome
    assert words.NOTHING_TO_SHOW not in outcome
    assert words.JOB_FAILED in activity.get_text()
    assert words.JOB_FINISHED not in activity.get_text()


def test_what_needs_indexing_has_a_button_beside_it(corpus: Path, client: TestClient):
    """ "2 documents need indexing" was a sentence, and the reader had to
    find the Index dialog themselves. One collection behind is indexed
    alone."""
    run = CliRunner()
    for name in ("first", "second"):
        source = corpus / f"{name}.md"
        source.write_text(f"# {name}\n\nText.\n", encoding="utf-8")
        assert run.invoke(main, ["corpus", "add", "-n", str(source)]).exit_code == 0
        if name == "first":
            assert run.invoke(main, ["corpus", "index"]).exit_code == 0

    strip = BeautifulSoup(client.get("/").text, "html.parser").find(id="strip-status")
    form = strip.find("form", class_="index-now")

    assert form is not None, strip
    assert form["action"] == form["hx-post"] == "/index"
    assert form.find("input", attrs={"name": "collection"})["value"] == "notes"
    assert words.index_now(["notes"]) in form.get_text()


def test_nothing_behind_offers_no_index_button(client: TestClient):
    strip = BeautifulSoup(client.get("/").text, "html.parser").find(id="strip-status")

    assert strip.find("form") is None


def test_an_add_that_wrote_offers_to_index_what_it_wrote():
    """ "Not searchable until the index is rebuilt" was a sentence with
    nothing to press beside it."""
    added = shown_add(AddReport([AddOutcome("x.md", Outcome.ADDED)], 0.1))
    refused = shown_add(AddReport([AddOutcome("x.md", Outcome.FAILED)], 0.1))
    drawn = TEMPLATES.env.get_template("job-outcome.html").render(shown=added)

    assert added.index_after and not refused.index_after
    assert 'action="/index"' in drawn
    assert words.INDEX_NOW in drawn


def test_a_long_outcome_folds_what_needs_nothing_and_shows_what_does():
    """A 4,000-file add listed every file, and the one refusal among them
    was somewhere in the list."""
    report = AddReport(
        [AddOutcome(f"n{at}.md", Outcome.ADDED) for at in range(30)]
        + [AddOutcome("broken.md", Outcome.FAILED)],
        0.1,
    )
    page = BeautifulSoup(
        TEMPLATES.env.get_template("job-outcome.html").render(shown=shown_add(report)),
        "html.parser",
    )

    fold = page.find("details", class_="all-items")
    assert fold is not None
    assert "open" not in fold.attrs
    assert words.every_item(30) in fold.summary.get_text()
    shown_first = page.find("ul", class_="items")
    assert fold not in shown_first.parents
    assert "broken.md" in shown_first.get_text()


def test_a_short_outcome_is_not_folded():
    report = AddReport([AddOutcome("one.md", Outcome.ADDED)], 0.1)
    drawn = TEMPLATES.env.get_template("job-outcome.html").render(
        shown=shown_add(report)
    )

    assert "all-items" not in drawn
    assert "one.md" in drawn


def test_an_empty_corpus_s_home_says_what_kennis_is_and_where_to_start(
    client: TestClient,
):
    """A fresh install showed an empty centre."""
    page = BeautifulSoup(client.get("/").text, "html.parser")
    welcome = page.find("section", class_="welcome")

    assert welcome is not None
    assert words.WELCOME_HEADING in welcome.get_text()
    offered = [link["href"] for link in welcome.find_all("a")]
    assert offered == [href for href, _, _ in words.WELCOME_ACTIONS]


def test_a_corpus_with_documents_is_not_welcomed(corpus: Path, client: TestClient):
    source = corpus / "held.md"
    source.write_text("# Held\n\nText.\n", encoding="utf-8")
    assert CliRunner().invoke(main, ["corpus", "add", "-n", str(source)]).exit_code == 0

    assert 'class="welcome"' not in client.get("/").text


def test_a_correctable_add_refusal_is_answered_inside_the_form(client: TestClient):
    answer = client.post(
        "/add",
        data={"kind": "paper", "identifiers": "2401.01234"},
        headers={**HTMX, "Origin": "http://testserver"},
    )

    assert answer.headers["HX-Retarget"] == "#add-problem"
    assert answer.headers["X-Kennis-Refused"] == "true"
    assert words.CHOOSE_A_COLLECTION in answer.text


def test_the_add_form_has_somewhere_to_answer_a_refusal(client: TestClient):
    form = BeautifulSoup(client.get("/add", headers=HTMX).text, "html.parser")

    assert form.find(id="add-problem").get("role") == "alert"


def test_a_kennis_summary_of_one_is_read_in_the_singular():
    """The strip said "note in notes (1 documents)"."""
    said = words.last_change("note", "notes", "1 documents, 3 chunks", 5)

    assert "(1 document, 3 chunks)" in said
