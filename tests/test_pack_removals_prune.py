"""What a sync removes for a pack takes its emptied folders with it, and a
pack's docs are declared, kept and removed by version (Brian, 2026-10-28).

Measured before this: a removed note left `notes/<pack>/<group>/` empty;
two versions of one project were one declaration, so the second was never
added; and a version its pack dropped stayed, restamped as the pack still
declaring the project, while a removal of the project would have taken every
version, the person's own among them.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import httpx
import pytest
from click.testing import CliRunner

from kennis import operations
from kennis.cli.__main__ import main
from kennis.context import existing_corpus
from kennis.engine.corpus.add import AddOptions, add_docs
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.document import Document
from kennis.engine.corpus.schema import DocsFrontmatter
from kennis.engine.corpus.sync import CorpusSync, sync_corpus
from kennis.engine.docs.versions import current_version_file, make_current
from kennis.engine.history.repository import initialise_corpus
from kennis.engine.pack.installed import uninstall_pack
from kennis.engine.pack.store import install_pack
from kennis.engine.pack.update import update_pack

FILES: dict[str, bytes] = {
    "files/notes/one.md": b"# One\n\nA note about calibration.\n",
    "files/notes/two.md": b"# Two\n\nA note about imaging.\n",
    "files/literature/rime.md": b"# Revisiting the RIME\n\nThe Jones formalism.\n",
    "files/docs/guide-1.md": b"# Guide one\n\nHow to use version one.\n",
    "files/docs/guide-2.md": b"# Guide two\n\nHow to use version two.\n",
}


def note(file: str, group: str) -> str:
    return f'    - {{file: "files/notes/{file}", group: "{group}"}}\n'


def paper(group: str) -> str:
    return (
        "    - citekey: smirnovRevisitingRIMEI2011\n"
        '      title: "Revisiting the RIME"\n'
        '      authors: ["Smirnov, O. M."]\n'
        "      year: 2011\n"
        '      identifier: "1101.1764"\n'
        "      file: files/literature/rime.md\n"
        f"      group: {group}\n"
    )


def docs(version: str) -> str:
    return (
        f'    - {{project: "tool", version: "{version}", '
        f'pages: ["files/docs/guide-{version[0]}.md"]}}\n'
    )


def a_pack(root: Path, pack_id: str, sections: dict[str, str]) -> Path:
    """A pack `pack_id` at `root`, shipping every file in FILES, declaring
    `sections` (a section's name to its entries), and updated."""
    if root.exists():
        shutil.rmtree(root)
    for relative, data in FILES.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    body = "".join(
        f"  {name}:\n{entries}" for name, entries in sections.items() if entries
    )
    path = root / f"{pack_id}.ken.yml"
    path.write_text(
        "kennis:\n  schema_version: 1\npack:\n"
        f'  id: {pack_id}\n  name: n\n  version: "1.0.0"\n'
        + ("corpus:\n" + body if body else ""),
        encoding="utf-8",
    )
    update_pack(path)
    return path


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    root.mkdir()
    initialise_corpus(root)
    return root


def synced(corpus: Path) -> CorpusSync:
    nowhere = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(404))
    )
    return sync_corpus(corpus, arxiv=nowhere, client=nowhere, request_delay_seconds=0)


def pages(corpus: Path) -> list[Document]:
    return list(Collection(root=corpus, name="docs").contents().documents)


def versions_of(corpus: Path) -> dict[str, str | None]:
    """Each docs page's version, by title, and whose it is."""
    found: dict[str, str | None] = {}
    for page in pages(corpus):
        frontmatter = page.frontmatter
        assert isinstance(frontmatter, DocsFrontmatter)
        found[f"{frontmatter.docs.version}:{frontmatter.title}"] = frontmatter.owner
    return found


def folders_under(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_dir()
    }


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


def test_a_removed_note_takes_the_groups_it_emptied(corpus: Path, tmp_path: Path):
    both = {"notes": note("one.md", "deep/nested") + note("two.md", "kept")}
    install_pack(corpus, a_pack(tmp_path / "alpha", "alpha", both))
    synced(corpus)
    assert {"alpha/deep/nested", "alpha/kept"} <= folders_under(corpus / "notes")

    install_pack(
        corpus, a_pack(tmp_path / "alpha", "alpha", {"notes": note("two.md", "kept")})
    )
    report = synced(corpus)

    assert report.counts.get("delete") == 1, report.counts
    assert folders_under(corpus / "notes") == {"alpha", "alpha/kept"}


def test_the_pack_s_own_folder_goes_with_its_last_document(
    corpus: Path, tmp_path: Path
):
    install_pack(
        corpus, a_pack(tmp_path / "alpha", "alpha", {"notes": note("one.md", "a/b")})
    )
    synced(corpus)
    # Without its `.gitkeep` the collection is empty too, and still stays.
    (corpus / "notes" / ".gitkeep").unlink()

    uninstall_pack(corpus, "alpha")
    synced(corpus)

    assert folders_under(corpus / "notes") == set()
    assert (corpus / "notes").is_dir()


def test_a_paper_moved_to_another_group_leaves_no_empty_one(
    corpus: Path, tmp_path: Path
):
    install_pack(
        corpus, a_pack(tmp_path / "alpha", "alpha", {"literature": paper("old/deep")})
    )
    synced(corpus)
    assert "alpha/old/deep" in folders_under(corpus / "literature")

    install_pack(
        corpus, a_pack(tmp_path / "alpha", "alpha", {"literature": paper("new")})
    )
    synced(corpus)

    held = folders_under(corpus / "literature")
    assert not any(folder.startswith("alpha/old") for folder in held), held
    assert "alpha/new" in held


def test_a_folder_the_person_made_is_left_alone(corpus: Path, tmp_path: Path):
    """Only what a removal empties goes: an empty folder the person made,
    or one holding a file of theirs, is not kennis's to remove."""
    (corpus / "notes" / "ideas").mkdir()
    install_pack(
        corpus, a_pack(tmp_path / "alpha", "alpha", {"notes": note("one.md", "g")})
    )
    synced(corpus)
    (corpus / "notes" / "alpha" / "g" / "scratch.txt").write_text("mine\n")

    uninstall_pack(corpus, "alpha")
    synced(corpus)

    assert folders_under(corpus / "notes") == {"ideas", "alpha", "alpha/g"}


# ---------------------------------------------------------------------------
# Docs, by version
# ---------------------------------------------------------------------------


def test_two_versions_of_one_project_are_both_added(corpus: Path, tmp_path: Path):
    install_pack(
        corpus,
        a_pack(tmp_path / "alpha", "alpha", {"docs": docs("1.0") + docs("2.0")}),
    )

    report = synced(corpus)

    assert report.failed == ()
    assert versions_of(corpus) == {
        "1.0:Guide one": "pack:alpha",
        "2.0:Guide two": "pack:alpha",
    }


def test_a_dropped_version_goes_and_another_pack_s_version_stays(
    corpus: Path, tmp_path: Path
):
    install_pack(
        corpus,
        a_pack(tmp_path / "alpha", "alpha", {"docs": docs("1.0") + docs("2.0")}),
    )
    install_pack(corpus, a_pack(tmp_path / "beta", "beta", {"docs": docs("2.0")}))
    synced(corpus)

    install_pack(corpus, a_pack(tmp_path / "alpha", "alpha", {}))
    synced(corpus)

    assert versions_of(corpus) == {"2.0:Guide two": "pack:beta"}
    assert folders_under(corpus / "docs") == {"tool", "tool/2.0"}


def test_a_version_two_packs_declare_stays_when_one_drops_it(
    corpus: Path, tmp_path: Path
):
    install_pack(corpus, a_pack(tmp_path / "alpha", "alpha", {"docs": docs("2.0")}))
    install_pack(corpus, a_pack(tmp_path / "beta", "beta", {"docs": docs("2.0")}))
    synced(corpus)
    assert versions_of(corpus) == {"2.0:Guide two": "pack:alpha"}

    uninstall_pack(corpus, "alpha")
    synced(corpus)

    assert versions_of(corpus) == {"2.0:Guide two": "pack:beta"}


def test_the_last_version_takes_its_project_and_its_record(
    corpus: Path, tmp_path: Path
):
    install_pack(corpus, a_pack(tmp_path / "alpha", "alpha", {"docs": docs("2.0")}))
    synced(corpus)
    make_current(corpus / "docs", "tool", "2.0")

    uninstall_pack(corpus, "alpha")
    synced(corpus)

    assert pages(corpus) == []
    assert folders_under(corpus / "docs") == set()
    assert not current_version_file(corpus / "docs", "tool").exists()


def test_a_project_left_with_only_a_stale_record_goes(corpus: Path, tmp_path: Path):
    """A record naming a version no longer held keeps nothing alive."""
    install_pack(corpus, a_pack(tmp_path / "alpha", "alpha", {"docs": docs("2.0")}))
    synced(corpus)
    make_current(corpus / "docs", "tool", "1.0")

    uninstall_pack(corpus, "alpha")
    synced(corpus)

    assert not (corpus / "docs" / "tool").exists()


def test_a_record_naming_the_dropped_version_goes_and_one_naming_another_stays(
    corpus: Path, tmp_path: Path
):
    install_pack(
        corpus,
        a_pack(tmp_path / "alpha", "alpha", {"docs": docs("1.0") + docs("2.0")}),
    )
    synced(corpus)
    make_current(corpus / "docs", "tool", "1.0")

    install_pack(corpus, a_pack(tmp_path / "alpha", "alpha", {"docs": docs("2.0")}))
    synced(corpus)
    assert not current_version_file(corpus / "docs", "tool").exists()

    install_pack(
        corpus,
        a_pack(tmp_path / "alpha", "alpha", {"docs": docs("1.0") + docs("2.0")}),
    )
    synced(corpus)
    make_current(corpus / "docs", "tool", "2.0")
    install_pack(corpus, a_pack(tmp_path / "alpha", "alpha", {"docs": docs("2.0")}))
    synced(corpus)

    record = current_version_file(corpus / "docs", "tool")
    assert record.read_text(encoding="utf-8").strip() == "2.0"


def test_a_page_of_the_person_s_keeps_a_dropped_version_and_stays_theirs(
    corpus: Path, tmp_path: Path
):
    """Titled to be found before the pack's page, so the version is still
    the pack's to manage; and the pack's page changed, so the version is
    crawled again and stamped with the person's page in it."""
    install_pack(corpus, a_pack(tmp_path / "alpha", "alpha", {"docs": docs("2.0")}))
    synced(corpus)
    mine = tmp_path / "mine.md"
    mine.write_text("# A page of mine\n\nWhat I worked out.\n", encoding="utf-8")
    add_docs(
        Collection(root=corpus, name="docs"),
        [str(mine)],
        AddOptions(project="tool", version="2.0"),
    )
    FILES["files/docs/guide-2.md"] = b"# Guide two\n\nHow to use it, revised.\n"
    try:
        install_pack(corpus, a_pack(tmp_path / "alpha", "alpha", {"docs": docs("2.0")}))
    finally:
        FILES["files/docs/guide-2.md"] = b"# Guide two\n\nHow to use version two.\n"
    report = synced(corpus)
    assert report.counts.get("rewrite") == 1, report.counts
    assert versions_of(corpus) == {
        "2.0:A page of mine": "user",
        "2.0:Guide two": "pack:alpha",
    }

    uninstall_pack(corpus, "alpha")
    synced(corpus)

    assert versions_of(corpus) == {"2.0:A page of mine": "user"}


def test_a_version_the_person_added_is_not_a_pack_s_to_remove(
    corpus: Path, tmp_path: Path
):
    mine = tmp_path / "guide.md"
    mine.write_text("# Old guide\n\nVersion zero.\n", encoding="utf-8")
    add_docs(
        Collection(root=corpus, name="docs"),
        [str(mine)],
        AddOptions(project="tool", version="0.9"),
    )
    install_pack(corpus, a_pack(tmp_path / "alpha", "alpha", {"docs": docs("2.0")}))
    synced(corpus)

    uninstall_pack(corpus, "alpha")
    synced(corpus)

    assert versions_of(corpus) == {"0.9:Old guide": "user"}
    assert folders_under(corpus / "docs") == {"tool", "tool/0.9"}


# ---------------------------------------------------------------------------
# Through the service's sequence: the mirror's removals reach the corpus
# ---------------------------------------------------------------------------


def test_a_published_sync_removes_the_folders_from_the_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    context = existing_corpus()
    root = context.corpus_root
    sections = {"notes": note("one.md", "a/b"), "docs": docs("1.0") + docs("2.0")}
    operations.install_a_pack(context, a_pack(tmp_path / "alpha", "alpha", sections))
    operations.synchronise_corpus(context)
    assert "alpha/a/b" in folders_under(root / "notes")

    operations.install_a_pack(
        context, a_pack(tmp_path / "alpha", "alpha", {"docs": docs("2.0")})
    )
    operations.synchronise_corpus(context)

    assert folders_under(root / "notes") == set()
    assert folders_under(root / "docs") == {"tool", "tool/2.0"}
