"""Unit 11d: adding, one kind at a time.

Four tabs, each with only its own fields, each field saying whether it is
required and what an empty one becomes; a preview of what the add would
do; one block per group; and a chooser that lists the computer kennis
runs on, because that is the computer `corpus add` reads from (#420).
"""

from __future__ import annotations

import io
import re
import tempfile
import time
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from urllib.parse import unquote

import pytest
from bs4 import BeautifulSoup, Tag
from click.testing import CliRunner
from fastapi import FastAPI
from fastapi.testclient import TestClient
from markupsafe import escape

from kennis.cli.__main__ import main
from kennis.engine.corpus.add import AddOptions, AddReport
from kennis.engine.corpus.intake import convert_local_file, uploaded_as
from kennis.engine.events import EventSink
from kennis.engine.literature.metadata import ArxivMetadata
from kennis.engine.settings import load_settings
from kennis.gui import words
from kennis.gui.app import build_app
from kennis.gui.icons import icon
from kennis.gui.responses import TEMPLATES
from kennis.gui.uploads import staged

TOKEN = "a-test-token"
HTMX = {"HX-Request": "true"}
STATIC = Path(__file__).parent.parent / "src" / "kennis" / "gui" / "static"

# Written by hand: the four kinds, in the order offered (#373).
EXPECTED_TABS = [
    ("paper", "Paper"),
    ("site", "Documentation site"),
    ("file", "Files"),
    ("group", "Several at once"),
]


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


type AddCall = tuple[str, tuple[str, ...], AddOptions]


@pytest.fixture
def adds(monkeypatch: pytest.MonkeyPatch) -> list[AddCall]:
    """Every add the window asks for, recorded instead of run."""
    calls: list[AddCall] = []

    def recorded(
        context: object,
        destination: str,
        identifiers: list[str] | tuple[str, ...],
        options: AddOptions,
        *,
        events: EventSink | None = None,
        restored: object = None,
    ) -> AddReport:
        calls.append((destination, tuple(identifiers), options))
        return AddReport(outcomes=[], elapsed_seconds=0.0)

    monkeypatch.setattr("kennis.gui.routes.add.add_documents", recorded)
    monkeypatch.setattr("kennis.operations.add_documents", recorded)
    return calls


def finished(app: FastAPI) -> None:
    for job in app.state.jobs.recent():
        assert job.done.wait(10)


def dialog_of(client: TestClient, kind: str) -> str:
    answer = client.get("/add", params={"kind": kind}, headers=HTMX)
    assert answer.status_code == 200
    return answer.text


def code_of(name: str) -> str:
    script = (STATIC / name).read_text(encoding="utf-8")
    return "\n".join(
        line for line in script.splitlines() if not line.strip().startswith("//")
    )


# ---------------------------------------------------------------------------
# Four tabs
# ---------------------------------------------------------------------------


def test_the_tabs_are_the_four_kinds_in_order():
    assert list(words.ADD_TABS) == EXPECTED_TABS


@pytest.mark.parametrize(("kind", "label"), EXPECTED_TABS)
def test_each_tab_links_every_tab_and_marks_its_own(
    client: TestClient, kind: str, label: str
):
    dialog = BeautifulSoup(dialog_of(client, kind), "html.parser")
    tabs = dialog.select("a.tab")

    assert [tab.get_text(strip=True) for tab in tabs] == [
        text for _, text in EXPECTED_TABS
    ]
    current = [
        tab.get_text(strip=True) for tab in tabs if tab.get("aria-current") == "page"
    ]
    assert current == [label]
    for tab, (other, _) in zip(tabs, EXPECTED_TABS, strict=True):
        assert tab["href"] == f"/add?kind={other}"


def test_a_tab_without_a_script_is_a_page(client: TestClient):
    page = client.get("/add", params={"kind": "site"}).text

    assert 'class="shell"' in page
    assert words.ADD_PREAMBLES["site"] in page


def test_an_unknown_kind_is_the_paper_tab(client: TestClient):
    """Not a refusal: a tab is a link, and the worst a bad one can do is
    open the first tab."""
    assert words.ADD_PREAMBLES["paper"] in dialog_of(client, "poster")


# Written by hand: which fields each tab cannot do without. A block's
# fields are all required, because a block with lines needs every one.
REQUIRED_FIELDS = {
    # One of the two is needed where the picker sits beside the field: a
    # path or identifier typed, or a file chosen. The Paper tab needs the
    # field of the way in chosen.
    "paper": {"source", "identifiers", "pdf"},
    "site": {"identifiers"},
    "file": {"identifiers", "collection"},
    "group": {
        "group-1",
        "collection-1",
        "lines-1",
        "group-2",
        "collection-2",
        "lines-2",
    },
}


# Which of `words.EMPTY_MEANS` each tab's optional fields say, written by
# hand (#373); `group` is `words.group_empty_means`, which reads the settings.
EMPTY_MEANS_OF = {
    "paper": {"identifier": "identifier", "title": "title", "citekey": "citekey"},
    "site": {
        "project": "project",
        "version": "version",
        "refresh": "refresh",
        "max_pages": "max_pages",
        "max_depth": "max_depth",
    },
    "file": {
        "title": "file_title",
        "project": "file_project",
        "version": "file_version",
    },
    "group": {},
}


def empty_means_of(kind: str, field: str) -> str:
    if field == "group":
        return words.group_empty_means(load_settings().corpus.default_group)
    return words.EMPTY_MEANS[EMPTY_MEANS_OF[kind][field]]


@pytest.mark.parametrize("kind", [kind for kind, _ in EXPECTED_TABS])
def test_every_field_says_whether_it_is_needed_and_what_empty_means(
    client: TestClient, kind: str
):
    """The right one of the two, not merely one of them: a form calling
    every field required passes a check that each says something. What
    empty becomes is the field's own placeholder, worded as its default,
    so it takes no line of its own."""
    dialog = dialog_of(client, kind)
    rows = re.findall(r'<div class="field"[^>]*>(.*?)</div>', dialog, re.S)

    assert rows, dialog
    for row in rows:
        # The field's own name, not the picker's beside it.
        name = re.search(r'name="(?!upload")([^"]+)"', row)
        assert name, row
        need = re.search(r'<span class="need">([^<]+)</span>', row)
        assert need, row
        expected = (
            words.REQUIRED if name.group(1) in REQUIRED_FIELDS[kind] else words.OPTIONAL
        )
        assert need.group(1) == expected, row
        if expected == words.OPTIONAL:
            checkbox = re.search(
                rf'<input id="add-{name.group(1)}" type="checkbox"[^>]*>'
                r'<span class="role-muted">([^<]*)</span>',
                row,
            )
            control = re.search(
                rf'<input id="add-{name.group(1)}" type="(?:text|number)"[^>]*>', row
            )
            # A checkbox has no placeholder: what unticked means is beside it.
            placeholder = (
                re.search(r'placeholder="([^"]*)"', control.group(0))
                if control
                else checkbox
            )
            assert placeholder, row
            said = unescape(placeholder.group(1))
            assert said.startswith(words.EMPTY_PREFIX), row
            assert empty_means_of(kind, name.group(1)) in said, row


@pytest.mark.parametrize(
    ("kind", "fields"),
    [
        (
            "paper",
            {
                "source",
                "identifiers",
                "pdf",
                "upload",
                "identifier",
                "title",
                "citekey",
                "group",
            },
        ),
        (
            "site",
            {"identifiers", "project", "version", "refresh", "max_pages", "max_depth"},
        ),
        (
            "file",
            {
                "identifiers",
                "upload",
                "collection",
                "title",
                "group",
                "project",
                "version",
            },
        ),
    ],
)
def test_each_tab_asks_only_its_own_fields(
    client: TestClient, kind: str, fields: set[str]
):
    dialog = dialog_of(client, kind)
    named = set(re.findall(r'<(?:input|textarea)[^>]*\bname="([^"]+)"', dialog))

    # Hidden bookkeeping rather than fields: the kind, a fixed collection,
    # and what the Paper preview filled in.
    bookkeeping = {"kind", "collection", "prefilled-title", "prefilled-citekey"}
    assert named - bookkeeping == fields - {"collection"}


# ---------------------------------------------------------------------------
# What each tab sends
# ---------------------------------------------------------------------------


def test_a_paper_goes_to_literature_with_its_own_fields(
    app: FastAPI, client: TestClient, adds: list[AddCall]
):
    client.post(
        "/add",
        data={
            "kind": "paper",
            "collection": "literature",
            "identifiers": "2409.19750",
            "citekey": "mine2024",
            "title": "",
        },
        headers=HTMX,
    )
    finished(app)

    assert len(adds) == 1
    destination, identifiers, options = adds[0]
    assert destination == "literature"
    assert identifiers == ("2409.19750",)
    assert options.citekey == "mine2024"
    assert options.title is None


def test_a_site_carries_its_limits(
    app: FastAPI, client: TestClient, adds: list[AddCall]
):
    client.post(
        "/add",
        data={
            "kind": "site",
            "collection": "docs",
            "identifiers": "https://stimela.readthedocs.io/en/latest/",
            "max_pages": "40",
            "max_depth": "",
        },
        headers=HTMX,
    )
    finished(app)

    destination, _, options = adds[0]
    assert destination == "docs"
    assert options.max_pages == 40
    assert options.max_depth == AddOptions().max_depth


def test_a_limit_that_is_not_a_number_is_refused(
    client: TestClient, adds: list[AddCall]
):
    refused = client.post(
        "/add",
        data={
            "kind": "site",
            "collection": "docs",
            "identifiers": "https://stimela.readthedocs.io/",
            "max_pages": "lots",
        },
        headers=HTMX,
    )

    assert adds == []
    sentence = words.not_a_count(words.FIELD_LABELS["max_pages"], "lots")
    assert escape(sentence) in refused.text


def test_several_groups_are_one_job_and_an_add_per_group(
    app: FastAPI, client: TestClient, adds: list[AddCall]
):
    client.post(
        "/add",
        data={
            "kind": "group",
            "group-1": "calibration",
            "collection-1": "literature",
            "lines-1": "2409.19750\n\n2409.19751\n",
            "group-2": "imaging",
            "collection-2": "notes",
            "lines-2": "/tmp/a.md",
            "group-3": "",
            "collection-3": "notes",
            "lines-3": "",
        },
        headers=HTMX,
    )
    finished(app)

    assert [(call[0], call[1], call[2].group) for call in adds] == [
        ("literature", ("2409.19750", "2409.19751"), "calibration"),
        ("notes", ("/tmp/a.md",), "imaging"),
    ]
    assert len(app.state.jobs.recent()) == 1


def test_a_group_with_lines_needs_a_name(client: TestClient, adds: list[AddCall]):
    refused = client.post(
        "/add",
        data={
            "kind": "group",
            "group-1": "",
            "collection-1": "notes",
            "lines-1": "/tmp/a.md",
        },
        headers=HTMX,
    )

    assert adds == []
    assert words.GROUP_NEEDS_A_NAME in refused.text


def test_several_groups_with_nothing_in_them_is_nothing_to_add(
    client: TestClient, adds: list[AddCall]
):
    refused = client.post(
        "/add",
        data={"kind": "group", "group-1": "x", "collection-1": "notes", "lines-1": ""},
        headers=HTMX,
    )

    assert adds == []
    assert words.NOTHING_TO_ADD in refused.text


def test_another_group_adds_a_block_and_a_button_for_the_next(client: TestClient):
    block = client.get("/add/block", params={"index": 3}, headers=HTMX).text

    assert 'name="group-3"' in block
    assert 'name="lines-3"' in block
    assert 'hx-get="/add/block?index=4"' in block
    assert 'name="group-2"' not in block


def test_the_group_tab_draws_two_blocks_to_start(client: TestClient):
    dialog = dialog_of(client, "group")

    assert 'name="lines-1"' in dialog and 'name="lines-2"' in dialog
    assert 'name="lines-3"' not in dialog


# ---------------------------------------------------------------------------
# The preview
# ---------------------------------------------------------------------------


@pytest.fixture
def lookups(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    asked: list[str] = []

    def answered(arxiv_id: str, *, client: object = None) -> ArxivMetadata:
        asked.append(arxiv_id)
        return ArxivMetadata(
            title="A Paper About Calibration", authors="Brian Welman", year="2024"
        )

    monkeypatch.setattr("kennis.engine.corpus.preview.lookup_arxiv_metadata", answered)
    return asked


def test_the_paper_field_asks_for_a_preview_as_it_is_typed(client: TestClient):
    dialog = dialog_of(client, "paper")
    field = re.search(r'<input[^>]*name="identifiers"[^>]*>', dialog)

    assert field, dialog
    assert 'hx-get="/add/preview/paper"' in field.group(0)
    assert "delay:" in field.group(0)


def test_a_preview_names_the_paper_and_its_citekey(
    client: TestClient, lookups: list[str]
):
    shown = client.get(
        "/add/preview/paper", params={"identifiers": "2409.19750"}, headers=HTMX
    ).text

    assert lookups == ["2409.19750"]
    assert "A Paper About Calibration" in shown
    assert "welmanPaperAboutCalibration2024" in shown


def test_a_partial_identifier_asks_nobody(client: TestClient, lookups: list[str]):
    for typed in ("2", "2409", "2409.1975"):
        client.get("/add/preview/paper", params={"identifiers": typed}, headers=HTMX)

    assert lookups == []


def test_a_doi_alone_is_told_what_the_add_would_say(
    client: TestClient, lookups: list[str]
):
    from kennis.engine.refusals import NoPublisherText
    from kennis.render.refusals import refusal_fact

    shown = client.get(
        "/add/preview/paper",
        params={"identifiers": "10.1093/mnras/stab1234"},
        headers=HTMX,
    ).text

    # The window's words for it, as the add's outcome has them (#475).
    sentence = refusal_fact(NoPublisherText(kind="doi", value="10.1093/mnras/stab1234"))
    assert re.sub(r"\s+", " ", sentence) in re.sub(
        r"\s+", " ", shown.replace("&#39;", "'")
    )
    assert lookups == []


def test_a_site_preview_names_the_project_and_probes_only_on_request(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    probed: list[str] = []

    def probe(client: object, base_url: str) -> str:
        probed.append(base_url)
        return "sitemap"

    monkeypatch.setattr("kennis.engine.corpus.preview.discovery_mode", probe)

    named = client.get(
        "/add/preview/site",
        params={"identifiers": "https://stimela.readthedocs.io/"},
        headers=HTMX,
    ).text
    assert "stimela" in named
    assert probed == []

    checked = client.get(
        "/add/preview/site",
        params={"identifiers": "https://stimela.readthedocs.io/", "probe": "1"},
        headers=HTMX,
    ).text
    assert probed == ["https://stimela.readthedocs.io/"]
    assert words.DISCOVERY_WORDS["sitemap"] in checked


def test_each_line_of_a_group_is_checked(client: TestClient, tmp_path: Path):
    document = tmp_path / "one.md"
    document.write_text("# One\n", encoding="utf-8")

    shown = client.get(
        "/add/check",
        params={
            "index": "2",
            "collection-2": "notes",
            "lines-2": f"{document}\nnot a thing\n2409.19750",
        },
        headers=HTMX,
    ).text
    rows = re.findall(r"<li[^>]*>(.*?)</li>", shown, re.S)

    assert len(rows) == 3
    assert words.LINE_KINDS["file"] in rows[0]
    assert words.LINE_KINDS["nothing"] in rows[1]
    assert words.LINE_KINDS["arxiv"] in rows[2]


# ---------------------------------------------------------------------------
# The chooser
# ---------------------------------------------------------------------------


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    place = tmp_path / "home"
    (place / "Papers").mkdir(parents=True)
    (place / "alpha").mkdir()
    (place / ".secret").mkdir()
    (place / "notes.md").write_text("x", encoding="utf-8")
    (place / "Zeta.pdf").write_bytes(b"%PDF")
    (place / ".hidden.md").write_text("x", encoding="utf-8")
    monkeypatch.setenv("HOME", str(place))
    # Where `Path.home()` looks on Windows; HOME alone moved nothing there.
    monkeypatch.setenv("USERPROFILE", str(place))
    return place


def entries_of(listing: str) -> list[str]:
    return re.findall(
        r'class="entry[^"]*"[^>]*>(?:<svg.*?</svg>)?([^<]+)<', listing, re.S
    )


def test_the_chooser_starts_at_home_folders_first_and_hides_dotfiles(
    client: TestClient, home: Path
):
    listing = client.get("/browse", params={"target": "identifiers"}, headers=HTMX).text

    assert str(home) in listing
    assert entries_of(listing) == ["alpha", "Papers", "notes.md", "Zeta.pdf"]


def test_a_file_is_chosen_by_its_whole_path(client: TestClient, home: Path):
    listing = client.get("/browse", params={"target": "identifiers"}, headers=HTMX).text

    assert f'data-choose="{home / "Zeta.pdf"}"' in listing


def test_a_folder_opens_rather_than_being_chosen_unless_asked(
    client: TestClient, home: Path
):
    listing = client.get(
        "/browse", params={"target": "identifiers", "folders": "1"}, headers=HTMX
    ).text

    assert f'data-choose="{home}"' in listing
    # Decoded whole, not `%2F` alone: a Windows path in the address has
    # its backslashes and drive colon encoded too.
    assert f"path={home / 'Papers'}" in unquote(listing)


def test_the_chooser_reads_names_and_never_contents(client: TestClient, home: Path):
    (home / "notes.md").write_text("A SENTENCE INSIDE THE FILE", encoding="utf-8")

    listing = client.get("/browse", params={"target": "identifiers"}, headers=HTMX).text

    assert "A SENTENCE INSIDE THE FILE" not in listing


def test_a_path_that_is_not_a_folder_is_said(client: TestClient, home: Path):
    listing = client.get(
        "/browse",
        params={"target": "identifiers", "path": str(home / "notes.md")},
        headers=HTMX,
    ).text

    assert escape(words.not_a_folder(str(home / "notes.md"))) in listing


def test_the_chooser_answers_only_with_the_token(corpus: Path, home: Path):
    stranger = TestClient(build_app(TOKEN))

    assert stranger.get("/browse").status_code == 401


def test_a_target_is_only_a_field_kennis_drew(client: TestClient, home: Path):
    """The target names the input the path is written into, and it is
    echoed into an attribute; only the names the forms use are taken."""
    listing = client.get("/browse", params={"target": '"><script>'}, headers=HTMX)

    assert listing.status_code == 400


def test_a_field_that_takes_files_offers_the_browsers_own_picker(
    client: TestClient,
):
    """The native dialog of the computer the reader sits at, sent with the
    form: the Browse list showed the computer kennis runs on, and asked
    for a path to be found in it."""
    for kind in ("paper", "file"):
        dialog = dialog_of(client, kind)
        assert re.search(r'<input type="file" name="upload" multiple', dialog), kind
        assert 'enctype="multipart/form-data"' in dialog, kind
        assert "/browse?target=identifiers" not in dialog, kind
    assert "webkitdirectory" in dialog_of(client, "file")
    assert "webkitdirectory" not in dialog_of(client, "paper")


def test_a_group_block_still_browses_the_computer_kennis_runs_on(
    client: TestClient,
):
    group = dialog_of(client, "group")
    assert 'hx-get="/browse?target=lines-1' in group
    assert 'hx-get="/browse?target=lines-2' in group


def test_the_chooser_script_writes_a_path_and_composes_no_words():
    code = code_of("chooser.js")

    assert "dataset.choose" in code
    assert not re.search(r"\"[A-Za-z]+ [A-Za-z ]+\"", code)


def test_the_chooser_script_is_loaded(client: TestClient):
    assert '<script defer src="/static/chooser.js"></script>' in client.get("/").text


def test_a_job_started_from_a_tab_reports_in_the_strip(
    app: FastAPI, client: TestClient, adds: list[AddCall]
):
    started = client.post(
        "/add",
        data={"kind": "file", "collection": "notes", "identifiers": "/tmp/a.md"},
        headers=HTMX,
    )

    assert "data-job" in started.text
    time.sleep(0.05)
    finished(app)


def test_a_control_inside_the_form_does_not_inherit_its_target(client: TestClient):
    """Found walking the window: Another group, a GET from inside the
    form, inherited the form's `hx-target="#job"` and put the new block
    in the strip. The form's attributes are its own request's."""
    form = re.search(r"<form\b[^>]*>", dialog_of(client, "group"))

    assert form
    assert 'hx-disinherit="*"' in form.group(0)


def test_only_the_forms_own_post_closes_the_dialog():
    """A preview, Browse or Another group is a GET from inside the form,
    and closing the dialog on one shut it under the reader's hands."""
    code = code_of("dialog.js")

    assert 'requestConfig.verb !== "post"' in code


def test_no_collection_is_chosen_for_the_reader(client: TestClient):
    """Found walking the window: the File tab checked the first collection,
    literature, and a Markdown note was refused there for having no paper
    identifier. `corpus add` chooses none either."""
    for kind in ("file", "group"):
        dialog = dialog_of(client, kind)
        radios = re.findall(r'<input type="radio"[^>]*>', dialog)
        assert radios, kind
        assert not any("checked" in radio for radio in radios), kind


def test_an_add_with_no_collection_is_refused(client: TestClient, adds: list[AddCall]):
    refused = client.post(
        "/add", data={"kind": "file", "identifiers": "/tmp/a.md"}, headers=HTMX
    )
    grouped = client.post(
        "/add",
        data={"kind": "group", "group-1": "g", "lines-1": "/tmp/a.md"},
        headers=HTMX,
    )

    assert adds == []
    assert words.CHOOSE_A_COLLECTION in refused.text
    assert words.CHOOSE_A_COLLECTION in grouped.text


def test_a_local_page_into_docs_without_a_project_is_refused_in_the_form(
    client: TestClient, adds: list[AddCall], tmp_path: Path
):
    """Refused by the add once it had started, after the dialog had closed,
    so what was typed was gone by the time the reason arrived."""
    page = tmp_path / "tutorial.md"
    page.write_text("# A tutorial\n", encoding="utf-8")

    refused = client.post(
        "/add",
        data={"kind": "file", "identifiers": str(page), "collection": "docs"},
        headers=HTMX,
    )
    grouped = client.post(
        "/add",
        data={
            "kind": "group",
            "group-1": "g",
            "lines-1": str(page),
            "collection-1": "docs",
        },
        headers=HTMX,
    )

    assert adds == []
    assert refused.headers["HX-Retarget"] == "#add-problem"
    assert unescape(words.docs_input_refused(str(page), "unnamed")) in unescape(
        refused.text
    )
    assert "tutorial.md" in grouped.text


def test_a_local_page_into_docs_with_a_project_starts(
    client: TestClient, adds: list[AddCall], tmp_path: Path
):
    page = tmp_path / "tutorial.md"
    page.write_text("# A tutorial\n", encoding="utf-8")

    client.post(
        "/add",
        data={
            "kind": "file",
            "identifiers": str(page),
            "collection": "docs",
            "project": "example",
            "version": "latest",
        },
        headers=HTMX,
    )

    assert len(adds) == 1


def test_a_site_whose_address_names_no_version_is_refused_in_the_form(
    client: TestClient, adds: list[AddCall]
):
    """#489: the reader is asked, rather than given a label kennis made up."""
    refused = client.post(
        "/add",
        data={
            "kind": "site",
            "collection": "docs",
            "identifiers": "https://example.org/docs/",
        },
        headers=HTMX,
    )

    assert adds == []
    assert "Enter a Version" in refused.text


def test_a_version_typed_in_the_form_reaches_the_add(
    app: FastAPI, client: TestClient, adds: list[AddCall]
):
    client.post(
        "/add",
        data={
            "kind": "site",
            "collection": "docs",
            "identifiers": "https://example.org/docs/",
            "version": "2.12",
        },
        headers=HTMX,
    )
    finished(app)

    assert adds[0][2].version == "2.12"


@pytest.mark.parametrize(("ticked", "refresh"), [(True, True), (False, False)])
def test_refresh_ticked_in_the_form_reaches_the_add(
    app: FastAPI, client: TestClient, adds: list[AddCall], ticked: bool, refresh: bool
):
    sent = {
        "kind": "site",
        "collection": "docs",
        "identifiers": "https://example.org/docs/2.12/",
    }
    if ticked:
        sent["refresh"] = "on"
    client.post("/add", data=sent, headers=HTMX)
    finished(app)

    assert adds[0][2].refresh is refresh


def test_refresh_is_a_checkbox(client: TestClient):
    dialog = dialog_of(client, "site")

    assert re.search(r'<input[^>]*type="checkbox"[^>]*name="refresh"', dialog)


def test_the_site_preview_names_the_version(client: TestClient):
    named = client.get(
        "/add/preview/site",
        params={"identifiers": "https://pydantic.dev/docs/validation/2.12/"},
    )
    unnamed = client.get(
        "/add/preview/site", params={"identifiers": "https://example.org/docs/"}
    )

    assert words.previewed_version("2.12") in unescape(named.text)
    assert words.VERSION_UNNAMED in unescape(unnamed.text)


# ---------------------------------------------------------------------------
# As the mockup draws it (#447)
# ---------------------------------------------------------------------------

# Written by hand: each tab's picture.
EXPECTED_TAB_ICONS = {
    "paper": "book-open",
    "site": "globe",
    "file": "file-text",
    "group": "folder",
}


def foot_of(dialog: str) -> Tag:
    foot = BeautifulSoup(dialog, "html.parser").select_one(".form-foot")
    assert isinstance(foot, Tag), dialog
    return foot


def test_each_tab_carries_its_picture(client: TestClient):
    dialog = dialog_of(client, "paper")
    tabs = re.findall(r'<a class="tab"[^>]*kind=(\w+)[^>]*>(.*?)</a>', dialog, re.S)

    assert [kind for kind, _ in tabs] == list(EXPECTED_TAB_ICONS)
    for kind, inside in tabs:
        assert str(icon(EXPECTED_TAB_ICONS[kind])) in inside, kind


def test_the_foot_says_where_the_add_goes_and_offers_cancel_and_the_kinds_add(
    client: TestClient,
):
    foot = foot_of(dialog_of(client, "paper"))
    destination = foot.select_one(".destination")
    cancel = foot.select_one("[data-close]")
    submit = foot.select_one("button[type=submit]")

    assert isinstance(destination, Tag)
    assert words.ADDS_TO in destination.get_text(" ")
    assert "literature" in destination.get_text(" ")
    assert isinstance(cancel, Tag) and cancel.get_text(strip=True) == words.CANCEL
    assert isinstance(submit, Tag)
    assert submit.get_text(strip=True) == words.ADD_ACTIONS["paper"]


def test_the_place_a_dialog_was_opened_on_is_where_it_says_it_adds(
    client: TestClient,
):
    """11f's Add here fills the group; the foot says so before the reader
    has typed anything."""
    answer = client.get(
        "/add", params={"kind": "paper", "group": "calibration"}, headers=HTMX
    )

    destination = foot_of(answer.text).select_one(".destination")

    assert isinstance(destination, Tag)
    assert "calibration" in destination.get_text(" ")


def test_the_destination_follows_the_fields_it_names(client: TestClient):
    """Each part names a field the form really has, so the script that
    copies values has something to copy."""
    for kind in ("paper", "site", "file"):
        dialog = dialog_of(client, kind)
        form = BeautifulSoup(dialog, "html.parser").select_one("form")
        assert isinstance(form, Tag)
        names = {str(field.get("name")) for field in form.select("[name]")}
        mirrored = [str(part["data-mirror"]) for part in form.select("[data-mirror]")]
        assert mirrored, kind
        assert set(mirrored) <= names, kind


def test_several_by_group_names_no_single_destination(client: TestClient):
    assert foot_of(dialog_of(client, "group")).select_one(".destination") is None


def test_the_dialog_script_copies_values_and_composes_no_words():
    code = code_of("dialog.js")

    # The call, not only the function: a function nothing calls copies
    # nothing, and the walk in a browser is what shows it copies.
    assert "data-mirror" in code
    assert re.search(r"\{ mirror\(form\); \}", code)
    assert "preventDefault" in code
    assert not re.search(r'"[A-Z][a-z]+ [a-z]', code), "a sentence in the script"


@pytest.mark.parametrize("kind", ["paper", "site", "file"])
def test_an_optional_field_says_what_empty_becomes_as_its_default(
    client: TestClient, kind: str
):
    """In the field itself, as its placeholder, worded as the default: the
    line under each optional field doubled the height of the form."""
    dialog = BeautifulSoup(dialog_of(client, kind), "html.parser")
    controls = dialog.select(
        '.field[data-need="optional"] input[type="text"], '
        '.field[data-need="optional"] input[type="number"]'
    )

    assert controls
    assert dialog.select(".field .empty") == []
    for control in controls:
        name = str(control["name"])
        assert control.get("placeholder") == (
            f"{words.EMPTY_PREFIX} {empty_means_of(kind, name)}"
        ), name


def test_a_required_field_takes_the_whole_row(client: TestClient):
    dialog = BeautifulSoup(dialog_of(client, "file"), "html.parser")
    css = client.get("/static/kennis.css").text

    needs = {str(row.get("data-need")) for row in dialog.select(".field")}
    assert needs == {"required", "optional"}
    assert re.search(
        r'\.field\[data-need="required"\]\s*\{[^}]*grid-column: 1 / -1', css
    )


def test_the_settings_pages_choices_rule_does_not_reach_the_add_form(
    client: TestClient,
):
    """A bare `.choices` placed the settings page's choices in grid row 1,
    and the File tab's collection radios rose above their own label: a
    bare class declared once, for one page, used by another (#451)."""
    css = client.get("/static/kennis.css").text

    for selector, body in re.findall(r"([^{}]*)\{([^}]*)\}", css):
        if "grid-row" in body and re.search(r"\.choices\b", selector):
            assert ".setting" in selector, selector


# ---------------------------------------------------------------------------
# Files sent from the browser's own picker
# ---------------------------------------------------------------------------


def test_uploaded_files_are_added_beside_what_was_typed(
    client: TestClient, adds: list[AddCall]
):
    """The picker is the native dialog of the computer the reader sits at,
    and its files arrive through the same connection as the page - so this
    is the same whether kennis runs there or behind `ssh -L`."""
    client.post(
        "/add",
        data={"kind": "file", "collection": "notes", "identifiers": ""},
        files=[
            ("upload", ("calibration.md", b"# Calibration\n", "text/markdown")),
            ("upload", ("solving.md", b"# Solving\n", "text/markdown")),
        ],
        headers=HTMX,
    )
    finished(client.app)

    [(destination, identifiers, _)] = adds
    assert destination == "notes"
    assert [Path(one).name for one in identifiers] == ["calibration.md", "solving.md"]
    assert Path(identifiers[0]).read_bytes() == b"# Calibration\n"


def test_an_uploaded_folder_is_added_once_with_its_folders_kept(
    client: TestClient, adds: list[AddCall]
):
    client.post(
        "/add",
        data={"kind": "file", "collection": "notes", "identifiers": ""},
        files=[
            ("upload", ("papers/a.md", b"# A\n", "text/markdown")),
            ("upload", ("papers/deep/b.md", b"# B\n", "text/markdown")),
        ],
        headers=HTMX,
    )
    finished(client.app)

    [(_, identifiers, _)] = adds
    [folder] = identifiers
    assert Path(folder).name == "papers"
    assert (Path(folder) / "deep" / "b.md").read_bytes() == b"# B\n"


def test_an_empty_picker_adds_only_what_was_typed(
    client: TestClient, adds: list[AddCall], tmp_path: Path
):
    """A file input left empty still posts one part, with no name."""
    typed = tmp_path / "typed.md"
    typed.write_text("# Typed\n", encoding="utf-8")

    client.post(
        "/add",
        data={"kind": "file", "collection": "notes", "identifiers": str(typed)},
        files=[("upload", ("", b"", "application/octet-stream"))],
        headers=HTMX,
    )
    finished(client.app)

    [(_, identifiers, _)] = adds
    assert identifiers == (str(typed),)


@pytest.mark.parametrize(
    "sent", ["../../escape.md", "/etc/escape.md", "C:\\Users\\x\\escape.md"]
)
def test_an_uploaded_name_cannot_place_a_file_outside_its_folder(sent: str):
    """The name is the sender's to choose; only its last parts are kept."""
    result = staged([UploadedPart(sent, b"# Kept\n")])

    [path] = result.names
    assert path.name == "escape.md"
    # Both resolved: Windows may name the temporary directory by its short
    # 8.3 name, RUNNER~1, and the resolved path by its long one.
    assert path.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
    assert ".." not in path.parts


@dataclass
class UploadedPart:
    name: str
    body: bytes

    @property
    def filename(self) -> str:
        return self.name

    @property
    def file(self) -> io.BytesIO:
        return self.stream

    def __post_init__(self) -> None:
        self.stream = io.BytesIO(self.body)


def test_an_uploaded_file_says_it_was_uploaded_not_where_it_was_staged():
    """A temporary path is gone once the add is, and names nothing."""
    result = staged([UploadedPart("notes/calibration.md", b"# Calibration\n")])
    [path] = result.names

    with uploaded_as(result.names):
        converted = convert_local_file(path)

    assert converted.origin == "upload:notes/calibration.md"
    assert convert_local_file(path).origin == f"path:{path}"


def test_a_field_beside_the_picker_takes_the_whole_row(client: TestClient):
    """Optional now - the picker will do instead - and still the first
    thing on its tab, so it is not squeezed into half a row."""
    dialog = BeautifulSoup(dialog_of(client, "paper"), "html.parser")
    css = client.get("/static/kennis.css").text

    assert dialog.select_one('.field[data-uploads] input[name="pdf"]')
    assert re.search(r"\.field\[data-uploads\][^{]*\{[^}]*grid-column: 1 / -1", css)


def test_the_file_tab_leads_with_the_picker_and_folds_the_typed_path(
    client: TestClient,
):
    """Two native inputs and a text field, all in view and all alike, left
    the reader to guess which to use; the folder input's own button even
    said "Choose File"."""
    dialog = BeautifulSoup(dialog_of(client, "file"), "html.parser")
    field = dialog.select_one('.field[data-uploads="both"]')
    assert field is not None

    labels = [label.get_text(strip=True) for label in field.select(".upload-button")]
    assert labels == [words.UPLOAD_FILES, words.UPLOAD_FOLDER]
    typed = field.select_one("details.typed-path")
    assert typed is not None and typed.get("open") is None
    assert typed.select_one('input[name="identifiers"]') is not None
    assert typed.get_text(" ", strip=True).startswith(words.UPLOAD_TYPED)


def test_the_picker_script_says_what_was_chosen_in_the_servers_words():
    code = code_of("uploads.js")

    assert "dataset.saidMany" in code and "dataset.saidFolder" in code
    assert not re.search(r"\"[A-Za-z]+ [A-Za-z ]+\"", code)


def test_the_picker_script_is_loaded(client: TestClient):
    assert '<script defer src="/static/uploads.js"></script>' in client.get("/").text


def test_an_info_tip_is_the_browsers_own_popover():
    """Opens by click, tap or keyboard and closes on Escape with no script;
    the button says what it is about, the tip holds the words."""
    template = TEMPLATES.env.from_string(
        '{% from "tip.html" import tip %}'
        '{{ tip("x", "the title", "Its own heading.") }}'
    )
    drawn = BeautifulSoup(template.render(), "html.parser")

    button = drawn.select_one("button.tip-button")
    tip = drawn.select_one("#tip-x")
    assert button is not None and tip is not None
    assert button.get("popovertarget") == "tip-x"
    assert button.get("aria-label") == words.tip_about("the title")
    assert tip.has_attr("popover")
    assert tip.get_text() == "Its own heading."


def test_a_group_field_suggests_the_groups_already_held(
    corpus: Path, client: TestClient
):
    """Typed free, "Radio" beside "radio" quietly made a second group."""
    note = corpus / "radio.md"
    note.write_text("# Radio\n\nA note.\n", encoding="utf-8")
    assert (
        CliRunner()
        .invoke(main, ["corpus", "add", "-n", str(note), "--group", "radio"])
        .exit_code
        == 0
    )

    for kind in ("paper", "file", "group"):
        dialog = BeautifulSoup(dialog_of(client, kind), "html.parser")
        offered = [option["value"] for option in dialog.select("#add-groups option")]
        assert offered == ["radio"], kind
        for field in dialog.select('input[name^="group"]'):
            assert field.get("list") == "add-groups", kind
    note_form = BeautifulSoup(client.get("/remember", headers=HTMX).text, "html.parser")
    assert [option["value"] for option in note_form.select("#note-groups option")] == [
        "radio"
    ]
    assert note_form.select_one('input[name="group"]')["list"] == "note-groups"


# ---------------------------------------------------------------------------
# The Paper tab's two ways in
# ---------------------------------------------------------------------------


def test_the_paper_tab_offers_an_identifier_or_a_pdf_with_identifier_chosen(
    client: TestClient,
):
    """As Zotero has it: the identifier field alone up front, and the PDF's
    fields - the picker and which paper it is - only once a PDF is the way
    in. Both were in view at once, and an arXiv ID was typed into both."""
    dialog = BeautifulSoup(dialog_of(client, "paper"), "html.parser")
    radios = dialog.select('input[name="source"]')
    css = client.get("/static/kennis.css").text

    assert [radio["value"] for radio in radios] == ["identifier", "pdf"]
    assert [radio.has_attr("checked") for radio in radios] == [True, False]
    # A switch with one way always chosen, not a field to be told is needed.
    switch = dialog.select_one(".ways")
    assert switch is not None and switch.find_parent(class_="field") is None
    assert switch["aria-label"] == words.FIELD_LABELS["source"]
    assert all(radio["hx-get"] == "/add/preview/paper" for radio in radios)
    when = {
        field["data-name"]: field.get("data-when") for field in dialog.select(".field")
    }
    assert when["identifiers"] == "identifier"
    assert when["pdf"] == when["identifier"] == "pdf"
    assert when["title"] is when["citekey"] is when["group"] is None
    assert re.search(
        r'\[name="source"\]\) \.field\[data-when\] \{\s*display: none', css
    )
    assert 'value="pdf"]:checked)\n  .field[data-when="pdf"]' in css


def test_the_pdf_way_in_leads_with_the_picker_and_folds_an_address_or_path(
    client: TestClient,
):
    dialog = BeautifulSoup(dialog_of(client, "paper"), "html.parser")
    field = dialog.select_one('.field[data-when="pdf"][data-uploads="file"]')
    assert field is not None

    labels = [label.get_text(strip=True) for label in field.select(".upload-button")]
    assert labels == [words.UPLOAD_PDF]
    typed = field.select_one("details.typed-path")
    assert typed is not None and typed.get("open") is None
    assert typed.select_one('input[name="pdf"]') is not None
    assert typed.get_text(" ", strip=True).startswith(words.UPLOAD_TYPED_PDF)


def test_by_identifier_adds_only_the_identifier_typed(
    client: TestClient, adds: list[AddCall]
):
    """A PDF left in the other way's picker, and an identifier left in its
    field, are out of sight: neither is added, nor changes the add."""
    client.post(
        "/add",
        data={
            "kind": "paper",
            "collection": "literature",
            "source": "identifier",
            "identifiers": "2409.19750",
            "identifier": "10.1093/mnras/stab1234",
        },
        files=[("upload", ("other.pdf", b"%PDF-1.4\n", "application/pdf"))],
        headers=HTMX,
    )
    finished(client.app)

    [(destination, identifiers, options)] = adds
    assert destination == "literature"
    assert identifiers == ("2409.19750",)
    assert options.identifier is None


def test_from_a_pdf_adds_the_pdf_as_the_paper_its_identifier_names(
    client: TestClient, adds: list[AddCall]
):
    client.post(
        "/add",
        data={
            "kind": "paper",
            "collection": "literature",
            "source": "pdf",
            "identifiers": "2409.19750",
            "pdf": "",
            "identifier": "10.1093/mnras/stab1234",
        },
        files=[("upload", ("paper.pdf", b"%PDF-1.4\n", "application/pdf"))],
        headers=HTMX,
    )
    finished(client.app)

    [(_, identifiers, options)] = adds
    assert [Path(one).name for one in identifiers] == ["paper.pdf"]
    assert options.identifier == "10.1093/mnras/stab1234"


@pytest.mark.parametrize(
    ("source", "said"),
    [("identifier", words.NO_IDENTIFIER), ("pdf", words.NO_PDF)],
)
def test_an_empty_way_in_is_told_what_it_needs(
    client: TestClient, adds: list[AddCall], source: str, said: str
):
    refused = client.post(
        "/add",
        data={"kind": "paper", "collection": "literature", "source": source},
        headers=HTMX,
    )

    assert adds == []
    assert said in refused.text


def test_from_a_pdf_the_preview_looks_up_the_identifier_given(
    client: TestClient, lookups: list[str]
):
    """So the reader sees which paper the PDF will be recorded as."""
    shown = client.get(
        "/add/preview/paper",
        params={
            "source": "pdf",
            "identifiers": "",
            "pdf": "/tmp/paper.pdf",
            "identifier": "2409.19750",
        },
        headers=HTMX,
    ).text

    assert lookups == ["2409.19750"]
    assert "A Paper About Calibration" in shown


# ---------------------------------------------------------------------------
# What the preview found, in the fields
# ---------------------------------------------------------------------------


def previewed(client: TestClient, **fields: str) -> BeautifulSoup:
    answer = client.get("/add/preview/paper", params=fields, headers=HTMX)
    assert answer.status_code == 200
    return BeautifulSoup(answer.text, "html.parser")


def redrawn(shown: BeautifulSoup, name: str) -> Tag | None:
    """The input named `name` the preview redraws out of band, if any."""
    for swapped in shown.select("[hx-swap-oob]"):
        found = swapped.find("input", attrs={"name": name})
        if isinstance(found, Tag):
            return found
    return None


def test_the_preview_fills_the_title_and_citekey_and_marks_them(
    client: TestClient, lookups: list[str]
):
    shown = previewed(client, identifiers="2409.19750")

    title = redrawn(shown, "title")
    citekey = redrawn(shown, "citekey")
    assert title is not None and citekey is not None
    assert title.get("value") == "A Paper About Calibration"
    assert citekey.get("value") == "welmanPaperAboutCalibration2024"
    for field in (title, citekey):
        assert "prefilled" in (field.get("class") or [])
        assert field.get("aria-describedby")
    assert redrawn(shown, "prefilled-title").get("value") == "A Paper About Calibration"
    assert (
        redrawn(shown, "prefilled-citekey").get("value")
        == "welmanPaperAboutCalibration2024"
    )


def test_the_paragraph_no_longer_repeats_what_is_in_the_fields(
    client: TestClient, lookups: list[str]
):
    shown = previewed(client, identifiers="2409.19750")
    paragraph = " ".join(
        element.get_text()
        for element in shown.find_all("p")
        if not element.get("hx-swap-oob")
    )

    assert "Brian Welman" in paragraph and "2024" in paragraph
    assert "A Paper About Calibration" not in paragraph
    assert "welmanPaperAboutCalibration2024" not in paragraph


def test_a_typed_title_is_never_redrawn_and_shapes_the_citekey(
    client: TestClient, lookups: list[str]
):
    shown = previewed(
        client,
        identifiers="2409.19750",
        title="My Own Words",
        **{"prefilled-title": "A Paper About Calibration"},
    )

    assert redrawn(shown, "title") is None
    citekey = redrawn(shown, "citekey")
    assert citekey is not None
    assert citekey.get("value") == "welmanMyOwnWords2024"


def test_a_value_still_kenniss_follows_a_changed_identifier(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    titles = {"2409.19750": "First Paper", "2501.00001": "Second Paper"}
    monkeypatch.setattr(
        "kennis.engine.corpus.preview.lookup_arxiv_metadata",
        lambda arxiv_id, *, client=None: ArxivMetadata(
            title=titles[arxiv_id], authors="Brian Welman", year="2024"
        ),
    )

    shown = previewed(
        client,
        identifiers="2501.00001",
        title="First Paper",
        citekey="welmanFirstPaper2024",
        **{
            "prefilled-title": "First Paper",
            "prefilled-citekey": "welmanFirstPaper2024",
        },
    )

    assert redrawn(shown, "title").get("value") == "Second Paper"
    assert redrawn(shown, "citekey").get("value") == "welmanSecondPaper2024"


def test_nothing_found_empties_what_kennis_had_filled(
    client: TestClient, lookups: list[str]
):
    shown = previewed(
        client,
        identifiers="not an identifier",
        title="A Paper About Calibration",
        **{"prefilled-title": "A Paper About Calibration"},
    )

    title = redrawn(shown, "title")
    assert title is not None
    assert not title.get("value")
    assert "prefilled" not in (title.get("class") or [])


def test_several_papers_prefill_nothing(client: TestClient, lookups: list[str]):
    """A title names one document."""
    shown = previewed(client, source="pdf", pdf="a.pdf\nb.pdf", identifier="")

    for name in ("title", "citekey"):
        field = redrawn(shown, name)
        assert field is None or not field.get("value")


def test_the_redrawn_citekey_still_asks_for_a_preview(
    client: TestClient, lookups: list[str]
):
    """One macro draws the input in the form and in the redraw, so the
    redraw cannot drop the attributes the form's own input has."""
    drawn = BeautifulSoup(dialog_of(client, "paper"), "html.parser")
    in_form = drawn.find("input", attrs={"name": "citekey"})
    again = redrawn(previewed(client, identifiers="2409.19750"), "citekey")

    assert isinstance(in_form, Tag) and again is not None
    for attribute in ("hx-get", "hx-trigger", "hx-target", "hx-include", "id"):
        assert again.get(attribute) == in_form.get(attribute), attribute


def test_the_dialog_holds_what_kennis_filled_in(client: TestClient):
    drawn = BeautifulSoup(dialog_of(client, "paper"), "html.parser")
    form = drawn.find("form")
    assert isinstance(form, Tag)

    for name in ("prefilled-title", "prefilled-citekey"):
        hidden = form.find("input", attrs={"name": name})
        assert isinstance(hidden, Tag), name
        assert hidden.get("type") == "hidden"


def test_an_add_treats_a_value_still_kenniss_as_empty(
    app: FastAPI, client: TestClient, adds: list[AddCall]
):
    """So the add derives what it would have derived, and a title kennis
    filled in for the first paper never reaches an add of several."""
    client.post(
        "/add",
        data={
            "kind": "paper",
            "collection": "literature",
            "source": "identifier",
            "identifiers": "2409.19750",
            "title": "A Paper About Calibration",
            "prefilled-title": "A Paper About Calibration",
            "citekey": "mine2024",
            "prefilled-citekey": "welmanPaperAboutCalibration2024",
        },
        headers=HTMX,
    )
    finished(app)

    [(_, _, options)] = adds
    assert options.title is None
    assert options.citekey == "mine2024"


def test_the_prefill_script_composes_no_words():
    code = code_of("prefill.js")

    assert "prefilled" in code
    assert not re.search(r"[\"'][A-Z][a-z]+ [a-z]+", code)


def test_the_field_being_typed_in_is_not_redrawn(
    client: TestClient, lookups: list[str]
):
    """Emptied to type afresh, the Citekey field asks for a preview; it
    must not be refilled under the cursor."""
    answer = client.get(
        "/add/preview/paper",
        params={
            "identifiers": "2409.19750",
            "citekey": "",
            "prefilled-citekey": "welmanPaperAboutCalibration2024",
        },
        headers={**HTMX, "HX-Trigger-Name": "citekey"},
    )
    shown = BeautifulSoup(answer.text, "html.parser")

    assert redrawn(shown, "citekey") is None
    assert redrawn(shown, "title") is not None


# ---------------------------------------------------------------------------
# What the preview found, as a card, and that it is looking
# ---------------------------------------------------------------------------


@pytest.fixture
def five_authors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "kennis.engine.corpus.preview.lookup_arxiv_metadata",
        lambda arxiv_id, *, client=None: ArxivMetadata(
            title="A Paper About Calibration",
            authors="Ada One and Bo Two and Cy Three and Di Four and Ed Five",
            year="2024",
        ),
    )


def found_card(shown: BeautifulSoup) -> Tag:
    card = shown.find(class_="found")
    assert isinstance(card, Tag), shown
    return card


def test_the_found_paper_is_a_card_with_a_link_to_its_abstract(
    client: TestClient, five_authors: None
):
    card = found_card(previewed(client, identifiers="https://arxiv.org/abs/2409.19750"))
    link = card.find("a")

    assert isinstance(link, Tag)
    assert link["href"] == "https://arxiv.org/abs/2409.19750"
    assert link.get("target") == "_blank"
    assert "noreferrer" in (link.get("rel") or [])
    assert "2409.19750" in link.get_text()
    assert "2024" in card.get_text()


def test_a_long_author_list_is_shortened_and_kept_whole_as_a_tooltip(
    client: TestClient, five_authors: None
):
    card = found_card(previewed(client, identifiers="2409.19750"))
    authors = card.find(class_="authors")

    assert isinstance(authors, Tag)
    assert authors.get_text(strip=True) == "Ada One, Bo Two, Cy Three and 2 others"
    assert authors["title"] == "Ada One, Bo Two, Cy Three, Di Four, Ed Five"


def test_the_card_names_the_title_only_when_its_field_does_not(
    client: TestClient, five_authors: None
):
    filled = found_card(previewed(client, identifiers="2409.19750"))
    typed = found_card(
        previewed(
            client,
            identifiers="2409.19750",
            title="My Own Words",
            **{"prefilled-title": ""},
        )
    )

    assert "A Paper About Calibration" not in filled.get_text()
    assert "A Paper About Calibration" in typed.get_text()


@pytest.mark.parametrize("kind", ["paper", "site"])
def test_every_field_that_asks_for_a_preview_shows_the_looking_line(
    client: TestClient, kind: str
):
    dialog = BeautifulSoup(dialog_of(client, kind), "html.parser")
    asking = dialog.select("[hx-get^='/add/preview']")
    looking = dialog.find(id="add-looking")

    assert asking
    for element in asking:
        assert element.get("hx-indicator") == "#add-looking", element
    assert isinstance(looking, Tag)
    assert looking.get_text(strip=True) == words.LOOKING_UP[kind]


def test_the_looking_line_shows_only_while_a_request_is_out():
    from kennis.gui.theme import layout_css

    css = layout_css()
    assert re.search(r"\.looking\s*\{[^}]*display:\s*none", css)
    assert re.search(r"\.looking\.htmx-request\s*\{[^}]*display:\s*(?!none)", css)


@pytest.mark.parametrize("kind", ["paper", "site"])
def test_the_looking_line_is_a_ring_with_its_words_for_a_screen_reader(
    client: TestClient, kind: str
):
    looking = BeautifulSoup(dialog_of(client, kind), "html.parser").find(
        id="add-looking"
    )
    assert isinstance(looking, Tag)
    ring = looking.find(class_="ring")
    said = looking.find(class_="visually-hidden")

    assert isinstance(ring, Tag) and ring.get("aria-hidden") == "true"
    assert isinstance(said, Tag) and said.get_text(strip=True) == words.LOOKING_UP[kind]


def test_the_lookup_ring_is_the_submit_buttons_ring():
    """One turning ring in the layout, so the two cannot drift apart."""
    from kennis.gui.theme import layout_css

    css = re.sub(r"/\*.*?\*/", "", layout_css(), flags=re.S)
    turning = [
        selector
        for selector, body in re.findall(r"([^{}]+)\{([^}]*)\}", css)
        if "animation: turning" in body
    ]
    assert len(turning) == 1
    assert ".looking .ring" in turning[0]
    assert 'button[type="submit"]::after' in turning[0]
