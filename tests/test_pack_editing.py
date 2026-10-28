"""`pack add` and `pack remove` edit a pack file's entries (Brian, 2026-10-26).

Anything `corpus add` accepts can be declared without editing the YAML by
hand, a local file included: it is copied into the pack under `files/` and
named relative to the pack file. The file is edited as text, never dumped,
so an author's comments, key order and header survive - the property most
of these tests are about.

No test reaches a host: an entry with no citekey makes `pack update` ask
arXiv, and the client handed over answers 404.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from kennis.engine.corpus.add import AddOptions, AddOutcome
from kennis.engine.errors import InputError, PackInvalid
from kennis.engine.events import ItemFinished, Outcome, Recorder
from kennis.engine.pack.content import content_digest
from kennis.engine.pack.editing import (
    Destination,
    PackAddition,
    add_to_pack,
    find_pack_file,
    remove_from_pack,
)
from kennis.engine.pack.schema import (
    ContentSource,
    NoteFile,
    NoteLink,
    Pack,
    load_pack,
)
from kennis.engine.pack.update import GENERATED_MARKER, update_pack
from kennis.engine.pack.validate import validate_pack
from kennis.engine.refusals import (
    AlreadyDeclared,
    IdentifierNeeded,
    NameTaken,
    NotAnInput,
)

COMMENTED = """\
# yaml-language-server: $schema=https://example.org/ken-1.json

kennis:
  schema_version: 1

pack:
  id: tron
  name: "TRON"
  version: "0.1.0"

corpus:
  literature:
    # The TRON series.
    - citekey: smirnovMiningTimeAxisTRONI2025
      title: "Mining the time axis with TRON. I."
      identifier: "2501.09488"

    # Foundational.
    - citekey: smirnovRevisitingRIMEI2011
      identifier: "1101.1764"

  docs:
    - project: stimela
      base_url: "https://stimela.readthedocs.io/en/latest/"

  notes:
    - url: "https://archive.example.org/report.pdf"
      title: "Time smearing"

# A closing remark about a paper not declared.
"""


def nowhere() -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(404))
    )


@pytest.fixture
def pack(tmp_path: Path) -> Path:
    root = tmp_path / "tron"
    root.mkdir()
    path = root / "tron.ken.yml"
    path.write_text(COMMENTED, encoding="utf-8")
    update_pack(path)
    return path


def read(path: Path) -> Pack:
    return load_pack(path.read_text(encoding="utf-8"))


def authored(path: Path) -> str:
    """The file above the generated block: what the author owns."""
    return path.read_text(encoding="utf-8").partition(GENERATED_MARKER)[0]


def added(
    path: Path,
    destination: Destination,
    *inputs: str,
    options: AddOptions | None = None,
    kept_out: tuple[Path, ...] = (),
) -> PackAddition:
    return add_to_pack(
        path,
        destination,
        list(inputs),
        options or AddOptions(),
        kept_out=kept_out,
        arxiv=nowhere(),
        request_delay_seconds=0,
    )


def the_one(addition: PackAddition) -> AddOutcome:
    [outcome] = addition.report.outcomes
    return outcome


def outside(tmp_path: Path, name: str, data: bytes = b"%PDF-1.4 fake\n") -> Path:
    path = tmp_path / "downloads" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


# ---------------------------------------------------------------------------
# Adding keeps the author's file
# ---------------------------------------------------------------------------


def test_a_paper_is_appended_to_its_section_and_nothing_else_moves(pack: Path):
    before = authored(pack)

    added(
        pack,
        "literature",
        "2511.10785",
        options=AddOptions(citekey="murphyDawesReview2026"),
    )

    after = authored(pack)
    insertion = after.index('    - {\n        identifier: "2511.10785",')
    # Everything above the new entry is the author's bytes, unmoved, and
    # everything below it too.
    head, tail = after[:insertion], after[insertion:].partition("\n\n")[2]
    assert before.startswith(head)
    assert before.endswith(tail)
    assert "# The TRON series." in after
    assert "# A closing remark about a paper not declared." in after
    entry = read(pack).corpus.literature[-1]
    assert (entry.identifier, entry.citekey) == ("2511.10785", "murphyDawesReview2026")


def test_the_new_entry_is_braced_and_set_apart_from_its_neighbours(pack: Path):
    """In kennis's form whatever its neighbours' (#558)."""
    added(
        pack,
        "literature",
        "2511.10785",
        options=AddOptions(citekey="murphyDawesReview2026"),
    )

    text = authored(pack)
    assert (
        '      identifier: "1101.1764"\n\n'
        "    - {\n"
        '        identifier: "2511.10785",\n'
        '        citekey: "murphyDawesReview2026",\n'
        "      }\n"
    ) in text


def test_adding_then_removing_returns_the_authors_bytes(pack: Path):
    before = authored(pack)

    added(
        pack,
        "literature",
        "2511.10785",
        options=AddOptions(citekey="murphyDawesReview2026"),
    )
    remove_from_pack(pack, ["murphyDawesReview2026"])

    assert authored(pack) == before


def test_a_doi_is_accepted_with_or_without_its_prefix(pack: Path):
    added(
        pack,
        "literature",
        "doi:10.48479/bhpj-nz95",
        options=AddOptions(citekey="maccagniRFI2022"),
    )

    entry = read(pack).corpus.literature[-1]
    assert entry.paper.kind == "doi"
    assert entry.paper.value == "10.48479/bhpj-nz95"
    remove_from_pack(pack, ["10.48479/bhpj-nz95"])
    assert [one.citekey for one in read(pack).corpus.literature] == [
        "smirnovMiningTimeAxisTRONI2025",
        "smirnovRevisitingRIMEI2011",
    ]


def test_a_paper_already_declared_is_unchanged_and_nothing_written(pack: Path):
    before = pack.read_bytes()

    addition = added(pack, "literature", "arXiv:1101.1764")

    outcome = the_one(addition)
    assert outcome.outcome is Outcome.UNCHANGED
    assert outcome.refusal == AlreadyDeclared(named="1101.1764")
    assert addition.update is None
    assert pack.read_bytes() == before


def test_each_input_is_added_or_refused_on_its_own(pack: Path, tmp_path: Path):
    unknown = outside(tmp_path, "unknown.pdf")

    addition = added(pack, "literature", "2511.10785", str(unknown), "1501.00001")

    assert [(one.identifier, one.outcome) for one in addition.report.outcomes] == [
        ("2511.10785", Outcome.ADDED),
        (str(unknown), Outcome.FAILED),
        ("1501.00001", Outcome.ADDED),
    ]
    assert addition.report.outcomes[1].refusal == IdentifierNeeded(named=str(unknown))
    held = [one.identifier for one in read(pack).corpus.literature]
    assert held[-2:] == ["2511.10785", "1501.00001"]
    assert not (pack.parent / "files").exists()


def test_an_input_given_twice_is_added_once(pack: Path):
    addition = added(pack, "literature", "2511.10785", "arXiv:2511.10785")

    assert [one.outcome for one in addition.report.outcomes] == [
        Outcome.ADDED,
        Outcome.UNCHANGED,
    ]
    assert [one.identifier for one in read(pack).corpus.literature].count(
        "2511.10785"
    ) == 1


def test_every_input_is_reported_as_an_event(pack: Path):
    seen = Recorder()

    add_to_pack(
        pack,
        "literature",
        ["2511.10785", "nothing-at-all"],
        AddOptions(),
        events=seen,
        arxiv=nowhere(),
        request_delay_seconds=0,
    )

    # The add's own, not the lookups `pack update` names as it describes.
    finished = [
        event
        for event in seen.events
        if isinstance(event, ItemFinished) and event.operation == "add"
    ]
    assert [(event.item, event.outcome) for event in finished] == [
        ("2511.10785", Outcome.ADDED),
        ("nothing-at-all", Outcome.FAILED),
    ]
    assert finished[1].refusal == NotAnInput(identifier="nothing-at-all")


def test_kennis_s_own_folders_are_refused_as_an_add_refuses_them(
    pack: Path, tmp_path: Path
):
    own = tmp_path / "corpus"
    (own / "notes").mkdir(parents=True)
    note = own / "notes" / "mine.md"
    note.write_bytes(b"# Mine\n")

    with pytest.raises(InputError, match="kennis's own files"):
        added(pack, "notes", str(note), kept_out=(own,))


# ---------------------------------------------------------------------------
# Local files are copied into the pack
# ---------------------------------------------------------------------------


def test_a_local_paper_is_copied_in_and_checksummed(pack: Path, tmp_path: Path):
    pdf = outside(tmp_path, "maccagni.pdf")

    added(
        pack,
        "literature",
        str(pdf),
        options=AddOptions(identifier="10.48479/bhpj-nz95"),
    )

    copy = pack.parent / "files" / "literature" / "maccagni.pdf"
    assert copy.read_bytes() == pdf.read_bytes()
    entry = read(pack).corpus.literature[-1]
    assert entry.file == "files/literature/maccagni.pdf"
    generated = read(pack).generated
    assert generated is not None
    assert generated.files == {entry.file: content_digest(pdf.read_bytes())}
    assert validate_pack(pack).ok


def test_a_local_paper_without_an_identifier_is_refused_before_copying(
    pack: Path, tmp_path: Path
):
    before = pack.read_bytes()

    outcome = the_one(added(pack, "literature", str(outside(tmp_path, "unknown.pdf"))))

    assert outcome.outcome is Outcome.FAILED
    assert isinstance(outcome.refusal, IdentifierNeeded)
    assert pack.read_bytes() == before
    assert not (pack.parent / "files").exists()


def test_a_file_already_in_the_pack_is_named_where_it_is(pack: Path):
    inside = pack.parent / "papers" / "rime.pdf"
    inside.parent.mkdir()
    inside.write_bytes(b"%PDF-1.4 fake\n")

    added(pack, "literature", str(inside), options=AddOptions(identifier="1501.00001"))

    assert read(pack).corpus.literature[-1].file == "papers/rime.pdf"
    assert not (pack.parent / "files").exists()


def test_a_copy_of_another_file_by_the_same_name_is_refused(pack: Path, tmp_path: Path):
    added(
        pack,
        "literature",
        str(outside(tmp_path, "a.pdf")),
        options=AddOptions(identifier="1501.00001"),
    )
    other = tmp_path / "elsewhere" / "a.pdf"
    other.parent.mkdir()
    other.write_bytes(b"%PDF-1.4 different\n")

    outcome = the_one(
        added(
            pack, "literature", str(other), options=AddOptions(identifier="1501.00002")
        )
    )

    assert outcome.outcome is Outcome.FAILED
    assert outcome.refusal == NameTaken(named=str(other), copy="files/literature/a.pdf")


def test_two_inputs_of_one_add_cannot_copy_to_one_name(pack: Path, tmp_path: Path):
    first = outside(tmp_path, "a.md", b"# First\n")
    second = tmp_path / "elsewhere" / "a.md"
    second.parent.mkdir()
    second.write_bytes(b"# Second\n")

    addition = added(pack, "notes", str(first), str(second))

    assert [one.outcome for one in addition.report.outcomes] == [
        Outcome.ADDED,
        Outcome.FAILED,
    ]
    assert addition.report.outcomes[1].refusal == NameTaken(
        named=str(second), copy="files/notes/a.md"
    )
    assert (pack.parent / "files" / "notes" / "a.md").read_bytes() == b"# First\n"


def test_local_docs_pages_gather_under_one_project(pack: Path, tmp_path: Path):
    first = outside(tmp_path, "usage.md", b"# Usage\n")
    second = outside(tmp_path, "install.md", b"# Install\n")

    added(
        pack, "docs", str(first), options=AddOptions(project="tron", version="latest")
    )
    added(
        pack, "docs", str(second), options=AddOptions(project="tron", version="latest")
    )

    [local] = [entry for entry in read(pack).corpus.docs if entry.project == "tron"]
    assert local.pages == ["files/docs/tron/usage.md", "files/docs/tron/install.md"]
    assert validate_pack(pack).ok


def test_local_docs_pages_need_a_project_and_a_version(pack: Path, tmp_path: Path):
    with pytest.raises(InputError, match="--version"):
        added(
            pack,
            "docs",
            str(outside(tmp_path, "usage.md")),
            options=AddOptions(project="tron"),
        )


def test_notes_found_by_a_pattern_are_each_one_input(pack: Path, tmp_path: Path):
    outside(tmp_path, "usage.md", b"# Usage\n")
    outside(tmp_path, "install.md", b"# Install\n")

    addition = added(pack, "notes", str(tmp_path / "downloads" / "*.md"))

    assert [one.outcome for one in addition.report.outcomes] == [Outcome.ADDED] * 2
    shipped = sorted(
        one.file for one in read(pack).corpus.notes if isinstance(one, NoteFile)
    )
    assert shipped == ["files/notes/install.md", "files/notes/usage.md"]


def test_a_docs_folder_or_pattern_is_refused_as_corpus_add_refuses_it(
    pack: Path, tmp_path: Path
):
    outside(tmp_path, "usage.md", b"# Usage\n")

    for argument in (tmp_path / "downloads", tmp_path / "downloads" / "*.md"):
        with pytest.raises(InputError, match="neither a documentation site nor a file"):
            added(
                pack,
                "docs",
                str(argument),
                options=AddOptions(project="tron", version="latest"),
            )


def test_a_docs_site_is_named_from_its_host(pack: Path):
    added(pack, "docs", "https://tkp.readthedocs.io/en/latest/")

    entry = read(pack).corpus.docs[-1]
    assert (entry.project, entry.base_url) == (
        "tkp",
        "https://tkp.readthedocs.io/en/latest/",
    )


def test_notes_by_address_by_file_and_by_folder(pack: Path, tmp_path: Path):
    folder = tmp_path / "downloads" / "reports"
    folder.mkdir(parents=True)
    (folder / "a.md").write_bytes(b"# A\n")
    (folder / "b.pdf").write_bytes(b"%PDF-1.4 fake\n")

    added(
        pack, "notes", "https://example.org/beam.html", options=AddOptions(title="Beam")
    )
    added(
        pack,
        "notes",
        str(outside(tmp_path, "rfi.pdf")),
        options=AddOptions(group="sarao"),
    )
    added(pack, "notes", str(folder))

    link, shipped, source = read(pack).corpus.notes[-3:]
    assert isinstance(link, NoteLink) and link.title == "Beam"
    assert isinstance(shipped, NoteFile)
    assert (shipped.file, shipped.group) == ("files/notes/rfi.pdf", "sarao")
    assert isinstance(source, ContentSource)
    assert source.source == "files/notes/reports/"
    assert sorted(source.include) == ["**/*.md", "**/*.pdf"]
    assert validate_pack(pack).ok


def test_context_markdown_lands_in_one_declared_folder(pack: Path, tmp_path: Path):
    added(pack, "context", str(outside(tmp_path, "conventions.md", b"# C\n")))
    added(pack, "context", str(outside(tmp_path, "decisions.md", b"# D\n")))

    assert [one.source for one in read(pack).context] == ["files/context/"]
    assert sorted(path.name for path in (pack.parent / "files/context").iterdir()) == [
        "conventions.md",
        "decisions.md",
    ]
    assert validate_pack(pack).ok


# ---------------------------------------------------------------------------
# Sections that are missing or empty
# ---------------------------------------------------------------------------


def test_a_section_the_pack_lacks_is_created(tmp_path: Path):
    path = tmp_path / "bare.ken.yml"
    path.write_text(
        "kennis:\n  schema_version: 1\n"
        'pack:\n  id: bare\n  name: b\n  version: "1.0.0"\n',
        encoding="utf-8",
    )

    added(
        path,
        "literature",
        "1101.1764",
        options=AddOptions(citekey="smirnovRevisitingRIMEI2011"),
    )

    assert [one.identifier for one in read(path).corpus.literature] == ["1101.1764"]


def test_an_empty_flow_list_becomes_a_block_list(tmp_path: Path):
    path = tmp_path / "empty.ken.yml"
    path.write_text(
        "kennis:\n  schema_version: 1\n"
        'pack:\n  id: empty\n  name: e\n  version: "1.0.0"\n'
        "corpus:\n  literature: []\n  docs: []\n",
        encoding="utf-8",
    )

    added(
        path,
        "literature",
        "1101.1764",
        options=AddOptions(citekey="smirnovRevisitingRIMEI2011"),
    )

    assert "literature: []" not in path.read_text(encoding="utf-8")
    assert len(read(path).corpus.literature) == 1


# ---------------------------------------------------------------------------
# Removing
# ---------------------------------------------------------------------------


def test_removing_the_last_entry_leaves_an_empty_list(pack: Path):
    remove_from_pack(pack, ["https://archive.example.org/report.pdf"])

    assert read(pack).corpus.notes == []
    assert "  notes: []\n" in authored(pack)


def test_removing_a_shipped_paper_deletes_the_copy_pack_add_made(
    pack: Path, tmp_path: Path
):
    added(
        pack,
        "literature",
        str(outside(tmp_path, "a.pdf")),
        options=AddOptions(identifier="1501.00001"),
    )

    edit = remove_from_pack(pack, ["files/literature/a.pdf"])

    assert edit.deleted == ("files/literature/a.pdf",)
    assert not (pack.parent / "files" / "literature" / "a.pdf").exists()


def test_a_file_outside_files_is_never_deleted(pack: Path):
    inside = pack.parent / "papers" / "rime.pdf"
    inside.parent.mkdir()
    inside.write_bytes(b"%PDF-1.4 fake\n")
    added(pack, "literature", str(inside), options=AddOptions(identifier="1501.00001"))

    edit = remove_from_pack(pack, ["papers/rime.pdf"])

    assert edit.deleted == ()
    assert inside.exists()


def test_removing_a_name_nothing_matches_is_refused(pack: Path):
    before = pack.read_bytes()

    with pytest.raises(InputError, match="nosuchCitekey"):
        remove_from_pack(pack, ["nosuchCitekey"])

    assert pack.read_bytes() == before


def test_a_docs_project_is_removed_by_its_name(pack: Path):
    remove_from_pack(pack, ["stimela"])

    assert read(pack).corpus.docs == []


# ---------------------------------------------------------------------------
# Which pack
# ---------------------------------------------------------------------------


def test_the_pack_is_the_one_ken_file_in_the_folder(pack: Path):
    assert find_pack_file(pack.parent) == pack


def test_no_pack_file_or_several_is_refused(tmp_path: Path):
    with pytest.raises(PackInvalid, match="--pack"):
        find_pack_file(tmp_path)
    (tmp_path / "a.ken.yml").write_text("", encoding="utf-8")
    (tmp_path / "b.ken.yml").write_text("", encoding="utf-8")
    with pytest.raises(PackInvalid, match="--pack"):
        find_pack_file(tmp_path)


def test_a_doi_added_without_a_citekey_is_given_its_registry_s(pack: Path):
    """Brian, 2026-10-26: `pack add -l doi:...` needs no `--citekey`; the
    update that follows the add derives one from the DOI's metadata and
    writes it into the entry."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "doi.org" and request.url.path != "/robots.txt":
            return httpx.Response(
                200,
                json={
                    "DOI": "10.1017/pasa.2025.10128",
                    "title": "The Dawes review 13: A new look at the dynamic radio sky",
                    "author": [{"family": "Murphy", "given": "Tara"}],
                    "issued": {"date-parts": [[2025, 12, 2]]},
                    "published-print": {"date-parts": [[2026]]},
                },
            )
        return httpx.Response(404)

    add_to_pack(
        pack,
        "literature",
        ["doi:10.1017/pasa.2025.10128"],
        AddOptions(),
        arxiv=httpx.Client(transport=httpx.MockTransport(handler)),
        request_delay_seconds=0,
    )

    entry = read(pack).corpus.literature[-1]
    assert entry.citekey == "murphyDawesReviewNew2026"
    assert entry.authors == ["Murphy, Tara"]
    assert entry.year == 2026


# ---------------------------------------------------------------------------
# Context one file at a time (Brian, 2026-10-27)
# ---------------------------------------------------------------------------


def a_brain(tmp_path: Path) -> Path:
    """A pack whose folder holds context it has not declared, as
    `rarg-brain` did when `pack add -c context/constraints.md` was refused."""
    root = tmp_path / "brain"
    (root / "context").mkdir(parents=True)
    for name in ("constraints.md", "glossary.md", "team.md"):
        (root / "context" / name).write_text(f"# {name}\n", encoding="utf-8")
    (root / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
    path = root / "brain.ken.yml"
    path.write_text(
        "kennis:\n  schema_version: 1\n"
        'pack:\n  id: brain\n  name: b\n  version: "0.1.0"\n',
        encoding="utf-8",
    )
    update_pack(path)
    return path


def test_a_context_file_in_the_pack_is_declared_by_its_folder_and_name(
    tmp_path: Path,
):
    path = a_brain(tmp_path)

    addition = added(
        path,
        "context",
        str(path.parent / "context/constraints.md"),
        options=AddOptions(group="context"),
    )

    assert the_one(addition).outcome is Outcome.ADDED
    [source] = read(path).context
    assert (source.source, source.group, source.include) == (
        "context/",
        "context",
        ["constraints.md"],
    )
    assert validate_pack(path).ok
    generated = read(path).generated
    assert generated is not None
    assert list(generated.content.context[0].files) == ["constraints.md"]


def test_more_files_of_that_folder_join_its_include_list(tmp_path: Path):
    path = a_brain(tmp_path)
    folder = path.parent / "context"

    added(path, "context", str(folder / "constraints.md"))
    added(path, "context", str(folder / "glossary.md"), str(folder / "team.md"))

    [source] = read(path).context
    assert source.include == ["constraints.md", "glossary.md", "team.md"]
    assert validate_pack(path).ok


def test_a_file_at_the_pack_s_root_is_declared_alone(tmp_path: Path):
    path = a_brain(tmp_path)

    added(path, "context", str(path.parent / "AGENTS.md"))

    [source] = read(path).context
    assert (source.source, source.include) == ("./", ["AGENTS.md"])
    generated = read(path).generated
    assert generated is not None
    assert list(generated.content.context[0].files) == ["AGENTS.md"]


def test_a_file_its_declared_folder_already_ships_is_unchanged(tmp_path: Path):
    path = a_brain(tmp_path)
    added(path, "context", str(path.parent / "context"))

    addition = added(path, "context", str(path.parent / "context/team.md"))

    assert the_one(addition).outcome is Outcome.UNCHANGED
    assert len(read(path).context) == 1


def test_a_file_named_by_its_include_list_is_removed_from_it(tmp_path: Path):
    path = a_brain(tmp_path)
    folder = path.parent / "context"
    added(path, "context", str(folder / "constraints.md"), str(folder / "team.md"))

    remove_from_pack(path, ["context/team.md"])

    [source] = read(path).context
    assert source.include == ["constraints.md"]
    assert (folder / "team.md").exists()


def test_the_last_file_of_an_include_list_takes_the_entry_with_it(tmp_path: Path):
    path = a_brain(tmp_path)
    added(path, "context", str(path.parent / "context/constraints.md"))

    remove_from_pack(path, ["context/constraints.md"])

    assert read(path).context == []


def test_a_file_inside_a_whole_folder_is_refused_naming_the_folder(tmp_path: Path):
    path = a_brain(tmp_path)
    added(path, "context", str(path.parent / "context"))

    with pytest.raises(InputError, match=r"part of the folder 'context/'"):
        remove_from_pack(path, ["context/team.md"])


def test_a_root_file_named_alone_sits_beside_a_declared_folder(tmp_path: Path):
    """`./` contains `context/`, but an entry naming `AGENTS.md` alone cannot
    deliver a file of that folder, so the two are not an overlap - which the
    validator said they were, found by installing `rarg-brain`'s shape."""
    path = a_brain(tmp_path)
    added(path, "context", str(path.parent / "context"))
    added(path, "context", str(path.parent / "AGENTS.md"))

    assert [one.source for one in read(path).context] == ["context/", "./"]
    assert validate_pack(path).ok
    # The rest of the pack is not reported as missed by a pattern.
    assert update_pack(path).unselected == 0


def overlap_found(tmp_path: Path, context: str) -> bool:
    path = a_brain(tmp_path)
    authored_part, marker, block = path.read_text(encoding="utf-8").partition(
        GENERATED_MARKER
    )
    path.write_text(
        authored_part + "context:\n" + context + "\n" + marker + block,
        encoding="utf-8",
    )
    update_pack(path)
    return any(
        problem.kind == "overlapping-sources"
        for problem in validate_pack(path).problems
    )


def test_two_entries_naming_one_file_overlap(tmp_path: Path):
    assert overlap_found(
        tmp_path,
        '  - source: "context/"\n    include: ["team.md"]\n'
        '  - source: "context/"\n    group: other\n    include: ["team.md"]\n',
    )


def test_a_named_file_a_folder_s_patterns_also_ship_overlaps(tmp_path: Path):
    assert overlap_found(
        tmp_path,
        '  - source: "context/"\n  - source: "./"\n    include: ["context/team.md"]\n',
    )


def test_two_folders_naming_different_files_do_not_overlap(tmp_path: Path):
    assert not overlap_found(
        tmp_path,
        '  - source: "context/"\n    include: ["team.md"]\n'
        '  - source: "./"\n    include: ["AGENTS.md"]\n',
    )


def test_one_name_in_two_folders_is_two_files(tmp_path: Path):
    """`context/team.md` and `team.md` at the root share a name and nothing
    else, so naming each in its own folder's list is not an overlap."""
    assert not overlap_found(
        tmp_path,
        '  - source: "context/"\n    include: ["team.md"]\n'
        '  - source: "./"\n    include: ["team.md"]\n',
    )


# ---------------------------------------------------------------------------
# A site whose address names no version (Brian, 2026-10-27)
# ---------------------------------------------------------------------------


def test_a_site_naming_no_version_is_refused_with_the_command_that_files_it(
    pack: Path,
):
    """`pack add -d https://casacore.github.io/python-casacore/` crashed with
    pydantic's traceback; it is refused as `corpus add -d` refuses it, and the
    remedy is this command with `--version unversioned`."""
    before = pack.read_text(encoding="utf-8")

    with pytest.raises(InputError) as raised:
        added(pack, "docs", "https://casacore.github.io/python-casacore/")

    assert raised.value.resolution == (
        "kennis pack add -d https://casacore.github.io/python-casacore/ "
        "--version unversioned"
    )
    assert pack.read_text(encoding="utf-8") == before


def test_unversioned_is_declared_as_given(pack: Path):
    added(
        pack,
        "docs",
        "https://casacore.github.io/python-casacore/",
        options=AddOptions(version="unversioned"),
    )

    assert [one.version for one in read(pack).corpus.docs][-1] == "unversioned"
    assert validate_pack(pack).ok
