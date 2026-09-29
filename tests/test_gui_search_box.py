"""The search form: what the box says, and what makes it submit.

Three subjects, and only the first was a defect.

**The placeholder names the scope.** It read "Search everything
kennis holds" whatever the select said, so a reader who had narrowed
to `literature` was told the opposite of what was about to happen.

**The Enter key already worked**, and these tests exist so it keeps
working. The behaviour itself is the HTML specification's - a
browser submits a form on Enter when the form has a submit button -
so what kennis owns is the markup that invokes it, and that is what
is asserted here. The behaviour was measured separately in a
headless browser: typing then Enter fired a request in 12ms, ahead
of the 400ms debounce, rendered 9 hits and pushed
`/?q=selfcal&scope=all` into the address.

**The interface works without JavaScript**, which nobody planned.
The form carries no `action`, so a native submission goes to the
current path with `q` and `scope` in the query string - and that is
exactly the address the page reconstructs from, because of the
decision in concern #340. Measured with scripting disabled: the
query ran, 9 hits rendered, the box kept the query. One
`action="/hits"` would take it away and nothing would say so.
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
from kennis.retrieval import EVERY_SCOPE, SCOPE_NAMES

TOKEN = "a-test-token"
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


def a_note(tmp_path: Path, name: str, body: str) -> None:
    run = CliRunner()
    source = tmp_path / "sources" / f"{name}.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(f"# {name}\n\n{body}\n", encoding="utf-8")
    assert run.invoke(main, ["corpus", "add", "-n", str(source)]).exit_code == 0
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0


# ---------------------------------------------------------------------------
# What the box says
# ---------------------------------------------------------------------------


def test_the_hint_names_the_scope_it_will_search():
    assert words.search_hint_for("literature") == "Search literature kennis holds"
    assert words.search_hint_for("notes") == "Search notes kennis holds"


def test_the_hint_for_a_sweep_says_where_a_sweep_goes():
    """The select's own label for the same choice, so the box and the
    thing beside it do not use two words for one scope."""
    assert words.EVERYWHERE_LABEL in words.search_hint_for(EVERY_SCOPE)


def test_every_scope_has_a_hint_and_they_are_all_different():
    """A scope whose hint collided with another's would be a box that
    says the wrong thing for one choice only, which is the hardest
    kind of wrong to notice."""
    hints = {
        scope: words.search_hint_for(scope) for scope in (*SCOPE_NAMES, EVERY_SCOPE)
    }

    assert len(set(hints.values())) == len(hints), hints
    for scope, hint in hints.items():
        assert hint.startswith("Search "), (scope, hint)


def test_the_page_is_drawn_with_the_hint_for_its_own_scope(
    corpus: Path, client: TestClient
):
    """The scope arrives in the address, so the first paint has to be
    right without a script running at all."""
    admitted(client)

    page = client.get("/", params={"scope": "literature"}).text

    assert f'placeholder="{words.search_hint_for("literature")}"' in page


def test_each_scope_option_carries_its_own_hint(corpus: Path, client: TestClient):
    """Changing the select must change the box without a round trip,
    and the words must not move into JavaScript to manage it. Each
    option carries the sentence the server wrote."""
    admitted(client)

    page = client.get("/").text
    options = re.findall(r"<option\b[^>]*>", page)

    assert options
    for option in options:
        value = re.search(r'value="([^"]*)"', option)
        assert value is not None, option
        assert f'data-hint="{words.search_hint_for(value.group(1))}"' in option


def test_the_script_carries_words_it_did_not_compose():
    """`static/hint.js` copies a string the server wrote onto the
    input. The moment it contains a sentence, the interface has two
    places its words live and only one of them is tested.

    The same rule `progress.js` follows, and it is asserted rather
    than left to review."""
    script = (STATIC / "hint.js").read_text(encoding="utf-8")
    code = "\n".join(
        line for line in script.splitlines() if not line.strip().startswith("//")
    )

    assert "Search" not in code
    assert "kennis holds" not in code
    assert words.EVERYWHERE_LABEL not in code


# ---------------------------------------------------------------------------
# What makes it submit
# ---------------------------------------------------------------------------


def test_the_form_has_what_a_browser_needs_to_submit_on_enter(
    corpus: Path, client: TestClient
):
    """A browser submits a form on Enter when the form has a submit
    button, and htmx handles `submit` only if its trigger list names
    it. Both are markup kennis owns, and removing either takes the
    Enter key away silently.

    A proxy for the behaviour, not a proof of it: the behaviour was
    measured in a headless browser and is described in this module's
    docstring."""
    admitted(client)

    page = client.get("/").text
    form = page[page.index("<form") : page.index("</form>")]

    assert 'type="submit"' in form
    trigger = re.search(r'hx-trigger="([^"]*)"', form)
    assert trigger is not None, form
    assert "submit" in [part.strip().split()[0] for part in trigger.group(1).split(",")]


def test_the_form_names_no_action_so_it_falls_back_to_the_address(
    corpus: Path, client: TestClient
):
    """With no `action`, a native submission goes to the current path
    with the fields as a query string - which is the address the page
    reconstructs from. An `action="/hits"` would send a reader without
    JavaScript to a bare fragment instead. Concern #340."""
    admitted(client)

    page = client.get("/").text
    form = page[page.index("<form") : page.index("</form>")]

    assert "action=" not in form


def test_a_search_in_the_address_answers_without_any_script(
    corpus: Path, client: TestClient
):
    """What the native submission lands on. No htmx header, no
    fragment - the whole page, with the hits in it and the query
    still in the box."""
    a_note(corpus, "gains", "The bandpass and the gains of the array.")
    admitted(client)

    page = client.get("/", params={"q": "bandpass", "scope": "notes"}).text

    assert 'value="bandpass"' in page
    assert "gains" in page


# ---------------------------------------------------------------------------
# Saying when it is working
# ---------------------------------------------------------------------------


def test_the_hits_say_what_they_are_the_hits_for(corpus: Path, client: TestClient):
    """The indicator asks one question - are the hits on the page the
    hits for what is in the box? - so the page has to state what the
    hits are for. It travels inside `#hits`, which is what htmx
    replaces, so every swap brings a fresh statement.

    A marker outside the swapped region would keep saying whatever it
    said when the page was first drawn."""
    a_note(corpus, "gains", "The bandpass and the gains of the array.")
    admitted(client)

    fragment = client.get("/hits", params={"q": "bandpass", "scope": "notes"}).text

    assert 'data-query="bandpass"' in fragment
    assert 'data-scope="notes"' in fragment


def test_what_the_hits_are_for_is_safe_in_an_attribute(
    corpus: Path, client: TestClient
):
    """The query is the reader's own text and it lands in an HTML
    attribute. A quote in it would close the attribute and everything
    after it would be markup."""
    admitted(client)

    fragment = client.get(
        "/hits", params={"q": '" onmouseover="x', "scope": "notes"}
    ).text

    assert '" onmouseover="x' not in fragment
    assert "onmouseover" not in fragment.replace("&#34; onmouseover=&#34;x", "")


def test_the_page_carries_an_indicator_with_words_from_python(
    corpus: Path, client: TestClient
):
    admitted(client)

    page = client.get("/").text

    assert words.SEARCHING in page
    assert 'aria-live="polite"' in page


def test_the_indicator_script_composes_nothing_and_remembers_nothing():
    """Two properties, and the second is why this is not the obvious
    implementation.

    **No words.** The same rule `hint.js` and `progress.js` follow.

    **No timer.** The obvious version shows on `input` and hides on
    `htmx:afterSwap`, and gets stuck: htmx's trigger is `input
    changed`, so typing a character and deleting it fires no request
    and the indicator never comes down. The remedy people reach for
    is a `setTimeout` safety net, which is a second wrong answer -
    it hides a true statement after an arbitrary delay. This one
    recomputes from what is on the page, so there is nothing to get
    stuck and nothing to time out."""
    script = (STATIC / "searching.js").read_text(encoding="utf-8")
    code = "\n".join(
        line for line in script.splitlines() if not line.strip().startswith("//")
    )

    assert words.SEARCHING not in code
    assert "setTimeout" not in code
    assert "setInterval" not in code
    # It has to read both halves of the comparison, or it is not
    # deriving the answer from anything.
    assert "dataset.query" in code
    assert "dataset.scope" in code


def test_the_indicator_is_hidden_when_the_hits_match_the_box(
    corpus: Path, client: TestClient
):
    """A page drawn from the address is already up to date, so it must
    not open saying it is searching."""
    a_note(corpus, "gains", "The bandpass and the gains of the array.")
    admitted(client)

    page = client.get("/", params={"q": "bandpass", "scope": "notes"}).text
    indicator = page[page.index('id="searching"') :]
    indicator = indicator[: indicator.index(">") + 1]

    assert "hidden" in indicator
