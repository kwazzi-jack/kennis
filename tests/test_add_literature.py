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
from kennis.engine.events import Diagnostic, Outcome, Recorder, Severity

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


LATEXML = """<html><body><article class="ltx_document">
<h1>A Paper About Calibration</h1>
<p>The full text of the paper.</p>
</article></body></html>
"""


EMPTY_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>
"""


def arxiv_client(body: str = ATOM, html: str = LATEXML) -> httpx.Client:
    """An arXiv that answers the metadata query and renders the paper.

    It serves both because a literature document is now its text or it is not
    written: a client that answered the Atom query and refused the rendering
    would refuse every add, and every test of citekeys, frontmatter and
    duplicates would be testing the refusal instead of what it was written
    for.

    The two responses differ, so this still answers only the question it is
    asked - one body for every request would hand an Atom feed to the HTML
    converter, which is a different test from the one the caller wrote.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if "/html/" in str(request.url):
            return httpx.Response(200, text=html, headers={"content-type": "text/html"})
        return httpx.Response(
            200, text=body, headers={"content-type": "application/atom+xml"}
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def unrenderable_client(body: str = ATOM) -> httpx.Client:
    """An arXiv that knows the paper and will not render it."""

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


XOVA_HTML = """<html><body><article class="ltx_document">
<h1>Xova: Baseline-Dependent Averaging</h1>
<p>The full text of the paper.</p>
</article></body></html>
"""


def unreachable_arxiv(html: str = XOVA_HTML) -> httpx.Client:
    """An arXiv that renders the paper and refuses the metadata query.

    406 with an empty body, which is what arXiv really answered for a few
    minutes on 2026-09-23 while a paper was being added. The rendering still
    works, because that is the case that matters: the document is written,
    and everything the metadata would have supplied is missing.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if "/html/" in str(request.url):
            return httpx.Response(200, text=html, headers={"content-type": "text/html"})
        return httpx.Response(406)

    return httpx.Client(transport=httpx.MockTransport(handler))


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


def bib_with_documents(tmp_path: Path, **entries: str) -> Path:
    """A bibliography whose every entry names a document that exists.

    The shape a bibliography now has to have: an entry with no `file =` field
    and no eprint has no text, and a bibliography containing one is refused
    whole.
    """
    lines: list[str] = []
    for citekey, doi in entries.items():
        document = tmp_path / f"{citekey}-document.md"
        document.write_text(
            f"# {citekey}\n\nThe text of {citekey}.\n", encoding="utf-8"
        )
        lines.append(
            f"@article{{{citekey},\n title={{{citekey}}},\n doi={{{doi}}},\n"
            f" file={{{document}}}\n}}\n"
        )
    path = tmp_path / "library.bib"
    path.write_text("".join(lines), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# A paper named by its identifier
# ---------------------------------------------------------------------------
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


def test_a_paper_is_stored_as_title_authors_year(papers: Collection):
    """What a directory listing of papers is scanned by. Concern #190."""
    add_literature(papers, ["2409.19750"], arxiv=arxiv_client())

    stored = [path.name for path in papers.path.rglob("*.md")]

    assert stored == ["A Paper About Calibration - Welman - 2024.md"]


def test_a_paper_is_refused_when_arxiv_cannot_be_reached(papers: Collection):
    """An arXiv identifier's only source of text is arXiv, so an unreachable
    arXiv means no document. This used to land a stub, on the argument that
    holding the identifier prevents a second copy later - but a corpus of
    literature that holds no literature is not a smaller loss than an empty
    one, it is a misleading one."""

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    report = add_literature(
        papers,
        ["2409.19750"],
        arxiv=httpx.Client(transport=httpx.MockTransport(unreachable)),
    )

    assert report.outcomes[0].outcome is Outcome.FAILED
    assert papers.contents().documents == []


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
    document = tmp_path / "paper.md"
    document.write_text("# A Paper\n\nOne paper's text.\n", encoding="utf-8")
    first = tmp_path / "a.bib"
    first.write_text(
        f"@article{{a,\n title={{A Paper}},\n doi={{10.1088/0004-637X/1}},\n"
        f" file={{{document}}}\n}}\n",
        encoding="utf-8",
    )
    # A different document, so the duplicate is caught by identity rather
    # than by the checksum - which is the whole point of this test.
    other = tmp_path / "other.md"
    other.write_text("# Same Paper\n\nA different scan of it.\n", encoding="utf-8")
    second = tmp_path / "b.bib"
    second.write_text(
        f"@article{{b,\n title={{Same Paper}},\n doi={{10.1088/0004-637X/1}},\n"
        f" file={{{other}}}\n}}\n",
        encoding="utf-8",
    )

    add_literature(papers, [str(first)], arxiv=no_preprint_client())
    report = add_literature(papers, [str(second)], arxiv=no_preprint_client())

    assert report.outcomes[0].outcome is Outcome.UNCHANGED
    assert len(papers.contents().documents) == 1


def test_identity_matching_ignores_case(papers: Collection, tmp_path: Path):
    one = tmp_path / "one.md"
    one.write_text("# A\n\nThe paper.\n", encoding="utf-8")
    other = tmp_path / "other.md"
    other.write_text("# B\n\nA different scan of it.\n", encoding="utf-8")
    first = tmp_path / "a.bib"
    first.write_text(
        f"@article{{a,\n title={{A}},\n doi={{10.1088/ABC}},\n file={{{one}}}\n}}\n",
        encoding="utf-8",
    )
    second = tmp_path / "b.bib"
    second.write_text(
        f"@article{{b,\n title={{B}},\n doi={{10.1088/abc}},\n file={{{other}}}\n}}\n",
        encoding="utf-8",
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
    bib = bib_with_documents(tmp_path, shared="10.1088/a", shared_again="10.1088/b")
    # Two entries with the *same* citekey, which the helper cannot express
    # because it keys on it. Written out so both are literally `shared`.
    bib.write_text(
        bib.read_text(encoding="utf-8").replace("shared_again,", "shared,"),
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
    bib = bib_with_documents(tmp_path, a="10.1088/a", b="10.1088/b")

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


def test_a_paper_named_only_by_an_identifier_gets_its_text(papers: Collection):
    """What closes the stub: the bibliography alone makes a citekey citeable,
    but nothing can be searched until there is a body."""
    add_literature(papers, ["2409.19750"], arxiv=arxiv_client())

    document = papers.contents().documents[0]
    assert "The full text of the paper." in document.body
    assert "has not been fetched" not in document.body


def test_a_paper_arxiv_will_not_render_is_refused_not_stubbed(papers: Collection):
    """A literature document is a paper's text or it is not written.

    The stub this replaces was indexed like any other document, so its
    bibliography competed in search results with real papers and could
    outrank one on a title match - and the reader then believes they have the
    paper.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if "/html/" in str(request.url):
            return httpx.Response(404)
        return httpx.Response(200, text=ATOM)

    report = add_literature(
        papers,
        ["2409.19750"],
        arxiv=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert papers.contents().documents == []
    assert [outcome.outcome for outcome in report.outcomes] == [Outcome.FAILED]
    assert "rendering" in str(report.outcomes[0].reason)
    assert "supply the document" in str(report.outcomes[0].reason).lower()


def test_a_doi_is_not_answered_with_a_preprint(papers: Collection):
    """kennis used to query arXiv's `doi` field, which holds the *journal*
    DOI authors report - so a published paper was silently answered with its
    preprint, and the stored document differed from the thing asked for.

    The client here would answer with a preprint if it were asked. It must
    not be asked.
    """
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        if "/html/" in str(request.url):
            return httpx.Response(404)
        return httpx.Response(
            200, text=ATOM, headers={"content-type": "application/atom+xml"}
        )

    report = add_literature(
        papers,
        ["10.1093/mnras/stab1234"],
        arxiv=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert not any("doi" in url for url in asked)
    assert [outcome.outcome for outcome in report.outcomes] == [Outcome.FAILED]
    assert papers.contents().documents == []


def test_a_doi_refused_for_no_text_names_the_pdf_and_not_notes(papers: Collection):
    """Two different refusals with two different remedies. No identity means
    `add it as a note`; no text means `supply the document`, because the
    paper's identity was established perfectly well."""
    report = add_literature(
        papers, ["10.1093/mnras/stab1234"], arxiv=no_preprint_client()
    )

    reason = str(report.outcomes[0].reason)
    assert "-n" not in reason
    assert "--identifier" in reason or "supply" in reason.lower()


def test_a_markdown_paper_does_not_need_the_pdf_converter(
    papers: Collection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """`add_literature` used to hand every local path to the converter, so a
    paper already in markdown demanded MinerU and the whole add was refused
    when it was not installed. The notes path had always filtered."""
    monkeypatch.setenv("PATH", str(tmp_path / "nothing-here"))
    document = tmp_path / "paper.md"
    document.write_text("# A Paper\n\nAlready markdown.\n", encoding="utf-8")

    report = add_literature(
        papers,
        [str(document)],
        AddOptions(identifier="10.1093/mnras/stab1234"),
        arxiv=no_preprint_client(),
    )

    assert [outcome.outcome for outcome in report.outcomes] == [Outcome.ADDED]
    assert "Already markdown." in papers.contents().documents[0].body


def test_a_doi_with_the_document_supplied_is_added(papers: Collection, tmp_path: Path):
    """The second user type: their own PDF, identified by its DOI. This is
    the case that has to keep working once auto-resolution is gone."""
    document = tmp_path / "paper.md"
    document.write_text(
        "# A Published Paper\n\nThe real text of the published version.\n",
        encoding="utf-8",
    )

    report = add_literature(
        papers,
        [str(document)],
        AddOptions(identifier="10.1093/mnras/stab1234"),
        arxiv=no_preprint_client(),
    )

    assert [outcome.outcome for outcome in report.outcomes] == [Outcome.ADDED]
    held = papers.contents().documents[0]
    assert "The real text of the published version." in held.body
    assert held.frontmatter.bib.doi == "10.1093/mnras/stab1234"


def test_the_papers_of_one_batch_are_spaced(
    papers: Collection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """arXiv answers a burst with 406, and every call here degrades to None
    on that, so without spacing a bibliography of preprints would be refused
    wholesale for a reason that is nothing to do with the bibliography."""
    slept: list[float] = []
    monkeypatch.setattr(
        "kennis.engine.corpus.add.time.sleep", lambda seconds: slept.append(seconds)
    )
    bib = bib_with_documents(tmp_path, one="10.1088/a", two="10.1088/b")

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
    """A throttled batch and a batch of papers nobody preprinted fail
    identically. The reason is what tells them apart."""

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
    assert outcome.outcome is Outcome.FAILED
    assert outcome.reason is not None
    # Still the distinction the old stub could not make: a throttled batch
    # and a batch of papers nobody preprinted now fail identically unless the
    # reason says which.
    assert "406" in outcome.reason


def test_a_paper_with_its_text_reports_no_complaint(papers: Collection):
    report = add_literature(
        papers,
        ["2409.19750"],
        AddOptions(request_delay_seconds=0),
        arxiv=arxiv_client(),
    )

    assert report.outcomes[0].reason is None


# ---------------------------------------------------------------------------
# A bibliography is a unit
# ---------------------------------------------------------------------------


def a_bibliography(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "library.bib"
    path.write_text(body, encoding="utf-8")
    return path


def test_a_bibliography_whose_entries_all_have_documents_is_added(
    papers: Collection, tmp_path: Path
):
    first = tmp_path / "first.md"
    first.write_text("# First\n\nThe first paper.\n", encoding="utf-8")
    second = tmp_path / "second.md"
    second.write_text("# Second\n\nThe second paper.\n", encoding="utf-8")

    bib = a_bibliography(
        tmp_path,
        f"@article{{one,\n title={{First}},\n doi={{10.1088/aaa}},\n"
        f" file={{{first}}}\n}}\n"
        f"@article{{two,\n title={{Second}},\n doi={{10.1088/bbb}},\n"
        f" file={{{second}}}\n}}\n",
    )

    report = add_literature(papers, [str(bib)], arxiv=no_preprint_client())

    assert [outcome.outcome for outcome in report.outcomes] == [
        Outcome.ADDED,
        Outcome.ADDED,
    ]
    assert len(papers.contents().documents) == 2


def test_one_entry_without_a_document_refuses_the_whole_bibliography(
    papers: Collection, tmp_path: Path
):
    """The bibliography is one artifact the user wrote, and a `file =` field
    is where its documents are named. Writing half of it would leave them
    reconciling what landed against what they asked for."""
    present = tmp_path / "present.md"
    present.write_text("# Present\n\nThis one has its text.\n", encoding="utf-8")

    bib = a_bibliography(
        tmp_path,
        f"@article{{one,\n title={{Present}},\n doi={{10.1088/aaa}},\n"
        f" file={{{present}}}\n}}\n"
        f"@article{{two,\n title={{Absent}},\n doi={{10.1088/bbb}}\n}}\n",
    )

    report = add_literature(papers, [str(bib)], arxiv=no_preprint_client())

    assert papers.contents().documents == []
    assert all(outcome.outcome is Outcome.FAILED for outcome in report.outcomes), (
        report.outcomes
    )


def test_the_refusal_names_every_entry_that_cannot_work(
    papers: Collection, tmp_path: Path
):
    """Naming one of them would have the user fix it and meet the next."""
    bib = a_bibliography(
        tmp_path,
        "@article{one,\n title={A},\n doi={10.1088/aaa}\n}\n"
        "@article{two,\n title={B},\n doi={10.1088/bbb}\n}\n",
    )

    report = add_literature(papers, [str(bib)], arxiv=no_preprint_client())

    reported = " ".join(str(outcome.reason) for outcome in report.outcomes)
    assert "one" in reported and "two" in reported


def test_an_entry_with_an_arxiv_identifier_needs_no_file(
    papers: Collection, tmp_path: Path
):
    """An arXiv identifier is a source of text, so a bibliography of
    preprints works with no `file =` field anywhere in it."""
    bib = a_bibliography(
        tmp_path,
        "@article{one,\n title={A Paper About Calibration},\n eprint={2409.19750}\n}\n",
    )

    report = add_literature(papers, [str(bib)], arxiv=arxiv_client())

    assert [outcome.outcome for outcome in report.outcomes] == [Outcome.ADDED]
    assert "The full text of the paper." in papers.contents().documents[0].body


def test_a_fetch_that_fails_at_runtime_does_not_retract_the_batch(
    papers: Collection, tmp_path: Path
):
    """The static check refuses a bibliography that *cannot* work. arXiv
    throttling is not a property of the bibliography, and rolling back
    written documents to honour it would be a transaction the corpus has no
    other use for."""
    supplied = tmp_path / "supplied.md"
    supplied.write_text("# Supplied\n\nIts own text.\n", encoding="utf-8")

    bib = a_bibliography(
        tmp_path,
        f"@article{{one,\n title={{Supplied}},\n doi={{10.1088/aaa}},\n"
        f" file={{{supplied}}}\n}}\n"
        f"@article{{two,\n title={{Throttled}},\n eprint={{2409.19750}}\n}}\n",
    )

    # Every arXiv request refused, which is what a 406 burst looks like.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(406)

    report = add_literature(
        papers,
        [str(bib)],
        arxiv=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    outcomes = {outcome.outcome for outcome in report.outcomes}
    assert Outcome.ADDED in outcomes and Outcome.FAILED in outcomes
    assert len(papers.contents().documents) == 1


# ---------------------------------------------------------------------------
# When arXiv cannot be reached
# ---------------------------------------------------------------------------


def test_a_paper_is_titled_from_its_own_heading_when_arxiv_is_unreachable(
    papers: Collection,
):
    """**The defect first real use left in Brian's corpus.**

    His stored paper reads `title: arXiv:2101.11270` and
    `citekey: paperArxiv`, while its body begins `# Xova: Baseline-Dependent
    Time and Channel Averaging for Radio Interferometry`. arXiv answered 406
    for a few minutes, `lookup_arxiv_metadata` degraded to None as designed,
    and the title chain - `options.title or identity.title or
    converted.suggested_title or paper.identifier` - fell all the way to the
    end.

    It should have stopped one step earlier. The arXiv-fetched `Converted`
    was the one construction site in the codebase that never set
    `suggested_title`, so the correct title was in the first line of the very
    markdown being written and was thrown away.

    The document is permanent: re-running the add reports it as a duplicate
    by identity and never retries the lookup.
    """
    client = unreachable_arxiv()

    report = add_literature(
        papers, ["arXiv:2101.11270"], AddOptions(), client=client, arxiv=client
    )

    assert [outcome.outcome for outcome in report.outcomes] == [Outcome.ADDED]
    document = papers.resolve(report.outcomes[0].document_id or "")
    assert document.frontmatter.title == "Xova: Baseline-Dependent Averaging"


def test_a_paper_whose_text_has_no_heading_still_falls_back_to_its_identifier(
    papers: Collection,
):
    """The end of the chain is still there for a paper whose markdown opens
    with no `#` line at all."""
    client = unreachable_arxiv(
        html="<html><body><article class='ltx_document'>"
        "<p>No heading here, just prose.</p></article></body></html>"
    )

    report = add_literature(
        papers, ["arXiv:2101.11270"], AddOptions(), client=client, arxiv=client
    )

    document = papers.resolve(report.outcomes[0].document_id or "")
    assert document.frontmatter.title == "arXiv:2101.11270"


def test_a_failed_metadata_lookup_is_reported(papers: Collection):
    """A degraded add that says nothing gives the reader no reason to look,
    and what it wrote cannot be repaired by running the command again."""
    events = Recorder()
    client = unreachable_arxiv()

    add_literature(
        papers,
        ["arXiv:2101.11270"],
        AddOptions(),
        client=client,
        arxiv=client,
        events=events,
    )

    warnings = [
        event.message
        for event in events.events
        if isinstance(event, Diagnostic) and event.severity is Severity.WARNING
    ]
    assert any("2101.11270" in message for message in warnings), warnings
    assert any("citekey" in message or "metadata" in message for message in warnings)


def test_metadata_that_arrives_is_not_warned_about(papers: Collection):
    """The control: the ordinary case says nothing extra."""
    events = Recorder()

    add_literature(
        papers,
        ["arXiv:2101.11270"],
        AddOptions(),
        client=arxiv_client(),
        arxiv=arxiv_client(),
        events=events,
    )

    assert not [
        event
        for event in events.events
        if isinstance(event, Diagnostic) and event.severity is Severity.WARNING
    ]
