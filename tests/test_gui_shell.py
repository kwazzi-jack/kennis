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
from kennis.gui import words
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


def test_the_token_admits_and_is_remembered(corpus: Path, client: TestClient):
    """It arrives once in the URL and is held in a cookie afterwards, so
    it is not on every subsequent request line.

    **It takes a corpus because the page it asks for reads one.** It
    did not, and so it resolved the default location and read the
    developer's own corpus - passing here and failing on all four CI
    platforms at once. Concern #361."""
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
        if role.colour:
            expected = CSS_COLOURS[role.colour]
        elif role.dim:
            # Dim is a terminal attribute and a browser has none, so
            # the adapter translates it to the muted grey rather than
            # transliterating it away. Concern #351.
            expected = CSS_COLOURS["bright_black"]
        else:
            # Not `inherit`: on a custom property at `:root` that is
            # the guaranteed-invalid value, and `color: var(...)`
            # then fell back to full ink.
            expected = "currentColor"
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


def test_the_stylesheet_is_served_and_carries_the_variables(
    corpus: Path, client: TestClient
):
    """The corpus is for the request that plants the token, not for
    the stylesheet, which needs none. Concern #361."""
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

    assert words.NOTHING_FOUND in found.text


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


def test_the_margin_carries_every_field_the_command_line_prints(
    corpus: Path, client: TestClient
):
    """The margin lays the fields out itself since #380, so the joined
    line no longer appears on the page and the test above cannot see
    them. Each field still has to be the same bytes, and each has to
    be in an element of its own - a gutter twenty characters wide
    wrapped `meaning:` away from `medium` when they shared one."""
    a_note(corpus, "calibration", "Calibration solves for antenna gains.")
    admitted(client)

    printed = CliRunner().invoke(
        main, ["search", "antenna gains", "--collection", "notes", "--snippet", "none"]
    )
    assert printed.exit_code == 0, printed.output
    served = client.get("/hits", params={"q": "antenna gains", "scope": "notes"})

    # The command line's own detail line, which is the fields joined
    # by two spaces. Recognised by the handle it ends with rather than
    # by a band, because a lexical-only corpus prints one band and a
    # hybrid one prints two.
    lines = [
        line.strip()
        for line in printed.output.splitlines()
        if "id=" in line and "chunk=" in line
    ]
    assert lines, printed.output
    for line in lines:
        fields = line.split("  ")
        assert len(fields) >= 2, line
        for field in fields:
            assert f"<span>{field}</span>" in served.text, field


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


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def test_a_note_written_from_the_page_reaches_the_corpus(
    corpus: Path, client: TestClient
):
    admitted(client)

    answer = client.post("/remember", data={"text": "Use NNLS for the solver."})

    assert answer.status_code == 200
    assert "Remembered" in answer.text
    held = Collection(root=existing_corpus().corpus_root, name="notes").contents()
    assert any("NNLS" in d.body for d in held.documents)


def test_the_write_is_committed(corpus: Path, client: TestClient):
    """The corpus is kennis's own repository. A write that never
    reaches git is one `corpus history` cannot show."""
    import subprocess

    def commits() -> int:
        done = subprocess.run(
            ["git", "rev-list", "--count", "--all"],
            cwd=corpus / "corpus",
            capture_output=True,
            text=True,
            check=True,
            stdin=subprocess.DEVNULL,
        )
        return int(done.stdout.strip())

    admitted(client)
    before = commits()

    client.post("/remember", data={"text": "Phase-only first, then amplitude."})

    assert commits() == before + 1


def test_writing_is_refused_without_the_token(corpus: Path, client: TestClient):
    """A write is exactly the request the guard exists for, and a POST
    route added after the middleware was written is what middleware
    exists to cover."""
    answer = client.post("/remember", data={"text": "Should not be written."})

    assert answer.status_code == 401
    held = Collection(root=existing_corpus().corpus_root, name="notes").contents()
    assert not held.documents


def test_the_cookie_is_not_sent_across_sites(corpus: Path, client: TestClient):
    """Cross-site protection here is `samesite=strict` on the token
    cookie, set in unit 9a for a different reason. It is asserted
    rather than commented because protection that falls out of
    something else is the kind that gets removed.
    """
    admitted(client)

    setting = client.get("/", params={"token": TOKEN}).headers.get("set-cookie", "")

    assert "samesite=strict" in setting.lower()
    assert "httponly" in setting.lower()


def test_writing_nothing_is_refused_by_the_page_not_by_the_engine(
    corpus: Path, client: TestClient
):
    """Both refuse empty text and they say nearly the same words, so
    asserting the words proves nothing about which one acted - the
    first version of this test passed with the page's own guard
    removed.

    The difference is what they offer next. The engine's refusal
    carries `kennis remember --help`, which is a command-line answer
    to someone looking at a textarea, so the page answers first and
    offers no command.
    """
    admitted(client)

    answer = client.post("/remember", data={"text": "   \n  "})

    assert "nothing to remember" in answer.text.lower()
    assert "role-warning" in answer.text
    assert "kennis remember" not in answer.text
    held = Collection(root=existing_corpus().corpus_root, name="notes").contents()
    assert not held.documents


def test_a_get_cannot_write(corpus: Path, client: TestClient):
    """The writing route is POST only. A GET that writes is a GET
    something will follow - a prefetcher, a link checker, a restored
    history entry - and each would write a note nobody asked for."""
    admitted(client)

    form = client.get("/remember", params={"text": "Written by a prefetcher."})

    assert form.status_code == 200
    held = Collection(root=existing_corpus().corpus_root, name="notes").contents()
    assert not held.documents


def test_saying_the_same_thing_twice_is_reported_as_already_known(
    corpus: Path, client: TestClient
):
    admitted(client)
    client.post("/remember", data={"text": "Weighting is Briggs with robust zero."})

    again = client.post(
        "/remember", data={"text": "Weighting is Briggs with robust zero."}
    )

    assert "already remembered" in again.text.lower()
    held = Collection(root=existing_corpus().corpus_root, name="notes").contents()
    assert len(held.documents) == 1


def test_a_busy_corpus_is_a_state_to_retry_from(corpus: Path, client: TestClient):
    """The lock is `timeout=0`, so a `corpus index` in a terminal
    refuses this write. Losing what someone typed is worse than making
    them press the button again, so it is an outcome and not an error
    page. Concern #167 is about this lock."""
    from kennis.engine.locking import corpus_lock

    admitted(client)

    with corpus_lock(corpus / "corpus"):
        answer = client.post("/remember", data={"text": "Written while busy."})

    assert answer.status_code == 200
    assert "busy" in answer.text.lower()


def test_writing_to_a_project_with_no_bundle_is_refused_not_redirected(
    corpus: Path, client: TestClient
):
    """Recording a project decision somewhere machine-global and
    reporting success is worse than not recording it."""
    admitted(client)

    answer = client.post(
        "/remember",
        data={"text": "This project images in 2 GHz sub-bands.", "target": "context"},
    )

    assert "context" in answer.text.lower()
    held = Collection(root=existing_corpus().corpus_root, name="notes").contents()
    assert not held.documents


# ---------------------------------------------------------------------------
# What a missing window backend looks like
# ---------------------------------------------------------------------------


def test_the_backend_probe_tracebacks_are_dropped_and_nothing_else_is():
    """On Linux with neither GTK nor Qt bindings, pywebview logs a
    full traceback per backend it tried before raising. kennis handles
    that and opens a browser, so the tracebacks make a handled
    fallback read as a crash - which is what it did when Brian first
    ran it.

    A filter on the message, not a silenced logger: silencing
    `pywebview` for the duration would also hide anything going wrong
    in a window that *did* open, which is the case someone would
    actually need to see. So the test asserts both halves.
    """
    import logging

    from kennis.gui.serve import _DropsBackendProbes

    dropping = _DropsBackendProbes()

    def record(message: str) -> logging.LogRecord:
        return logging.LogRecord(
            "pywebview", logging.ERROR, __file__, 1, message, None, None
        )

    assert not dropping.filter(record("GTK cannot be loaded"))
    assert not dropping.filter(record("QT cannot be loaded"))
    # Everything else still reaches the person running it.
    assert dropping.filter(record("the window crashed"))
    assert dropping.filter(record("failed to render the page"))


def test_the_browser_fallback_is_announced(
    corpus: Path, monkeypatch: pytest.MonkeyPatch
):
    """A browser tab appearing where a window was asked for needs
    saying, or it reads as the wrong thing happening silently."""
    import kennis.gui.serve as serving

    said: list[str] = []
    monkeypatch.setattr(serving, "_shown_in_a_window", lambda url: False)
    monkeypatch.setattr(serving.webbrowser, "open", lambda url: True)
    monkeypatch.setattr(serving, "_wait_until_interrupted", lambda: None)

    serving.run(lambda url: None, on_no_window=lambda: said.append("no window"))

    assert said == ["no window"]


def test_a_window_that_opens_is_not_announced_as_a_fallback(
    corpus: Path, monkeypatch: pytest.MonkeyPatch
):
    """The other side, so the test above cannot pass by announcing
    always."""
    import kennis.gui.serve as serving

    said: list[str] = []
    monkeypatch.setattr(serving, "_shown_in_a_window", lambda url: True)
    monkeypatch.setattr(serving.webbrowser, "open", lambda url: True)
    monkeypatch.setattr(serving, "_wait_until_interrupted", lambda: None)

    serving.run(lambda url: None, on_no_window=lambda: said.append("no window"))

    assert said == []
