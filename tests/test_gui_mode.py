"""Choosing which retrieval legs run, from the window.

The engine has taken a mode since milestone 1 and `kennis search
--mode` has passed one for as long. What v0.7b adds is a way to say
it from the interface and a place in the address to carry it, so the
half of the choice v0.7a reported on - `lexical: very high  meaning:
low` - can also be decided.

Three things here are easy to get wrong in ways that still look
right:

- **The default is not `hybrid`.** It is "no mode given", which lets
  each scope use its own setting. The bundle's is lexical by design,
  so sending `hybrid` for a reader who touched nothing would ask it
  for a leg it deliberately has not got and warn about the absence.
  Both directions are asserted: silent by default, and speaking when
  the reader chose it.
- **The words are the band's words.** A reader who is shown
  `meaning: low` and offered a mode called `dense` has been given two
  names for one thing.
- **An unknown mode is named.** Silently falling back to the default
  would answer a different question than the one in the address.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.gui import history, words
from kennis.gui.app import build_app
from kennis.gui.pages import shown_recents
from kennis.retrieval import as_mode

TOKEN = "a-test-token"
STATIC = Path(__file__).resolve().parents[1] / "src/kennis/gui/static"
TEMPLATES = Path(__file__).resolve().parents[1] / "src/kennis/gui/templates"


@pytest.fixture
def client() -> TestClient:
    return TestClient(build_app(TOKEN), follow_redirects=False)


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    run = CliRunner()
    assert run.invoke(main, ["corpus", "init"]).exit_code == 0
    return tmp_path


def admitted(app_client: TestClient) -> TestClient:
    assert app_client.get("/", params={"token": TOKEN}).status_code == 200
    return app_client


def mode_select(page: str) -> str:
    """Just the mode control, for #375's reason: the page holds the
    scope's select and the theme's as well, and a test that scanned
    every `<option>` would be reading all three."""
    found = re.search(r'<select name="mode".*?</select>', page, re.DOTALL)
    assert found is not None, "no mode select on the page"
    return found.group(0)


def a_note(tmp_path: Path, name: str, body: str) -> None:
    run = CliRunner()
    source = tmp_path / "sources" / f"{name}.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(f"# {name}\n\n{body}\n", encoding="utf-8")
    assert run.invoke(main, ["corpus", "add", "-n", str(source)]).exit_code == 0
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0


# ---------------------------------------------------------------------------
# The words
# ---------------------------------------------------------------------------


def test_the_modes_are_named_for_what_a_band_is_named_for():
    """`lexical` and `meaning` are what a hit's margin says. A control
    offering `bm25` and `dense` beside it would make the reader hold
    two vocabularies for one distinction, and the engine's names are
    for the mechanism rather than for what it measures."""
    labels = " ".join(label for _, label in words.MODE_CHOICES).lower()

    assert "lexical" in labels
    assert "meaning" in labels
    for mechanism in ("bm25", "dense", "hybrid", "embedding", "cosine"):
        assert mechanism not in labels, mechanism


def test_every_engine_mode_is_offered_and_nothing_else_is():
    """A mode the engine has and the window does not offer is a
    capability the reader cannot reach; one the window offers and the
    engine rejects is a control that fails when used."""
    offered = [value for value, _ in words.MODE_CHOICES if value]

    assert set(offered) == {"hybrid", "bm25", "dense"}
    for value in offered:
        assert as_mode(value) == value


def test_the_default_is_no_mode_at_all():
    """Not `hybrid`. `sweep` with no mode lets each scope use its own
    setting, and the bundle's is lexical by design - design section
    13, because a dense bundle index costs what
    `retrieval.context_method` exists to avoid."""
    assert words.MODE_DEFAULT == ""
    assert words.MODE_CHOICES[0][0] == words.MODE_DEFAULT


def test_the_default_is_offered_first_and_has_a_label():
    """A blank option in a select is a control whose current state
    cannot be read."""
    label = dict(words.MODE_CHOICES)[words.MODE_DEFAULT]

    assert label.strip()
    assert label.lower() != "none"


# ---------------------------------------------------------------------------
# The control
# ---------------------------------------------------------------------------


def test_the_page_offers_the_mode_beside_the_scope(corpus: Path, client: TestClient):
    admitted(client)

    page = client.get("/").text

    control = mode_select(page)
    for value, label in words.MODE_CHOICES:
        assert f'value="{value}"' in control, value
        assert label in control, label


def test_the_control_shows_the_mode_the_address_asked_for(
    corpus: Path, client: TestClient
):
    """The mode arrives in the address, so the first paint has to be
    drawn with it or Back and reload show a control disagreeing with
    the results beneath it."""
    admitted(client)

    page = client.get("/", params={"q": "x", "mode": "dense"}).text

    control = mode_select(page)
    chosen = re.findall(r'<option value="([^"]*)"[^>]*\sselected', control)
    assert chosen == ["dense"], control


def test_changing_the_mode_re_runs_the_search(corpus: Path, client: TestClient):
    """By name, not `from:select`. htmx resolves that against the
    document and the theme control in the sidebar is a select, so a
    colour change would fire a search."""
    admitted(client)

    form = re.search(r'<form class="search".*?>', client.get("/").text, re.DOTALL)
    assert form is not None
    trigger = form.group(0)

    assert "change from:select[name=mode]" in trigger
    assert "change from:select[name=scope]" in trigger
    assert "from:select," not in trigger and "from:select " not in trigger


def test_the_indicator_notices_a_mode_that_has_not_been_answered_yet():
    """`searching.js` derives staleness by comparing what the page was
    answered with against what the form now says. Without the mode in
    that comparison, changing it shows nothing while the search runs."""
    script = (STATIC / "searching.js").read_text(encoding="utf-8")
    code = "\n".join(
        line for line in script.splitlines() if not line.strip().startswith("//")
    )

    # The *comparison*, not the word. `select[name=mode]` and the
    # variable it is read into both survive the comparison being
    # deleted, so asserting "mode" appears asserted nothing. Concern
    # #382.
    assert "dataset.mode" in code, code
    assert re.search(r"!==\s*shown\.dataset\.mode", code), code
    marker = (TEMPLATES / "hits.html").read_text(encoding="utf-8")
    assert 'data-mode="{{ mode }}"' in marker


# ---------------------------------------------------------------------------
# The address
# ---------------------------------------------------------------------------


def test_the_mode_is_in_the_address_htmx_pushes(corpus: Path, client: TestClient):
    """Concern #340: the header names the page rather than the route
    that was fetched. It has to carry the mode too, or Back restores a
    search that ran differently from the one it shows."""
    a_note(corpus, "rivers", "Rivers carry sediment to the delta.")
    admitted(client)

    answered = client.get(
        "/hits", params={"q": "sediment", "scope": "notes", "mode": "bm25"}
    )

    pushed = answered.headers["HX-Push-Url"]
    assert "q=sediment" in pushed
    assert "scope=notes" in pushed
    assert "mode=bm25" in pushed


def test_the_default_mode_is_not_written_into_the_address(
    corpus: Path, client: TestClient
):
    """An address carrying `mode=` says the reader chose the default,
    which is a different claim from not having chosen."""
    a_note(corpus, "rivers", "Rivers carry sediment to the delta.")
    admitted(client)

    answered = client.get("/hits", params={"q": "sediment", "scope": "notes"})

    assert "mode=" not in answered.headers["HX-Push-Url"]


def test_a_mode_that_is_not_offered_is_named_rather_than_ignored(
    corpus: Path, client: TestClient
):
    """Falling back to the default would answer a question other than
    the one in the address, and say nothing about having done so."""
    a_note(corpus, "rivers", "Rivers carry sediment to the delta.")
    admitted(client)

    page = client.get("/", params={"q": "sediment", "mode": "psychic"})

    assert page.status_code == 200
    # **In the message**, not merely somewhere on the page. The
    # marker carries `data-mode="psychic"` whatever the message says,
    # so asserting the word appears passed for a page that named
    # nothing. Found by injection. Concern #382.
    warning = re.search(r'<p class="role-warning">([^<]*)</p>', page.text)
    assert warning is not None, page.text
    assert "psychic" in warning.group(1), warning.group(1)
    # And the search did not run: no hit carries a handle.
    assert "chunk=" not in page.text


def test_a_named_mode_reaches_the_engine(corpus: Path, client: TestClient):
    """The whole point of the control, and the one thing a markup test
    cannot see.

    Proved by the case where choosing a mode *removes* a warning.
    `corpus_method` defaults to `hybrid`, and this corpus has no
    embedding backend, so the default degrades to lexical and
    `Sweep.degraded` names the collection. Asking for `bm25` is asking
    for what the index can do, so nothing degraded and nothing is
    said. The two directions are the same fixture and the same query,
    differing only in the parameter under test."""
    a_note(corpus, "rivers", "Rivers carry sediment to the delta.")
    admitted(client)

    default = client.get("/hits", params={"q": "sediment", "scope": "notes"}).text
    chosen = client.get(
        "/hits", params={"q": "sediment", "scope": "notes", "mode": "bm25"}
    ).text

    assert "lexical search" in default, default
    assert "lexical search" not in chosen, chosen
    # Both found the note, so the difference is the warning and not
    # one of them having failed to run.
    assert "chunk=" in default and "chunk=" in chosen


def test_the_page_says_when_a_search_ran_lexically_after_all(
    corpus: Path, client: TestClient
):
    """`Sweep.degraded` reached the command line and never reached the
    window: `kennis search` printed "the notes index has no dense leg,
    so this ran as a lexical search" and the page said nothing at all.

    It mattered little while nobody could ask for a dense leg from the
    page. A control that offers "Meaning only" and then silently
    returns lexical results is a control that lies. Concern #381."""
    a_note(corpus, "rivers", "Rivers carry sediment to the delta.")
    admitted(client)

    page = client.get(
        "/", params={"q": "sediment", "scope": "notes", "mode": "dense"}
    ).text

    assert "no dense leg" in page
    assert "notes" in page


def test_the_page_keeps_no_client_side_history_snapshot(
    corpus: Path, client: TestClient
):
    """Back and Forward are navigations the server answers.

    htmx caches the page as it was and restores that snapshot, but the
    snapshot does not carry the search form, which sits outside the
    swapped `#hits`. Measured in a browser: search, change the scope,
    Back, Forward - and the scope control read `all` while the address
    and the results both said `notes`. The invariant from concern #340
    is that the search is in the address and the server names it, and
    a client-side snapshot is the client naming it instead.

    The behaviour needs a browser and the suite has none, so what is
    asserted here is the attribute that decides it. Concern #383."""
    admitted(client)

    page = client.get("/").text

    assert re.search(r"<body\b[^>]*\shx-history=\"false\"", page), page[:400]


# ---------------------------------------------------------------------------
# What is remembered
# ---------------------------------------------------------------------------


def test_a_search_from_the_page_records_the_mode_it_ran_with(
    corpus: Path, client: TestClient
):
    """Through the interface rather than by calling `record`. Every
    other test here supplies the mode itself, so the one line that
    passes it from the request to the history was untested and an
    injection setting it to "" was not caught. Concern #382."""
    a_note(corpus, "rivers", "Rivers carry sediment to the delta.")
    admitted(client)

    client.get("/hits", params={"q": "sediment", "scope": "notes", "mode": "bm25"})

    assert history.recent()[0].mode == "bm25"


def test_a_recent_search_offers_the_mode_it_ran_with(corpus: Path, tmp_path: Path):
    history.overwrite([])
    history.record("sediment", scope="notes", hits=1, capped=False, mode="dense")

    shown = shown_recents(history.recent())

    assert len(shown) == 1
    assert "mode=dense" in shown[0].href


def test_a_recent_search_with_no_mode_carries_none(corpus: Path, tmp_path: Path):
    history.overwrite([])
    history.record("sediment", scope="notes", hits=1, capped=False, mode="")

    shown = shown_recents(history.recent())

    assert "mode=" not in shown[0].href
    assert dict(words.MODE_CHOICES)[""].lower() not in shown[0].detail.lower()


def test_a_recent_search_says_the_mode_when_it_is_not_the_default(
    corpus: Path, tmp_path: Path
):
    """Two facts were asked for - where and how many - and a third is
    added only when it is news."""
    history.overwrite([])
    history.record("sediment", scope="notes", hits=1, capped=False, mode="bm25")

    detail = shown_recents(history.recent())[0].detail

    assert dict(words.MODE_CHOICES)["bm25"].lower() in detail.lower()


def test_a_history_written_before_the_mode_existed_still_reads(
    corpus: Path, tmp_path: Path
):
    """`recent()` swallows a `KeyError` and returns nothing, so
    requiring the field would silently empty the reader's history.
    This is their own data rather than a code path, which is why it
    gets a default where the project otherwise keeps no compatibility."""
    history.history_path().parent.mkdir(parents=True, exist_ok=True)
    history.history_path().write_text(
        json.dumps(
            [
                {
                    "query": "sediment",
                    "scope": "notes",
                    "hits": 1,
                    "capped": False,
                    "at": 1.0,
                }
            ]
        ),
        encoding="utf-8",
    )

    held = history.recent()

    assert [search.query for search in held] == ["sediment"]
    assert held[0].mode == ""


def test_changing_the_mode_does_not_make_a_second_recent_search(
    corpus: Path, tmp_path: Path
):
    """The same rule the scope gets: adjusting a control re-runs one
    search rather than making two, and the entry keeps whichever the
    reader stopped on."""
    history.overwrite([])
    history.record("sediment", scope="notes", hits=1, capped=False, mode="")
    history.record("sediment", scope="notes", hits=1, capped=False, mode="bm25")

    held = history.recent()

    assert len(held) == 1, held
    assert held[0].mode == "bm25"


def test_an_old_search_repeated_with_a_new_mode_is_still_one_entry(
    corpus: Path, tmp_path: Path
):
    """The test above cannot see this. Two records seconds apart are
    collapsed by the *typing* rule, so an exact-repeat rule that kept
    entries differing in mode changed nothing and an injection into it
    was inert. Planting an entry older than the collapse window leaves
    only the rule under test. Concern #382."""
    history.overwrite(
        [
            history.Search(
                query="sediment",
                scope="notes",
                mode="",
                hits=1,
                capped=False,
                at=time.time() - history.COLLAPSE_WINDOW_SECONDS - 60,
            )
        ]
    )

    history.record("sediment", scope="notes", hits=1, capped=False, mode="bm25")

    held = history.recent()
    assert len(held) == 1, held
    assert held[0].mode == "bm25"
