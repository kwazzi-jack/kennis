"""The add path for notes: identifiers in, documents on disk.

The order of work is the design here, and most of these tests assert it: the
collection is walked once, checksums settle duplicates before anything is
converted, and what survives is converted in runs rather than one at a time.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from kennis.engine.corpus.add import AddOptions, add_notes
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.converters import ConversionBatch
from kennis.engine.errors import InputError
from kennis.engine.events import (
    Diagnostic,
    ItemFinished,
    ItemStarted,
    OperationFinished,
    Outcome,
    Progress,
    Recorder,
)


class CountingConverter:
    """A converter that records every batch it was handed.

    Counting calls is how "the duplicate is detected before any conversion
    runs" is asserted: a timing measurement would be a proxy, the call count
    is the property itself.
    """

    name = "counting"
    formats = frozenset({"pdf", "docx", "pptx", "xlsx"})

    def __init__(self, failing: frozenset[str] = frozenset()) -> None:
        self.runs: list[tuple[Path, ...]] = []
        self.failing = failing

    @property
    def converted_paths(self) -> list[Path]:
        return [path for run in self.runs for path in run]

    def is_available(self) -> bool:
        return True

    def install_hint(self) -> str:
        return "install the counting converter"

    def convert(
        self, paths: Sequence[Path], *, page_limit: int | None = None
    ) -> ConversionBatch:
        self.runs.append(tuple(paths))
        return ConversionBatch(
            markdown={
                path: f"# {path.stem}\n\nConverted.\n"
                for path in paths
                if path.name not in self.failing
            },
            failure_reason="one document was unreadable" if self.failing else None,
        )


@pytest.fixture
def notes(tmp_path: Path) -> Collection:
    return Collection(root=tmp_path / "corpus", name="notes")


def a_note_file(path: Path, text: str = "# A note\n\nBody.\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def a_pdf(path: Path, body: bytes = b"%PDF-1.7\nfake\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


# ---------------------------------------------------------------------------
# Adding
# ---------------------------------------------------------------------------


def test_a_note_is_written_and_then_found(notes: Collection, tmp_path: Path):
    path = a_note_file(tmp_path / "A note.md")

    report = add_notes(notes, [str(path)])

    assert [outcome.outcome for outcome in report.outcomes] == [Outcome.ADDED]
    document = notes.resolve(report.outcomes[0].document_id or "")
    assert document.body == "# A note\n\nBody.\n"
    assert document.frontmatter.title == "A note"


def test_a_note_is_owned_by_the_user(notes: Collection, tmp_path: Path):
    add_notes(notes, [str(a_note_file(tmp_path / "A note.md"))])

    assert notes.contents().documents[0].frontmatter.owner == "user"


def test_a_note_records_where_it_came_from(notes: Collection, tmp_path: Path):
    path = a_note_file(tmp_path / "A note.md")

    add_notes(notes, [str(path)])

    source = notes.contents().documents[0].frontmatter.source
    assert source.origin == str(path)
    assert source.via == "verbatim"
    assert source.format == "markdown"
    assert source.sha256


def test_a_notes_identifier_is_minted_not_derived(notes: Collection, tmp_path: Path):
    """Notes have no natural key by definition, which is exactly why they are
    safe to mint randomly. An absent `id_from` is how a reader tells the two
    apart."""
    add_notes(notes, [str(a_note_file(tmp_path / "A note.md"))])

    assert notes.contents().documents[0].frontmatter.id_from is None


def test_two_notes_in_one_batch_get_different_identifiers(
    notes: Collection, tmp_path: Path
):
    """Every write updates the uniqueness record in place, so the second
    document in a batch sees the first."""
    first = a_note_file(tmp_path / "first.md", "# First\n")
    second = a_note_file(tmp_path / "second.md", "# Second\n")

    report = add_notes(notes, [str(first), str(second)])

    identifiers = {outcome.document_id for outcome in report.outcomes}
    assert len(identifiers) == 2


def test_two_notes_of_the_same_title_do_not_overwrite_each_other(
    notes: Collection, tmp_path: Path
):
    first = a_note_file(tmp_path / "one" / "n.md", "# Same\n\nFirst.\n")
    second = a_note_file(tmp_path / "two" / "n.md", "# Same\n\nSecond.\n")

    add_notes(notes, [str(first), str(second)])

    assert len(notes.contents().documents) == 2


def test_a_title_may_be_given_rather_than_taken_from_the_source(
    notes: Collection, tmp_path: Path
):
    path = a_note_file(tmp_path / "A note.md")

    add_notes(notes, [str(path)], AddOptions(title="A better title"))

    assert notes.contents().documents[0].frontmatter.title == "A better title"


def test_a_source_with_no_heading_is_titled_after_its_file(
    notes: Collection, tmp_path: Path
):
    path = a_note_file(tmp_path / "no-heading.md", "Just a body.\n")

    add_notes(notes, [str(path)])

    assert notes.contents().documents[0].frontmatter.title == "no-heading"


def test_kept_originals_become_assets_of_the_document(
    notes: Collection, tmp_path: Path
):
    path = a_note_file(tmp_path / "A note.md")

    add_notes(notes, [str(path)], AddOptions(keep_original=True))

    document = notes.contents().documents[0]
    assert document.wrapper_dir is not None
    assert (document.wrapper_dir / "A note.md").read_bytes() == path.read_bytes()
    assert document.frontmatter.source.original == "A note.md"


# ---------------------------------------------------------------------------
# Duplicates
# ---------------------------------------------------------------------------


def test_adding_the_same_file_twice_produces_one_document(
    notes: Collection, tmp_path: Path
):
    path = a_note_file(tmp_path / "A note.md")

    add_notes(notes, [str(path)])
    second = add_notes(notes, [str(path)])

    assert len(notes.contents().documents) == 1
    assert second.outcomes[0].outcome is Outcome.UNCHANGED


def test_the_second_add_reports_a_duplicate_rather_than_failing(
    notes: Collection, tmp_path: Path
):
    """The corpus already holds the document and nothing was written, which is
    the absence of news rather than a failure."""
    path = a_note_file(tmp_path / "A note.md")
    add_notes(notes, [str(path)])

    report = add_notes(notes, [str(path)])

    outcome = report.outcomes[0]
    assert outcome.outcome is Outcome.UNCHANGED
    assert outcome.document_id == notes.contents().documents[0].id
    assert outcome.reason


def test_a_duplicate_is_detected_before_any_conversion_runs(
    notes: Collection, tmp_path: Path
):
    """Re-adding a folder of fifty PDFs should cost fifty file reads, not
    fifty conversions whose results are then thrown away."""
    path = a_pdf(tmp_path / "paper.pdf")
    converter = CountingConverter()
    add_notes(notes, [str(path)], converter=converter)
    assert len(converter.converted_paths) == 1

    second = CountingConverter()
    report = add_notes(notes, [str(path)], converter=second)

    assert second.runs == []
    assert report.outcomes[0].outcome is Outcome.UNCHANGED


def test_the_same_file_named_twice_in_one_command_is_converted_once(
    notes: Collection, tmp_path: Path
):
    path = a_pdf(tmp_path / "paper.pdf")
    converter = CountingConverter()

    add_notes(notes, [str(path), str(path)], converter=converter)

    assert converter.converted_paths == [path]


def test_two_files_of_identical_content_in_one_batch_produce_one_document(
    notes: Collection, tmp_path: Path
):
    """The first write updates the uniqueness record, so the second sees it."""
    first = a_note_file(tmp_path / "a.md", "# Same content\n")
    second = a_note_file(tmp_path / "b.md", "# Same content\n")

    report = add_notes(notes, [str(first), str(second)])

    assert len(notes.contents().documents) == 1
    assert [outcome.outcome for outcome in report.outcomes] == [
        Outcome.ADDED,
        Outcome.UNCHANGED,
    ]


# ---------------------------------------------------------------------------
# Failures that do not stop the batch
# ---------------------------------------------------------------------------


def test_a_converter_failure_fails_only_its_own_document(
    notes: Collection, tmp_path: Path
):
    good = a_pdf(tmp_path / "good.pdf", b"%PDF good\n")
    bad = a_pdf(tmp_path / "doomed.pdf", b"%PDF bad\n")
    converter = CountingConverter(failing=frozenset({"doomed.pdf"}))

    report = add_notes(notes, [str(good), str(bad)], converter=converter)

    by_identifier = {outcome.identifier: outcome for outcome in report.outcomes}
    assert by_identifier[str(good)].outcome is Outcome.ADDED
    assert by_identifier[str(bad)].outcome is Outcome.FAILED
    assert by_identifier[str(bad)].reason
    assert len(notes.contents().documents) == 1


def test_an_unresolvable_identifier_fails_only_itself(
    notes: Collection, tmp_path: Path
):
    good = a_note_file(tmp_path / "A note.md")

    report = add_notes(notes, [str(good), "welman2024"])

    outcomes = {outcome.identifier: outcome.outcome for outcome in report.outcomes}
    assert outcomes[str(good)] is Outcome.ADDED
    assert outcomes["welman2024"] is Outcome.FAILED
    assert len(notes.contents().documents) == 1


def test_an_argument_naming_nothing_stops_the_command_before_it_starts(
    notes: Collection, tmp_path: Path
):
    """Raised rather than collected: the command as typed cannot be carried
    out, and running the rest would leave the user to find the gap."""
    with pytest.raises(InputError):
        add_notes(notes, [f"{tmp_path}/*.md"])


# ---------------------------------------------------------------------------
# Walks
# ---------------------------------------------------------------------------


def test_a_walk_mirrors_its_subdirectories_onto_groups(
    notes: Collection, tmp_path: Path
):
    source = tmp_path / "code"
    a_note_file(source / "top.md", "# Top\n")
    a_note_file(source / "gains" / "x.md", "# X\n")

    add_notes(notes, [str(source)])

    written = {
        document.frontmatter.title: document.md_path.relative_to(notes.path).parent
        for document in notes.contents().documents
    }
    assert written == {"Top": Path("."), "X": Path("gains")}


def test_a_group_is_a_prefix_over_a_walk_not_an_override(
    notes: Collection, tmp_path: Path
):
    """Collapsing every walked file into one flat group would undo the thing
    the mirrored structure is for: keeping a `README.md` per subdirectory
    apart."""
    source = tmp_path / "code"
    a_note_file(source / "gains" / "x.md", "# X\n")

    add_notes(notes, [str(source)], AddOptions(group="reading"))

    assert notes.contents().documents[0].md_path.relative_to(notes.path).parent == Path(
        "reading/gains"
    )


def test_a_group_places_a_named_file(notes: Collection, tmp_path: Path):
    add_notes(
        notes,
        [str(a_note_file(tmp_path / "A note.md"))],
        AddOptions(group="reading"),
    )

    assert notes.contents().documents[0].md_path.parent == notes.path / "reading"


def test_files_the_walk_declined_reach_the_report(notes: Collection, tmp_path: Path):
    """A walk that silently ignored half a directory would leave the user
    believing the corpus holds something it does not."""
    source = tmp_path / "code"
    a_note_file(source / "a.md", "# A\n")
    a_pdf(source / "binary.so", b"\x7fELF")

    report = add_notes(notes, [str(source)])

    skipped = [
        outcome for outcome in report.outcomes if outcome.outcome is Outcome.SKIPPED
    ]
    assert len(skipped) == 1
    assert "binary.so" in skipped[0].identifier


# ---------------------------------------------------------------------------
# Batching
# ---------------------------------------------------------------------------


def test_a_batch_is_converted_in_runs(notes: Collection, tmp_path: Path):
    """One run over a whole folder reports no progress and keeps nothing if
    it is interrupted, because the converter writes nothing until a run
    finishes."""
    paths = [
        a_pdf(tmp_path / f"p{index}.pdf", f"%PDF {index}\n".encode())
        for index in range(5)
    ]
    converter = CountingConverter()

    add_notes(
        notes,
        [str(path) for path in paths],
        AddOptions(batch_size=2),
        converter=converter,
    )

    assert [len(run) for run in converter.runs] == [2, 2, 1]


def test_a_batch_size_of_zero_is_one_run(notes: Collection, tmp_path: Path):
    paths = [
        a_pdf(tmp_path / f"p{index}.pdf", f"%PDF {index}\n".encode())
        for index in range(3)
    ]
    converter = CountingConverter()

    add_notes(
        notes,
        [str(path) for path in paths],
        AddOptions(batch_size=0),
        converter=converter,
    )

    assert len(converter.runs) == 1


def test_a_text_source_needs_no_converter_at_all(notes: Collection, tmp_path: Path):
    converter = CountingConverter()

    add_notes(notes, [str(a_note_file(tmp_path / "A note.md"))], converter=converter)

    assert converter.runs == []


# ---------------------------------------------------------------------------
# The event stream
# ---------------------------------------------------------------------------


def test_every_item_is_started_and_finished(notes: Collection, tmp_path: Path):
    first = a_note_file(tmp_path / "a.md", "# A\n")
    second = a_note_file(tmp_path / "b.md", "# B\n")
    recorder = Recorder()

    add_notes(notes, [str(first), str(second)], events=recorder)

    assert len(recorder.events_of_type(ItemStarted)) == 2
    assert len(recorder.events_of_type(ItemFinished)) == 2


def test_the_stream_says_what_became_of_each_item(notes: Collection, tmp_path: Path):
    path = a_note_file(tmp_path / "a.md", "# A\n")
    add_notes(notes, [str(path)])
    recorder = Recorder()

    add_notes(notes, [str(path)], events=recorder)

    assert recorder.outcomes() == {str(path): Outcome.UNCHANGED}


def test_a_conversion_run_is_the_only_moment_there_is_to_report(
    notes: Collection, tmp_path: Path
):
    paths = [
        a_pdf(tmp_path / f"p{index}.pdf", f"%PDF {index}\n".encode())
        for index in range(4)
    ]
    recorder = Recorder()

    add_notes(
        notes,
        [str(path) for path in paths],
        AddOptions(batch_size=2),
        converter=CountingConverter(),
        events=recorder,
    )

    progress = recorder.events_of_type(Progress)
    assert [(event.completed, event.total) for event in progress] == [(1, 2), (2, 2)]


def test_the_operation_reports_its_counts_when_it_finishes(
    notes: Collection, tmp_path: Path
):
    path = a_note_file(tmp_path / "a.md", "# A\n")
    add_notes(notes, [str(path)])
    recorder = Recorder()

    add_notes(
        notes,
        [str(path), str(a_note_file(tmp_path / "b.md", "# B\n"))],
        events=recorder,
    )

    finished = recorder.events_of_type(OperationFinished)
    assert len(finished) == 1
    assert finished[0].counts == {Outcome.ADDED: 1, Outcome.UNCHANGED: 1}
    assert finished[0].elapsed_seconds >= 0


def test_a_dotfile_title_is_reported_as_a_diagnostic(notes: Collection, tmp_path: Path):
    """The dot is stripped so the filename stays visible to the walk, which
    means the file on disk is not named what the title says."""
    path = a_note_file(tmp_path / "bashrc.md", "# .bashrc\n\nBody.\n")
    recorder = Recorder()

    add_notes(notes, [str(path)], events=recorder)

    diagnostics = recorder.events_of_type(Diagnostic)
    assert len(diagnostics) == 1
    assert "dot" in diagnostics[0].message


def test_an_add_that_went_smoothly_produces_no_diagnostics(
    notes: Collection, tmp_path: Path
):
    recorder = Recorder()

    add_notes(notes, [str(a_note_file(tmp_path / "a.md", "# A\n"))], events=recorder)

    assert recorder.events_of_type(Diagnostic) == []


def test_a_caller_wanting_only_the_report_need_not_supply_a_sink(
    notes: Collection, tmp_path: Path
):
    report = add_notes(notes, [str(a_note_file(tmp_path / "a.md", "# A\n"))])

    assert report.counts == {Outcome.ADDED: 1}


def test_adding_nothing_is_not_an_error(notes: Collection):
    report = add_notes(notes, [])

    assert report.outcomes == []
    assert report.counts == {}


# ---------------------------------------------------------------------------
# A collection holding a document kennis cannot read
# ---------------------------------------------------------------------------


def break_one_document(collection: Collection) -> Path:
    """Add a key that `extra="forbid"` refuses - which is what anybody editing
    YAML frontmatter by hand would try."""
    document = collection.contents().documents[0]
    text = document.md_path.read_text(encoding="utf-8")
    document.md_path.write_text(
        text.replace("title:", "tags: [physics]\ntitle:"), encoding="utf-8"
    )
    return document.md_path


def test_one_unreadable_document_does_not_stop_an_unrelated_add(
    notes: Collection, tmp_path: Path
):
    """The error used to name a document the user was not touching, and its
    own resolution named a command that would hit the same wall."""
    add_notes(notes, [str(a_note_file(tmp_path / "old.md", "# Old\n"))])
    break_one_document(notes)

    report = add_notes(notes, [str(a_note_file(tmp_path / "new.md", "# New\n"))])

    assert [outcome.outcome for outcome in report.outcomes] == [Outcome.ADDED]


def test_an_unreadable_document_is_reported_rather_than_passed_over(
    notes: Collection, tmp_path: Path
):
    """A corpus served nine tenths of in silence is worse than one that says
    what is wrong."""
    add_notes(notes, [str(a_note_file(tmp_path / "old.md", "# Old\n"))])
    broken = break_one_document(notes)
    recorder = Recorder()

    add_notes(
        notes, [str(a_note_file(tmp_path / "new.md", "# New\n"))], events=recorder
    )

    diagnostics = recorder.events_of_type(Diagnostic)
    assert len(diagnostics) == 1
    assert broken.name in diagnostics[0].message


def test_an_unreadable_document_still_reserves_its_identifier(
    notes: Collection, tmp_path: Path
):
    """Skipping it outright would let `mint_id` reissue its identifier, and
    two documents sharing one is a corruption worse than the first."""
    add_notes(notes, [str(a_note_file(tmp_path / "old.md", "# Old\n"))])
    broken = break_one_document(notes)
    taken = next(
        line.split(": ", 1)[1].strip()
        for line in broken.read_text(encoding="utf-8").splitlines()
        if line.startswith("id: ")
    )

    add_notes(notes, [str(a_note_file(tmp_path / "new.md", "# New\n"))])

    minted = [facts.identifier for facts in notes.survey()]
    assert minted.count(taken) == 1


def test_an_unreadable_document_still_answers_for_its_content(
    notes: Collection, tmp_path: Path
):
    """Its checksum is a plain YAML key, so re-adding its source is still
    recognised as a duplicate rather than writing a second copy."""
    source = a_note_file(tmp_path / "old.md", "# Old\n")
    add_notes(notes, [str(source)])
    break_one_document(notes)

    report = add_notes(notes, [str(source)])

    assert report.outcomes[0].outcome is Outcome.UNCHANGED
    assert len(notes.survey()) == 1
