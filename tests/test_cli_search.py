"""Searching the index, and reading what surrounds a hit.

The last thing v0.1 needs to be usable. These are the command-line half; the
retrieval itself is covered by the milestone 3 suite.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    return tmp_path / "corpus"


@pytest.fixture
def run() -> CliRunner:
    return CliRunner()


@pytest.fixture
def corpus(isolated: Path, run: CliRunner) -> Path:
    assert run.invoke(main, ["corpus", "init"]).exit_code == 0
    return isolated


def a_source(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / "sources" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {name.removesuffix('.md')}\n\n{body}\n", encoding="utf-8")
    return path


def indexed_notes(run: CliRunner, tmp_path: Path, **bodies: str) -> None:
    """A notes collection holding one document per keyword, then indexed."""
    for name, body in bodies.items():
        source = a_source(tmp_path, f"{name}.md", body)
        assert run.invoke(main, ["corpus", "add", "-n", str(source)]).exit_code == 0
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0


def identifier_of(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("id:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError(f"no identifier in {path}")


def group_of(output: str, collection: str) -> str:
    """The lines belonging to one collection's group, heading excluded.

    A group runs from its heading to the next heading or the end. The
    heading is the capitalised collection at the margin, which is the
    grammar `corpus status` uses and nothing else in this output does.
    """
    lines = output.splitlines()
    headings = [
        index
        for index, line in enumerate(lines)
        if line[:1].isupper() and line[:1] == line[:1].strip()
    ]
    wanted = f"{collection.capitalize()} "
    for position, index in enumerate(headings):
        if not lines[index].startswith(wanted):
            continue
        end = headings[position + 1] if position + 1 < len(headings) else len(lines)
        return "\n".join(lines[index + 1 : end])
    return ""


def hits_in(output: str, collection: str | None = None) -> int:
    """How many result lines the report printed, in total or in one group.

    Counted by the handle line, which every hit has whatever `--scores` is
    set to and nothing else does. Two spellings, because a corpus hit's
    handle is `id=` plus a chunk index and a context hit's is `path=` - a
    bundle document is addressed by where it is, not by an identifier
    kennis minted.
    """
    text = output if collection is None else group_of(output, collection)
    return text.count("id=") + text.count("path=")


def a_docs_page(corpus: Path, page: str, body: str) -> None:
    """A docs page written as `add_docs` writes one.

    Hand-written because crawling a site needs a network, and what these
    tests need from docs is only that a second collection has an index.
    """
    path = corpus / "docs" / "numpy" / f"{page}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\n"
        f"id: docsnumpy{page[:2]}\n"
        f"title: {page}\n"
        f"owner: user\n"
        f"id_from: 'docs:numpy/{page}'\n"
        f"source:\n"
        f"  from: 'url:https://numpy.org/doc/{page}'\n"
        f"  via: html\n"
        f"  format: html\n"
        f"docs:\n"
        f"  project: numpy\n"
        f"  page: {page}\n"
        f"---\n\n# {page}\n\n{body}\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


def test_search_finds_the_document_that_says_it(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    indexed_notes(
        run,
        tmp_path,
        trees="Deciduous trees shed their leaves every autumn.",
        rivers="Rivers carry sediment towards the delta.",
    )

    result = run.invoke(main, ["search", "sediment"])

    assert result.exit_code == 0, result.output
    assert "rivers" in result.output.lower()
    assert "trees" not in result.output.lower()


def test_each_group_names_its_collection_and_its_relevance_basis(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """The heading carries both, so a level below it can be read correctly.

    The basis line used to be printed once for the whole report and dropped
    whenever two collections disagreed about it - which is the one case a
    reader needs it. Concern #230.
    """
    indexed_notes(run, tmp_path, rivers="Rivers carry sediment to the delta.")

    result = run.invoke(main, ["search", "sediment"])

    assert result.exit_code == 0, result.output
    assert "Notes" in result.output
    assert "relevance relative to the best lexical match" in result.output
    assert hits_in(result.output, "notes") == 1


def test_a_sweep_skips_a_collection_with_no_index(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """A collection you never mentioned is not part of the answer. Failing
    the run would make every search depend on having indexed all three.

    It used to assert that the two unindexed collections were named in a
    warning. They are empty here, and an empty collection is no longer
    reported - `kennis corpus index` skips one, so the line named a command
    that changes nothing. `test_an_unindexed_corpus_collection_is_still_reported`
    covers the case that is still news, and
    `test_an_empty_corpus_collection_is_not_reported_as_unindexed` covers
    this one directly.
    """
    indexed_notes(run, tmp_path, rivers="Rivers carry sediment to the delta.")

    result = run.invoke(main, ["search", "sediment"])

    assert result.exit_code == 0, result.output
    assert hits_in(result.output) == 1


def test_naming_a_collection_with_no_index_fails(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """The one you named is what you asked for. Answering `no hits` when the
    truth is `never indexed` is the failure this exists to prevent.

    Notes is indexed first on purpose: without it the command would fail
    anyway, because nothing at all is indexed, and the test would pass
    without the promise it is about ever being kept.
    """
    indexed_notes(run, tmp_path, rivers="Rivers carry sediment to the delta.")

    result = run.invoke(main, ["search", "sediment", "--collection", "docs"])

    assert result.exit_code != 0
    assert "docs" in result.output
    assert hits_in(result.output) == 0


def test_a_hybrid_search_of_a_lexical_index_falls_back_and_says_so(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """A silent downgrade would have people comparing result quality against
    a dense index they do not have."""
    indexed_notes(run, tmp_path, rivers="Rivers carry sediment to the delta.")

    result = run.invoke(main, ["search", "sediment", "--mode", "hybrid"])

    assert result.exit_code == 0, result.output
    assert "lexical" in result.output.lower() or "bm25" in result.output.lower()


def test_top_k_bounds_the_answer(corpus: Path, run: CliRunner, tmp_path: Path):
    """Counted exactly. `fewer than` would pass for a command that returned
    one hit whatever was asked for."""
    indexed_notes(
        run,
        tmp_path,
        first="Sediment settles slowly.",
        second="Sediment moves with the current.",
        third="Sediment builds the delta.",
    )

    one = run.invoke(main, ["search", "sediment", "--top-k", "1"])
    three = run.invoke(main, ["search", "sediment", "--top-k", "3"])

    assert one.exit_code == 0 and three.exit_code == 0, one.output + three.output
    assert hits_in(one.output) == 1
    assert hits_in(three.output) == 3


def test_top_k_bounds_each_group_rather_than_the_total(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """`-k` is per collection now.

    Each group is a complete answer from its source; a group truncated to
    one because another collection happened to be noisier is worse than a
    longer report. Concern #231.
    """
    a_docs_page(corpus, "indexing", "Sediment is not an indexing concept.")
    indexed_notes(
        run,
        tmp_path,
        first="Sediment settles slowly.",
        second="Sediment moves with the current.",
    )

    result = run.invoke(main, ["search", "sediment", "--top-k", "1"])

    assert result.exit_code == 0, result.output
    assert hits_in(result.output, "notes") == 1
    assert hits_in(result.output, "docs") == 1
    assert hits_in(result.output) == 2


def test_groups_run_in_a_fixed_order_not_by_quality(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """Ordering groups by their best hit would put the cross-collection
    comparison back in through the layout, which is what grouping removes.

    The notes hit is deliberately the stronger lexical match, so fixed order
    and quality order disagree. Without that they agree and the test passes
    for free - which is how it was written the first time, and an injection
    sorting the groups by BM25 went straight through it.
    """
    a_docs_page(corpus, "sediment", "Sediment is mentioned here once.")
    indexed_notes(
        run,
        tmp_path,
        rivers="Sediment sediment sediment sediment sediment deposition.",
    )

    result = run.invoke(main, ["search", "sediment"])

    assert result.exit_code == 0, result.output
    assert hits_in(result.output, "docs") == 1
    assert hits_in(result.output, "notes") == 1
    assert result.output.index("Docs ") < result.output.index("Notes ")


def test_a_lexical_band_is_relative_to_its_own_group(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """Each group's best lexical hit is the top level *of that group*.

    Taken across collections, a strong match in one would push every hit in
    the other down a band for no reason a reader could see. That compromise
    existed only while one column served every collection; the group heading
    says "relative to the best lexical match" now, once per group.
    Concern #231.
    """
    a_docs_page(
        corpus, "sediment", "Sediment sediment sediment sediment sediment sediment."
    )
    indexed_notes(run, tmp_path, rivers="Sediment is mentioned here once.")

    result = run.invoke(main, ["search", "sediment"])

    assert result.exit_code == 0, result.output
    notes = group_of(result.output, "notes")
    assert "relevance: very high" in notes, notes


def test_a_collection_with_no_hits_gets_no_group(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    a_docs_page(corpus, "indexing", "Nothing about rivers here.")
    indexed_notes(run, tmp_path, rivers="Sediment settles slowly.")

    result = run.invoke(main, ["search", "sediment"])

    assert result.exit_code == 0, result.output
    assert hits_in(result.output, "notes") == 1
    assert "Docs " not in result.output


def test_ranks_restart_in_each_group(corpus: Path, run: CliRunner, tmp_path: Path):
    """A rank is a position in a ranking, and there is no longer one
    ranking across collections."""
    a_docs_page(corpus, "sediment", "Sediment deposition in the delta.")
    indexed_notes(run, tmp_path, rivers="Sediment settles slowly.")

    result = run.invoke(main, ["search", "sediment"])

    assert result.exit_code == 0, result.output
    assert result.output.count("[1]") == 2


def test_the_summary_counts_each_collection(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """How much came from where is the thing a grouped report can say and a
    merged one could not."""
    a_docs_page(corpus, "sediment", "Sediment deposition in the delta.")
    indexed_notes(run, tmp_path, rivers="Sediment settles slowly.")

    result = run.invoke(main, ["search", "sediment"])

    assert result.exit_code == 0, result.output
    assert "1 in docs" in result.output
    assert "1 in notes" in result.output


def test_no_hits_is_not_a_failure(corpus: Path, run: CliRunner, tmp_path: Path):
    """Asserted on the sentence. `"no" in output` matches "notes" and "no
    dense leg", and passed while saying nothing about the empty result."""
    indexed_notes(run, tmp_path, rivers="Rivers carry sediment to the delta.")

    result = run.invoke(main, ["search", "photosynthesis chlorophyll thylakoid"])

    assert result.exit_code == 0, result.output
    assert "no matching passages" in result.output
    assert hits_in(result.output) == 0


def test_searching_an_unindexed_corpus_names_the_command_that_fixes_it(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """Documents and no index. The fixture used to give an *empty* corpus,
    where `kennis corpus index` is not the fix at all - it skips a
    collection with no documents, which is concern #242."""
    assert (
        run.invoke(
            main, ["corpus", "add", "-n", str(a_source(tmp_path, "rivers.md", "Silt."))]
        ).exit_code
        == 0
    )

    result = run.invoke(main, ["search", "sediment"])

    assert result.exit_code != 0
    assert "kennis corpus index" in result.output


def test_searching_an_empty_corpus_names_what_fills_it(corpus: Path, run: CliRunner):
    """Nothing to index, so nothing to rebuild: the command that changes
    this is the one that puts a document in."""
    result = run.invoke(main, ["search", "sediment"])

    assert result.exit_code != 0
    assert "kennis corpus add" in result.output
    assert "kennis corpus index" not in result.output


def test_a_clone_with_an_unindexed_bundle_is_told_to_index_it(
    workspace: Path, corpus: Path, run: CliRunner
):
    """The ordinary state of a fresh clone: the documents are committed and
    the index is gitignored (#248), so this is the first thing many readers
    will ever see from `kennis search`. Naming a corpus command here would
    send them away from the one thing that is actually there."""
    assert run.invoke(main, ["context", "init", "--here"]).exit_code == 0
    assert run.invoke(main, ["remember", "--context", "Four minutes."]).exit_code == 0

    result = run.invoke(main, ["search", "four minutes"])

    assert result.exit_code != 0
    assert "kennis context index" in result.output
    assert "kennis corpus" not in result.output


def test_the_refusal_names_the_nearest_scope_when_several_are_unindexed(
    workspace: Path, corpus: Path, run: CliRunner, tmp_path: Path
):
    """Two scopes with documents and no index. The refusal can name only one
    command, and it names the first in scope order - context, the nearest.
    Without a second unindexed scope this test cannot tell the first from
    the last, which is how the ordering went untested at first."""
    assert (
        run.invoke(
            main, ["corpus", "add", "-n", str(a_source(tmp_path, "rivers.md", "Silt."))]
        ).exit_code
        == 0
    )
    assert run.invoke(main, ["context", "init", "--here"]).exit_code == 0
    assert run.invoke(main, ["remember", "--context", "Four minutes."]).exit_code == 0

    result = run.invoke(main, ["search", "four minutes"])

    assert result.exit_code != 0
    assert "kennis context index" in result.output
    assert "kennis corpus index" not in result.output


def test_a_group_filter_narrows_the_search(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """The group is recorded on every chunk by the loader, so filtering on it
    needs no layout knowledge in the query layer."""
    assert (
        run.invoke(
            main,
            [
                "corpus",
                "add",
                "-n",
                "--group",
                "geology",
                str(a_source(tmp_path, "rivers.md", "Sediment reaches the delta.")),
            ],
        ).exit_code
        == 0
    )
    assert (
        run.invoke(
            main,
            [
                "corpus",
                "add",
                "-n",
                "--group",
                "botany",
                str(a_source(tmp_path, "trees.md", "Sediment around tree roots.")),
            ],
        ).exit_code
        == 0
    )
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0

    result = run.invoke(main, ["search", "sediment", "--group", "geology"])

    assert result.exit_code == 0, result.output
    assert "rivers" in result.output.lower()
    assert "trees" not in result.output.lower()


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------


def test_read_gives_the_whole_document_by_default(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """The command's subject is a document, not a hit. Concern #187."""
    indexed_notes(run, tmp_path, rivers="Rivers carry sediment to the delta. " * 40)
    stored = next((corpus / "notes").rglob("*.md"))
    handle = identifier_of(stored)

    result = run.invoke(main, ["read", handle])

    assert result.exit_code == 0, result.output
    body = stored.read_text(encoding="utf-8").split("---\n", 2)[2].strip()
    # Character for character: a document is a payload, and rewrapping it
    # would put line breaks inside fenced code and inside tables.
    assert result.stdout.strip() == body


def test_a_whole_document_read_puts_nothing_but_markdown_on_stdout(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """`kennis read x > x.md` has to produce a usable file, which is the same
    rule `config show` follows."""
    indexed_notes(run, tmp_path, rivers="Rivers carry sediment to the delta.")
    handle = identifier_of(next((corpus / "notes").rglob("*.md")))

    result = run.invoke(main, ["read", handle])

    assert result.exit_code == 0, result.output
    assert "Read" not in result.stdout
    assert handle not in result.stdout
    # The provenance is not lost, only moved off the payload.
    assert handle in result.stderr


def test_a_whole_document_read_omits_the_frontmatter_unless_asked(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    indexed_notes(run, tmp_path, rivers="Rivers carry sediment to the delta.")
    handle = identifier_of(next((corpus / "notes").rglob("*.md")))

    without = run.invoke(main, ["read", handle])
    with_it = run.invoke(main, ["read", handle, "--frontmatter"])

    assert "owner: user" not in without.stdout
    assert "owner: user" in with_it.stdout


def test_a_document_is_readable_by_title_and_by_filename(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """Brian's own words: by title name, filename, file id, or whatever is
    relevant and appropriate to use."""
    indexed_notes(run, tmp_path, rivers="Rivers carry sediment to the delta.")
    stored = next((corpus / "notes").rglob("*.md"))

    for handle in ("rivers", stored.name, stored.stem):
        result = run.invoke(main, ["read", handle])
        assert result.exit_code == 0, (handle, result.output)
        assert "sediment" in result.stdout.lower(), handle


def test_a_document_that_was_never_indexed_is_still_readable(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """The whole-document read goes to the file, so an index it does not need
    is not a reason to refuse. The old read could only reach the index, which
    made an unindexed document unreadable."""
    source = a_source(tmp_path, "rivers.md", "Rivers carry sediment.")
    assert run.invoke(main, ["corpus", "add", "-n", str(source)]).exit_code == 0

    result = run.invoke(main, ["read", "rivers"])

    assert result.exit_code == 0, result.output
    assert "sediment" in result.stdout.lower()


def test_a_chunk_read_shows_the_text_around_it(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    indexed_notes(run, tmp_path, rivers="Rivers carry sediment to the delta.")
    handle = identifier_of(next((corpus / "notes").rglob("*.md")))

    result = run.invoke(main, ["read", handle, "--chunks", "0"])

    assert result.exit_code == 0, result.output
    assert "sediment" in result.stdout.lower()
    assert handle in result.stderr


def test_both_kinds_of_read_split_the_streams_the_same_way(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """One rule for the command: **stdout is the text, stderr is the
    provenance**, whether the text is a whole document or one passage.

    A contract that changed with a flag meant `kennis read x | y` and
    `kennis read x --chunk 3 | y` fed `y` different things - the second with
    a report line on the front of it.
    """
    indexed_notes(run, tmp_path, rivers="Rivers carry sediment to the delta.")
    handle = identifier_of(next((corpus / "notes").rglob("*.md")))

    whole = run.invoke(main, ["read", handle])
    passage = run.invoke(main, ["read", handle, "--chunks", "0"])

    for result in (whole, passage):
        assert result.exit_code == 0, result.output
        assert "Read" not in result.stdout
        assert handle not in result.stdout
        assert handle in result.stderr


def test_an_option_that_does_not_apply_is_refused_rather_than_ignored(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """`--frontmatter` prepends a document's YAML and means nothing for a
    span of its text. Accepting it silently is how a person concludes the
    command did not work."""
    indexed_notes(run, tmp_path, rivers="Rivers carry sediment to the delta.")
    handle = identifier_of(next((corpus / "notes").rglob("*.md")))

    result = run.invoke(main, ["read", handle, "--chunks", "0", "--frontmatter"])

    assert result.exit_code != 0
    assert "--chunks" in result.output


def test_a_range_reads_exactly_the_chunks_it_names(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    indexed_notes(run, tmp_path, long="word " * 900)
    handle = identifier_of(next((corpus / "notes").rglob("*.md")))

    result = run.invoke(main, ["read", handle, "--chunks", "0:2"])

    assert result.exit_code == 0, result.output
    assert "chunks 0 to 1" in result.stderr


def test_a_range_kennis_cannot_read_names_the_forms_that_work(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    indexed_notes(run, tmp_path, rivers="Rivers carry sediment to the delta.")
    handle = identifier_of(next((corpus / "notes").rglob("*.md")))

    result = run.invoke(main, ["read", handle, "--chunks", "0:3:2"])

    assert result.exit_code != 0
    assert "contiguous" in result.output


def test_a_bracketed_handle_is_still_a_handle(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """The range lives in an option value, so a document whose own name has
    brackets in it resolves as it always did. This is the ambiguity the
    proposed `read x[0:3]` would have had to legislate around. Concern #205.
    """
    source = a_source(tmp_path, "Results [preliminary].md", "Rivers carry sediment.")
    assert run.invoke(main, ["corpus", "add", "-n", str(source)]).exit_code == 0

    result = run.invoke(main, ["read", "Results [preliminary]"])

    assert result.exit_code == 0, result.output
    assert "sediment" in result.stdout.lower()


def test_the_search_hint_runs_as_printed(corpus: Path, run: CliRunner, tmp_path: Path):
    """Rule 4.4, and the reason `--chunks` can replace three options: the
    arithmetic they saved is arithmetic the hint does.

    The hit this corpus returns is at chunk 0, which is the case that would
    bite - `n - 1` is `-1` there, and `-1` is the *last* chunk.
    """
    indexed_notes(run, tmp_path, rivers="Rivers carry sediment to the delta.")

    found = run.invoke(main, ["search", "sediment"])

    # Between the backticks, which is exactly what `display.command` marks
    # as the runnable part - the note after it is prose, not arguments.
    invocation = re.search(r"`(kennis read [^`]+)`", found.output)
    assert invocation is not None, found.output
    replayed = run.invoke(main, shlex.split(invocation.group(1))[1:])

    assert "--chunks 0:" in invocation.group(1), invocation.group(1)
    assert replayed.exit_code == 0, replayed.output
    assert "sediment" in replayed.stdout.lower()


def test_a_chunk_read_needs_an_index_and_says_so(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """A span is stitched out of the index, so this one genuinely cannot be
    answered without it - unlike the whole-document read above."""
    source = a_source(tmp_path, "rivers.md", "Rivers carry sediment.")
    assert run.invoke(main, ["corpus", "add", "-n", str(source)]).exit_code == 0

    result = run.invoke(main, ["read", "rivers", "--chunks", "0"])

    assert result.exit_code != 0
    assert "kennis corpus index" in result.output


def test_reading_a_document_that_is_not_there_says_which_command_to_run(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    indexed_notes(run, tmp_path, rivers="Rivers carry sediment to the delta.")

    result = run.invoke(main, ["read", "nosuchdoc"])

    assert result.exit_code != 0
    assert "kennis corpus list" in result.output


# ---------------------------------------------------------------------------
# The context bundle as a fourth collection
#
# Not a second axis: the plan settles this by reading boepie. `--context` as
# its own flag would make two questions out of one - which scopes to search -
# so `context` is a value of the selector the corpus collections already use.
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.chdir(root)
    monkeypatch.delenv("KENNIS_CONTEXT_DIR", raising=False)
    return root


def indexed_context(run: CliRunner, **notes: str) -> None:
    """A bundle holding one note per keyword, then indexed."""
    assert run.invoke(main, ["context", "init", "--here"]).exit_code == 0
    for title, body in notes.items():
        assert (
            run.invoke(
                main, ["remember", "--context", "--title", title, body]
            ).exit_code
            == 0
        )
    assert run.invoke(main, ["context", "index"]).exit_code == 0


def test_context_is_searched_by_default(
    workspace: Path, corpus: Path, run: CliRunner, tmp_path: Path
):
    indexed_notes(run, tmp_path, calibration="Calibration solves for gains.")
    indexed_context(run, Chunking="This project calibrates in four-minute chunks.")

    result = run.invoke(main, ["search", "calibration chunks"])

    assert result.exit_code == 0, result.output
    assert hits_in(result.output, "context") >= 1
    assert hits_in(result.output, "notes") >= 1


def test_context_can_be_searched_alone(workspace: Path, run: CliRunner):
    """And with no corpus at all: a bundle belongs to a project, and a
    machine that has never run `corpus init` must still search one."""
    indexed_context(run, Chunking="This project calibrates in four-minute chunks.")

    result = run.invoke(
        main, ["search", "four-minute chunks", "--collection", "context"]
    )

    assert result.exit_code == 0, result.output
    assert hits_in(result.output, "context") >= 1


def test_the_selector_takes_a_comma_separated_list(
    workspace: Path, corpus: Path, run: CliRunner, tmp_path: Path
):
    indexed_notes(run, tmp_path, calibration="Calibration solves for gains.")
    indexed_context(run, Chunking="Calibration runs in four-minute chunks.")

    result = run.invoke(
        main, ["search", "calibration", "--collection", "notes,context"]
    )

    assert result.exit_code == 0, result.output
    assert hits_in(result.output, "notes") >= 1
    assert hits_in(result.output, "context") >= 1


def test_an_unknown_collection_names_the_ones_that_exist(
    workspace: Path, corpus: Path, run: CliRunner
):
    result = run.invoke(main, ["search", "anything", "--collection", "notes,pack"])

    assert result.exit_code != 0
    assert "pack" in result.output
    assert "context" in result.output


def test_a_context_hit_is_addressed_by_path_and_not_by_an_identifier(
    workspace: Path, run: CliRunner
):
    """There is no `kennis read` for a bundle file. It is a file in the
    user's own project, so its handle is where it is."""
    indexed_context(run, Chunking="This project calibrates in four-minute chunks.")

    result = run.invoke(
        main, ["search", "four-minute chunks", "--collection", "context"]
    )

    group = group_of(result.output, "context")
    assert "path=.context/Chunking.md" in group
    assert "id=" not in group


def test_a_context_only_report_offers_no_read_command(workspace: Path, run: CliRunner):
    """Rule 4.4: `kennis read` resolves a handle against the corpus, so a
    hint built from a bundle path would print a command that cannot run."""
    indexed_context(run, Chunking="This project calibrates in four-minute chunks.")

    result = run.invoke(
        main, ["search", "four-minute chunks", "--collection", "context"]
    )

    assert "kennis read" not in result.output


def test_a_mixed_report_anchors_the_read_hint_on_a_corpus_hit(
    workspace: Path, corpus: Path, run: CliRunner, tmp_path: Path
):
    """Context is printed first, so the hint cannot simply take the first
    hit of the report - it has to take the first one `read` can resolve."""
    indexed_notes(run, tmp_path, calibration="Calibration solves for gains.")
    indexed_context(run, Chunking="Calibration runs in four-minute chunks.")

    result = run.invoke(main, ["search", "calibration"])

    hint = [line for line in result.output.splitlines() if "kennis read" in line]
    assert len(hint) == 1
    # A corpus handle is an opaque identifier kennis minted; a bundle
    # document is addressed by its filename. Asserting the absence of
    # `.context/` would prove nothing - the hint is built from
    # `chunk.document_id`, which for a context hit is the bundle-relative
    # path with no prefix, so the string would be absent either way.
    assert ".md" not in hint[0]


def test_the_read_hint_runs_as_printed_in_a_mixed_report(
    workspace: Path, corpus: Path, run: CliRunner, tmp_path: Path
):
    indexed_notes(run, tmp_path, calibration="Calibration solves for gains.")
    indexed_context(run, Chunking="Calibration runs in four-minute chunks.")
    found = run.invoke(main, ["search", "calibration"])

    invocation = re.search(r"`(kennis read [^`]+)`", found.output)
    assert invocation is not None, found.output
    replayed = run.invoke(main, shlex.split(invocation.group(1))[1:])

    assert replayed.exit_code == 0, replayed.output


def test_context_comes_first_because_it_is_the_nearest_scope(
    workspace: Path, corpus: Path, run: CliRunner, tmp_path: Path
):
    indexed_notes(run, tmp_path, calibration="Calibration solves for gains.")
    indexed_context(run, Chunking="Calibration runs in four-minute chunks.")

    result = run.invoke(main, ["search", "calibration"])

    assert result.output.index("Context ") < result.output.index("Notes ")


def test_no_bundle_is_not_an_error_in_a_sweep(
    workspace: Path, corpus: Path, run: CliRunner, tmp_path: Path
):
    """The same asymmetry a missing index has: a scope you never mentioned
    is not part of the answer, and one you named is what you asked for."""
    indexed_notes(run, tmp_path, calibration="Calibration solves for gains.")

    result = run.invoke(main, ["search", "calibration"])

    assert result.exit_code == 0, result.output
    assert hits_in(result.output, "notes") >= 1


def test_no_bundle_is_an_error_when_context_was_asked_for(
    workspace: Path, corpus: Path, run: CliRunner
):
    result = run.invoke(main, ["search", "anything", "--collection", "context"])

    assert result.exit_code != 0
    assert "kennis context init" in result.output


def test_an_unindexed_bundle_names_the_command_that_indexes_it(
    workspace: Path, corpus: Path, run: CliRunner, tmp_path: Path
):
    """`kennis corpus index` does not build a bundle's index, so a report
    that skipped context must not print it as the way to fix that."""
    indexed_notes(run, tmp_path, calibration="Calibration solves for gains.")
    assert run.invoke(main, ["context", "init", "--here"]).exit_code == 0
    assert (
        run.invoke(main, ["remember", "--context", "Four-minute chunks."]).exit_code
        == 0
    )

    result = run.invoke(main, ["search", "calibration"])

    assert result.exit_code == 0, result.output
    assert "kennis context index" in result.output


def test_a_context_group_says_its_band_is_relative(workspace: Path, run: CliRunner):
    """A bundle index is lexical by design, not by a missing backend, so the
    band is a fraction of this query's own best hit and the heading says so."""
    indexed_context(run, Chunking="This project calibrates in four-minute chunks.")

    result = run.invoke(
        main, ["search", "four-minute chunks", "--collection", "context"]
    )

    assert "relative to the best lexical match" in result.output


def test_a_context_search_does_not_report_a_missing_dense_leg(
    workspace: Path, run: CliRunner
):
    """That note exists for a corpus collection part-way through a model
    change. A bundle is lexical on purpose - design section 13 - so saying
    it 'ran as a lexical search' reads as a degradation that did not
    happen."""
    indexed_context(run, Chunking="This project calibrates in four-minute chunks.")

    result = run.invoke(main, ["search", "four-minute chunks"])

    assert result.exit_code == 0, result.output
    assert hits_in(result.output, "context") >= 1
    assert "no dense leg" not in result.output


def test_the_group_filter_reaches_a_bundle_subdirectory(
    workspace: Path, run: CliRunner
):
    assert run.invoke(main, ["context", "init", "--here"]).exit_code == 0
    for group, body in (("decisions", "Calibration in chunks."), ("", "Calibration.")):
        command = ["remember", "--context", body]
        if group:
            command += ["--group", group]
        assert run.invoke(main, command).exit_code == 0
    assert run.invoke(main, ["context", "index"]).exit_code == 0

    result = run.invoke(
        main,
        ["search", "calibration", "--collection", "context", "--group", "decisions"],
    )

    assert result.exit_code == 0, result.output
    assert hits_in(result.output, "context") == 1


def test_read_explains_why_it_does_not_take_a_context_handle(
    workspace: Path, corpus: Path, run: CliRunner
):
    """`invalid choice: context` is accurate and says nothing about why, and
    why is a decision worth one sentence: the file is the user's own."""
    result = run.invoke(main, ["read", "anything", "--collection", "context"])

    assert result.exit_code != 0
    assert "open it with your own tools" in result.output


def test_a_sweep_works_on_a_machine_with_no_corpus(workspace: Path, run: CliRunner):
    """A bundle belongs to a project and a corpus is machine-global. If the
    default sweep required a corpus, `kennis search` inside a project would
    be unusable until an unrelated global store had been created."""
    indexed_context(run, Chunking="This project calibrates in four-minute chunks.")

    result = run.invoke(main, ["search", "four-minute chunks"])

    assert result.exit_code == 0, result.output
    assert hits_in(result.output, "context") >= 1


def test_a_named_corpus_collection_still_requires_a_corpus(
    workspace: Path, run: CliRunner
):
    result = run.invoke(main, ["search", "anything", "--collection", "notes"])

    assert result.exit_code != 0
    assert "kennis corpus init" in result.output


def test_nothing_to_search_at_all_names_what_is_missing(
    workspace: Path, run: CliRunner
):
    """`kennis corpus index` is the fix for an unindexed corpus and fails on
    a machine that has none, so printing it here would hand the reader a
    second error instead of an answer."""
    result = run.invoke(main, ["search", "anything"])

    assert result.exit_code != 0
    assert "kennis corpus init" in result.output
    assert "kennis corpus index" not in result.output


def test_a_sweep_with_no_corpus_says_nothing_about_the_corpus(
    workspace: Path, run: CliRunner
):
    """`kennis corpus index` fails on a machine with no corpus, so printing
    it as the fix hands the reader a second error. Nothing is printed at
    all: nobody believes a store they have never created was searched, and
    a line about it above every answer is noise."""
    indexed_context(run, Chunking="This project calibrates in four-minute chunks.")

    result = run.invoke(main, ["search", "four-minute chunks"])

    assert result.exit_code == 0, result.output
    assert "kennis corpus index" not in result.output
    assert "not searched" not in result.output


def test_a_sweep_outside_a_project_says_nothing_about_a_bundle(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """Most searches are run outside any project."""
    indexed_notes(run, tmp_path, calibration="Calibration solves for gains.")

    result = run.invoke(main, ["search", "calibration"])

    assert result.exit_code == 0, result.output
    # The group heading, not the bare word: the closing hint ends "to read
    # one in context", which would make a substring check pass for the
    # wrong reason.
    assert "Context " not in result.output
    # The corpus's other two collections are genuinely unindexed and are
    # reported, which is the rule working; what must not appear in that line
    # is context, because there is no bundle here to have an index.
    assert "kennis context" not in result.output


def test_an_unindexed_corpus_collection_is_still_reported(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """The other half of the rule: a store that exists and has not been
    indexed is news, because the reader has one and may believe it was
    searched."""
    indexed_notes(run, tmp_path, calibration="Calibration solves for gains.")
    a_docs_page(corpus, "quickstart", "Arrays are contiguous.")

    result = run.invoke(main, ["search", "calibration"])

    assert "not searched" in result.output
    assert "kennis corpus index" in result.output


def test_an_empty_corpus_collection_is_not_reported_as_unindexed(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """`kennis corpus index` skips a collection with no documents, so naming
    it as the fix would print a command that runs, changes nothing, and
    leaves the identical warning on the next search. A fresh corpus has two
    such collections, so this is what every search on one looks like."""
    indexed_notes(run, tmp_path, calibration="Calibration solves for gains.")

    result = run.invoke(main, ["search", "calibration"])

    assert result.exit_code == 0, result.output
    assert "not searched" not in result.output


def test_a_lexical_corpus_index_still_reports_the_downgrade(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """`retrieval.corpus_method` defaults to hybrid and this corpus is
    indexed with no backend, so the search ran as lexical and says so. The
    context scope has its own setting now; without this the two could be
    swapped and every test would still pass."""
    indexed_notes(run, tmp_path, calibration="Calibration solves for gains.")

    result = run.invoke(main, ["search", "calibration", "--collection", "notes"])

    assert result.exit_code == 0, result.output
    assert "the notes index has no dense leg" in result.output


def test_the_default_hit_count_applies_to_each_scope(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """`-k` is per scope, so the default is what one group can print, not
    what the report can. It was 5 while one merged list was truncated
    globally; grouping made a three-collection sweep able to print fifteen
    hits, and 3 keeps the worst case near what the merged list used to show.
    Concern #232."""
    indexed_notes(
        run,
        tmp_path,
        **{f"sediment{index}": "Rivers carry sediment." for index in range(5)},
    )

    result = run.invoke(main, ["search", "sediment"])

    assert result.exit_code == 0, result.output
    assert hits_in(result.output, "notes") == 3


def test_the_default_can_still_be_raised(corpus: Path, run: CliRunner, tmp_path: Path):
    indexed_notes(
        run,
        tmp_path,
        **{f"sediment{index}": "Rivers carry sediment." for index in range(5)},
    )

    result = run.invoke(main, ["search", "sediment", "-k", "5"])

    assert hits_in(result.output, "notes") == 5
