"""A pack's context is searched where it lives (14g, #513).

A project declares the packs it uses; its context search reads its own
bundle and each declared pack's `context:` content from the store, a group
for each. Nothing is copied into the project. A project replaces one pack
file by copying it into its bundle as its own; the original is then hidden
in that project only.
"""

from __future__ import annotations

import html
import re
import shutil
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from click.testing import CliRunner
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.engine.context.bundle import declare_packs, init_bundle
from kennis.engine.context.notes import remember_in_bundle
from kennis.engine.frontmatter import split_frontmatter
from kennis.engine.pack.content import content_digest
from kennis.engine.pack.store import pack_root
from kennis.engine.pack.update import update_pack
from kennis.gui.app import build_app
from kennis.retrieval import sweep


@pytest.fixture(autouse=True)
def no_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KENNIS_CONTEXT_DIR", raising=False)


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "corpus"
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(root))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    answered = CliRunner().invoke(main, ["corpus", "init"])
    assert answered.exit_code == 0, answered.output
    return root


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project with a bundle, the working directory of every test."""
    root = tmp_path / "pipelines"
    (root / ".git").mkdir(parents=True)
    init_bundle(root)
    monkeypatch.chdir(root)
    return root / ".context"


def a_pack(
    root: Path, identifier: str = "alpha", files: dict[str, str] | None = None
) -> Path:
    """A pack shipping context content, rebuilt from scratch each time."""
    if root.exists():
        shutil.rmtree(root)
    for relative, text in (
        files or {"content/solving.md": "Solve the gains per scan.\n"}
    ).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    path = root / f"{identifier}.ken.yml"
    path.write_text(
        "kennis:\n  schema_version: 1\n"
        f'pack:\n  id: {identifier}\n  name: n\n  version: "1.0.0"\n'
        "context:\n  - source: content/\n",
        encoding="utf-8",
    )
    update_pack(path)
    return path


def installed(
    tmp_path: Path, identifier: str = "alpha", files: dict[str, str] | None = None
) -> None:
    path = a_pack(tmp_path / "providers" / identifier, identifier, files)
    answered = CliRunner().invoke(main, ["pack", "add", str(path)])
    assert answered.exit_code == 0, answered.output


def context_sweep(project: Path, question: str = "gains") -> dict[str, list[str]]:
    """Each context group's document ids, for `question`."""
    found = sweep(question, scopes=["context"], named=False, bundle=project)
    return {
        name: [hit.result.chunk.document_id for hit in hits]
        for name, hits in found.groups.items()
    }


# ---------------------------------------------------------------------------
# Searching


def test_a_declared_pack_s_context_is_its_own_group(
    corpus: Path, project: Path, tmp_path: Path
):
    installed(tmp_path)
    declare_packs(project, ["alpha"])

    groups = context_sweep(project)

    assert groups.get("pack:alpha") == ["solving.md"]


def test_a_pack_the_project_does_not_declare_is_not_searched(
    corpus: Path, project: Path, tmp_path: Path
):
    installed(tmp_path)
    remember_in_bundle(project, "Our gains drift at night.", title=None, group=None)
    assert CliRunner().invoke(main, ["context", "index"]).exit_code == 0

    groups = context_sweep(project)

    assert set(groups) == {"context"}


def test_the_project_s_own_notes_and_the_pack_are_separate_groups(
    corpus: Path, project: Path, tmp_path: Path
):
    """Each with its own scale: a keyword band is relative to the best match
    in one index, so two indexes in one list would compare unlike things."""
    installed(tmp_path)
    declare_packs(project, ["alpha"])
    remember_in_bundle(project, "Our gains drift at night.", title=None, group=None)
    assert CliRunner().invoke(main, ["context", "index"]).exit_code == 0

    groups = context_sweep(project)

    assert set(groups) == {"context", "pack:alpha"}
    assert groups["pack:alpha"] == ["solving.md"]


def test_nothing_of_the_pack_is_copied_into_the_project(
    corpus: Path, project: Path, tmp_path: Path
):
    installed(tmp_path)
    declare_packs(project, ["alpha"])

    context_sweep(project)
    answered = CliRunner().invoke(main, ["context", "sync"])

    assert answered.exit_code == 0, answered.output
    assert not (project / "solving.md").exists()


def test_the_pack_s_index_is_built_in_the_store_on_first_search(
    corpus: Path, project: Path, tmp_path: Path
):
    installed(tmp_path)
    declare_packs(project, ["alpha"])
    assert not (pack_root(corpus, "alpha") / ".index").exists()

    context_sweep(project)

    assert (pack_root(corpus, "alpha") / ".index").is_dir()


def test_a_new_release_of_the_pack_is_what_is_searched(
    corpus: Path, project: Path, tmp_path: Path
):
    installed(tmp_path)
    declare_packs(project, ["alpha"])
    assert context_sweep(project)["pack:alpha"] == ["solving.md"]

    installed(tmp_path, files={"content/flagging.md": "Flag before solving gains.\n"})

    assert context_sweep(project)["pack:alpha"] == ["flagging.md"]


def test_a_declared_pack_that_is_not_installed_is_said_and_skipped(
    corpus: Path, project: Path, tmp_path: Path
):
    installed(tmp_path)
    declare_packs(project, ["alpha", "gamma"])

    found = sweep("gains", scopes=["context"], named=False, bundle=project)

    assert "pack:alpha" in found.groups
    assert [skipped.name for skipped in found.skipped] == ["pack:gamma"]


# ---------------------------------------------------------------------------
# A project's own version of a pack file


def test_copying_a_pack_file_makes_it_the_project_s_own(
    corpus: Path, project: Path, tmp_path: Path
):
    installed(tmp_path)
    declare_packs(project, ["alpha"])

    answered = CliRunner().invoke(main, ["context", "copy", "alpha/solving.md"])

    assert answered.exit_code == 0, answered.output
    header, body = split_frontmatter(
        (project / "solving.md").read_text(encoding="utf-8")
    )
    assert header["owner"] == "user"
    assert header["replaces"] == "pack:alpha/solving.md"
    assert body == "Solve the gains per scan.\n"


def test_a_project_s_copy_hides_the_pack_s_original_there(
    corpus: Path, project: Path, tmp_path: Path
):
    installed(tmp_path)
    declare_packs(project, ["alpha"])
    assert (
        CliRunner().invoke(main, ["context", "copy", "alpha/solving.md"]).exit_code == 0
    )
    assert CliRunner().invoke(main, ["context", "index"]).exit_code == 0

    groups = context_sweep(project)

    assert groups.get("context") == ["solving.md"]
    assert "pack:alpha" not in groups


def test_copying_a_file_the_pack_does_not_ship_is_refused(
    corpus: Path, project: Path, tmp_path: Path
):
    installed(tmp_path)
    declare_packs(project, ["alpha"])

    answered = CliRunner().invoke(main, ["context", "copy", "alpha/absent.md"])

    assert answered.exit_code != 0
    assert "absent.md" in answered.output
    assert not (project / "absent.md").exists()


# ---------------------------------------------------------------------------
# What sync does now


def test_sync_removes_the_copies_an_older_kennis_wrote(
    corpus: Path, project: Path, tmp_path: Path
):
    installed(tmp_path)
    declare_packs(project, ["alpha"])
    (project / "solving.md").write_text(
        "---\ntitle: solving\nowner: pack:alpha\nsource:\n  via: pack\n"
        "  pack: alpha\n  address: solving.md\n"
        f"  sha256: {_digest('Solve the gains per scan.')}\n"
        "---\nSolve the gains per scan.\n",
        encoding="utf-8",
    )

    answered = CliRunner().invoke(main, ["context", "sync"])

    assert answered.exit_code == 0, answered.output
    assert not (project / "solving.md").exists()


def test_sync_keeps_a_copy_the_person_edited_and_says_so(
    corpus: Path, project: Path, tmp_path: Path
):
    installed(tmp_path)
    declare_packs(project, ["alpha"])
    (project / "solving.md").write_text(
        "---\ntitle: solving\nowner: pack:alpha\nsource:\n  via: pack\n"
        "  pack: alpha\n  address: solving.md\n"
        f"  sha256: {_digest('Solve the gains per scan.')}\n"
        "---\nSolve the gains per scan, and per band.\n",
        encoding="utf-8",
    )

    answered = CliRunner().invoke(main, ["context", "sync"])

    assert answered.exit_code == 0, answered.output
    assert (project / "solving.md").exists()
    assert "solving.md" in answered.output


def test_sync_in_a_project_that_declares_nothing_says_how_to_declare(
    corpus: Path, project: Path, tmp_path: Path
):
    installed(tmp_path)

    answered = CliRunner().invoke(main, ["context", "sync"])

    assert answered.exit_code == 0, answered.output
    assert "kennis context packs alpha" in answered.output


def _digest(text: str) -> str:
    """What a sync records of a body it wrote."""
    return content_digest(f"{text}\n".encode())


# ---------------------------------------------------------------------------
# The window


TOKEN = "a-test-token"


@pytest.fixture
def window(corpus: Path, project: Path, tmp_path: Path) -> TestClient:
    """The window, with alpha declared by the one known project."""
    installed(tmp_path)
    declare_packs(project, ["alpha"])
    client = TestClient(build_app(TOKEN), follow_redirects=False)
    assert client.get("/", params={"token": TOKEN}).status_code == 200
    return client


def test_a_pack_hit_in_the_window_is_its_own_group_and_links_to_the_file(
    window: TestClient,
):
    found = window.get("/hits", params={"q": "gains", "scope": "context"})

    page = BeautifulSoup(found.text, "html.parser")
    heads = [head.select_one(".name") for head in page.select("h2.group-head")]
    assert [head.get_text() for head in heads if head] == ["pack alpha"]
    links = [
        str(link["href"])
        for link in page.select("li.hit a.title")
        if link.has_attr("href")
    ]
    assert links and links[0].startswith("/pack/alpha/solving.md?")


def test_a_pack_hit_s_page_shows_the_file_with_its_passage_marked(
    window: TestClient,
):
    found = window.get("/hits", params={"q": "gains", "scope": "context"})
    (link,) = re.findall(r'href="(/pack/[^"]*)"', found.text)[:1]

    page = window.get(html.unescape(link))

    assert page.status_code == 200
    assert (
        "Solve the gains per scan."
        in BeautifulSoup(page.text, "html.parser").get_text()
    )
    assert 'class="chunk"' in page.text
    assert "kennis context copy alpha/solving.md" in page.text


def test_a_pack_path_cannot_reach_beyond_the_pack_s_files(window: TestClient):
    """Looked up among the files the pack declares, so a traversal names
    no file at all."""
    for attempt in (
        "/pack/alpha/../../../etc/passwd",
        "/pack/alpha/..%2f..%2falpha.ken.yml",
        "/pack/alpha/missing.md",
    ):
        page = window.get(attempt)
        assert "root:" not in page.text, attempt
        assert "schema_version" not in page.text, attempt


def test_a_pack_file_s_breadcrumb_leads_somewhere_that_answers(window: TestClient):
    page = BeautifulSoup(window.get("/pack/alpha/solving.md").text, "html.parser")
    crumb = page.select_one(".crumbs .crumb-collection")

    assert crumb is not None
    assert crumb.get_text() == "pack alpha"
    href = str(crumb["href"])
    assert window.get(href.split("#")[0]).status_code == 200


def test_a_bundle_note_s_breadcrumb_is_not_a_link_to_a_page_that_refuses(
    window: TestClient, project: Path
):
    """There is no page for the bundle, and `/collection/context` answered
    "unknown collection"."""
    remember_in_bundle(project, "Our gains drift at night.", title=None, group=None)
    assert CliRunner().invoke(main, ["context", "index"]).exit_code == 0
    (note,) = [
        path
        for path in project.glob("*.md")
        if path.name != "LANDING.md" and not path.name.startswith(".")
    ]

    page = BeautifulSoup(
        window.get(f"/bundle/{note.name}", params={"project": "pipelines"}).text,
        "html.parser",
    )
    crumb = page.select_one(".crumbs .crumb-collection")

    assert crumb is not None
    assert crumb.name == "span"
    assert crumb.get_text() == "pipelines/.context"
