"""What a pack carries that is not markdown, and what kennis says about it.

Every other pack test ships `.md` files, which is why the two silences
this file is about survived: a file a pattern did not match, and a pack
that declares rather than ships.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kennis.engine.events import ItemFinished, Outcome, Recorder
from kennis.engine.pack.content import read_source
from kennis.engine.pack.schema import ContentSource
from kennis.engine.pack.store import install_pack
from kennis.engine.pack.update import update_pack

HEADER = """
kennis:
  schema_version: 1
pack:
  id: shapes
  name: "input shapes"
  version: "0.1.0"
"""


def a_pack(root: Path, body: str) -> Path:
    path = root / "p.ken.yml"
    path.write_text(body, encoding="utf-8")
    return path


def a_source(root: Path, **files: bytes) -> Path:
    notes = root / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (notes / name).write_bytes(body)
    return notes


# ---------------------------------------------------------------------------
# What the walk selects, and what it says about the rest
# ---------------------------------------------------------------------------


def test_a_file_no_include_matches_is_reported_not_dropped(tmp_path: Path):
    """The silence this file exists for. An author who drops a PDF into a
    declared source and runs `pack update` was told "Unchanged"."""
    a_source(tmp_path, **{"one.md": b"# One\n"})
    (tmp_path / "notes" / "paper.pdf").write_bytes(b"%PDF-1.4\n")

    found = read_source(tmp_path, ContentSource(source="notes/"))

    assert set(found.digests) == {"one.md"}
    assert found.unselected == ("notes/paper.pdf",)


def test_a_file_an_exclude_removed_stays_silent(tmp_path: Path):
    """`exclude:` is intent. Reporting it on every run would be noise, and
    the two cases must not share a channel or the useful one drowns."""
    a_source(tmp_path, **{"one.md": b"# One\n", "draft.md": b"# Draft\n"})

    found = read_source(tmp_path, ContentSource(source="notes/", exclude=["draft.md"]))

    assert set(found.digests) == {"one.md"}
    assert found.unselected == ()


@pytest.mark.parametrize(
    ("name", "selected"),
    [
        ("plain.md", True),
        ("UPPER.MD", False),
        ("notes.txt", False),
        ("diagram.png", False),
        ("a paper.pdf", False),
        (".hidden.md", True),
        ("with spaces.md", True),
    ],
)
def test_which_shapes_the_default_include_takes(
    tmp_path: Path, name: str, selected: bool
):
    """`**/*.md`, spelled out. `UPPER.MD` is the surprising one - matching
    is case-sensitive, as everywhere else in the glob dialect - and it is
    exactly why an unmatched file has to be reported rather than dropped.
    """
    a_source(tmp_path, **{name: b"# Body\n"})

    found = read_source(tmp_path, ContentSource(source="notes/"))

    assert (name in found.digests) is selected


def test_a_unicode_filename_survives_the_walk(tmp_path: Path):
    # Built from code points rather than written out: this repository is
    # ASCII only, and `ruff format` normalises a `\u` escape in a string
    # literal back into the character it names.
    accented = "unicode-" + "".join(chr(point) for point in (0xE9, 0xE7, 0xE3)) + "o.md"
    a_source(tmp_path, **{accented: b"# Accented\n"})

    found = read_source(tmp_path, ContentSource(source="notes/"))

    assert accented in found.digests


def test_an_empty_file_is_content_with_a_digest(tmp_path: Path):
    """Not skipped: an empty note is a note the author wrote, and a digest
    of nothing is still a digest that changes when they fill it in."""
    a_source(tmp_path, **{"empty.md": b""})

    found = read_source(tmp_path, ContentSource(source="notes/"))

    assert "empty.md" in found.digests


def test_line_endings_are_not_normalised(tmp_path: Path):
    """The digest is of the bytes, so a provider on Windows and one on Linux
    shipping the same words have different digests - which is correct, and
    worth pinning so nobody 'fixes' it into a text-mode read."""
    a_source(tmp_path, **{"crlf.md": b"# Title\r\n\r\nBody.\r\n"})
    a_source(tmp_path / "other", **{"lf.md": b"# Title\n\nBody.\n"})

    crlf = read_source(tmp_path, ContentSource(source="notes/"))
    lf = read_source(tmp_path / "other", ContentSource(source="notes/"))

    assert crlf.digests["crlf.md"] != lf.digests["lf.md"]


def test_a_nested_tree_is_taken_at_any_depth(tmp_path: Path):
    deep = tmp_path / "notes" / "one" / "two" / "three"
    deep.mkdir(parents=True)
    (deep / "far.md").write_text("# Far\n", encoding="utf-8")

    found = read_source(tmp_path, ContentSource(source="notes/"))

    assert "one/two/three/far.md" in found.digests


# ---------------------------------------------------------------------------
# What `update` says about it
# ---------------------------------------------------------------------------


def test_update_names_every_unselected_file_in_the_log(tmp_path: Path):
    a_source(tmp_path, **{"one.md": b"# One\n"})
    (tmp_path / "notes" / "paper.pdf").write_bytes(b"%PDF-1.4\n")
    (tmp_path / "notes" / "table.csv").write_bytes(b"a,b\n")
    path = a_pack(tmp_path, HEADER + "corpus:\n  notes:\n    - source: notes/\n")
    events = Recorder()

    update_pack(path, events=events)

    skipped = [
        event.item
        for event in events.events_of_type(ItemFinished)
        if event.outcome is Outcome.SKIPPED
    ]
    assert sorted(skipped) == ["notes/paper.pdf", "notes/table.csv"]


def test_update_counts_what_it_did_not_take(tmp_path: Path):
    a_source(tmp_path, **{"one.md": b"# One\n"})
    (tmp_path / "notes" / "paper.pdf").write_bytes(b"%PDF-1.4\n")
    path = a_pack(tmp_path, HEADER + "corpus:\n  notes:\n    - source: notes/\n")

    result = update_pack(path)

    assert result.files == 1
    assert result.unselected == 1


# ---------------------------------------------------------------------------
# A pack that declares rather than ships
# ---------------------------------------------------------------------------


DECLARATIONS = """
corpus:
  literature:
    - citekey: smirnovRevisitingRIMEI2011
      title: "Revisiting the RIME I"
      arxiv_id: "1101.1764"
  docs:
    - project: stimela
      base_url: "https://stimela.readthedocs.io/en/latest/"
"""


def test_a_declarations_only_pack_reports_what_it_declared(tmp_path: Path):
    """It copies nothing, so the file count is zero and "0 files installed"
    reads as "nothing happened" for a pack that just declared two papers
    and a documentation site."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    path = a_pack(tmp_path, HEADER + DECLARATIONS)

    install = install_pack(corpus, path)

    assert install.files == 0
    assert install.literature == 1
    assert install.docs == 1


def test_a_content_pack_declares_nothing(tmp_path: Path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    a_source(tmp_path, **{"one.md": b"# One\n"})
    path = a_pack(tmp_path, HEADER + "corpus:\n  notes:\n    - source: notes/\n")
    update_pack(path)

    install = install_pack(corpus, path)

    assert install.files == 1
    assert install.literature == 0
    assert install.docs == 0
