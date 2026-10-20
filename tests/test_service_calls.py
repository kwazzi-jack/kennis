"""Every operation a client may call, through the service's API (14b).

The table in `service/calls.py` is the API. These tests are generated from
it, and `EXPECTED_OPERATIONS` is the third statement written by hand
(#373): an operation added to the table without a call here, or dropped
from it, fails a test.

A read is compared with the same function called directly: the API's
answer must be the direct answer's wire form. A write runs as a job, so a
second call would act twice; for a write the test asserts that the job's
result reads back as the operation's declared type, and the operations'
own tests say what they do.
"""

from __future__ import annotations

import json
import threading
import typing
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import pytest
from click.testing import CliRunner
from fastapi import FastAPI
from fastapi.testclient import TestClient
from filelock import FileLock

import kennis.finding
import kennis.holdings
import kennis.retrieval
from kennis.cli.__main__ import main
from kennis.context import Context, existing_corpus
from kennis.engine.context.bundle import find_bundle
from kennis.engine.corpus.add import AddOptions
from kennis.engine.corpus.collection import Collection
from kennis.engine.errors import KennisError, NothingToIndex
from kennis.engine.events import ItemFinished, ItemStarted
from kennis.engine.history.repository import Repository
from kennis.engine.pack.installed import list_installed
from kennis.engine.rag.search import ChunkRange
from kennis.operations import GroupBlock
from kennis.protocol.progress import Began, Queued
from kennis.protocol.wire import Json, dump, load, load_error, wire_name
from kennis.service.api import PREFIX
from kennis.service.app import build_service_app
from kennis.service.calls import OPERATIONS, Operation
from kennis.service.jobs import CORPUS_LANE, INDEX_LANE, context_lane
from pinned import pin

TOKEN = "a-test-token"
BEARER = {"Authorization": f"Bearer {TOKEN}"}

# Written by hand, from the plan: what a client of 14b can ask for.
EXPECTED_OPERATIONS = frozenset(
    {
        # Writes, each a job in a lane.
        "add",
        "add_in_groups",
        "back_up",
        "copy_document",
        "index",
        "install_pack",
        "make_version_current",
        "move_document",
        "remember",
        "remove_document",
        "remove_pack",
        "remove_version",
        "restore_document",
        "return_corpus",
        "sync_bundle",
        "sync_corpus",
        # Reads, answered on the request.
        "contents",
        "docs_versions",
        "document_marks",
        "found",
        "history",
        "holdings",
        "last_change",
        "pack_listing",
        "read_document",
        "read_passage",
        "return_preview",
        "revision",
        "search_scope",
        "status",
        "sweep",
        "tree",
        "version_pages",
    }
)


@dataclass(frozen=True, slots=True)
class Scene:
    """What a call's arguments are built from."""

    scratch: Path
    corpus: Path
    note: str
    first_commit: str


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Scene:
    scratch = pin(tmp_path, monkeypatch)
    runner = CliRunner()
    for arguments in (
        ["corpus", "init"],
        ["corpus", "add", "-n", str(scratch / "sources/calibration.md")],
        [
            "corpus",
            "add",
            "-d",
            "--project",
            "tool",
            "--version",
            "1.0",
            str(scratch / "sources/page.md"),
        ],
        ["corpus", "index"],
        ["pack", "update", str(scratch / "provider/provider.ken.yml")],
    ):
        answered = runner.invoke(main, arguments)
        assert answered.exit_code == 0, (arguments, answered.output)
    monkeypatch.chdir(scratch / "project")
    assert runner.invoke(main, ["context", "init"]).exit_code == 0
    corpus = scratch / "corpus"
    notes = Collection(root=corpus, name="notes")
    (note,) = notes.contents().documents
    history = Repository(corpus)
    return Scene(
        scratch=scratch,
        corpus=corpus,
        note=note.frontmatter.id,
        first_commit=history_root(history),
    )


def history_root(history: Repository) -> str:
    head = history.head()
    assert head is not None
    return head


@pytest.fixture
def app(scene: Scene) -> FastAPI:
    return build_service_app(TOKEN, scene.corpus)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def a_pack_s_note(scene: Scene) -> Mapping[str, object]:
    """A pack's note, installed and synced: the document a person copies
    to have a version of their own (#514)."""
    runner = CliRunner()
    for arguments in (
        ["pack", "add", str(scene.scratch / "provider/provider.ken.yml")],
        ["corpus", "sync"],
    ):
        answered = runner.invoke(main, arguments)
        assert answered.exit_code == 0, answered.output
    return {"handle": "convention"}


def installed(scene: Scene) -> Mapping[str, object]:
    answered = CliRunner().invoke(
        main, ["pack", "add", str(scene.scratch / "provider/provider.ken.yml")]
    )
    assert answered.exit_code == 0, answered.output
    return {"pack_id": "provider"}


def removed_first(scene: Scene) -> Mapping[str, object]:
    runner = CliRunner()
    answered = runner.invoke(main, ["corpus", "remove", "--yes", scene.note])
    assert answered.exit_code == 0, answered.output
    return {"document_id": scene.note, "commit": "HEAD~1"}


# One call per operation: the arguments it is given, built from the scene.
CALLS: dict[str, Callable[[Scene], Mapping[str, object]]] = {
    "add": lambda scene: {
        "destination": "notes",
        "identifiers": [str(scene.scratch / "sources/imaging.md")],
        "options": AddOptions(),
    },
    "add_in_groups": lambda scene: {
        "blocks": [
            GroupBlock(
                collection="notes",
                group="radio",
                identifiers=(str(scene.scratch / "sources/beams.md"),),
            )
        ],
        "options": AddOptions(),
    },
    "back_up": lambda scene: {
        "folder": scene.scratch / "backups",
        "password": "a password",
    },
    "copy_document": a_pack_s_note,
    "index": lambda scene: {"collection": "notes"},
    "install_pack": lambda scene: {"path": scene.scratch / "provider/provider.ken.yml"},
    "make_version_current": lambda scene: {"project": "tool", "version": "1.0"},
    "move_document": lambda scene: {
        "collection": "notes",
        "handle": scene.note,
        "group": "moved",
    },
    "remember": lambda scene: {"text": "Flagging removes the worst interference."},
    "remove_document": lambda scene: {"collection": "notes", "handle": scene.note},
    "remove_pack": installed,
    "remove_version": lambda scene: {"project": "tool", "version": "1.0"},
    "restore_document": removed_first,
    "return_corpus": lambda scene: {"commit": scene.first_commit},
    "sync_bundle": lambda scene: {"bundle": scene.scratch / "project" / ".context"},
    "sync_corpus": lambda scene: {},
    "contents": lambda scene: {"collection": "notes"},
    "docs_versions": lambda scene: {},
    "history": lambda scene: {"collection": None, "limit": 5},
    "return_preview": lambda scene: {"commit": scene.first_commit},
    "status": lambda scene: {},
    "tree": lambda scene: {"collection": None},
    "version_pages": lambda scene: {"project": "tool", "version": "1.0"},
    "document_marks": lambda scene: {"collection": "notes"},
    "found": lambda scene: {"handle": "calibration", "collection": None},
    "holdings": lambda scene: {},
    "pack_listing": lambda scene: {
        name: value for name, value in installed(scene).items() if name != "pack_id"
    },
    "last_change": lambda scene: {},
    "read_document": lambda scene: {"handle": "calibration", "frontmatter": True},
    "read_passage": lambda scene: {
        "handle": "calibration",
        "chunks": ChunkRange(start=0, stop=2),
    },
    "revision": lambda scene: {},
    "search_scope": lambda scene: {
        "collection": "notes",
        "question": "calibration",
        "bundle": None,
    },
    "sweep": lambda scene: {
        "question": "calibration",
        "scopes": ["notes", "context"],
        "named": False,
        "bundle": scene.scratch / "project" / ".context",
    },
}

# Each read as the window calls it today, written out by hand: comparing the
# API with the table's own function would compare it with itself (#373).
DIRECT: dict[str, Callable[[Context], object]] = {
    "contents": lambda context: kennis.holdings.contents_of(context, "notes"),
    "document_marks": lambda context: kennis.holdings.document_marks(context, "notes"),
    "found": lambda context: kennis.finding.found_document(
        context, "calibration", None
    ),
    "docs_versions": kennis.holdings.docs_versions,
    "history": lambda context: kennis.holdings.history_of(context, None, 5),
    "return_preview": lambda context: kennis.holdings.return_preview(
        context, history_root(Repository(context.corpus_root))
    ),
    "status": kennis.holdings.corpus_status,
    "tree": lambda context: kennis.holdings.corpus_tree(context, None),
    "version_pages": lambda context: kennis.holdings.version_pages(
        context, "tool", "1.0"
    ),
    "holdings": kennis.holdings.holdings,
    "pack_listing": lambda context: list_installed(context.corpus_root),
    "last_change": kennis.holdings.last_change,
    "read_document": lambda context: kennis.finding.read_document(
        context, "calibration", None, frontmatter=True
    ),
    "read_passage": lambda context: kennis.finding.read_passage(
        context, "calibration", None, chunks=ChunkRange(start=0, stop=2)
    ),
    "revision": kennis.holdings.revision,
    "search_scope": lambda context: kennis.retrieval.search_scope(
        "notes", "calibration", bundle=None
    ),
    "sweep": lambda context: kennis.retrieval.sweep(
        "calibration",
        scopes=["notes", "context"],
        named=False,
        bundle=find_bundle(Path.cwd()),
    ),
}

WRITES = sorted(name for name, operation in OPERATIONS.items() if operation.writes)
READS = sorted(name for name, operation in OPERATIONS.items() if not operation.writes)


def wire_arguments(arguments: Mapping[str, object]) -> dict[str, Json]:
    return {name: dump(value) for name, value in arguments.items()}


def returned(operation: Operation) -> object:
    return typing.get_type_hints(operation.function)["return"]


def events_of(client: TestClient, job: str) -> list[dict[str, Json]]:
    """Every message of a job's stream, in order, to its end."""
    with client.stream("GET", f"{PREFIX}/job/{job}/events", headers=BEARER) as answer:
        assert answer.status_code == 200
        assert answer.headers["content-type"].startswith("text/event-stream")
        body = "".join(answer.iter_text())
    messages: list[dict[str, Json]] = []
    for block in body.split("\n\n"):
        if block.startswith("data: "):
            message = json.loads(block.removeprefix("data: "))
            assert isinstance(message, dict)
            messages.append(message)
    return messages


def called(client: TestClient, name: str, arguments: Mapping[str, object]) -> Json:
    """The operation's result as the wire carried it, whether a read or a
    job; a refusal is raised as the error it was."""
    answer = client.post(
        f"{PREFIX}/call/{name}",
        headers=BEARER,
        json={"arguments": wire_arguments(arguments)},
    )
    said = answer.json()
    if "error" in said:
        raise load_error(said["error"])
    if "result" in said:
        result: Json = said["result"]
        return result
    final = events_of(client, said["job"])[-1]
    if "error" in final:
        raise load_error(final["error"])
    outcome: Json = final["result"]
    return outcome


def test_the_table_is_what_the_plan_expects():
    assert set(OPERATIONS) == EXPECTED_OPERATIONS


def test_every_operation_has_a_call_here():
    assert set(CALLS) == set(OPERATIONS)


def test_every_read_has_a_direct_call():
    assert set(DIRECT) == set(READS)


def test_the_table_has_both_kinds():
    """A parametrisation over nothing passes for the wrong reason."""
    assert WRITES and READS


@pytest.mark.parametrize("name", READS)
def test_a_read_answers_what_calling_it_directly_answers(
    client: TestClient, scene: Scene, name: str
):
    operation = OPERATIONS[name]
    arguments = CALLS[name](scene)

    through_the_api = called(client, name, arguments)

    assert through_the_api == dump(DIRECT[name](existing_corpus()))
    load(through_the_api, returned(operation))


@pytest.mark.parametrize("name", WRITES)
def test_a_write_runs_as_a_job_and_answers_its_declared_type(
    client: TestClient, scene: Scene, name: str
):
    operation = OPERATIONS[name]
    arguments = CALLS[name](scene)

    result = called(client, name, arguments)

    load(result, returned(operation))


def test_a_write_s_stream_carries_the_operation_s_own_events(
    client: TestClient, scene: Scene
):
    answer = client.post(
        f"{PREFIX}/call/add",
        headers=BEARER,
        json={"arguments": wire_arguments(CALLS["add"](scene))},
    )
    assert answer.status_code == 202

    messages = events_of(client, answer.json()["job"])

    kinds = [message["event"]["type"] for message in messages if "event" in message]
    assert wire_name(ItemStarted) in kinds
    assert wire_name(ItemFinished) in kinds
    assert "result" in messages[-1]


def test_a_finished_job_can_be_asked_for_again(client: TestClient, scene: Scene):
    """A client that stopped watching - a Ctrl-C detaches - can come back
    for the outcome while the service keeps it."""
    job = client.post(
        f"{PREFIX}/call/remember",
        headers=BEARER,
        json={"arguments": wire_arguments(CALLS["remember"](scene))},
    ).json()["job"]
    events_of(client, job)

    said = client.get(f"{PREFIX}/job/{job}", headers=BEARER).json()

    assert said["state"] == "done"
    assert said["kind"] == "remember"
    assert "result" in said


def test_an_unknown_job_is_not_found(client: TestClient):
    assert client.get(f"{PREFIX}/job/nothing", headers=BEARER).status_code == 404
    answer = client.get(f"{PREFIX}/job/nothing/events", headers=BEARER)
    assert answer.status_code == 404


def test_two_writes_complete_in_order_and_the_second_says_it_waited(
    app: FastAPI, client: TestClient, scene: Scene
):
    release = threading.Event()
    app.state.jobs.start("add", lambda events: release.wait(30), lane=CORPUS_LANE)
    answer = client.post(
        f"{PREFIX}/call/remember",
        headers=BEARER,
        json={"arguments": wire_arguments(CALLS["remember"](scene))},
    )
    release.set()

    messages = events_of(client, answer.json()["job"])

    events = [load(message["event"], Queued | Began) for message in messages[:2]]
    assert events == [Queued(ahead=1, behind="add"), Began()]
    assert "result" in messages[-1]


def test_a_read_is_answered_while_a_write_runs(app: FastAPI, client: TestClient):
    release = threading.Event()
    app.state.jobs.start("add", lambda events: release.wait(30), lane=CORPUS_LANE)
    try:
        answer = client.post(
            f"{PREFIX}/call/holdings", headers=BEARER, json={"arguments": {}}
        )
    finally:
        release.set()

    assert answer.status_code == 200
    assert "result" in answer.json()


def test_a_note_written_during_a_build_lands_and_says_its_index_waits(
    client: TestClient, scene: Scene
):
    """The two lanes, as #330 requires: the build holds the notes index, and
    the note is written, committed, and reported `deferred`."""
    index_lock = scene.corpus / "index" / "notes" / ".lock"
    with FileLock(str(index_lock), timeout=0):
        result = called(client, "remember", CALLS["remember"](scene))

    assert isinstance(result, dict)
    report = typing.cast(dict[str, Json], result["fields"])
    assert report["index_outcome"] == "deferred"


def test_a_read_s_refusal_arrives_as_the_error_it_was(client: TestClient):
    with pytest.raises(NothingToIndex):
        called(
            client,
            "search_scope",
            {"collection": "literature", "question": "x", "bundle": None},
        )


def test_a_write_s_refusal_ends_its_stream(client: TestClient, scene: Scene):
    with pytest.raises(KennisError):
        called(client, "remove_document", {"collection": "notes", "handle": "absent"})


def test_an_unknown_operation_is_not_found(client: TestClient):
    answer = client.post(
        f"{PREFIX}/call/format_the_disk", headers=BEARER, json={"arguments": {}}
    )

    assert answer.status_code == 404


@pytest.mark.parametrize(
    "arguments",
    [
        {"collection": "notes", "question": "x", "bundle": None, "shell": "rm -rf"},
        {"collection": "notes", "bundle": None},
        {"collection": "notes", "question": 42, "bundle": None},
    ],
    ids=["unknown", "missing", "wrong type"],
)
def test_arguments_the_signature_does_not_take_are_refused(
    client: TestClient, arguments: dict[str, Json]
):
    """Read against the function's own hints, so a request cannot hand the
    service anything its signature does not take."""
    answer = client.post(
        f"{PREFIX}/call/search_scope", headers=BEARER, json={"arguments": arguments}
    )

    assert answer.status_code == 400
    assert "error" in answer.json()


def test_the_service_s_own_parameters_are_not_arguments(client: TestClient):
    """`events` and `restored` are the service's to give, never a client's."""
    answer = client.post(
        f"{PREFIX}/call/remember",
        headers=BEARER,
        json={"arguments": {"text": "x", "restored": []}},
    )

    assert answer.status_code == 400


@pytest.mark.parametrize("name", WRITES)
def test_each_write_runs_in_its_own_lane(scene: Scene, name: str):
    """An index build in the corpus lane would wait behind every add, and
    a note behind every build, which is what the two lanes exist to stop
    (#330). Written by hand rather than read from the table."""
    bundle = scene.scratch / "project" / ".context"
    expected = {"index": INDEX_LANE, "sync_bundle": context_lane(str(bundle))}
    operation = OPERATIONS[name]
    arguments = CALLS[name](scene) if name != "restore_document" else {}

    assert operation.lane(arguments) == expected.get(name, CORPUS_LANE)


def test_a_search_uses_the_bundle_it_was_sent_not_the_service_s_directory(
    client: TestClient, scene: Scene, monkeypatch: pytest.MonkeyPatch
):
    """The service stands in one project; the client sends another (#508)."""
    elsewhere = scene.scratch / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    runner = CliRunner()
    assert runner.invoke(main, ["context", "init", "--here"]).exit_code == 0
    assert (
        runner.invoke(
            main, ["remember", "--context", "Tropospheric delay varies by hour."]
        ).exit_code
        == 0
    )
    assert runner.invoke(main, ["context", "index"]).exit_code == 0
    monkeypatch.chdir(scene.scratch / "project")

    hits = called(
        client,
        "search_scope",
        {
            "collection": "context",
            "question": "tropospheric",
            "bundle": elsewhere / ".context",
        },
    )

    assert isinstance(hits, list) and hits
