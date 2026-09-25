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

    Counted by `id=`, which is on every hit's handle line whatever
    `--scores` is set to, and nowhere else. The old counter used the
    bracketed collection label, which the grouped report prints once per
    group rather than once per hit.
    """
    text = output if collection is None else group_of(output, collection)
    return text.count("id=")


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
    the run would make every search depend on having indexed all three."""
    indexed_notes(run, tmp_path, rivers="Rivers carry sediment to the delta.")

    result = run.invoke(main, ["search", "sediment"])

    assert result.exit_code == 0, result.output
    assert hits_in(result.output) == 1
    assert "no index yet" in result.output
    assert "literature" in result.output and "docs" in result.output


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
    corpus: Path, run: CliRunner
):
    result = run.invoke(main, ["search", "sediment"])

    assert result.exit_code != 0
    assert "kennis corpus index" in result.output


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
