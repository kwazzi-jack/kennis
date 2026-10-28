"""A pack declares a paper by its identifier alone (#459, part 3).

`corpus add 1101.1764` needs nothing but the identifier, so a pack's
literature entry needs nothing more either. `kennis pack update` fills in
what an entry leaves out - the citekey, the title, the authors and the year
- as `corpus add` would derive them, and writes them into the entry itself
(Brian, 2026-10-26: "like a package.json with npm"), so every machine that
installs the pack files the paper under the same citekey.

Nothing here reaches a host: every client is an `httpx.MockTransport`.
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path

import httpx
import pytest
import yaml

from kennis.engine.corpus.add import AddOptions, add_literature
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.schema import LiteratureFrontmatter
from kennis.engine.corpus.sync import sync_corpus
from kennis.engine.errors import PackInvalid
from kennis.engine.events import Event, ItemFinished, Progress
from kennis.engine.history.repository import initialise_corpus
from kennis.engine.pack.editing import add_to_pack
from kennis.engine.pack.schema import load_pack
from kennis.engine.pack.store import install_pack
from kennis.engine.pack.update import GENERATED_MARKER, update_pack

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


def described(path: Path) -> dict[str, dict[str, object]]:
    """Each paper's entry as the file now holds it, by its key, without the
    identifier the test wrote; and no paper recorded in the generated
    block, which holds checksums alone."""
    text = path.read_text(encoding="utf-8")
    document = yaml.safe_load(text)
    assert "literature" not in (document.get("generated") or {})
    pack = load_pack(text)
    return {
        entry.key: {key: value for key, value in raw.items() if key != "identifier"}
        for entry, raw in zip(
            pack.corpus.literature, document["corpus"]["literature"], strict=True
        )
    }


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


def test_update_writes_what_the_entry_leaves_out_into_the_entry(tmp_path: Path):
    path = a_pack(tmp_path, "    - identifier: '1101.1764'\n")

    result = update_pack(path, arxiv=arxiv(), request_delay_seconds=0)

    assert described(path) == {
        "arxiv:1101.1764": {
            "citekey": "smirnovRevisitingRime2011",
            "title": "Revisiting the RIME",
            "authors": ["Oleg Smirnov"],
            "year": 2011,
        }
    }
    assert result.described == (("arxiv:1101.1764", "smirnovRevisitingRime2011"),)


def test_the_entry_is_written_again_in_kennis_s_order(tmp_path: Path):
    """The derived fields and the author's own, in one order (#558)."""
    path = a_pack(tmp_path, "    - identifier: '1101.1764'\n      group: rime\n")

    updated(path, arxiv())

    assert (
        "  literature:\n"
        "    - {\n"
        '        identifier: "1101.1764",\n'
        '        citekey: "smirnovRevisitingRime2011",\n'
        '        title: "Revisiting the RIME",\n'
        "        year: 2011,\n"
        '        group: "rime",\n'
        "        authors: [\n"
        '          "Oleg Smirnov",\n'
        "        ],\n"
        "      }\n"
    ) in path.read_text(encoding="utf-8")


def test_an_entry_whose_dash_stands_alone_is_written_from_its_dash(
    tmp_path: Path,
):
    path = a_pack(tmp_path, "    -\n      identifier: '1101.1764'\n")

    updated(path, arxiv())

    text = path.read_text(encoding="utf-8")
    assert "  literature:\n    - {\n" in text
    assert "    -\n" not in text


def test_a_record_in_the_generated_block_is_refused_naming_what_to_do():
    with pytest.raises(PackInvalid, match="kennis pack update") as raised:
        load_pack(
            f"{HEADER}corpus:\n  literature:\n    - identifier: '1101.1764'\n"
            'generated:\n  at: "x"\n  by: "y"\n'
            "  literature:\n    arxiv:1101.1764:\n      citekey: rime\n"
        )

    assert "into its entry" in str(raised.value)


def test_a_citekey_edited_by_hand_is_kept_by_the_next_update(tmp_path: Path):
    """The entry is the person's as much as kennis's: kennis writes into it
    and the person may change what it wrote."""
    path = a_pack(tmp_path, "    - identifier: '1101.1764'\n")
    updated(path, arxiv())
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            '"smirnovRevisitingRime2011"', '"rimeOne"'
        ),
        encoding="utf-8",
    )
    before = path.read_bytes()

    update_pack(path, arxiv=nowhere(), request_delay_seconds=0)

    assert described(path)["arxiv:1101.1764"]["citekey"] == "rimeOne"
    assert path.read_bytes() == before


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
    assert (
        described(path)["arxiv:1101.1764"]["citekey"] == paper.frontmatter.bib.citekey
    )


def test_the_authors_own_fields_are_kept_as_written(tmp_path: Path):
    path = a_pack(tmp_path, "    - identifier: '1101.1764'\n      title: The RIME\n")

    updated(path, arxiv())

    # Counted in the text: a YAML reader keeps the last of two equal keys
    # and says nothing, so a title written twice would read as one.
    assert path.read_text(encoding="utf-8").count("title:") == 1

    assert described(path) == {
        "arxiv:1101.1764": {
            "citekey": "smirnovRime2011",
            "authors": ["Oleg Smirnov"],
            "year": 2011,
            "title": "The RIME",
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

    assert described(path) == {"arxiv:1101.1764": {"citekey": "rime", "title": "T"}}
    assert "    - identifier: '1101.1764'\n      citekey: rime\n      title: T\n" in (
        path.read_text(encoding="utf-8")
    )


def test_two_papers_deriving_one_citekey_are_told_apart(tmp_path: Path):
    path = a_pack(
        tmp_path,
        "    - identifier: '1101.1764'\n"
        "    - identifier: '1502.06974'\n      year: 2011\n",
    )

    updated(path, arxiv())

    keys = [paper["citekey"] for paper in described(path).values()]
    assert sorted(keys) == ["smirnovRevisitingRime2011", "smirnovRevisitingRime2011a"]


def test_a_paper_arxiv_cannot_describe_is_reported_and_not_recorded(tmp_path: Path):
    path = a_pack(tmp_path, "    - identifier: '1101.1764'\n")

    result = update_pack(path, arxiv=arxiv(failing=True), request_delay_seconds=0)

    assert result.undescribed == ("arxiv:1101.1764",)
    assert described(path) == {"arxiv:1101.1764": {}}
    load_pack(path.read_text(encoding="utf-8"))


def registry(asked: list[str] | None = None) -> httpx.Client:
    """doi.org's content negotiation, for the one DOI below."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if asked is not None:
            asked.append(str(request.url))
        if request.url.host == "doi.org" and request.url.path == "/10.48479/bhpj-nz95":
            return httpx.Response(
                200,
                json={
                    "DOI": "10.48479/bhpj-nz95",
                    "title": "RFI at u=0 in MeerKAT observations",
                    "author": [
                        {"family": "Maccagni", "given": "Filippo Marcello"},
                        {"family": "Healy", "given": "Julia"},
                    ],
                    "issued": {"date-parts": [[2022]]},
                },
            )
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_a_doi_is_described_by_its_registry_as_an_arxiv_id_is_by_arxiv(
    tmp_path: Path,
):
    """Brian, 2026-10-26: a citekey need not be given when the DOI's own
    metadata can derive it."""
    path = a_pack(tmp_path, "    - identifier: doi:10.48479/bhpj-nz95\n")

    result = update_pack(path, arxiv=registry(), request_delay_seconds=0)

    assert described(path) == {
        "doi:10.48479/bhpj-nz95": {
            "citekey": "maccagniRfiUMeerkat2022",
            "title": "RFI at u=0 in MeerKAT observations",
            "authors": ["Maccagni, Filippo Marcello", "Healy, Julia"],
            "year": 2022,
        }
    }
    assert result.undescribed == ()


def test_what_a_doi_entry_gives_is_kept_and_only_the_rest_written(tmp_path: Path):
    path = a_pack(
        tmp_path,
        "    - identifier: 10.48479/bhpj-nz95\n"
        "      url: https://archive.example.org/smearing.pdf\n"
        "      title: MeerKAT time smearing simulation\n      year: 2024\n",
    )

    updated(path, registry())

    assert described(path) == {
        "doi:10.48479/bhpj-nz95": {
            "citekey": "maccagniMeerkatTimeSmearing2024",
            "authors": ["Maccagni, Filippo Marcello", "Healy, Julia"],
            "url": "https://archive.example.org/smearing.pdf",
            "title": "MeerKAT time smearing simulation",
            "year": 2024,
        }
    }


def test_a_doi_its_registry_cannot_describe_is_reported_and_not_recorded(
    tmp_path: Path,
):
    path = a_pack(tmp_path, "    - identifier: doi:10.1093/mnras/unknown\n")

    result = update_pack(path, arxiv=registry(), request_delay_seconds=0)

    assert result.undescribed == ("doi:10.1093/mnras/unknown",)
    assert described(path) == {"doi:10.1093/mnras/unknown": {}}


def test_a_bibcode_is_still_described_from_what_the_entry_says(tmp_path: Path):
    """ADS needs a key kennis does not ask for."""
    path = a_pack(
        tmp_path,
        "    - identifier: 2011A&A...527A.106S\n"
        "      title: Revisiting the RIME\n      authors: ['Smirnov, O. M.']\n"
        "      year: 2011\n",
    )

    update_pack(path, arxiv=nowhere(), request_delay_seconds=0)

    assert described(path) == {
        "bibcode:2011A&A...527A.106S": {
            "citekey": "smirnovRevisitingRime2011",
            "title": "Revisiting the RIME",
            "authors": ["Smirnov, O. M."],
            "year": 2011,
        }
    }


def test_the_authors_comments_are_kept(tmp_path: Path):
    path = a_pack(tmp_path, "    - identifier: '1101.1764'\n")

    updated(path, arxiv())

    assert "# The author's own comment.\n" in path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# corpus sync files the paper under the citekey its entry holds
# ---------------------------------------------------------------------------


def test_sync_files_the_paper_under_its_entry_s_citekey(tmp_path: Path):
    path = a_pack(tmp_path, "    - identifier: '1101.1764'\n")
    updated(path, arxiv())
    text = path.read_text(encoding="utf-8").replace(
        '"smirnovRevisitingRime2011"', '"theWrittenOne"'
    )
    path.write_text(text, encoding="utf-8")
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    initialise_corpus(corpus)
    install_pack(corpus, path)

    sync_corpus(corpus, arxiv=arxiv(), client=arxiv(), request_delay_seconds=0)

    (paper,) = Collection(root=corpus, name="literature").contents().documents
    assert isinstance(paper.frontmatter, LiteratureFrontmatter)
    assert paper.frontmatter.bib.citekey == "theWrittenOne"


def test_sync_derives_a_citekey_where_nothing_was_written(tmp_path: Path):
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


def test_a_written_citekey_keeps_its_place_when_a_new_paper_derives_it(
    tmp_path: Path,
):
    """A citekey never moves once written: the paper declared later, even
    above it in the file, is the one told apart."""
    path = a_pack(tmp_path, "    - identifier: '1101.1764'\n")
    updated(path, arxiv())
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "  literature:\n",
            "  literature:\n    - identifier: '1502.06974'\n      year: 2011\n",
        ),
        encoding="utf-8",
    )

    updated(path, arxiv())

    assert described(path)["arxiv:1101.1764"]["citekey"] == "smirnovRevisitingRime2011"
    assert (
        described(path)["arxiv:1502.06974"]["citekey"] == "smirnovRevisitingRime2011a"
    )


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


def test_filling_an_entry_leaves_the_block_and_its_stamp_alone(tmp_path: Path):
    """No checksum changed, so the block's bytes - `at` included - stay."""
    path = a_pack(tmp_path, "    - identifier: '1101.1764'\n      citekey: rime\n")
    update_pack(path, arxiv=nowhere(), request_delay_seconds=0)
    # A stamp from long ago: one written this second would be rewritten
    # with the same bytes, and the test could not tell.
    stamped = re.sub(
        r'at: "[^"]*"', 'at: "2000-01-01T00:00:00Z"', path.read_text(encoding="utf-8")
    )
    path.write_text(stamped, encoding="utf-8")
    block = stamped.partition(GENERATED_MARKER)[2]
    path.write_text(
        stamped.replace(
            "  literature:\n", "  literature:\n    - identifier: '1502.06974'\n"
        ),
        encoding="utf-8",
    )

    result = update_pack(path, arxiv=arxiv(), request_delay_seconds=0)

    assert result.outcome == "written"
    assert path.read_text(encoding="utf-8").partition(GENERATED_MARKER)[2] == block


# ---------------------------------------------------------------------------
# Saying the lookups are running (Brian, 2026-10-27)
# ---------------------------------------------------------------------------


class Recording:
    def __init__(self) -> None:
        self.events: list[Event] = []

    def emit(self, event: Event) -> None:
        self.events.append(event)

    def progress(self) -> list[tuple[int, int | None]]:
        return [
            (event.completed, event.total)
            for event in self.events
            if isinstance(event, Progress)
        ]


def test_each_lookup_advances_progress_as_it_returns(tmp_path: Path):
    """A doi.org lookup took 8 to 10 s here (Crossref's latency), and six of
    them printed nothing for 56 s. At each request, the progress already
    emitted must say how many came before it - not all at the end."""
    path = a_pack(
        tmp_path,
        "    - identifier: arxiv:1101.1764\n    - identifier: arxiv:1502.06974\n",
    )
    sink = Recording()
    seen_at_request: list[list[tuple[int, int | None]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path != "/robots.txt":
            seen_at_request.append(sink.progress())
        return arxiv().send(request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    update_pack(path, arxiv=client, request_delay_seconds=0, events=sink)

    assert sink.progress() == [(0, 2), (1, 2), (2, 2)]
    # A lookup may make more than one request, so each paper's requests are
    # one run of equal values.
    last_seen = [seen[-1] for seen in seen_at_request]
    assert [
        one for at, one in enumerate(last_seen) if last_seen[at - 1 : at] != [one]
    ] == [
        (0, 2),
        (1, 2),
    ]


def test_an_update_owing_no_lookup_draws_no_progress(tmp_path: Path):
    path = a_pack(
        tmp_path,
        "    - identifier: arxiv:1101.1764\n      citekey: smirnov2011\n",
    )
    sink = Recording()

    update_pack(path, arxiv=nowhere(), request_delay_seconds=0, events=sink)

    assert sink.progress() == []


def test_pack_add_hands_its_sink_to_the_update_and_times_all_of_it(
    tmp_path: Path,
):
    """`Added 6 entries in 6ms` measured the entries and not the 56 s of
    lookups after them."""
    path = a_pack(
        tmp_path, "    - identifier: arxiv:1101.1764\n      citekey: smirnov2011\n"
    )
    sink = Recording()
    pause = 0.2

    def handler(request: httpx.Request) -> httpx.Response:
        time.sleep(pause)
        return registry().send(request)

    addition = add_to_pack(
        path,
        "literature",
        ["doi:10.48479/bhpj-nz95"],
        AddOptions(),
        events=sink,
        arxiv=httpx.Client(transport=httpx.MockTransport(handler)),
        request_delay_seconds=0,
    )

    assert sink.progress() == [(0, 1), (1, 1)]
    assert addition.report.elapsed_seconds >= pause


def test_doi_lookups_run_together_and_citekeys_keep_entry_order(tmp_path: Path):
    """Brian, 2026-10-27: requests in parallel where the host allows it.
    doi.org names no delay, so two lookups are in flight at once - each
    answer waits for the other request, so one at a time fails the barrier -
    and the second paper deriving the same citekey is still the one told
    apart, whichever answer came back first."""
    together = threading.Barrier(2, timeout=5)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        together.wait()
        doi = request.url.path.lstrip("/")
        return httpx.Response(
            200,
            json={
                "DOI": doi,
                "title": "Mining the time axis",
                "author": [{"family": "Smirnov", "given": "Oleg"}],
                "issued": {"date-parts": [[2025]]},
            },
        )

    path = a_pack(
        tmp_path,
        "    - identifier: doi:10.1093/mnrasl/slaf009\n"
        "    - identifier: doi:10.1093/mnrasl/slaf015\n",
    )

    result = update_pack(
        path,
        arxiv=httpx.Client(transport=httpx.MockTransport(handler)),
        request_delay_seconds=0,
    )

    assert result.described == (
        ("doi:10.1093/mnrasl/slaf009", "smirnovMiningTimeAxis2025"),
        ("doi:10.1093/mnrasl/slaf015", "smirnovMiningTimeAxis2025a"),
    )


def test_each_lookup_names_its_paper_as_it_returns(tmp_path: Path):
    """So a bar can say what it is working on, not only how far it is."""
    path = a_pack(
        tmp_path,
        "    - identifier: arxiv:1101.1764\n    - identifier: arxiv:1502.06974\n",
    )
    sink = Recording()

    update_pack(path, arxiv=arxiv(), request_delay_seconds=0, events=sink)

    named = [
        event.item
        for event in sink.events
        if isinstance(event, ItemFinished) and event.operation == "pack-describe"
    ]
    assert named == ["arxiv:1101.1764", "arxiv:1502.06974"]
