"""A paper a pack declares and kennis cannot fetch, supplied as a local file.

Brian, 2026-10-26: the front end asks for the file once the sync is done,
and the paper it becomes is the pack's - filed as the sync would have filed
the fetched text, so the next sync keeps it rather than fetching it again.

No test reaches a host, and none hands over a client: a file supplied with
its identifier is added without asking anyone.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from kennis.engine.corpus.add import AddReport
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.schema import LiteratureFrontmatter
from kennis.engine.corpus.sync import supply_paper, sync_corpus
from kennis.engine.errors import InputError
from kennis.engine.events import Outcome
from kennis.engine.history.repository import initialise_corpus
from kennis.engine.pack.store import install_pack
from kennis.engine.pack.update import update_pack

DOI = "10.48479/bhpj-nz95"
ADDRESS = f"doi:{DOI}"

PACK = f"""\
kennis:
  schema_version: 1
pack:
  id: alpha
  name: n
  version: "1.0.0"
corpus:
  literature:
    - citekey: maccagniRFIMeerKAT2022
      title: "RFI at u=0 in MeerKAT observations"
      authors: ["Maccagni, F. M."]
      year: 2022
      identifier: "{DOI}"
      group: rfi
"""


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    root.mkdir()
    initialise_corpus(root)
    pack = tmp_path / "pack" / "alpha.ken.yml"
    pack.parent.mkdir()
    pack.write_text(PACK, encoding="utf-8")
    update_pack(pack)
    install_pack(root, pack)
    return root


@pytest.fixture
def downloaded(tmp_path: Path) -> Path:
    path = tmp_path / "Downloads" / "maccagni.md"
    path.parent.mkdir()
    path.write_text("# RFI at u=0\n\nThe text, downloaded by hand.\n", encoding="utf-8")
    return path


def supplied(corpus: Path, path: Path, address: str = ADDRESS) -> AddReport:
    # doi.org is asked what the paper is, and answers here that it does not
    # know: what is under test is where the paper is filed.
    unknown = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(404))
    )
    return supply_paper(corpus, address, path, arxiv=unknown)


def test_the_supplied_paper_is_the_packs(corpus: Path, downloaded: Path):
    report = supplied(corpus, downloaded)

    assert [one.outcome for one in report.outcomes] == [Outcome.ADDED]
    [paper] = Collection(root=corpus, name="literature").contents().documents
    assert paper.frontmatter.owner == "pack:alpha"
    assert isinstance(paper.frontmatter, LiteratureFrontmatter)
    assert paper.frontmatter.bib.citekey == "maccagniRFIMeerKAT2022"
    assert paper.md_path.parent == corpus / "literature" / "alpha" / "rfi"
    assert "downloaded by hand" in paper.body


def test_the_next_sync_keeps_it_without_fetching(corpus: Path, downloaded: Path):
    supplied(corpus, downloaded)
    asked: list[str] = []

    def answered(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(404)

    watching = httpx.Client(transport=httpx.MockTransport(answered))
    report = sync_corpus(
        corpus, arxiv=watching, client=watching, request_delay_seconds=0
    )

    assert [action.verdict for action in report.actions] == ["keep"]
    assert asked == []


def test_an_address_no_installed_pack_declares_is_refused(
    corpus: Path, downloaded: Path
):
    with pytest.raises(InputError, match=r"1101\.1764"):
        supplied(corpus, downloaded, address="arxiv:1101.1764")


def test_a_paper_already_held_is_refused(corpus: Path, downloaded: Path):
    supplied(corpus, downloaded)

    with pytest.raises(InputError, match="already"):
        supplied(corpus, downloaded)
