"""A kept image, drawn in the window (#642).

A paper converted since images were kept is a directory holding
`content.md` and the image files it links. The window draws one where its
file is held and serves the file itself, behind the token like every other
address, and only a raster image that is a document's own asset.

The image is a JPEG's first bytes, never text (#649).
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from click.testing import CliRunner
from fastapi.testclient import TestClient

from kennis import operations
from kennis.cli.__main__ import main
from kennis.context import Context, existing_corpus
from kennis.engine.corpus import add as adding
from kennis.engine.corpus.add import AddOptions
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.converters import ConversionBatch
from kennis.engine.corpus.document import Document
from kennis.engine.corpus.layout import relative_to_corpus
from kennis.engine.events import Outcome
from kennis.gui.app import build_app
from kennis.gui.figures import figure_addresses, held_figure
from kennis.gui.theme import stylesheet
from kennis.render.html import IMAGE_MISSING

TOKEN = "a-test-token"
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01"
FIGURE = "0123456789abcdef.jpg"
TITLE = "Residual maps"


class FigureConverter:
    """Converts every document to markdown that links one image."""

    name = "figures"
    formats = frozenset({"pdf"})

    def is_available(self) -> bool:
        return True

    def install_hint(self) -> str:
        return "install the figure converter"

    def convert(self, paths: Sequence[Path]) -> ConversionBatch:
        return ConversionBatch(
            markdown={
                path: (
                    f"# {path.stem}\n\nResiduals of the patch.\n\n"
                    f"![Refer to caption]({FIGURE})  \nFigure 1. After calibration.\n"
                )
                for path in paths
            },
            images={path: {FIGURE: JPEG} for path in paths},
        )


@pytest.fixture
def context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Context:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    monkeypatch.setattr(adding, "default_converter", FigureConverter)
    return existing_corpus()


@pytest.fixture
def paper(context: Context, tmp_path: Path) -> Document:
    """One paper with a figure, added the way every front end adds one."""
    source = tmp_path / "sources" / f"{TITLE}.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"%PDF figures\n")
    report = operations.add_documents(context, "notes", [str(source)], AddOptions())
    assert [outcome.outcome for outcome in report.outcomes] == [Outcome.ADDED]
    (document,) = (
        Collection(root=context.corpus_root, name="notes").contents().documents
    )
    assert document.wrapper_dir is not None, "the fixture no longer keeps an image"
    assert (document.wrapper_dir / FIGURE).read_bytes() == JPEG
    return document


@pytest.fixture
def client(context: Context) -> TestClient:
    opened = TestClient(build_app(TOKEN), follow_redirects=False)
    assert opened.get("/", params={"token": TOKEN}).status_code == 200
    return opened


def directory_of(context: Context, paper: Document) -> str:
    """The paper's directory, relative to the corpus."""
    assert paper.wrapper_dir is not None
    return relative_to_corpus(paper.wrapper_dir, context.corpus_root)


def images_on(client: TestClient, address: str, **params: str) -> list[str]:
    answer = client.get(address, params=params)
    assert answer.status_code == 200, answer.text
    drawn = BeautifulSoup(answer.text, "html.parser").select("img.figure")
    return [str(image["src"]) for image in drawn]


# ---------------------------------------------------------------------------
# On the page
# ---------------------------------------------------------------------------


def test_a_document_s_page_draws_its_figure_and_the_address_answers_the_file(
    context: Context, paper: Document, client: TestClient
):
    (address,) = images_on(client, f"/document/notes/{paper.id}")

    # Written by hand: the directory's space is encoded, and nothing else.
    assert address == f"/figure/notes/Residual%20maps/{FIGURE}"
    answer = client.get(address)
    assert answer.status_code == 200
    assert answer.content == JPEG
    assert answer.headers["content-type"] == "image/jpeg"
    assert answer.headers["x-content-type-options"] == "nosniff"
    assert answer.headers["cache-control"] == "private, no-cache"


def test_a_figure_is_behind_the_token_like_every_other_address(
    context: Context, paper: Document, client: TestClient
):
    (address,) = images_on(client, f"/document/notes/{paper.id}")
    stranger = TestClient(build_app(TOKEN), follow_redirects=False)

    answer = stranger.get(address)

    assert answer.status_code in {401, 403}
    assert JPEG not in answer.content


def test_a_figure_removed_by_hand_is_a_placeholder_and_not_a_broken_image(
    context: Context, paper: Document, client: TestClient
):
    assert paper.wrapper_dir is not None
    (paper.wrapper_dir / FIGURE).unlink()

    answer = client.get(f"/document/notes/{paper.id}")

    assert "<img" not in answer.text
    assert IMAGE_MISSING in answer.text
    missing = client.get(f"/figure/{directory_of(context, paper)}/{FIGURE}")
    assert missing.status_code == 404


def test_a_search_hit_s_passage_draws_the_figure(
    context: Context, paper: Document, client: TestClient
):
    assert CliRunner().invoke(main, ["corpus", "index"]).exit_code == 0

    drawn = images_on(client, "/hits", q="residuals", scope="notes")

    assert drawn == [f"/figure/notes/Residual%20maps/{FIGURE}"]


# ---------------------------------------------------------------------------
# What the address answers, and what it never does
# ---------------------------------------------------------------------------


def test_only_a_document_s_own_raster_image_is_a_figure(
    context: Context, paper: Document
):
    root = context.corpus_root
    directory = directory_of(context, paper)
    assert paper.wrapper_dir is not None
    (paper.wrapper_dir / "PLOT.PNG").write_bytes(JPEG)
    (paper.wrapper_dir / "drawing.svg").write_bytes(b"<svg/>")
    (paper.wrapper_dir / ".hidden.jpg").write_bytes(JPEG)
    (root / "notes" / "stray.jpg").write_bytes(JPEG)
    (root / ".git" / "wrapped").mkdir()
    (root / ".git" / "wrapped" / "content.md").write_bytes(b"x")
    (root / ".git" / "wrapped" / "inside.jpg").write_bytes(JPEG)
    (root / "index" / "wrapped").mkdir(parents=True)
    (root / "index" / "wrapped" / "content.md").write_bytes(b"x")
    (root / "index" / "wrapped" / "inside.jpg").write_bytes(JPEG)
    (root.parent / "content.md").write_bytes(b"x")
    (root.parent / "outside.jpg").write_bytes(JPEG)

    assert held_figure(root, f"{directory}/{FIGURE}") == paper.wrapper_dir / FIGURE
    assert held_figure(root, f"{directory}/PLOT.PNG") == paper.wrapper_dir / "PLOT.PNG"

    refused = [
        f"{directory}/content.md",
        f"{directory}/drawing.svg",
        f"{directory}/.hidden.jpg",
        f"{directory}/absent.jpg",
        f"{directory}",
        "notes/stray.jpg",
        ".git/wrapped/inside.jpg",
        "index/wrapped/inside.jpg",
        f"{directory}/../../../outside.jpg",
        "notes/../../outside.jpg",
        f"{directory}//{FIGURE}",
        f"/{directory}/{FIGURE}",
        str(paper.wrapper_dir / FIGURE),
        "",
    ]
    for path in refused:
        assert held_figure(root, path) is None, path


@pytest.mark.parametrize(
    "tail",
    [
        "content.md",
        "absent.jpg",
        "%2e%2e/%2e%2e/%2e%2e/outside.jpg",
    ],
)
def test_the_address_answers_nothing_that_is_not_a_figure(
    context: Context, paper: Document, client: TestClient, tail: str
):
    (context.corpus_root.parent / "content.md").write_bytes(b"x")
    (context.corpus_root.parent / "outside.jpg").write_bytes(JPEG)
    held = client.get(f"/figure/{directory_of(context, paper)}/{FIGURE}")
    assert held.status_code == 200, "the fixture no longer exercises the case"

    answer = client.get(f"/figure/{directory_of(context, paper)}/{tail}")

    assert answer.status_code == 404
    assert JPEG not in answer.content
    assert b"Residuals of the patch" not in answer.content


def test_a_page_is_given_addresses_only_for_what_the_address_answers(
    context: Context, paper: Document
):
    root = context.corpus_root
    directory = directory_of(context, paper)
    address = figure_addresses(root, f"{directory}/content.md")

    assert address is not None
    assert address(FIGURE) == f"/figure/notes/Residual%20maps/{FIGURE}"
    assert address("absent.jpg") is None
    assert address("content.md") is None
    assert address(f"../{TITLE}/{FIGURE}") is None
    assert address(f"sub/{FIGURE}") is None
    assert address(f"sub\\{FIGURE}") is None
    assert address("") is None
    # A document that is one file has no directory of its own to hold one.
    assert figure_addresses(root, "notes/Plain note.md") is None


# ---------------------------------------------------------------------------
# How a figure is drawn
# ---------------------------------------------------------------------------


def test_a_transparent_figure_is_on_white_in_both_themes():
    """Black axes on the dark ground were close to invisible (#658). A
    background shows only through transparent pixels, so an opaque image
    is as it was."""
    sheet = stylesheet()
    figure = re.findall(r"img\.figure\s*\{([^}]*)\}", sheet)

    assert len(figure) == 1
    assert "background: var(--figure-ground);" in figure[0]
    grounds = re.findall(r"--figure-ground:\s*([^;]+);", sheet)
    # Written by hand: light, dark by the system, dark by choice.
    assert grounds == ["#FFFFFF", "#FFFFFF", "#FFFFFF"]


def test_a_backslash_never_reaches_a_file(context: Context, paper: Document):
    """On Windows a backslash separates folders inside what was checked as
    one name, so `x\\..\\` climbed back to a file the checks never saw.
    Elsewhere it is a character of a name, and such a file is not served
    either: one rule on every platform."""
    root = context.corpus_root
    directory = directory_of(context, paper)
    assert paper.wrapper_dir is not None
    if os.name != "nt":
        (paper.wrapper_dir / f"x\\..\\{FIGURE}").write_bytes(JPEG)
        (paper.wrapper_dir / "back\\slash.jpg").write_bytes(JPEG)
    assert held_figure(root, f"{directory}/{FIGURE}") is not None

    assert held_figure(root, f"{directory}/x\\..\\{FIGURE}") is None
    assert held_figure(root, f"{directory}/back\\slash.jpg") is None
    address = figure_addresses(root, f"{directory}/content.md")
    assert address is not None
    assert address(f"x\\..\\{FIGURE}") is None


def test_a_link_out_of_the_corpus_is_not_a_figure(
    context: Context, paper: Document, client: TestClient, tmp_path: Path
):
    """A link beside `content.md` is followed by every read of it."""
    assert paper.wrapper_dir is not None
    outside = tmp_path / "private.jpg"
    outside.write_bytes(b"\xff\xd8 not the corpus's")
    (paper.wrapper_dir / "linked.jpg").symlink_to(outside)
    (paper.wrapper_dir / "within.jpg").symlink_to(paper.wrapper_dir / FIGURE)
    directory = directory_of(context, paper)

    assert held_figure(context.corpus_root, f"{directory}/linked.jpg") is None
    answer = client.get(f"/figure/{directory}/linked.jpg")
    assert answer.status_code == 404
    assert b"not the corpus's" not in answer.content
    # The other side: a link that stays inside is a figure.
    assert held_figure(context.corpus_root, f"{directory}/within.jpg") is not None
