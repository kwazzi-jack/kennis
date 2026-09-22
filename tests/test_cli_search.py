"""Searching the index, and reading what surrounds a hit.

The last thing v0.1 needs to be usable. These are the command-line half; the
retrieval itself is covered by the milestone 3 suite.
"""

from __future__ import annotations

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


def hits_in(output: str, collection: str = "notes") -> int:
    """How many result lines the report printed.

    Counted by the bracketed collection label, which appears on a hit line
    and nowhere else - the warnings name a collection in prose, so a bare
    substring search finds them too and has passed for the wrong reason.
    """
    return output.count(f"[{collection}]")


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


def test_each_hit_names_the_collection_it_came_from(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """A merged list has to stay readable as the several lists it is.

    Asserted on the bracketed label rather than on the bare word, which also
    appears in the warning about the lexical fallback.
    """
    indexed_notes(run, tmp_path, rivers="Rivers carry sediment to the delta.")

    result = run.invoke(main, ["search", "sediment"])

    assert result.exit_code == 0, result.output
    assert hits_in(result.output) == 1


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


def test_a_merged_result_is_bounded_by_top_k(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """Each collection is asked for `top_k` of its own, so the merged list is
    as long as the number of collections searched until it is cut. With one
    collection indexed the final bound is unobservable, which is why this
    test indexes two."""
    a_docs_page(corpus, "indexing", "Sediment is not an indexing concept.")
    indexed_notes(
        run,
        tmp_path,
        first="Sediment settles slowly.",
        second="Sediment moves with the current.",
    )

    result = run.invoke(main, ["search", "sediment", "--top-k", "2"])

    assert result.exit_code == 0, result.output
    assert hits_in(result.output, "notes") + hits_in(result.output, "docs") == 2


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


def test_read_shows_the_text_around_a_chunk(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    indexed_notes(run, tmp_path, rivers="Rivers carry sediment to the delta.")
    handle = identifier_of(next((corpus / "notes").rglob("*.md")))

    result = run.invoke(main, ["read", handle])

    assert result.exit_code == 0, result.output
    assert "sediment" in result.output.lower()


def test_read_names_the_document_and_where_it_came_from(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    indexed_notes(run, tmp_path, rivers="Rivers carry sediment to the delta.")
    handle = identifier_of(next((corpus / "notes").rglob("*.md")))

    result = run.invoke(main, ["read", handle])

    assert result.exit_code == 0, result.output
    assert handle in result.output
    assert "notes/" in result.output.replace("\\", "/")


def test_reading_a_document_that_is_not_indexed_says_which_command_to_run(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    indexed_notes(run, tmp_path, rivers="Rivers carry sediment to the delta.")

    result = run.invoke(main, ["read", "nosuchdoc"])

    assert result.exit_code != 0
    assert "index" in result.output


def test_read_refuses_when_nothing_is_indexed_at_all(corpus: Path, run: CliRunner):
    result = run.invoke(main, ["read", "anything"])

    assert result.exit_code != 0
    assert "kennis corpus index" in result.output
