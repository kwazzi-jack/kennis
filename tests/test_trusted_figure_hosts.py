"""Figures from a host the reader named load when a document is opened (#660).

A paper read from arXiv's HTML keeps each figure as an address. The window
blocks a remote figure, because loading one tells its host which document
is being read; `figures.trusted_hosts` names the hosts the reader has
decided that about once, rather than page by page.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from click.testing import CliRunner
from fastapi.testclient import TestClient
from pydantic import ValidationError

from kennis.cli.__main__ import main
from kennis.context import existing_corpus
from kennis.engine.corpus.collection import Collection
from kennis.engine.settings import FiguresSettings, figure_hosts, load_settings
from kennis.gui import words
from kennis.gui.app import build_app
from kennis.render.html import IMAGE_BLOCKED, passage_html, to_html

TOKEN = "a-test-token"
ARXIV = "https://arxiv.org/html/2409.19750v1/x1.png"
ELSEWHERE = "https://example.org/figures/a.png"
PLAIN = "http://arxiv.org/html/2409.19750v1/x2.png"
SUBDOMAIN = "https://export.arxiv.org/x3.png"


# ---------------------------------------------------------------------------
# The setting
# ---------------------------------------------------------------------------


def test_no_host_is_trusted_until_one_is_named():
    assert FiguresSettings().trusted_hosts == ""
    assert figure_hosts("") == frozenset()


@pytest.mark.parametrize(
    ("written", "hosts"),
    [
        ("arxiv.org", {"arxiv.org"}),
        ("arxiv.org ar5iv.labs.arxiv.org", {"arxiv.org", "ar5iv.labs.arxiv.org"}),
        (" ArXiv.org,  example-site.org ,", {"arxiv.org", "example-site.org"}),
    ],
)
def test_hosts_are_names_separated_by_spaces_or_commas(written: str, hosts: set[str]):
    assert figure_hosts(FiguresSettings(trusted_hosts=written).trusted_hosts) == hosts


@pytest.mark.parametrize(
    "written",
    [
        "https://arxiv.org",
        "arxiv.org/html",
        "arxiv.org:443",
        "*.arxiv.org",
        "*",
        "arxiv",
        "arxiv.org; example.org",
        "-arxiv.org",
    ],
)
def test_anything_but_a_host_s_name_is_refused(written: str):
    """Told, rather than left matching nothing: `https://arxiv.org/` reads
    as though it would work."""
    with pytest.raises(ValidationError):
        FiguresSettings(trusted_hosts=written)


# ---------------------------------------------------------------------------
# The renderer
# ---------------------------------------------------------------------------

BODY = "\n\n".join(
    f"![{name}]({address})"
    for name, address in (
        ("one", ARXIV),
        ("two", ELSEWHERE),
        ("three", PLAIN),
        ("four", SUBDOMAIN),
    )
)


def drawn(html: str) -> list[str]:
    return [
        str(image["src"]) for image in BeautifulSoup(html, "html.parser").select("img")
    ]


def test_only_a_trusted_host_s_figures_are_drawn():
    """Exactly the host named: not another, not a host under it, and not
    over plain HTTP, which the page's policy never admits for it."""
    rendered = to_html(BODY, trusted_hosts=frozenset({"arxiv.org"}))

    assert drawn(rendered) == [ARXIV]
    assert f"{IMAGE_BLOCKED} example.org" in rendered
    assert f"{IMAGE_BLOCKED} export.arxiv.org" in rendered
    assert rendered.count(f"{IMAGE_BLOCKED} arxiv.org") == 1


def test_a_host_is_matched_whatever_its_case_in_the_address():
    rendered = to_html(
        "![](https://ArXiv.org/x1.png)", trusted_hosts=frozenset({"arxiv.org"})
    )

    assert len(drawn(rendered)) == 1


def test_with_no_trusted_host_nothing_remote_is_drawn():
    assert drawn(to_html(BODY)) == []


def test_a_remote_figure_is_asked_for_when_the_reader_nears_it():
    """Forty figures are not forty requests on opening a paper: both ways
    of loading one mark it for the browser to fetch as it comes near."""
    trusted = to_html(BODY, trusted_hosts=frozenset({"arxiv.org"}))
    asked = to_html(BODY, load_remote_images=True)

    for rendered, count in ((trusted, 1), (asked, 4)):
        images = BeautifulSoup(rendered, "html.parser").select("img")
        assert len(images) == count
        assert all(image.get("loading") == "lazy" for image in images)


def test_a_search_passage_never_loads_a_remote_figure():
    """A result is not a document the reader opened. `passage_html` takes
    no hosts at all, so there is nothing to pass by mistake."""
    parts = passage_html(BODY, terms=[], fits=360)

    assert "<img" not in parts.lead + parts.body
    assert "trusted_hosts" in inspect.signature(to_html).parameters
    assert "trusted_hosts" not in inspect.signature(passage_html).parameters


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------


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


def a_note(corpus: Path, title: str, body: str) -> str:
    source = corpus / "sources" / f"{title}.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
    added = CliRunner().invoke(main, ["corpus", "add", "-n", str(source)])
    assert added.exit_code == 0, added.output
    held = Collection(root=existing_corpus().corpus_root, name="notes").contents()
    return next(d.id for d in held.documents if d.frontmatter.title == title)


def trust(monkeypatch: pytest.MonkeyPatch, hosts: str) -> None:
    monkeypatch.setenv("KENNIS_FIGURES_TRUSTED_HOSTS", hosts)
    assert load_settings().figures.trusted_hosts == hosts


def image_sources_of(policy: str) -> list[str]:
    (images,) = [
        part.strip().split(" ")[1:]
        for part in policy.split(";")
        if part.strip().startswith("img-src ")
    ]
    return images


def test_a_trusted_host_s_figures_are_on_the_page_and_the_browser_may_load_them(
    corpus: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """Both walls: the renderer draws it and the content policy admits that
    host, and only that host."""
    identifier = a_note(corpus, "Figures", BODY)
    trust(monkeypatch, "arxiv.org")

    answer = client.get(f"/document/notes/{identifier}")

    assert drawn(answer.text) == [ARXIV]
    # Written by hand: what the policy says with one trusted host.
    assert image_sources_of(answer.headers["Content-Security-Policy"]) == [
        "'self'",
        "data:",
        "https://arxiv.org",
    ]


def test_untrusted_figures_are_still_blocked_and_still_offered(
    corpus: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    identifier = a_note(corpus, "Figures", BODY)
    trust(monkeypatch, "arxiv.org")

    answer = client.get(f"/document/notes/{identifier}")

    assert f"{IMAGE_BLOCKED} example.org" in answer.text
    assert words.LOAD_IMAGES in answer.text


def test_a_document_whose_figures_are_all_trusted_offers_nothing_to_load(
    corpus: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    identifier = a_note(corpus, "Trusted", f"![one]({ARXIV})")

    before = client.get(f"/document/notes/{identifier}")
    trust(monkeypatch, "arxiv.org")
    after = client.get(f"/document/notes/{identifier}")

    assert words.LOAD_IMAGES in before.text
    assert drawn(before.text) == []
    assert words.LOAD_IMAGES not in after.text
    assert drawn(after.text) == [ARXIV]


def test_a_trusted_host_is_admitted_on_a_document_s_page_and_nowhere_else(
    corpus: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    identifier = a_note(corpus, "Figures", BODY)
    trust(monkeypatch, "arxiv.org example.org")

    document = client.get(f"/document/notes/{identifier}")
    home = client.get("/")
    hits = client.get("/hits", params={"q": "figures"})

    assert image_sources_of(document.headers["Content-Security-Policy"]) == [
        "'self'",
        "data:",
        "https://arxiv.org",
        "https://example.org",
    ]
    for elsewhere in (home, hits):
        assert image_sources_of(elsewhere.headers["Content-Security-Policy"]) == [
            "'self'",
            "data:",
        ]


def test_the_setting_is_offered_with_what_naming_a_host_discloses(
    corpus: Path, client: TestClient
):
    page = client.get("/settings")

    assert page.status_code == 200
    assert words.SETTING_NAMES["figures.trusted_hosts"] in page.text
    assert (
        "which document you are reading" in words.SETTING_TIPS["figures.trusted_hosts"]
    )
