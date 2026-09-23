"""`remember`: prose in, a note on disk, and findable without a second command.

Design section 12. This is the one verb that takes what the user is telling
kennis now rather than a file or an identifier, so two properties matter that
no other write path has: the text is stored exactly as given, and the thing
just remembered can be searched for in the same session.

The crossing test is `test_a_remembered_note_can_be_searched_for_immediately`.
The plan names this risk by name: a document written by a new path that the
loader cannot see, silently. Nothing else catches it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kennis.engine.corpus.add import AddOptions, add_notes
from kennis.engine.corpus.collection import Collection
from kennis.engine.errors import InputError
from kennis.engine.events import Outcome
from kennis.engine.rag.binding import binding_from
from kennis.engine.rag.index import (
    build_index,
    index_id_for,
    load_index,
    read_manifest,
)
from kennis.engine.rag.loaders import CollectionLoader
from kennis.engine.rag.search import search
from kennis.engine.remember import RememberOptions, remember
from kennis.engine.settings import ChunkingSettings, EmbeddingSettings

# Lexical only. A dense binding would download a model, and nothing these
# tests assert is about embedding.
LEXICAL = binding_from(ChunkingSettings(), EmbeddingSettings(backend="none"))


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    (root / "notes").mkdir(parents=True)
    return root


def notes_of(corpus: Path) -> Collection:
    return Collection(root=corpus, name="notes")


def a_note_file(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# What is written
# ---------------------------------------------------------------------------


def test_the_text_is_stored_exactly_as_given(corpus: Path):
    text = "QuartiCal needs --input-ms-time-chunk tuned for long tracks"

    report = remember(corpus, text, binding=LEXICAL, index=False)

    document = notes_of(corpus).resolve(report.document_id)
    assert document.body == text


def test_a_remembered_note_is_owned_by_the_user(corpus: Path):
    """Section 12: `owner: user`, so no pack and no sync will overwrite it."""
    remember(corpus, "A thing worth keeping.", binding=LEXICAL, index=False)

    assert notes_of(corpus).contents().documents[0].frontmatter.owner == "user"


def test_a_remembered_note_says_it_was_remembered(corpus: Path):
    """`source.via: remember` is what distinguishes a thing the user told
    kennis from a document kennis ingested. No other value says that, which
    is why the vocabulary gains one rather than reusing `verbatim`."""
    remember(corpus, "A thing worth keeping.", binding=LEXICAL, index=False)

    source = notes_of(corpus).contents().documents[0].frontmatter.source
    assert source.via == "remember"
    assert source.origin == "remember:inline"


def test_an_origin_can_name_the_file_the_text_came_from(corpus: Path, tmp_path: Path):
    """`remember --from notes.md` is still a remembered note - it entered by
    being told, not by being ingested - but where the text came from is worth
    recording."""
    path = a_note_file(tmp_path / "jottings.md", "Some jottings.")

    remember(
        corpus,
        "Some jottings.",
        binding=LEXICAL,
        origin=f"path:{path}",
        index=False,
    )

    source = notes_of(corpus).contents().documents[0].frontmatter.source
    assert source.via == "remember"
    assert source.origin == f"path:{path}"


def test_a_remembered_note_is_reported_with_its_own_path(corpus: Path):
    report = remember(corpus, "A thing worth keeping.", binding=LEXICAL, index=False)

    assert report.outcome is Outcome.ADDED
    assert report.path.is_file()
    assert "A thing worth keeping." in report.path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The title
# ---------------------------------------------------------------------------


def test_a_leading_heading_becomes_the_title(corpus: Path):
    report = remember(
        corpus, "# Calibration notes\n\nBody.", binding=LEXICAL, index=False
    )

    assert report.title == "Calibration notes"


def test_without_a_heading_the_first_line_becomes_the_title(corpus: Path):
    """A note is addressed by its identifier, but its filename comes from its
    title, so the fallback has to be something recognisable in `corpus
    tree`."""
    report = remember(
        corpus,
        "Tune the time chunk\n\nand then the frequency chunk.",
        binding=LEXICAL,
        index=False,
    )

    assert report.title == "Tune the time chunk"


def test_a_long_first_line_is_trimmed_at_a_word_boundary(corpus: Path):
    text = (
        "QuartiCal needs its input measurement set time chunk tuned "
        "whenever the track is longer than a few hours, otherwise it "
        "allocates far too much memory."
    )

    report = remember(corpus, text, binding=LEXICAL, index=False)

    assert len(report.title) <= 60
    assert text.startswith(report.title)
    assert not report.title.endswith(" ")
    # Trimmed between words, not through one.
    assert text[len(report.title)] in " "


def test_a_given_title_wins_over_both(corpus: Path):
    report = remember(
        corpus,
        "# Calibration notes\n\nBody.",
        binding=LEXICAL,
        options=RememberOptions(title="Something else"),
        index=False,
    )

    assert report.title == "Something else"


def test_text_that_is_only_whitespace_is_refused(corpus: Path):
    """Nothing was said, so there is nothing to remember. Writing an empty
    document would put an untitled, unsearchable file in the corpus."""
    with pytest.raises(InputError):
        remember(corpus, "   \n\n  ", binding=LEXICAL, index=False)


# ---------------------------------------------------------------------------
# Saying the same thing twice
# ---------------------------------------------------------------------------


def test_remembering_the_same_text_twice_writes_one_document(corpus: Path):
    """An agent repeating itself is the expected case once the MCP server
    exists, and two identical notes would both be returned by every search
    that matched either."""
    text = "The pipeline runs on 16 cores."

    first = remember(corpus, text, binding=LEXICAL, index=False)
    second = remember(corpus, text, binding=LEXICAL, index=False)

    assert first.outcome is Outcome.ADDED
    assert second.outcome is Outcome.UNCHANGED
    assert second.document_id == first.document_id
    assert len(notes_of(corpus).contents().documents) == 1


def test_a_note_with_a_group_lands_in_that_subdirectory(corpus: Path):
    report = remember(
        corpus,
        "A thing worth keeping.",
        binding=LEXICAL,
        options=RememberOptions(group="calibration"),
        index=False,
    )

    assert report.path.parent.name == "calibration"


# ---------------------------------------------------------------------------
# Indexing its own write
# ---------------------------------------------------------------------------


def indexed_corpus(corpus: Path, tmp_path: Path) -> Path:
    """A corpus whose notes collection has been indexed once already."""
    collection = notes_of(corpus)
    add_notes(
        collection,
        [str(a_note_file(tmp_path / "Existing.md", "# Existing\n\nOld words."))],
        AddOptions(),
    )
    build_index(
        CollectionLoader(collection), index_root=corpus / "index", binding=LEXICAL
    )
    return corpus


def test_a_remembered_note_can_be_searched_for_immediately(
    corpus: Path, tmp_path: Path
):
    """**The crossing test.** A document written by a new path that the
    loader cannot see is the failure this project has already met once, and
    it fails silently: the write succeeds, the index reports success, and the
    document is simply absent from every result.
    """
    indexed_corpus(corpus, tmp_path)

    report = remember(
        corpus,
        "Ionospheric screens need direction-dependent solutions.",
        binding=LEXICAL,
    )

    assert report.index_outcome == "indexed"
    index = load_index(corpus / "index", "notes")
    hits = search(index, "ionospheric screens", mode="bm25")
    assert any(hit.chunk.document_id == report.document_id for hit in hits)


def test_an_unindexed_collection_is_not_indexed_by_a_single_note(corpus: Path):
    """The cost, not the lock. A notes collection that has never been indexed
    would make one remembered line pay for a full cold build - 50s for a
    1942-chunk corpus by design section 15 - because nothing is cached. With
    a manifest already present the cache holds every existing chunk and only
    the new ones are embedded.
    """
    report = remember(corpus, "A thing worth keeping.", binding=LEXICAL)

    assert report.index_outcome == "unindexed"
    assert read_manifest(corpus / "index", "notes") is None
    assert notes_of(corpus).resolve(report.document_id).body


def test_indexing_can_be_switched_off(corpus: Path, tmp_path: Path):
    indexed_corpus(corpus, tmp_path)
    before = read_manifest(corpus / "index", "notes")

    report = remember(corpus, "A thing worth keeping.", binding=LEXICAL, index=False)

    assert report.index_outcome == "skipped"
    assert read_manifest(corpus / "index", "notes") == before


def test_the_report_counts_what_the_rebuilt_index_holds(corpus: Path, tmp_path: Path):
    """The whole collection, not the one note. What a caller wants to say
    afterwards is how big the index now is, and a per-note count would be the
    number 1 every time."""
    indexed_corpus(corpus, tmp_path)

    report = remember(corpus, "A thing worth keeping.", binding=LEXICAL)

    assert report.chunk_count == len(load_index(corpus / "index", "notes").chunks)


def test_a_sentence_does_not_carry_its_full_stop_into_the_title(corpus: Path):
    """Found by running the command, not by the suite.

    Remembered prose is a sentence and ends in a full stop; `title_filename`
    appends `.md`; so the first note written this way landed on disk as
    `Ionospheric screens need direction-dependent solutions..md`. Every
    fixture above happened to be a fragment or a heading.
    """
    report = remember(
        corpus, "Ionospheric screens need solutions.", binding=LEXICAL, index=False
    )

    assert report.title == "Ionospheric screens need solutions"
    assert report.path.name == "Ionospheric screens need solutions.md"


def test_a_given_title_keeps_its_own_punctuation(corpus: Path):
    """The trimming above is about a title kennis derived. One the user chose
    is what they asked for, full stop and all."""
    report = remember(
        corpus,
        "Body.",
        binding=LEXICAL,
        options=RememberOptions(title="Ask why."),
        index=False,
    )

    assert report.title == "Ask why."


def test_a_note_does_not_build_an_index_of_a_different_kind(
    corpus: Path, tmp_path: Path
):
    """Sketch uncertainty 4, and the reason the manifest check compares the
    binding rather than merely asking whether a manifest exists.

    A user who indexes lexically and then sets an embedding backend has a
    manifest, but it is a lexical one. Rebuilding into a dense index would
    make one remembered line download a 65 MB model and re-embed every
    existing chunk - design section 15 measures that at 33s plus 50s - inside
    a command that looked like it would cost nothing.
    """
    indexed_corpus(corpus, tmp_path)
    dense = binding_from(ChunkingSettings(), EmbeddingSettings(backend="fastembed"))

    report = remember(corpus, "A thing worth keeping.", binding=dense)

    assert report.index_outcome == "unindexed"
    # The lexical index is still the published one, untouched.
    manifest = read_manifest(corpus / "index", "notes")
    assert manifest is not None
    assert manifest.index_id == index_id_for(LEXICAL)
