"""The graphical front end's shell: the token, the theme, the peer rule.

Unit 9a builds nothing a user would call a feature. It builds the four
things that are expensive to add afterwards, and three of them are
testable here.

**The token is the one that must be right the first time.** The server
listens on the loopback interface, and loopback is not private on a
shared machine - any other process, and any other user account on the
same host, can reach 127.0.0.1. Brian works on cluster login nodes.
Retrofitting authentication onto a working interface is the change
that gets deferred, so it is tested before there is anything to
protect. Concern #309.

The window itself is not tested. `pywebview` resolves its backend
inside `start()`, which blocks until the window closes, and there is
no honest way to exercise that from a test process. Saying so is
better than a test that passes without touching it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.context import existing_corpus
from kennis.engine.corpus.collection import Collection
from kennis.gui.app import build_app
from kennis.gui.serve import ANY_PORT, HOST
from kennis.gui.theme import CSS_COLOURS, css_variables
from kennis.render.theme import ANSI_COLOURS, ROLES

TOKEN = "a-test-token"


@pytest.fixture
def client() -> TestClient:
    """A client that does *not* follow redirects or carry the token.

    Both defaults matter: a test that silently followed a redirect to a
    login page would report 200 for a request that was refused.
    """
    return TestClient(build_app(TOKEN), follow_redirects=False)


# ---------------------------------------------------------------------------
# The token
# ---------------------------------------------------------------------------


def test_a_request_without_the_token_is_refused(client: TestClient):
    assert client.get("/").status_code == 401


def test_a_request_with_the_wrong_token_is_refused(client: TestClient):
    assert client.get("/", params={"token": "not-it"}).status_code == 401


def test_the_token_admits_and_is_remembered(client: TestClient):
    """It arrives once in the URL and is held in a cookie afterwards, so
    it is not on every subsequent request line."""
    first = client.get("/", params={"token": TOKEN})

    assert first.status_code == 200
    assert client.get("/").status_code == 200


def test_every_route_is_guarded_not_just_the_page(client: TestClient):
    """The check is middleware rather than a decorator per route,
    because a route added in unit 9c must not be able to forget it.

    A static asset is the case that would be missed: it is not written
    by hand, so it is not where anyone looks for a guard.
    """
    for path in ("/", "/static/kennis.css", "/does-not-exist"):
        assert client.get(path).status_code == 401, path


def test_the_guard_does_not_redirect_to_somewhere_unguarded(client: TestClient):
    """A refusal that redirects is a refusal a client follows."""
    refused = client.get("/")

    assert refused.status_code == 401
    assert "location" not in {key.lower() for key in refused.headers}


# ---------------------------------------------------------------------------
# The theme
# ---------------------------------------------------------------------------


def test_every_semantic_role_becomes_a_css_variable():
    """Exhaustive over the registry, so adding a role and not styling it
    fails here rather than rendering as unstyled text.

    The same property that makes `render/diagnostics.py`'s match worth
    having: the check is against the source of truth, not a list
    written beside it.
    """
    emitted = css_variables()

    for name in ROLES:
        assert f"--role-{name}:" in emitted, name


def test_the_adapter_transliterates_and_does_not_choose():
    """`render/theme.py` declares the palette and this adapts it. A
    colour chosen here is the drift the roles exist to prevent.

    So the property is not "the value is a colour" but "the value is
    *this role's* colour, spelled the way CSS spells it" - which a
    wrong-but-plausible mapping fails and a rule about colours in
    general would not.
    """
    emitted = dict(_variables_of(css_variables()))

    for name, role in ROLES.items():
        expected = CSS_COLOURS[role.colour] if role.colour else "inherit"
        assert emitted[f"--role-{name}"] == expected, name


def test_every_ansi_colour_the_registry_may_name_has_a_css_name():
    """The registry's colour set is the source of truth. A colour added
    there with no name here would emit `bright_black` or similar into a
    stylesheet, which no browser understands - so the text renders
    unstyled and nothing says a colour was lost."""
    assert not set(ANSI_COLOURS) - set(CSS_COLOURS)


def _variables_of(block: str) -> list[tuple[str, str]]:
    """`--name: value;` lines, as pairs."""
    pairs: list[tuple[str, str]] = []
    for line in block.splitlines():
        if "--role-" not in line:
            continue
        name, value = line.split(":", 1)
        pairs.append((name.strip(), value.strip().rstrip(";")))
    return pairs


def test_the_stylesheet_is_served_and_carries_the_variables(client: TestClient):
    client.get("/", params={"token": TOKEN})

    served = client.get("/static/kennis.css")

    assert served.status_code == 200
    assert "--role-error:" in served.text


# ---------------------------------------------------------------------------
# Where it listens
# ---------------------------------------------------------------------------


def test_the_interface_binds_loopback_and_lets_the_kernel_pick_a_port():
    """Two constants, asserted rather than trusted.

    `0.0.0.0` would put a personal corpus on the network, and a fixed
    port makes the interface both collision-prone and predictable to
    find on a shared machine. Neither is a mistake anyone makes
    deliberately; both are one character from correct.

    This checks the constants, not the socket. Binding for real would
    mean starting the server, and the honest note is that this catches
    the edit rather than proving the bind - which is still worth
    having, because the edit is the failure that happens.
    """
    assert HOST == "127.0.0.1"
    assert ANY_PORT == 0


# ---------------------------------------------------------------------------
# Searching and reading
# ---------------------------------------------------------------------------


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    run = CliRunner()
    assert run.invoke(main, ["corpus", "init"]).exit_code == 0
    return tmp_path


def a_note(tmp_path: Path, name: str, body: str) -> str:
    run = CliRunner()
    source = tmp_path / "sources" / f"{name}.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(f"# {name}\n\n{body}\n", encoding="utf-8")
    assert run.invoke(main, ["corpus", "add", "-n", str(source)]).exit_code == 0
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0
    held = Collection(root=existing_corpus().corpus_root, name="notes").contents()
    return next(d.id for d in held.documents if d.frontmatter.title == name)


def admitted(app_client: TestClient) -> TestClient:
    assert app_client.get("/", params={"token": TOKEN}).status_code == 200
    return app_client


def test_a_search_finds_and_links_to_the_document(corpus: Path, client: TestClient):
    identifier = a_note(corpus, "calibration", "Antenna gains drift on long tracks.")
    admitted(client)

    found = client.get("/hits", params={"q": "antenna gains", "scope": "notes"})

    assert found.status_code == 200
    assert "calibration" in found.text
    assert f"/document/notes/{identifier}" in found.text


def test_a_search_that_matches_nothing_says_so(corpus: Path, client: TestClient):
    a_note(corpus, "calibration", "Antenna gains drift on long tracks.")
    admitted(client)

    found = client.get("/hits", params={"q": "zzzznotaword", "scope": "notes"})

    assert "No passages matched." in found.text


def test_a_scope_with_no_index_reports_the_command_that_builds_one(
    corpus: Path, client: TestClient
):
    """A failure becomes fields on the page the person is still typing
    in, not a replaced page - and it names the command, as every other
    front end does."""
    admitted(client)

    found = client.get("/hits", params={"q": "anything", "scope": "literature"})

    assert found.status_code == 200
    assert "kennis corpus index" in found.text


def test_a_mistyped_scope_is_named_rather_than_answered_emptily(
    corpus: Path, client: TestClient
):
    admitted(client)

    found = client.get("/hits", params={"q": "anything", "scope": "notez"})

    # The quotes around the name are escaped by the template, so the
    # assertion is on the parts escaping does not touch. Asserting the
    # exact sentence would fail on correct output.
    assert "no scope called" in found.text
    assert "notez" in found.text
    assert "No passages matched." not in found.text


def test_a_document_is_rendered_as_html(corpus: Path, client: TestClient):
    identifier = a_note(corpus, "calibration", "Gains **drift** on long tracks.")
    admitted(client)

    page = client.get(f"/document/notes/{identifier}")

    assert page.status_code == 200
    assert "<strong>drift</strong>" in page.text


def test_a_document_that_is_not_there_is_a_page_and_not_a_traceback(
    corpus: Path, client: TestClient
):
    admitted(client)

    page = client.get("/document/notes/notarealid")

    assert page.status_code == 404
    assert "notarealid" in page.text
    assert "kennis corpus list" in page.text


def test_a_remote_figure_is_withheld_until_it_is_asked_for(
    corpus: Path, client: TestClient
):
    """The privacy rule reaching the page: reading a paper must not
    tell its publisher, and the control appears only because there is
    something to load."""
    identifier = a_note(
        corpus, "paper", "![Refer to caption](https://arxiv.org/html/2409.1/Fig1.png)"
    )
    admitted(client)

    withheld = client.get(f"/document/notes/{identifier}")
    loaded = client.get(f"/document/notes/{identifier}", params={"images": "on"})

    assert "<img" not in withheld.text
    assert "arxiv.org" in withheld.text
    assert "Load them" in withheld.text
    assert "<img" in loaded.text


def test_the_vendored_assets_are_served_and_guarded(corpus: Path, client: TestClient):
    """Mounted rather than routed one file at a time, which is exactly
    the case a per-route guard would have missed."""
    assert client.get("/static/vendor/katex.min.css").status_code == 401

    admitted(client)
    served = client.get("/static/vendor/katex.min.css")

    assert served.status_code == 200
    assert "katex" in served.text.lower()


def test_a_hit_carries_the_same_text_as_the_command_line(
    corpus: Path, client: TestClient
):
    """Design section 20's exception, now with a third caller.

    The interface arranges a hit into elements, but the words inside
    them are `render/hits.py`'s and not its own. Compared as **whole
    lines**, for #297's reason: asserting that the page merely mentions
    the query passes for a page that composed its own headline, and an
    injection proved exactly that.
    """
    a_note(corpus, "calibration", "Calibration solves for antenna gains.")
    a_note(corpus, "baking", "A recipe for sourdough bread at home.")
    admitted(client)

    printed = CliRunner().invoke(
        main, ["search", "antenna gains", "--collection", "notes", "--snippet", "none"]
    )
    assert printed.exit_code == 0, printed.output
    served = client.get("/hits", params={"q": "antenna gains", "scope": "notes"})

    headlines = [
        line.strip()
        for line in printed.output.splitlines()
        if line.strip().startswith("[")
    ]
    assert headlines, printed.output
    for headline in headlines:
        assert headline in served.text, headline


# ---------------------------------------------------------------------------
# Browsing what is held
# ---------------------------------------------------------------------------


def test_the_holdings_page_lists_every_collection(corpus: Path, client: TestClient):
    a_note(corpus, "calibration", "Antenna gains.")
    admitted(client)

    page = client.get("/held")

    assert page.status_code == 200
    for name in ("notes", "literature", "docs"):
        assert f"/collection/{name}" in page.text
    assert "1 document" in page.text


def test_a_collection_never_indexed_is_not_called_stale(
    corpus: Path, client: TestClient
):
    """Two different states. Telling a fresh corpus its index is stale
    sends someone to rebuild an index that does not exist."""
    admitted(client)

    page = client.get("/held")

    assert "never indexed" in page.text
    assert "stale" not in page.text


def test_a_collection_lists_its_documents_with_links(corpus: Path, client: TestClient):
    identifier = a_note(corpus, "calibration", "Antenna gains.")
    admitted(client)

    page = client.get("/collection/notes")

    assert page.status_code == 200
    assert "calibration" in page.text
    assert f"/document/notes/{identifier}" in page.text


def test_documents_in_a_group_are_shown_under_it(corpus: Path, client: TestClient):
    CliRunner().invoke(
        main, ["remember", "--group", "decisions", "--title", "Solver", "Use NNLS."]
    )
    admitted(client)

    page = client.get("/collection/notes")

    assert "decisions" in page.text
    assert "Solver" in page.text


def test_an_unknown_collection_is_a_page_and_not_a_traceback(
    corpus: Path, client: TestClient
):
    admitted(client)

    page = client.get("/collection/notez")

    assert page.status_code == 404
    assert "notez" in page.text


# ---------------------------------------------------------------------------
# The view that goes stale
# ---------------------------------------------------------------------------


def test_a_page_carries_the_revision_it_was_drawn_at(corpus: Path, client: TestClient):
    """Concern #311. A window open for an hour is showing counts that
    were true when it drew them, and the corpus is a git repository
    whose head moves on every write - so the head is the page's
    timestamp in the only unit that matters."""
    a_note(corpus, "calibration", "Antenna gains.")
    admitted(client)

    page = client.get("/held")
    current = client.get("/revision").json()["revision"]

    assert current
    assert f'data-revision="{current}"' in page.text


def test_the_revision_changes_when_a_terminal_writes(corpus: Path, client: TestClient):
    """The mechanism is only worth having if it actually moves."""
    a_note(corpus, "calibration", "Antenna gains.")
    admitted(client)
    before = client.get("/revision").json()["revision"]

    a_note(corpus, "imaging", "Deconvolution.")

    assert client.get("/revision").json()["revision"] != before


def test_the_revision_is_not_readable_without_the_token(
    corpus: Path, client: TestClient
):
    """It says whether the corpus changed and when, which is not much
    but is not nothing, and a route added after the guard was written
    is exactly what middleware exists to cover."""
    assert client.get("/revision").status_code == 401


def test_a_script_cannot_be_fetched_from_outside_the_static_directory(
    corpus: Path, client: TestClient
):
    """`name` is matched against what is there rather than joined into
    a path, so a traversal names nothing."""
    admitted(client)

    assert client.get("/static/typeset.js").status_code == 200
    assert client.get("/static/..%2f..%2fapp.js").status_code in (307, 404)


def test_a_listing_says_when_it_left_documents_out(corpus: Path, client: TestClient):
    """The other half of `CollectionContents`, on the page. A listing
    that silently omits a broken document tells the reader the corpus
    is smaller than it is."""
    a_note(corpus, "calibration", "Antenna gains.")
    broken = corpus / "corpus" / "notes" / "broken.md"
    broken.write_text("---\nnot: valid\n---\n\nText.\n", encoding="utf-8")
    admitted(client)

    listing = client.get("/collection/notes")
    summary = client.get("/held")

    assert "could not be read" in listing.text
    assert "kennis corpus status" in listing.text
    assert "1 unreadable" in summary.text
