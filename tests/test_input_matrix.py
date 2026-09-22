"""Every kind of argument kennis accepts, in every collection that takes it.

The table in `design/rules.md` is what this file checks. Written as a matrix
rather than as isolated cases because the questions worth answering are about
*combinations* - a URL behaves one way in notes and another in literature is
exactly the kind of thing no single-path test notices.

Nothing here touches the network: every URL is answered by a mock transport
whose content type is the variable under test.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from kennis.engine.corpus.add import AddOptions, add_literature, add_notes
from kennis.engine.corpus.collection import Collection
from kennis.engine.events import Outcome

PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n%%EOF\n"
HTML_PAGE = (
    "<html><head><title>A Page</title></head><body><p>Body text.</p></body></html>"
)
MARKDOWN_PAGE = "# A Markdown Page\n\nIts body.\n"


@pytest.fixture
def notes(tmp_path: Path) -> Collection:
    return Collection(root=tmp_path / "corpus", name="notes")


@pytest.fixture
def papers(tmp_path: Path) -> Collection:
    return Collection(root=tmp_path / "corpus", name="literature")


def serving(content: bytes | str, content_type: str) -> httpx.Client:
    """A server answering every request with one body and one content type."""

    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(content, bytes):
            return httpx.Response(
                200, content=content, headers={"content-type": content_type}
            )
        return httpx.Response(200, text=content, headers={"content-type": content_type})

    return httpx.Client(transport=httpx.MockTransport(handler))


def a_file(tmp_path: Path, name: str, body: str = "# A File\n\nIts body.\n") -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def only(collection: Collection) -> object:
    documents = collection.contents().documents
    assert len(documents) == 1, documents
    return documents[0]


# ---------------------------------------------------------------------------
# A URL, by what the server actually sends
# ---------------------------------------------------------------------------


def test_a_url_serving_html_is_converted_as_html(notes: Collection):
    report = add_notes(
        notes,
        ["https://example.com/page"],
        client=serving(HTML_PAGE, "text/html; charset=utf-8"),
    )

    assert [outcome.outcome for outcome in report.outcomes] == [Outcome.ADDED]
    held = only(notes)
    assert "Body text." in held.body
    assert held.frontmatter.source.via == "html"


def test_a_url_serving_markdown_is_taken_verbatim(notes: Collection):
    """Running an HTML converter over markdown strips nothing and mangles
    what it does not understand."""
    report = add_notes(
        notes,
        ["https://example.com/readme"],
        client=serving(MARKDOWN_PAGE, "text/markdown"),
    )

    assert [outcome.outcome for outcome in report.outcomes] == [Outcome.ADDED]
    held = only(notes)
    assert "# A Markdown Page" in held.body
    assert held.frontmatter.source.via == "verbatim"


def test_a_url_serving_a_pdf_reaches_the_pdf_converter(
    notes: Collection, fake_mineru: Path
):
    """The defect this file was written to catch. `convert_url` ran
    `convert_html` over `response.text` whatever arrived, so a URL answering
    with a PDF stored `%PDF-1.4 ...` as the document body, labelled
    `via: html`, and indexed it.

    Asserted against a fake converter rather than against a failure, because
    "it failed" is satisfied by several wrong behaviours and "it was
    converted as a PDF" is satisfied by only the right one.
    """
    report = add_notes(
        notes,
        ["https://example.com/paper.pdf"],
        client=serving(PDF_BYTES, "application/pdf"),
    )

    assert [outcome.outcome for outcome in report.outcomes] == [Outcome.ADDED]
    held = only(notes)
    assert held.frontmatter.source.via == "mineru"
    assert held.frontmatter.source.format == "pdf"
    assert "%PDF" not in held.body
    # The URL, not the temporary file it was downloaded to, which is what
    # says whether the document could ever be fetched again.
    assert held.frontmatter.source.origin == "url:https://example.com/paper.pdf"


def test_a_server_that_will_not_commit_to_a_type_is_sniffed(
    notes: Collection, fake_mineru: Path
):
    """`application/octet-stream` for a PDF is common enough that trusting
    the header alone would send real PDFs to the HTML converter."""
    report = add_notes(
        notes,
        ["https://example.com/download"],
        client=serving(PDF_BYTES, "application/octet-stream"),
    )

    assert [outcome.outcome for outcome in report.outcomes] == [Outcome.ADDED]
    assert only(notes).frontmatter.source.via == "mineru"


def test_a_served_pdf_without_the_converter_says_which_converter(
    notes: Collection, no_mineru: None
):
    """It must fail as a conversion problem, naming the tool, rather than as
    an unrecognised content type - the two have different remedies."""
    report = add_notes(
        notes,
        ["https://example.com/paper.pdf"],
        client=serving(PDF_BYTES, "application/pdf"),
    )

    assert [outcome.outcome for outcome in report.outcomes] == [Outcome.FAILED]
    assert "mineru" in str(report.outcomes[0].reason).lower()
    assert notes.contents().documents == []


def test_the_suffix_does_not_decide_a_url(notes: Collection):
    """A URL ending `.pdf` that answers with an HTML paywall page is the
    common case, not the exotic one. Only the server knows."""
    report = add_notes(
        notes,
        ["https://example.com/paper.pdf"],
        client=serving(HTML_PAGE, "text/html"),
    )

    assert [outcome.outcome for outcome in report.outcomes] == [Outcome.ADDED]
    assert only(notes).frontmatter.source.via == "html"


def test_a_url_serving_something_unconvertible_is_refused(notes: Collection):
    report = add_notes(
        notes,
        ["https://example.com/archive.zip"],
        client=serving(b"PK\x03\x04", "application/zip"),
    )

    assert [outcome.outcome for outcome in report.outcomes] == [Outcome.FAILED]
    assert "zip" in str(report.outcomes[0].reason).lower()


# ---------------------------------------------------------------------------
# The same URL, in literature
# ---------------------------------------------------------------------------


def test_literature_accepts_a_url_with_an_identifier(papers: Collection):
    """A URL is a document, not an identity, so it needs `--identifier` -
    the same rule a local PDF already follows. What it must not do is refuse
    the URL for being a URL."""
    report = add_literature(
        papers,
        ["https://example.com/paper"],
        AddOptions(identifier="10.1093/mnras/stab1234", request_delay_seconds=0),
        client=serving(HTML_PAGE, "text/html"),
    )

    assert [outcome.outcome for outcome in report.outcomes] == [Outcome.ADDED]
    held = only(papers)
    assert "Body text." in held.body
    assert held.frontmatter.bib.doi == "10.1093/mnras/stab1234"


def test_literature_refuses_a_url_with_no_identity(papers: Collection):
    """Not for being a URL - for being unidentified, which is the same
    refusal a local PDF with no front-page identifier gets."""
    report = add_literature(
        papers,
        ["https://example.com/paper"],
        AddOptions(request_delay_seconds=0),
        client=serving(HTML_PAGE, "text/html"),
    )

    assert [outcome.outcome for outcome in report.outcomes] == [Outcome.FAILED]
    reason = str(report.outcomes[0].reason)
    assert "identity" in reason or "identifier" in reason
    assert "not an existing file" not in reason


# ---------------------------------------------------------------------------
# Local files, by kind
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "via"),
    [
        ("note.md", "verbatim"),
        ("note.txt", "verbatim"),
        ("page.html", "html"),
        ("script.py", "verbatim"),
    ],
)
def test_a_local_text_file_needs_no_converter(
    notes: Collection, tmp_path: Path, name: str, via: str
):
    """None of these is binary, so none of them may reach MinerU: a machine
    without it must still be able to add a note."""
    report = add_notes(notes, [str(a_file(tmp_path, name))])

    assert [outcome.outcome for outcome in report.outcomes] == [Outcome.ADDED]
    assert only(notes).frontmatter.source.via == via


def test_an_unknown_suffix_named_explicitly_is_accepted(
    notes: Collection, tmp_path: Path
):
    """`detect_format` answers `code` for anything it does not know, which is
    right when a user named one file and vouched for it. A directory walk
    uses the accept-list instead."""
    report = add_notes(notes, [str(a_file(tmp_path, "notes.myformat"))])

    assert [outcome.outcome for outcome in report.outcomes] == [Outcome.ADDED]


def test_a_directory_walk_skips_what_it_does_not_recognise(
    notes: Collection, tmp_path: Path
):
    directory = tmp_path / "mixed"
    a_file(directory, "kept.md")
    (directory / "skipped.bin").write_bytes(b"\x00\x01\x02")

    report = add_notes(notes, [str(directory)])

    # Reported, not silently dropped: a walk that quietly ignored a file
    # would have the user believe it was indexed.
    assert report.counts == {Outcome.SKIPPED: 1, Outcome.ADDED: 1}
    # The source path, not the title: the helper's body starts with a
    # heading, so every document it writes is titled after that heading
    # rather than after its filename.
    assert "kept.md" in str(only(notes).frontmatter.source.origin)


def test_a_missing_path_that_is_not_an_identifier_is_refused(notes: Collection):
    report = add_notes(notes, ["/no/such/file.md"])

    assert [outcome.outcome for outcome in report.outcomes] == [Outcome.FAILED]


# ---------------------------------------------------------------------------
# The same local kinds, in literature and docs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "via"),
    [("paper.md", "verbatim"), ("paper.html", "html"), ("paper.txt", "verbatim")],
)
def test_literature_takes_the_same_local_kinds_as_notes(
    papers: Collection, tmp_path: Path, name: str, via: str
):
    """The table in `rules.md` says every local kind is accepted by every
    collection. Literature adds an identity requirement on top, and nothing
    else."""
    report = add_literature(
        papers,
        [str(a_file(tmp_path, name))],
        AddOptions(identifier="10.1093/mnras/stab1234", request_delay_seconds=0),
    )

    assert [outcome.outcome for outcome in report.outcomes] == [Outcome.ADDED]
    assert only(papers).frontmatter.source.via == via


def test_literature_takes_a_directory(papers: Collection, tmp_path: Path):
    """One identifier cannot name two papers, so a directory of several is a
    duplicate-identity refusal rather than a walk that was not allowed."""
    directory = tmp_path / "papers"
    a_file(directory, "one.md")

    report = add_literature(
        papers,
        [str(directory)],
        AddOptions(identifier="10.1093/mnras/stab1234", request_delay_seconds=0),
    )

    assert [outcome.outcome for outcome in report.outcomes] == [Outcome.ADDED]


def test_docs_takes_a_local_file_filed_into_a_project(
    tmp_path: Path,
):
    """Source and collection are independent: a hand-written tutorial belongs
    in a docs project as readily as a crawled page does."""
    from kennis.engine.corpus.add import add_docs

    pages = Collection(root=tmp_path / "corpus", name="docs")
    report = add_docs(
        pages,
        [str(a_file(tmp_path, "tutorial.md"))],
        AddOptions(project="numpy", request_delay_seconds=0),
    )

    assert [outcome.outcome for outcome in report.outcomes] == [Outcome.ADDED]
    held = only(pages)
    assert held.frontmatter.docs.project == "numpy"


def test_a_shell_pattern_expands_to_one_document_each(
    notes: Collection, tmp_path: Path
):
    # Different bodies, or the second is a checksum duplicate of the first
    # and the test would be measuring deduplication instead of expansion.
    a_file(tmp_path, "first.md", "# First\n\nThe first body.\n")
    a_file(tmp_path, "second.md", "# Second\n\nThe second body.\n")

    report = add_notes(notes, [str(tmp_path / "*.md")])

    assert report.counts == {Outcome.ADDED: 2}
