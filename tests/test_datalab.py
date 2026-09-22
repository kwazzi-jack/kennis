"""The hosted converter, behind the same interface as the local one.

Nothing here reaches the network. The protocol is where the mistakes live -
submit, then poll a *second* URL with the same header until the status
settles - so every test drives a `MockTransport` that answers the way the
documented API does.

One test does reach it, marked `network`, and skips unless a key is present.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from kennis.engine.corpus.converters import (
    DatalabConverter,
    default_converter,
)
from kennis.engine.errors import ConversionFailed, ConverterUnavailable

CHECK_URL = "https://www.datalab.to/api/v1/convert/abc123"


def a_pdf(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.7\nnot really a pdf\n")
    return path


def conversation(
    *replies: dict[str, object], submit_status: int = 200
) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    """A transport that submits once and then answers each poll in turn."""
    seen: list[httpx.Request] = []
    remaining = list(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "POST":
            return httpx.Response(
                submit_status,
                json={"request_check_url": CHECK_URL, "status": "processing"},
            )
        return httpx.Response(200, json=remaining.pop(0))

    return httpx.MockTransport(handler), seen


def a_converter(transport: httpx.MockTransport) -> DatalabConverter:
    return DatalabConverter(
        api_key="dl-notarealkey",
        client=httpx.Client(transport=transport),
        poll_seconds=0.0,
    )


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def test_a_converter_without_a_key_cannot_run():
    assert not DatalabConverter(api_key="").is_available()


def test_a_converter_with_a_key_can_run():
    assert DatalabConverter(api_key="dl-notarealkey").is_available()


def test_the_missing_key_hint_names_the_setup_rather_than_an_install(
    tmp_path: Path,
):
    """Nothing to install. What is missing is a credential, so the hint has
    to name the command that asks for one."""
    with pytest.raises(ConverterUnavailable) as raised:
        DatalabConverter(api_key="").convert([a_pdf(tmp_path / "a.pdf")])

    assert "kennis config init" in "".join(raised.value.__notes__)


def test_it_declares_the_formats_it_accepts():
    assert "pdf" in DatalabConverter(api_key="k").formats


# ---------------------------------------------------------------------------
# The submit-then-poll protocol
# ---------------------------------------------------------------------------


def test_a_document_is_submitted_and_the_markdown_polled_for(tmp_path: Path):
    transport, seen = conversation(
        {"status": "processing"},
        {"status": "complete", "success": True, "markdown": "# A paper\n"},
    )
    path = a_pdf(tmp_path / "a.pdf")

    batch = a_converter(transport).convert([path])

    assert batch.markdown == {path: "# A paper\n"}
    assert [request.method for request in seen] == ["POST", "GET", "GET"]


def test_the_key_is_sent_on_the_poll_as_well_as_the_submit(tmp_path: Path):
    """The check URL is a separate request and rejects an unauthenticated
    one, so a key sent only on submit converts nothing."""
    transport, seen = conversation(
        {"status": "complete", "success": True, "markdown": "# A\n"}
    )

    a_converter(transport).convert([a_pdf(tmp_path / "a.pdf")])

    assert all(request.headers.get("X-API-Key") == "dl-notarealkey" for request in seen)


def test_the_poll_follows_the_url_the_server_gave(tmp_path: Path):
    """Not a URL kennis assembled. The server names where to look."""
    transport, seen = conversation(
        {"status": "complete", "success": True, "markdown": "# A\n"}
    )

    a_converter(transport).convert([a_pdf(tmp_path / "a.pdf")])

    assert str(seen[1].url) == CHECK_URL


def test_markdown_is_asked_for_explicitly(tmp_path: Path):
    transport, seen = conversation(
        {"status": "complete", "success": True, "markdown": "# A\n"}
    )

    a_converter(transport).convert([a_pdf(tmp_path / "a.pdf")])

    assert b"markdown" in seen[0].content


# ---------------------------------------------------------------------------
# Failure
# ---------------------------------------------------------------------------


def test_a_failed_document_does_not_cost_the_others(tmp_path: Path):
    """The same promise MinerU's batch makes: a path missing from `markdown`
    is that document's failure alone."""
    replies = [
        {"status": "complete", "success": False, "error": "unreadable"},
        {"status": "complete", "success": True, "markdown": "# B\n"},
    ]
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"request_check_url": CHECK_URL})
        return httpx.Response(200, json=replies.pop(0))

    first = a_pdf(tmp_path / "a.pdf")
    second = a_pdf(tmp_path / "b.pdf")

    batch = a_converter(httpx.MockTransport(handler)).convert([first, second])

    assert first not in batch.markdown
    assert batch.markdown[second] == "# B\n"
    assert batch.failure_reason is not None
    assert "unreadable" in batch.failure_reason


def test_a_batch_that_converts_nothing_at_all_is_a_failure(tmp_path: Path):
    transport, _ = conversation(
        {"status": "complete", "success": False, "error": "quota exhausted"}
    )

    with pytest.raises(ConversionFailed) as raised:
        a_converter(transport).convert([a_pdf(tmp_path / "a.pdf")])

    assert "quota exhausted" in str(raised.value)


def test_a_rejected_submission_is_reported_rather_than_polled(tmp_path: Path):
    transport, seen = conversation({}, submit_status=401)

    with pytest.raises(ConversionFailed):
        a_converter(transport).convert([a_pdf(tmp_path / "a.pdf")])

    assert [request.method for request in seen] == ["POST"]


def test_polling_gives_up_rather_than_looping_for_ever(tmp_path: Path):
    """A status that never settles is the one failure mode a poll loop can
    turn into a hang, which is what every other external call here forbids."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"request_check_url": CHECK_URL})
        return httpx.Response(200, json={"status": "processing"})

    converter = DatalabConverter(
        api_key="dl-notarealkey",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        poll_seconds=0.0,
        max_polls=3,
    )

    with pytest.raises(ConversionFailed) as raised:
        converter.convert([a_pdf(tmp_path / "a.pdf")])

    assert "did not finish" in str(raised.value)


# ---------------------------------------------------------------------------
# What it cannot do
# ---------------------------------------------------------------------------


def test_no_front_page_is_reported_because_the_api_returns_none(tmp_path: Path):
    """MinerU classifies page furniture, which is where a paper stamps its
    arXiv id. Datalab returns markdown. A caller must not read an empty front
    page as "this paper states no identity"."""
    transport, _ = conversation(
        {"status": "complete", "success": True, "markdown": "# A\n"}
    )

    batch = a_converter(transport).convert([a_pdf(tmp_path / "a.pdf")])

    assert batch.front_page == {}


# ---------------------------------------------------------------------------
# Choosing one
# ---------------------------------------------------------------------------


def test_the_default_converter_follows_the_setting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("KENNIS_CONVERSION_BACKEND", "datalab")
    monkeypatch.setenv("DATALAB_API_KEY", "dl-notarealkey")

    assert isinstance(default_converter(), DatalabConverter)


# ---------------------------------------------------------------------------
# Against the real service
# ---------------------------------------------------------------------------


@pytest.mark.network
def test_the_hosted_converter_converts_a_real_document(tmp_path: Path):
    """Skipped without a key. Nothing in this suite uploads a document to a
    third party unless someone has deliberately provided credentials."""
    key = os.environ.get("DATALAB_API_KEY")
    if not key:
        pytest.skip("DATALAB_API_KEY is not set")

    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    path = tmp_path / "paper.pdf"
    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.drawString(72, 700, "Wideband Calibration of Aperture Arrays")
    pdf.save()

    batch = DatalabConverter(api_key=key).convert([path])

    assert "Wideband" in batch.markdown[path]
