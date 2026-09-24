"""Turning a source into markdown, whatever kind of source it is.

One dispatch covers every collection: a local file is classified by suffix and
converted according to its format, an http(s) URL is fetched and its HTML
converted, and anything else is passed back for a collection-specific resolver
- an arXiv identifier, a DOI, a `.bib` file - to make sense of. What differs
per collection is only the frontmatter block written on top and which
resolvers run first.

Text-shaped formats are read verbatim: a `.py` file's own bytes are already
the best representation of it, and running it through any converter would only
lose information. Binary document formats go to a `Converter`, which is an
opt-in extra rather than a hard dependency - it pulls model weights and wants
a GPU to be quick, which is too much to impose on someone who only ever adds
markdown notes.
"""

from __future__ import annotations

import hashlib
import re
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final
from urllib.parse import urlparse

import httpx

from kennis.engine.corpus.converters import (
    Converter,
    default_converter,
    require_converter,
)
from kennis.engine.corpus.schema import ConversionVia, SourceFormat
from kennis.engine.errors import ConversionFailed, SourceUnreadable

_USER_AGENT: Final = "kennis-corpus-add"
_REQUEST_TIMEOUT_SECONDS: Final = 30

# Suffix -> format. Anything not listed and not obviously binary is treated as
# code, on the reasoning that an unrecognised text file is far more often a
# config or source file than something kennis should refuse.
_MARKDOWN_SUFFIXES: Final = frozenset({".md", ".markdown", ".mdown"})
_TEXT_SUFFIXES: Final = frozenset({".txt", ".text", ".rst", ".org", ".log"})
_HTML_SUFFIXES: Final = frozenset({".html", ".htm", ".xhtml"})
_BINARY_SUFFIXES: Final[dict[str, SourceFormat]] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
}
_CODE_SUFFIXES: Final = frozenset(
    {
        ".py", ".pyi", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".c", ".h", ".cc",
        ".cpp", ".hpp", ".go", ".rs", ".java", ".kt", ".rb", ".sh", ".bash",
        ".zsh", ".fish", ".ps1", ".sql", ".r", ".jl", ".m", ".f90", ".f", ".pro",
        ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg", ".conf", ".env",
        ".xml", ".csv", ".tsv", ".tex", ".bib", ".lua", ".pl", ".php", ".swift",
        ".scala", ".hs", ".ex", ".exs", ".vim", ".dockerfile", ".makefile",
    }
)  # fmt: skip

# Every suffix kennis has a converter for. This is the accept-list a directory
# walk works from, and it exists because `detect_format` below deliberately
# does not: asked about an unknown suffix it answers "code", which is right
# when a user named one file explicitly and vouched for it, and catastrophic
# when walking a directory. `read_text_file`'s encoding ladder ends in latin-1
# and so never fails, meaning a naive walk would ingest an ELF binary, a
# `.pyc` or a git pack file as a fenced block of mojibake, silently, and index
# it.
#
# Derived from the sets above rather than restated, so a format added to one
# of them is walkable without a second edit.
SUPPORTED_SUFFIXES: Final[frozenset[str]] = (
    _MARKDOWN_SUFFIXES
    | _TEXT_SUFFIXES
    | _HTML_SUFFIXES
    | _CODE_SUFFIXES
    | frozenset(_BINARY_SUFFIXES)
)

# The formats that cannot be read as text and must go through a converter.
BINARY_FORMATS: Final[frozenset[SourceFormat]] = frozenset(_BINARY_SUFFIXES.values())

# Tried in order when a text file is not valid UTF-8. Latin-1 never fails, so
# it terminates the ladder and guarantees a text file is always readable
# rather than crashing the whole batch on one stray byte.
#
# `utf-8-sig` comes *first*, not after `utf-8`. It decodes BOM-less UTF-8
# identically, so nothing is lost by preferring it - whereas the other order
# makes it unreachable, because plain `utf-8` decodes a BOM successfully as a
# leading U+FEFF rather than failing. The character then survives into the
# document's first line, and from there into its title and its filename.
_TEXT_ENCODINGS: Final = ("utf-8-sig", "utf-8", "cp1252", "latin-1")

# Fenced-block languages worth labelling, so a code note's fence carries the
# highlighting hint a reader - or a model - expects.
_FENCE_LANGUAGES: Final[dict[str, str]] = {
    ".py": "python", ".js": "javascript", ".ts": "typescript", ".sh": "bash",
    ".bash": "bash", ".yaml": "yaml", ".yml": "yaml", ".json": "json",
    ".toml": "toml", ".sql": "sql", ".c": "c", ".cpp": "cpp", ".go": "go",
    ".rs": "rust", ".java": "java", ".rb": "ruby", ".r": "r", ".jl": "julia",
}  # fmt: skip

# Tags that are page chrome rather than content.
_CHROME_TAGS: Final = (
    "script", "style", "nav", "header", "footer", "aside", "noscript",
)  # fmt: skip


@dataclass(frozen=True, slots=True)
class Converted:
    """One source turned into markdown, with everything `source` needs."""

    markdown: str
    via: ConversionVia
    format: SourceFormat
    origin: str
    sha256: str | None = None
    # The source bytes, retained only when the caller asked to keep them.
    original_bytes: bytes | None = None
    original_name: str | None = None
    # A title the source suggested (a leading H1, a page's <title>); the
    # caller falls back to this when it was given no title of its own.
    suggested_title: str | None = None
    # The name the source file had, without its extension. None for anything
    # that came from a URL, an arXiv fetch or text typed at the command line,
    # because there is no filename there to carry.
    #
    # Separate from `suggested_title` rather than folded into its fallback
    # order, because the two answer different questions: what the document is
    # *called* and what it is *about*. A note a person wrote and named wants
    # the first; a converted paper wants the second. Concern #189.
    source_name: str | None = None


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def looks_like_url(identifier: str) -> bool:
    return urlparse(identifier).scheme in ("http", "https")


def is_supported_suffix(path: Path, extra: Sequence[str] = ()) -> bool:
    """Whether a directory walk should pick `path` up.

    `extra` is the user's own additional file types, added rather than
    substituted: the common need is one more extension - an `.ipynb`, a house
    format - not a replacement for the sixty kennis already knows.
    """
    suffix = path.suffix.lower()
    if not suffix:
        # No extension at all. A `Makefile` is real text, but so is every
        # extensionless binary, and a walk cannot tell them apart by name.
        return False
    return suffix in SUPPORTED_SUFFIXES or suffix in {
        item.lower() if item.startswith(".") else f".{item.lower()}" for item in extra
    }


def detect_format(path: Path) -> SourceFormat:
    """Classify a local file by suffix.

    Suffix rather than content sniffing: the formats that matter here are
    already unambiguous by extension, and a wrong guess on a binary file is
    caught by the converter anyway.
    """
    suffix = path.suffix.lower()
    if suffix in _BINARY_SUFFIXES:
        return _BINARY_SUFFIXES[suffix]
    if suffix in _MARKDOWN_SUFFIXES:
        return "markdown"
    if suffix in _HTML_SUFFIXES:
        return "html"
    if suffix in _TEXT_SUFFIXES:
        return "text"
    return "code"


def read_text_file(path: Path) -> str:
    """Read a text file, trying progressively more forgiving encodings.

    Reading with utf-8 alone is how a non-UTF-8 file surfaces a raw
    `UnicodeDecodeError` as a command's error message. Binary formats never
    reach here, but a text file written on a Windows box still might not be
    UTF-8.
    """
    try:
        data = path.read_bytes()
    except OSError as error:
        raise SourceUnreadable(f"could not read '{path}': {error}") from error
    for encoding in _TEXT_ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise SourceUnreadable(f"could not decode '{path}' as text in any known encoding")


# Inline markdown a heading may carry that a title should not. Converters vary
# in how much emphasis they preserve - MinerU renders a bold DOCX heading as
# `# **Title**` - and the markers would otherwise reach the title field, and
# from there every search hit, every listing line, and the filename.
_MARKDOWN_INLINE: Final = (
    re.compile(r"\[([^\]]+)\]\([^)]*\)"),  # [text](url)
    re.compile(r"\*\*(.+?)\*\*"),
    re.compile(r"__(.+?)__"),
    re.compile(r"\*(.+?)\*"),
    re.compile(r"`(.+?)`"),
)


def strip_markdown_inline(text: str) -> str:
    """Reduce one line of markdown to its plain text.

    Deliberately narrow: it unwraps emphasis and link syntax and nothing else,
    so an identifier like `snake_case_name`, whose underscores are not a
    matched pair around the whole word, survives intact.
    """
    cleaned = text
    for pattern in _MARKDOWN_INLINE:
        cleaned = pattern.sub(r"\1", cleaned)
    # Unmatched markers - a heading of literally `****` - survive the patterns
    # above, since each needs a pair with content between. Trimming them from
    # the ends leaves nothing, which the caller reads as "no usable title".
    return cleaned.strip(" *_`\t")


def title_from_markdown(markdown: str, fallback: str) -> str:
    """The document's own title, from its first top-level heading."""
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            title = strip_markdown_inline(stripped[2:])
            if title:
                return title
    return fallback


def convert_html(html: str) -> str:
    """Generic HTML to markdown for an arbitrary web page.

    Not structure-aware: a known documentation renderer has a container worth
    selecting, and that belongs to the fetcher that knows which renderer it is
    talking to. An arbitrary page has no such container, so this strips chrome
    instead.
    """
    from bs4 import BeautifulSoup
    from markdownify import markdownify

    soup = BeautifulSoup(html, "html.parser")
    for tag_name in _CHROME_TAGS:
        for node in soup.find_all(tag_name):
            node.decompose()

    body = soup.body or soup
    markdown = markdownify(
        str(body),
        heading_style="ATX",
        escape_underscores=False,
        escape_asterisks=False,
        escape_misc=False,
    )
    return re.sub(r"\n{3,}", "\n\n", markdown).strip() + "\n"


def html_title(html: str) -> str | None:
    from bs4 import BeautifulSoup

    title_tag = BeautifulSoup(html, "html.parser").find("title")
    if title_tag is None or not title_tag.text.strip():
        return None
    return " ".join(title_tag.text.split())


def convert_local_file(
    path: Path,
    *,
    converter: Converter | None = None,
    keep_original: bool = False,
    prepared_markdown: str | None = None,
) -> Converted:
    """Convert one local file of any supported format into markdown.

    `prepared_markdown` is output an earlier batch already produced for this
    path. Supplying it is what keeps a batched conversion from being repeated
    a document at a time; it is ignored for the formats the converter never
    sees.
    """
    source_format = detect_format(path)
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise SourceUnreadable(f"could not read '{path}': {error}") from error

    via: ConversionVia
    if source_format in BINARY_FORMATS:
        markdown = prepared_markdown
        if markdown is None:
            markdown = _convert_binary(path, converter or default_converter())
        via = "mineru"
    elif source_format == "html":
        markdown = convert_html(read_text_file(path))
        via = "html"
    elif source_format == "code":
        language = _FENCE_LANGUAGES.get(path.suffix.lower(), "")
        body = read_text_file(path)
        # Fenced so the chunker treats it as one block rather than reflowing
        # it as prose, and so a reader can tell code from commentary.
        markdown = f"# {path.name}\n\n```{language}\n{body.rstrip()}\n```\n"
        via = "verbatim"
    else:
        markdown = read_text_file(path)
        via = "verbatim"

    return Converted(
        markdown=markdown,
        via=via,
        format=source_format,
        # `path:` and not a bare path. Design section 4 makes `source.from` a
        # scheme plus a value, and the recoverability table keys on the
        # scheme: it is how `corpus status` counts the documents that cannot
        # be refetched, which is the number a user wants before trusting a
        # backup. A bare path has no scheme to read.
        origin=f"path:{path}",
        sha256=sha256_of(raw),
        original_bytes=raw if keep_original else None,
        original_name=path.name if keep_original else None,
        suggested_title=title_from_markdown(markdown, path.stem),
        source_name=path.stem,
    )


def _convert_binary(path: Path, converter: Converter) -> str:
    """One binary document through the converter, on its own.

    The batched path is `prepared_markdown`; this is the single-document
    fallback, and it pays the converter's whole startup cost for one file.
    """
    require_converter(converter, [path])
    batch = converter.convert([path])
    markdown = batch.markdown.get(path)
    if markdown is None:
        raise ConversionFailed(_nothing_produced(path, batch.failure_reason))
    return markdown


def _nothing_produced(path: Path, reason: str | None) -> str:
    """Why one document came back with nothing.

    `reason` is the converter's own wording when the process itself failed;
    without one the document simply produced no output, which is what an
    empty, encrypted or unsupported file looks like from here.
    """
    if reason:
        return f"could not convert '{path.name}': {reason}"
    return (
        f"no markdown was produced for '{path.name}'. "
        f"The file may be empty, encrypted, or an unsupported variant."
    )


# What a server's content type means for conversion. Keyed on the bare type,
# with parameters like `; charset=utf-8` stripped before the lookup.
_URL_BINARY_TYPES: Final[dict[str, str]] = {
    "application/pdf": ".pdf",
    "application/x-pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        ".docx"
    ),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (
        ".pptx"
    ),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
}
_URL_HTML_TYPES: Final[frozenset[str]] = frozenset(
    {"text/html", "application/xhtml+xml"}
)
_URL_TEXT_TYPES: Final[frozenset[str]] = frozenset(
    {"text/markdown", "text/x-markdown", "text/plain"}
)
# What a server says when it does not know or will not commit.
_URL_UNCOMMITTED_TYPES: Final[frozenset[str]] = frozenset(
    {"application/octet-stream", "binary/octet-stream", ""}
)


def convert_url(
    url: str, *, keep_original: bool = False, client: httpx.Client | None = None
) -> Converted:
    """Fetch one URL and convert whatever came back.

    **The content type decides, not the suffix.** A local path is a name the
    user typed and vouched for; a URL is a request whose answer only the
    server knows, and a link ending `.pdf` that returns an HTML paywall page
    is the common case rather than the exotic one. This used to run
    `convert_html` over `response.text` whatever arrived, so a URL serving a
    PDF stored `%PDF-1.4 ...` as the document body, labelled `via: html`, and
    indexed it.

    `client` is supplied by the caller so a test can hand over a transport
    that never touches the network; left out, one is built and closed here.
    """
    owned = client is None
    active = client or httpx.Client(
        headers={"User-Agent": _USER_AGENT}, follow_redirects=True
    )
    try:
        response = active.get(url, timeout=_REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise SourceUnreadable(f"could not fetch '{url}': {error}") from error
    finally:
        if owned:
            active.close()

    declared = response.headers.get("content-type", "").split(";")[0].strip().lower()
    suffix = _binary_suffix_for(declared, response.content)
    if suffix is not None:
        return _converted_download(url, response.content, suffix, keep_original)
    if declared in _URL_TEXT_TYPES:
        return _converted_text(url, response, keep_original)
    if declared in _URL_HTML_TYPES or declared in _URL_UNCOMMITTED_TYPES:
        return _converted_html(url, response, keep_original)
    raise SourceUnreadable(
        f"'{url}' answered with '{declared}', which kennis has no converter "
        f"for. Download it yourself and add the file instead."
    )


def _binary_suffix_for(declared: str, content: bytes) -> str | None:
    """The file suffix a downloaded body should be converted as, if any.

    Falls back to sniffing the first bytes when the server declined to
    commit: `application/octet-stream` for a PDF is common enough that
    trusting the header alone would send real PDFs to the HTML converter.
    """
    if declared in _URL_BINARY_TYPES:
        return _URL_BINARY_TYPES[declared]
    if declared in _URL_UNCOMMITTED_TYPES and content.startswith(b"%PDF"):
        return ".pdf"
    return None


def _converted_download(
    url: str, content: bytes, suffix: str, keep_original: bool
) -> Converted:
    """A fetched binary, converted by the same path a local one takes.

    Written to a temporary file because `convert_local_file` and the
    converter behind it both work on paths - MinerU is a subprocess and
    cannot be handed bytes. The file is removed even when conversion raises,
    so a failed fetch leaves nothing behind.
    """
    with tempfile.TemporaryDirectory(prefix="kennis-fetch-") as scratch:
        downloaded = Path(scratch) / f"download{suffix}"
        downloaded.write_bytes(content)
        converted = convert_local_file(downloaded, keep_original=keep_original)

    return replace(
        converted,
        # The URL, not the temporary path that no longer exists: `source.from`
        # is what says whether a document could be fetched again.
        origin=f"url:{url}",
        original_name=Path(urlparse(url).path).name or f"download{suffix}"
        if keep_original
        else None,
        suggested_title=converted.suggested_title
        or title_from_markdown(converted.markdown, urlparse(url).netloc or url),
    )


def _converted_text(
    url: str, response: httpx.Response, keep_original: bool
) -> Converted:
    """Markdown or plain text, taken as it is.

    Running an HTML converter over markdown strips nothing and mangles what
    it does not understand, so the only correct thing to do is nothing.
    """
    markdown = response.text
    return Converted(
        markdown=markdown,
        via="verbatim",
        format="markdown",
        origin=f"url:{url}",
        sha256=sha256_of(response.content),
        original_bytes=response.content if keep_original else None,
        original_name="original.md" if keep_original else None,
        suggested_title=title_from_markdown(markdown, urlparse(url).netloc or url),
    )


def _converted_html(
    url: str, response: httpx.Response, keep_original: bool
) -> Converted:
    html = response.text
    markdown = convert_html(html)
    fallback = html_title(html) or urlparse(url).netloc or url
    return Converted(
        markdown=markdown,
        via="html",
        format="html",
        origin=f"url:{url}",
        sha256=sha256_of(response.content),
        original_bytes=response.content if keep_original else None,
        original_name="original.html" if keep_original else None,
        suggested_title=title_from_markdown(markdown, fallback),
    )
