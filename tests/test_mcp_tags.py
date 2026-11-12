"""Tags for an agent (#625, sketch 2026-11-06-tags, part t4).

The `tag` tool writes, as `remember` does: it takes what a hit gives - a
`document_id` or a context hit's `path`, with its `chunk` - as `cite` does,
never a link the agent composed, and a batch is all or nothing. The
`search` takes `tags`, and `list_corpus` names the tags in use.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kennis.engine.context.bundle import init_bundle
from kennis.engine.errors import KennisError
from kennis.engine.tags import Anchor, read_tags
from kennis.mcp.instructions import instructions_for
from kennis.mcp.tools.cite import CiteRequest
from kennis.mcp.tools.corpus import list_corpus
from kennis.mcp.tools.search import search
from kennis.mcp.tools.tags import tag
from test_cli_tags import PAPER_ID, SOLVING, chunk_holding, indexed_paper, run


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = indexed_paper(tmp_path, monkeypatch)
    source = tmp_path / "drift.md"
    source.write_text("# Drift\n\nThe gains drift between scans.\n", encoding="utf-8")
    run("corpus", "add", "-n", str(source))
    run("corpus", "index")
    return root


@pytest.fixture
def project(corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "pipelines"
    (root / ".git").mkdir(parents=True)
    init_bundle(root)
    for name in ("ours", "theirs"):
        (root / ".context" / f"{name}.md").write_text(
            f"---\ntitle: {name}\n---\nWe solve the gains per scan.\n",
            encoding="utf-8",
        )
    monkeypatch.chdir(root)
    run("context", "index")
    return root / ".context"


# ---------------------------------------------------------------------------
# Tagging


def test_the_tool_tags_a_passage_as_a_hit_gives_it(corpus: Path):
    chunk = chunk_holding(corpus, SOLVING)

    said = tag([CiteRequest(document_id=PAPER_ID, chunk=chunk)], ["Calibration"])

    (anchor,) = read_tags(corpus / "tags.yml")["calibration"]
    assert (anchor.document, anchor.chunk) == (PAPER_ID, chunk)
    assert said.startswith("[1] Revisiting the radio interferometer")
    assert "tagged: calibration" in said


def test_the_tool_tags_a_whole_document(corpus: Path):
    tag([CiteRequest(document_id=PAPER_ID)], ["to-read"])

    assert read_tags(corpus / "tags.yml") == {"to-read": (Anchor(PAPER_ID),)}


def test_the_tool_tags_a_context_hit_by_its_path(project: Path, corpus: Path):
    tag([CiteRequest(path=".context/ours.md", chunk=0)], ["mine"])

    assert read_tags(project / "tags.yml")["mine"][0].document == "ours.md"
    assert not (corpus / "tags.yml").exists()


def test_the_tool_removes_a_tag(corpus: Path):
    tag([CiteRequest(document_id=PAPER_ID)], ["to-read"])

    said = tag([CiteRequest(document_id=PAPER_ID)], ["to-read"], remove=True)

    assert read_tags(corpus / "tags.yml") == {}
    assert "untagged" in said


def test_tagging_again_says_so(corpus: Path):
    tag([CiteRequest(document_id=PAPER_ID)], ["to-read"])

    said = tag([CiteRequest(document_id=PAPER_ID)], ["to-read"])

    assert "already" in said


def test_one_refused_request_writes_none_and_says_which(corpus: Path):
    said = tag(
        [
            CiteRequest(document_id=PAPER_ID),
            CiteRequest(document_id=PAPER_ID, chunk=999),
        ],
        ["calibration"],
    )

    assert not (corpus / "tags.yml").exists()
    assert "[2]" in said
    assert "[1]" not in said
    assert "Nothing was tagged" in said


@pytest.mark.parametrize(
    ("requests", "names", "refusal"),
    [
        ([], ["a"], "no requests"),
        ([CiteRequest(document_id=PAPER_ID)], [], "no tags"),
        (
            [CiteRequest(document_id=PAPER_ID, path=".context/ours.md")],
            ["a"],
            "exactly one",
        ),
        ([CiteRequest(document_id=PAPER_ID)], ["phase calibration"], "not a tag"),
        ([CiteRequest(document_id=PAPER_ID)] * 13, ["a"], "at most"),
    ],
)
def test_the_tool_refuses_what_it_cannot_tag_and_writes_nothing(
    corpus: Path, requests: list[CiteRequest], names: list[str], refusal: str
):
    said = tag(requests, names)

    assert refusal in said
    assert not (corpus / "tags.yml").exists()


# ---------------------------------------------------------------------------
# Searching and listing


def test_a_search_tool_is_kept_to_its_tags(corpus: Path):
    tag([CiteRequest(document_id=PAPER_ID)], ["calibration"])

    assert "Drift" in search("gains", ["notes"])
    assert search("gains", ["notes"], tags=["calibration"]) == "no matching passages"
    assert PAPER_ID in search("gains", ["literature"], tags=["calibration"])


def test_a_context_search_is_kept_to_the_project_s_tags(project: Path):
    tag([CiteRequest(path=".context/ours.md")], ["mine"])

    said = search("gains", ["context"], tags=["mine"])

    assert "ours.md" in said
    assert "theirs.md" not in said


def test_a_tag_nothing_carries_is_refused_naming_the_listing(corpus: Path):
    with pytest.raises(KennisError) as refused:
        search("gains", ["literature"], tags=["nowhere"])

    assert refused.value.resolution == "kennis tags"


def test_list_corpus_names_the_tags_in_use(corpus: Path):
    tag([CiteRequest(document_id=PAPER_ID)], ["calibration", "to-read"])

    said = list_corpus()

    assert "tags: calibration (1), to-read (1)" in said


def test_the_instructions_name_tag_as_a_tool_that_writes():
    block = instructions_for(())

    assert "`remember` and `tag` are the only tools here that change anything" in (
        " ".join(block.split())
    )


def test_a_path_the_server_cannot_place_writes_none_of_the_batch(corpus: Path):
    """Refused before the service is asked - the path is in no `.context` -
    and still nothing of the batch is written."""
    said = tag(
        [CiteRequest(document_id=PAPER_ID), CiteRequest(path="notes/x.md")],
        ["calibration"],
    )

    assert not (corpus / "tags.yml").exists()
    assert said.startswith("[2] ")
    assert "Nothing was tagged" in said
