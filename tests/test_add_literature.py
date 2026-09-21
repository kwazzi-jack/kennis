"""Adding papers: notes plus bibliographic processing.

Literature refuses a document whose identity it cannot establish, because an
invented citekey cites nothing and duplicate detection - which runs on the
bibliographic identifiers - has nothing to compare. These tests are mostly
about that: what counts as an identity, where one may come from, and what
happens when there is none.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import httpx
import pytest

from kennis.engine.corpus.add import AddOptions, add_literature
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.converters import ConversionBatch
from kennis.engine.corpus.ids import derive_id
from kennis.engine.corpus.schema import LiteratureFrontmatter
from kennis.engine.events import Outcome, Recorder

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2409.19750v1</id>
    <published>2024-09-29T12:00:00Z</published>
    <title>A Paper About Calibration</title>
    <author><name>Brian Welman</name></author>
  </entry>
</feed>
"""


EMPTY_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>
"""


def arxiv_client(body: str = ATOM) -> httpx.Client:
    """An arXiv that answers the metadata query and renders no HTML.

    The rendering is a 404 rather than the same body, so this fixture answers
    only the question it is asked. A stub that replies identically to every
    request would hand an Atom feed to the HTML converter, which is a
    different test from the one the caller wrote.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if "/html/" in str(request.url):
            return httpx.Response(404)
        return httpx.Response(
            200, text=body, headers={"content-type": "application/atom+xml"}
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def no_preprint_client() -> httpx.Client:
    """An arXiv that holds nothing.

    Needed wherever a test has two papers with different DOIs: the fixture
    above answers every query with the *same* entry, so both DOIs would
    resolve to one arXiv identifier and the two papers would collide as
    duplicates for a reason the test was not about.
    """
    return arxiv_client(EMPTY_FEED)


class FrontPageConverter:
    """A converter that stamps each document's front page with what it says.

    The page text is keyed by filename, so a test can give one paper its own
    arXiv stamp and another nothing at all.
    """

    name = "front-page"
    formats = frozenset({"pdf", "docx", "pptx", "xlsx"})

    def __init__(self, front_pages: dict[str, str] | None = None) -> None:
        self.front_pages = front_pages or {}
        self.runs: list[tuple[Path, ...]] = []

    def is_available(self) -> bool:
        return True

    def install_hint(self) -> str:
        return "install it"

    def convert(
        self, paths: Sequence[Path], *, page_limit: int | None = None
    ) -> ConversionBatch:
        self.runs.append(tuple(paths))
        return ConversionBatch(
            markdown={path: f"# {path.stem}\n\nBody.\n" for path in paths},
            front_page={path: self.front_pages.get(path.name, "") for path in paths},
        )


@pytest.fixture
def papers(tmp_path: Path) -> Collection:
    return Collection(root=tmp_path / "corpus", name="literature")


def a_pdf(path: Path, body: bytes = b"%PDF-1.7\nfake\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


def citekeys_of(papers: Collection) -> set[str]:
    keys: set[str] = set()
    for document in papers.contents().documents:
        frontmatter = document.frontmatter
        assert isinstance(frontmatter, LiteratureFrontmatter)
        keys.add(frontmatter.bib.citekey)
    return keys


def only(papers: Collection) -> LiteratureFrontmatter:
    documents = papers.contents().documents
    assert len(documents) == 1
    frontmatter = documents[0].frontmatter
    assert isinstance(frontmatter, LiteratureFrontmatter)
    return frontmatter


# ---------------------------------------------------------------------------
# A paper named by its identifier
# ---------------------------------------------------------------------------


def test_a_bare_arxiv_identifier_is_enough(papers: Collection):
    report = add_literature(papers, ["2409.19750"], arxiv=arxiv_client())

    assert [outcome.outcome for outcome in report.outcomes] == [Outcome.ADDED]
    assert only(papers).bib.arxiv_id == "2409.19750"


def test_the_metadata_lookup_supplies_the_title_and_the_citekey(
    papers: Collection,
):
    """What upgrades a citekey from a title-derived one to a real
    author-and-year key."""
    add_literature(papers, ["2409.19750"], arxiv=arxiv_client())

    frontmatter = only(papers)
    assert frontmatter.title == "A Paper About Calibration"
    assert frontmatter.bib.citekey == "welmanPaperAboutCalibration2024"
    assert frontmatter.bib.authors == "Brian Welman"
    assert frontmatter.bib.year == "2024"


def test_a_paper_is_still_added_when_arxiv_cannot_be_reached(papers: Collection):
    """The identifier is what prevents the same paper landing twice, and it is
    already in hand; refusing over an unreachable arXiv trades a small loss for
    a total one."""

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    report = add_literature(
        papers,
        ["2409.19750"],
        arxiv=httpx.Client(transport=httpx.MockTransport(unreachable)),
    )

    assert report.outcomes[0].outcome is Outcome.ADDED
    assert only(papers).bib.arxiv_id == "2409.19750"


def test_a_filename_containing_an_identifier_is_not_treated_as_one(
    papers: Collection, tmp_path: Path
):
    """Answering a mistyped path by silently fetching an unrelated paper of
    that number is the worst failure this path can produce."""
    report = add_literature(
        papers,
        [str(tmp_path / "my-paper-2409.19750.md")],
        arxiv=arxiv_client(),
    )

    assert report.outcomes[0].outcome is Outcome.FAILED
    assert papers.contents().documents == []


# ---------------------------------------------------------------------------
# The surrogate identifier
# ---------------------------------------------------------------------------


def test_the_identifier_is_derived_from_the_paper_rather_than_minted(
    papers: Collection,
):
    """Two machines that fetch the same paper write byte-identical files, so
    git has nothing to resolve."""
    add_literature(papers, ["2409.19750"], arxiv=arxiv_client())

    frontmatter = only(papers)
    assert frontmatter.id == derive_id("arxiv:2409.19750")
    assert frontmatter.id_from == "arxiv:2409.19750"


def test_the_derivation_key_records_the_precedence_that_was_applied(
    papers: Collection,
):
    """A paper with both an arXiv identifier and a DOI derives from the arXiv
    identifier, and says so."""
    bib = "@article{x,\n title={T},\n doi={10.1088/x},\n eprint={2409.19750}\n}\n"
    path = Path(str(papers.root)) / "library.bib"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(bib, encoding="utf-8")

    add_literature(papers, [str(path)], arxiv=arxiv_client())

    assert only(papers).id_from == "arxiv:2409.19750"


# ---------------------------------------------------------------------------
# Bibliographic identity as duplicate detection
# ---------------------------------------------------------------------------


def test_the_same_paper_by_two_routes_produces_one_document(
    papers: Collection, tmp_path: Path
):
    """The two routes derive different citekeys and share no source checksum,
    so neither the natural key nor the content digest catches the duplicate.
    Its bibliographic identity does, and nothing else can."""
    bib = tmp_path / "library.bib"
    bib.write_text(
        "@article{welman2024,\n title={A Paper},\n eprint={2409.19750}\n}\n",
        encoding="utf-8",
    )

    add_literature(papers, ["2409.19750"], arxiv=arxiv_client())
    second = add_literature(papers, [str(bib)], arxiv=arxiv_client())

    assert len(papers.contents().documents) == 1
    assert second.outcomes[0].outcome is Outcome.UNCHANGED


def test_the_duplicate_is_found_by_doi_too(papers: Collection, tmp_path: Path):
    first = tmp_path / "a.bib"
    first.write_text(
        "@article{a,\n title={A Paper},\n doi={10.1088/0004-637X/1}\n}\n",
        encoding="utf-8",
    )
    second = tmp_path / "b.bib"
    second.write_text(
        "@article{b,\n title={Same Paper},\n doi={10.1088/0004-637X/1}\n}\n",
        encoding="utf-8",
    )

    add_literature(papers, [str(first)], arxiv=no_preprint_client())
    report = add_literature(papers, [str(second)], arxiv=no_preprint_client())

    assert report.outcomes[0].outcome is Outcome.UNCHANGED
    assert len(papers.contents().documents) == 1


def test_identity_matching_ignores_case(papers: Collection, tmp_path: Path):
    first = tmp_path / "a.bib"
    first.write_text(
        "@article{a,\n title={A},\n doi={10.1088/ABC}\n}\n", encoding="utf-8"
    )
    second = tmp_path / "b.bib"
    second.write_text(
        "@article{b,\n title={B},\n doi={10.1088/abc}\n}\n", encoding="utf-8"
    )

    add_literature(papers, [str(first)], arxiv=no_preprint_client())
    report = add_literature(papers, [str(second)], arxiv=no_preprint_client())

    assert report.outcomes[0].outcome is Outcome.UNCHANGED


# ---------------------------------------------------------------------------
# Citekeys
# ---------------------------------------------------------------------------


def test_a_bib_entry_keeps_its_own_citekey(papers: Collection, tmp_path: Path):
    """That key is what the user's own bibliography already cites; deriving a
    new one would break every reference in their writing."""
    bib = tmp_path / "library.bib"
    bib.write_text(
        "@article{smirnovRevisiting2011,\n"
        "  title={Revisiting the Measurement Equation},\n"
        "  author={Smirnov, Oleg},\n"
        "  year={2011},\n"
        "  eprint={1101.1764}\n}\n",
        encoding="utf-8",
    )

    add_literature(papers, [str(bib)], arxiv=arxiv_client())

    assert only(papers).bib.citekey == "smirnovRevisiting2011"


def test_a_citekey_is_derived_only_when_the_paper_arrived_without_one(
    papers: Collection,
):
    add_literature(papers, ["2409.19750"], arxiv=arxiv_client())

    assert only(papers).bib.citekey == "welmanPaperAboutCalibration2024"


def test_two_papers_that_would_share_a_citekey_are_disambiguated(
    papers: Collection, tmp_path: Path
):
    bib = tmp_path / "library.bib"
    bib.write_text(
        "@article{shared,\n title={A},\n doi={10.1088/a}\n}\n"
        "@article{shared,\n title={B},\n doi={10.1088/b}\n}\n",
        encoding="utf-8",
    )

    add_literature(
        papers,
        [str(bib)],
        AddOptions(request_delay_seconds=0),
        arxiv=no_preprint_client(),
    )

    assert citekeys_of(papers) == {"shared", "shareda"}


# ---------------------------------------------------------------------------
# Identity off a front page
# ---------------------------------------------------------------------------


def test_a_local_paper_is_identified_from_its_own_first_page(
    papers: Collection, tmp_path: Path
):
    """A paper's own identifier is absent from the converted markdown, so the
    front page the converter carried out is the only place it exists."""
    path = a_pdf(tmp_path / "paper.pdf")
    converter = FrontPageConverter({"paper.pdf": "arXiv:2409.19750v2 [astro-ph.IM]"})

    report = add_literature(
        papers,
        [str(path)],
        converter=converter,
        arxiv=arxiv_client(),
    )

    assert report.outcomes[0].outcome is Outcome.ADDED
    assert only(papers).bib.arxiv_id == "2409.19750"


def test_precedence_decides_between_kinds_and_that_is_not_a_guess(
    papers: Collection, tmp_path: Path
):
    """One arXiv identifier and one DOI is the rule milestone 1 wrote down,
    not a choice this path is making."""
    path = a_pdf(tmp_path / "paper.pdf")
    converter = FrontPageConverter(
        {"paper.pdf": "arXiv:2409.19750 and doi:10.1088/0004-637X/1"}
    )

    add_literature(papers, [str(path)], converter=converter, arxiv=arxiv_client())

    assert only(papers).id_from == "arxiv:2409.19750"


def test_two_candidates_of_one_kind_are_refused_rather_than_guessed_between(
    papers: Collection, tmp_path: Path
):
    """One of them is likely something the paper cites, and no pattern work
    distinguishes them. Picking one would be a guess recorded as a fact."""
    path = a_pdf(tmp_path / "paper.pdf")
    converter = FrontPageConverter(
        {"paper.pdf": "arXiv:2409.19750 builds on arXiv:1101.1764"}
    )

    report = add_literature(
        papers,
        [str(path)],
        converter=converter,
        arxiv=arxiv_client(),
    )

    assert report.outcomes[0].outcome is Outcome.FAILED
    assert "2409.19750" in (report.outcomes[0].reason or "")
    assert "1101.1764" in (report.outcomes[0].reason or "")


def test_an_identifier_supplied_by_hand_settles_an_ambiguous_page(
    papers: Collection, tmp_path: Path
):
    """An answer from a person beats anything the page offered."""
    path = a_pdf(tmp_path / "paper.pdf")
    converter = FrontPageConverter(
        {"paper.pdf": "arXiv:2409.19750 builds on arXiv:1101.1764"}
    )

    add_literature(
        papers,
        [str(path)],
        AddOptions(identifier="2409.19750"),
        converter=converter,
        arxiv=arxiv_client(),
    )

    assert only(papers).bib.arxiv_id == "2409.19750"


# ---------------------------------------------------------------------------
# Refusal
# ---------------------------------------------------------------------------


def test_a_paper_with_no_establishable_identity_is_refused(
    papers: Collection, tmp_path: Path
):
    """An invented citekey cites nothing, and duplicate detection has nothing
    to compare, so the same paper reached by another route lands twice."""
    path = a_pdf(tmp_path / "paper.pdf")

    report = add_literature(
        papers,
        [str(path)],
        converter=FrontPageConverter(),
        arxiv=arxiv_client(),
    )

    assert report.outcomes[0].outcome is Outcome.FAILED
    assert papers.contents().documents == []


def test_the_refusal_names_both_ways_forward(papers: Collection, tmp_path: Path):
    """Notes is a real answer here, not a consolation prize: notes have no
    natural key by design, so a document with no bibliographic identity is
    exactly what that collection is for."""
    path = a_pdf(tmp_path / "paper.pdf")

    report = add_literature(
        papers,
        [str(path)],
        converter=FrontPageConverter(),
        arxiv=arxiv_client(),
    )
    reason = report.outcomes[0].reason or ""

    assert "--identifier" in reason
    assert "corpus add -n" in reason
    assert str(path) in reason


def test_a_refusal_costs_only_its_own_document(papers: Collection, tmp_path: Path):
    good = a_pdf(tmp_path / "good.pdf", b"%PDF good\n")
    nameless = a_pdf(tmp_path / "nameless.pdf", b"%PDF nameless\n")
    converter = FrontPageConverter({"good.pdf": "arXiv:2409.19750"})

    report = add_literature(
        papers,
        [str(good), str(nameless)],
        AddOptions(request_delay_seconds=0),
        converter=converter,
        arxiv=arxiv_client(),
    )

    outcomes = {outcome.identifier: outcome.outcome for outcome in report.outcomes}
    assert outcomes[str(good)] is Outcome.ADDED
    assert outcomes[str(nameless)] is Outcome.FAILED
    assert len(papers.contents().documents) == 1


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


def test_a_bib_file_expands_into_one_outcome_per_entry(
    papers: Collection, tmp_path: Path
):
    bib = tmp_path / "library.bib"
    bib.write_text(
        "@article{a,\n title={A},\n doi={10.1088/a}\n}\n"
        "@article{b,\n title={B},\n doi={10.1088/b}\n}\n",
        encoding="utf-8",
    )

    report = add_literature(
        papers,
        [str(bib)],
        AddOptions(request_delay_seconds=0),
        arxiv=no_preprint_client(),
    )

    assert len(report.outcomes) == 2
    assert report.counts == {Outcome.ADDED: 2}


def test_the_event_stream_reports_each_paper(papers: Collection, tmp_path: Path):
    recorder = Recorder()

    add_literature(papers, ["2409.19750"], arxiv=arxiv_client(), events=recorder)

    assert recorder.outcomes() == {"2409.19750": Outcome.ADDED}


def test_adding_no_papers_is_not_an_error(papers: Collection):
    report = add_literature(papers, [], arxiv=arxiv_client())

    assert report.outcomes == []


# ---------------------------------------------------------------------------
# Fetching the paper's text
# ---------------------------------------------------------------------------

LATEXML = """<html><body><article class="ltx_document">
<h1>A Paper About Calibration</h1>
<p>The full text of the paper.</p>
</article></body></html>
"""


def fetching_client(body: str = ATOM, html: str = LATEXML) -> httpx.Client:
    """An arXiv that answers both the Atom query and the HTML rendering."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "/html/" in str(request.url):
            return httpx.Response(200, text=html, headers={"content-type": "text/html"})
        return httpx.Response(
            200, text=body, headers={"content-type": "application/atom+xml"}
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_a_paper_named_only_by_an_identifier_gets_its_text(papers: Collection):
    """What closes the stub: the bibliography alone makes a citekey citeable,
    but nothing can be searched until there is a body."""
    add_literature(papers, ["2409.19750"], arxiv=fetching_client())

    document = papers.contents().documents[0]
    assert "The full text of the paper." in document.body
    assert "has not been fetched" not in document.body


def test_a_paper_arxiv_will_not_render_still_lands_as_a_stub(papers: Collection):
    """The identifier and the bibliography are the parts that prevent a second
    copy; refusing the whole add over a missing rendering loses more."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "/html/" in str(request.url):
            return httpx.Response(404)
        return httpx.Response(200, text=ATOM)

    add_literature(
        papers,
        ["2409.19750"],
        arxiv=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    document = papers.contents().documents[0]
    assert "The text of this paper has not been fetched." in document.body


def test_fetching_can_be_turned_off(papers: Collection):
    add_literature(
        papers,
        ["2409.19750"],
        AddOptions(fetch=False),
        arxiv=fetching_client(),
    )

    assert "has not been fetched" in papers.contents().documents[0].body


def test_a_paper_with_only_a_doi_is_not_fetched_from_arxiv(papers: Collection):
    """There is nothing to fetch: a DOI names a publisher's copy, which needs
    a browser session kennis does not have."""
    bib = Path(str(papers.root)).parent / "library.bib"
    bib.parent.mkdir(parents=True, exist_ok=True)
    bib.write_text(
        "@article{smith2020,\n title={A Title Here},\n doi={10.1093/mnras/xyz}\n}\n",
        encoding="utf-8",
    )

    add_literature(papers, [str(bib)], arxiv=no_preprint_client())

    assert "has not been fetched" in papers.contents().documents[0].body


def test_the_papers_of_one_batch_are_spaced(
    papers: Collection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """arXiv answers a burst with 406, and every call here degrades to None on
    that, so without spacing a bibliography lands as a pile of stubs and says
    nothing about why."""
    slept: list[float] = []
    monkeypatch.setattr(
        "kennis.engine.corpus.add.time.sleep", lambda seconds: slept.append(seconds)
    )
    bib = tmp_path / "library.bib"
    bib.write_text(
        "@article{one,\n title={A},\n doi={10.1088/a}\n}\n"
        "@article{two,\n title={B},\n doi={10.1088/b}\n}\n",
        encoding="utf-8",
    )

    add_literature(
        papers,
        [str(bib)],
        AddOptions(request_delay_seconds=2.5),
        arxiv=no_preprint_client(),
    )

    assert slept == [2.5]


def test_the_interval_between_papers_is_the_users_to_set(
    papers: Collection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """How patient to be with someone else's server is a judgement kennis
    should not make on the user's behalf, so the default is a default rather
    than a constant."""
    slept: list[float] = []
    monkeypatch.setattr(
        "kennis.engine.corpus.add.time.sleep", lambda seconds: slept.append(seconds)
    )
    bib = tmp_path / "library.bib"
    bib.write_text(
        "@article{one,\n title={A},\n doi={10.1088/a}\n}\n"
        "@article{two,\n title={B},\n doi={10.1088/b}\n}\n",
        encoding="utf-8",
    )

    add_literature(
        papers,
        [str(bib)],
        AddOptions(request_delay_seconds=0),
        arxiv=no_preprint_client(),
    )

    assert slept == []


def test_a_paper_added_without_its_text_says_why(papers: Collection):
    """A throttled batch and a batch of papers nobody preprinted write the
    same stubs. The outcome is what tells them apart."""

    def refusing(request: httpx.Request) -> httpx.Response:
        if "/html/" in str(request.url):
            return httpx.Response(406)
        return httpx.Response(
            200, text=ATOM, headers={"content-type": "application/atom+xml"}
        )

    report = add_literature(
        papers,
        ["2409.19750"],
        AddOptions(request_delay_seconds=0),
        arxiv=httpx.Client(transport=httpx.MockTransport(refusing)),
    )

    outcome = report.outcomes[0]
    assert outcome.outcome is Outcome.ADDED
    assert outcome.reason is not None
    assert "406" in outcome.reason


def test_a_paper_with_its_text_reports_no_complaint(papers: Collection):
    report = add_literature(
        papers,
        ["2409.19750"],
        AddOptions(request_delay_seconds=0),
        arxiv=fetching_client(),
    )

    assert report.outcomes[0].reason is None
