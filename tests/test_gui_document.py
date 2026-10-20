"""An opened document as the mockup draws it (#447).

A bar of breadcrumbs above the text, a byline under the title, and an
inspector beside the column with three disclosures: what the
frontmatter says, where the reader's words occur, and the headings.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup, Tag
from click.testing import CliRunner
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.context import existing_corpus
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.layout import index_root
from kennis.engine.corpus.schema import DocsFrontmatter, LiteratureFrontmatter
from kennis.engine.rag.index import load_index
from kennis.engine.rag.models import Chunk
from kennis.gui import words
from kennis.gui.app import build_app
from kennis.gui.pages import byline_of, document_details, shown_matches, state_in
from kennis.holdings import DocumentMarks
from kennis.retrieval import chunk_range, document_chunks

TOKEN = "a-test-token"

_WORDS = ["gains", "delays", "bandpass", "pointing", "flagging", "weights"]

# Two sections, each long enough to be several chunks at the real chunk
# size, so that the matches are a proper subset of the chunks.
_BODY = "\n\n".join(
    [
        "## Solving",
        *(
            f"Paragraph {number} discusses the {word} of the array in "
            "considerable detail, at sufficient length that the packer treats "
            "it as a block of its own and the document runs to several chunks "
            f"rather than one, saying little of substance about {word}."
            for number, word in enumerate(_WORDS)
        ),
        "## Imaging",
        *(
            f"Paragraph {number} turns to imaging, where the {word} matter "
            "less than the weighting and the deconvolution, and again the "
            "text is long enough to need a chunk of its own in the index."
            for number, word in enumerate(_WORDS, start=len(_WORDS))
        ),
    ]
)


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    return tmp_path


@pytest.fixture
def client(corpus: Path) -> TestClient:
    opened = TestClient(build_app(TOKEN), follow_redirects=False)
    assert opened.get("/", params={"token": TOKEN}).status_code == 200
    return opened


def a_note(corpus: Path, *, index: bool = True) -> str:
    source = corpus / "sources" / "Calibration.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(f"# Calibration\n\n{_BODY}\n", encoding="utf-8")
    run = CliRunner()
    added = run.invoke(main, ["corpus", "add", "-n", "--group", "radio", str(source)])
    assert added.exit_code == 0, added.output
    if index:
        assert run.invoke(main, ["corpus", "index"]).exit_code == 0
    held = Collection(root=existing_corpus().corpus_root, name="notes").contents()
    return next(d.id for d in held.documents if d.frontmatter.title == "Calibration")


def page_of(client: TestClient, identifier: str, **params: str) -> BeautifulSoup:
    answer = client.get(f"/document/notes/{identifier}", params=params)
    assert answer.status_code == 200, answer.text
    return BeautifulSoup(answer.text, "html.parser")


def found(soup: BeautifulSoup | Tag, selector: str) -> Tag:
    element = soup.select_one(selector)
    assert isinstance(element, Tag), selector
    return element


def text_of(element: Tag) -> str:
    return " ".join(element.get_text(" ").split())


# ---------------------------------------------------------------------------
# The bar
# ---------------------------------------------------------------------------


def test_the_bar_leads_back_to_the_search_the_collection_and_names_the_document(
    corpus: Path, client: TestClient
):
    identifier = a_note(corpus)

    bar = found(page_of(client, identifier, q="bandpass", chunk="1"), ".doc-bar")
    links = {text_of(link): str(link["href"]) for link in bar.select(".crumbs a")}

    assert "q=bandpass" in links[words.search_crumb("bandpass")]
    assert links["notes"] == "/collection/notes"
    assert "radio" in text_of(found(bar, ".crumbs"))
    # The title, which the reader recognises; the handle in its tooltip.
    here = found(bar, ".crumbs .here")
    assert here["title"] == identifier
    assert text_of(here) == text_of(found(page_of(client, identifier), "article h1"))


def test_without_a_search_the_bar_offers_no_way_back_to_one(
    corpus: Path, client: TestClient
):
    identifier = a_note(corpus)

    bar = found(page_of(client, identifier), ".doc-bar")

    assert "q=" not in str(bar)


def test_the_inspector_is_open_unless_the_reader_closed_it(
    corpus: Path, client: TestClient
):
    """A cookie the server draws onto `<html>`, as the pane's is, so the
    first paint is already right."""
    identifier = a_note(corpus)

    opened = page_of(client, identifier)
    client.cookies.set("inspector", "closed")
    closed = page_of(client, identifier)
    client.cookies.set("inspector", "nonsense")
    unknown = page_of(client, identifier)

    assert found(opened, "html")["data-inspector"] == "open"
    assert found(closed, "html")["data-inspector"] == "closed"
    assert found(unknown, "html")["data-inspector"] == "open"
    toggle = found(opened, "#inspector-toggle")
    assert toggle["aria-controls"] == "inspector"
    assert toggle["data-show"] == words.INSPECTOR_SHOW
    assert toggle["data-hide"] == words.INSPECTOR_HIDE


def test_the_inspector_script_composes_no_words():
    script = (
        Path(__file__).resolve().parents[1] / "src/kennis/gui/static/inspector.js"
    ).read_text(encoding="utf-8")
    code = "\n".join(
        line for line in script.splitlines() if not line.strip().startswith("//")
    )

    assert "inspector=" in code and "samesite=strict" in code
    assert not re.search(r'"[A-Z][a-z]+ [a-z]', code), "a sentence in the script"


# ---------------------------------------------------------------------------
# Details
# ---------------------------------------------------------------------------


def details_in(soup: BeautifulSoup) -> dict[str, str]:
    listing = found(soup, ".inspector .details dl")
    terms = [text_of(term) for term in listing.find_all("dt")]
    values = [text_of(value) for value in listing.find_all("dd")]
    return dict(zip(terms, values, strict=True))


def test_a_notes_details_say_where_it_is_and_whether_it_is_searchable(
    corpus: Path, client: TestClient
):
    identifier = a_note(corpus)

    details = details_in(page_of(client, identifier))

    assert details[words.DETAIL_LABELS["collection"]] == "notes"
    assert details[words.DETAIL_LABELS["group"]] == "radio"
    assert details[words.DETAIL_LABELS["id"]] == identifier
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", details[words.DETAIL_LABELS["added"]])
    assert details[words.DETAIL_LABELS["index"]] == words.INDEX_STATES[""]


def test_a_document_added_since_the_index_says_so(corpus: Path, client: TestClient):
    """The tree's own rule: a collection never indexed marks everything
    as not indexed."""
    identifier = a_note(corpus, index=False)

    details = details_in(page_of(client, identifier))

    assert details[words.DETAIL_LABELS["index"]] == words.INDEX_STATES["unindexed"]


PAPER = LiteratureFrontmatter.model_validate(
    {
        "id": "zp7iju8j60",
        "title": "Revisiting the RIME",
        "owner": "user",
        "source": {"from": "arxiv:1101.1764", "via": "html", "format": "html"},
        "bib": {
            "citekey": "smirnov2011a",
            "authors": "O. M. Smirnov",
            "year": "2011",
            "arxiv_id": "1101.1764",
            "doi": "10.1051/0004-6361/201016082",
        },
    }
)


def test_a_paper_is_bylined_by_its_authors_and_year():
    assert byline_of(PAPER) == "O. M. Smirnov, 2011"


def test_a_papers_details_carry_its_citekey_and_identifiers_verbatim():
    shown = {
        detail.label: (detail.value, detail.verbatim)
        for detail in document_details(
            PAPER, collection="literature", group="", state=""
        )
    }

    assert shown[words.DETAIL_LABELS["citekey"]] == ("smirnov2011a", True)
    assert shown[words.DETAIL_LABELS["arxiv"]] == ("1101.1764", True)
    assert shown[words.DETAIL_LABELS["doi"]] == ("10.1051/0004-6361/201016082", True)
    assert shown[words.DETAIL_LABELS["converted"]] == ("html", False)
    assert words.DETAIL_LABELS["group"] not in shown


def a_docs_page(*, version: str | None, release: str | None) -> DocsFrontmatter:
    return DocsFrontmatter.model_validate(
        {
            "id": "abcdefghij",
            "title": "Models",
            "owner": "user",
            "source": {
                "from": "url:https://h.io/2.12/m/",
                "via": "html",
                "format": "html",
            },
            "docs": {
                "project": "pydantic",
                "page": "m",
                "version": version,
                "release": release,
            },
        }
    )


def test_a_docs_page_s_details_say_its_version_and_the_site_s_release():
    """#489: the folder's version, and the site's release when it says more."""
    shown = {
        detail.label: detail.value
        for detail in document_details(
            a_docs_page(version="latest", release="2.2.0rc1"),
            collection="docs",
            group="",
            state="",
        )
    }

    assert shown[words.DETAIL_LABELS["version"]] == "latest"
    assert shown[words.DETAIL_LABELS["release"]] == "2.2.0rc1"


def test_a_release_the_version_already_says_is_not_said_twice():
    shown = [
        detail.label
        for detail in document_details(
            a_docs_page(version="2.12", release="2.12"),
            collection="docs",
            group="",
            state="",
        )
    ]

    assert words.DETAIL_LABELS["release"] not in shown


def test_an_index_that_cannot_be_checked_says_nothing_about_the_document():
    shown = [
        detail.label
        for detail in document_details(
            PAPER, collection="literature", group="", state=None
        )
    ]

    assert words.DETAIL_LABELS["index"] not in shown


def test_an_index_whose_commit_is_gone_cannot_say_a_document_is_searchable(
    tmp_path: Path,
):
    """`DocumentMarks.state_of` answers "" both for "in step" and for
    "cannot be checked", and only the first is searchable."""
    uncheckable = DocumentMarks(never_indexed=False, states=None)
    never = DocumentMarks(never_indexed=True, states=None)
    anchor = tmp_path / "notes" / "a.md"

    assert state_in(uncheckable, tmp_path, anchor) is None
    assert state_in(never, tmp_path, anchor) == "unindexed"


# ---------------------------------------------------------------------------
# Matches
# ---------------------------------------------------------------------------


def test_a_documents_chunks_are_its_own_in_order(corpus: Path):
    identifier = a_note(corpus)

    chunks = document_chunks(existing_corpus(), "notes", identifier, bundle=None)

    assert len(chunks) > 2, "the sample must chunk"
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert {chunk.document_id for chunk in chunks} == {identifier}
    for chunk in chunks:
        assert chunk_range(
            existing_corpus(), "notes", identifier, chunk.chunk_index, bundle=None
        ) == (chunk.char_start, chunk.char_end)


def test_the_matches_are_the_chunks_the_readers_words_occur_in(
    corpus: Path, client: TestClient
):
    identifier = a_note(corpus)
    index = load_index(index_root(existing_corpus().corpus_root), "notes")
    expected = sorted(
        chunk.chunk_index
        for chunk in index.chunks
        if chunk.document_id == identifier and re.search(r"\bimaging\b", chunk.text)
    )
    assert (
        0
        < len(expected)
        < len([chunk for chunk in index.chunks if chunk.document_id == identifier])
    ), "the fixture no longer exercises a proper subset"

    soup = page_of(client, identifier, q="imaging")
    matches = found(soup, ".inspector .matches")
    links = matches.select("a")

    assert words.matches_heading("imaging") in text_of(matches)
    shown: list[int] = []
    for link in links:
        href = str(link["href"])
        chunk = re.search(r"chunk=(\d+)", href)
        assert chunk, href
        shown.append(int(chunk.group(1)))
        assert href.endswith(f"#chunk-{chunk.group(1)}")
        assert "q=imaging" in href
        assert text_of(link) in ("Solving", "Imaging")
    assert shown == expected


def a_chunk(index: int, section: str | None, text: str = "imaging here") -> Chunk:
    return Chunk(
        id=f"doc::{index}",
        collection="notes",
        document_id="doc",
        chunk_index=index,
        text=text,
        source_path="notes/doc.md",
        char_start=index * 10,
        char_end=index * 10 + 9,
        section=section,
    )


def test_matches_in_one_section_are_told_apart():
    """A long section matches in several chunks, and four links all
    reading "Introduction" cannot be told apart."""
    chunks = [
        a_chunk(0, None),
        a_chunk(1, "Method"),
        a_chunk(2, "Results"),
        a_chunk(3, "Results", text="nothing to see"),
        a_chunk(4, "Results"),
        a_chunk(5, "Results"),
    ]

    shown = shown_matches(
        chunks, question="imaging", collection="notes", document_id="doc"
    )

    assert [match.label for match in shown] == [
        words.passage_label(0),
        "Method",
        words.match_in_section("Results", 1, 3),
        words.match_in_section("Results", 2, 3),
        words.match_in_section("Results", 3, 3),
    ]


def test_the_readers_words_are_marked_in_the_document(corpus: Path, client: TestClient):
    """As the mockup draws it, and as an opened passage already marks
    them, by the same rule."""
    identifier = a_note(corpus)

    article = found(page_of(client, identifier, q="imaging"), "article")

    marks = [text_of(mark).casefold() for mark in article.find_all("mark")]
    assert marks and set(marks) == {"imaging"}
    assert page_of(client, identifier).find("mark") is None


def test_a_changed_document_lists_no_matches(corpus: Path, client: TestClient):
    """A chunk of a changed document addresses text that has moved, the
    reason a stale index withholds the mark."""
    identifier = a_note(corpus)
    held = Collection(root=existing_corpus().corpus_root, name="notes").contents()
    path = next(d.md_path for d in held.documents if d.id == identifier)
    path.write_text(
        path.read_text(encoding="utf-8") + "\nA late paragraph on imaging.\n",
        encoding="utf-8",
    )

    soup = page_of(client, identifier, q="imaging")

    assert soup.select(".inspector .matches a") == []


def test_without_a_search_there_is_no_matches_section(corpus: Path, client: TestClient):
    identifier = a_note(corpus)

    assert page_of(client, identifier).select(".inspector .matches") == []


# ---------------------------------------------------------------------------
# Outline
# ---------------------------------------------------------------------------


def test_the_outline_links_each_heading_on_the_page(corpus: Path, client: TestClient):
    identifier = a_note(corpus)

    soup = page_of(client, identifier)
    links = found(soup, ".inspector .outline").select("a")

    assert [text_of(link) for link in links] == ["Solving", "Imaging"]
    for link in links:
        target = str(link["href"]).removeprefix("#")
        heading = soup.find(id=target)
        assert isinstance(heading, Tag) and heading.name in ("h2", "h3")
        assert text_of(heading) == text_of(link)


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


def test_the_text_scrolls_and_the_bar_and_inspector_stay(
    corpus: Path, client: TestClient
):
    identifier = a_note(corpus)

    soup = page_of(client, identifier)
    css = client.get("/static/kennis.css").text

    assert "document" in (found(soup, "main").get("class") or [])
    assert found(soup, "main > .doc-bar") is not None
    reading = found(soup, "main .reading")
    assert reading.select_one("article") is not None
    # `clip`, not `hidden`: a fragment link may still scroll an element
    # whose overflow is hidden, and following one to a chunk scrolled
    # the bar out of sight.
    assert re.search(r"main\.document\s*\{[^}]*overflow: clip", css)
    assert re.search(r"\.reading\s*\{[^}]*overflow-y: auto", css)
    assert re.search(r"\.inspector\s*\{[^}]*overflow-y: auto", css)


def test_the_marked_chunk_wears_the_highlighter(client: TestClient):
    """The mockup's mark: the wash and the amber rule, which is also the
    colour of an opened passage, so "here" is one colour everywhere."""
    css = client.get("/static/kennis.css").text
    rule = re.search(r"\.chunk\s*\{([^}]*)\}", css)

    assert rule, css
    assert "var(--mark)" in rule.group(1)
    assert "role-hint" not in rule.group(1)


def test_a_paper_s_identifiers_lead_to_where_anyone_can_look_them_up():
    """arXiv and the DOI were plain text in the inspector, and the citekey
    - the thing typed into a paper - had no way to the clipboard."""
    from kennis.engine.corpus.schema import LiteratureFrontmatter
    from kennis.gui.pages import document_details

    frontmatter = LiteratureFrontmatter.model_validate(
        {
            "id": "zyxwvutsrq",
            "title": "A paper",
            "owner": "user",
            "id_from": "arxiv:1101.1764",
            "source": {
                "from": "arxiv:1101.1764",
                "via": "arxiv-html",
                "format": "html",
            },
            "bib": {
                "citekey": "welman2024",
                "arxiv_id": "1101.1764",
                "doi": "10.1088/0004-637X/1",
            },
        }
    )

    rows = {
        row.value: row
        for row in document_details(
            frontmatter, collection="literature", group="", state=None
        )
    }

    assert rows["1101.1764"].href == "https://arxiv.org/abs/1101.1764"
    assert rows["10.1088/0004-637X/1"].href == "https://doi.org/10.1088/0004-637X/1"
    assert rows["welman2024"].copyable
    assert not rows["arxiv:1101.1764"].href
