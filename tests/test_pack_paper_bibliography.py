"""A pack's paper written by a sync takes the pack's bibliography for the gaps.

Measured 2026-11-21: two `tron` papers written while arXiv and doi.org did
not answer came back with no authors and no year and MinerU's heading for
a title, though the pack declares all three. The rule `_rewrote_bibliography`
states - the fetch where it has a value, the pack's values fill the gaps -
holds for a paper written by a sync as well as one rewritten.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.document import Document
from kennis.engine.corpus.schema import LiteratureFrontmatter
from kennis.engine.corpus.sync import CorpusSync, supply_paper, sync_corpus
from kennis.engine.history.repository import initialise_corpus
from kennis.engine.pack.store import install_pack
from kennis.engine.pack.update import update_pack

DOI = "10.1016/j.newar.2004.09.038"
HEADER = (
    'kennis:\n  schema_version: 1\npack:\n  id: alpha\n  name: n\n  version: "1.0.0"\n'
)


def entry(*, shipped: bool) -> str:
    return (
        "    - citekey: cordesDynamicRadioSky2004\n"
        '      title: "The dynamic radio sky"\n'
        '      authors: ["Cordes, James M.", "Lazio, T. Joseph W."]\n'
        "      year: 2004\n"
        f'      identifier: "{DOI}"\n'
        "      group: transients\n"
        + ("      file: papers/cordes.pdf\n" if shipped else "")
    )


@pytest.fixture
def corpus(tmp_path: Path, fake_mineru: Path) -> Path:
    root = tmp_path / "corpus"
    root.mkdir()
    initialise_corpus(root)
    return root


def installed(corpus: Path, tmp_path: Path, *, shipped: bool = True) -> None:
    pack = tmp_path / "pack"
    (pack / "papers").mkdir(parents=True)
    (pack / "papers" / "cordes.pdf").write_bytes(b"%PDF-1.4 cordes\n")
    path = pack / "alpha.ken.yml"
    path.write_text(
        HEADER + "corpus:\n  literature:\n" + entry(shipped=shipped), encoding="utf-8"
    )
    update_pack(path)
    install_pack(corpus, path)


def answering(registry: dict[str, object] | None) -> httpx.Client:
    """doi.org answers `registry` as CSL-JSON, or nothing answers at all."""

    def answer(request: httpx.Request) -> httpx.Response:
        if registry is not None and request.url.host == "doi.org":
            return httpx.Response(200, json=registry)
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(answer))


def synced(corpus: Path, client: httpx.Client) -> CorpusSync:
    return sync_corpus(corpus, arxiv=client, client=client, request_delay_seconds=0)


def the_paper(corpus: Path) -> tuple[Document, LiteratureFrontmatter]:
    [paper] = Collection(root=corpus, name="literature").contents().documents
    assert isinstance(paper.frontmatter, LiteratureFrontmatter)
    return paper, paper.frontmatter


def test_a_paper_whose_metadata_did_not_come_takes_the_pack_s(
    corpus: Path, tmp_path: Path
) -> None:
    installed(corpus, tmp_path)

    report = synced(corpus, answering(None))

    assert report.failed == ()
    paper, frontmatter = the_paper(corpus)
    assert frontmatter.title == "The dynamic radio sky"
    assert frontmatter.bib.authors == "Cordes, James M. and Lazio, T. Joseph W."
    assert frontmatter.bib.year == "2004"
    assert frontmatter.bib.citekey == "cordesDynamicRadioSky2004"
    assert "Cordes et al - 2004" in paper.md_path.as_posix()


def test_what_the_registry_says_comes_before_the_pack(
    corpus: Path, tmp_path: Path
) -> None:
    installed(corpus, tmp_path)
    registry = {
        "DOI": DOI,
        "title": "The Dynamic Radio Sky as the Registry Has It",
        "author": [{"family": "Cordes", "given": "J. M."}],
        "issued": {"date-parts": [[2005]]},
    }

    synced(corpus, answering(registry))

    _, frontmatter = the_paper(corpus)
    assert frontmatter.title == "The Dynamic Radio Sky as the Registry Has It"
    assert frontmatter.bib.authors == "Cordes, J. M."
    assert frontmatter.bib.year == "2005"


def test_a_paper_supplied_for_a_pack_takes_the_pack_s_as_well(
    corpus: Path, tmp_path: Path
) -> None:
    """`supply_paper` files as the sync would have (Brian, 2026-10-26)."""
    installed(corpus, tmp_path, shipped=False)
    supplied = tmp_path / "downloaded.pdf"
    supplied.write_bytes(b"%PDF-1.4 cordes, downloaded\n")
    nowhere = answering(None)

    supply_paper(corpus, f"doi:{DOI}", supplied, arxiv=nowhere, client=nowhere)

    _, frontmatter = the_paper(corpus)
    assert frontmatter.bib.authors == "Cordes, James M. and Lazio, T. Joseph W."
    assert frontmatter.bib.year == "2004"
    assert frontmatter.title == "The dynamic radio sky"
