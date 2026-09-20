"""Classifying a source and turning it into markdown.

Text-shaped sources are read verbatim, code is fenced with its language, and
binary documents go to a converter. What comes back is markdown plus
everything the `source` block of a document's frontmatter needs.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import httpx
import pytest

from kennis.engine.corpus.converters import ConversionBatch
from kennis.engine.corpus.intake import (
    SUPPORTED_SUFFIXES,
    Converted,
    convert_local_file,
    convert_url,
    detect_format,
    is_supported_suffix,
    read_text_file,
    sha256_of,
    strip_markdown_inline,
    title_from_markdown,
)
from kennis.engine.errors import ConversionFailed


class StubConverter:
    """A converter that answers from a fixed table, so intake can be tested
    without a subprocess."""

    formats = frozenset({"pdf", "docx", "pptx", "xlsx"})
    name = "stub"

    def __init__(self, markdown: dict[Path, str] | None = None) -> None:
        self.markdown = markdown or {}
        self.calls: list[tuple[Path, ...]] = []

    def is_available(self) -> bool:
        return True

    def install_hint(self) -> str:
        return "install the stub"

    def convert(
        self, paths: Sequence[Path], *, page_limit: int | None = None
    ) -> ConversionBatch:
        self.calls.append(tuple(paths))
        return ConversionBatch(
            markdown={path: self.markdown.get(path, "# Stub\n") for path in paths}
        )


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("a.md", "markdown"),
        ("a.markdown", "markdown"),
        ("a.txt", "text"),
        ("a.rst", "text"),
        ("a.html", "html"),
        ("a.htm", "html"),
        ("a.pdf", "pdf"),
        ("a.docx", "docx"),
        ("a.pptx", "pptx"),
        ("a.xlsx", "xlsx"),
        ("a.py", "code"),
        ("a.toml", "code"),
    ],
)
def test_a_file_is_classified_by_suffix(name: str, expected: str):
    """Suffix rather than content sniffing: the formats that matter are
    unambiguous by extension, and a wrong guess on a binary file is caught by
    the converter anyway."""
    assert detect_format(Path(name)) == expected


def test_an_unknown_suffix_is_treated_as_code():
    """Right when a user named one file explicitly and vouched for it. The
    accept-list below is what stops the same answer being applied to a walk."""
    assert detect_format(Path("a.zzz")) == "code"


def test_the_accept_list_and_the_classifier_deliberately_disagree():
    """`detect_format` answers "code" for anything unknown; a walk must not.
    The encoding ladder never fails, so a walk working from the classifier
    would ingest an ELF binary as a fenced block of mojibake, silently."""
    assert detect_format(Path("a.zzz")) == "code"
    assert is_supported_suffix(Path("a.zzz")) is False
    assert ".zzz" not in SUPPORTED_SUFFIXES


def test_the_accept_list_covers_every_format_the_classifier_names():
    for suffix in (".md", ".txt", ".html", ".py", ".pdf", ".docx"):
        assert suffix in SUPPORTED_SUFFIXES


# ---------------------------------------------------------------------------
# Reading text
# ---------------------------------------------------------------------------


def test_a_utf8_file_reads_as_itself(tmp_path: Path):
    path = tmp_path / "a.txt"
    path.write_bytes(b"plain ascii\n")

    assert read_text_file(path) == "plain ascii\n"


def test_a_file_that_is_not_utf8_still_reads(tmp_path: Path):
    """A text file written on a Windows box may not be UTF-8, and one stray
    byte must not take the whole batch down. Latin-1 never fails, which is
    what terminates the ladder."""
    path = tmp_path / "a.txt"
    path.write_bytes(b"caf\xe9 is not utf-8\n")

    assert "is not utf-8" in read_text_file(path)


def test_a_byte_order_mark_is_not_part_of_the_text(tmp_path: Path):
    path = tmp_path / "a.txt"
    path.write_bytes(b"\xef\xbb\xbfhello\n")

    assert read_text_file(path) == "hello\n"


# ---------------------------------------------------------------------------
# Titles
# ---------------------------------------------------------------------------


def test_a_title_comes_from_a_leading_heading():
    assert title_from_markdown("# A Paper\n\nBody.\n", "fallback") == "A Paper"


def test_a_document_whose_title_contains_markdown_emphasis_gets_a_clean_title():
    """A converter renders a bold heading as `# **Title**`, and without
    stripping, the markers reach the title field and from there every search
    hit, every listing line, and the filename."""
    assert title_from_markdown("# **A Paper**\n", "fallback") == "A Paper"


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        ("**bold**", "bold"),
        ("*italic*", "italic"),
        ("__bold__", "bold"),
        ("`code`", "code"),
        ("[linked](https://x)", "linked"),
        ("**bold** and *italic*", "bold and italic"),
    ],
)
def test_inline_markdown_is_unwrapped(heading: str, expected: str):
    assert strip_markdown_inline(heading) == expected


def test_an_identifier_with_underscores_survives():
    """Deliberately narrow: `snake_case_name`'s underscores are not a matched
    pair around the whole word, so they are not emphasis."""
    assert strip_markdown_inline("snake_case_name") == "snake_case_name"


def test_a_heading_of_nothing_but_markers_yields_no_title():
    """Each pattern needs a pair with content between, so `****` survives
    them; trimming the ends leaves nothing, which the caller reads as "no
    usable title"."""
    assert title_from_markdown("# ****\n", "fallback") == "fallback"


def test_a_document_with_no_heading_falls_back():
    assert title_from_markdown("Just a body.\n", "fallback") == "fallback"


def test_only_a_top_level_heading_counts():
    assert title_from_markdown("## Subsection\n", "fallback") == "fallback"


# ---------------------------------------------------------------------------
# Converting a local file
# ---------------------------------------------------------------------------


def test_markdown_is_read_verbatim(tmp_path: Path):
    path = tmp_path / "A note.md"
    path.write_text("# A note\n\nBody.\n", encoding="utf-8")

    converted = convert_local_file(path)

    assert converted.markdown == "# A note\n\nBody.\n"
    assert converted.via == "verbatim"
    assert converted.format == "markdown"
    assert converted.origin == str(path)
    assert converted.suggested_title == "A note"


def test_a_checksum_is_taken_of_the_source_bytes(tmp_path: Path):
    path = tmp_path / "a.md"
    path.write_bytes(b"# A note\n")

    converted = convert_local_file(path)

    assert converted.sha256 == sha256_of(b"# A note\n")


def test_code_is_fenced_with_its_language(tmp_path: Path):
    """Fenced so the chunker treats it as one block rather than reflowing it
    as prose, and so a reader can tell code from commentary."""
    path = tmp_path / "solver.py"
    path.write_text("def solve():\n    return 1\n", encoding="utf-8")

    converted = convert_local_file(path)

    assert "```python" in converted.markdown
    assert "def solve():" in converted.markdown
    assert converted.format == "code"


def test_a_code_file_is_titled_after_itself(tmp_path: Path):
    path = tmp_path / "solver.py"
    path.write_text("x = 1\n", encoding="utf-8")

    assert convert_local_file(path).suggested_title == "solver.py"


def test_a_code_file_in_an_unlabelled_language_is_still_fenced(tmp_path: Path):
    path = tmp_path / "a.conf"
    path.write_text("key = value\n", encoding="utf-8")

    assert "```\n" in convert_local_file(path).markdown


def test_html_becomes_markdown_with_the_chrome_removed(tmp_path: Path):
    path = tmp_path / "page.html"
    path.write_text(
        "<html><head><title>T</title><script>junk()</script></head>"
        "<body><nav>menu</nav><h1>Heading</h1><p>Body text.</p></body></html>",
        encoding="utf-8",
    )

    converted = convert_local_file(path)

    assert "# Heading" in converted.markdown
    assert "Body text." in converted.markdown
    assert "junk()" not in converted.markdown
    assert "menu" not in converted.markdown
    assert converted.via == "html"


def test_the_original_bytes_are_kept_only_when_asked_for(tmp_path: Path):
    path = tmp_path / "a.md"
    path.write_bytes(b"# A note\n")

    assert convert_local_file(path).original_bytes is None
    kept = convert_local_file(path, keep_original=True)
    assert kept.original_bytes == b"# A note\n"
    assert kept.original_name == "a.md"


# ---------------------------------------------------------------------------
# Converting a binary document
# ---------------------------------------------------------------------------


def test_a_binary_document_goes_to_the_converter(tmp_path: Path):
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"%PDF-1.7\n")
    converter = StubConverter({path: "# A Paper\n\nBody.\n"})

    converted = convert_local_file(path, converter=converter)

    assert converted.markdown == "# A Paper\n\nBody.\n"
    assert converted.via == "mineru"
    assert converted.format == "pdf"
    assert converter.calls == [(path,)]


def test_a_binary_document_never_reaches_the_encoding_ladder(tmp_path: Path):
    """The other half of "never surfaces as a UnicodeDecodeError": the ladder
    would happily decode a PDF as latin-1 mojibake if it were ever asked to."""
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"%PDF-1.7\n\x00\x01\x02\xff\xfe")

    converted = convert_local_file(path, converter=StubConverter())

    assert "\xff" not in converted.markdown


def test_markdown_an_earlier_batch_already_produced_is_reused(tmp_path: Path):
    """What keeps a batched conversion from being repeated a document at a
    time: the add path converts a whole batch in one process, then walks the
    documents with the results in hand."""
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"%PDF-1.7\n")
    converter = StubConverter()

    converted = convert_local_file(
        path, converter=converter, prepared_markdown="# Already Done\n"
    )

    assert converted.markdown == "# Already Done\n"
    assert converter.calls == []


def test_prepared_markdown_is_ignored_for_a_format_the_converter_never_sees(
    tmp_path: Path,
):
    path = tmp_path / "a.md"
    path.write_text("# The real thing\n", encoding="utf-8")

    converted = convert_local_file(path, prepared_markdown="# Not this\n")

    assert converted.markdown == "# The real thing\n"


def test_a_converter_that_produced_nothing_for_this_document_fails_it(
    tmp_path: Path,
):
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"%PDF-1.7\n")

    class EmptyConverter(StubConverter):
        def convert(
            self, paths: Sequence[Path], *, page_limit: int | None = None
        ) -> ConversionBatch:
            return ConversionBatch(markdown={})

    with pytest.raises(ConversionFailed) as raised:
        convert_local_file(path, converter=EmptyConverter())

    assert "paper.pdf" in str(raised.value)


def test_a_binary_document_with_no_converter_at_all_is_refused(tmp_path: Path):
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"%PDF-1.7\n")

    class UnavailableConverter(StubConverter):
        def is_available(self) -> bool:
            return False

        def convert(
            self, paths: Sequence[Path], *, page_limit: int | None = None
        ) -> ConversionBatch:
            raise AssertionError("must not be run when unavailable")

    with pytest.raises(Exception) as raised:
        convert_local_file(path, converter=UnavailableConverter())

    assert "install the stub" in str(raised.value) or "stub" in str(
        raised.value.__dict__.get("resolution", "")
    )


# ---------------------------------------------------------------------------
# Converting a URL
# ---------------------------------------------------------------------------


def transport_returning(html: str, status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, html=html)

    return httpx.MockTransport(handler)


def test_a_page_is_fetched_and_converted():
    client = httpx.Client(
        transport=transport_returning(
            "<html><head><title>Quickstart</title></head>"
            "<body><h1>Quickstart</h1><p>Install it.</p></body></html>"
        )
    )

    converted = convert_url("https://numpy.org/quickstart", client=client)

    assert "# Quickstart" in converted.markdown
    assert "Install it." in converted.markdown
    assert converted.via == "html"
    assert converted.format == "html"
    assert converted.origin == "https://numpy.org/quickstart"


def test_a_page_with_no_heading_falls_back_to_its_title_tag():
    client = httpx.Client(
        transport=transport_returning(
            "<html><head><title>Page Title</title></head>"
            "<body><p>No heading here.</p></body></html>"
        )
    )

    converted = convert_url("https://x/y", client=client)

    assert converted.suggested_title == "Page Title"


def test_a_page_with_neither_falls_back_to_the_host():
    client = httpx.Client(
        transport=transport_returning("<html><body><p>Bare.</p></body></html>")
    )

    assert convert_url("https://example.org/y", client=client).suggested_title == (
        "example.org"
    )


def test_a_failed_fetch_is_a_domain_error_not_an_httpx_one():
    client = httpx.Client(transport=transport_returning("nope", status=404))

    with pytest.raises(Exception) as raised:
        convert_url("https://x/y", client=client)

    assert not isinstance(raised.value, httpx.HTTPError)
    assert "https://x/y" in str(raised.value)


def test_a_converted_result_is_a_frozen_record(tmp_path: Path):
    path = tmp_path / "a.md"
    path.write_text("# A note\n", encoding="utf-8")

    assert isinstance(convert_local_file(path), Converted)
