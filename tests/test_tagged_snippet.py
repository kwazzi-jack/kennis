"""A passage a tag admitted shows the words the tag is on (#50, unit 3b,
sketch 2026-11-17-tagged-snippet).

The command line and an agent are given those words as the snippet; the
window draws the whole passage, opened at them, and the browser highlights
them. A search kept to no tag, and a passage only a whole-document tag
admitted, are as before.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup, Tag
from click.testing import CliRunner
from fastapi.testclient import TestClient

from annotating import whole_document, write_store
from kennis.cli.__main__ import main
from kennis.context import existing_corpus
from kennis.engine.annotations import (
    Annotation,
    AnnotationStore,
    Span,
    annotated_spans,
    selector_of,
)
from kennis.engine.corpus.collection import Collection
from kennis.engine.rag.models import Chunk
from kennis.gui.app import build_app
from kennis.mcp.tools.search import search
from kennis.render.html import passage_html

CREATED = "2026-11-17T10:00:00+00:00"


def selection(
    identifier: str, document: str, body: str, words: str, tags: tuple[str, ...]
) -> Annotation:
    start = body.index(words)
    return Annotation(
        id=identifier,
        document=document,
        selector=selector_of(body, start, start + len(words)),
        tags=tags,
        comment=None,
        created=CREATED,
    )


# ---------------------------------------------------------------------------
# Where the words are, by hand

BODY = "Alpha beta gamma delta. Epsilon zeta eta theta. Iota kappa lambda mu."
# Two windows overlapping on "Epsilon zeta eta theta. ", as the chunker's
# sliding windows do.
FIRST = Chunk(
    id="d::0",
    collection="notes",
    document_id="d",
    chunk_index=0,
    text=BODY[:48],
    source_path="d.md",
    char_start=0,
    char_end=48,
)
SECOND = Chunk(
    id="d::1",
    collection="notes",
    document_id="d",
    chunk_index=1,
    text=BODY[24:],
    source_path="d.md",
    char_start=24,
    char_end=len(BODY),
)


def spans_of(
    *annotations: Annotation, names: tuple[str, ...] = ("t",)
) -> dict[str, tuple[Span, ...]]:
    return annotated_spans(
        AnnotationStore(annotations=annotations), names, [FIRST, SECOND]
    )


def test_a_selection_in_one_chunk_is_its_offsets_in_that_chunk():
    found = spans_of(selection("0000000a", "d", BODY, "beta gamma", ("t",)))

    assert found == {"d::0": (Span(6, 16),)}
    assert FIRST.text[6:16] == "beta gamma"


def test_a_selection_across_two_chunks_is_clipped_to_each():
    found = spans_of(selection("0000000a", "d", BODY, "delta. Epsilon zeta", ("t",)))

    assert found == {"d::0": (Span(17, 36),), "d::1": (Span(0, 12),)}
    assert FIRST.text[17:36] == "delta. Epsilon zeta"
    assert SECOND.text[0:12] == "Epsilon zeta"


def test_a_sentence_in_the_overlap_shows_in_the_window_that_owns_it():
    """Linked to the second window alone, as `links` says, and its words
    are in that window's text."""
    found = spans_of(selection("0000000a", "d", BODY, "zeta eta", ("t",)))

    assert found == {"d::1": (Span(8, 16),)}
    assert SECOND.text[8:16] == "zeta eta"


def test_a_whole_document_another_tag_and_a_detached_selection_give_none():
    gone = selection("0000000c", "d", BODY + " Nu xi.", "Nu xi.", ("t",))

    assert spans_of(whole_document("d", ("t",))) == {}
    assert spans_of(selection("0000000a", "d", BODY, "beta", ("other",))) == {}
    assert spans_of(gone) == {}


def test_any_asked_name_counts():
    found = spans_of(
        selection("0000000a", "d", BODY, "beta", ("a",)),
        selection("0000000b", "d", BODY, "gamma", ("b",)),
        names=("a", "b"),
    )

    assert found == {"d::0": (Span(6, 10), Span(11, 16))}


# ---------------------------------------------------------------------------
# Where a passage opens


def test_the_passage_opens_at_the_block_holding_the_words():
    markdown = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph here."

    drawn = passage_html(markdown, terms=(), fits=10, opens_at=markdown.index("Third"))

    assert "First" in drawn.lead and "Second" in drawn.lead
    assert drawn.body.startswith("<p>Third")


def test_the_words_open_it_before_an_earlier_mark_of_the_readers_words():
    markdown = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph here."

    drawn = passage_html(
        markdown, terms=("second",), fits=10, opens_at=markdown.index("Third")
    )

    assert "<mark>Second</mark>" in drawn.lead
    assert drawn.body.startswith("<p>Third")


# ---------------------------------------------------------------------------
# A corpus, searched through each front end

QUIET = (
    "The calibration notes begin with an unrelated opening paragraph about "
    "the observatory.\n\nA middle paragraph mentions the weather.\n\n"
    "Here the gains drift slowly after sunset, as expected.\n"
)


def run(*arguments: str) -> str:
    answered = CliRunner().invoke(main, list(arguments))
    assert answered.exit_code == 0, answered.output
    return answered.output


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    """One note of three paragraphs, its last sentence's words tagged
    `drift`. Returns the corpus and the note's identifier."""
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    run("corpus", "init")
    source = tmp_path / "quiet.md"
    source.write_text(f"# Quiet\n\n{QUIET}", encoding="utf-8")
    run("corpus", "add", "-n", str(source))
    run("corpus", "index")
    root = existing_corpus().corpus_root
    (document,) = Collection(root=root, name="notes").contents().documents
    write_store(
        root,
        AnnotationStore(
            annotations=(
                selection(
                    "0000000a",
                    document.id,
                    document.body,
                    "gains drift slowly after sunset",
                    ("drift",),
                ),
            )
        ),
    )
    return root, document.id


def lines_of(said: str) -> list[str]:
    return [" ".join(line.split()) for line in said.splitlines() if line.strip()]


def test_kennis_search_kept_to_a_tag_shows_the_tagged_words(corpus: tuple[Path, str]):
    said = lines_of(
        run("search", "calibration", "--collection", "notes", "--tag", "drift")
    )

    assert "gains drift slowly after sunset" in said
    assert not any("unrelated opening" in line for line in said)


def test_kennis_search_kept_to_no_tag_shows_the_passage_from_its_start(
    corpus: tuple[Path, str],
):
    said = " ".join(lines_of(run("search", "calibration", "--collection", "notes")))

    assert "unrelated opening" in said


def test_an_agent_kept_to_a_tag_is_given_the_tagged_words(corpus: tuple[Path, str]):
    answer = search("calibration", ["notes"], tags=["drift"])

    assert "  gains drift slowly after sunset" in answer.splitlines()
    assert "unrelated opening" not in answer


TOKEN = "a-test-token"


def card_of(client: TestClient, **query: str | list[str]) -> Tag:
    answered = client.get(
        "/hits", params={"q": "calibration", "scope": "notes", **query}
    )
    assert answered.status_code == 200
    (found,) = BeautifulSoup(answered.text, "html.parser").select("li.hit")
    return found


@pytest.fixture
def window(corpus: tuple[Path, str]) -> TestClient:
    client = TestClient(build_app(TOKEN), follow_redirects=False)
    assert client.get("/", params={"token": TOKEN}).status_code == 200
    return client


def test_the_window_opens_a_tagged_passage_at_its_words(window: TestClient):
    found = card_of(window, tag="drift")

    full = found.select_one(".passage .full")
    assert full is not None
    ((shown),) = json.loads(str(full.get("data-annotated")))
    assert shown["words"] == ["gains", "drift", "slowly", "after", "sunset"]
    # The third of three paragraphs: well past the passage's middle.
    assert 0.6 < shown["at"] < 1
    body = found.select_one(".passage .body")
    lead = found.select_one(".passage .lead")
    assert body is not None and lead is not None
    assert body.get_text(" ", strip=True).startswith("Here the gains drift")
    assert "unrelated opening" in lead.get_text(" ", strip=True)


def test_the_window_kept_to_no_tag_draws_nothing_and_opens_where_it_did(
    window: TestClient,
):
    found = card_of(window)

    full = found.select_one(".passage .full")
    assert full is not None and not full.has_attr("data-annotated")
    body = found.select_one(".passage .body")
    assert body is not None
    assert "unrelated opening" in body.get_text(" ", strip=True)


# ---------------------------------------------------------------------------
# A project's notes


def test_a_projects_passage_kept_to_a_tag_shows_the_tagged_words(
    tmp_path: Path, corpus: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
):
    from kennis.engine.context.bundle import init_bundle
    from kennis.engine.context.index import index_bundle
    from kennis.engine.context.notes import remember_in_bundle

    root = tmp_path / "pipelines"
    (root / ".git").mkdir(parents=True)
    bundle = init_bundle(root).path
    written = remember_in_bundle(
        bundle,
        "Pipelines open with a long preamble about scheduling.\n\n"
        "Then they solve the gains per scan, which is too coarse.",
        title="Scans",
    )
    index_bundle(bundle)
    monkeypatch.chdir(root)
    body = (bundle / written.relative_path).read_text(encoding="utf-8")
    write_store(
        bundle,
        AnnotationStore(
            annotations=(
                selection(
                    "0000000e",
                    written.relative_path,
                    body,
                    "solve the gains per scan",
                    ("coarse",),
                ),
            )
        ),
    )

    said = lines_of(
        run("search", "pipelines", "--collection", "context", "--tag", "coarse")
    )

    assert "solve the gains per scan" in said
    assert not any("preamble" in line for line in said)
