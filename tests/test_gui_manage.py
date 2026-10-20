"""Managing the corpus from the graphical interface.

Unit 9f. Four operations - add, index, both syncs, install a pack -
each started by a POST that answers at once, streamed while it runs,
and reported when it ends.

**The property worth stating.** An add that is refused offers a repair
the reader can submit, built from 9e's typed refusal rather than from
the sentence about it. That is why 9e was placed immediately before
this unit rather than at the start of the milestone.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from click.testing import CliRunner
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response

from kennis.cli.__main__ import main
from kennis.cli.display import sync_marker
from kennis.cli.sink import marker_for
from kennis.context import existing_corpus
from kennis.engine.corpus.collection import Collection
from kennis.engine.errors import InputError
from kennis.engine.events import EventSink, Outcome
from kennis.engine.history.repository import Repository
from kennis.engine.locking import corpus_lock
from kennis.engine.pack.store import PackInstall
from kennis.gui import words
from kennis.gui.app import build_app
from kennis.gui.pages import shown_install
from kennis.gui.pane import Pane
from kennis.gui.responses import TEMPLATES
from kennis.gui.stream import MARKERS, SYNC_MARKERS
from kennis.logs import log_path, start_logging, stop_logging
from kennis.render.words import waiting_for

TOKEN = "a-test-token"


def posted(client: TestClient, path: str, **kwargs: object) -> Response:
    """A POST as the window's htmx form sends it.

    Without the header a POST is a plain form's, and since #412 that
    answers a page or a redirect - not the fragment these tests read.
    """
    return client.post(path, headers={"HX-Request": "true"}, **kwargs)


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    return build_app(TOKEN)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    opened = TestClient(app, follow_redirects=False)
    assert opened.get("/", params={"token": TOKEN}).status_code == 200
    return opened


def a_source(tmp_path: Path, name: str, body: str = "Some words.") -> Path:
    path = tmp_path / "sources" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {name}\n\n{body}\n", encoding="utf-8")
    return path


def job_of(html: str) -> str:
    """The job identifier the panel was drawn with."""
    marker = 'data-job="'
    start = html.index(marker) + len(marker)
    return html[start : html.index('"', start)]


def finished(client: TestClient, job_id: str, seconds: float = 20.0) -> str:
    """Drain this job's stream, then ask what it came to.

    Draining rather than sleeping: the stream ends when the operation
    does, so reading it to the end *is* the wait, and a test that slept
    would be slow when the work is fast and flaky when it is not.
    """
    with client.stream("GET", f"/job/{job_id}/events") as answer:
        assert answer.status_code == 200
        for _ in answer.iter_lines():
            pass
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        outcome = client.get(f"/job/{job_id}/outcome")
        if "still running" not in outcome.text:
            return outcome.text
    raise AssertionError("the job never finished")


def messages(client: TestClient, job_id: str) -> list[dict[str, object]]:
    """Every message the stream carried, decoded."""
    seen: list[dict[str, object]] = []
    with client.stream("GET", f"/job/{job_id}/events") as answer:
        for line in answer.iter_lines():
            if line.startswith("data: "):
                seen.append(json.loads(line[len("data: ") :]))
    return seen


# ---------------------------------------------------------------------------
# Adding
# ---------------------------------------------------------------------------


def test_an_add_writes_the_document_and_reports_it(client: TestClient, tmp_path: Path):
    started = posted(
        client,
        "/add",
        data={
            "identifiers": str(a_source(tmp_path, "trees.md")),
            "collection": "notes",
        },
    )

    assert started.status_code == 200
    shown = finished(client, job_of(started.text))

    assert "Added 1 document" in shown
    assert (
        Collection(root=existing_corpus().corpus_root, name="notes")
        .contents()
        .documents
    )


def test_an_add_commits_what_it_wrote(client: TestClient, tmp_path: Path):
    """The same sequence the command line uses, and the reason it was
    extracted: a front end that wrote without committing would leave a
    corpus with no history to read."""
    corpus_root = existing_corpus().corpus_root
    before = Repository(corpus_root).head()

    started = posted(
        client,
        "/add",
        data={
            "identifiers": str(a_source(tmp_path, "trees.md")),
            "collection": "notes",
        },
    )
    finished(client, job_of(started.text))

    assert Repository(corpus_root).head() != before
    assert Repository(corpus_root).is_clean()


def test_an_add_with_nothing_named_is_refused_before_a_job_starts(client: TestClient):
    """A job that had nothing to do would still occupy the one slot and
    would still have to be watched to find that out."""
    answer = posted(
        client, "/add", data={"identifiers": "  \n\n", "collection": "notes"}
    )

    assert "Nothing to add" in answer.text
    assert "data-job" not in answer.text


def test_a_refused_add_offers_a_repair_that_can_be_submitted(
    client: TestClient, tmp_path: Path
):
    """The property this unit exists for. A markdown file has no
    bibliographic identity, so literature refuses it - and the answer
    is a form with the path already in it, not a sentence telling the
    reader to type a command elsewhere."""
    source = a_source(tmp_path, "paper.md")

    started = posted(
        client, "/add", data={"identifiers": str(source), "collection": "literature"}
    )
    shown = finished(client, job_of(started.text))

    assert "no bibliographic identity" in shown
    assert 'class="repair"' in shown
    assert f'value="{source}"' in shown
    assert 'value="notes"' in shown


def test_the_offered_repair_actually_repairs(client: TestClient, tmp_path: Path):
    """Submitting the form the refusal produced must add the document.
    A repair that does not repair is worse than no repair.

    **The form's own route and fields, read from the page.** This test
    used to post its own fields to `/add`, and passed for three units
    while the form itself posted to `/manage/add`, which 11a removed
    (11e)."""
    source = a_source(tmp_path, "paper.md")
    refused = posted(
        client, "/add", data={"identifiers": str(source), "collection": "literature"}
    )
    page = finished(client, job_of(refused.text))
    form = re.search(
        r'<form class="repair"[^>]*hx-post="([^"]+)"[^>]*>(.*?)</form>', page, re.S
    )
    assert form, page
    sent = dict(
        re.findall(
            r'<input type="hidden" name="([^"]+)" value="([^"]*)">', form.group(2)
        )
    )
    assert sent["collection"] == "notes"

    repaired = posted(client, form.group(1), data=sent)
    shown = finished(client, job_of(repaired.text))

    assert "Added 1 document" in shown
    assert (
        Collection(root=existing_corpus().corpus_root, name="notes")
        .contents()
        .documents
    )


def test_a_repair_replaces_the_command_rather_than_joining_it(
    client: TestClient, tmp_path: Path
):
    """A terminal command beside a button that does the same thing asks
    the reader to leave the interface to do what the interface does."""
    source = a_source(tmp_path, "paper.md")

    started = posted(
        client, "/add", data={"identifiers": str(source), "collection": "literature"}
    )
    shown = finished(client, job_of(started.text))

    assert 'class="repair"' in shown
    assert "kennis corpus add -n" not in shown


def test_an_added_document_is_told_it_is_not_searchable_yet(
    client: TestClient, tmp_path: Path
):
    """Said as a sentence pointing at the control above, rather than as
    `kennis corpus index`, for the same reason."""
    started = posted(
        client,
        "/add",
        data={
            "identifiers": str(a_source(tmp_path, "trees.md")),
            "collection": "notes",
        },
    )
    shown = finished(client, job_of(started.text))

    # Against the constant, not a literal: a reword should not
    # break a test whose point is that the note is there.
    assert words.NOT_SEARCHABLE_YET in shown
    assert "kennis corpus index" not in shown


def test_an_ambiguous_refusal_offers_every_candidate_and_chooses_none(
    client: TestClient, tmp_path: Path
):
    """Choosing for the reader would be deciding which paper this is."""
    from kennis.engine.refusals import AmbiguousIdentity
    from kennis.gui.repairs import repairs_for

    repairs = repairs_for(
        AmbiguousIdentity(
            named="/tmp/paper.pdf", kind="arxiv", values=("2409.19750", "1101.1764")
        )
    )

    choosing = [repair for repair in repairs if repair.choices]
    assert len(choosing) == 1
    assert choosing[0].choices == ("2409.19750", "1101.1764")


def test_an_unknown_collection_is_named_back(client: TestClient, tmp_path: Path):
    answer = posted(
        client,
        "/add",
        data={
            "identifiers": str(a_source(tmp_path, "a.md")),
            "collection": "elsewhere",
        },
    )

    assert "elsewhere" in answer.text
    assert "data-job" not in answer.text


# ---------------------------------------------------------------------------
# The stream
# ---------------------------------------------------------------------------


def test_the_stream_carries_each_item_and_then_closes(
    client: TestClient, tmp_path: Path
):
    started = posted(
        client,
        "/add",
        data={
            "identifiers": "\n".join(
                str(a_source(tmp_path, name)) for name in ("one.md", "two.md")
            ),
            "collection": "notes",
        },
    )

    seen = messages(client, job_of(started.text))

    items = [message for message in seen if message["kind"] == "item"]
    assert len(items) == 2
    assert seen[-1]["kind"] == "closed"


def test_the_stream_ends_even_when_the_operation_fails(
    app: FastAPI, client: TestClient
):
    """A stream that simply stopped would leave a page showing a
    spinner, with no way to tell a finished job from a dropped
    connection."""

    def fails(events: EventSink) -> object:
        raise InputError("this operation could not run")

    job = app.state.jobs.start("add", fails)
    seen = messages(client, job.id)

    assert seen[-1]["kind"] == "closed"
    assert job.error is not None


def test_a_corpus_held_elsewhere_is_waited_for_not_refused(
    app: FastAPI, client: TestClient, tmp_path: Path
):
    """In the service a job waits for the corpus rather than being told it
    is busy (14b): a terminal or a build's commit that holds it was there
    first. Checked between the two events it orders - the job must not
    have finished while the corpus is held, and must finish once it is not.
    """
    corpus_root = existing_corpus().corpus_root
    with corpus_lock(corpus_root):
        started = posted(
            client,
            "/add",
            data={
                "identifiers": str(a_source(tmp_path, "trees.md")),
                "collection": "notes",
            },
        )
        job = app.state.jobs.get(job_of(started.text))
        assert job is not None
        assert not job.done.wait(0.5), "the job ran beside the corpus's holder"
    shown = finished(client, job.id)

    assert job.error is None
    assert "busy" not in shown


def test_an_operation_started_from_the_window_reaches_the_log(
    client: TestClient, tmp_path: Path
):
    """Section 14: the log records what the report omits. An operation
    whose only subscriber was a browser recorded nothing at all, which
    is not less than the report - it is none of it. Concern #326."""
    start_logging()
    try:
        started = posted(
            client,
            "/add",
            data={
                "identifiers": str(a_source(tmp_path, "trees.md")),
                "collection": "notes",
            },
        )
        finished(client, job_of(started.text))
        written = log_path().read_text(encoding="utf-8")
    finally:
        stop_logging()

    assert "add added" in written
    assert "trees.md" in written


def test_the_markers_agree_with_the_command_lines(client: TestClient):
    """`gui/` may not import `cli/`, so the two front ends each hold
    their own marker table. They must still agree: the same event shown
    as `+` in a terminal and `~` in a window would be one corpus
    described two ways."""
    for outcome in Outcome:
        assert MARKERS[outcome] == marker_for(outcome)
    for verdict, marker in SYNC_MARKERS.items():
        assert marker == sync_marker(verdict)


# ---------------------------------------------------------------------------
# One at a time in each lane, and the rest wait their turn (14b)
# ---------------------------------------------------------------------------


def test_a_second_operation_waits_its_turn_and_says_for_what(
    app: FastAPI, client: TestClient, tmp_path: Path
):
    """It was refused while the corpus lock refused it anyway; in the
    service it queues, and says which task it is behind.

    The first job is held open by an event this test releases, rather
    than by a corpus lock: a lock makes the operation *fail*, which
    finishes the job, and a job that has finished is no longer the one
    in the way.
    """
    holding = threading.Event()
    running = app.state.jobs.start("add", lambda events: holding.wait(10))
    try:
        second = posted(
            client,
            "/add",
            data={
                "identifiers": str(a_source(tmp_path, "two.md")),
                "collection": "notes",
            },
        )
        waiting = app.state.jobs.get(job_of(second.text))

        assert job_of(second.text) != running.id
        assert waiting is not None and waiting.state == "queued"
        assert waiting_for("add", 1) in second.text
        assert 'data-state="queued"' in second.text
    finally:
        holding.set()
    finished(client, job_of(second.text))
    assert waiting.result is not None


def test_a_job_that_has_finished_is_no_longer_in_the_way(
    app: FastAPI, client: TestClient, tmp_path: Path
):
    """One at a time, not one ever."""
    holding = threading.Event()
    earlier = app.state.jobs.start("add", lambda events: holding.wait(10))
    holding.set()
    assert earlier.done.wait(10)

    started = posted(
        client,
        "/add",
        data={
            "identifiers": str(a_source(tmp_path, "one.md")),
            "collection": "notes",
        },
    )

    assert 'data-state="queued"' not in started.text
    finished(client, job_of(started.text))


# ---------------------------------------------------------------------------
# Indexing, syncing, installing
# ---------------------------------------------------------------------------


def test_indexing_reports_what_it_built(client: TestClient, tmp_path: Path):
    added = posted(
        client,
        "/add",
        data={
            "identifiers": str(a_source(tmp_path, "trees.md")),
            "collection": "notes",
        },
    )
    finished(client, job_of(added.text))

    started = posted(client, "/index", data={"collection": ""})
    shown = finished(client, job_of(started.text))

    assert "Indexed 1 document" in shown
    assert "notes" in shown


def test_indexing_an_empty_corpus_says_there_is_nothing_to_do(client: TestClient):
    started = posted(client, "/index", data={"collection": ""})
    shown = finished(client, job_of(started.text))

    assert "Nothing to index" in shown


def test_a_corpus_sync_with_no_packs_reports_nothing_and_does_not_fail(
    client: TestClient,
):
    """And says so quietly. Nothing happened, so the line must not be
    the colour of something having happened."""
    started = posted(client, "/sync", data={})
    shown = finished(client, job_of(started.text))

    assert "data-job" not in shown
    assert "role-muted" in shown
    assert "role-added" not in shown


def test_installing_a_pack_that_is_not_a_file_is_refused_before_a_job_starts(
    client: TestClient,
):
    answer = posted(client, "/pack", data={"path": "/nowhere/at/all.ken.yml"})

    assert "data-job" not in answer.text
    assert "/nowhere/at/all.ken.yml" in answer.text


def test_the_pack_field_browses_the_computer_kennis_runs_on(client: TestClient):
    """A pack is read from its path, and its sources from beside it, so the
    browser's own picker - which uploads a copy - cannot choose one
    (Brian, 2026-10-16: "the ability to look for a file")."""
    form = BeautifulSoup(
        client.get("/pack", headers={"HX-Request": "true"}).text, "html.parser"
    ).find("form")
    browse = form.find(
        attrs={"hx-get": lambda value: bool(value) and value.startswith("/browse")}
    )
    assert browse is not None
    address = str(browse["hx-get"])

    assert "target=path" in address
    assert "folders" not in address, "a pack is a file"
    slot = form.find(id=str(browse["hx-target"]).removeprefix("#"))
    assert slot is not None and "chooser" in slot["class"]
    assert form.find("input", attrs={"name": "path"}) is not None
    assert client.get(address, headers={"HX-Request": "true"}).status_code == 200


def test_the_sync_dialog_syncs_the_corpus_and_no_project(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """A project's context is read from the store, so there is nothing of
    a pack for the window to copy into one (14g); its sync stays on the
    command line, run in the project concerned."""
    monkeypatch.setattr("kennis.gui.pane.present_projects", lambda: ("kennis",))
    dialog = client.get("/sync", headers={"HX-Request": "true"}).text

    assert 'hx-post="/sync"' in dialog
    assert "/context-sync" not in dialog
    foot = BeautifulSoup(dialog, "html.parser").select_one(".form-foot")
    assert foot is not None
    submits = foot.select("button[type=submit]")
    assert "primary" in (submits[0].get("class") or [])


def test_the_management_routes_need_the_token(tmp_path: Path):
    """The guard is middleware, so a route added in a later unit cannot
    forget it - which is exactly what this checks for the routes added
    in this one."""
    stranger = TestClient(build_app(TOKEN), follow_redirects=False)

    assert posted(stranger, "/add", data={"identifiers": "x"}).status_code == 401
    assert stranger.get("/add").status_code == 401
    assert stranger.get("/tree/notes").status_code == 401
    assert stranger.get("/job/whatever/events").status_code == 401


def test_the_index_dialog_marks_and_chooses_what_needs_indexing(
    client: TestClient, tmp_path: Path
):
    """It offered every collection alike, so the reader had to find out
    elsewhere which one their new documents were in."""
    for name in ("one.md", "two.md"):
        result = CliRunner().invoke(
            main, ["corpus", "add", "-n", str(a_source(tmp_path, name))]
        )
        assert result.exit_code == 0

    dialog = BeautifulSoup(
        client.get("/index", headers={"HX-Request": "true"}).text, "html.parser"
    )

    checked = dialog.select_one('input[name="collection"]:checked')
    assert checked is not None and checked["value"] == "notes"
    marked = {
        str(label.select_one("input")["value"]): label.select_one(".waiting")
        for label in dialog.select(".segmented label")
    }
    assert marked["notes"] is not None
    assert marked["notes"].get_text() == words.index_waiting(2)
    assert marked["literature"] is None and marked[""] is None


def test_an_installed_pack_offers_the_sync_as_a_button_not_a_command(
    client: TestClient,
):
    """The outcome printed `kennis corpus sync` while the bar has a Sync
    button that does exactly that."""
    shown = shown_install(
        PackInstall(
            pack_id="boepie", outcome="Installed", files=2, literature=1, docs=0
        )
    )
    drawn = TEMPLATES.get_template("job-outcome.html").render(
        shown=shown, pane_now=lambda request: Pane(collections=(), projects=())
    )

    assert shown.next_steps == ()
    page = BeautifulSoup(drawn, "html.parser")
    assert page.select_one('form[hx-post="/sync"] button') is not None
    assert "kennis corpus sync" not in drawn


def test_a_saved_note_waiting_for_its_index_offers_index_now(client: TestClient):
    """It said to go and type `kennis corpus index` elsewhere."""
    answer = client.post(
        "/remember",
        data={"text": "Antenna gains drift.", "title": "Drift", "target": "notes"},
        headers={"HX-Request": "true"},
    )

    page = BeautifulSoup(answer.text, "html.parser")
    button = page.select_one('button[formaction="/index"]')
    assert button is not None and button["value"] == "notes"
    assert "kennis corpus index" not in answer.text
