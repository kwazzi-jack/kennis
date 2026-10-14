"""What an add would do, said before it is done (unit 11d).

The preview is a promise about the add, so the tests that matter compare
the two: the citekey proposed is the citekey written, a paper reported as
held is the paper the add reports as a duplicate, and a refusal foreseen
is the refusal the add raises. And it fetches only what the add itself
would fetch, only once the input is recognised - typing an identifier
must not send each keystroke to arXiv.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from kennis.engine.corpus.add import add_literature
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.preview import (
    LineCheck,
    check_lines,
    preview_paper,
    preview_site,
)
from kennis.engine.corpus.schema import LiteratureFrontmatter
from kennis.engine.refusals import NoPublisherText, SamePaper

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


class Recording:
    """An arXiv that answers, and remembers every request it was sent."""

    def __init__(self) -> None:
        self.requests: list[str] = []

    def client(self) -> httpx.Client:
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(str(request.url))
            if "/html/" in str(request.url):
                return httpx.Response(
                    200, text=LATEXML, headers={"content-type": "text/html"}
                )
            # The entry names the paper asked for, as arXiv's does: kennis
            # refuses an entry for some other paper.
            asked = request.url.params.get("id_list") or "2409.19750"
            return httpx.Response(
                200,
                text=ATOM.replace("2409.19750", asked),
                headers={"content-type": "application/atom+xml"},
            )

        return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def papers(tmp_path: Path) -> Collection:
    return Collection(root=tmp_path / "corpus", name="literature")


@pytest.fixture
def arxiv() -> Recording:
    return Recording()


# ---------------------------------------------------------------------------
# A paper
# ---------------------------------------------------------------------------


def test_an_arxiv_identifier_is_previewed_with_what_arxiv_says(
    papers: Collection, arxiv: Recording
):
    preview = preview_paper(papers, "2409.19750", client=arxiv.client())

    assert preview.recognised is not None
    assert preview.recognised.kind == "arxiv"
    assert preview.title == "A Paper About Calibration"
    assert preview.authors == "Brian Welman"
    assert preview.year == "2024"
    # Written by hand: the key `derive_citekey` makes of these.
    assert preview.citekey == "welmanPaperAboutCalibration2024"
    assert preview.refusal is None


def test_the_citekey_proposed_is_the_citekey_written(
    papers: Collection, arxiv: Recording
):
    """Two papers that derive the same base: the preview has to take the
    held one into account exactly as the add does."""
    add_literature(papers, ["2409.19750"], arxiv=arxiv.client())

    preview = preview_paper(papers, "2409.19751", client=arxiv.client())
    add_literature(papers, ["2409.19751"], arxiv=arxiv.client())

    written = {
        document.frontmatter.bib.citekey
        for document in papers.contents().documents
        if isinstance(document.frontmatter, LiteratureFrontmatter)
        and document.frontmatter.bib.arxiv_id == "2409.19751"
    }
    assert preview.citekey is not None
    assert written == {preview.citekey}
    assert preview.citekey != "welmanPaperAboutCalibration2024"


def test_a_citekey_given_is_the_one_proposed(papers: Collection, arxiv: Recording):
    preview = preview_paper(
        papers, "2409.19750", citekey="mine2024", client=arxiv.client()
    )

    assert preview.citekey == "mine2024"


def test_a_paper_already_held_is_said_before_the_add(
    papers: Collection, arxiv: Recording
):
    """And without asking arXiv: the identity is held locally, and a
    request for a paper already in hand tells a third party nothing it
    needs to know."""
    report = add_literature(papers, ["2409.19750"], arxiv=arxiv.client())
    held = report.outcomes[0].document_id
    arxiv.requests.clear()

    preview = preview_paper(papers, "arXiv:2409.19750", client=arxiv.client())

    assert preview.refusal == SamePaper(document_id=str(held))
    assert preview.held_title == "A Paper About Calibration"
    assert arxiv.requests == []


@pytest.mark.parametrize(
    ("asked", "kind"),
    [("10.1093/mnras/stab1234", "doi"), ("2021MNRAS.501.1234W", "bibcode")],
)
def test_a_doi_or_bibcode_alone_is_refused_ahead_and_not_looked_up(
    papers: Collection, arxiv: Recording, asked: str, kind: str
):
    """The add records a DOI as given and refuses one with no text, because
    arXiv's `doi` field is the journal's and resolving through it stored the
    preprint of what was asked for. The preview promises the same."""
    preview = preview_paper(papers, asked, client=arxiv.client())

    assert preview.recognised is not None
    assert preview.recognised.kind == kind
    assert isinstance(preview.refusal, NoPublisherText)
    assert preview.refusal.kind == kind
    assert arxiv.requests == []


@pytest.mark.parametrize("typed", ["2409", "2409.1", "10.10", "arXiv:", "calibration"])
def test_nothing_is_fetched_until_the_input_is_recognised(
    papers: Collection, arxiv: Recording, typed: str
):
    preview = preview_paper(papers, typed, client=arxiv.client())

    assert preview.recognised is None
    assert arxiv.requests == []


def test_a_local_file_is_named_as_one_and_not_fetched(
    papers: Collection, arxiv: Recording, tmp_path: Path
):
    document = tmp_path / "paper.pdf"
    document.write_bytes(b"%PDF-1.7\n")

    preview = preview_paper(papers, str(document), client=arxiv.client())

    assert preview.recognised is None
    assert preview.is_file
    assert arxiv.requests == []


def test_an_unreachable_arxiv_leaves_the_identifier_recognised(papers: Collection):
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    preview = preview_paper(
        papers,
        "2409.19750",
        client=httpx.Client(transport=httpx.MockTransport(unreachable)),
    )

    assert preview.recognised is not None
    assert preview.title is None
    assert preview.looked_up


# ---------------------------------------------------------------------------
# A site
# ---------------------------------------------------------------------------


def test_a_site_names_its_project_without_a_request():
    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"fetched {request.url}")

    preview = preview_site(
        "https://stimela.readthedocs.io/en/latest/",
        client=httpx.Client(transport=httpx.MockTransport(refuse)),
    )

    assert preview.project == "stimela"
    assert preview.discovery is None


def test_a_project_given_wins():
    preview = preview_site("https://stimela.readthedocs.io/", project="cab")

    assert preview.project == "cab"


def test_the_site_is_probed_only_when_asked():
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        if request.url.path.endswith("objects.inv"):
            return httpx.Response(404)
        if request.url.path.endswith("robots.txt"):
            return httpx.Response(404)
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    preview = preview_site("https://docs.example.org/", probe=True, client=client)

    assert asked
    assert preview.discovery == "crawl"


def test_a_site_address_kennis_cannot_name_is_said():
    preview = preview_site("not a url")

    assert preview.project is None


# ---------------------------------------------------------------------------
# Several lines, checked locally
# ---------------------------------------------------------------------------


def test_each_line_says_what_it_is(papers: Collection, tmp_path: Path):
    folder = tmp_path / "pdfs"
    folder.mkdir()
    document = tmp_path / "one.pdf"
    document.write_bytes(b"%PDF-1.7\n")

    checks = check_lines(
        papers,
        [
            "2409.19750",
            "10.1093/mnras/stab1234",
            "https://example.org/paper.pdf",
            str(document),
            str(folder),
            str(tmp_path / "missing.pdf"),
            "",
        ],
    )

    assert [check.kind for check in checks] == [
        "arxiv",
        "doi",
        "address",
        "file",
        "folder",
        "nothing",
    ]


def test_a_held_line_is_marked_without_a_request(papers: Collection, arxiv: Recording):
    add_literature(papers, ["2409.19750"], arxiv=arxiv.client())

    checks = check_lines(papers, ["2409.19750", "2409.19751"])

    assert [check.held is not None for check in checks] == [True, False]
    assert all(isinstance(check, LineCheck) for check in checks)
