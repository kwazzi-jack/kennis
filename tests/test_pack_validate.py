"""`pack validate`: the checks that need more than the models.

Milestone 7 unit 2. Unit 1's models answer "is this a well-formed pack"; the
four questions here need this kennis's version, the declared trees compared
against each other, and the content on disk.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from kennis.engine.errors import PackInvalid
from kennis.engine.pack.validate import (
    PackReport,
    content_digest,
    validate_pack,
)

HEADER = """
kennis:
  schema_version: 1
pack:
  id: boepie
  name: "stimela pipelines"
  version: "0.1.0"
"""


def header_with(extra: str) -> str:
    """The minimal header plus one more `kennis:` key."""
    return HEADER.replace("  schema_version: 1", f"  schema_version: 1\n  {extra}")


def a_pack_file(root: Path, body: str = HEADER) -> Path:
    path = root / "stimela.ken.yml"
    path.write_text(body, encoding="utf-8")
    return path


def a_file(root: Path, relative: str, body: str = "Body.\n") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def kinds(report: PackReport) -> list[str]:
    return [problem.kind for problem in report.problems]


# ---------------------------------------------------------------------------
# The shape of a report
# ---------------------------------------------------------------------------


def test_a_pack_with_nothing_to_check_is_valid(tmp_path: Path):
    report = validate_pack(a_pack_file(tmp_path))

    assert report.ok
    assert report.problems == ()
    assert report.refusal is None


def test_a_missing_file_is_refused_as_a_pack_not_as_an_os_error(tmp_path: Path):
    with pytest.raises(PackInvalid):
        validate_pack(tmp_path / "absent.ken.yml")


def test_a_file_that_does_not_parse_raises_rather_than_reporting(tmp_path: Path):
    """There is no pack to report on, so this is the one failure that raises.
    Everything else is a finding about a pack that exists."""
    path = a_pack_file(tmp_path, "kennis:\n  schema_version: [unclosed\n")

    with pytest.raises(PackInvalid):
        validate_pack(path)


# ---------------------------------------------------------------------------
# The two version refusals
# ---------------------------------------------------------------------------


def test_a_newer_schema_version_is_refused_as_a_version_not_as_a_defect(
    tmp_path: Path,
):
    """Section 5 step 1: a pack needing a feature that does not exist yet has
    a different fix from a file with a bad field, so it is reported as a
    different thing."""
    path = a_pack_file(
        tmp_path,
        HEADER.replace("schema_version: 1", "schema_version: 2"),
    )

    report = validate_pack(path)

    assert not report.ok
    assert report.refusal is not None
    assert report.refusal.kind == "schema-too-new"
    assert report.refusal.required == "2"
    assert report.refusal.available == "1"


def test_a_min_version_above_this_kennis_is_refused(tmp_path: Path):
    path = a_pack_file(tmp_path, header_with('min_version: "99.0"'))

    report = validate_pack(path)

    assert report.refusal is not None
    assert report.refusal.kind == "kennis-too-old"
    assert report.refusal.required == "99.0"


def test_a_min_version_this_kennis_meets_is_not_a_refusal(tmp_path: Path):
    path = a_pack_file(tmp_path, header_with('min_version: "0.0.1"'))

    assert validate_pack(path).refusal is None


def test_min_version_is_compared_numerically_not_as_a_string(tmp_path: Path):
    """The case the design names: `0.10` sorts before `0.2` as a string, so a
    string comparison would call this satisfied by kennis 0.2 and install a
    pack that needs 0.10. The version here is far enough ahead that no real
    kennis satisfies it, and lexicographically it is behind every 0.2.x."""
    path = a_pack_file(tmp_path, header_with('min_version: "0.100"'))

    report = validate_pack(path)

    assert report.refusal is not None
    assert report.refusal.kind == "kennis-too-old"


def test_a_refused_version_stops_before_the_content_checks(tmp_path: Path):
    """A newer schema may use sections this kennis cannot interpret, so
    walking the content and judging its digests would be judging a file by
    rules that do not apply to it."""
    a_file(tmp_path, "notes/one.md")
    path = a_pack_file(
        tmp_path,
        HEADER.replace("schema_version: 1", "schema_version: 2")
        + "corpus:\n  notes:\n    - source: notes/\n",
    )

    report = validate_pack(path)

    assert report.refusal is not None
    assert report.problems == ()
    assert not report.digests_checked


# ---------------------------------------------------------------------------
# Overlapping sources
# ---------------------------------------------------------------------------


def test_a_source_nested_inside_another_is_refused(tmp_path: Path):
    """Section 5 keys content on `(section, source index, relative path)`, so
    a file reachable from two sources would have two addresses and the diff
    could not decide which one moved."""
    a_file(tmp_path, "notes/deep/one.md")
    path = a_pack_file(
        tmp_path,
        HEADER + "corpus:\n  notes:\n    - source: notes/\n    - source: notes/deep/\n",
    )

    report = validate_pack(path)

    assert "overlapping-sources" in kinds(report)


def test_the_same_source_declared_twice_is_refused(tmp_path: Path):
    a_file(tmp_path, "notes/one.md")
    path = a_pack_file(
        tmp_path,
        HEADER + "corpus:\n  notes:\n    - source: notes/\n    - source: notes\n",
    )

    assert "overlapping-sources" in kinds(validate_pack(path))


def test_the_same_path_in_two_sections_is_not_an_overlap(tmp_path: Path):
    """`notes` and `context` are different destinations, and the diff key
    carries the section. A pack shipping one tree to both is odd but not
    ambiguous."""
    a_file(tmp_path, "shared/one.md")
    path = a_pack_file(
        tmp_path,
        HEADER
        + "corpus:\n  notes:\n    - source: shared/\ncontext:\n  - source: shared/\n",
    )

    assert "overlapping-sources" not in kinds(validate_pack(path))


# ---------------------------------------------------------------------------
# Path hygiene
# ---------------------------------------------------------------------------


def test_a_source_directory_that_is_not_there_is_reported(tmp_path: Path):
    """An empty digest map is indistinguishable from a pack that ships
    nothing, which is the state the fast path of section 5 step 2 spends its
    whole length defending against."""
    path = a_pack_file(tmp_path, HEADER + "corpus:\n  notes:\n    - source: absent/\n")

    report = validate_pack(path)

    assert kinds(report) == ["source-missing"]
    assert report.problems[0].path == "absent/"


def test_a_symlink_out_of_the_pack_root_is_reported_and_not_read(tmp_path: Path):
    """The zip-slip shape from section 7. The declared source is relative and
    inside the pack, and a symlink under it points at a file that is not."""
    outside = tmp_path.parent / "outside.md"
    outside.write_text("Secrets.\n", encoding="utf-8")
    a_file(tmp_path, "notes/real.md")
    (tmp_path / "notes" / "stolen.md").symlink_to(outside)
    path = a_pack_file(tmp_path, HEADER + "corpus:\n  notes:\n    - source: notes/\n")

    report = validate_pack(path)

    assert "escapes-root" in kinds(report)
    escaping = [
        problem for problem in report.problems if problem.kind == "escapes-root"
    ]
    assert escaping[0].path == "notes/stolen.md"


def test_a_symlink_inside_the_pack_root_is_still_not_followed(tmp_path: Path):
    """ "Not followed" is simpler to state than "followed when it is safe",
    and a pack has no reason to ship one. Reported so an author who did not
    mean to include it finds out."""
    a_file(tmp_path, "notes/real.md")
    (tmp_path / "notes" / "copy.md").symlink_to(tmp_path / "notes" / "real.md")
    path = a_pack_file(tmp_path, HEADER + "corpus:\n  notes:\n    - source: notes/\n")

    assert "symlink" in kinds(validate_pack(path))


def test_a_symlinked_directory_is_not_descended_into(tmp_path: Path):
    outside = tmp_path.parent / "elsewhere"
    outside.mkdir(exist_ok=True)
    (outside / "sneaky.md").write_text("Secrets.\n", encoding="utf-8")
    a_file(tmp_path, "notes/real.md")
    (tmp_path / "notes" / "linked").symlink_to(outside, target_is_directory=True)
    path = a_pack_file(tmp_path, HEADER + "corpus:\n  notes:\n    - source: notes/\n")

    report = validate_pack(path)

    assert not any("sneaky" in problem.path for problem in report.problems)


# ---------------------------------------------------------------------------
# Digests
# ---------------------------------------------------------------------------


def generated_for(entries: dict[str, str], source: str = "notes/") -> str:
    files = "\n".join(
        f'          "{name}": "{digest}"' for name, digest in entries.items()
    )
    return (
        "generated:\n"
        '  at: "2026-09-26T00:00:00Z"\n'
        '  by: "kennis 0.2.0"\n'
        "  content:\n"
        "    notes:\n"
        f"      - source: {source}\n"
        "        files:\n"
        f"{files}\n"
    )


def test_digests_that_match_the_content_are_valid(tmp_path: Path):
    body = "Body.\n"
    a_file(tmp_path, "notes/one.md", body)
    path = a_pack_file(
        tmp_path,
        HEADER
        + "corpus:\n  notes:\n    - source: notes/\n"
        + generated_for({"one.md": content_digest(body.encode("utf-8"))}),
    )

    report = validate_pack(path)

    assert report.ok, report.problems
    assert report.digests_checked


def test_a_digest_that_disagrees_with_the_file_is_reported_with_both(tmp_path: Path):
    """The failure section 3 exists to catch: an author edited a note and did
    not re-run `pack update`, so the file lies about its own content."""
    a_file(tmp_path, "notes/one.md", "Edited after the update.\n")
    path = a_pack_file(
        tmp_path,
        HEADER
        + "corpus:\n  notes:\n    - source: notes/\n"
        + generated_for({"one.md": content_digest(b"what it used to say")}),
    )

    report = validate_pack(path)

    problem = report.problems[0]
    assert problem.kind == "digest-mismatch"
    assert problem.path == "notes/one.md"
    assert problem.recorded == content_digest(b"what it used to say")
    assert problem.actual == content_digest(b"Edited after the update.\n")


def test_a_file_the_generated_block_does_not_mention_is_reported(tmp_path: Path):
    a_file(tmp_path, "notes/one.md", "Body.\n")
    a_file(tmp_path, "notes/added-later.md", "New.\n")
    path = a_pack_file(
        tmp_path,
        HEADER
        + "corpus:\n  notes:\n    - source: notes/\n"
        + generated_for({"one.md": content_digest(b"Body.\n")}),
    )

    report = validate_pack(path)

    assert kinds(report) == ["undigested"]
    assert report.problems[0].path == "notes/added-later.md"


def test_a_digest_for_a_file_that_is_gone_is_reported(tmp_path: Path):
    a_file(tmp_path, "notes/one.md", "Body.\n")
    path = a_pack_file(
        tmp_path,
        HEADER
        + "corpus:\n  notes:\n    - source: notes/\n"
        + generated_for(
            {
                "one.md": content_digest(b"Body.\n"),
                "deleted.md": content_digest(b"gone"),
            }
        ),
    )

    report = validate_pack(path)

    assert kinds(report) == ["digest-absent"]
    assert report.problems[0].path == "notes/deleted.md"


def test_a_pack_with_no_generated_block_is_valid_and_says_it_checked_nothing(
    tmp_path: Path,
):
    """A pack that has never had `pack update` run is valid, so its absence
    cannot be an error - but a forgotten `update` in a release pipeline is
    exactly what this command exists to catch, so the report says which
    checks it performed rather than passing in silence."""
    a_file(tmp_path, "notes/one.md")
    path = a_pack_file(tmp_path, HEADER + "corpus:\n  notes:\n    - source: notes/\n")

    report = validate_pack(path)

    assert report.ok
    assert not report.digests_checked


def test_exclude_keeps_a_file_out_of_the_digest_check(tmp_path: Path):
    """`pack update` honours `include`/`exclude` when it writes the block, so
    validate has to honour them when it reads it, or every excluded file
    would report as undigested."""
    a_file(tmp_path, "notes/one.md", "Body.\n")
    a_file(tmp_path, "notes/draft.md", "Not shipped.\n")
    path = a_pack_file(
        tmp_path,
        HEADER
        + "corpus:\n  notes:\n    - source: notes/\n      exclude: ['draft.md']\n"
        + generated_for({"one.md": content_digest(b"Body.\n")}),
    )

    assert validate_pack(path).ok


def test_include_selects_and_a_non_matching_file_is_not_content(tmp_path: Path):
    a_file(tmp_path, "notes/one.md", "Body.\n")
    a_file(tmp_path, "notes/notes.txt", "Not markdown.\n")
    path = a_pack_file(
        tmp_path,
        HEADER
        + "corpus:\n  notes:\n    - source: notes/\n"
        + generated_for({"one.md": content_digest(b"Body.\n")}),
    )

    assert validate_pack(path).ok


def test_the_digest_is_sha256_of_the_bytes(tmp_path: Path):
    """Named rather than left to the implementation, because a pack is an
    interchange format and another tool may compute this without kennis. Not
    the corpus's blake2b over decoded text, which exists for chunking
    stability and would be surprising here."""
    del tmp_path
    assert content_digest(b"abc") == hashlib.sha256(b"abc").hexdigest()
