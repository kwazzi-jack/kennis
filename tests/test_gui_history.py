"""Recent searches: the first thing kennis stores about its user.

Everything else the interface shows is recomputed from the corpus on
request. This is a record of the person rather than of their
documents, so the tests that matter are about where it is kept, what
is in it, and that it can be removed.

Three properties carry the design.

**It is never in the corpus.** That is a git repository staged with
`git add --all .` and converged by a pack sync, so a history file
there would be committed and carried wherever the corpus goes.

**Typing one query does not record five.** The box fires every 400ms,
so "calibration" arrives as "cali", "calibratio", "calibration". A
new query replaces the most recent entry when one is a prefix of the
other and it is recent, and is appended otherwise - the window is
what separates refining a query from making a similar one next week.

**It can be cleared, by a POST.** A query is the user's own words and
there must be a way to remove one. A GET that writes is one a
prefetcher will follow.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.gui import history
from kennis.gui.app import build_app

TOKEN = "a-test-token"


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
    assert (
        run.invoke(main, ["remember", "Antenna gains drift on long tracks."]).exit_code
        == 0
    )
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0
    return tmp_path


def admitted(client: TestClient) -> None:
    client.get("/", params={"token": TOKEN})


# ---------------------------------------------------------------------------
# Where it is kept
# ---------------------------------------------------------------------------


def test_the_history_is_not_written_into_the_corpus(corpus: Path, client: TestClient):
    """The corpus is committed with `git add --all .`, so a file put
    there travels with it. Searched for by name anywhere under the
    corpus root rather than at the one path it would be written to -
    the point is that nothing lands there, not that one path is
    avoided."""
    admitted(client)

    client.get("/hits", params={"q": "gains", "scope": "notes"})

    corpus_root = corpus / "corpus"
    assert list(corpus_root.rglob("*history*")) == []
    assert list(corpus_root.rglob("*search*")) == []
    assert corpus_root not in history.history_path().parents


def test_the_state_directory_is_redirected_for_every_test():
    """`KENNIS_STATE_DIR` is a new variable, and a test that does not
    set it writes to the developer's own state directory. The autouse
    fixture redirects it; this asserts the redirection happened, so
    removing the fixture fails here rather than silently polluting a
    real machine. The same shape as the `somewhere_else` guard for
    concern #325."""
    written_to = history.state_dir()

    assert "pytest" in str(written_to), written_to


def test_a_search_is_recorded_with_its_scope_and_count(
    corpus: Path, client: TestClient
):
    admitted(client)

    client.get("/hits", params={"q": "gains", "scope": "notes"})

    recent = history.recent()
    assert len(recent) == 1
    assert recent[0].query == "gains"
    assert recent[0].scope == "notes"
    assert recent[0].hits == 1
    assert recent[0].capped is False


def test_an_empty_query_is_not_a_search(corpus: Path, client: TestClient):
    """Landing on the page is not searching for nothing."""
    admitted(client)

    client.get("/", params={"q": "", "scope": "notes"})
    client.get("/hits", params={"q": "   ", "scope": "notes"})

    assert history.recent() == []


# ---------------------------------------------------------------------------
# Collapsing the keystrokes
# ---------------------------------------------------------------------------


def test_typing_one_query_records_one_entry(corpus: Path, client: TestClient):
    """The defect this exists to prevent: a list of prefixes of one
    word. Every request here is what the debounced box actually
    sends."""
    admitted(client)

    for typed in ("g", "ga", "gai", "gain", "gains"):
        client.get("/hits", params={"q": typed, "scope": "notes"})

    recent = history.recent()
    assert len(recent) == 1
    assert recent[0].query == "gains"


def test_backspacing_keeps_the_query_the_reader_stopped_on(
    corpus: Path, client: TestClient
):
    """The same interaction from the other end. Collapse is on either
    direction of the prefix relation, so deleting back to a shorter
    query leaves that shorter query rather than the long one."""
    admitted(client)

    client.get("/hits", params={"q": "gains", "scope": "notes"})
    client.get("/hits", params={"q": "gai", "scope": "notes"})

    recent = history.recent()
    assert len(recent) == 1
    assert recent[0].query == "gai"


def test_two_unrelated_searches_are_two_entries(corpus: Path, client: TestClient):
    admitted(client)

    client.get("/hits", params={"q": "gains", "scope": "notes"})
    client.get("/hits", params={"q": "bandpass", "scope": "notes"})

    assert [entry.query for entry in history.recent()] == ["bandpass", "gains"]


def test_a_refinement_made_later_is_its_own_entry(corpus: Path, client: TestClient):
    """The case that put a window on the collapse rule. "gains" and
    then "gains calibration" typed in one breath is one search; the
    same pair a week apart is two the reader would want both of. A
    bare prefix test cannot tell them apart and would eat the first."""
    admitted(client)
    client.get("/hits", params={"q": "gains", "scope": "notes"})

    aged = [
        replace(entry, at=entry.at - history.COLLAPSE_WINDOW_SECONDS - 1)
        for entry in history.recent()
    ]
    history.overwrite(aged)
    client.get("/hits", params={"q": "gains calibration", "scope": "notes"})

    assert [entry.query for entry in history.recent()] == [
        "gains calibration",
        "gains",
    ]


def test_the_same_query_twice_is_not_two_entries(corpus: Path, client: TestClient):
    """A reload and a Back both re-run the search, and an identical
    string is a prefix of itself - so recording is idempotent under
    both without a special case."""
    admitted(client)

    client.get("/", params={"q": "gains", "scope": "notes"})
    client.get("/", params={"q": "gains", "scope": "notes"})

    assert len(history.recent()) == 1


def test_the_list_is_capped_and_drops_the_oldest(corpus: Path, client: TestClient):
    admitted(client)

    for number in range(history.KEPT + 5):
        client.get("/hits", params={"q": f"query{number:03d}x", "scope": "notes"})

    recent = history.recent()
    assert len(recent) == history.KEPT
    assert recent[0].query == f"query{history.KEPT + 4:03d}x"
    assert "query000x" not in [entry.query for entry in recent]


# ---------------------------------------------------------------------------
# Showing it, and removing it
# ---------------------------------------------------------------------------


def test_the_recents_appear_on_an_empty_search_page(corpus: Path, client: TestClient):
    admitted(client)
    client.get("/hits", params={"q": "gains", "scope": "notes"})

    page = client.get("/")

    assert "gains" in page.text
    assert (
        "/?q=gains&amp;scope=notes" in page.text or "/?q=gains&scope=notes" in page.text
    )


def test_the_recents_give_way_to_results(corpus: Path, client: TestClient):
    """A page showing both would put what was searched for before
    beside what was just found, which is two answers to one
    question."""
    admitted(client)
    client.get("/hits", params={"q": "bandpass", "scope": "notes"})

    page = client.get("/", params={"q": "gains", "scope": "notes"})

    assert "bandpass" not in page.text


def test_clearing_the_history_is_a_post(corpus: Path, client: TestClient):
    """A GET that writes is one a prefetcher will follow, and this
    one destroys."""
    admitted(client)
    client.get("/hits", params={"q": "gains", "scope": "notes"})

    refused = client.get("/history/clear")
    assert refused.status_code in (404, 405)
    assert history.recent() != []

    cleared = client.post("/history/clear")
    assert cleared.status_code == 200
    assert history.recent() == []


def test_a_damaged_history_file_is_not_a_crash(corpus: Path, client: TestClient):
    """It is a file on disk that nothing validates on write from a
    previous version, and a search page that 500s because of it would
    make the corpus unreachable through the interface for the sake of
    a convenience."""
    admitted(client)
    history.history_path().parent.mkdir(parents=True, exist_ok=True)
    history.history_path().write_text("{not json", encoding="utf-8")

    page = client.get("/")

    assert page.status_code == 200
    assert history.recent() == []


def test_the_history_records_no_results(corpus: Path, client: TestClient):
    """The count, never the documents. A list of which papers matched
    which query is a far more revealing file than a list of queries,
    and nothing here needs it."""
    admitted(client)
    client.get("/hits", params={"q": "gains", "scope": "notes"})

    written = json.loads(history.history_path().read_text(encoding="utf-8"))

    assert set(written[0]) == {"query", "scope", "mode", "hits", "capped", "at"}


def test_a_saturated_search_reports_its_count_as_a_floor(
    corpus: Path, client: TestClient
):
    """`default_top_k` is 3 *per scope*, so a search that fills its
    quota has no idea how many more there were. Every query on a real
    corpus reported "9 hits" - a ceiling wearing the look of a
    measurement - until the line said "at least"."""
    run = CliRunner()
    for number in range(5):
        assert (
            run.invoke(main, ["remember", f"Note {number} on antenna gains."]).exit_code
            == 0
        )
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0
    admitted(client)

    client.get("/hits", params={"q": "gains", "scope": "notes"})

    entry = history.recent()[0]
    assert entry.hits == 3, "the fixture must saturate for this to test anything"
    assert entry.capped is True
    assert "3+ hits" in client.get("/").text


def test_the_same_query_on_another_day_moves_to_the_top(
    corpus: Path, client: TestClient
):
    """Not a second slot. The collapse rule looks only at the most
    recent entry, so a query run again after others intervened took
    another line - and the few queries a person actually runs filled
    the list with themselves.

    One run of the interface could not show this and two could: the
    history outlives a launch, so the second walk rendered every
    query twice."""
    admitted(client)
    for query in ("calibration", "bandpass", "wsclean"):
        client.get("/hits", params={"q": query, "scope": "notes"})

    client.get("/hits", params={"q": "calibration", "scope": "notes"})

    queries = [entry.query for entry in history.recent()]
    assert queries == ["calibration", "wsclean", "bandpass"]


def test_moving_to_the_top_keeps_the_newest_count(corpus: Path, client: TestClient):
    """The entry that survives is the new one, not the old one
    relocated, so a query whose answer has changed says what it says
    now."""
    admitted(client)
    client.get("/hits", params={"q": "gains", "scope": "notes"})
    before = history.recent()[0].hits
    run = CliRunner()
    assert run.invoke(main, ["remember", "More on antenna gains."]).exit_code == 0
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0
    client.get("/hits", params={"q": "bandpass", "scope": "notes"})

    client.get("/hits", params={"q": "gains", "scope": "notes"})

    moved = history.recent()[0]
    assert moved.query == "gains"
    assert moved.hits > before, "the old entry was relocated rather than replaced"
