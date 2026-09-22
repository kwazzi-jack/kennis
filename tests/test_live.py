"""Tests that touch the real network, deselected by default.

Run them with `uv run pytest -m network`. They exist because three concerns in
`design/concerns.md` cannot be settled against a fixture: #14 (which mineru
extra is needed), #26 (whether the identity rule is too strict against real
papers) and #34 (what a publisher actually serves to a standalone client). A
fixture I wrote agrees with my parser by construction; a real host does not.

They are expected to be slower and less reliable than the rest of the suite,
and a failure here is as likely to mean an upstream site changed as that
kennis is wrong. That is why they are opt-in rather than skipped on a network
probe: a test that silently skips reports nothing.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from kennis.engine.corpus.add import AddOptions, add_docs, add_literature
from kennis.engine.corpus.collection import Collection
from kennis.engine.docs.discover import discover_pages, discovery_mode
from kennis.engine.docs.sites import DocsSite
from kennis.engine.events import Outcome
from kennis.engine.literature.fetch import fetch_paper
from kennis.engine.literature.metadata import lookup_arxiv_metadata

pytestmark = pytest.mark.network

# arXiv's throttle is address-level and its window is minutes, not seconds:
# measured on 2026-09-21, a burst refused every subsequent request for long
# enough that `curl` from the same machine was refused too, and a cold request
# minutes later succeeded. Three seconds - arXiv's own stated API interval -
# is therefore not enough to make this module reliable, and no interval can
# make it certain. Ten seconds plus ordering the light requests before the
# heavy ones is what made it pass; it is a mitigation, not a guarantee.
#
# The tests below are ordered deliberately: the two API queries first, the
# full-paper fetches after. A rendered paper is around 360 KB and is what
# trips the throttle, and both observed failures were of the test that ran
# immediately after one.
_ARXIV_REQUEST_INTERVAL_SECONDS = 10.0


@pytest.fixture(autouse=True)
def _spaced() -> Iterator[None]:
    yield
    time.sleep(_ARXIV_REQUEST_INTERVAL_SECONDS)


# A 2011 paper, old enough that arXiv's own HTML backfill may not reach it,
# so this also exercises the ar5iv fallback.
SMIRNOV_ARXIV_ID = "1101.1764"

# An MNRAS article. Oxford Academic mints the PDF URL against the session that
# rendered the landing page, so a standalone client cannot follow it.
MNRAS_PDF_URL = (
    "https://academic.oup.com/mnras/article-pdf/416/2/832/3080350/mnras0416-0832.pdf"
)

SPHINX_SITE = "https://www.sphinx-doc.org/en/master/"


# ---------------------------------------------------------------------------
# arXiv, lightest request first
# ---------------------------------------------------------------------------


def test_a_real_arxiv_paper_has_metadata():
    metadata = lookup_arxiv_metadata(SMIRNOV_ARXIV_ID)

    assert metadata is not None
    assert "Smirnov" in metadata.authors
    assert metadata.year == "2011"


def test_an_identifier_that_names_no_paper_is_unavailable_not_an_error():
    assert fetch_paper("9999.99999").source == "unavailable"


def test_a_real_arxiv_paper_can_be_fetched():
    result = fetch_paper(SMIRNOV_ARXIV_ID)

    assert result.source in ("arxiv-html", "ar5iv")
    assert result.markdown is not None
    assert len(result.markdown) > 5000


def test_a_real_paper_added_by_identifier_gets_a_body(tmp_path: Path):
    """The whole path, against the real service: identifier to bibliography to
    text. Concern #26 is about whether this holds for papers generally."""
    papers = Collection(root=tmp_path / "corpus", name="literature")
    report = add_literature(papers, [SMIRNOV_ARXIV_ID])

    assert [outcome.outcome for outcome in report.outcomes] == [Outcome.ADDED]
    document = papers.contents().documents[0]
    assert "has not been fetched" not in document.body


# ---------------------------------------------------------------------------
# Documentation sites
# ---------------------------------------------------------------------------


def test_a_real_sphinx_site_is_recognised_as_one():
    import httpx

    with httpx.Client(follow_redirects=True) as client:
        assert discovery_mode(client, SPHINX_SITE) == "sphinx"


def test_a_real_sphinx_site_yields_pages():
    import httpx

    site = DocsSite(project="sphinx", base_url=SPHINX_SITE)
    with httpx.Client(follow_redirects=True) as client:
        found = discover_pages(client, site)

    assert found.mode == "sphinx"
    assert len(found.pages) > 20
    assert all(not item.key.startswith("/") for item in found.pages)


def test_a_real_site_can_be_added(tmp_path: Path):
    docs = Collection(root=tmp_path / "corpus", name="docs")
    report = add_docs(
        docs,
        [SPHINX_SITE],
        AddOptions(project="sphinx", max_pages=5),
    )

    added = [item for item in report.outcomes if item.outcome is Outcome.ADDED]
    assert added
    assert docs.contents().documents


# ---------------------------------------------------------------------------
# What a standalone client cannot have
# ---------------------------------------------------------------------------


def test_a_publisher_pdf_is_refused_rather_than_written(tmp_path: Path):
    """Concern #34, stated as a test. Whether the publisher answers with a
    challenge page, a redirect to a landing page or an error, the one thing
    that must not happen is a document whose body is the refusal."""
    notes = Collection(root=tmp_path / "corpus", name="notes")
    from kennis.engine.corpus.add import add_notes

    report = add_notes(notes, [MNRAS_PDF_URL])

    written = notes.contents().documents
    if not written:
        assert set(report.counts) <= {Outcome.FAILED, Outcome.SKIPPED}
        return
    body = written[0].body.lower()
    for phrase in ("just a moment", "checking your browser", "enable javascript"):
        assert phrase not in body


# ---------------------------------------------------------------------------
# The embedding backend
# ---------------------------------------------------------------------------


def test_the_default_backend_really_embeds(tmp_path: Path):
    """Nothing offline can test this: every other embedding test supplies its
    own embedder, so the one thing never exercised is whether the fastembed
    binding resolves to a model that runs. The first run on a machine
    downloads it, which design section 15 measured at about 33 seconds."""
    import numpy as np

    from kennis.engine.rag.binding import Binding, document_digest
    from kennis.engine.rag.cache import VectorCache
    from kennis.engine.rag.chunking import ChunkParameters
    from kennis.engine.rag.embedding import ModelBinding, embed_texts

    binding = ModelBinding(
        kind="fastembed", model="BAAI/bge-small-en-v1.5", dim=384, normalise=True
    )
    texts = [
        "Calibration solves for antenna gains against a sky model.",
        "A recipe for baking sourdough bread at home.",
        "Gain solutions are derived per antenna and per time interval.",
    ]

    matrix = embed_texts(binding, texts)

    assert matrix.shape == (3, 384)
    assert matrix.dtype == np.float32
    for row in matrix:
        assert float(np.linalg.norm(row)) == pytest.approx(1.0, abs=1e-5)

    # The two calibration sentences must sit closer to each other than either
    # does to the bread. If this fails the vectors are arriving, but they are
    # not carrying meaning, which no shape assertion would catch.
    related = float(matrix[0] @ matrix[2])
    unrelated = float(matrix[0] @ matrix[1])
    assert related > unrelated

    # And the cache round-trips a real matrix, not just a synthetic one.
    cache = VectorCache(
        root=tmp_path / "vectors",
        binding=Binding(chunking=ChunkParameters(), model=binding),
    )
    digest = document_digest(texts[0])
    cache.put("doc1", digest, matrix)
    restored = cache.get("doc1", digest)

    assert restored is not None
    assert np.array_equal(restored, matrix)


@pytest.mark.network
def test_the_whole_dense_path_runs_end_to_end(tmp_path: Path):
    """`corpus index` then `search`, with a real model and no stub anywhere.

    The one thing `test_the_default_backend_really_embeds` does not settle.
    That test calls `embed_texts` directly, so the parts it leaves untouched
    are the parts that only appear in a whole run: the binding built from
    settings, the per-document cache write, the matrix reaching the index in
    chunk order, and a query embedded with the index's own binding read back
    from disk rather than with the caller's configuration.

    A dense search that returned confident nonsense would pass every offline
    test in the suite, because a stub embedder agrees with itself.
    """
    from click.testing import CliRunner

    from kennis.cli.__main__ import main

    corpus = tmp_path / "corpus"
    runner = CliRunner()
    environment = {
        "KENNIS_CORPUS_ROOT": str(corpus),
        "KENNIS_CONFIG_DIR": str(tmp_path / "config"),
        "KENNIS_LOG_DIR": str(tmp_path / "state"),
        "KENNIS_EMBEDDING_BACKEND": "fastembed",
        "KENNIS_EMBEDDING_MODEL": "BAAI/bge-small-en-v1.5",
        "KENNIS_EMBEDDING_DIMENSIONS": "384",
    }

    def invoke(*arguments: str) -> object:
        result = runner.invoke(main, list(arguments), env=environment)
        assert result.exit_code == 0, result.output
        return result

    sources = tmp_path / "sources"
    sources.mkdir()
    for name, body in {
        "gains": "Calibration solves for antenna gains against a sky model.",
        "bread": "A recipe for baking sourdough bread slowly at home.",
    }.items():
        (sources / f"{name}.md").write_text(f"# {name}\n\n{body}\n", encoding="utf-8")

    invoke("corpus", "init")
    invoke("corpus", "add", "-n", *[str(path) for path in sorted(sources.iterdir())])
    built = invoke("corpus", "index")
    assert "fastembed" in getattr(built, "output", "")

    # The vectors must have reached the index, not only the cache.
    pointer = json.loads(
        (corpus / "index" / "notes" / "latest.json").read_text(encoding="utf-8")
    )
    index_dir = corpus / "index" / "notes" / str(pointer["index_id"])
    assert (index_dir / "embeddings.npy").is_file()

    # A query sharing no words with the document it should find. BM25 cannot
    # answer this at all, so the *ordering* here is the dense leg doing its
    # job. Ordering and not exclusion: a dense search ranks every chunk it is
    # given and returns the best `top_k`, so with two documents in the corpus
    # both come back whatever the query, and asserting that one is absent
    # would be asserting something retrieval never promised.
    found = invoke("search", "antenna phase solutions", "--mode", "dense")
    output = getattr(found, "output", "").lower()
    assert "gains" in output and "bread" in output
    assert output.index("gains") < output.index("bread")
