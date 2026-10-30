"""A pack ships no file Windows cannot hold (#573).

Found unpacking the TRON pack on Windows: ten PDFs named after their titles
held a `:`, and `pack validate` had passed them. A pack is data written on
one platform and installed on another, so a name is checked against the
strictest one wherever the pack is written or read.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from kennis.engine.corpus.add import AddOptions, AddOutcome
from kennis.engine.errors import PackInvalid
from kennis.engine.events import Outcome
from kennis.engine.history.repository import initialise_corpus
from kennis.engine.pack.editing import Destination, add_to_pack
from kennis.engine.pack.store import install_pack
from kennis.engine.pack.update import update_pack
from kennis.engine.pack.validate import PackProblem, validate_pack
from kennis.engine.portable import (
    PORTABLE_PATH_LIMIT,
    PortabilityProblem,
    portability_problem,
)
from kennis.engine.refusals import NotPortable
from kennis.render.packs import describe_problem
from kennis.render.portable import describe_unportable
from kennis.render.refusals import describe_refusal, remedies_for_refusal
from platforms import needs_unportable_filenames

HEADER = (
    'kennis:\n  schema_version: 1\npack:\n  id: alpha\n  name: n\n  version: "1.0.0"\n'
)


def nowhere() -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(404))
    )


def a_pack(root: Path, corpus_section: str, files: dict[str, bytes]) -> Path:
    root.mkdir(parents=True)
    for relative, data in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    path = root / "alpha.ken.yml"
    path.write_text(HEADER + "corpus:\n" + corpus_section, encoding="utf-8")
    return path


def problems_of(path: Path) -> list[tuple[str, str]]:
    return [(one.kind, one.path) for one in validate_pack(path).problems]


# ---------------------------------------------------------------------------
# The rule, on paths alone
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("character", list('<>:"|?*\\'))
def test_a_character_windows_forbids_is_named(character: str):
    segment = f"VASTER{character} the pipeline.pdf"

    assert portability_problem(f"papers/{segment}") == PortabilityProblem(
        kind="reserved-character", segment=segment, character=character
    )


def test_a_control_character_is_named():
    assert portability_problem("notes/a\tb.md") == PortabilityProblem(
        kind="control-character", segment="a\tb.md", character="\t"
    )


@pytest.mark.parametrize("segment", ["CON", "nul.md", "Com1.txt", "lpt9", "AUX.tar.gz"])
def test_a_device_name_is_refused_with_or_without_an_extension(segment: str):
    assert portability_problem(f"files/{segment}") == PortabilityProblem(
        kind="reserved-name", segment=segment
    )


@pytest.mark.parametrize(
    "segment", ["console.md", "con1.md", "auxiliary", "nullify.md"]
)
def test_a_name_that_only_begins_like_a_device_is_ordinary(segment: str):
    assert portability_problem(f"files/{segment}") is None


@pytest.mark.parametrize("path", ["notes./a.md", "notes/a.md ", "notes /a.md"])
def test_a_segment_ending_in_a_dot_or_a_space_is_refused(path: str):
    problem = portability_problem(path)

    assert problem is not None
    assert problem.kind == "ends-in-dot-or-space"


def test_a_path_is_refused_past_the_limit_and_not_at_it():
    at_limit = "papers/" + "a" * (PORTABLE_PATH_LIMIT - len("papers/.pdf")) + ".pdf"
    assert len(at_limit) == PORTABLE_PATH_LIMIT

    assert portability_problem(at_limit) is None
    over = portability_problem("p" + at_limit)
    assert over is not None
    assert over.kind == "too-long"


@pytest.mark.parametrize(
    "path",
    [
        "papers/wangVasterAskapReal2026.pdf",
        "files/docs/python-casacore/casacore_tables.md",
        "breifast-wiki/Getting started (v2) - notes.md",
        "data-models/msv4.md",
    ],
)
def test_ordinary_names_pass(path: str):
    assert portability_problem(path) is None


# ---------------------------------------------------------------------------
# pack validate, and so pack install
# ---------------------------------------------------------------------------


def test_validate_names_a_declared_file_windows_cannot_hold(tmp_path: Path):
    """No file is created: the declared path alone is enough to judge."""
    path = a_pack(
        tmp_path / "pack",
        "  notes:\n    - file: 'files/MIGHTEE: early science.md'\n",
        {},
    )

    assert ("not-portable", "files/MIGHTEE: early science.md") in problems_of(path)


@needs_unportable_filenames
def test_validate_names_a_shipped_file_inside_a_source(tmp_path: Path):
    path = a_pack(
        tmp_path / "pack",
        "  notes:\n    - source: wiki/\n",
        {"wiki/ok.md": b"# Fine\n", "wiki/Bursts: from space.md": b"# Colon\n"},
    )
    update_pack(path)

    assert problems_of(path) == [("not-portable", "wiki/Bursts: from space.md")]


@needs_unportable_filenames
def test_a_file_the_source_does_not_ship_is_not_judged(tmp_path: Path):
    path = a_pack(
        tmp_path / "pack",
        "  notes:\n    - source: wiki/\n",
        {"wiki/ok.md": b"# Fine\n", "wiki/scratch: draft.txt": b"not shipped\n"},
    )
    update_pack(path)

    assert problems_of(path) == []


@needs_unportable_filenames
def test_install_refuses_an_unportable_pack(tmp_path: Path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    initialise_corpus(corpus)
    path = a_pack(
        tmp_path / "pack",
        "  notes:\n    - source: wiki/\n",
        {"wiki/Bursts: from space.md": b"# Colon\n"},
    )
    update_pack(path)

    with pytest.raises(PackInvalid, match="not-portable"):
        install_pack(corpus, path)


# ---------------------------------------------------------------------------
# pack add
# ---------------------------------------------------------------------------


@pytest.fixture
def pack(tmp_path: Path) -> Path:
    path = a_pack(tmp_path / "tron", "  notes: []\n", {})
    update_pack(path)
    return path


def add(
    path: Path, destination: Destination, raw: str, options: AddOptions | None = None
) -> AddOutcome:
    addition = add_to_pack(
        path,
        destination,
        [raw],
        options or AddOptions(),
        kept_out=(),
        arxiv=nowhere(),
        request_delay_seconds=0,
    )
    [outcome] = addition.report.outcomes
    return outcome


@needs_unportable_filenames
def test_a_local_file_named_with_a_colon_is_refused_before_it_is_copied(
    pack: Path, tmp_path: Path
):
    source = tmp_path / "downloads" / "VASTER: the pipeline.pdf"
    source.parent.mkdir()
    source.write_bytes(b"%PDF-1.4 fake\n")
    before = pack.read_bytes()

    outcome = add(pack, "literature", str(source), AddOptions(identifier="2501.00001"))

    assert outcome.outcome is Outcome.FAILED
    assert outcome.refusal == NotPortable(
        named=str(source),
        path="files/literature/VASTER: the pipeline.pdf",
        problem=PortabilityProblem(
            kind="reserved-character",
            segment="VASTER: the pipeline.pdf",
            character=":",
        ),
    )
    assert pack.read_bytes() == before
    assert not (pack.parent / "files").exists()


@needs_unportable_filenames
def test_a_file_already_in_the_pack_is_refused_by_its_own_name(pack: Path):
    inside = pack.parent / "papers" / "Dawes review 13: radio sky.pdf"
    inside.parent.mkdir()
    inside.write_bytes(b"%PDF-1.4 fake\n")
    before = pack.read_bytes()

    outcome = add(pack, "literature", str(inside), AddOptions(identifier="2501.00002"))

    assert isinstance(outcome.refusal, NotPortable)
    assert outcome.refusal.path == "papers/Dawes review 13: radio sky.pdf"
    assert pack.read_bytes() == before


@needs_unportable_filenames
def test_a_copied_folder_is_judged_by_every_file_it_would_ship(
    pack: Path, tmp_path: Path
):
    folder = tmp_path / "downloads" / "wiki"
    folder.mkdir(parents=True)
    (folder / "ok.md").write_bytes(b"# Fine\n")
    (folder / "nul.md").write_bytes(b"# A device\n")

    outcome = add(pack, "notes", str(folder))

    assert isinstance(outcome.refusal, NotPortable)
    assert outcome.refusal.path == "files/notes/wiki/nul.md"
    assert outcome.refusal.problem.kind == "reserved-name"
    assert not (pack.parent / "files").exists()


@needs_unportable_filenames
def test_an_add_is_not_refused_for_a_file_the_pack_already_shipped(
    tmp_path: Path,
):
    """As `ShippedTwice`: the input is judged by what it adds."""
    path = a_pack(
        tmp_path / "tron",
        "  notes:\n    - source: wiki/\n",
        {"wiki/Bursts: from space.md": b"# Colon\n"},
    )
    update_pack(path)
    note = tmp_path / "downloads" / "fine.md"
    note.parent.mkdir()
    note.write_bytes(b"# Fine\n")

    outcome = add(path, "notes", str(note))

    assert outcome.outcome is Outcome.ADDED


# ---------------------------------------------------------------------------
# The words
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("problem", "expected"),
    [
        (
            PortabilityProblem(
                kind="reserved-character", segment="a: b", character=":"
            ),
            "Windows does not allow ':' in a name",
        ),
        (
            PortabilityProblem(
                kind="control-character", segment="a\tb", character="\t"
            ),
            "Windows does not allow the control character 0x09 in a name",
        ),
        (
            PortabilityProblem(kind="reserved-name", segment="nul.md"),
            "'nul.md' is a device name on Windows",
        ),
        (
            PortabilityProblem(kind="ends-in-dot-or-space", segment="notes."),
            "Windows drops the dot or space that ends 'notes.'",
        ),
        (
            PortabilityProblem(kind="too-long", segment=""),
            f"it is longer than {PORTABLE_PATH_LIMIT} characters",
        ),
    ],
)
def test_each_kind_says_why_in_its_own_words(
    problem: PortabilityProblem, expected: str
):
    assert expected in describe_unportable("files/x", problem)


def test_the_validator_and_the_refusal_say_the_same_thing():
    problem = PortabilityProblem(
        kind="reserved-character", segment="a: b", character=":"
    )
    finding = PackProblem(kind="not-portable", path="files/a: b", portability=problem)
    refusal = NotPortable(named="/tmp/a: b", path="files/a: b", problem=problem)
    reason = describe_unportable("files/a: b", problem)

    assert reason in describe_problem(finding)
    assert reason in describe_refusal(refusal)


def test_the_refusal_offers_no_command():
    """The way out is a name only the author can choose."""
    problem = PortabilityProblem(kind="too-long", segment="")
    refusal = NotPortable(named="x", path="files/x", problem=problem)

    assert remedies_for_refusal(refusal) == ()
