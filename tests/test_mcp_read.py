"""The three `read_*` tools: the follow-up to a search hit.

**There is no `read_context`.** A bundle file is a file in the user's
own repository, so a context hit's handle is a path and the agent opens
it with native file tools - the same reason `kennis read` refuses
`--collection context`.

Design section 20's exception covers document spans as well as hits, so
the provenance line a tool returns and the one `kennis read` prints to
stderr are the same text. The first test holds that.

The rest cover what batching means: one call carries several requests,
and one bad request must not cost the others.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.context import existing_corpus
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.layout import index_root
from kennis.engine.rag.index import load_index
from kennis.mcp.tools.read import ReadRequest, read_docs, read_literature, read_notes


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    return tmp_path


@pytest.fixture
def run() -> CliRunner:
    return CliRunner()


@pytest.fixture
def corpus(isolated: Path, run: CliRunner) -> Path:
    assert run.invoke(main, ["corpus", "init"]).exit_code == 0
    return isolated / "corpus"


def a_note(run: CliRunner, tmp_path: Path, name: str, body: str) -> str:
    """One note in the corpus, and the identifier it was given.

    The identifier is read back from the collection rather than parsed
    out of `corpus list`, so a change to that command's layout does not
    silently hand these tests the wrong string.
    """
    source = tmp_path / "sources" / f"{name}.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(f"# {name}\n\n{body}\n", encoding="utf-8")
    added = run.invoke(main, ["corpus", "add", "-n", str(source)])
    assert added.exit_code == 0, added.output
    held = Collection(root=existing_corpus().corpus_root, name="notes").contents()
    for document in held.documents:
        if document.frontmatter.title == name:
            return document.id
    raise AssertionError(f"no identifier for {name}")


def a_long_note(run: CliRunner, tmp_path: Path, chunks_wanted: int) -> str:
    """A note that genuinely spans several chunks, and its identifier.

    The chunk count is asserted rather than assumed. The target is 1500
    characters, so forty short paragraphs are *one* chunk - and a test
    that asks for `chunk_index=1` on a one-chunk document is testing the
    out-of-range path while appearing to test a window.
    """
    paragraph = " ".join("Paragraph {number} about antenna gains." for _ in range(12))
    body = "\n\n".join(
        paragraph.format(number=number) for number in range(chunks_wanted * 4)
    )
    identifier = a_note(run, tmp_path, "long", body)
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0
    index = load_index(index_root(existing_corpus().corpus_root), "notes")
    held = [chunk for chunk in index.chunks if chunk.document_id == identifier]
    assert len(held) >= chunks_wanted, f"only {len(held)} chunks"
    return identifier


# ---------------------------------------------------------------------------
# The shared provenance line
# ---------------------------------------------------------------------------


def test_the_provenance_line_is_the_same_in_both_front_ends(
    corpus: Path, isolated: Path, run: CliRunner
):
    """Section 20's exception applies to spans as it does to hits."""
    identifier = a_note(run, isolated, "calibration", "Antenna gains and sky models.")
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0

    printed = run.invoke(main, ["read", identifier, "--chunks", "0:1"])
    assert printed.exit_code == 0, printed.output
    answered = read_notes([ReadRequest(document_id=identifier, chunk_index=0)])

    provenance = next(line for line in answered.splitlines() if "[notes]" in line)
    assert provenance.strip() in printed.output


# ---------------------------------------------------------------------------
# What the tools do
# ---------------------------------------------------------------------------


def test_a_chunk_read_returns_the_surrounding_prose(
    corpus: Path, isolated: Path, run: CliRunner
):
    identifier = a_note(run, isolated, "calibration", "Antenna gains and sky models.")
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0

    answered = read_notes([ReadRequest(document_id=identifier, chunk_index=0)])

    assert "Antenna gains and sky models." in answered


def test_a_whole_document_needs_no_index(corpus: Path, isolated: Path, run: CliRunner):
    """`chunk_index` omitted reads the body from the corpus, as `kennis
    read` without `--chunks` does, so a document that has never been
    indexed is still readable."""
    identifier = a_note(run, isolated, "calibration", "Antenna gains and sky models.")

    answered = read_notes([ReadRequest(document_id=identifier)])

    assert "Antenna gains and sky models." in answered


def test_before_and_after_widen_the_window(
    corpus: Path, isolated: Path, run: CliRunner
):
    """The neighbourhood of a hit, which is what an agent has from a
    search: a chunk index, and a wish for a little more around it."""
    identifier = a_long_note(run, isolated, chunks_wanted=4)

    narrow = read_notes(
        [ReadRequest(document_id=identifier, chunk_index=1, before=0, after=0)]
    )
    wide = read_notes(
        [ReadRequest(document_id=identifier, chunk_index=1, before=1, after=1)]
    )

    # Both must be real passages. Without this the test passes when the
    # narrow read failed and returned a short error block instead.
    assert "chunk 1" in narrow
    assert "chunks 0 to 2" in wide
    assert len(wide) > len(narrow)


def test_a_hit_at_chunk_zero_does_not_ask_for_the_last_chunk(
    corpus: Path, isolated: Path, run: CliRunner
):
    """`chunk_index=0` with `before=1` would compute `-1`, which is the
    document's *last* chunk - so the read would return the wrong end of
    it. The same arithmetic the printed `--chunks` hint gets right."""
    identifier = a_long_note(run, isolated, chunks_wanted=4)

    answered = read_notes(
        [ReadRequest(document_id=identifier, chunk_index=0, before=1)]
    )

    assert "Paragraph 0 about antenna gains." in answered
    assert "Paragraph 15 about antenna gains." not in answered


def test_both_kinds_of_read_name_the_document_the_same_way(
    corpus: Path, isolated: Path, run: CliRunner
):
    """One path convention across the two answers an agent gets.

    A whole-document read took its path from `Document.md_path`, which
    is absolute, while a chunk read took the index's `source_path`,
    which is relative to the corpus root. An agent shown both has been
    shown one document under two addresses, and the absolute one
    carries the user's account name to a model provider. Concern #299.
    """
    identifier = a_note(run, isolated, "calibration", "Antenna gains.")
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0

    whole = read_notes([ReadRequest(document_id=identifier)])
    passage = read_notes([ReadRequest(document_id=identifier, chunk_index=0)])

    assert "notes/calibration.md" in whole
    assert "notes/calibration.md" in passage
    assert str(existing_corpus().corpus_root) not in whole


# ---------------------------------------------------------------------------
# Batching
# ---------------------------------------------------------------------------


def test_several_requests_are_answered_in_one_call(
    corpus: Path, isolated: Path, run: CliRunner
):
    first = a_note(run, isolated, "calibration", "Antenna gains.")
    second = a_note(run, isolated, "imaging", "Deconvolution and cleaning.")
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0

    answered = read_notes(
        [ReadRequest(document_id=first), ReadRequest(document_id=second)]
    )

    assert "Antenna gains." in answered
    assert "Deconvolution and cleaning." in answered


def test_one_bad_identifier_does_not_cost_the_others(
    corpus: Path, isolated: Path, run: CliRunner
):
    """The whole point of batching. An agent that constructed one id
    wrongly still gets the three it copied correctly, and is told which
    one failed."""
    good = a_note(run, isolated, "calibration", "Antenna gains.")

    answered = read_notes(
        [ReadRequest(document_id="notarealid"), ReadRequest(document_id=good)]
    )

    assert "Antenna gains." in answered
    assert "notarealid" in answered


def test_an_empty_batch_says_so_rather_than_returning_nothing(corpus: Path):
    assert "no requests" in read_notes([])


# ---------------------------------------------------------------------------
# Each tool stays in its collection
# ---------------------------------------------------------------------------


def test_a_note_cannot_be_read_through_the_literature_tool(
    corpus: Path, isolated: Path, run: CliRunner
):
    """The collection is fixed by which tool was called. Otherwise
    `read_literature` would quietly serve a note and an agent citing it
    would attribute a user's jotting to a paper."""
    identifier = a_note(run, isolated, "calibration", "Antenna gains.")

    answered = read_literature([ReadRequest(document_id=identifier)])

    assert "Antenna gains." not in answered
    assert identifier in answered


def test_read_docs_is_a_tool_of_its_own(corpus: Path):
    assert "no requests" in read_docs([])


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------


def test_a_long_whole_document_is_cut_and_says_so(
    corpus: Path, isolated: Path, run: CliRunner
):
    """A tool answer goes into a context window. A hundred-page paper
    read whole would fill it, and an agent handed a silent truncation
    would go on to reason about a document it has only part of - so the
    cut is announced, and names the argument that reads the rest."""
    body = "\n\n".join(f"Paragraph {number} about gains." for number in range(4000))
    identifier = a_note(run, isolated, "enormous", body)

    answered = read_notes([ReadRequest(document_id=identifier)])

    assert len(answered) < len(body)
    assert "chunk_index" in answered


def test_a_short_whole_document_is_not_cut(
    corpus: Path, isolated: Path, run: CliRunner
):
    """The other side of the cut, so the test above cannot pass by the
    tool truncating everything."""
    identifier = a_note(run, isolated, "calibration", "Antenna gains and sky models.")

    answered = read_notes([ReadRequest(document_id=identifier)])

    assert "chunk_index" not in answered


def test_a_huge_batch_is_refused_rather_than_answered_in_part(
    corpus: Path, isolated: Path, run: CliRunner
):
    """Silently dropping the tail would answer a question the caller did
    not ask, and they would not know which requests were served."""
    identifier = a_note(run, isolated, "calibration", "Antenna gains.")
    many = [ReadRequest(document_id=identifier) for _ in range(40)]

    answered = read_notes(many)

    assert "Antenna gains." not in answered
    assert "40" in answered
