"""A pack declares a note by address, or ships one kennis converts (#459).

What `corpus add -n` can add, a pack can declare: a note fetched from an
address at `corpus sync`, and a file in a `source:` folder that is not
markdown - a PDF, say - converted at sync as `corpus add -n <file>` would.
Paths in a pack are relative to the pack file's folder.

Nothing here reaches a host: every client is an `httpx.MockTransport`.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import httpx
import pytest

from kennis.engine.corpus.add import add_notes
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.document import Document, write_document
from kennis.engine.corpus.sync import sync_corpus
from kennis.engine.errors import PackInvalid
from kennis.engine.history.repository import initialise_corpus
from kennis.engine.pack.installed import list_installed, overlaps_between
from kennis.engine.pack.schema import NoteLink, Pack, load_pack
from kennis.engine.pack.store import install_pack, pack_root
from kennis.engine.pack.update import update_pack

REPORT = "https://archive.example.org/public/reports/Time-Smearing.html"
PAGE = (
    "<html><head><title>Time smearing on MeerKAT</title></head>"
    "<body><h1>Time smearing</h1><p>Averaging in time smears a source.</p>"
    "</body></html>"
)


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    root.mkdir()
    initialise_corpus(root)
    return root


def a_pack(
    root: Path,
    notes: str,
    *,
    identifier: str = "alpha",
    files: dict[str, bytes] | None = None,
) -> Path:
    """A pack whose `corpus.notes` section is `notes`, written as given."""
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    for relative, data in (files or {}).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    path = root / f"{identifier}.ken.yml"
    path.write_text(
        "kennis:\n  schema_version: 1\n"
        f'pack:\n  id: {identifier}\n  name: n\n  version: "1.0.0"\n'
        f"corpus:\n  notes:\n{notes}",
        encoding="utf-8",
    )
    update_pack(path)
    return path


def link(
    url: str = REPORT, *, title: str | None = None, group: str | None = None
) -> str:
    lines = [f"    - url: {url}\n"]
    if title is not None:
        lines.append(f"      title: {title}\n")
    if group is not None:
        lines.append(f"      group: {group}\n")
    return "".join(lines)


def serving(
    body: str = PAGE, *, status: int = 200, asked: list[str] | None = None
) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if asked is not None:
            asked.append(str(request.url))
        return httpx.Response(
            status, text=body, headers={"content-type": "text/html; charset=utf-8"}
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def notes_in(corpus: Path) -> list[Document]:
    return list(Collection(root=corpus, name="notes").contents().documents)


def only_note(corpus: Path) -> Document:
    documents = notes_in(corpus)
    assert len(documents) == 1, [one.frontmatter.title for one in documents]
    return documents[0]


def installed(corpus: Path, tmp_path: Path, notes: str, **kwargs: object) -> None:
    identifier = str(kwargs.get("identifier", "alpha"))
    files = kwargs.get("files")
    assert files is None or isinstance(files, dict)
    install_pack(
        corpus, a_pack(tmp_path / identifier, notes, identifier=identifier, files=files)
    )


# ---------------------------------------------------------------------------
# The schema
# ---------------------------------------------------------------------------


def schema_of(notes: str) -> Pack:
    return load_pack(
        "kennis:\n  schema_version: 1\n"
        'pack:\n  id: alpha\n  name: n\n  version: "1.0.0"\n'
        f"corpus:\n  notes:\n{notes}"
    )


def test_a_notes_entry_may_be_a_link():
    pack = schema_of(link(title="Smearing", group="reports"))

    assert isinstance(pack.corpus.notes[0], NoteLink)
    assert pack.corpus.note_links[0].group == "reports"
    assert pack.corpus.note_sources == []


def test_a_link_must_be_http_or_https():
    with pytest.raises(PackInvalid, match="http"):
        schema_of(link("ftp://example.org/report.pdf"))


def test_an_entry_naming_both_a_folder_and_an_address_is_refused():
    with pytest.raises(PackInvalid):
        schema_of(f"    - source: notes/\n      url: {REPORT}\n")


def test_a_links_group_stays_inside_the_packs_folder():
    with pytest.raises(PackInvalid, match="group"):
        schema_of(link(group="../outside"))


# ---------------------------------------------------------------------------
# A link, at sync
# ---------------------------------------------------------------------------


def test_a_link_becomes_a_note_owned_by_the_pack(corpus: Path, tmp_path: Path):
    installed(corpus, tmp_path, link(title="Smearing report", group="reports"))

    sync_corpus(corpus, client=serving())

    note = only_note(corpus)
    assert note.frontmatter.owner == "pack:alpha"
    assert note.frontmatter.title == "Smearing report"
    assert "Averaging in time smears a source." in note.body
    assert note.md_path.parent == corpus / "notes" / "alpha" / "reports"


def test_a_link_note_records_the_address_it_was_declared_at(
    corpus: Path, tmp_path: Path
):
    installed(corpus, tmp_path, link())

    sync_corpus(corpus, client=serving())

    assert only_note(corpus).frontmatter.source.origin == f"pack:alpha/url:{REPORT}"


def test_a_link_without_a_title_is_named_as_corpus_add_names_it(
    corpus: Path, tmp_path: Path
):
    installed(corpus, tmp_path, link())
    sync_corpus(corpus, client=serving())
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    initialise_corpus(elsewhere)

    added = add_notes(
        Collection(root=elsewhere, name="notes"), [REPORT], client=serving()
    )

    assert only_note(corpus).frontmatter.title == added.outcomes[0].title
    assert only_note(corpus).frontmatter.title == "Time smearing"


def test_an_unchanged_link_is_not_fetched_again(corpus: Path, tmp_path: Path):
    installed(corpus, tmp_path, link())
    sync_corpus(corpus, client=serving())
    asked: list[str] = []

    report = sync_corpus(corpus, client=serving(asked=asked))

    assert asked == []
    assert report.counts.get("keep") == 1
    assert len(notes_in(corpus)) == 1


def test_a_changed_declaration_rewrites_the_note_where_it_is(
    corpus: Path, tmp_path: Path
):
    installed(corpus, tmp_path, link(title="First"))
    sync_corpus(corpus, client=serving())
    before = only_note(corpus)

    installed(corpus, tmp_path, link(title="Second"))
    sync_corpus(corpus, client=serving(PAGE.replace("smears", "blurs")))

    after = only_note(corpus)
    assert after.id == before.id
    assert after.frontmatter.title == "Second"
    assert "blurs" in after.body


def test_a_link_the_pack_no_longer_declares_is_removed(corpus: Path, tmp_path: Path):
    installed(corpus, tmp_path, link())
    sync_corpus(corpus, client=serving())

    installed(
        corpus,
        tmp_path,
        "    - source: notes/\n",
        files={"notes/kept.md": b"# Kept\n\nStill here.\n"},
    )
    sync_corpus(corpus, client=serving())

    assert [note.frontmatter.title for note in notes_in(corpus)] == ["Kept"]


def test_a_link_that_cannot_be_fetched_fails_alone(corpus: Path, tmp_path: Path):
    installed(
        corpus,
        tmp_path,
        "    - source: notes/\n" + link(),
        files={"notes/kept.md": b"# Kept\n\nStill here.\n"},
    )

    report = sync_corpus(corpus, client=serving(status=500))

    assert report.failed == (f"url:{REPORT}",)
    assert dict(report.why).get(f"url:{REPORT}") is not None
    assert [note.frontmatter.title for note in notes_in(corpus)] == ["Kept"]


def test_a_person_edit_to_a_link_note_is_kept_as_theirs(corpus: Path, tmp_path: Path):
    installed(corpus, tmp_path, link(title="First"))
    sync_corpus(corpus, client=serving())
    note = only_note(corpus)
    write_document(
        note.md_path, frontmatter=note.frontmatter, body=note.body + "\nMine.\n"
    )

    installed(corpus, tmp_path, link(title="Second"))
    report = sync_corpus(corpus, client=serving())

    # The pack's new text is put back and the edit is kept as a note of the
    # person's (#514).
    (mine,) = [one for one in notes_in(corpus) if one.frontmatter.owner == "user"]
    assert report.copied == ((note.id, mine.id),)
    assert "Mine." in mine.body
    (pack_s,) = [one for one in notes_in(corpus) if one.frontmatter.owner != "user"]
    assert "Mine." not in pack_s.body


def test_a_link_two_packs_declare_belongs_to_the_first(corpus: Path, tmp_path: Path):
    installed(corpus, tmp_path, link(), identifier="alpha")
    installed(corpus, tmp_path, link(), identifier="beta")

    report = sync_corpus(corpus, client=serving())

    assert only_note(corpus).frontmatter.owner == "pack:alpha"
    assert (f"url:{REPORT}", "beta") in report.deferred


def test_pack_status_names_a_link_two_packs_declare(corpus: Path, tmp_path: Path):
    installed(corpus, tmp_path, link(), identifier="alpha")
    installed(corpus, tmp_path, link(), identifier="beta")

    overlaps = overlaps_between(list_installed(corpus).packs)

    assert [(one.kind, one.key, one.owner) for one in overlaps] == [
        ("notes", f"url:{REPORT}", "alpha")
    ]


# ---------------------------------------------------------------------------
# A file kennis converts, shipped in a source folder
# ---------------------------------------------------------------------------

PDF_NOTES = '    - source: reports/\n      include: ["**/*.pdf", "**/*.md"]\n'


def test_pack_add_copies_what_the_declared_include_selects(
    corpus: Path, tmp_path: Path
):
    installed(
        corpus,
        tmp_path,
        PDF_NOTES,
        files={"reports/Smearing.pdf": b"%PDF-1.4 fake\n", "reports/a.md": b"A.\n"},
    )

    stored = pack_root(corpus, "alpha") / "reports"
    assert sorted(path.name for path in stored.iterdir()) == ["Smearing.pdf", "a.md"]


def test_a_shipped_pdf_is_converted_at_sync(
    corpus: Path, tmp_path: Path, fake_mineru: Path
):
    installed(
        corpus, tmp_path, PDF_NOTES, files={"reports/Smearing.pdf": b"%PDF-1.4 fake\n"}
    )

    sync_corpus(corpus)

    note = only_note(corpus)
    assert note.frontmatter.title == "Smearing"
    assert "Converted body." in note.body
    assert note.frontmatter.source.origin == "pack:alpha/Smearing.pdf"
    assert fake_mineru.exists()


def test_a_shipped_pdf_that_will_not_convert_fails_alone(
    corpus: Path,
    tmp_path: Path,
    fake_mineru: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("MINERU_FAKE_SKIP", "Smearing")
    installed(
        corpus,
        tmp_path,
        PDF_NOTES,
        files={"reports/Smearing.pdf": b"%PDF-1.4 fake\n", "reports/a.md": b"A.\n"},
    )

    report = sync_corpus(corpus)

    assert report.failed == ("Smearing.pdf",)
    assert [note.body.strip() for note in notes_in(corpus)] == ["A."]


def test_a_folder_declared_twice_gives_each_declaration_only_its_own_files(
    corpus: Path, tmp_path: Path, fake_mineru: Path
):
    """The store holds what either declaration selects; notes take only
    what the notes declaration selects."""
    root = tmp_path / "alpha"
    path = a_pack(
        root,
        '    - source: shared/\n      include: ["**/*.pdf"]\n',
        files={"shared/Smearing.pdf": b"%PDF-1.4 fake\n", "shared/guide.md": b"G.\n"},
    )
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "corpus:\n",
            'context:\n  - source: shared/\n    include: ["**/*.md"]\ncorpus:\n',
            1,
        ),
        encoding="utf-8",
    )
    update_pack(path)
    install_pack(corpus, path)

    sync_corpus(corpus)

    assert [note.frontmatter.title for note in notes_in(corpus)] == ["Smearing"]
