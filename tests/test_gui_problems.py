"""One place for each kind of problem, and window words for its way out.

Brian, 2026-10-16: errors "are not using the new features throughout".
Measured: four answers put a bare sentence into the bar's `#job`, and a
paper with no fetchable copy told the window's reader to use `-l` and
`--identifier`. The rule (`sketches/2026-10-16-one-place-for-a-problem.md`):
what was typed is refused in the form, with the dialog kept; work that
could not start or failed is a task on the bar, its panel open, listed in
Activity.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from bs4 import BeautifulSoup, Tag
from click.testing import CliRunner
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.engine.corpus.preview import PaperPreview
from kennis.engine.events import EventSink
from kennis.engine.literature.identifiers import PaperIdentifier
from kennis.engine.refusals import (
    AmbiguousIdentity,
    BibliographyIncomplete,
    IdentityMismatch,
    KennisOwn,
    NoArxivText,
    NoIdentity,
    NoPublisherText,
    NotAnInput,
    NothingConverted,
    Quoted,
    Refusal,
    SameContent,
    SamePage,
    SamePaper,
    SymlinkSkipped,
    UnsupportedFormat,
)
from kennis.gui import words
from kennis.gui.adding import preview_ways, shown_paper_preview
from kennis.gui.app import build_app
from kennis.gui.pages import ShownItem, ShownJob
from kennis.gui.repairs import (
    ADD_FROM_A_PDF,
    OPEN_THE_PAPER,
    SET_UNPAYWALL,
    repairs_for,
    ways_out_for,
)
from kennis.gui.responses import TEMPLATES
from kennis.render.refusals import describe_refusal, refusal_fact

TOKEN = "a-test-token"
HTMX = {"HX-Request": "true"}
STATIC = Path(__file__).parent.parent / "src" / "kennis" / "gui" / "static"


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    return tmp_path


@pytest.fixture
def app(corpus: Path) -> FastAPI:
    return build_app(TOKEN)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    opened = TestClient(app, follow_redirects=False)
    assert opened.get("/", params={"token": TOKEN}).status_code == 200
    return opened


def a_crashed_job(app: FastAPI) -> str:
    def fills_the_disk(events: EventSink) -> object:
        raise OSError(28, "No space left on device")

    job = app.state.jobs.start("add", fills_the_disk)
    assert job.done.wait(5)
    return str(job.id)


def bar_of(page: str) -> BeautifulSoup:
    start = page.index('<footer class="strip">')
    return BeautifulSoup(page[start : page.index("</footer>", start)], "html.parser")


# ---------------------------------------------------------------------------
# The bar draws its own job and nothing of the page's
# ---------------------------------------------------------------------------


def test_a_page_s_own_problem_never_reaches_the_bar(app: FastAPI, client: TestClient):
    """The search page's refusal was drawn a second time in the bar:
    `job.html` read the page's `problem` through the include."""
    a_crashed_job(app)

    bar = bar_of(client.get("/", params={"q": "antenna"}).text)

    assert "nothing to search" not in bar.get_text()


def test_on_a_job_s_own_page_the_bar_still_has_its_segment(
    app: FastAPI, client: TestClient
):
    """The page sets `inline`, which the bar's include read as its own."""
    job_id = a_crashed_job(app)

    bar = bar_of(client.get(f"/job/{job_id}").text)

    assert bar.find(class_="job-segment") is not None
    assert bar.find(attrs={"popover": True}) is not None


# ---------------------------------------------------------------------------
# What was typed is refused in the form
# ---------------------------------------------------------------------------


def test_a_pack_file_that_is_not_there_is_refused_in_the_form(client: TestClient):
    form = BeautifulSoup(client.get("/pack", headers=HTMX).text, "html.parser")
    place = form.find(id="pack-problem")
    assert isinstance(place, Tag) and place.find_parent("form") is not None

    answer = client.post("/pack", data={"path": "/nowhere/pack.ken.yml"}, headers=HTMX)

    assert answer.headers["HX-Retarget"] == "#pack-problem"
    assert answer.headers["X-Kennis-Refused"] == "true"
    assert "/nowhere/pack.ken.yml" in answer.text


# ---------------------------------------------------------------------------
# Work that could not start is a task on the bar
# ---------------------------------------------------------------------------


def test_a_context_sync_with_no_context_is_a_task_that_failed(
    app: FastAPI, client: TestClient
):
    answer = BeautifulSoup(
        client.post("/context-sync", headers=HTMX).text, "html.parser"
    )

    job = answer.find(class_="job")
    assert isinstance(job, Tag)
    assert job["data-state"] == "failed"
    assert job.has_attr("data-open"), "the reader's own action: its panel opens"
    assert job.find(attrs={"popover": True}) is not None
    recorded = app.state.jobs.get(job["data-job"])
    assert recorded is not None and recorded.kind == "context-sync"
    assert recorded.failed and recorded.done.is_set()
    activity = client.get("/activity").text
    assert f"/job/{job['data-job']}" in activity
    assert words.JOB_FAILED in activity


def test_a_task_drawn_on_a_page_load_does_not_open_itself(
    app: FastAPI, client: TestClient
):
    """Only an answer to the reader's own action opens a panel: one that
    opened on every page would hide the page behind it."""
    client.post("/context-sync", headers=HTMX)

    bar = bar_of(client.get("/").text)

    job = bar.find(class_="job")
    assert isinstance(job, Tag) and job["data-state"] == "failed"
    assert not job.has_attr("data-open")


def test_a_second_task_is_answered_by_the_running_one_with_its_panel_open(
    app: FastAPI, client: TestClient
):
    holding = threading.Event()
    running = app.state.jobs.start("index", lambda events: holding.wait(20))
    try:
        answer = BeautifulSoup(client.post("/sync", headers=HTMX).text, "html.parser")
    finally:
        holding.set()

    job = answer.find(class_="job")
    assert isinstance(job, Tag)
    assert job["data-job"] == running.id
    assert job["data-state"] == "running"
    assert job.has_attr("data-open")
    panel = job.find(attrs={"popover": True})
    assert isinstance(panel, Tag)
    assert words.BUSY_WITH_ANOTHER in panel.get_text()
    # Nothing outside the job: the bar is the job's.
    assert answer.find("p", class_="role-warning", recursive=False) is None


def test_a_domain_error_aimed_at_the_bar_becomes_a_task(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """`existing_corpus()` raises when the corpus has gone; the handler
    drew the sentence into whatever htmx aimed at, which was the bar."""
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "gone"))

    answer = BeautifulSoup(
        client.post("/index", headers=HTMX | {"HX-Target": "job"}).text,
        "html.parser",
    )

    job = answer.find(class_="job")
    assert isinstance(job, Tag) and job["data-state"] == "failed"
    assert job["data-kind"] == "index"


def test_the_page_opens_a_panel_it_is_handed_open():
    script = (STATIC / "redraws.js").read_text(encoding="utf-8")
    code = "\n".join(
        line for line in script.splitlines() if not line.strip().startswith("//")
    )

    assert ".job[data-open] [popover]" in code
    assert "showPopover()" in code


# ---------------------------------------------------------------------------
# The window's words for a refusal, and its ways out
# ---------------------------------------------------------------------------

# Written by hand: one of every refusal, so a new one is worded here too.
EVERY_REFUSAL: list[Refusal] = [
    Quoted("an exception's own words"),
    SameContent(document_id="d1"),
    SamePaper(document_id="d2"),
    SamePage(project="dp3", key="steps"),
    NoIdentity(named="/papers/a.pdf"),
    AmbiguousIdentity(named="/papers/b.pdf", kind="doi", values=("10.1/a", "10.1/b")),
    IdentityMismatch(
        named="/papers/c.pdf", kind="doi", stated="10.1/x", found=("10.1/y",)
    ),
    NoPublisherText(kind="doi", value="10.9999/a.b"),
    NoPublisherText(kind="doi", value="10.9999/a.b", asked_unpaywall=True),
    NoPublisherText(
        kind="doi",
        value="10.9999/a.b",
        asked_unpaywall=True,
        accepted_manuscript="https://repository.example/am.pdf",
    ),
    NoPublisherText(kind="bibcode", value="2020A&A...1A"),
    NoArxivText(named="2304.14157", arxiv_id="2304.14157"),
    NotAnInput(identifier="nonsense"),
    BibliographyIncomplete(name="refs.bib", citekeys=("a", "b")),
    NothingConverted(name="d.pdf", problem=None),
    SymlinkSkipped(),
    KennisOwn(),
    UnsupportedFormat(suffix=".xyz"),
]

_TERMINAL_ONLY = re.compile(r"(^|\s)(-l|--[a-z]+)\b|kennis corpus|supply that address")


@pytest.mark.parametrize("refusal", EVERY_REFUSAL, ids=lambda refusal: repr(refusal))
def test_the_window_s_words_for_a_refusal_name_no_flag(refusal: Refusal):
    assert not _TERMINAL_ONLY.search(refusal_fact(refusal)), refusal_fact(refusal)


@pytest.mark.parametrize("refusal", EVERY_REFUSAL, ids=lambda refusal: repr(refusal))
def test_the_window_and_the_terminal_state_the_same_fact(refusal: Refusal):
    """The terminal's sentence begins with the window's first clause: the
    two say the same thing happened and differ only in what to do."""
    first = re.split(r"[;.] ", refusal_fact(refusal))[0]

    assert describe_refusal(refusal).startswith(first)


def test_the_terminal_s_words_are_unchanged():
    """The command line's bytes, written by hand from before the split."""
    assert describe_refusal(NoPublisherText(kind="doi", value="10.9/a")) == (
        "kennis has no copy of the DOI '10.9/a' it can fetch; download it "
        "from https://doi.org/10.9/a and supply the document with -l and "
        "--identifier '10.9/a'. Or set literature.unpaywall_email, and "
        "kennis will look for a free, legal copy"
    )
    assert describe_refusal(NoArxivText(named="n", arxiv_id="2304.1")) == (
        "arXiv has no rendering of 'n' to fetch; supply the document with -l "
        "and --identifier '2304.1'"
    )


def link_saying(drawn: BeautifulSoup, label: str) -> Tag | None:
    for link in drawn.find_all("a"):
        if isinstance(link, Tag) and link.get_text(strip=True) == label:
            return link
    return None


def query_of(href: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(href).query)


def test_a_paper_with_no_copy_offers_its_page_and_an_add_from_a_pdf():
    ways = ways_out_for(NoPublisherText(kind="doi", value="10.9999/a#b"))
    by_label = {way.label: way for way in ways}

    page = by_label[OPEN_THE_PAPER]
    assert page.href == "https://doi.org/10.9999/a%23b"
    assert page.outside
    from_a_pdf = by_label[ADD_FROM_A_PDF]
    assert not from_a_pdf.outside
    assert urlsplit(from_a_pdf.href).path == "/add"
    assert query_of(from_a_pdf.href) == {
        "kind": ["paper"],
        "source": ["pdf"],
        "identifier": ["10.9999/a#b"],
    }
    unpaywall = by_label[SET_UNPAYWALL]
    assert unpaywall.href == "/settings#setting-literature.unpaywall_email"


def test_the_unpaywall_link_leads_to_a_field_on_the_settings_page(client: TestClient):
    (way,) = [
        way
        for way in ways_out_for(NoPublisherText(kind="doi", value="10.9/a"))
        if way.label == SET_UNPAYWALL
    ]
    page = BeautifulSoup(client.get("/settings").text, "html.parser")

    field = page.find(id=urlsplit(way.href).fragment)

    assert isinstance(field, Tag) and field.name == "input"
    assert field["name"] == "literature.unpaywall_email"


def test_unpaywall_is_offered_only_when_it_was_not_asked():
    asked = ways_out_for(
        NoPublisherText(kind="doi", value="10.9/a", asked_unpaywall=True)
    )
    bibcode = ways_out_for(NoPublisherText(kind="bibcode", value="2020A&A...1A"))

    assert SET_UNPAYWALL not in {way.label for way in asked}
    assert SET_UNPAYWALL not in {way.label for way in bibcode}


def test_an_accepted_manuscript_is_a_repair_that_adds_it():
    refusal = NoPublisherText(
        kind="doi",
        value="10.9/a",
        asked_unpaywall=True,
        accepted_manuscript="https://repository.example/am.pdf",
    )

    (repair,) = repairs_for(refusal)

    assert repair.collection == "literature"
    assert dict(repair.fields) == {
        "kind": "paper",
        "source": "pdf",
        "pdf": "https://repository.example/am.pdf",
        "identifier": "10.9/a",
    }


@pytest.mark.parametrize(
    "refusal",
    [
        NoArxivText(named="2304.14157", arxiv_id="2304.14157"),
        IdentityMismatch(
            named="/papers/c.pdf", kind="doi", stated="10.1/x", found=("10.1/y",)
        ),
    ],
    ids=["no-arxiv-text", "identity-mismatch"],
)
def test_a_paper_to_supply_by_hand_offers_an_add_from_a_pdf(refusal: Refusal):
    (way,) = [way for way in ways_out_for(refusal) if way.label == ADD_FROM_A_PDF]

    assert query_of(way.href)["source"] == ["pdf"]


def test_the_add_dialog_opens_on_the_pdf_way_in_with_the_identifier(
    client: TestClient,
):
    dialog = BeautifulSoup(
        client.get(
            "/add",
            params={"kind": "paper", "source": "pdf", "identifier": "10.9/a"},
            headers=HTMX,
        ).text,
        "html.parser",
    )

    chosen = dialog.find("input", attrs={"name": "source", "checked": True})
    assert isinstance(chosen, Tag) and chosen["value"] == "pdf"
    identifier = dialog.find("input", attrs={"name": "identifier"})
    assert isinstance(identifier, Tag) and identifier.get("value") == "10.9/a"


def test_an_item_with_ways_out_is_drawn_first_with_them():
    item = ShownItem(
        marker="!",
        name="10.9999/a.b",
        outcome="failed",
        detail=refusal_fact(NoPublisherText(kind="doi", value="10.9999/a.b")),
        ways=ways_out_for(NoPublisherText(kind="doi", value="10.9999/a.b")),
    )
    shown = ShownJob(headline="Added 0 documents", items=(item,))
    assert shown.single == (item,)

    html = TEMPLATES.get_template("job-outcome.html").render(
        {"shown": shown, "request": None}
    )
    drawn = BeautifulSoup(html, "html.parser")

    outside = link_saying(drawn, OPEN_THE_PAPER)
    assert isinstance(outside, Tag)
    assert outside["target"] == "_blank"
    assert outside["rel"] == ["noopener", "noreferrer"]
    in_the_dialog = link_saying(drawn, ADD_FROM_A_PDF)
    assert isinstance(in_the_dialog, Tag)
    assert in_the_dialog["hx-target"] == "#dialog"
    assert "-l" not in drawn.get_text()


def test_a_paper_preview_says_the_fact_and_offers_the_ways_out():
    refusal = NoPublisherText(kind="doi", value="10.9999/a.b")
    preview = PaperPreview(
        asked="10.9999/a.b",
        recognised=PaperIdentifier(kind="doi", value="10.9999/a.b"),
        refusal=refusal,
    )

    lines = shown_paper_preview(preview)
    html = TEMPLATES.get_template("forms/add-preview.html").render(
        {"lines": lines, "ways": preview_ways(preview), "request": None}
    )
    drawn = BeautifulSoup(html, "html.parser")

    assert [line.text for line in lines] == [refusal_fact(refusal)]
    assert link_saying(drawn, ADD_FROM_A_PDF) is not None
    assert "--identifier" not in drawn.get_text()


# Written by hand: every page and dialog that draws a form.
FORM_PAGES = [
    "/add",
    "/add?kind=paper",
    "/add?kind=site",
    "/add?kind=files",
    "/add?kind=group",
    "/index",
    "/sync",
    "/pack",
    "/remember",
    "/settings",
]


@pytest.mark.parametrize("route", FORM_PAGES)
def test_a_form_holding_its_own_htmx_control_passes_nothing_down(
    client: TestClient, route: str
):
    """The pack form's Browse inherited `hx-disabled-elt="find
    button[type=submit]"`, which found nothing inside itself (#430 again)."""
    page = BeautifulSoup(client.get(route, headers=HTMX).text, "html.parser")

    for form in page.find_all("form"):
        inner = [
            control
            for control in form.find_all(True)
            if control.has_attr("hx-get") or control.has_attr("hx-post")
        ]
        if inner:
            assert form.get("hx-disinherit") == "*", (route, form.get("action"))
