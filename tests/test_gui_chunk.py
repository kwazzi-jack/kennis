"""A hit takes the reader to its chunk, and the chunk is marked.

The link a hit carries is the point of this unit: a search says the
match is in chunk 3 of a nineteen-page paper, and before this the
reader was handed the top of the paper and left to find it by eye.

Three things are asserted here that are easy to get wrong in ways
that still look right:

- **The offsets belong to the index, not the document.** If the
  document changed after it was indexed they address text that has
  moved, and a mark on the wrong paragraph is worse than no mark,
  because it is a confident claim. The mark is withheld and the
  reason is said.
- **An absent mark looks identical whatever caused it.** So every
  test of the guard asserts both halves - present when the index is
  current, absent when it is not - or it would pass for a marking
  that never worked at all.
- **A chunk the reader asks for by hand may not exist.** The number
  arrives in a query string, so it can be anything.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.context import existing_corpus
from kennis.engine.context.index import load_bundle_index
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.layout import index_root
from kennis.engine.errors import DocumentNotFound
from kennis.engine.rag.index import load_index
from kennis.gui.app import build_app
from kennis.gui.pages import shown_bundle_document
from kennis.gui.words import MARK_WITHHELD

TOKEN = "a-test-token"

# Long enough to be several chunks at the real chunk size
# (`ChunkParameters.size` is 1500 characters), so that the passage a
# hit points at is genuinely not the top of the document. `a_long_note`
# asserts the note really did chunk - a one-chunk document would make
# every test below pass against `chunk=0` and prove nothing.
_WORDS = [
    "gains",
    "delays",
    "bandpass",
    "pointing",
    "flagging",
    "weights",
    "baselines",
    "polarisation",
    "deconvolution",
    "selfcal",
    "fringes",
    "sidelobes",
]

_PARAGRAPHS = [
    f"Paragraph {number} discusses the {word} of the array in considerable "
    f"detail, at sufficient length that the packer treats it as a block of "
    f"its own and the document as a whole runs to several chunks rather "
    f"than one. It says little of substance, because what is under test is "
    f"where the passage sits and not what it says about {word}."
    for number, word in enumerate(_WORDS)
]


@pytest.fixture
def client() -> TestClient:
    return TestClient(build_app(TOKEN), follow_redirects=False)


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    run = CliRunner()
    assert run.invoke(main, ["corpus", "init"]).exit_code == 0
    return tmp_path


def a_long_note(tmp_path: Path, name: str) -> str:
    """A note of several paragraphs, added and indexed."""
    run = CliRunner()
    source = tmp_path / "sources" / f"{name}.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        f"# {name}\n\n" + "\n\n".join(_PARAGRAPHS) + "\n", encoding="utf-8"
    )
    assert run.invoke(main, ["corpus", "add", "-n", str(source)]).exit_code == 0
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0
    held = Collection(root=existing_corpus().corpus_root, name="notes").contents()
    identifier = next(d.id for d in held.documents if d.frontmatter.title == name)

    # The sample has to chunk, or every assertion about chunk 1 below
    # would be an assertion about a chunk that does not exist, and
    # "no mark" would pass for the wrong reason.
    index = load_index(index_root(existing_corpus().corpus_root), "notes")
    chunks = [c for c in index.chunks if c.document_id == identifier]
    assert len(chunks) > 2, f"the sample must chunk; it produced {len(chunks)}"
    return identifier


def admitted(app_client: TestClient) -> TestClient:
    assert app_client.get("/", params={"token": TOKEN}).status_code == 200
    return app_client


def document_path(tmp_path: Path, identifier: str) -> Path:
    held = Collection(root=existing_corpus().corpus_root, name="notes").contents()
    return next(d.md_path for d in held.documents if d.id == identifier)


# ---------------------------------------------------------------------------
# The link
# ---------------------------------------------------------------------------


def test_a_hit_links_to_its_chunk_and_not_just_its_document(
    corpus: Path, client: TestClient
):
    """The whole point of the unit, asserted on the link itself."""
    identifier = a_long_note(corpus, "calibration")
    admitted(client)

    found = client.get("/hits", params={"q": "bandpass", "scope": "notes"})

    assert f"/document/notes/{identifier}?chunk=" in found.text
    assert "#chunk-" in found.text


def test_the_link_names_the_chunk_the_hit_reported(corpus: Path, client: TestClient):
    """Not merely *a* chunk: the one the search matched. A link that
    always said `chunk=0` would satisfy the test above."""
    a_long_note(corpus, "calibration")
    admitted(client)

    found = client.get("/hits", params={"q": "flagging", "scope": "notes"})

    # The detail line states the chunk, in the same words `kennis
    # search` prints; the link must agree with it. Matched separately
    # rather than by splitting on "chunk=", which the href now also
    # contains - the first version of this test read its own answer
    # out of the thing it was checking.
    reported = re.search(r"chunk=(\d+)</p>|chunk=(\d+)\s", found.text)
    assert reported is not None, "the detail line must state the chunk"
    number = reported.group(1) or reported.group(2)
    assert int(number) > 0, "the match must not be in the first chunk"
    assert f"?chunk={number}#chunk-{number}" in found.text


# ---------------------------------------------------------------------------
# The mark
# ---------------------------------------------------------------------------


def test_the_named_chunk_is_marked_in_the_document(corpus: Path, client: TestClient):
    identifier = a_long_note(corpus, "calibration")
    admitted(client)

    page = client.get(f"/document/notes/{identifier}", params={"chunk": "1"})

    assert page.status_code == 200
    assert 'id="chunk-1"' in page.text
    assert 'class="chunk"' in page.text


def test_a_document_asked_for_without_a_chunk_is_not_marked(
    corpus: Path, client: TestClient
):
    """Opening a document from the collection listing marks nothing:
    there is no passage to point at."""
    identifier = a_long_note(corpus, "calibration")
    admitted(client)

    page = client.get(f"/document/notes/{identifier}")

    assert page.status_code == 200
    assert 'class="chunk"' not in page.text


def test_the_marked_passage_is_the_chunk_and_not_the_first_block(
    corpus: Path, client: TestClient
):
    """A mark that always landed on the opening paragraph would pass
    every test above. This one fails unless the offsets are used."""
    identifier = a_long_note(corpus, "calibration")
    admitted(client)

    page = client.get(f"/document/notes/{identifier}", params={"chunk": "1"})
    marked = page.text[page.text.index('id="chunk-1"') :].partition("</div>")[0]

    assert "Paragraph 0" not in marked
    assert any(f"Paragraph {number}" in marked for number in range(1, 6))


# ---------------------------------------------------------------------------
# The staleness guard
# ---------------------------------------------------------------------------


def test_a_stale_index_withholds_the_mark_and_says_why(
    corpus: Path, client: TestClient
):
    """The offsets are the index's. Once the document has changed they
    address text that has moved, and marking anyway would state
    something false about where the passage is."""
    identifier = a_long_note(corpus, "calibration")
    admitted(client)

    current = client.get(f"/document/notes/{identifier}", params={"chunk": "1"})
    assert 'class="chunk"' in current.text, "the mark must work before it is withheld"

    path = document_path(corpus, identifier)
    path.write_text(
        path.read_text(encoding="utf-8").replace("Paragraph 0", "Rewritten opening"),
        encoding="utf-8",
    )

    after = client.get(f"/document/notes/{identifier}", params={"chunk": "1"})

    assert 'class="chunk"' not in after.text
    assert MARK_WITHHELD in after.text


def test_a_stale_index_still_renders_the_document(corpus: Path, client: TestClient):
    """Only the mark is withheld. The document is perfectly readable
    and replacing it with an error would be a worse answer than the
    one thing kennis cannot currently place."""
    identifier = a_long_note(corpus, "calibration")
    admitted(client)
    path = document_path(corpus, identifier)
    path.write_text(
        path.read_text(encoding="utf-8").replace("Paragraph 0", "Rewritten opening"),
        encoding="utf-8",
    )

    page = client.get(f"/document/notes/{identifier}", params={"chunk": "1"})

    assert page.status_code == 200
    assert "Rewritten opening" in page.text
    assert "Paragraph 3" in page.text


# ---------------------------------------------------------------------------
# What arrives in a query string can be anything
# ---------------------------------------------------------------------------


def test_a_chunk_that_is_not_a_number_is_ignored(corpus: Path, client: TestClient):
    identifier = a_long_note(corpus, "calibration")
    admitted(client)

    page = client.get(f"/document/notes/{identifier}", params={"chunk": "third"})

    assert page.status_code == 200
    assert 'class="chunk"' not in page.text


def test_a_chunk_past_the_end_is_ignored(corpus: Path, client: TestClient):
    """Not an error page: the document is there and readable, and the
    reader asked for a passage of it that does not exist."""
    identifier = a_long_note(corpus, "calibration")
    admitted(client)

    page = client.get(f"/document/notes/{identifier}", params={"chunk": "999"})

    assert page.status_code == 200
    assert 'class="chunk"' not in page.text
    assert "Paragraph 3" in page.text


def test_a_document_in_a_collection_with_no_index_is_still_readable(
    corpus: Path, client: TestClient
):
    """A chunk cannot be looked up without an index, and a document
    can be read without one - `shown_document` reads the corpus, not
    the index. The absent index must not cost the reader the page."""
    run = CliRunner()
    source = corpus / "sources" / "unindexed.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("# unindexed\n\nSome text.\n", encoding="utf-8")
    assert run.invoke(main, ["corpus", "add", "-n", str(source)]).exit_code == 0
    held = Collection(root=existing_corpus().corpus_root, name="notes").contents()
    identifier = next(
        d.id for d in held.documents if d.frontmatter.title == "unindexed"
    )
    admitted(client)

    page = client.get(f"/document/notes/{identifier}", params={"chunk": "0"})

    assert page.status_code == 200
    assert "Some text." in page.text


# ---------------------------------------------------------------------------
# The fourth scope
# ---------------------------------------------------------------------------
#
# A context hit is a hit in a document that is not in the corpus: the
# bundle lives in the user's own repository. Before this unit every
# hit was linked as `/document/{collection}/{id}`, so a context hit
# led to "unknown collection 'context'" and a 404 - one scope in four
# answering a search with an error page. Found by running the
# interface against a real bundle rather than by the suite, which is
# the sixth consecutive unit that has happened in. Concern #332.


@pytest.fixture
def bundle(corpus: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project with a bundle, standing in it."""
    workspace = corpus / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    run = CliRunner()
    assert run.invoke(main, ["context", "init"]).exit_code == 0
    assert (
        run.invoke(
            main,
            ["remember", "--context", "--title", "Solver", "\n\n".join(_PARAGRAPHS)],
        ).exit_code
        == 0
    )
    assert run.invoke(main, ["context", "index"]).exit_code == 0
    return workspace / ".context"


def test_a_context_hit_links_to_a_page_that_exists(bundle: Path, client: TestClient):
    """The defect this section exists for, asserted on the status code
    rather than on the shape of the link: a link that is well formed
    and 404s is the thing that was shipped."""
    admitted(client)

    found = client.get("/hits", params={"q": "bandpass", "scope": "context"})
    links = re.findall(r'href="(/[^"]*)"', found.text)
    readable = [link for link in links if "bundle" in link or "document" in link]
    assert readable, "a context hit must link somewhere"

    page = client.get(readable[0].replace("&amp;", "&"))

    assert page.status_code == 200
    assert "Paragraph" in page.text


def test_a_context_hit_marks_its_chunk_too(bundle: Path, client: TestClient):
    """The same feature for the fourth scope, not a lesser version of
    it: a bundle note long enough to chunk has the same problem a
    paper does."""
    admitted(client)

    found = client.get("/hits", params={"q": "bandpass", "scope": "context"})
    links = re.findall(r'href="(/bundle/[^"]*)"', found.text)
    assert links, "a context hit must link into the bundle"

    page = client.get(links[0].replace("&amp;", "&"))

    assert 'class="chunk"' in page.text
    assert "Paragraph" in page.text


def test_a_bundle_path_cannot_walk_out_of_the_bundle(bundle: Path, client: TestClient):
    """The route takes a path from the address bar, and the bundle
    sits inside the user's repository. A traversal would serve any
    file the process can read to anything that reached the port.

    Checked against the documents the bundle actually holds rather
    than by normalising the path, because a membership test has no
    encoding to be fooled by."""
    admitted(client)

    for attempt in (
        "/bundle/../../../etc/passwd",
        "/bundle/..%2f..%2f..%2fetc%2fpasswd",
        "/bundle/LANDING.md/../../.git/config",
    ):
        page = client.get(attempt)
        assert page.status_code != 200 or "root:" not in page.text, attempt


def test_a_bundle_document_that_is_not_there_is_refused(
    bundle: Path, client: TestClient
):
    admitted(client)

    page = client.get("/bundle/no-such-note.md")

    assert page.status_code != 200 or "no such document" in page.text.lower()


def test_a_corpus_hit_still_links_into_the_corpus(corpus: Path, client: TestClient):
    """The fix must not send corpus documents through the bundle
    route: they are different stores with different readers."""
    identifier = a_long_note(corpus, "calibration")
    admitted(client)

    found = client.get("/hits", params={"q": "bandpass", "scope": "notes"})

    assert f"/document/notes/{identifier}" in found.text
    assert "/bundle/" not in found.text


def test_the_bundle_mark_is_the_chunk_and_not_the_header(
    bundle: Path, client: TestClient
):
    """The bundle index records its offsets against the note's *body*,
    with the frontmatter already split off. Rendering the whole file
    puts every offset out by the length of that header.

    **Compared against the chunk the index holds, not against a word
    in it.** The first version of this test asserted that a search
    term appeared inside the mark, and passed under exactly the
    defect it was written for: the header is about one paragraph
    long, the chunk spans about five, so a one-paragraph shift left
    the word inside. What distinguishes a correct mark from a shifted
    one is where it *begins*."""
    admitted(client)

    found = client.get("/hits", params={"q": "deconvolution", "scope": "context"})
    links = re.findall(r'href="(/bundle/[^"]*)"', found.text)
    assert links, "a context hit must link into the bundle"
    link = links[0].replace("&amp;", "&")
    asked = re.search(r"chunk=(\d+)", link)
    assert asked is not None
    number = int(asked.group(1))

    index = load_bundle_index(bundle)
    chunk = next(c for c in index.chunks if c.chunk_index == number)
    assert chunk.text.strip(), "the sample chunk must have text"

    page = client.get(link)
    marked = page.text[page.text.index(f'id="chunk-{number}"') :]
    marked = marked.partition(">")[2].partition("</div>")[0]
    inside = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", marked)).split())

    # Where the mark *begins*, not what it contains. Rendering the
    # whole file puts the frontmatter inside the mark and leaves the
    # chunk's own text further down, so a containment check passes
    # under exactly the defect this exists to catch - it did, twice.
    # The leading `#` goes because a heading's marker is consumed by
    # the `<h1>` and never reaches the text.
    opening = next(line for line in chunk.text.splitlines() if line.strip())
    opening = " ".join(opening.lstrip("#").split())
    assert inside.startswith(opening), (
        f"the mark must begin at the chunk; it begins {inside[:80]!r}"
    )


def test_the_bundle_reader_refuses_a_path_outside_the_bundle(bundle: Path):
    """The guard, reached directly rather than over HTTP.

    Starlette normalises `..` out of a request path before a route
    sees it, so no HTTP test can exercise this: every traversal
    answers 404 whether the check is there or not. That makes the
    check defence in depth, and defence in depth still has to be
    tested, or it is only a comment. Called as a function, which is
    also how a future front end would call it. Concern #333."""
    outside = bundle.parent / "secret.txt"
    outside.write_text("root:x:0:0:SECRET\n", encoding="utf-8")

    with pytest.raises(DocumentNotFound):
        shown_bundle_document(bundle, "../secret.txt", load_remote_images=False)


def test_a_stale_bundle_index_withholds_the_mark_and_says_why(
    bundle: Path, client: TestClient
):
    """The bundle's half of the staleness guard.

    Asserted in both directions for the reason the corpus one is: an
    absent mark looks the same whatever caused it, so a test of the
    withholding alone would pass for a marking that never worked."""
    admitted(client)

    found = client.get("/hits", params={"q": "deconvolution", "scope": "context"})
    link = re.findall(r'href="(/bundle/[^"]*)"', found.text)[0].replace("&amp;", "&")
    assert 'class="chunk"' in client.get(link).text, "the mark must work first"

    note = next(
        path for path in bundle.rglob("*.md") if "Paragraph 0" in path.read_text()
    )
    note.write_text(
        note.read_text(encoding="utf-8").replace("Paragraph 0", "Rewritten"),
        encoding="utf-8",
    )

    after = client.get(link)

    assert 'class="chunk"' not in after.text
    assert MARK_WITHHELD in after.text
