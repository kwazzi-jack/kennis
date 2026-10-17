"""The declarations a fetch resolves: papers and documentation projects.

Milestone 7 unit 7c. A pack's `corpus.literature` and `corpus.docs` are
not content the store holds, so they are not copied - they are resolved
by fetching. The same table as the notes, with the digest taken of the
**declaration's own fields** rather than of any bytes, because there are
no bytes until something is fetched.

Nothing here reaches a host: every client is an `httpx.MockTransport`.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import httpx
import pytest

from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.document import Document
from kennis.engine.corpus.schema import Bibliography
from kennis.engine.corpus.sync import (
    OPERATION,
    CorpusSync,
    bibliography_key,
    literature_key,
    sync_corpus,
)
from kennis.engine.errors import DocumentInvalid
from kennis.engine.events import Event, OperationFinished, Progress
from kennis.engine.history.repository import initialise_corpus
from kennis.engine.pack.schema import LiteratureEntry
from kennis.engine.pack.store import install_pack
from kennis.engine.pack.update import update_pack
from kennis.render.packs import describe_why_unfetched

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

# A Sphinx site, the same shape `test_add_docs.py` serves: the search
# index is what discovery reads to learn which pages exist, so a site
# without one is crawled as a single page and the test would be about
# the fallback rather than about the declaration.
BASE_URL = "https://docs.example/en/latest/"
SEARCHINDEX = (
    'Search.setIndex({"docnames": ["index", "guide/install"], "filenames": []});'
)
OPTIONS_JS = "var DOCUMENTATION_OPTIONS = {VERSION: '2.1.0'};"


def a_page(title: str) -> str:
    return (
        '<html><body><div role="main">'
        f"<h1>{title}</h1><p>Body of {title}.</p>"
        "</div></body></html>"
    )


def arxiv_client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/html/" in str(request.url):
            return httpx.Response(
                200, text=LATEXML, headers={"content-type": "text/html"}
            )
        return httpx.Response(
            200, text=ATOM, headers={"content-type": "application/atom+xml"}
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def unreachable_client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        raise httpx.ConnectError("no network in a test")

    return httpx.Client(transport=httpx.MockTransport(handler))


def site_client() -> httpx.Client:
    pages = {
        "/en/latest/index.html": a_page("Overview"),
        "/en/latest/guide/install.html": a_page("Install"),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("searchindex.js"):
            return httpx.Response(200, text=SEARCHINDEX)
        if path.endswith("documentation_options.js"):
            return httpx.Response(200, text=OPTIONS_JS)
        if path.endswith("robots.txt"):
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        html = pages.get(path)
        if html is None:
            return httpx.Response(404)
        return httpx.Response(200, text=html, headers={"content-type": "text/html"})

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    root.mkdir()
    initialise_corpus(root)
    return root


PAPER = (
    "corpus:\n  literature:\n    - citekey: welman2024\n"
    '      title: "A Paper About Calibration"\n      identifier: "2409.19750"\n'
)
DOCS = f'corpus:\n  docs:\n    - project: stimela\n      base_url: "{BASE_URL}"\n'


# One `corpus:` key, because two in a YAML document is a duplicate
# mapping key and the second silently wins - which is how the first
# version of this test declared only the documentation site and then
# asserted about the paper.
BOTH = (
    "corpus:\n"
    "  literature:\n    - citekey: welman2024\n"
    '      title: "A Paper About Calibration"\n      identifier: "2409.19750"\n'
    "  docs:\n    - project: stimela\n"
    f'      base_url: "{BASE_URL}"\n'
)


def a_pack(root: Path, *, identifier: str = "alpha", body: str) -> Path:
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    path = root / f"{identifier}.ken.yml"
    path.write_text(
        "kennis:\n  schema_version: 1\n"
        f'pack:\n  id: {identifier}\n  name: n\n  version: "1.0.0"\n' + body,
        encoding="utf-8",
    )
    update_pack(path)
    return path


def installed(corpus: Path, tmp_path: Path, *, body: str) -> None:
    install_pack(corpus, a_pack(tmp_path / "provider", body=body))


def papers_in(corpus: Path) -> list[Document]:
    return list(Collection(root=corpus, name="literature").contents().documents)


def pages_in(corpus: Path) -> list[Document]:
    return list(Collection(root=corpus, name="docs").contents().documents)


def synced(
    corpus: Path,
    *,
    arxiv: httpx.Client | None = None,
    client: httpx.Client | None = None,
) -> CorpusSync:
    """A sync with clients that never leave the machine."""
    return sync_corpus(
        corpus,
        arxiv=arxiv or arxiv_client(),
        client=client or site_client(),
        request_delay_seconds=0.0,
    )


# ---------------------------------------------------------------------------
# Literature
# ---------------------------------------------------------------------------


def test_a_declared_paper_is_fetched(corpus: Path, tmp_path: Path):
    installed(corpus, tmp_path, body=PAPER)

    synced(corpus)

    assert len(papers_in(corpus)) == 1


def test_the_fetched_paper_is_owned_by_the_pack(corpus: Path, tmp_path: Path):
    installed(corpus, tmp_path, body=PAPER)

    synced(corpus)

    assert papers_in(corpus)[0].frontmatter.owner == "pack:alpha"


def test_a_second_sync_does_not_fetch_the_paper_again(corpus: Path, tmp_path: Path):
    """An unchanged declaration is `keep`, and a refetch would cost a
    request per paper on every provider run."""
    installed(corpus, tmp_path, body=PAPER)
    synced(corpus)
    before = papers_in(corpus)[0].id

    result = synced(corpus, arxiv=unreachable_client())

    assert papers_in(corpus)[0].id == before
    assert result.counts.get("keep") == 1


def test_a_changed_citekey_is_a_rename_and_not_a_refetch(corpus: Path, tmp_path: Path):
    """Section 5 step 3: keying on the identifier is what makes correcting
    a citekey a rename. Re-fetching would delete a paper and pull the
    identical one down again."""
    installed(corpus, tmp_path, body=PAPER)
    synced(corpus)
    before = papers_in(corpus)[0].id

    installed(corpus, tmp_path, body=PAPER.replace("welman2024", "welmanCalib2024"))
    synced(corpus, arxiv=unreachable_client())

    paper = papers_in(corpus)[0]
    assert paper.id == before
    assert paper.frontmatter.bib.citekey == "welmanCalib2024"


def test_a_paper_no_pack_declares_any_more_is_removed(corpus: Path, tmp_path: Path):
    installed(corpus, tmp_path, body=PAPER)
    synced(corpus)

    installed(corpus, tmp_path, body="corpus:\n  notes: []\n")
    synced(corpus)

    assert papers_in(corpus) == []


def test_a_paper_the_user_owns_is_left_alone_and_reported(corpus: Path, tmp_path: Path):
    from kennis.engine.corpus.add import add_literature

    add_literature(
        Collection(root=corpus, name="literature"),
        ["2409.19750"],
        arxiv=arxiv_client(),
    )
    installed(corpus, tmp_path, body=PAPER)

    result = synced(corpus, arxiv=unreachable_client())

    assert len(papers_in(corpus)) == 1
    assert papers_in(corpus)[0].frontmatter.owner == "user"
    assert result.counts.get("yours") == 1


def test_a_fetch_that_fails_does_not_stop_the_run(corpus: Path, tmp_path: Path):
    """One unreachable host must not prevent the other declarations from
    being resolved."""
    installed(corpus, tmp_path, body=BOTH)

    result = synced(corpus, arxiv=unreachable_client())

    assert papers_in(corpus) == []
    assert len(pages_in(corpus)) >= 1
    assert result.failed == ("arxiv:2409.19750",)


def test_a_failed_fetch_is_retried_on_the_next_run(corpus: Path, tmp_path: Path):
    """Nothing was written, so the declaration is still unresolved - and
    a sync that recorded the failure would never try again."""
    installed(corpus, tmp_path, body=PAPER)
    synced(corpus, arxiv=unreachable_client())

    synced(corpus)

    assert len(papers_in(corpus)) == 1


# ---------------------------------------------------------------------------
# Documentation
# ---------------------------------------------------------------------------


def test_a_declared_project_is_crawled(corpus: Path, tmp_path: Path):
    installed(corpus, tmp_path, body=DOCS)

    synced(corpus)

    assert len(pages_in(corpus)) >= 1
    assert pages_in(corpus)[0].frontmatter.owner == "pack:alpha"


def test_a_second_sync_does_not_crawl_again(corpus: Path, tmp_path: Path):
    """A crawl is hundreds of requests and the diff key for docs is the
    project alone, so an unchanged declaration is `keep`. Refreshing a
    site is what `corpus add --docs` is for. Concern #277."""
    installed(corpus, tmp_path, body=DOCS)
    synced(corpus)
    before = len(pages_in(corpus))

    result = synced(corpus, client=unreachable_client())

    assert len(pages_in(corpus)) == before
    assert result.counts.get("keep") == 1


def test_a_project_no_pack_declares_any_more_loses_every_page(
    corpus: Path, tmp_path: Path
):
    """The unit of declaration is the project; the unit on disk is a
    page. Removing one page and leaving the rest would leave a project
    nothing declares and nothing would ever clean it."""
    installed(corpus, tmp_path, body=DOCS)
    synced(corpus)
    assert pages_in(corpus)

    installed(corpus, tmp_path, body="corpus:\n  notes: []\n")
    synced(corpus)

    assert pages_in(corpus) == []


# ---------------------------------------------------------------------------
# Both, and the rows they share with notes
# ---------------------------------------------------------------------------


def test_an_unrecognised_owner_refuses_before_anything_is_fetched(
    corpus: Path, tmp_path: Path
):
    installed(corpus, tmp_path, body=PAPER)
    synced(corpus)
    path = papers_in(corpus)[0].md_path
    path.write_text(
        path.read_text().replace("owner: pack:alpha", "owner: managed_by:alpha"),
        encoding="utf-8",
    )

    with pytest.raises(DocumentInvalid):
        synced(corpus)


def test_a_sync_with_no_declarations_fetches_nothing(corpus: Path, tmp_path: Path):
    installed(corpus, tmp_path, body="corpus:\n  notes: []\n")

    result = synced(corpus, arxiv=unreachable_client(), client=unreachable_client())

    assert result.counts == {}


def test_the_packs_citekey_is_what_the_fetched_paper_carries(
    corpus: Path, tmp_path: Path
):
    """Found by running the command. The citekey is the handle the
    provider's own prose cites, so a paper that arrived under one kennis
    derived from the title would answer to nothing the pack says."""
    installed(corpus, tmp_path, body=PAPER)

    synced(corpus)

    assert papers_in(corpus)[0].frontmatter.bib.citekey == "welman2024"


def test_the_fetch_keeps_the_title_it_found_over_the_declarations(
    corpus: Path, tmp_path: Path
):
    """arXiv knows the paper's own title better than a pack's one-line
    declaration does, so a rename changes the citekey and leaves the
    title alone."""
    installed(corpus, tmp_path, body=PAPER)
    synced(corpus)
    fetched = papers_in(corpus)[0].frontmatter.title

    installed(
        corpus,
        tmp_path,
        body=PAPER.replace("welman2024", "welmanCalib2024").replace(
            "A Paper About Calibration", "A Different Title Entirely"
        ),
    )
    synced(corpus, arxiv=unreachable_client())

    paper = papers_in(corpus)[0]
    assert paper.frontmatter.bib.citekey == "welmanCalib2024"
    assert paper.frontmatter.title == fetched


# ---------------------------------------------------------------------------
# The keys, as pure functions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [
        ("1712.01093", "arxiv:1712.01093"),
        ("10.48550/arXiv.1712.01093", "arxiv:1712.01093"),
        ("10.1000/xyz", "doi:10.1000/xyz"),
        ("2018MNRAS.478.2399K", "bibcode:2018MNRAS.478.2399K"),
    ],
)
def test_a_paper_is_keyed_by_its_identifier_and_its_kind(
    identifier: str, expected: str
):
    """The kind is part of the key so a DOI and an arXiv id that happen to
    share a string cannot collide; arXiv's own DOI is the arXiv paper."""
    entry = LiteratureEntry(citekey="a", title="t", identifier=identifier)

    assert literature_key(entry) == expected


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"arxiv_id": "1712.01093"}, "arxiv:1712.01093"),
        ({"doi": "10.1000/xyz"}, "doi:10.1000/xyz"),
        ({"bibcode": "2018MNRAS.478.2399K"}, "bibcode:2018MNRAS.478.2399K"),
        ({}, None),
    ],
)
def test_a_held_paper_is_keyed_back_the_same_way(
    fields: dict[str, str], expected: str | None
):
    """The document has to answer to the key its declaration produced,
    or a sync would fetch a second copy of a paper it already holds.
    None for a paper with no identifier at all, which no declaration can
    be about."""
    assert bibliography_key(Bibliography(citekey="a", **fields)) == expected


def test_a_crawl_that_fails_is_reported_and_not_recorded(corpus: Path, tmp_path: Path):
    """Nothing was written, so the project is still undeclared on disk
    and the next run tries again."""
    installed(corpus, tmp_path, body=DOCS)

    result = synced(corpus, client=unreachable_client())

    assert pages_in(corpus) == []
    assert result.failed == ("stimela",)


def test_two_packs_declaring_one_paper_resolve_to_the_incumbent(
    corpus: Path, tmp_path: Path
):
    """Section 5 step 6: a declaration section is a union too, and the
    earliest-installed pack owns what two of them declare. Without it
    the second pack's citekey would fight the first's on every run."""
    install_pack(corpus, a_pack(tmp_path / "one", identifier="alpha", body=PAPER))
    install_pack(
        corpus,
        a_pack(
            tmp_path / "two",
            identifier="beta",
            body=PAPER.replace("welman2024", "betaCalib2024"),
        ),
    )

    synced(corpus)

    paper = papers_in(corpus)[0]
    assert paper.frontmatter.owner == "pack:alpha"
    assert paper.frontmatter.bib.citekey == "welman2024"


# ---------------------------------------------------------------------------
# What a sync shows, and how fast it asks
# ---------------------------------------------------------------------------


class Recording:
    def __init__(self) -> None:
        self.events: list[Event] = []

    def emit(self, event: Event) -> None:
        self.events.append(event)


def test_a_sync_draws_one_bar_across_its_papers_and_projects(
    corpus: Path, tmp_path: Path
):
    """Its notes written, a sync sat silent through every fetch and crawl:
    an add of one paper draws no bar, and each add's finish closed any
    bar that was open."""
    installed(corpus, tmp_path, body=BOTH)
    recorded = Recording()

    sync_corpus(
        corpus,
        arxiv=arxiv_client(),
        client=site_client(),
        request_delay_seconds=0.0,
        events=recorded,
    )

    bars = [event for event in recorded.events if isinstance(event, Progress)]
    finishes = [
        event for event in recorded.events if isinstance(event, OperationFinished)
    ]
    assert [(bar.operation, bar.completed, bar.total) for bar in bars] == [
        (OPERATION, 0, 2),
        (OPERATION, 1, 2),
        (OPERATION, 2, 2),
    ]
    assert [finish.operation for finish in finishes] == [OPERATION]


def test_a_sync_paces_its_papers_as_arxiv_asks(
    corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Each paper is an add of one, so the add's pacing - between the papers
    it is given - never applied, and a sync asked arXiv back to back."""
    slept: list[float] = []
    monkeypatch.setattr(
        "kennis.engine.corpus.sync.time.sleep", lambda seconds: slept.append(seconds)
    )
    two = (
        "corpus:\n  literature:\n"
        '    - citekey: one\n      title: "One"\n      identifier: "2409.19750"\n'
        '    - citekey: two\n      title: "Two"\n      identifier: "2409.19751"\n'
    )
    installed(corpus, tmp_path, body=two)

    sync_corpus(corpus, arxiv=arxiv_client(), client=site_client())

    assert slept == [3.0]


def test_a_changed_project_is_crawled_once_and_then_kept(corpus: Path, tmp_path: Path):
    """Its pages were already held, so they kept the old digest, and every
    later sync judged the project changed and crawled it again."""
    installed(corpus, tmp_path, body=DOCS)
    synced(corpus)
    installed(corpus, tmp_path, body=DOCS + '      exclude: ["nothing/*"]\n')

    rewritten = synced(corpus)
    after = synced(corpus, client=unreachable_client())

    assert rewritten.counts.get("rewrite") == 1
    assert rewritten.failed == ()
    assert after.counts.get("keep") == 1


# ---------------------------------------------------------------------------
# A declared paper with an address for its text
# ---------------------------------------------------------------------------

JOURNAL_PDF = "https://journal.example/stab1234.md"


def a_paper_at() -> str:
    return (
        "corpus:\n  literature:\n    - citekey: welman2021\n"
        '      title: "A Journal Paper"\n'
        '      identifier: "10.1093/mnras/stab1234"\n'
        f'      url: "{JOURNAL_PDF}"\n'
    )


def journal(front: str) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == JOURNAL_PDF:
            return httpx.Response(
                200, text=front, headers={"content-type": "text/markdown"}
            )
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_a_paper_declared_with_an_address_is_fetched_from_it(
    corpus: Path, tmp_path: Path
):
    """A DOI alone has no text kennis can fetch; the pack says where it is."""
    installed(corpus, tmp_path, body=a_paper_at())

    result = synced(
        corpus,
        client=journal("# A Journal Paper\n\ndoi:10.1093/mnras/stab1234\n"),
    )

    assert result.failed == ()
    [paper] = papers_in(corpus)
    assert paper.frontmatter.bib.doi == "10.1093/mnras/stab1234"
    assert paper.frontmatter.bib.citekey == "welman2021"


def test_an_address_holding_another_paper_is_not_filed(corpus: Path, tmp_path: Path):
    installed(corpus, tmp_path, body=a_paper_at())

    result = synced(
        corpus, client=journal("# Something Else\n\ndoi:10.1093/mnras/stab9999\n")
    )

    assert result.failed == ("doi:10.1093/mnras/stab1234",)
    assert papers_in(corpus) == []


def test_a_paper_kennis_cannot_reach_is_handed_back_with_where_to_get_it(
    corpus: Path, tmp_path: Path
):
    """A sync said only that a paper "could not be fetched and will be tried
    again" - which it would be, and fail the same way, for a paper behind a
    publisher. What the add knew - where to download it - was dropped."""
    installed(
        corpus,
        tmp_path,
        body=(
            "corpus:\n  literature:\n    - citekey: welman2021\n"
            '      title: "A Journal Paper"\n'
            '      identifier: "10.1093/mnras/stab1234"\n'
        ),
    )

    result = synced(corpus, arxiv=unreachable_client())

    assert result.failed == ("doi:10.1093/mnras/stab1234",)
    [(address, refusal)] = result.why
    assert address == "doi:10.1093/mnras/stab1234"
    assert "https://doi.org/10.1093/mnras/stab1234" in describe_why_unfetched(
        address, refusal
    )


# ---------------------------------------------------------------------------
# Where a pack's papers are filed (Brian, 2026-10-16)
# ---------------------------------------------------------------------------


def literature_folder(document: Document, corpus: Path) -> str:
    holder = document.wrapper_dir or document.md_path
    return holder.parent.relative_to(corpus / "literature").as_posix()


GROUPED_PAPER = PAPER + "      group: calibration/gains\n"


def test_a_pack_paper_is_filed_under_the_pack(corpus: Path, tmp_path: Path):
    installed(corpus, tmp_path, body=PAPER)

    synced(corpus)

    (paper,) = papers_in(corpus)
    assert literature_folder(paper, corpus) == "alpha"


def test_a_pack_paper_with_a_group_is_filed_in_it_under_the_pack(
    corpus: Path, tmp_path: Path
):
    installed(corpus, tmp_path, body=GROUPED_PAPER)

    synced(corpus)

    (paper,) = papers_in(corpus)
    assert literature_folder(paper, corpus) == "alpha/calibration/gains"


def test_a_paper_whose_group_changed_is_moved_and_not_fetched_again(
    corpus: Path, tmp_path: Path
):
    installed(corpus, tmp_path, body=PAPER)
    synced(corpus)
    (before,) = papers_in(corpus)
    installed(corpus, tmp_path, body=GROUPED_PAPER)

    result = synced(corpus, arxiv=unreachable_client())

    (after,) = papers_in(corpus)
    assert literature_folder(after, corpus) == "alpha/calibration/gains"
    assert after.id == before.id
    assert result.failed == ()
    assert result.counts.get("rewrite") == 1


def test_a_paper_the_user_owns_stays_where_the_user_filed_it(
    corpus: Path, tmp_path: Path
):
    from kennis.engine.corpus.add import add_literature

    add_literature(
        Collection(root=corpus, name="literature"),
        ["2409.19750"],
        arxiv=arxiv_client(),
    )
    installed(corpus, tmp_path, body=PAPER)

    synced(corpus, arxiv=unreachable_client())

    (paper,) = papers_in(corpus)
    assert literature_folder(paper, corpus) == "."


def test_a_docs_project_is_one_folder_by_its_name_holding_its_version(
    corpus: Path, tmp_path: Path
):
    installed(corpus, tmp_path, body=DOCS)

    synced(corpus)

    folders = {
        page.md_path.parent.relative_to(corpus / "docs").as_posix()
        for page in pages_in(corpus)
    }
    assert folders == {"stimela/latest"}


def test_a_pack_s_named_version_decides_the_folder(corpus: Path, tmp_path: Path):
    """#489: an entry's `version` wins over the one in its address."""
    installed(corpus, tmp_path, body=DOCS + '      version: "2.2"\n')

    synced(corpus)

    folders = {
        page.md_path.parent.relative_to(corpus / "docs").as_posix()
        for page in pages_in(corpus)
    }
    assert folders == {"stimela/2.2"}


# ---------------------------------------------------------------------------
# Where each document is, for the report (Brian, 2026-10-16)
# ---------------------------------------------------------------------------


def place_of(document: Document, corpus: Path) -> str:
    return document.md_path.relative_to(corpus).as_posix()


def test_a_fetched_paper_is_reported_where_it_was_filed(corpus: Path, tmp_path: Path):
    """The report said `arxiv:2409.19750`, the key only a pack author reads."""
    installed(corpus, tmp_path, body=PAPER)

    result = synced(corpus)

    (paper,) = papers_in(corpus)
    (action,) = result.actions
    assert result.places[action.address] == place_of(paper, corpus)
    assert result.places[action.address].startswith("literature/alpha/")


def test_a_removed_paper_is_reported_where_it_was(corpus: Path, tmp_path: Path):
    """tron's 13 papers were reported as 13 arXiv keys when removed."""
    installed(corpus, tmp_path, body=PAPER)
    synced(corpus)
    (paper,) = papers_in(corpus)
    was = place_of(paper, corpus)

    installed(corpus, tmp_path, body="corpus:\n  notes: []\n")
    result = synced(corpus)

    (action,) = result.actions
    assert action.verdict == "delete"
    assert result.places[action.address] == was


def test_a_project_is_reported_as_its_folder(corpus: Path, tmp_path: Path):
    installed(corpus, tmp_path, body=DOCS)

    result = synced(corpus)

    (action,) = result.actions
    assert result.places[action.address] == "docs/stimela"
