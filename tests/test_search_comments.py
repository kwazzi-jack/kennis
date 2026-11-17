"""The comments on annotations, searched as a scope of their own (#50, unit
3a, sketch 2026-11-17-search-comments).

A comment is the reader's words, so it is a group of its own and never part
of a document's ranking. Its hit names the annotated document, quotes the
selected words and leads to them; an annotation with tags and no comment is
not a hit, because `--tag` already finds those.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup, Tag
from click.testing import CliRunner
from fastapi.testclient import TestClient

from annotating import write_store
from kennis.cli.__main__ import main
from kennis.context import existing_corpus
from kennis.engine.annotations import (
    Annotation,
    AnnotationStore,
    comments_ranked,
    selector_of,
)
from kennis.engine.context.bundle import init_bundle
from kennis.engine.context.index import index_bundle
from kennis.engine.context.notes import remember_in_bundle
from kennis.engine.corpus.collection import Collection
from kennis.engine.rag.models import Filter
from kennis.engine.settings import Settings
from kennis.gui.app import build_app
from kennis.links import context_link, link_to
from kennis.mcp.tools.search import search
from kennis.retrieval import sweep

CREATED = "2026-11-17T10:00:00+00:00"
DRIFT = "The gains drift slowly after sunset, which the solver must track."
FLAGS = "Short baselines carry most of the interference on this array."


def annotation(
    identifier: str,
    document: str,
    *,
    body: str | None = None,
    words: str | None = None,
    tags: tuple[str, ...] = (),
    comment: str | None = None,
) -> Annotation:
    """An annotation of `words` in `body`, or of the whole document."""
    selector = None
    if body is not None and words is not None:
        start = body.index(words)
        selector = selector_of(body, start, start + len(words))
    return Annotation(
        id=identifier,
        document=document,
        selector=selector,
        tags=tuple(sorted(tags)),
        comment=comment,
        created=CREATED,
    )


def run(*arguments: str) -> str:
    answered = CliRunner().invoke(main, list(arguments))
    assert answered.exit_code == 0, answered.output
    return answered.output


# ---------------------------------------------------------------------------
# Ranking, by hand


def commented(*comments: str | None) -> list[Annotation]:
    return [
        annotation(f"{number:08x}", "doc", comment=comment)
        for number, comment in enumerate(comments, start=1)
    ]


def test_the_comment_sharing_the_words_ranks_first():
    found = comments_ranked(
        commented("flagging on short baselines", "the gains drift at sunset"),
        "gains drift",
        5,
    )

    assert [position for position, _ in found] == [1]


def test_an_annotation_without_a_comment_is_never_a_candidate():
    found = comments_ranked(commented(None, "gains", None), "gains", 5)

    assert [position for position, _ in found] == [1]


def test_one_comment_alone_is_found():
    """bm25's inverse document frequency over one document is the
    degenerate case; the comment must still score."""
    ((position, score),) = comments_ranked(commented("gains drift"), "gains", 5)

    assert position == 0
    assert score > 0


def test_stopwords_alone_find_nothing():
    assert comments_ranked(commented("the gains drift"), "the and of", 5) == []
    assert comments_ranked(commented("the of and"), "gains", 5) == []
    assert comments_ranked(commented(), "gains", 5) == []


# ---------------------------------------------------------------------------
# A corpus with comments


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Two notes, `drift` in group `physics` and `flags` in none, indexed."""
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    run("corpus", "init")
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "drift.md").write_text(f"# Drift\n\n{DRIFT}\n", encoding="utf-8")
    (sources / "flags.md").write_text(f"# Flags\n\n{FLAGS}\n", encoding="utf-8")
    run("corpus", "add", "-n", "--group", "physics", str(sources / "drift.md"))
    run("corpus", "add", "-n", str(sources / "flags.md"))
    run("corpus", "index")
    return existing_corpus().corpus_root


def note(root: Path, title: str) -> tuple[str, str]:
    """A note's identifier and body."""
    (document,) = [
        one
        for one in Collection(root=root, name="notes").contents().documents
        if one.frontmatter.title.lower() == title
    ]
    return document.id, document.body


@pytest.fixture
def comments(corpus: Path) -> dict[str, Annotation]:
    """On `drift`: a selection with a comment about the solver, tagged
    `calibration`, and a selection with tags alone. On `flags`: the whole
    document, commented about interference."""
    drift, drift_body = note(corpus, "drift")
    flags, _ = note(corpus, "flags")
    made = {
        "solver": annotation(
            "0000000a",
            drift,
            body=drift_body,
            words="gains drift slowly",
            tags=("calibration",),
            comment="Check whether the solver interval follows this.",
        ),
        "tagged": annotation(
            "0000000b",
            drift,
            body=drift_body,
            words="after sunset",
            tags=("solver",),
        ),
        "flags": annotation(
            "0000000c", flags, comment="Interference: compare with the RFI mask."
        ),
    }
    write_store(corpus, AnnotationStore(annotations=tuple(made.values())))
    return made


def found_ids(
    question: str,
    *,
    tags: tuple[str, ...] = (),
    filters: list[Filter] | None = None,
) -> list[str]:
    swept = sweep(
        question,
        scopes=["annotations"],
        named=True,
        bundle=None,
        tags=tags,
        filters=filters,
    )
    return [
        hit.annotation.id
        for hit in swept.groups.get("annotations", [])
        if hit.annotation is not None
    ]


def test_a_comment_is_found_by_its_words(comments: dict[str, Annotation]):
    assert found_ids("solver interval") == ["0000000a"]
    assert found_ids("interference mask") == ["0000000c"]


def test_tags_alone_are_not_a_comment(comments: dict[str, Annotation]):
    """The tag-only annotation carries `solver` as a tag; the question
    `solver` finds the comment that says it, not the tag."""
    assert found_ids("solver") == ["0000000a"]


def test_a_comment_does_not_change_the_documents_search(
    comments: dict[str, Annotation],
):
    swept = sweep("interval", scopes=["notes"], named=True, bundle=None)

    assert swept.groups == {}


def test_tags_keep_only_the_comments_carrying_them(comments: dict[str, Annotation]):
    assert found_ids("solver interference", tags=("calibration",)) == ["0000000a"]


def test_a_group_keeps_only_comments_on_its_documents(
    comments: dict[str, Annotation],
):
    physics = [Filter(field="group", op="glob", value="physics")]

    assert found_ids("solver interference", filters=physics) == ["0000000a"]
    assert sorted(found_ids("solver interference")) == ["0000000a", "0000000c"]


def test_no_store_named_is_searched_and_finds_nothing(corpus: Path):
    """Not "the corpus is empty", which a corpus with no comment yet is
    not."""
    swept = sweep("gains", scopes=["annotations"], named=True, bundle=None)

    assert swept.groups == {}
    assert swept.searched == ("annotations",)


def test_no_store_is_not_searched_by_default(corpus: Path):
    swept = sweep("gains", scopes=None, named=False, bundle=None)

    assert "annotations" not in swept.searched


def test_a_default_search_covers_the_comments(comments: dict[str, Annotation]):
    swept = sweep("interval", scopes=None, named=False, bundle=None)

    assert list(swept.groups) == ["annotations"]
    assert swept.left_out == ()


def test_a_meaning_search_says_the_comments_were_matched_by_keywords(
    comments: dict[str, Annotation],
):
    swept = sweep(
        "interval", scopes=["annotations"], named=True, bundle=None, mode="hybrid"
    )

    assert swept.degraded == ("annotations",)
    assert (
        sweep("interval", scopes=["annotations"], named=True, bundle=None).degraded
        == ()
    )


# ---------------------------------------------------------------------------
# What a hit says, written by hand


def test_kennis_search_quotes_the_selection_and_gives_the_comment(
    corpus: Path, comments: dict[str, Annotation]
):
    drift, _ = note(corpus, "drift")

    said = run("search", "solver interval", "--collection", "annotations")

    lines = [line.strip() for line in said.splitlines() if line.strip()]
    assert "[1] drift" in lines
    handle = next(line for line in lines if "annotation=0000000a" in line)
    assert handle.endswith(f"id={drift} chunk=0 annotation=0000000a")
    assert link_to(drift, 0) in lines
    quote = lines.index('"gains drift slowly"')
    assert lines[quote + 1] == "Check whether the solver interval follows this."


def test_a_whole_document_has_no_chunk_and_no_quote(
    corpus: Path, comments: dict[str, Annotation]
):
    flags, _ = note(corpus, "flags")

    said = run("search", "interference", "--collection", "annotations")

    lines = [line.strip() for line in said.splitlines() if line.strip()]
    assert any(line.endswith(f"id={flags} annotation=0000000c") for line in lines)
    assert link_to(flags, None) in lines
    assert not any(line.startswith('"') for line in lines)
    assert "Interference: compare with the RFI mask." in lines


def test_a_detached_selection_has_no_chunk(corpus: Path):
    drift, drift_body = note(corpus, "drift")
    gone = annotation(
        "0000000d",
        drift,
        body=drift_body + " Words that were cut since.",
        words="Words that were cut since.",
        comment="This sentence was removed later.",
    )
    write_store(corpus, AnnotationStore(annotations=(gone,)))

    said = run("search", "removed", "--collection", "annotations")

    lines = [line.strip() for line in said.splitlines() if line.strip()]
    assert any(line.endswith(f"id={drift} annotation=0000000d") for line in lines)
    assert link_to(drift, None) in lines
    assert '"Words that were cut since."' in lines


def test_an_agent_is_given_the_quote_and_the_comment(
    corpus: Path, comments: dict[str, Annotation]
):
    drift, _ = note(corpus, "drift")

    answer = search("solver interval", ["annotations"])

    lines = [line.strip() for line in answer.splitlines()]
    assert f"id={drift} chunk=0 annotation=0000000a" in answer
    quote = lines.index('"gains drift slowly"')
    assert lines[quote + 1].startswith("Check whether the solver interval")


# ---------------------------------------------------------------------------
# A project's comments


@pytest.fixture
def project(
    tmp_path: Path, corpus: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, str]:
    """A project with one indexed note and a comment on a sentence of it;
    the working directory. Returns the bundle and the note's path."""
    root = tmp_path / "pipelines"
    (root / ".git").mkdir(parents=True)
    bundle = init_bundle(root).path
    written = remember_in_bundle(
        bundle, "Pipelines solve the gains per scan.", title="Scans"
    )
    index_bundle(bundle)
    monkeypatch.chdir(root)
    path = written.relative_path
    body = (bundle / path).read_text(encoding="utf-8")
    store = AnnotationStore(
        annotations=(
            annotation(
                "0000000e",
                path,
                body=body,
                words="solve the gains per scan",
                comment="Per scan is too coarse for the long tracks.",
            ),
        )
    )
    write_store(bundle, store)
    return bundle, path


def test_a_projects_comment_is_in_the_same_group_by_its_path(
    project: tuple[Path, str], comments: dict[str, Annotation]
):
    _, path = project

    said = run("search", "coarse tracks", "--collection", "annotations")

    lines = [line.strip() for line in said.splitlines() if line.strip()]
    assert any(
        line.endswith(f"path=.context/{path} chunk=0 annotation=0000000e")
        for line in lines
    )
    assert context_link("pipelines", path, 0) in lines
    assert '"solve the gains per scan"' in lines


# ---------------------------------------------------------------------------
# The window

TOKEN = "a-test-token"


@pytest.fixture
def window(comments: dict[str, Annotation]) -> TestClient:
    client = TestClient(build_app(TOKEN), follow_redirects=False)
    assert client.get("/", params={"token": TOKEN}).status_code == 200
    return client


def card(window: TestClient, question: str) -> Tag:
    answered = window.get("/hits", params={"q": question, "scope": "annotations"})
    assert answered.status_code == 200
    (found,) = BeautifulSoup(answered.text, "html.parser").select("li.hit")
    return found


def test_the_window_quotes_the_selection_over_the_comment(
    corpus: Path, window: TestClient
):
    drift, _ = note(corpus, "drift")

    found = card(window, "solver interval")

    assert found.get("data-collection") == "annotations"
    quote = found.select_one("blockquote.hit-quote")
    assert quote is not None and quote.get_text() == "gains drift slowly"
    passage = found.select_one(".passage .body")
    assert passage is not None
    assert passage.get_text(" ", strip=True) == (
        "Check whether the solver interval follows this."
    )
    title = found.select_one("a.title")
    assert title is not None and title.get_text() == "drift"
    assert title.get("href") == f"/document/notes/{drift}?chunk=0#chunk-0"


def test_the_window_offers_the_annotation_to_edit_and_its_tags(window: TestClient):
    found = card(window, "solver interval")

    entries = [entry.get("href") for entry in found.select(".bookmark-items a")]
    assert "/annotations/0000000a" in entries
    assert not any(str(entry).startswith("/tags/add") for entry in entries)
    assert not found.select(".copy-citation")
    chips = [chip.get_text() for chip in found.select(".hit-tags .tag-chip")]
    assert chips == ["calibration"]


def test_the_window_offers_the_scope(window: TestClient):
    page = BeautifulSoup(window.get("/", params={"q": ""}).text, "html.parser")

    offered = [
        option.get("value") for option in page.select("select[name=scope] option")
    ]
    assert "annotations" in offered


def test_the_setting_takes_the_scope():
    chosen = Settings.model_validate(
        {"retrieval": {"default_collections": "annotations notes"}}
    )

    assert chosen.retrieval.default_collections == "annotations notes"
