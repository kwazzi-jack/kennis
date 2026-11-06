"""What an installed pack contains, said by `pack show` and the window.

The engine names each item (`contents_of`), `render/packs.py` words a
section, and both front ends print the same lines.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from click.testing import CliRunner
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.engine.pack.installed import PackContents, contents_of, list_installed
from kennis.engine.pack.store import install_pack
from kennis.engine.pack.update import update_pack
from kennis.gui.app import build_app
from kennis.render.citations import style_path
from kennis.render.packs import contents_sections

TOKEN = "a-test-token"

BODY = """
corpus:
  literature:
    - {
        citekey: smith2020,
        title: "A Survey of Transients",
        identifier: "2001.01234",
        authors: [Jan Smith],
        year: 2020,
      }
  docs:
    - {project: stimela, base_url: "https://x.org/stimela/2.1/", version: "2.1"}
  notes:
    - source: notes/
      group: recipes
    - {url: "https://example.org/guide", title: "The guide"}
context:
  - source: context/
"""


def a_provider(root: Path, *, identifier: str = "alpha") -> Path:
    """A pack declaring one item of every kind, with its generated block."""
    for relative, text in {
        "notes/imaging.md": "Image.\n",
        "context/conventions.md": "Conventions.\n",
    }.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    path = root / f"{identifier}.ken.yml"
    path.write_text(
        "kennis:\n  schema_version: 1\n"
        f'pack:\n  id: {identifier}\n  name: Alpha\n  version: "0.1.0"\n' + BODY,
        encoding="utf-8",
    )
    update_pack(path)
    return path


def test_the_contents_name_every_declared_item_where_it_lands(tmp_path: Path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    install_pack(corpus, a_provider(tmp_path / "provider"))
    (installed,) = list_installed(corpus).packs

    contents = contents_of(installed)

    assert contents is not None
    assert [entry.citekey for entry in contents.papers] == ["smith2020"]
    assert [entry.project for entry in contents.docs] == ["stimela"]
    # A `source:` is expanded into the addresses its files land at.
    assert contents.shipped_notes == ("recipes/imaging.md",)
    assert [link.url for link in contents.note_links] == ["https://example.org/guide"]
    assert contents.context == ("conventions.md",)


def contents_in(tmp_path: Path) -> PackContents:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    install_pack(corpus, a_provider(tmp_path / "provider"))
    (installed,) = list_installed(corpus).packs
    contents = contents_of(installed)
    assert contents is not None
    return contents


def test_each_section_is_counted_and_drawn_under_its_folders(tmp_path: Path):
    sections = {
        section.kind: section
        for section in contents_sections(contents_in(tmp_path), None)
    }

    assert [section.heading for section in sections.values()] == [
        "1 paper",
        "1 documentation project",
        "2 notes",
        "1 context file",
    ]
    notes = sections["notes"].top
    # A shipped file sits under its folder, named by its own name; the
    # folder is named by its last part and counts what is beneath it.
    assert [folder.name for folder in notes.folders] == ["recipes"]
    assert notes.folders[0].count == 1
    assert [item.name for item in notes.folders[0].items] == ["imaging.md"]
    assert [(item.name, item.detail) for item in notes.items] == [
        ("The guide", "https://example.org/guide")
    ]
    assert notes.count == 2
    (docs,) = sections["docs"].top.items
    assert (docs.name, docs.detail) == ("stimela 2.1", "https://x.org/stimela/2.1/")
    # What each item is, for a front end to mark it by.
    assert docs.kind == "site"
    assert [item.kind for item in notes.items] == ["address"]
    assert notes.folders[0].items[0].kind == "file"
    assert sections["literature"].top.items[0].kind == "paper"


def test_a_paper_is_its_citekey_and_its_reference_in_the_style(tmp_path: Path):
    style = style_path("")
    (papers, *_) = contents_sections(contents_in(tmp_path), style)

    (paper,) = papers.top.items
    assert paper.name == "smith2020"
    assert paper.detail is not None
    # Harvard (Cite Them Right), the default: family name, initial, year.
    assert paper.detail.startswith("Smith, J. (2020)")
    assert "A Survey of Transients" in paper.detail


def test_a_style_that_cannot_be_read_falls_back_to_a_plain_line(tmp_path: Path):
    unreadable = tmp_path / "not-a-style.csl"
    unreadable.write_text("not xml", encoding="utf-8")

    (papers, *_) = contents_sections(contents_in(tmp_path), unreadable)

    (paper,) = papers.top.items
    # The name as the pack wrote it, since no style reordered it.
    assert paper.detail == "Jan Smith (2020) A Survey of Transients"


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    path = a_provider(tmp_path / "provider")
    result = CliRunner().invoke(main, ["pack", "install", str(path)])
    assert result.exit_code == 0, result.output
    return tmp_path / "corpus"


@pytest.fixture
def isolated_notes(corpus: Path) -> None:
    # Each text its own: a note whose text is already held is not written.
    for title, group in (
        ("On ASKAP", "tron/askap"),
        ("On citizens", "tron/citizen-science"),
    ):
        result = CliRunner().invoke(
            main,
            ["remember", f"{title}.", "--title", title, "--group", group, "--no-index"],
        )
        assert result.exit_code == 0, result.output


def test_pack_show_prints_every_section(corpus: Path):
    result = CliRunner().invoke(main, ["pack", "show", "alpha"])

    assert result.exit_code == 0, result.output
    lines = [line.rstrip() for line in result.output.splitlines()]
    assert any(line.strip() == "1 paper" for line in lines)
    # Every item is marked, so one entry is told from the next.
    for expected in ("- smith2020", "- conventions.md"):
        assert any(line.strip() == expected for line in lines), expected
    # A project's address fits beside its name, so it is drawn there.
    assert any(
        line.split() == ["-", "stimela", "2.1", "https://x.org/stimela/2.1/"]
        for line in lines
    )
    # A reference sits under its citekey, past the marker.
    citekey = next(line for line in lines if line.strip() == "- smith2020")
    reference = lines[lines.index(citekey) + 1]
    assert reference.strip().startswith("Smith, J. (2020)")
    assert len(reference) - len(reference.lstrip()) == citekey.index("smith2020")
    # The folder, then its file one step further in.
    folder = next(line for line in lines if line.strip() == "recipes/")
    shipped = next(line for line in lines if line.strip() == "- imaging.md")
    assert lines.index(shipped) == lines.index(folder) + 1
    assert len(shipped) - len(shipped.lstrip()) > len(folder) - len(folder.lstrip())


def test_pack_show_with_no_id_shows_every_pack(corpus: Path):
    result = CliRunner().invoke(main, ["pack", "show"])

    assert result.exit_code == 0, result.output
    assert "smith2020" in result.output


def test_pack_show_of_a_pack_not_installed_names_the_listing(corpus: Path):
    result = CliRunner().invoke(main, ["pack", "show", "nothing"])

    assert result.exit_code != 0
    assert "nothing" in result.output
    assert "kennis pack list" in result.output


def opened() -> TestClient:
    client = TestClient(build_app(TOKEN), follow_redirects=False)
    assert client.get("/", params={"token": TOKEN}).status_code == 200
    return client


def test_the_pack_page_draws_each_section_as_a_folder_tree(corpus: Path):
    answer = opened().get("/packs/alpha")

    assert answer.status_code == 200
    shown = BeautifulSoup(answer.text, "html.parser")
    sections = shown.select("main details.outline-section")
    headings = [
        section.select_one("summary .name").get_text(strip=True) for section in sections
    ]
    assert headings == [
        "1 paper",
        "1 documentation project",
        "2 notes",
        "1 context file",
    ]
    notes = sections[2]
    folder = notes.select_one("li.outline-folder")
    assert folder.select_one("summary .name").get_text(strip=True) == "recipes"
    assert folder.select_one(".item-name").get_text(strip=True) == "imaging.md"
    paper = sections[0].select_one("li.outline-item")
    assert paper.select_one(".item-name").get_text(strip=True) == "smith2020"
    assert (
        paper.select_one(".item-detail")
        .get_text(strip=True)
        .startswith("Smith, J. (2020)")
    )


def test_the_corpus_page_folds_each_region_and_each_pack(corpus: Path):
    page = BeautifulSoup(opened().get("/corpus").text, "html.parser")

    regions = page.select("main details.region")
    assert [region.get("id") for region in regions] == ["holdings", "packs"]
    (pack,) = page.select("#packs details.pack")
    assert pack.select_one("details.outline-section") is not None
    # Closed until asked for, by default (Brian, 2026-11-04).
    assert not any(one.has_attr("open") for one in page.select("main details"))


def test_the_folders_preference_draws_every_fold_open(corpus: Path):
    client = opened()
    client.cookies.set("folders", "open")

    page = BeautifulSoup(client.get("/corpus").text, "html.parser")

    folds = page.select("main details")
    assert folds
    assert all(one.has_attr("open") for one in folds)


def test_a_folders_preference_not_offered_is_the_default(corpus: Path):
    client = opened()
    client.cookies.set("folders", "sideways")

    page = BeautifulSoup(client.get("/corpus").text, "html.parser")

    assert not any(one.has_attr("open") for one in page.select("main details"))


def test_the_pack_card_navigates_by_buttons_not_by_text_links(corpus: Path):
    """Brian's rule: navigation is a button with a symbol, never a line of
    underlined text."""
    page = BeautifulSoup(opened().get("/corpus").text, "html.parser")
    (pack,) = page.select("#packs details.pack")

    links = pack.select("a")
    assert links
    for link in links:
        assert "button" in (link.get("class") or []), link
        assert link.find("svg") is not None, link
    hrefs = [link["href"] for link in links]
    assert "/packs/alpha" in hrefs
    assert "/packs/alpha/uninstall" in hrefs


def test_every_item_in_a_pack_is_marked_by_its_kind(corpus: Path):
    page = BeautifulSoup(opened().get("/packs/alpha").text, "html.parser")

    items = page.select("main li.outline-item")
    assert len(items) == 5
    for item in items:
        assert item.find("svg") is not None, item


def test_the_packs_page_lists_every_pack_and_the_pane_goes_there(corpus: Path):
    client = opened()
    page = BeautifulSoup(client.get("/packs").text, "html.parser")

    assert [
        pack.select_one(".name").get_text(strip=True)
        for pack in page.select("main details.pack")
    ] == ["Alpha"]
    pane = page.select_one("nav.pane")
    assert pane.select_one("a[href='/packs']") is not None
    assert pane.select_one("a[href='/corpus#packs']") is None


def test_uninstalling_from_the_window_asks_then_drops_the_pack(corpus: Path):
    app = build_app(TOKEN)
    client = TestClient(app, follow_redirects=False)
    assert client.get("/", params={"token": TOKEN}).status_code == 200
    dialog = BeautifulSoup(client.get("/packs/alpha/uninstall").text, "html.parser")
    form = dialog.select_one("form.uninstall")
    assert form["action"] == "/packs/alpha/uninstall"
    # The documents stay until a sync, and the dialog says so.
    assert "Sync" in dialog.get_text()

    answer = client.post(str(form["action"]))

    # A task, as an install is: its page says what went and offers the
    # sync that takes the pack's documents out, without running it.
    assert answer.status_code == 303
    location = answer.headers["location"]
    assert location.startswith("/job/")
    assert app.state.jobs.get(location.removeprefix("/job/")).done.wait(20)
    outcome = BeautifulSoup(client.get(location).text, "html.parser")
    assert "Uninstalled" in outcome.get_text()
    assert outcome.select_one("form[action='/sync'] button[type=submit]")
    assert "Pack install" not in outcome.get_text()
    page = BeautifulSoup(client.get("/packs").text, "html.parser")
    assert not page.select("main details.pack")
    listed = CliRunner().invoke(main, ["pack", "list"])
    assert "no packs installed" in listed.output


def test_uninstalling_a_pack_not_installed_is_a_problem_page(corpus: Path):
    client = opened()

    assert client.get("/packs/nothing/uninstall").status_code == 404
    assert client.post("/packs/nothing/uninstall").status_code == 404


def test_forgetting_a_project_from_the_window_asks_then_drops_it(
    corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    project = tmp_path / "boepie"
    project.mkdir()
    monkeypatch.chdir(project)
    assert CliRunner().invoke(main, ["context", "init"]).exit_code == 0
    client = opened()
    pane = BeautifulSoup(client.get("/").text, "html.parser").select_one("nav.pane")
    forget = pane.select_one("a[href='/projects/forget?project=boepie']")
    assert forget is not None

    dialog = BeautifulSoup(client.get(str(forget["href"])).text, "html.parser")
    form = dialog.select_one("form.forget")
    fields = {
        field["name"]: field["value"] for field in form.select("input[type=hidden]")
    }
    # The files stay, and the dialog says where they are.
    assert str(project / ".context") in dialog.get_text()

    answer = client.post(str(form["action"]), data=fields)

    assert answer.status_code == 303
    assert (project / ".context").is_dir()
    pane = BeautifulSoup(client.get("/").text, "html.parser").select_one("nav.pane")
    assert pane.select_one("a[href='/projects/forget?project=boepie']") is None


def test_the_collection_page_nests_groups_by_their_last_part(
    corpus: Path, isolated_notes: None
):
    page = BeautifulSoup(opened().get("/collection/notes").text, "html.parser")

    assert not page.select("main h2")
    top = page.select_one("main ul.outline")
    (outer,) = top.find_all("li", class_="outline-folder", recursive=False)
    assert outer.select_one("summary .name").get_text(strip=True) == "tron"
    assert outer.select_one("summary .count").get_text(strip=True) == "2"
    inner = [
        folder.select_one("summary .name").get_text(strip=True)
        for folder in outer.select("ul.outline > li.outline-folder")
    ]
    assert inner == ["askap", "citizen-science"]
    titles = [link.get_text(strip=True) for link in outer.select("a.document")]
    assert titles == ["On ASKAP", "On citizens"]


def test_a_pack_not_installed_is_a_problem_page(corpus: Path):
    client = TestClient(build_app(TOKEN), follow_redirects=False)
    assert client.get("/", params={"token": TOKEN}).status_code == 200

    assert client.get("/packs/nothing").status_code == 404
