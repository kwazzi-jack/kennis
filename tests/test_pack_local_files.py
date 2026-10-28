"""A pack ships a local file for a paper, a note or a documentation page.

Brian, 2026-10-26: anything `corpus add` accepts, a pack can declare,
including a file on disk - copied into the pack and named relative to the
pack file, so the pack still works on another machine. `file:` on a paper
or a note, `pages:` on a documentation project, and one map of checksums,
`generated.files`, for every file so named.

Nothing here reaches a host: a paper is shipped as markdown with its
bibliography given, and every client answers 404, so the add files it from
what the entry says.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import httpx
import pytest

from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.document import Document
from kennis.engine.corpus.schema import DocsFrontmatter, LiteratureFrontmatter
from kennis.engine.corpus.sync import CorpusSync, sync_corpus
from kennis.engine.errors import PackInvalid
from kennis.engine.history.repository import initialise_corpus
from kennis.engine.pack.content import content_digest
from kennis.engine.pack.schema import Pack, load_pack
from kennis.engine.pack.store import install_pack, pack_root
from kennis.engine.pack.update import update_pack
from kennis.engine.pack.validate import validate_pack

HEADER = (
    'kennis:\n  schema_version: 1\npack:\n  id: alpha\n  name: n\n  version: "1.0.0"\n'
)

PAPER = (
    "  literature:\n"
    "    - citekey: smirnovRevisitingRIMEI2011\n"
    '      title: "Revisiting the RIME"\n'
    '      authors: ["Smirnov, O. M."]\n'
    "      year: 2011\n"
    '      identifier: "1101.1764"\n'
    "      file: files/literature/rime.md\n"
)
NOTE = (
    "  notes:\n"
    "    - file: files/notes/smearing.md\n"
    '      title: "Time smearing"\n'
    "      group: sarao\n"
)
DOCS = (
    "  docs:\n"
    "    - project: tron\n"
    "      version: latest\n"
    "      pages:\n"
    "        - files/docs/usage.md\n"
)

FILES: dict[str, bytes] = {
    "files/literature/rime.md": b"# Revisiting the RIME\n\nThe Jones formalism.\n",
    "files/notes/smearing.md": b"# Smearing\n\nAveraging in time smears a source.\n",
    "files/docs/usage.md": b"# Usage\n\nRun tron on a measurement set.\n",
}


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    root.mkdir()
    initialise_corpus(root)
    return root


def a_pack(
    root: Path,
    corpus_section: str = PAPER + NOTE + DOCS,
    *,
    files: dict[str, bytes] | None = None,
    update: bool = True,
) -> Path:
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    for relative, data in (FILES if files is None else files).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    path = root / "alpha.ken.yml"
    path.write_text(HEADER + "corpus:\n" + corpus_section, encoding="utf-8")
    if update:
        update_pack(path)
    return path


def schema_of(corpus_section: str) -> Pack:
    return load_pack(HEADER + "corpus:\n" + corpus_section)


def synced(corpus: Path) -> CorpusSync:
    nowhere = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(404))
    )
    return sync_corpus(corpus, arxiv=nowhere, client=nowhere, request_delay_seconds=0)


def documents_in(corpus: Path, name: str) -> list[Document]:
    return list(Collection(root=corpus, name=name).contents().documents)


# ---------------------------------------------------------------------------
# The schema
# ---------------------------------------------------------------------------


def test_each_kind_of_entry_may_name_a_file_in_the_pack():
    pack = schema_of(PAPER + NOTE + DOCS)

    assert pack.shipped_files == (
        "files/literature/rime.md",
        "files/notes/smearing.md",
        "files/docs/usage.md",
    )


@pytest.mark.parametrize(
    "path", ["/etc/passwd", "C:\\paper.pdf", "~/paper.pdf", "../paper.pdf"]
)
def test_a_shipped_file_stays_inside_the_pack(path: str):
    # Single-quoted, where a backslash is not an escape, so every case
    # reaches the path rule rather than failing as YAML.
    with pytest.raises(
        PackInvalid, match=r"relative to the pack|home directory|leaves the pack"
    ):
        schema_of(
            f"  literature:\n    - identifier: \"1101.1764\"\n      file: '{path}'\n"
        )


def test_a_paper_names_either_an_address_or_a_file():
    with pytest.raises(PackInvalid, match=r"url.*file|file.*url"):
        schema_of(
            "  literature:\n"
            '    - identifier: "1101.1764"\n'
            "      url: https://example.org/rime.pdf\n"
            "      file: files/rime.pdf\n"
        )


def test_a_paper_shipped_as_a_file_still_needs_its_identifier():
    """The identifier is what a sync diffs on, so it must be known before
    any file is read."""
    with pytest.raises(PackInvalid, match="identifier"):
        schema_of("  literature:\n    - file: files/rime.pdf\n")


def test_a_docs_project_is_a_site_or_pages_and_not_both():
    with pytest.raises(PackInvalid, match=r"base_url.*pages|pages.*base_url"):
        schema_of(
            "  docs:\n"
            "    - project: tron\n"
            "      base_url: https://tron.example.org/en/latest/\n"
            "      pages: [files/docs/usage.md]\n"
        )
    with pytest.raises(PackInvalid, match=r"base_url.*pages|pages.*base_url"):
        schema_of("  docs:\n    - project: tron\n      version: latest\n")


def test_local_docs_pages_must_say_their_version():
    with pytest.raises(PackInvalid, match="version"):
        schema_of("  docs:\n    - project: tron\n      pages: [files/docs/usage.md]\n")


# ---------------------------------------------------------------------------
# pack update and pack validate
# ---------------------------------------------------------------------------


def test_update_records_a_checksum_for_every_shipped_file(tmp_path: Path):
    path = a_pack(tmp_path / "pack")

    generated = load_pack(path.read_text(encoding="utf-8")).generated
    assert generated is not None
    assert generated.files == {
        relative: content_digest(data) for relative, data in FILES.items()
    }


def test_a_second_update_leaves_the_file_byte_identical(tmp_path: Path):
    path = a_pack(tmp_path / "pack")
    before = path.read_bytes()

    result = update_pack(path)

    assert result.outcome == "unchanged"
    assert path.read_bytes() == before


def test_update_records_a_shipped_file_that_changed(tmp_path: Path):
    path = a_pack(tmp_path / "pack")
    shipped = path.parent / "files/literature/rime.md"
    shipped.write_bytes(b"# Revisiting the RIME\n\nCorrected.\n")

    result = update_pack(path)

    assert result.outcome == "written"
    generated = load_pack(path.read_text(encoding="utf-8")).generated
    assert generated is not None
    assert generated.files["files/literature/rime.md"] == content_digest(
        shipped.read_bytes()
    )


def test_update_refuses_a_shipped_file_that_is_not_there(tmp_path: Path):
    path = a_pack(tmp_path / "pack", files={}, update=False)

    with pytest.raises(PackInvalid, match=r"files/literature/rime.md"):
        update_pack(path)


def test_validate_reports_a_changed_shipped_file(tmp_path: Path):
    path = a_pack(tmp_path / "pack")
    (path.parent / "files/notes/smearing.md").write_bytes(b"# Changed\n")

    report = validate_pack(path)

    assert [(one.kind, one.path) for one in report.problems] == [
        ("digest-mismatch", "files/notes/smearing.md")
    ]


def test_validate_reports_a_shipped_file_that_went(tmp_path: Path):
    path = a_pack(tmp_path / "pack")
    (path.parent / "files/docs/usage.md").unlink()

    report = validate_pack(path)

    assert [(one.kind, one.path) for one in report.problems] == [
        ("file-missing", "files/docs/usage.md")
    ]


def test_validate_reports_a_file_two_entries_name(tmp_path: Path):
    twice = PAPER + "  notes:\n    - file: files/literature/rime.md\n"
    path = a_pack(tmp_path / "pack", twice)

    report = validate_pack(path)

    assert ("declared-twice", "files/literature/rime.md") in [
        (one.kind, one.path) for one in report.problems
    ]


def test_validate_reports_a_note_file_inside_a_notes_source(tmp_path: Path):
    """It would be delivered twice: once by the folder, once by itself."""
    inside = (
        "  notes:\n    - source: files/notes/\n    - file: files/notes/smearing.md\n"
    )
    path = a_pack(tmp_path / "pack", inside)

    report = validate_pack(path)

    assert "overlapping-sources" in [one.kind for one in report.problems]


# ---------------------------------------------------------------------------
# pack install and corpus sync
# ---------------------------------------------------------------------------


def test_install_copies_every_shipped_file_into_the_store(corpus: Path, tmp_path: Path):
    install_pack(corpus, a_pack(tmp_path / "pack"))

    stored = pack_root(corpus, "alpha")
    for relative, data in FILES.items():
        assert (stored / relative).read_bytes() == data


def test_a_sync_files_each_shipped_file_as_the_packs(corpus: Path, tmp_path: Path):
    install_pack(corpus, a_pack(tmp_path / "pack"))

    report = synced(corpus)

    assert report.failed == ()
    [paper] = documents_in(corpus, "literature")
    [note] = documents_in(corpus, "notes")
    [page] = documents_in(corpus, "docs")
    for document in (paper, note, page):
        assert document.frontmatter.owner == "pack:alpha"
    assert isinstance(paper.frontmatter, LiteratureFrontmatter)
    assert paper.frontmatter.bib.citekey == "smirnovRevisitingRIMEI2011"
    assert "Jones formalism" in paper.body
    assert note.frontmatter.title == "Time smearing"
    assert note.md_path.parent == corpus / "notes" / "alpha" / "sarao"
    assert isinstance(page.frontmatter, DocsFrontmatter)
    assert page.frontmatter.docs.project == "tron"
    assert page.md_path.is_relative_to(corpus / "docs" / "tron" / "latest")


def test_a_second_sync_keeps_everything(corpus: Path, tmp_path: Path):
    install_pack(corpus, a_pack(tmp_path / "pack"))
    synced(corpus)

    report = synced(corpus)

    assert set(report.counts) == {"keep"}, report.counts


def test_a_changed_docs_page_is_rewritten_in_place(corpus: Path, tmp_path: Path):
    install_pack(corpus, a_pack(tmp_path / "pack"))
    synced(corpus)
    [before] = documents_in(corpus, "docs")

    changed = dict(FILES)
    changed["files/docs/usage.md"] = b"# Usage\n\nRun tron twice.\n"
    install_pack(corpus, a_pack(tmp_path / "pack", files=changed))
    synced(corpus)

    [after] = documents_in(corpus, "docs")
    assert after.id == before.id
    assert "Run tron twice." in after.body


def test_a_changed_note_file_is_rewritten_in_place(corpus: Path, tmp_path: Path):
    install_pack(corpus, a_pack(tmp_path / "pack"))
    synced(corpus)
    [before] = documents_in(corpus, "notes")

    changed = dict(FILES)
    changed["files/notes/smearing.md"] = b"# Smearing\n\nIt smears less.\n"
    install_pack(corpus, a_pack(tmp_path / "pack", files=changed))
    synced(corpus)

    [after] = documents_in(corpus, "notes")
    assert after.id == before.id
    assert "It smears less." in after.body
