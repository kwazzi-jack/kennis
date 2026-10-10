"""Unit 11e: a refusal that needs a choice, made a choice a reader can make.

Each candidate links to its own page, opened where kennis's window cannot
be reached from it; nothing is chosen for the reader; Skip stands beside
the repair. And the repair forms post to a route that exists - since 11a
they had posted to `/manage/add`, which answers 404, and the test meant
to prove a repair repairs posted its own fields to `/add` instead of
reading the form the page drew.
"""

from __future__ import annotations

import re
from html import unescape
from pathlib import Path

import pytest
from click.testing import CliRunner
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.context import existing_corpus
from kennis.engine.corpus.add import AddOutcome, AddReport
from kennis.engine.corpus.collection import Collection
from kennis.engine.events import Outcome
from kennis.engine.refusals import AmbiguousIdentity, NoIdentity
from kennis.gui import words
from kennis.gui.app import build_app
from kennis.gui.repairs import candidate_address

TOKEN = "a-test-token"
HTMX = {"HX-Request": "true"}


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


def outcome_of(app: FastAPI, client: TestClient, report: AddReport) -> str:
    """The outcome page of an add that came to `report`."""
    job = app.state.jobs.start("add", lambda events: report)
    assert job.done.wait(10)
    answer = client.get(f"/job/{job.id}/outcome", headers=HTMX)
    assert answer.status_code == 200
    return answer.text


def refused(refusal: NoIdentity | AmbiguousIdentity) -> AddReport:
    return AddReport(
        outcomes=[
            AddOutcome(
                identifier=getattr(refusal, "named", "x"),
                outcome=Outcome.FAILED,
                refusal=refusal,
            )
        ],
        elapsed_seconds=0.0,
    )


def forms_in(page: str) -> list[str]:
    return re.findall(r'<form class="repair"[^>]*>.*?</form>', page, re.S)


def fields_of(form: str) -> dict[str, str]:
    """What a browser would send: hidden inputs, and a checked radio."""
    sent: dict[str, str] = {}
    for control in re.findall(r"<input[^>]*>", form):
        name = re.search(r'name="([^"]+)"', control)
        value = re.search(r'value="([^"]*)"', control)
        if name is None or value is None:
            continue
        if 'type="radio"' in control and "checked" not in control:
            continue
        sent[name.group(1)] = unescape(value.group(1))
    return sent


AMBIGUOUS = AmbiguousIdentity(
    named="/tmp/paper.pdf", kind="arxiv", values=("2409.19750", "1101.1764")
)


# ---------------------------------------------------------------------------
# The repair reaches a route, and repairs
# ---------------------------------------------------------------------------


def test_a_repair_submitted_as_drawn_repairs(
    app: FastAPI, client: TestClient, tmp_path: Path
):
    """Read the form from the page and send what it sends, where it says.
    Posting hand-written fields to `/add` proved `/add` works and nothing
    about the form - which posted to a route that no longer existed."""
    source = tmp_path / "paper.md"
    source.write_text("# A paper\n\nWith no identifier.\n", encoding="utf-8")
    page = outcome_of(app, client, refused(NoIdentity(named=str(source))))

    forms = forms_in(page)
    assert forms, page
    form = forms[0]
    route = re.search(r'hx-post="([^"]+)"', form)
    assert route, form
    answer = client.post(route.group(1), data=fields_of(form), headers=HTMX)

    assert answer.status_code == 200, answer.text
    job = re.search(r'data-job="([^"]+)"', answer.text)
    assert job, answer.text
    assert app.state.jobs.get(job.group(1)).done.wait(20)
    assert (
        Collection(root=existing_corpus().corpus_root, name="notes")
        .contents()
        .documents
    )


def test_every_repair_form_posts_to_the_add_route_with_and_without_a_script(
    app: FastAPI, client: TestClient
):
    page = outcome_of(app, client, refused(AMBIGUOUS))

    for form in forms_in(page):
        head = re.match(r"<form[^>]*>", form)
        assert head
        assert 'hx-post="/add"' in head.group(0)
        assert 'action="/add"' in head.group(0)
        assert 'method="post"' in head.group(0)
        assert 'hx-disabled-elt="find button[type=submit]"' in head.group(0)


# ---------------------------------------------------------------------------
# A choice, left to the reader
# ---------------------------------------------------------------------------


def test_no_candidate_is_chosen_for_the_reader(app: FastAPI, client: TestClient):
    """Choosing would be deciding which paper this is (`repairs.py`). The
    template checked the first candidate while the Python said otherwise."""
    page = outcome_of(app, client, refused(AMBIGUOUS))
    radios = re.findall(r'<input type="radio"[^>]*>', page)

    assert len(radios) == 2
    assert not any("checked" in radio for radio in radios)
    assert all("required" in radio for radio in radios)


def test_each_candidate_links_to_its_own_page(app: FastAPI, client: TestClient):
    page = outcome_of(app, client, refused(AMBIGUOUS))

    for value in AMBIGUOUS.values:
        link = re.search(
            rf'<a [^>]*href="https://arxiv\.org/abs/{re.escape(value)}"[^>]*>', page
        )
        assert link, value
        assert 'target="_blank"' in link.group(0)
        assert 'rel="noopener noreferrer"' in link.group(0)


@pytest.mark.parametrize(
    ("kind", "value", "address"),
    [
        ("arxiv", "2409.19750", "https://arxiv.org/abs/2409.19750"),
        ("doi", "10.1093/mnras/stab1234", "https://doi.org/10.1093/mnras/stab1234"),
        (
            "bibcode",
            "2021MNRAS.501.1234W",
            "https://ui.adsabs.harvard.edu/abs/2021MNRAS.501.1234W/abstract",
        ),
        # A DOI may carry characters that end a path; they are quoted, and
        # the slash that belongs to the DOI is kept.
        (
            "doi",
            "10.1002/(SICI)1097#x?y",
            "https://doi.org/10.1002/%28SICI%291097%23x%3Fy",
        ),
    ],
)
def test_a_candidate_address_is_its_registry_page(kind: str, value: str, address: str):
    assert candidate_address(kind, value) == address


# ---------------------------------------------------------------------------
# Skip
# ---------------------------------------------------------------------------


def test_skip_stands_beside_the_repairs(app: FastAPI, client: TestClient):
    page = outcome_of(app, client, refused(AMBIGUOUS))
    repairs = re.search(r'<div class="repairs">(.*?)</div>', page, re.S)

    assert repairs, page
    skip = re.search(r'<form class="skip"[^>]*>', repairs.group(1))
    assert skip, repairs.group(1)
    assert 'hx-get="/skip"' in skip.group(0)
    assert 'action="/skip"' in skip.group(0)
    assert 'hx-target="closest .repairs"' in skip.group(0)
    assert words.SKIP in repairs.group(1)


def test_skipping_says_what_it_means_and_changes_nothing(client: TestClient):
    before = existing_corpus().corpus_root
    revision = CliRunner().invoke(main, ["corpus", "log"]).output

    fragment = client.get("/skip", headers=HTMX)
    page = client.get("/skip")

    assert words.SKIPPED in fragment.text
    assert 'class="shell"' not in fragment.text
    assert words.SKIPPED in page.text
    assert 'class="shell"' in page.text
    assert CliRunner().invoke(main, ["corpus", "log"]).output == revision
    assert before.is_dir()


def test_a_refusal_with_no_repair_has_no_skip(app: FastAPI, client: TestClient):
    from kennis.engine.refusals import NoPublisherText

    report = AddReport(
        outcomes=[
            AddOutcome(
                identifier="10.1093/x",
                outcome=Outcome.FAILED,
                refusal=NoPublisherText(kind="doi", value="10.1093/x"),
            )
        ],
        elapsed_seconds=0.0,
    )

    assert '<form class="skip"' not in outcome_of(app, client, report)


# ---------------------------------------------------------------------------
# Nothing kennis serves tells another site where the reader was
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("route", ["/", "/corpus", "/add", "/static/kennis.css"])
def test_every_answer_withholds_the_referrer(client: TestClient, route: str):
    assert client.get(route).headers.get("referrer-policy") == "no-referrer"


def test_a_refusal_answer_withholds_it_too():
    """The 401 is answered by the middleware before any route; a reader
    who reached it from a stale tab still sends no referrer onward."""
    stranger = TestClient(build_app(TOKEN))

    assert stranger.get("/").headers.get("referrer-policy") == "no-referrer"
