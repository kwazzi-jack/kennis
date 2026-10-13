"""Unit 11f: the tree reports state, and is a place to act.

Each document says whether the index has it as it stands - quiet when
it does, a letter when not - a group says the worst beneath it, and a
filter hides what is quiet. Each row has a menu: Open, Move to group,
Add here, Index this collection.

The page is read with a parser, not with patterns: the menus nest
inside the rows they act on, and a pattern that stops at the first
`</details>` reads a group's folder as its menu.
"""

from __future__ import annotations

import re
from html import unescape
from pathlib import Path

import pytest
from bs4 import BeautifulSoup, Tag
from click.testing import CliRunner
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.context import existing_corpus
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.document import write_document
from kennis.engine.corpus.schema import DocsFrontmatter
from kennis.engine.groups import group_problem
from kennis.engine.history.repository import Repository
from kennis.gui import words
from kennis.gui.app import build_app

TOKEN = "a-test-token"
HTMX = {"HX-Request": "true"}
STATIC = Path(__file__).parent.parent / "src" / "kennis" / "gui" / "static"

# Written by hand: what each menu offers, in order (#373).
EXPECTED_MENU = ["Open", "Move to group", "Add here", "Index this collection"]
EXPECTED_DOCS_MENU = ["Open", "Add here", "Index this collection"]
EXPECTED_GROUP_MENU = ["Add here", "Index this collection"]
# And the letter for each state, which is what the reader learns to read.
EXPECTED_LETTERS = {"unindexed": "U", "changed": "M", "unreadable": "!"}


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


def add_note(tmp_path: Path, title: str, body: str, group: str | None = None) -> str:
    source = tmp_path / "sources" / f"{title}.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
    arguments = ["corpus", "add", "-n", str(source)]
    if group:
        arguments += ["--group", group]
    added = CliRunner().invoke(main, arguments)
    assert added.exit_code == 0, added.output
    held = Collection(root=existing_corpus().corpus_root, name="notes").contents()
    return next(d.id for d in held.documents if d.frontmatter.title == title)


def path_of(document_id: str) -> Path:
    held = Collection(root=existing_corpus().corpus_root, name="notes").contents()
    return next(d.md_path for d in held.documents if d.id == document_id)


@pytest.fixture
def states(corpus: Path) -> dict[str, str]:
    """Four notes in four states: quiet, changed since indexed, added after
    the index was built, and one kennis cannot read."""
    quiet = add_note(corpus, "Quiet", "Nothing has happened to this one.")
    # A quiet one in the group too, so a count of the group's entries and
    # a count of those needing attention differ (#352).
    add_note(corpus, "Settled", "Nothing has happened here either.", group="botany")
    edited = add_note(corpus, "Edited", "This will change.", group="botany")
    assert CliRunner().invoke(main, ["corpus", "index"]).exit_code == 0
    later = add_note(corpus, "Later", "Added after the index.", group="botany")
    edited_path = path_of(edited)
    edited_path.write_text(
        edited_path.read_text(encoding="utf-8") + "\nA second paragraph.\n",
        encoding="utf-8",
    )
    broken = existing_corpus().corpus_root / "notes" / "Broken.md"
    broken.write_text("---\nid: [unclosed\n---\n\nBody.\n", encoding="utf-8")
    return {"quiet": quiet, "edited": edited, "later": later}


def tree_of(client: TestClient, collection: str = "notes") -> BeautifulSoup:
    answer = client.get(f"/tree/{collection}", headers=HTMX)
    assert answer.status_code == 200
    return BeautifulSoup(answer.text, "html.parser")


def row_of(tree: BeautifulSoup | Tag, document_id: str) -> Tag:
    row = tree.find("li", attrs={"data-document": document_id})
    assert isinstance(row, Tag), tree
    return row


def group_of(tree: BeautifulSoup | Tag, name: str) -> Tag:
    group = tree.find("li", attrs={"data-group": name})
    assert isinstance(group, Tag), tree
    return group


def classes(element: Tag) -> list[str]:
    found = element.get("class") or []
    return list(found) if isinstance(found, list) else found.split()


def own_menu(row: Tag) -> Tag:
    """The menu that is this row's own child - never one nested deeper."""
    menu = row.find("details", class_="menu", recursive=False)
    assert isinstance(menu, Tag), row
    return menu


def menu_labels(row: Tag) -> list[str]:
    return [item.get_text(strip=True) for item in own_menu(row).select(".item")]


def own_mark(row: Tag) -> Tag | None:
    """The state letter on this row's own line, which is its first child."""
    line = row.find(["a", "span"], recursive=False)
    assert isinstance(line, Tag), row
    found = line.find("span", class_="doc-state")
    return found if isinstance(found, Tag) else None


def code_of(name: str) -> str:
    script = (STATIC / name).read_text(encoding="utf-8")
    return "\n".join(
        line for line in script.splitlines() if not line.strip().startswith("//")
    )


def sent_by(form: Tag) -> dict[str, str]:
    """What a browser sends: every named input's value."""
    sent: dict[str, str] = {}
    for control in form.find_all("input"):
        name = control.get("name")
        if isinstance(name, str):
            value = control.get("value")
            sent[name] = value if isinstance(value, str) else ""
    return sent


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


def test_each_document_says_where_the_index_stands(
    client: TestClient, states: dict[str, str]
):
    tree = tree_of(client)

    assert row_of(tree, states["quiet"])["data-state"] == ""
    assert row_of(tree, states["edited"])["data-state"] == "changed"
    assert row_of(tree, states["later"])["data-state"] == "unindexed"


def test_a_state_is_a_letter_with_its_reason(
    client: TestClient, states: dict[str, str]
):
    mark = own_mark(row_of(tree_of(client), states["edited"]))

    assert mark is not None
    assert mark.get_text() == EXPECTED_LETTERS["changed"]
    assert mark["title"] == words.STATE_WORDS["changed"]
    assert "role-changed" in classes(mark)


def test_the_letters_are_the_ones_written_down():
    assert words.STATE_LETTERS == EXPECTED_LETTERS


def test_a_quiet_document_carries_no_mark(client: TestClient, states: dict[str, str]):
    row = row_of(tree_of(client), states["quiet"])

    assert own_mark(row) is None
    assert "quiet" in classes(row)


def test_a_wrapped_document_is_named_by_its_directory(client: TestClient, corpus: Path):
    """git names a wrapped document by its wrapper; looking it up by its
    `content.md` would find nothing and call a changed document quiet."""
    source = corpus / "sources" / "Wrapped.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("# Wrapped\n\nBody.\n", encoding="utf-8")
    added = CliRunner().invoke(
        main, ["corpus", "add", "-n", str(source), "--keep-original"]
    )
    assert added.exit_code == 0, added.output
    assert CliRunner().invoke(main, ["corpus", "index"]).exit_code == 0
    held = Collection(root=existing_corpus().corpus_root, name="notes").contents()
    wrapped = next(d for d in held.documents if d.wrapper_dir is not None)
    wrapped.md_path.write_text(
        wrapped.md_path.read_text(encoding="utf-8") + "\nMore.\n", encoding="utf-8"
    )

    assert row_of(tree_of(client), wrapped.id)["data-state"] == "changed"


def test_a_note_written_and_indexed_in_one_command_is_quiet(
    client: TestClient, corpus: Path
):
    """`remember` writes, indexes, then commits, so the index's recorded
    commit is the one before the note: the diff lists it as added. The
    manifest's digests are what say it is held (#245)."""
    add_note(corpus, "First", "So there is an index to add to.")
    assert CliRunner().invoke(main, ["corpus", "index"]).exit_code == 0
    told = CliRunner().invoke(
        main, ["remember", "Calibration converged.", "--title", "Kept"]
    )
    assert told.exit_code == 0, told.output
    held = Collection(root=existing_corpus().corpus_root, name="notes").contents()
    kept = next(d.id for d in held.documents if d.frontmatter.title == "Kept")

    assert row_of(tree_of(client), kept)["data-state"] == ""


def test_a_collection_never_indexed_has_every_document_unindexed(
    client: TestClient, corpus: Path
):
    """No manifest at all: there is nothing in step, so nothing is quiet."""
    first = add_note(corpus, "One", "A note.")
    second = add_note(corpus, "Two", "Another.")
    tree = tree_of(client)

    assert row_of(tree, first)["data-state"] == "unindexed"
    assert row_of(tree, second)["data-state"] == "unindexed"


def test_an_index_that_cannot_be_checked_marks_nothing(
    client: TestClient, states: dict[str, str], monkeypatch: pytest.MonkeyPatch
):
    """Its commit is not in this corpus: there is no per-document answer,
    and guessing one would mark documents on no evidence."""
    monkeypatch.setattr(Repository, "has_commit", lambda self, commit: False)
    tree = tree_of(client)

    assert row_of(tree, states["edited"])["data-state"] == ""
    assert row_of(tree, states["later"])["data-state"] == ""


def test_the_states_agree_with_corpus_status(
    client: TestClient, states: dict[str, str]
):
    """One rule, two readers: the tree's marks are the sets whose sizes
    `corpus status` prints.

    Status counts the unreadable file among the added - git sees a new
    file the index does not hold - and the tree marks it with the worse
    of its two states. So added is the new ones plus the unreadable."""
    tree = tree_of(client)
    marked = [row["data-state"] for row in tree.select("li.row")]
    status = CliRunner().invoke(main, ["corpus", "status"]).output

    assert marked.count("changed") == 1
    assert marked.count("unindexed") + marked.count("unreadable") == 2
    assert "1 document changed, 2 documents added" in status, status


def test_an_unreadable_document_is_in_the_tree(
    client: TestClient, states: dict[str, str]
):
    """It was a count beneath the tree; a count cannot be found."""
    rows = tree_of(client).select('li.row[data-state="unreadable"]')

    assert len(rows) == 1
    assert "Broken.md" in rows[0].get_text()
    mark = own_mark(rows[0])
    assert mark is not None
    assert mark.get_text() == EXPECTED_LETTERS["unreadable"]
    assert rows[0].find("a") is None


def test_a_group_shows_the_worst_beneath_it_and_how_many(
    client: TestClient, states: dict[str, str]
):
    summary = group_of(tree_of(client), "botany").find("summary")
    assert isinstance(summary, Tag)
    mark = summary.find("span", class_="doc-state")

    # Changed is worse than not yet indexed: the index answers with text a
    # changed document no longer has, and merely without a new one.
    assert isinstance(mark, Tag), summary
    assert mark.get_text() == EXPECTED_LETTERS["changed"]
    assert mark["title"] == words.attention_count(2)
    assert summary.find("span", class_="count").get_text() == "3"


def test_unreadable_is_the_worst_of_all(client: TestClient, states: dict[str, str]):
    broken = existing_corpus().corpus_root / "notes" / "botany" / "Also broken.md"
    broken.write_text("---\nid: [unclosed\n---\n\nBody.\n", encoding="utf-8")
    summary = group_of(tree_of(client), "botany").find("summary")
    assert isinstance(summary, Tag)
    mark = summary.find("span", class_="doc-state")

    assert isinstance(mark, Tag)
    assert mark.get_text() == EXPECTED_LETTERS["unreadable"]
    assert mark["title"] == words.attention_count(3)


def test_a_quiet_group_is_quiet(client: TestClient, corpus: Path):
    add_note(corpus, "Settled", "In step.", group="settled")
    assert CliRunner().invoke(main, ["corpus", "index"]).exit_code == 0
    group = group_of(tree_of(client), "settled")

    assert "quiet" in classes(group)
    assert group.find("span", class_="doc-state") is None


def test_the_filter_hides_what_is_quiet_without_a_script(
    client: TestClient, states: dict[str, str]
):
    tree = tree_of(client)
    sheet = client.get("/static/kennis.css").text
    box = tree.find("input", class_="attention-only")

    assert isinstance(box, Tag)
    assert box["type"] == "checkbox"
    assert words.ATTENTION_ONLY in tree.get_text()
    assert re.search(
        r"\.branch:has\(\.attention-only:checked\) \.quiet \{ display: none; \}", sheet
    )


def test_there_is_no_filter_when_nothing_needs_attention(
    client: TestClient, corpus: Path
):
    add_note(corpus, "Settled", "In step.")
    assert CliRunner().invoke(main, ["corpus", "index"]).exit_code == 0

    assert tree_of(client).find("input", class_="attention-only") is None


# ---------------------------------------------------------------------------
# The menu
# ---------------------------------------------------------------------------


def test_a_document_menu_offers_the_four_actions(
    client: TestClient, states: dict[str, str]
):
    assert menu_labels(row_of(tree_of(client), states["quiet"])) == EXPECTED_MENU


def test_a_group_menu_offers_adding_and_indexing(
    client: TestClient, states: dict[str, str]
):
    """The group's own menu, not the first menu of a document inside it."""
    assert menu_labels(group_of(tree_of(client), "botany")) == EXPECTED_GROUP_MENU


def test_a_group_menu_is_reachable_while_the_group_is_closed(
    client: TestClient, states: dict[str, str]
):
    """A menu inside the folder's `<details>` would be hidden with its
    contents whenever the folder is closed: it must be the row's own
    child, beside the folder."""
    group = group_of(tree_of(client), "botany")

    assert own_menu(group).parent is group


def test_the_words_of_the_menu_are_the_ones_written_down():
    assert [
        words.MENU_OPEN,
        words.MENU_MOVE,
        words.MENU_ADD_HERE,
        words.MENU_INDEX,
    ] == EXPECTED_MENU


def a_docs_page(project: str, page: str) -> str:
    identifier = f"docs{project}{page}"
    frontmatter = DocsFrontmatter.model_validate(
        {
            "id": identifier,
            "title": f"{project} {page}",
            "owner": "user",
            "source": {"from": "url:https://x/y", "via": "html", "format": "html"},
            "docs": {"project": project, "page": page},
        }
    )
    docs = existing_corpus().corpus_root / "docs"
    write_document(
        docs / project / f"{page}.md", frontmatter=frontmatter, body="How.\n"
    )
    return identifier


def test_a_docs_page_is_not_offered_a_move(client: TestClient, corpus: Path):
    """Its directory is its project, which is part of its identity (#101)."""
    identifier = a_docs_page("numpy", "indexing")
    tree = tree_of(client, "docs")

    assert menu_labels(row_of(tree, identifier)) == EXPECTED_DOCS_MENU
    assert tree.find("form", class_="move") is None


def test_the_menu_button_is_named_and_reachable_by_keyboard(
    client: TestClient, states: dict[str, str]
):
    """A `<summary>` is focusable and opens on Enter with no script."""
    button = own_menu(row_of(tree_of(client), states["quiet"])).find(
        "summary", recursive=False
    )

    assert isinstance(button, Tag)
    assert "menu-button" in classes(button)
    assert button["aria-label"] == words.menu_for("Quiet")


def move_form(row: Tag) -> Tag:
    form = own_menu(row).find("form", class_="move")
    assert isinstance(form, Tag), row
    return form


def test_moving_as_drawn_refiles_the_document_and_redraws_the_branch(
    client: TestClient, states: dict[str, str]
):
    """The form the menu drew, sent where it says, with a group typed in."""
    form = move_form(row_of(tree_of(client), states["quiet"]))
    sent = sent_by(form)
    sent["group"] = "botany"
    head = existing_corpus().corpus_root

    answer = client.post(str(form["hx-post"]), data=sent, headers=HTMX)

    assert answer.status_code == 200, answer.text
    assert path_of(states["quiet"]).parent == head / "notes" / "botany"
    redrawn = BeautifulSoup(answer.text, "html.parser")
    assert row_of(group_of(redrawn, "botany"), states["quiet"])
    assert "move" in CliRunner().invoke(main, ["corpus", "history"]).output


def test_the_move_form_targets_its_branch_and_works_without_a_script(
    client: TestClient, states: dict[str, str]
):
    form = move_form(row_of(tree_of(client), states["quiet"]))

    assert form["action"] == form["hx-post"] == "/move"
    assert form["method"] == "post"
    assert form["hx-target"] == "closest .branch"
    assert sorted(sent_by(form)) == ["collection", "document", "group"]


def test_a_move_to_the_top_level_is_an_empty_group(
    client: TestClient, states: dict[str, str]
):
    head = existing_corpus().corpus_root
    client.post(
        "/move",
        data={"collection": "notes", "document": states["later"], "group": ""},
        headers=HTMX,
    )

    assert path_of(states["later"]).parent == head / "notes"


def test_a_move_redraws_the_strip_and_the_pane_with_the_branch(
    client: TestClient, states: dict[str, str]
):
    """After a move the document showed "U" while the pane's dot and the
    strip still said searchable, until the page was reloaded."""
    answer = client.post(
        "/move",
        data={"collection": "notes", "document": states["later"], "group": "moved"},
        headers=HTMX,
    )
    redrawn = BeautifulSoup(answer.text, "html.parser")

    assert redrawn.find(id="strip-status", attrs={"hx-swap-oob": "true"})
    assert redrawn.find(id="pane-row-notes", attrs={"hx-swap-oob": "true"})


def test_a_refused_move_redraws_only_its_branch(
    client: TestClient, states: dict[str, str]
):
    answer = client.post(
        "/move",
        data={"collection": "notes", "document": states["later"], "group": "../x"},
        headers=HTMX,
    )

    assert 'hx-swap-oob="true"' not in answer.text


@pytest.mark.parametrize("group", ["../escape", "/abs", "a/../../b", ".hidden"])
def test_a_group_that_leaves_the_collection_is_refused_in_the_branch(
    client: TestClient, states: dict[str, str], group: str
):
    before = path_of(states["quiet"])
    answer = client.post(
        "/move",
        data={"collection": "notes", "document": states["quiet"], "group": group},
        headers=HTMX,
    )
    redrawn = BeautifulSoup(answer.text, "html.parser")
    problem = redrawn.find("p", class_="role-error")
    reason = group_problem(group)

    assert reason is not None
    assert isinstance(problem, Tag), answer.text
    assert reason in unescape(problem.get_text())
    assert path_of(states["quiet"]) == before
    # The branch is redrawn under the refusal, so the tree is not lost.
    assert row_of(redrawn, states["quiet"])


def test_a_move_without_a_script_returns_to_the_collection(
    client: TestClient, states: dict[str, str]
):
    answer = client.post(
        "/move", data={"collection": "notes", "document": states["quiet"], "group": "x"}
    )

    assert answer.status_code == 303
    assert answer.headers["location"] == "/collection/notes"


def test_a_refused_move_without_a_script_is_a_page(
    client: TestClient, states: dict[str, str]
):
    answer = client.post(
        "/move",
        data={"collection": "notes", "document": states["quiet"], "group": "../x"},
    )

    assert 'class="shell"' in answer.text


def test_the_groups_held_are_offered_to_type_into(
    client: TestClient, states: dict[str, str]
):
    tree = tree_of(client)
    field = move_form(row_of(tree, states["quiet"])).find(
        "input", attrs={"name": "group"}
    )
    assert isinstance(field, Tag)
    offered = tree.find("datalist", id=str(field["list"]))

    assert isinstance(offered, Tag)
    assert [option["value"] for option in offered.find_all("option")] == ["botany"]


def add_here_link(menu_owner: Tag) -> Tag:
    for item in own_menu(menu_owner).select("a.item"):
        if item.get_text(strip=True) == words.MENU_ADD_HERE:
            return item
    raise AssertionError(menu_owner)


def test_add_here_fills_in_the_collection_and_the_group(
    client: TestClient, states: dict[str, str]
):
    link = add_here_link(group_of(tree_of(client), "botany"))
    assert link["hx-target"] == "#dialog"

    dialog = BeautifulSoup(
        client.get(str(link["href"]), headers=HTMX).text, "html.parser"
    )
    checked = dialog.find("input", attrs={"name": "collection", "checked": True})
    group = dialog.find("input", attrs={"name": "group"})

    assert isinstance(checked, Tag) and checked["value"] == "notes"
    assert isinstance(group, Tag) and group["value"] == "botany"


def test_add_here_on_a_docs_project_opens_the_site_tab_with_the_project(
    client: TestClient, corpus: Path
):
    a_docs_page("numpy", "indexing")
    link = add_here_link(group_of(tree_of(client, "docs"), "numpy"))

    dialog = BeautifulSoup(
        client.get(str(link["href"]), headers=HTMX).text, "html.parser"
    )
    project = dialog.find("input", attrs={"name": "project"})
    current = dialog.find("a", attrs={"aria-current": "page"})

    assert isinstance(project, Tag) and project["value"] == "numpy"
    assert isinstance(current, Tag) and "kind=site" in str(current["href"])


def test_an_unoffered_collection_fills_in_nothing(client: TestClient, corpus: Path):
    """The address is the reader's to edit; a collection the File tab does
    not offer is left unchosen rather than drawn as no radio checked."""
    dialog = BeautifulSoup(
        client.get("/add?kind=file&collection=elsewhere", headers=HTMX).text,
        "html.parser",
    )

    assert dialog.find("input", attrs={"name": "collection", "checked": True}) is None


def test_index_this_collection_posts_the_collection(
    client: TestClient, states: dict[str, str]
):
    form = own_menu(row_of(tree_of(client), states["quiet"])).find(
        "form", class_="index"
    )

    assert isinstance(form, Tag)
    assert form["hx-post"] == form["action"] == "/index"
    assert form["hx-target"] == "#job"
    assert sent_by(form) == {"collection": "notes"}


def test_the_branch_does_not_inherit_the_pane_target(client: TestClient):
    """The `<details>` the branch arrives in targets `find .branch`; a form
    inside it that named no target of its own would inherit that (#430)."""
    page = BeautifulSoup(client.get("/").text, "html.parser")
    holders = page.select("details[hx-get^='/tree/']")

    assert holders
    assert all(holder.get("hx-disinherit") == "*" for holder in holders)


def test_the_menu_script_opens_on_right_click_and_composes_no_words(client: TestClient):
    code = code_of("menu.js")

    assert '"contextmenu"' in code
    assert '"Escape"' in code
    assert not re.search(r"\"[A-Za-z]+ [A-Za-z ]+\"", code)
    assert '<script defer src="/static/menu.js"></script>' in client.get("/").text


def test_a_move_says_which_document_deleted_by_hand_it_put_back(
    client: TestClient, states: dict[str, str]
):
    deleted = path_of(states["quiet"])
    named = deleted.relative_to(existing_corpus().corpus_root).as_posix()
    deleted.unlink()

    answer = client.post(
        "/move",
        data={"collection": "notes", "document": states["later"], "group": "moved"},
        headers=HTMX,
    )

    assert f"{named} was deleted outside kennis and has been restored" in answer.text
