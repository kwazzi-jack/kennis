"""The window asks for papers kennis could not fetch (Brian, 2026-10-26).

A sync or an add that ends with papers no open copy exists for offers, in
one dialog, each paper's page - where the person may be able to download it
through their institution - and the browser's own file picker for it. Cancel
skips them all; a paper left without a file is skipped. A pack's paper so
supplied is the pack's.

Forms are submitted as the page drew them (#432).
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
from kennis.engine.corpus.add import AddOutcome, AddReport
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.schema import LiteratureFrontmatter
from kennis.engine.corpus.sync import CorpusSync
from kennis.engine.events import Outcome
from kennis.engine.refusals import NoPublisherText, Quoted, Refusal
from kennis.gui import words
from kennis.gui.app import build_app

TOKEN = "a-test-token"
HTMX = {"HX-Request": "true"}
DOI = "10.48479/bhpj-nz95"
BEHIND_A_PUBLISHER = NoPublisherText(kind="doi", value=DOI)

PACK = f"""\
kennis:
  schema_version: 1
pack:
  id: alpha
  name: n
  version: "1.0.0"
corpus:
  literature:
    - citekey: maccagniRFIMeerKAT2022
      identifier: "{DOI}"
"""


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    # A supplied DOI paper is described by doi.org, and a request through
    # the window cannot be handed a client: the registry here knows nothing.
    monkeypatch.setattr(
        "kennis.engine.corpus.add.lookup_doi_metadata",
        lambda doi, *, client=None: None,
    )
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    return build_app(TOKEN)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    opened = TestClient(app, follow_redirects=False)
    assert opened.get("/", params={"token": TOKEN}).status_code == 200
    return opened


@pytest.fixture
def installed(tmp_path: Path) -> None:
    pack = tmp_path / "pack" / "alpha.ken.yml"
    pack.parent.mkdir()
    pack.write_text(PACK, encoding="utf-8")
    runner = CliRunner()
    for arguments in (["pack", "update", str(pack)], ["pack", "install", str(pack)]):
        answered = runner.invoke(main, arguments)
        assert answered.exit_code == 0, answered.output


def a_sync(why: list[tuple[str, Refusal]]) -> CorpusSync:
    return CorpusSync(
        actions=(),
        counts={},
        deferred=(),
        copied=(),
        failed=tuple(address for address, _ in why),
        why=tuple(why),
    )


def an_add(refusal: Refusal) -> AddReport:
    return AddReport(
        outcomes=[AddOutcome(identifier=DOI, outcome=Outcome.FAILED, refusal=refusal)],
        elapsed_seconds=0.0,
    )


def outcome_of(app: FastAPI, client: TestClient, report: CorpusSync | AddReport) -> str:
    job = app.state.jobs.start("sync", lambda events: report)
    assert job.done.wait(10)
    answer = client.get(f"/job/{job.id}/outcome", headers=HTMX)
    assert answer.status_code == 200
    return answer.text


def ask_route(page: str) -> str | None:
    found = re.search(r'data-ask-route="([^"]+)"', page)
    return unescape(found.group(1)) if found else None


def the_form(page: str) -> str:
    found = re.search(r'<form[^>]*action="/supply".*?</form>', page, re.S)
    assert found, page
    return found.group(0)


def hidden_fields(form: str) -> dict[str, str]:
    sent: dict[str, str] = {}
    for control in re.findall(r'<input type="hidden"[^>]*>', form):
        name = re.search(r'name="([^"]+)"', control)
        value = re.search(r'value="([^"]*)"', control)
        assert name and value, control
        sent[name.group(1)] = unescape(value.group(1))
    return sent


def file_fields(form: str) -> list[str]:
    return re.findall(r'<input type="file" name="([^"]+)"', form)


def finished(app: FastAPI, answer_text: str) -> AddReport:
    """The report of the job a POST started, by the id its panel names."""
    found = re.search(r'data-job="([^"]+)"', answer_text)
    assert found, answer_text
    job = app.state.jobs.get(found.group(1))
    assert job is not None and job.done.wait(20)
    assert isinstance(job.result, AddReport), job.error
    return job.result


# ---------------------------------------------------------------------------
# The outcome asks
# ---------------------------------------------------------------------------


def test_a_sync_that_could_not_fetch_a_paper_asks_for_it(
    app: FastAPI, client: TestClient
):
    page = outcome_of(app, client, a_sync([(f"doi:{DOI}", BEHIND_A_PUBLISHER)]))

    route = ask_route(page)
    assert route is not None and route.startswith("/supply?")
    assert "owner=pack" in route
    # The paper is an item with its page and a way back to the dialog,
    # so closing the dialog by mistake is not the end of it.
    assert (
        f'href="https://doi.org/{DOI}" target="_blank" rel="noopener noreferrer"'
        in page
    )
    assert words.CHOOSE_THE_FILE in page


def test_a_sync_whose_papers_failed_otherwise_asks_nothing(
    app: FastAPI, client: TestClient
):
    page = outcome_of(app, client, a_sync([(f"doi:{DOI}", Quoted("no answer"))]))

    assert ask_route(page) is None


def test_an_add_that_could_not_fetch_a_paper_asks_for_it_as_the_persons(
    app: FastAPI, client: TestClient
):
    page = outcome_of(app, client, an_add(BEHIND_A_PUBLISHER))

    route = ask_route(page)
    assert route is not None and "owner=user" in route


# ---------------------------------------------------------------------------
# The dialog
# ---------------------------------------------------------------------------


def the_dialog(app: FastAPI, client: TestClient, report: CorpusSync | AddReport) -> str:
    route = ask_route(outcome_of(app, client, report))
    assert route is not None
    answer = client.get(route, headers=HTMX)
    assert answer.status_code == 200, answer.text
    return answer.text


def test_the_dialog_names_each_paper_its_page_and_a_picker(
    app: FastAPI, client: TestClient
):
    dialog = the_dialog(app, client, a_sync([(f"doi:{DOI}", BEHIND_A_PUBLISHER)]))

    assert "<dialog" in dialog
    assert DOI in dialog
    assert (
        f'href="https://doi.org/{DOI}" target="_blank" rel="noopener noreferrer"'
        in dialog
    )
    assert "institution" in dialog
    form = the_form(dialog)
    assert 'enctype="multipart/form-data"' in form
    assert len(file_fields(form)) == 1
    # Cancel closes the dialog and skips every paper.
    assert "data-close" in dialog


def test_the_dialog_without_a_script_is_a_page(app: FastAPI, client: TestClient):
    route = ask_route(
        outcome_of(app, client, a_sync([(f"doi:{DOI}", BEHIND_A_PUBLISHER)]))
    )
    assert route is not None

    answer = client.get(route)

    assert answer.status_code == 200
    # The whole window around the form, not the action dialog: every page
    # carries the corpus-changed notice's own `<dialog>`, so the action's
    # heading is what tells the two apart.
    assert 'aria-labelledby="dialog-title"' not in answer.text
    assert 'action="/supply"' in answer.text


def test_a_file_chosen_for_a_packs_paper_becomes_the_packs(
    app: FastAPI, client: TestClient, installed: None, tmp_path: Path
):
    form = the_form(
        the_dialog(app, client, a_sync([(f"doi:{DOI}", BEHIND_A_PUBLISHER)]))
    )
    [picker] = file_fields(form)

    answer = client.post(
        "/supply",
        data=hidden_fields(form),
        files={
            picker: ("maccagni.md", b"# RFI at u=0\n\nDownloaded.\n", "text/markdown")
        },
        headers=HTMX,
    )

    assert answer.status_code == 200, answer.text
    report = finished(app, answer.text)
    assert [one.outcome for one in report.outcomes] == [Outcome.ADDED]
    [paper] = (
        Collection(root=tmp_path / "corpus", name="literature").contents().documents
    )
    assert paper.frontmatter.owner == "pack:alpha"
    assert isinstance(paper.frontmatter, LiteratureFrontmatter)
    assert paper.frontmatter.bib.citekey == "maccagniRFIMeerKAT2022"


def test_a_file_chosen_after_an_add_is_the_persons(
    app: FastAPI, client: TestClient, tmp_path: Path
):
    form = the_form(the_dialog(app, client, an_add(BEHIND_A_PUBLISHER)))
    [picker] = file_fields(form)

    answer = client.post(
        "/supply",
        data=hidden_fields(form),
        files={
            picker: ("maccagni.md", b"# RFI at u=0\n\nDownloaded.\n", "text/markdown")
        },
        headers=HTMX,
    )

    report = finished(app, answer.text)
    assert [one.outcome for one in report.outcomes] == [Outcome.ADDED]
    [paper] = (
        Collection(root=tmp_path / "corpus", name="literature").contents().documents
    )
    assert paper.frontmatter.owner == "user"
    assert isinstance(paper.frontmatter, LiteratureFrontmatter)
    assert paper.frontmatter.bib.doi == DOI


def test_sending_no_file_is_answered_in_the_dialog(app: FastAPI, client: TestClient):
    form = the_form(
        the_dialog(app, client, a_sync([(f"doi:{DOI}", BEHIND_A_PUBLISHER)]))
    )

    answer = client.post("/supply", data=hidden_fields(form), headers=HTMX)

    assert answer.headers.get("HX-Retarget") == "#supply-problem"
    assert words.SUPPLY_NOTHING_CHOSEN in answer.text


# ---------------------------------------------------------------------------
# Asked once, when the job ends in front of the reader
# ---------------------------------------------------------------------------


def test_the_dialog_is_fetched_only_when_a_watched_job_finishes():
    """`finish` runs only for a job that ended while this page watched it;
    an outcome drawn later is drawn by the server and never reaches it."""
    script = (
        Path(__file__).parents[1] / "src/kennis/gui/static/progress.js"
    ).read_text(encoding="utf-8")
    code = "\n".join(
        line for line in script.splitlines() if not line.strip().startswith("//")
    )
    finish = code[code.index("function finish()") :]
    assert "data-ask-route" in finish
    assert "data-ask-route" not in code[: code.index("function finish()")]
