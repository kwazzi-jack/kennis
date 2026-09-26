"""What the pack operations report through the event stream.

Design section 14: **the report is not the log.** The display subscribes to
this same stream and ignores `ItemFinished` entirely, so everything asserted
here is what the log keeps and the terminal does not - which for
`pack update` is the whole of the per-file detail behind a one-line report.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kennis.engine.errors import PackInvalid
from kennis.engine.events import (
    ItemFinished,
    OperationFinished,
    Outcome,
    Recorder,
)
from kennis.engine.pack.scaffold import scaffold_pack
from kennis.engine.pack.update import update_pack
from kennis.engine.pack.validate import validate_pack

HEADER = """
kennis:
  schema_version: 1
pack:
  id: boepie
  name: n
  version: "0.1.0"
"""

NOTES = "corpus:\n  notes:\n    - source: notes/\n"


def a_pack(root: Path, body: str = HEADER + NOTES) -> Path:
    path = root / "p.ken.yml"
    path.write_text(body, encoding="utf-8")
    return path


def a_file(root: Path, relative: str, body: str = "Body.\n") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# update: the operation with most to say
# ---------------------------------------------------------------------------


def test_update_names_every_file_it_recorded(tmp_path: Path):
    """The report says "2 files recorded". Which two is the log's job."""
    a_file(tmp_path, "notes/one.md")
    a_file(tmp_path, "notes/two.md")
    events = Recorder()

    update_pack(a_pack(tmp_path), events=events)

    assert events.outcomes() == {
        "notes:notes/one.md": Outcome.ADDED,
        "notes:notes/two.md": Outcome.ADDED,
    }


def test_update_distinguishes_added_changed_unchanged_and_gone(tmp_path: Path):
    """The four states a digest can be in between two runs, which is the
    thing a reader goes to the log to find out."""
    a_file(tmp_path, "notes/kept.md", "Same.\n")
    a_file(tmp_path, "notes/edited.md", "Before.\n")
    a_file(tmp_path, "notes/removed.md")
    path = a_pack(tmp_path)
    update_pack(path)

    a_file(tmp_path, "notes/edited.md", "After.\n")
    (tmp_path / "notes" / "removed.md").unlink()
    a_file(tmp_path, "notes/new.md")
    events = Recorder()
    update_pack(path, events=events)

    assert events.outcomes() == {
        "notes:notes/kept.md": Outcome.UNCHANGED,
        "notes:notes/edited.md": Outcome.CHANGED,
        "notes:notes/removed.md": Outcome.REMOVED,
        "notes:notes/new.md": Outcome.ADDED,
    }


def test_a_file_shipped_to_two_sections_is_two_items(tmp_path: Path):
    """`validate` allows the same tree in `notes` and `context`, because
    section 5's diff key carries the section. Reporting them under one name
    would count one change where there are two."""
    a_file(tmp_path, "shared/one.md")
    path = a_pack(
        tmp_path,
        HEADER
        + "corpus:\n  notes:\n    - source: shared/\ncontext:\n  - source: shared/\n",
    )
    events = Recorder()

    update_pack(path, events=events)

    assert sorted(events.outcomes()) == [
        "context:shared/one.md",
        "notes:shared/one.md",
    ]


def test_update_reports_the_operation_with_its_counts(tmp_path: Path):
    a_file(tmp_path, "notes/one.md")
    events = Recorder()

    update_pack(a_pack(tmp_path), events=events)

    finished = events.events_of_type(OperationFinished)
    assert [event.operation for event in finished] == ["pack-update"]
    assert finished[0].counts == {Outcome.ADDED: 1}


def test_an_unchanged_run_still_reports_what_it_looked_at(tmp_path: Path):
    """The run writes nothing, and a reader asking why wants to see that it
    walked the files and found them the same - not silence."""
    a_file(tmp_path, "notes/one.md")
    path = a_pack(tmp_path)
    update_pack(path)
    events = Recorder()

    result = update_pack(path, events=events)

    assert result.outcome == "unchanged"
    assert events.outcomes() == {"notes:notes/one.md": Outcome.UNCHANGED}


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def test_validate_reports_each_problem_as_its_kind_not_as_a_sentence(
    tmp_path: Path,
):
    """Concern #81: the engine names and does not phrase. The sentence lives
    in `render.packs`, and a second copy here would be a second place to
    change it."""
    events = Recorder()

    validate_pack(a_pack(tmp_path), events=events)

    assert events.outcomes() == {"notes/": Outcome.FAILED}
    reasons = [event.reason for event in events.events_of_type(ItemFinished)]
    assert reasons == ["source-missing"]


def test_validate_reports_a_refusal_against_the_file_itself(tmp_path: Path):
    """A version refusal is about the pack, not about one of its files, so
    the item is the path and the reason carries what was needed."""
    path = a_pack(tmp_path, HEADER.replace("schema_version: 1", "schema_version: 9"))
    events = Recorder()

    validate_pack(path, events=events)

    finished = events.events_of_type(ItemFinished)
    assert finished[0].item == str(path)
    assert finished[0].reason is not None
    assert "schema-too-new" in finished[0].reason


def test_a_clean_validate_reports_the_operation_and_no_items(tmp_path: Path):
    events = Recorder()

    validate_pack(a_pack(tmp_path, HEADER), events=events)

    assert events.events_of_type(ItemFinished) == []
    assert events.events_of_type(OperationFinished)[0].counts == {}


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


def test_init_reports_the_file_it_wrote(tmp_path: Path):
    path = tmp_path / "p.ken.yml"
    events = Recorder()

    scaffold_pack(path, identifier="a", name="n", events=events)

    assert events.outcomes() == {str(path): Outcome.ADDED}


def test_a_refused_init_reports_nothing(tmp_path: Path):
    """It raises, and an operation that did not happen has no outcome to
    record. The error carries the reason."""
    path = tmp_path / "p.ken.yml"
    path.write_text("corpus: {}\n", encoding="utf-8")
    events = Recorder()

    with pytest.raises(PackInvalid):
        scaffold_pack(path, identifier="a", name="n", events=events)

    assert events.events == []
