"""`pack update`: writing the generated block. Milestone 7 unit 4.

The property that decides the design is in design section 3: a rebuild that
altered nothing leaves the file byte-identical, because the pack file's
sha256 is the fast path in section 5 step 2.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kennis.engine.errors import PackInvalid
from kennis.engine.pack.schema import load_pack
from kennis.engine.pack.update import GENERATED_MARKER, update_pack
from kennis.engine.pack.validate import content_digest, validate_pack

HEADER = """# yaml-language-server: $schema=https://example/ken-1.json

kennis:
  schema_version: 1

pack:
  id: boepie
  name: "stimela pipelines"
  version: "0.1.0"
"""

NOTES = "\ncorpus:\n  notes:\n    - source: notes/\n      group: stimela\n"


def a_pack(root: Path, body: str = HEADER + NOTES) -> Path:
    path = root / "stimela.ken.yml"
    path.write_text(body, encoding="utf-8")
    return path


def a_file(root: Path, relative: str, body: str = "Body.\n") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Writing the block
# ---------------------------------------------------------------------------


def test_the_digests_it_writes_are_the_ones_validate_accepts(tmp_path: Path):
    """The pairing that matters: two walks that disagreed would have
    `update` write a block `validate` rejects, and an author caught between
    two kennis commands has nowhere to go."""
    a_file(tmp_path, "notes/one.md", "Body.\n")
    path = a_pack(tmp_path)

    update_pack(path)

    assert validate_pack(path).ok


def test_the_block_records_the_digest_of_each_file(tmp_path: Path):
    a_file(tmp_path, "notes/one.md", "Body.\n")
    path = a_pack(tmp_path)

    update_pack(path)

    pack = load_pack(path.read_text(encoding="utf-8"))
    assert pack.generated is not None
    assert pack.generated.content.notes[0].files == {
        "one.md": content_digest(b"Body.\n")
    }


def test_context_and_notes_are_recorded_under_their_own_sections(tmp_path: Path):
    """Section 5 keys content on its destination, so a digest carries the
    section it belongs to rather than a bare relative path."""
    a_file(tmp_path, "notes/one.md")
    a_file(tmp_path, "content/index.md")
    path = a_pack(tmp_path, HEADER + NOTES + "\ncontext:\n  - source: content/\n")

    update_pack(path)

    pack = load_pack(path.read_text(encoding="utf-8"))
    assert pack.generated is not None
    assert [entry.source for entry in pack.generated.content.notes] == ["notes/"]
    assert [entry.source for entry in pack.generated.content.context] == ["content/"]


def test_exclude_keeps_a_file_out_of_the_block(tmp_path: Path):
    a_file(tmp_path, "notes/one.md")
    a_file(tmp_path, "notes/draft.md")
    path = a_pack(
        tmp_path,
        HEADER
        + "\ncorpus:\n  notes:\n    - source: notes/\n      exclude: ['draft.md']\n",
    )

    update_pack(path)

    pack = load_pack(path.read_text(encoding="utf-8"))
    assert pack.generated is not None
    assert list(pack.generated.content.notes[0].files) == ["one.md"]


def test_a_source_that_holds_nothing_records_an_empty_map(tmp_path: Path):
    """An empty map and an absent entry read differently in `validate`:
    absent means the block predates this source, empty means it was walked
    and held nothing. A source that matched no file is the second."""
    (tmp_path / "notes").mkdir()
    path = a_pack(tmp_path)

    update_pack(path)

    pack = load_pack(path.read_text(encoding="utf-8"))
    assert pack.generated is not None
    assert pack.generated.content.notes[0].files == {}


# ---------------------------------------------------------------------------
# Byte-identical when nothing changed
# ---------------------------------------------------------------------------


def test_a_second_update_over_unchanged_content_writes_nothing(tmp_path: Path):
    """Section 3: otherwise every provider rebuild changes the pack's sha256
    and defeats the fast path in section 5. Asserted on the bytes, because
    that is what the hash is taken of."""
    a_file(tmp_path, "notes/one.md")
    path = a_pack(tmp_path)
    update_pack(path)
    first = path.read_bytes()

    second = update_pack(path)

    assert path.read_bytes() == first
    assert second.outcome == "unchanged"


def test_a_changed_file_restamps_the_block(tmp_path: Path):
    a_file(tmp_path, "notes/one.md", "Body.\n")
    path = a_pack(tmp_path)
    update_pack(path)
    before = path.read_bytes()

    a_file(tmp_path, "notes/one.md", "Edited.\n")
    result = update_pack(path)

    assert path.read_bytes() != before
    assert result.outcome == "written"


def test_everything_above_the_marker_survives_byte_for_byte(tmp_path: Path):
    """`yaml.dump` of the parsed pack would produce a valid file that had
    lost the editor header line unit 3 exists to write, every comment, and
    the author's key order."""
    a_file(tmp_path, "notes/one.md", "Body.\n")
    path = a_pack(tmp_path, HEADER + "\n# A comment the author wrote.\n" + NOTES)
    head = path.read_bytes()

    update_pack(path)
    a_file(tmp_path, "notes/one.md", "Edited.\n")
    update_pack(path)

    text = path.read_bytes()
    assert text.startswith(head)
    assert b"# A comment the author wrote." in text


def test_the_marker_is_written_once_however_often_update_runs(tmp_path: Path):
    a_file(tmp_path, "notes/one.md", "One.\n")
    path = a_pack(tmp_path)

    for body in ("One.\n", "Two.\n", "Three.\n"):
        a_file(tmp_path, "notes/one.md", body)
        update_pack(path)

    assert path.read_text(encoding="utf-8").count(GENERATED_MARKER) == 1


# ---------------------------------------------------------------------------
# What it refuses
# ---------------------------------------------------------------------------


def test_a_missing_source_directory_is_refused_not_recorded_as_empty(
    tmp_path: Path,
):
    """Writing an empty map here would be indistinguishable from a pack that
    ships nothing, and section 5 step 2 treats that claim as authority to
    delete the user's files."""
    path = a_pack(tmp_path)

    with pytest.raises(PackInvalid) as raised:
        update_pack(path)

    assert "notes/" in str(raised.value)


def test_a_file_that_escapes_the_pack_root_is_refused(tmp_path: Path):
    """`validate` reports it; `update` refuses, because a digest written for
    a path outside the pack would be a claim kennis makes about a file it
    does not own."""
    outside = tmp_path.parent / "outside.md"
    outside.write_text("Secrets.\n", encoding="utf-8")
    a_file(tmp_path, "notes/one.md")
    (tmp_path / "notes" / "stolen.md").symlink_to(outside)
    path = a_pack(tmp_path)

    with pytest.raises(PackInvalid):
        update_pack(path)


def test_a_marker_that_is_not_the_last_section_is_refused(tmp_path: Path):
    """The rewrite replaces from the marker to the end of the file, so an
    author who moved their own content below it would have it eaten."""
    a_file(tmp_path, "notes/one.md")
    body = (
        HEADER
        + "\n"
        + GENERATED_MARKER
        + '\ngenerated:\n  at: "x"\n  by: "y"\n'
        + NOTES
    )
    path = a_pack(tmp_path, body)

    with pytest.raises(PackInvalid):
        update_pack(path)


def test_a_file_that_does_not_parse_is_refused_before_anything_is_written(
    tmp_path: Path,
):
    path = a_pack(tmp_path, "kennis:\n  schema_version: [unclosed\n")
    before = path.read_bytes()

    with pytest.raises(PackInvalid):
        update_pack(path)

    assert path.read_bytes() == before


def test_a_pack_this_kennis_may_not_read_is_not_rewritten(tmp_path: Path):
    """A newer schema may nest content differently, so writing a block in
    this kennis's shape would corrupt a file this kennis was told not to
    interpret."""
    a_file(tmp_path, "notes/one.md")
    path = a_pack(
        tmp_path, HEADER.replace("schema_version: 1", "schema_version: 2") + NOTES
    )
    before = path.read_bytes()

    with pytest.raises(PackInvalid):
        update_pack(path)

    assert path.read_bytes() == before
