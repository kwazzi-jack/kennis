"""A pack's paper that is not in the corpus is said wherever the corpus is.

Brian, 2026-11-27, after his trial's 2.13: a sync that could not fetch a
paper said so once, during the sync, and nothing afterwards - not `corpus
status`, not `pack list`, not the window's pack page, not `list_corpus`.
A reader who skipped the paper at the prompt could carry on without
realising it was missing. Each of those now names it, and where a file
would answer it the window offers the dialog that takes one.

What is missing is read without a fetch: a declared paper whose
resolution is `write`. Why it is missing is a fetch's to learn, so the
words name the sync, which fetches it or asks for the reader's copy.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from bs4 import BeautifulSoup
from click.testing import CliRunner
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.engine.corpus.sync import MissingPaper, missing_pack_papers, supply_paper
from kennis.engine.history.repository import initialise_corpus
from kennis.engine.pack.installed import list_installed
from kennis.engine.pack.store import install_pack
from kennis.engine.pack.update import update_pack
from kennis.gui.app import build_app
from kennis.mcp.tools.corpus import list_corpus

DOI = "10.48479/bhpj-nz95"
ADDRESS = f"doi:{DOI}"
CITEKEY = "maccagniRFIMeerKAT2022"
TITLE = "RFI at u=0 in MeerKAT observations"
TOKEN = "a-test-token"

PACK = f"""\
kennis:
  schema_version: 1
pack:
  id: alpha
  name: Alpha
  version: "1.0.0"
corpus:
  literature:
    - citekey: {CITEKEY}
      title: "{TITLE}"
      authors: ["Maccagni, F. M."]
      year: 2022
      identifier: "{DOI}"
      group: rfi
"""

MISSING = MissingPaper(address=ADDRESS, pack_id="alpha", citekey=CITEKEY, title=TITLE)


def a_pack(tmp_path: Path) -> Path:
    path = tmp_path / "provider" / "alpha.ken.yml"
    path.parent.mkdir(parents=True)
    path.write_text(PACK, encoding="utf-8")
    # Every field is given, so nothing is fetched to complete the entry.
    update_pack(path)
    return path


def downloaded(tmp_path: Path) -> Path:
    path = tmp_path / "Downloads" / "maccagni.md"
    path.parent.mkdir(parents=True)
    path.write_text("# RFI at u=0\n\nThe text, downloaded by hand.\n", encoding="utf-8")
    return path


def supplied(corpus: Path, path: Path) -> None:
    # doi.org is asked what the paper is, and answers that it does not know.
    unknown = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(404))
    )
    supply_paper(corpus, ADDRESS, path, arxiv=unknown)


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------


@pytest.fixture
def installed(tmp_path: Path) -> Path:
    """A corpus with a pack installed and never synchronised."""
    root = tmp_path / "corpus"
    root.mkdir()
    initialise_corpus(root)
    install_pack(root, a_pack(tmp_path))
    return root


def test_a_declared_paper_never_fetched_is_missing(installed: Path):
    assert missing_pack_papers(installed) == (MISSING,)


def test_a_supplied_paper_is_no_longer_missing(installed: Path, tmp_path: Path):
    supplied(installed, downloaded(tmp_path))

    assert missing_pack_papers(installed) == ()


def test_a_corpus_with_no_packs_misses_nothing(tmp_path: Path):
    root = tmp_path / "corpus"
    root.mkdir()
    initialise_corpus(root)

    assert missing_pack_papers(root) == ()


def test_a_damaged_pack_is_left_to_pack_status(installed: Path):
    """A read must not raise for a store a sync refuses: `pack status`
    names the damage and the command that repairs it."""
    stored = installed / "packs" / "alpha" / "pack.ken.yml"
    # The store is written read-only, so damaging it takes permission first.
    stored.chmod(0o644)
    stored.write_text("not: [a pack\n", encoding="utf-8")
    assert [one.declaration for one in list_installed(installed).packs] == [None]

    assert missing_pack_papers(installed) == ()


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    result = CliRunner().invoke(main, ["pack", "install", str(a_pack(tmp_path))])
    assert result.exit_code == 0, result.output
    return tmp_path / "corpus"


def lines_of(output: str) -> list[str]:
    return [" ".join(line.split()) for line in output.splitlines()]


def test_corpus_status_names_the_missing_paper_and_the_sync(corpus: Path):
    result = CliRunner().invoke(main, ["corpus", "status"])

    assert result.exit_code == 0, result.output
    lines = lines_of(result.output)
    row = next(line for line in lines if ADDRESS in line)
    assert CITEKEY in row
    assert "alpha" in row
    assert "kennis corpus sync" in result.output
    assert lines.index(row) < next(
        position for position, line in enumerate(lines) if "kennis corpus sync" in line
    )


def test_corpus_status_says_nothing_of_packs_once_the_paper_is_held(
    corpus: Path, tmp_path: Path
):
    supplied(corpus, downloaded(tmp_path))

    result = CliRunner().invoke(main, ["corpus", "status"])

    assert result.exit_code == 0, result.output
    assert ADDRESS not in result.output
    assert "kennis corpus sync" not in result.output


def test_pack_status_names_the_paper_under_its_pack(corpus: Path):
    result = CliRunner().invoke(main, ["pack", "status"])

    assert result.exit_code == 0, result.output
    lines = lines_of(result.output)
    pack = next(
        position for position, line in enumerate(lines) if line.startswith("alpha")
    )
    row = next(position for position, line in enumerate(lines) if ADDRESS in line)
    assert row > pack
    assert lines[row].startswith("!")
    assert "kennis corpus sync" in result.output


def test_pack_list_counts_what_is_not_in_the_corpus(corpus: Path):
    result = CliRunner().invoke(main, ["pack", "list"])

    assert result.exit_code == 0, result.output
    assert "1 paper not in the corpus" in " ".join(result.output.split())


def test_pack_list_says_nothing_of_it_once_the_paper_is_held(
    corpus: Path, tmp_path: Path
):
    supplied(corpus, downloaded(tmp_path))

    result = CliRunner().invoke(main, ["pack", "list"])

    assert result.exit_code == 0, result.output
    assert "not in the corpus" not in result.output


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------


def opened() -> TestClient:
    client = TestClient(build_app(TOKEN), follow_redirects=False)
    assert client.get("/", params={"token": TOKEN}).status_code == 200
    return client


@pytest.mark.parametrize("address", ["/packs/alpha", "/packs", "/corpus"])
def test_the_pack_card_offers_the_file_for_a_missing_paper(corpus: Path, address: str):
    page = BeautifulSoup(opened().get(address).text, "html.parser")

    [missing] = page.select(".pack-missing li")
    assert CITEKEY in missing.get_text(" ", strip=True)
    hrefs = [link["href"] for link in missing.select("a")]
    assert f"https://doi.org/{DOI}" in hrefs
    supplying = [urlsplit(href) for href in hrefs if href.startswith("/supply?")]
    assert [parse_qs(address.query) for address in supplying] == [
        {"owner": ["pack"], "paper": [ADDRESS]}
    ]


def test_the_pack_card_lists_nothing_once_the_paper_is_held(
    corpus: Path, tmp_path: Path
):
    supplied(corpus, downloaded(tmp_path))

    page = BeautifulSoup(opened().get("/packs/alpha").text, "html.parser")

    assert page.select(".pack-missing") == []


# ---------------------------------------------------------------------------
# The MCP server
# ---------------------------------------------------------------------------


def test_list_corpus_names_the_paper_a_pack_declares_and_the_corpus_lacks(
    corpus: Path,
):
    said = list_corpus("literature")

    row = next(line for line in said.splitlines() if ADDRESS in line)
    assert CITEKEY in row
    assert "not in the corpus" in said


def test_list_corpus_names_a_document_by_its_place(corpus: Path):
    """The defect `corpus list` had (#707): a paper that keeps its figures
    is a folder holding `content.md`, and a row naming the file is a row
    naming nothing."""
    wrapper = corpus / "notes" / "calibration" / "Wrapped"
    (wrapper / "images").mkdir(parents=True)
    (wrapper / "content.md").write_text(
        "---\nid: wrappedaaa\ntitle: Wrapped\nowner: user\n"
        "source:\n  from: 'path:x'\n  via: verbatim\n  format: markdown\n"
        "---\n\n# Wrapped\n",
        encoding="utf-8",
    )

    said = list_corpus("notes", detail="documents")

    assert "content.md" not in said
    assert "wrappedaaa  notes/calibration/Wrapped" in said
