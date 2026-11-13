"""A figure for an agent: the `figure` tool and the rule behind it (#642).

An agent reading a paper sees `![](3f9a...jpg)` and a caption. `figure`
answers the image itself: one kept beside the document, or one held at a
site the reader named in `figures.trusted_hosts`, fetched when asked for.
Only what the document's own markdown links can be asked for.

The image is a JPEG's first bytes, never text (#649). No test here reaches
a host: the fetch is answered by a handler in the test.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable, Sequence
from pathlib import Path

import httpx
import pytest
from click.testing import CliRunner
from fastmcp import Client
from fastmcp.utilities.types import Image

from kennis import figures, operations
from kennis.cli.__main__ import main
from kennis.context import Context, existing_corpus
from kennis.engine import courtesy
from kennis.engine.corpus import add as adding
from kennis.engine.corpus.add import AddOptions
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.converters import ConversionBatch
from kennis.engine.corpus.document import Document
from kennis.engine.errors import DocumentNotFound, InputError
from kennis.engine.events import Outcome
from kennis.figures import MAX_FIGURE_BYTES, figure_of
from kennis.mcp.server import build_server
from kennis.mcp.tools.figure import figure

JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01"
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR remote"
KEPT = "0123456789abcdef.jpg"
GONE = "images/abc123.jpg"
ARXIV = "https://arxiv.org/html/2409.19750v1/x1.png"
ELSEWHERE = "https://example.org/figures/a.png"
PLAIN = "http://arxiv.org/html/2409.19750v1/x2.png"
UNLINKED = "https://arxiv.org/html/2409.19750v1/never-linked.png"

BODY = "\n\n".join(
    [
        "Residuals of the patch.",
        f"![]({KEPT})  \nFigure 1. Kept.",
        f"![]({GONE})  \nFigure 2. Never kept.",
        f"![Refer to caption]({ARXIV})  \nFigure 3. At arXiv.",
        f"![]({ELSEWHERE})",
        f"![]({PLAIN})",
        f"A link that is not an image: [the paper]({UNLINKED}).",
    ]
)


class FigureConverter:
    name = "figures"
    formats = frozenset({"pdf"})

    def is_available(self) -> bool:
        return True

    def install_hint(self) -> str:
        return "install the figure converter"

    def convert(self, paths: Sequence[Path]) -> ConversionBatch:
        return ConversionBatch(
            markdown={path: f"# {path.stem}\n\n{BODY}\n" for path in paths},
            images={path: {KEPT: JPEG} for path in paths},
        )


@pytest.fixture
def context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Context:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    monkeypatch.setattr(adding, "default_converter", FigureConverter)
    courtesy.forget_hosts()
    return existing_corpus()


@pytest.fixture
def paper(context: Context, tmp_path: Path) -> Document:
    source = tmp_path / "sources" / "Residual maps.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"%PDF figures\n")
    report = operations.add_documents(context, "notes", [str(source)], AddOptions())
    assert [outcome.outcome for outcome in report.outcomes] == [Outcome.ADDED]
    notes = Collection(root=context.corpus_root, name="notes")
    (document,) = notes.contents().documents
    assert document.wrapper_dir is not None, "the fixture no longer keeps an image"
    return document


type Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def asked(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every address requested of a host, the hosts answered here: no
    robots.txt (so nothing is disallowed and no delay asked), and a PNG."""
    requested: list[str] = []
    answers: dict[str, Handler] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        answer = answers.get(str(request.url))
        if answer is not None:
            return answer(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})

    monkeypatch.setattr(
        figures,
        "http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    HANDLERS.append(answers)
    return requested


# The answers of the test now running, so a test can say what one address
# answers.
HANDLERS: list[dict[str, Handler]] = []


def answering(address: str, handler: Handler) -> None:
    HANDLERS[-1][address] = handler


def trust(monkeypatch: pytest.MonkeyPatch, hosts: str) -> None:
    monkeypatch.setenv("KENNIS_FIGURES_TRUSTED_HOSTS", hosts)


def fetched_images(asked: list[str]) -> list[str]:
    return [address for address in asked if not address.endswith("/robots.txt")]


# ---------------------------------------------------------------------------
# A kept figure
# ---------------------------------------------------------------------------


def test_a_kept_figure_is_answered_as_its_bytes(
    context: Context, paper: Document, asked: list[str]
):
    found = figure_of(context, paper.id, KEPT)

    assert base64.b64decode(found.data) == JPEG
    assert found.media_type == "image/jpeg"
    assert found.name == KEPT
    assert found.origin == "kept"
    assert asked == []


def test_only_what_the_document_links_as_an_image_can_be_asked_for(
    context: Context, paper: Document, asked: list[str], monkeypatch: pytest.MonkeyPatch
):
    """Not a file beside it, not a path out of it, and not an address it
    links as an ordinary link - whatever the host."""
    trust(monkeypatch, "arxiv.org")
    assert paper.wrapper_dir is not None
    (paper.wrapper_dir / "beside.jpg").write_bytes(JPEG)

    for name in ("beside.jpg", "content.md", f"../Residual maps/{KEPT}", UNLINKED, ""):
        with pytest.raises(InputError, match="does not link"):
            figure_of(context, paper.id, name)
    assert asked == []


def test_a_figure_the_conversion_did_not_keep_says_so(
    context: Context, paper: Document, asked: list[str]
):
    with pytest.raises(InputError, match="not kept"):
        figure_of(context, paper.id, GONE)


def test_an_unknown_document_is_refused_as_any_read_refuses_it(
    context: Context, paper: Document, asked: list[str]
):
    with pytest.raises(DocumentNotFound):
        figure_of(context, "no-such-document", KEPT)


def test_a_kept_figure_over_the_limit_is_refused_with_its_size(
    context: Context, paper: Document, asked: list[str]
):
    assert paper.wrapper_dir is not None
    (paper.wrapper_dir / KEPT).write_bytes(JPEG + b"\x00" * MAX_FIGURE_BYTES)

    with pytest.raises(InputError, match="more than"):
        figure_of(context, paper.id, KEPT)


# ---------------------------------------------------------------------------
# A figure held at a site
# ---------------------------------------------------------------------------


def test_a_remote_figure_is_not_fetched_from_a_host_nobody_named(
    context: Context, paper: Document, asked: list[str]
):
    """And the refusal says whose decision it is, with the command."""
    with pytest.raises(InputError) as refused:
        figure_of(context, paper.id, ARXIV)

    assert asked == []
    assert "arxiv.org" in str(refused.value)
    assert refused.value.resolution == (
        'kennis config set figures.trusted_hosts "arxiv.org"'
    )


def test_the_command_keeps_the_hosts_already_trusted(
    context: Context, paper: Document, asked: list[str], monkeypatch: pytest.MonkeyPatch
):
    """`config set` replaces the value, so the command names every host."""
    trust(monkeypatch, "arxiv.org")

    with pytest.raises(InputError) as refused:
        figure_of(context, paper.id, ELSEWHERE)

    assert refused.value.resolution == (
        'kennis config set figures.trusted_hosts "arxiv.org example.org"'
    )


def test_a_trusted_host_s_figure_is_fetched_and_answered(
    context: Context, paper: Document, asked: list[str], monkeypatch: pytest.MonkeyPatch
):
    trust(monkeypatch, "arxiv.org")

    found = figure_of(context, paper.id, ARXIV)

    assert base64.b64decode(found.data) == PNG
    assert found.media_type == "image/png"
    assert found.origin == "fetched"
    assert fetched_images(asked) == [ARXIV]
    # robots.txt is asked first, as for everything kennis fetches.
    assert asked[0] == "https://arxiv.org/robots.txt"


def test_plain_http_is_never_fetched_even_from_a_trusted_host(
    context: Context, paper: Document, asked: list[str], monkeypatch: pytest.MonkeyPatch
):
    trust(monkeypatch, "arxiv.org")

    with pytest.raises(InputError):
        figure_of(context, paper.id, PLAIN)
    assert asked == []


def test_a_figure_fetched_once_is_not_fetched_again(
    context: Context, paper: Document, asked: list[str], monkeypatch: pytest.MonkeyPatch
):
    """Kept under the state folder, never in the corpus."""
    trust(monkeypatch, "arxiv.org")

    first = figure_of(context, paper.id, ARXIV)
    second = figure_of(context, paper.id, ARXIV)

    assert fetched_images(asked) == [ARXIV]
    assert second == first
    assert paper.wrapper_dir is not None
    assert sorted(path.name for path in paper.wrapper_dir.iterdir()) == [
        KEPT,
        "content.md",
    ]


def test_a_host_no_longer_trusted_is_not_answered_from_what_was_kept(
    context: Context, paper: Document, asked: list[str], monkeypatch: pytest.MonkeyPatch
):
    trust(monkeypatch, "arxiv.org")
    figure_of(context, paper.id, ARXIV)
    trust(monkeypatch, "")

    with pytest.raises(InputError):
        figure_of(context, paper.id, ARXIV)


def test_what_a_host_answers_must_be_an_image(
    context: Context, paper: Document, asked: list[str], monkeypatch: pytest.MonkeyPatch
):
    """A page saying the figure moved is not shown to an agent as a figure,
    and is not kept to be answered again."""
    trust(monkeypatch, "arxiv.org")
    answering(
        ARXIV,
        lambda request: httpx.Response(
            200, content=b"<html>moved</html>", headers={"content-type": "text/html"}
        ),
    )

    for _ in range(2):
        with pytest.raises(InputError, match="not an image"):
            figure_of(context, paper.id, ARXIV)
    assert fetched_images(asked) == [ARXIV, ARXIV]


def test_a_host_that_refuses_is_reported_and_nothing_is_kept(
    context: Context, paper: Document, asked: list[str], monkeypatch: pytest.MonkeyPatch
):
    trust(monkeypatch, "arxiv.org")
    answering(ARXIV, lambda request: httpx.Response(404))

    with pytest.raises(InputError, match="404"):
        figure_of(context, paper.id, ARXIV)
    answering(
        ARXIV,
        lambda request: httpx.Response(
            200, content=PNG, headers={"content-type": "image/png"}
        ),
    )
    assert base64.b64decode(figure_of(context, paper.id, ARXIV).data) == PNG


def test_a_remote_figure_over_the_limit_is_refused(
    context: Context, paper: Document, asked: list[str], monkeypatch: pytest.MonkeyPatch
):
    trust(monkeypatch, "arxiv.org")
    answering(
        ARXIV,
        lambda request: httpx.Response(
            200,
            content=PNG + b"\x00" * MAX_FIGURE_BYTES,
            headers={"content-type": "image/png"},
        ),
    )

    with pytest.raises(InputError, match="more than"):
        figure_of(context, paper.id, ARXIV)


def test_a_path_robots_txt_disallows_is_not_asked_for(
    context: Context, paper: Document, asked: list[str], monkeypatch: pytest.MonkeyPatch
):
    trust(monkeypatch, "arxiv.org")
    answering(
        "https://arxiv.org/robots.txt",
        lambda request: httpx.Response(200, text="User-agent: *\nDisallow: /html\n"),
    )

    with pytest.raises(InputError, match=r"robots\.txt"):
        figure_of(context, paper.id, ARXIV)
    assert fetched_images(asked) == []


# ---------------------------------------------------------------------------
# The tool
# ---------------------------------------------------------------------------


def test_the_tool_answers_each_figure_as_a_line_and_an_image(
    context: Context, paper: Document, asked: list[str]
):
    answered = figure(paper.id, [KEPT])

    assert len(answered) == 2
    line, image = answered
    assert isinstance(line, str) and KEPT in line and "kept" in line
    assert isinstance(image, Image)
    assert image.to_image_content().mime_type == "image/jpeg"
    assert base64.b64decode(image.to_image_content().data) == JPEG


def test_one_figure_that_fails_does_not_cost_the_others(
    context: Context, paper: Document, asked: list[str]
):
    answered = figure(paper.id, [GONE, KEPT, ARXIV])

    assert [type(part) for part in answered] == [str, str, Image, str]
    assert "not kept" in str(answered[0])
    # The refusal reaches the agent whole: whose decision, and the command.
    assert "figures.trusted_hosts" in str(answered[3])
    assert "the user" in str(answered[3])


def test_the_tool_refuses_a_batch_it_would_answer_in_part(
    context: Context, paper: Document, asked: list[str]
):
    assert figure(paper.id, []) == ["no figures named"]
    (refusal,) = figure(paper.id, [KEPT] * 5)
    assert isinstance(refusal, str) and "at most 4" in refusal


def test_an_agent_is_sent_an_image_over_the_protocol(
    context: Context, paper: Document, asked: list[str]
):
    """Through the server as an agent connects, not by calling the function:
    a tool that exists and is not registered is invisible."""

    async def called() -> list[object]:
        async with Client(build_server()) as client:
            result = await client.call_tool(
                "figure", {"document_id": paper.id, "names": [KEPT]}
            )
            return list(result.content)

    text, image = asyncio.run(called())

    assert getattr(text, "type", None) == "text"
    assert getattr(image, "type", None) == "image"
    assert getattr(image, "mime_type", None) == "image/jpeg"
    assert base64.b64decode(getattr(image, "data", "")) == JPEG
