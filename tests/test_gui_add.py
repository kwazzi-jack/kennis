"""Unit 11d: adding, one kind at a time.

Four tabs, each with only its own fields, each field saying whether it is
required and what an empty one becomes; a preview of what the add would
do; one block per group; and a chooser that lists the computer kennis
runs on, because that is the computer `corpus add` reads from (#420).
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import pytest
from bs4 import BeautifulSoup, Tag
from click.testing import CliRunner
from fastapi import FastAPI
from fastapi.testclient import TestClient
from markupsafe import escape

from kennis.cli.__main__ import main
from kennis.engine.corpus.add import AddOptions, AddReport
from kennis.engine.events import EventSink
from kennis.engine.literature.metadata import ArxivMetadata
from kennis.gui import words
from kennis.gui.app import build_app
from kennis.gui.icons import icon

TOKEN = "a-test-token"
HTMX = {"HX-Request": "true"}
STATIC = Path(__file__).parent.parent / "src" / "kennis" / "gui" / "static"

# Written by hand: the four kinds, in the order offered (#373).
EXPECTED_TABS = [
    ("paper", "Paper"),
    ("site", "Documentation site"),
    ("file", "File"),
    ("group", "Several by group"),
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

    monkeypatch.setattr("kennis.gui.app.add_documents", recorded)
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
    "paper": {"identifiers"},
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


@pytest.mark.parametrize("kind", [kind for kind, _ in EXPECTED_TABS])
def test_every_field_says_whether_it_is_needed_and_what_empty_means(
    client: TestClient, kind: str
):
    """The right one of the two, not merely one of them: a form calling
    every field required passes a check that each says something."""
    dialog = dialog_of(client, kind)
    rows = re.findall(r'<div class="field"[^>]*>(.*?)</div>', dialog, re.S)

    assert rows, dialog
    for row in rows:
        name = re.search(r'name="([^"]+)"', row)
        assert name, row
        need = re.search(r'<span class="need">([^<]+)</span>', row)
        assert need, row
        expected = (
            words.REQUIRED if name.group(1) in REQUIRED_FIELDS[kind] else words.OPTIONAL
        )
        assert need.group(1) == expected, row
        if expected == words.OPTIONAL:
            assert 'class="empty"' in row, row


@pytest.mark.parametrize(
    ("kind", "fields"),
    [
        ("paper", {"identifiers", "identifier", "title", "citekey", "group"}),
        ("site", {"identifiers", "project", "max_pages", "max_depth"}),
        ("file", {"identifiers", "collection", "title", "group", "project"}),
    ],
)
def test_each_tab_asks_only_its_own_fields(
    client: TestClient, kind: str, fields: set[str]
):
    dialog = dialog_of(client, kind)
    named = set(re.findall(r'<(?:input|textarea)[^>]*\bname="([^"]+)"', dialog))

    assert named - {"kind", "collection"} == fields - {"collection"}


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
            "identifiers": "https://stimela.readthedocs.io/",
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
    from kennis.render.refusals import describe_refusal

    shown = client.get(
        "/add/preview/paper",
        params={"identifiers": "10.1093/mnras/stab1234"},
        headers=HTMX,
    ).text

    sentence = describe_refusal(
        NoPublisherText(kind="doi", value="10.1093/mnras/stab1234")
    )
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
    assert f"path={home / 'Papers'}" in listing.replace("%2F", "/")


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


def test_every_field_that_takes_a_path_has_browse(client: TestClient):
    for kind in ("paper", "file"):
        dialog = dialog_of(client, kind)
        assert re.search(r'hx-get="/browse\?target=identifiers', dialog), kind
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


def test_an_optional_field_says_what_empty_becomes_with_the_value_set_apart(
    client: TestClient,
):
    dialog = BeautifulSoup(dialog_of(client, "paper"), "html.parser")
    empty = dialog.select_one(".field .empty")

    assert isinstance(empty, Tag)
    assert empty.get_text(" ").startswith(words.EMPTY_PREFIX)
    assert empty.find("b") is not None


def test_a_required_field_takes_the_whole_row(client: TestClient):
    dialog = BeautifulSoup(dialog_of(client, "paper"), "html.parser")
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
