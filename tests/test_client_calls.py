"""The client's side of a call: a read answered, a job followed (14c).

Against the service's application in this process, through the same
`connect` every command uses, which the autouse `service_in_this_process`
fixture binds to an in-process application for the test's corpus (#503).
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from click.testing import CliRunner

from in_process import InProcessServices
from kennis.cli.__main__ import main
from kennis.client import connection
from kennis.client.calls import JobDetached, call, watch
from kennis.context import existing_corpus
from kennis.engine.corpus.add import AddOptions, AddReport
from kennis.engine.corpus.collection import CollectionContents
from kennis.engine.errors import DocumentNotFound
from kennis.engine.events import Event, ItemFinished, ItemStarted, OperationFinished
from kennis.holdings import contents_of
from kennis.protocol.progress import Began, Queued
from kennis.service.jobs import CORPUS_LANE


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "corpus"
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(root))
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    return root


def a_source(tmp_path: Path, name: str) -> Path:
    path = tmp_path / "sources" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {name}\n\nAbout {name}.\n", encoding="utf-8")
    return path


class Recorded:
    """Every event a job reported, in order."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    def emit(self, event: Event) -> None:
        self.events.append(event)


def test_a_read_answers_as_its_declared_type(corpus: Path):
    answered = call(
        connection.connect(corpus),
        "contents",
        {"collection": "notes"},
        returns=CollectionContents,
    )

    assert answered.result == contents_of(existing_corpus(), "notes")
    assert isinstance(answered.result, CollectionContents)


def test_a_job_is_followed_to_its_end_and_its_events_reach_the_sink(
    corpus: Path, tmp_path: Path
):
    recorded = Recorded()

    answered = call(
        connection.connect(corpus),
        "add",
        {
            "destination": "notes",
            "identifiers": [str(a_source(tmp_path, "one.md"))],
            "options": AddOptions(),
        },
        returns=AddReport,
        events=recorded,
    )

    assert isinstance(answered.result, AddReport)
    assert [outcome.identifier for outcome in answered.result.outcomes] == [
        str(a_source(tmp_path, "one.md"))
    ]
    kinds = [type(event) for event in recorded.events]
    assert kinds[0] is ItemStarted
    assert ItemFinished in kinds
    assert kinds[-1] is OperationFinished
    assert answered.restored == []


def test_a_refusal_is_raised_as_the_error_it_was(corpus: Path):
    with pytest.raises(DocumentNotFound):
        call(
            connection.connect(corpus),
            "remove_document",
            {"collection": "notes", "handle": "absent"},
            returns=object,
        )


def test_a_job_behind_another_says_so_before_it_begins(
    corpus: Path, tmp_path: Path, service_in_this_process: InProcessServices
):
    told: list[Queued | Began] = []
    app = service_in_this_process.app(corpus)
    release = threading.Event()
    app.state.jobs.start("index", lambda events: release.wait(30), lane=CORPUS_LANE)
    threading.Timer(0.2, release.set).start()

    call(
        connection.connect(corpus),
        "add",
        {
            "destination": "notes",
            "identifiers": [str(a_source(tmp_path, "two.md"))],
            "options": AddOptions(),
        },
        returns=AddReport,
        events=Recorded(),
        on_waiting=told.append,
    )

    assert told == [Queued(ahead=1, behind="index"), Began()]


def test_an_interrupt_while_following_detaches_and_names_the_job(
    corpus: Path, tmp_path: Path
):
    """Ctrl-C stops the watching, never the work (Brian's default 3)."""

    class Interrupting:
        def emit(self, event: Event) -> None:
            raise KeyboardInterrupt

    with pytest.raises(JobDetached) as detached:
        call(
            connection.connect(corpus),
            "add",
            {
                "destination": "notes",
                "identifiers": [str(a_source(tmp_path, "three.md"))],
                "options": AddOptions(),
            },
            returns=AddReport,
            events=Interrupting(),
        )

    job = detached.value.job
    assert job in str(detached.value.resolution)
    followed = watch(
        connection.connect(corpus), job, returns=AddReport, events=Recorded()
    )
    assert isinstance(followed.result, AddReport)


def test_every_command_reaches_the_service_in_this_process(corpus: Path):
    """The harness's own guard: a connection is to this process's
    application, never to a started service."""
    assert connection.connect.__module__ != "kennis.client.connection"
    assert connection.connect(corpus).base_url.host == "testserver"
