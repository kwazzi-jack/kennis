"""A pack declares a paper by its identifier alone (#459, part 3).

`corpus add 1101.1764` needs nothing but the identifier, so a pack's
literature entry needs nothing more either. `kennis pack update` fills in
what an entry leaves out - the citekey, the title, the authors and the year
- as `corpus add` would derive them, and records them in the generated
block, so every machine that installs the pack files the paper under the
same citekey.

Nothing here reaches a host: every client is an `httpx.MockTransport`.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import yaml

from kennis.engine.corpus.add import AddOptions, add_literature
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.schema import LiteratureFrontmatter
from kennis.engine.corpus.sync import sync_corpus
from kennis.engine.errors import PackInvalid
from kennis.engine.history.repository import initialise_corpus
from kennis.engine.pack.schema import load_pack
from kennis.engine.pack.store import install_pack
from kennis.engine.pack.update import update_pack

HEADER = (
    'kennis:\n  schema_version: 1\npack:\n  id: alpha\n  name: n\n  version: "1.0.0"\n'
)


def atom(identifier: str, title: str, author: str, published: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
        f"<id>http://arxiv.org/abs/{identifier}v1</id>"
        f"<published>{published}T12:00:00Z</published>"
        f"<title>{title}</title><author><name>{author}</name></author>"
        "</entry></feed>"
    )


PAPERS = {
    "1101.1764": atom("1101.1764", "Revisiting the RIME", "Oleg Smirnov", "2011-01-10"),
    "1502.06974": atom(
        "1502.06974", "Revisiting the RIME", "Oleg Smirnov", "2015-02-24"
    ),
}

LATEXML = (
    '<html><body><article class="ltx_document"><h1>Revisiting the RIME</h1>'
    "<p>The full text of the paper.</p></article></body></html>"
)


def arxiv(asked: list[str] | None = None, *, failing: bool = False) -> httpx.Client:
    """arXiv's API and its HTML, for the two papers above."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if asked is not None:
            asked.append(url)
        if failing:
            return httpx.Response(503)
        if "/html/" in url:
            return httpx.Response(
                200, text=LATEXML, headers={"content-type": "text/html"}
            )
        for identifier, feed in PAPERS.items():
            if identifier in url:
                return httpx.Response(
                    200, text=feed, headers={"content-type": "application/atom+xml"}
                )
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def nowhere() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"pack update asked {request.url}")

    return httpx.Client(transport=httpx.MockTransport(handler))


def a_pack(tmp_path: Path, literature: str) -> Path:
    path = tmp_path / "alpha.ken.yml"
    path.write_text(
        f"{HEADER}# The author's own comment.\ncorpus:\n  literature:\n{literature}",
        encoding="utf-8",
    )
    return path


def recorded(path: Path) -> dict[str, dict[str, object]]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    papers = document["generated"].get("literature", {})
    assert isinstance(papers, dict)
    return papers


def updated(path: Path, client: httpx.Client) -> None:
    update_pack(path, arxiv=client, request_delay_seconds=0)


# ---------------------------------------------------------------------------
# The schema
# ---------------------------------------------------------------------------


def test_an_identifier_alone_declares_a_paper():
    pack = load_pack(f"{HEADER}corpus:\n  literature:\n    - identifier: '1101.1764'\n")

    assert pack.corpus.literature[0].key == "arxiv:1101.1764"


def test_an_address_naming_the_paper_declares_it():
    pack = load_pack(
        f"{HEADER}corpus:\n  literature:\n"
        "    - url: https://arxiv.org/abs/1502.06974v2\n"
    )

    assert pack.corpus.literature[0].key == "arxiv:1502.06974"


def test_an_entry_with_neither_is_refused_naming_the_field():
    with pytest.raises(PackInvalid, match="identifier"):
        load_pack(f"{HEADER}corpus:\n  literature:\n    - title: Something\n")


def test_an_address_naming_no_paper_needs_the_identifier():
    with pytest.raises(PackInvalid, match="identifier"):
        load_pack(
            f"{HEADER}corpus:\n  literature:\n"
            "    - url: https://archive.example.org/report.pdf\n"
        )


# ---------------------------------------------------------------------------
# pack update describes the paper
# ---------------------------------------------------------------------------


def test_update_records_what_the_entry_leaves_out(tmp_path: Path):
    path = a_pack(tmp_path, "    - identifier: '1101.1764'\n")

    updated(path, arxiv())

    assert recorded(path) == {
        "arxiv:1101.1764": {
            "citekey": "smirnovRevisitingRime2011",
            "title": "Revisiting the RIME",
            "authors": "Oleg Smirnov",
            "year": 2011,
        }
    }


def test_the_citekey_is_the_one_corpus_add_derives(tmp_path: Path):
    path = a_pack(tmp_path, "    - identifier: '1101.1764'\n")
    updated(path, arxiv())
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    initialise_corpus(corpus)

    add_literature(
        Collection(root=corpus, name="literature"),
        ["1101.1764"],
        AddOptions(request_delay_seconds=0),
        arxiv=arxiv(),
        client=arxiv(),
    )

    (paper,) = Collection(root=corpus, name="literature").contents().documents
    assert isinstance(paper.frontmatter, LiteratureFrontmatter)
    assert recorded(path)["arxiv:1101.1764"]["citekey"] == paper.frontmatter.bib.citekey


def test_the_authors_own_fields_are_not_recorded(tmp_path: Path):
    path = a_pack(tmp_path, "    - identifier: '1101.1764'\n      title: The RIME\n")

    updated(path, arxiv())

    assert recorded(path) == {
        "arxiv:1101.1764": {
            "citekey": "smirnovRime2011",
            "authors": "Oleg Smirnov",
            "year": 2011,
        }
    }


def test_a_second_update_contacts_nothing_and_writes_nothing(tmp_path: Path):
    path = a_pack(tmp_path, "    - identifier: '1101.1764'\n")
    updated(path, arxiv())
    before = path.read_bytes()

    result = update_pack(path, arxiv=nowhere(), request_delay_seconds=0)

    assert result.outcome == "unchanged"
    assert path.read_bytes() == before


def test_an_entry_giving_its_citekey_contacts_nothing(tmp_path: Path):
    """The shape every pack had before #459: a citekey and a title, with
    the authors and the year left to the fetch at sync."""
    path = a_pack(
        tmp_path, "    - identifier: '1101.1764'\n      citekey: rime\n      title: T\n"
    )

    update_pack(path, arxiv=nowhere(), request_delay_seconds=0)

    assert recorded(path) == {}


def test_two_papers_deriving_one_citekey_are_told_apart(tmp_path: Path):
    path = a_pack(
        tmp_path,
        "    - identifier: '1101.1764'\n"
        "    - identifier: '1502.06974'\n      year: 2011\n",
    )

    updated(path, arxiv())

    keys = [paper["citekey"] for paper in recorded(path).values()]
    assert sorted(keys) == ["smirnovRevisitingRime2011", "smirnovRevisitingRime2011a"]


def test_a_paper_arxiv_cannot_describe_is_reported_and_not_recorded(tmp_path: Path):
    path = a_pack(tmp_path, "    - identifier: '1101.1764'\n")

    result = update_pack(path, arxiv=arxiv(failing=True), request_delay_seconds=0)

    assert result.undescribed == ("arxiv:1101.1764",)
    assert recorded(path) == {}
    load_pack(path.read_text(encoding="utf-8"))


def test_a_doi_is_described_from_what_the_entry_says_without_a_request(
    tmp_path: Path,
):
    path = a_pack(
        tmp_path,
        "    - identifier: 10.48479/bhpj-nz95\n"
        "      url: https://archive.example.org/smearing.pdf\n"
        "      title: MeerKAT time smearing simulation\n      year: 2024\n",
    )

    result = update_pack(path, arxiv=nowhere(), request_delay_seconds=0)

    assert recorded(path) == {
        "doi:10.48479/bhpj-nz95": {"citekey": "paperMeerkatTimeSmearing2024"}
    }
    assert result.undescribed == ()


def test_a_paper_no_longer_declared_loses_its_record(tmp_path: Path):
    path = a_pack(tmp_path, "    - identifier: '1101.1764'\n")
    updated(path, arxiv())

    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "    - identifier: '1101.1764'\n", "    - identifier: '1502.06974'\n"
        ),
        encoding="utf-8",
    )
    updated(path, arxiv())

    assert list(recorded(path)) == ["arxiv:1502.06974"]


def test_the_authors_text_above_the_block_is_kept(tmp_path: Path):
    path = a_pack(tmp_path, "    - identifier: '1101.1764'\n")

    updated(path, arxiv())

    assert "# The author's own comment.\n" in path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# corpus sync files the paper under the recorded citekey
# ---------------------------------------------------------------------------


def test_sync_files_the_paper_under_the_recorded_citekey(tmp_path: Path):
    path = a_pack(tmp_path, "    - identifier: '1101.1764'\n")
    updated(path, arxiv())
    text = path.read_text(encoding="utf-8").replace(
        '"smirnovRevisitingRime2011"', '"theRecordedOne"'
    )
    path.write_text(text, encoding="utf-8")
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    initialise_corpus(corpus)
    install_pack(corpus, path)

    sync_corpus(corpus, arxiv=arxiv(), client=arxiv(), request_delay_seconds=0)

    (paper,) = Collection(root=corpus, name="literature").contents().documents
    assert isinstance(paper.frontmatter, LiteratureFrontmatter)
    assert paper.frontmatter.bib.citekey == "theRecordedOne"


def test_sync_derives_a_citekey_where_nothing_was_recorded(tmp_path: Path):
    path = a_pack(tmp_path, "    - identifier: '1101.1764'\n")
    update_pack(path, arxiv=arxiv(failing=True), request_delay_seconds=0)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    initialise_corpus(corpus)
    install_pack(corpus, path)

    sync_corpus(corpus, arxiv=arxiv(), client=arxiv(), request_delay_seconds=0)

    (paper,) = Collection(root=corpus, name="literature").contents().documents
    assert isinstance(paper.frontmatter, LiteratureFrontmatter)
    assert paper.frontmatter.bib.citekey == "smirnovRevisitingRime2011"
    assert paper.frontmatter.owner == "pack:alpha"


def test_a_recorded_citekey_keeps_its_place_when_a_new_paper_derives_it(
    tmp_path: Path,
):
    """A citekey never moves once recorded: the paper declared later, even
    above it in the file, is the one told apart."""
    path = a_pack(tmp_path, "    - identifier: '1101.1764'\n")
    updated(path, arxiv())
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "    - identifier: '1101.1764'\n",
            "    - identifier: '1502.06974'\n      year: 2011\n"
            "    - identifier: '1101.1764'\n",
        ),
        encoding="utf-8",
    )

    updated(path, arxiv())

    assert recorded(path)["arxiv:1101.1764"]["citekey"] == "smirnovRevisitingRime2011"
    assert recorded(path)["arxiv:1502.06974"]["citekey"] == "smirnovRevisitingRime2011a"


def test_a_changed_declaration_keeps_a_citekey_the_add_derived(tmp_path: Path):
    path = a_pack(tmp_path, "    - identifier: '1101.1764'\n")
    update_pack(path, arxiv=arxiv(failing=True), request_delay_seconds=0)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    initialise_corpus(corpus)
    install_pack(corpus, path)
    sync_corpus(corpus, arxiv=arxiv(), client=arxiv(), request_delay_seconds=0)

    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "    - identifier: '1101.1764'\n",
            "    - identifier: '1101.1764'\n      title: Revisiting the RIME\n",
        ),
        encoding="utf-8",
    )
    update_pack(path, arxiv=arxiv(failing=True), request_delay_seconds=0)
    install_pack(corpus, path)
    report = sync_corpus(corpus, arxiv=nowhere(), client=nowhere())

    (paper,) = Collection(root=corpus, name="literature").contents().documents
    assert isinstance(paper.frontmatter, LiteratureFrontmatter)
    assert report.counts.get("rewrite") == 1
    assert paper.frontmatter.bib.citekey == "smirnovRevisitingRime2011"
