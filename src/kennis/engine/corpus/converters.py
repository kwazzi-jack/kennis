"""Turning a binary document into markdown, behind one interface.

v0.1 has exactly one implementation, MinerU. Hosted conversion is a second
behind the same interface, added when credentials exist, and the interface is
declared now so that the add path is written against the shape rather than
against MinerU.

**A converter takes a batch, not a document.** That is the design rather than
a convenience: MinerU spends around twenty seconds loading its model stack
before it converts anything, so a process per document pays that toll every
time - measured on a 19-page paper, 41 seconds for one document alone against
88 for four in one call. Hosted conversion will want batching for a different
reason, one request beating several.

**A batch reports per document.** A converter converts what it can and records
the rest, so a path missing from `markdown` is that document's failure alone
and must not cost the others. `failure_reason` is the process's own wording
when it exited badly, which is the only context a bare "produced nothing"
would lack.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Protocol, runtime_checkable

import httpx

from kennis.engine.corpus.schema import SourceFormat
from kennis.engine.errors import ConversionFailed, ConverterUnavailable
from kennis.engine.settings import credential, load_settings


@dataclass(frozen=True, slots=True)
class ConversionBatch:
    """What one converter run produced, per document."""

    markdown: dict[Path, str]
    # Page-one text per document, page furniture included. Carried out of the
    # run's temporary directory because that is the only place it exists: the
    # content list is discarded with the run, and the markdown never had it.
    front_page: dict[Path, str] = field(default_factory=dict)
    # The process's own wording when it exited non-zero, whether or not it
    # still produced output for some documents.
    failure_reason: str | None = None


@runtime_checkable
class Converter(Protocol):
    """What the add path needs from any converter.

    A Protocol rather than a base class so the engine needs no registry that
    imports every implementation - the hosted one will want an HTTP client and
    credentials, and nothing should pay for that to convert a PDF locally.
    """

    name: str
    formats: frozenset[SourceFormat]

    def is_available(self) -> bool:
        """Whether this converter can run at all on this machine."""
        ...

    def install_hint(self) -> str:
        """The command that would make it available."""
        ...

    def convert(
        self, paths: Sequence[Path], *, page_limit: int | None = None
    ) -> ConversionBatch:
        """Convert a whole batch in one run."""
        ...


# ---------------------------------------------------------------------------
# MinerU
# ---------------------------------------------------------------------------
#
# Driven through its command line rather than its Python interface. MinerU
# imports torch and its model stack at import time, which would make every
# kennis invocation pay for a dependency almost no command uses; a subprocess
# also keeps a model crash from taking the process down with it, and makes the
# tool's absence a fact to report rather than an ImportError.

_MINERU_FORMATS: Final[dict[str, SourceFormat]] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
}

MINERU_FORMATS: Final[frozenset[SourceFormat]] = frozenset(_MINERU_FORMATS.values())

_INSTALL_HINT: Final = "uv sync --extra mineru"

# Settings whose value is "auto" mean "let MinerU decide", which MinerU
# expects to be expressed by the variable being *absent*. Passing the literal
# string through is an error it rejects outright:
#   MINERU_MODEL_SOURCE=auto is not supported. Unset MINERU_MODEL_SOURCE to
#   use auto detection once, or set it to huggingface/modelscope/local.
# The variable is actively removed rather than merely not set, so an "auto"
# already exported in the user's shell cannot reach MinerU either.
_AUTO: Final = "auto"

_ENVIRONMENT_VARIABLES: Final[dict[str, str]] = {
    "device_mode": "MINERU_DEVICE_MODE",
    "model_source": "MINERU_MODEL_SOURCE",
}

# How long a run gets before kennis cancels it. Two terms, because the cost
# has two: the model stack loads once per run (~20s measured, far worse on a
# cold cache that has to download it), then each document is converted (~16s
# for a full pass, ~1.2s for a two-page survey). Both measured on boepie's
# hardware and multiplied generously - the point is to catch a converter that
# has stopped making progress, not to police a slow machine. Without a
# timeout, one wedged conversion hangs the whole command with no output and
# nothing to interrupt but Ctrl-C.
_STARTUP_GRACE_SECONDS: Final = 900
_SECONDS_PER_DOCUMENT: Final = 300

# How much of the original filename a staged copy keeps. The index prefix is
# what makes the name unique; the rest is there only so MinerU's own error
# output names something the user recognises, and truncating is easier than
# discovering each filesystem's own limit.
_STAGED_STEM_LIMIT: Final = 100

# Block kinds MinerU classifies as page furniture rather than body text. These
# are exactly what the rendered markdown throws away, and exactly where a
# paper stamps its own identity: `arXiv:1805.03410v2 [astro-ph.IM]` arrives as
# `page_aside_text`, a journal DOI as a `page_footer`, an ADS bibcode on a
# scanned paper as a `page_header`.
_FURNITURE_TYPES: Final = frozenset(
    {"page_header", "page_footer", "page_footnote", "page_aside_text", "page_number"}
)


@dataclass(frozen=True, slots=True)
class MineruOptions:
    """The knobs MinerU takes, in the form it wants them.

    Settings will supply these in a later milestone; until then a caller
    passes them or takes the defaults.
    """

    device_mode: str = _AUTO
    backend: str = "pipeline"
    model_source: str = _AUTO


class MineruConverter:
    """The local binary-document converter."""

    name = "mineru"
    formats = MINERU_FORMATS

    def __init__(self, options: MineruOptions | None = None) -> None:
        self.options = options or MineruOptions()

    def is_available(self) -> bool:
        return shutil.which(self.name) is not None

    def install_hint(self) -> str:
        return _INSTALL_HINT

    def convert(
        self, paths: Sequence[Path], *, page_limit: int | None = None
    ) -> ConversionBatch:
        """Convert every path in one MinerU process.

        The caller decides how large a run is, because MinerU writes nothing
        until the whole run finishes: a run is the unit of progress and the
        unit lost to an interruption.

        `page_limit` stops MinerU after that many pages. Used to survey a
        batch before committing to converting it - a paper states its own
        identity on page one, so two pages are enough to learn what every
        document in a folder *is*. The markdown that comes back is a fragment
        and is meant to be discarded; the front page is the point.
        """
        if not paths:
            return ConversionBatch(markdown={})
        require_converter(self, paths)

        with tempfile.TemporaryDirectory(prefix="kennis-mineru-") as temporary:
            staged_dir = Path(temporary) / "input"
            output_dir = Path(temporary) / "output"
            staged_dir.mkdir()
            output_dir.mkdir()
            staged = _stage(paths, staged_dir)

            completed = self._run(staged_dir, output_dir, len(paths), page_limit)
            markdown, front_page = _collect(staged, output_dir)

        reason = _failure_reason(completed) if completed.returncode != 0 else None
        if not markdown and reason is not None:
            raise ConversionFailed(f"mineru failed: {reason}")
        return ConversionBatch(
            markdown=markdown, front_page=front_page, failure_reason=reason
        )

    def _run(
        self,
        staged_dir: Path,
        output_dir: Path,
        document_count: int,
        page_limit: int | None,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            self.name,
            "-p",
            str(staged_dir),
            "-o",
            str(output_dir),
            "-b",
            self.options.backend,
        ]
        if page_limit is not None:
            command += ["-s", "0", "-e", str(page_limit - 1)]
        timeout_seconds = _STARTUP_GRACE_SECONDS + (
            _SECONDS_PER_DOCUMENT * document_count
        )
        try:
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                env=self._environment(),
                check=False,
                timeout=timeout_seconds,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired as expired:
            plural = "document" if document_count == 1 else "documents"
            raise ConversionFailed(
                f"mineru did not finish converting {document_count} {plural} "
                f"within {timeout_seconds}s and was cancelled. Nothing was "
                f"written. Convert the documents in smaller batches."
            ) from expired
        except OSError as error:
            raise ConversionFailed(f"could not run mineru: {error}") from error

    def _environment(self) -> dict[str, str]:
        """The child environment for one run."""
        environment = dict(os.environ)
        for setting, variable in _ENVIRONMENT_VARIABLES.items():
            value = getattr(self.options, setting)
            if value == _AUTO:
                environment.pop(variable, None)
            else:
                environment[variable] = value
        return environment


# ---------------------------------------------------------------------------
# Datalab
# ---------------------------------------------------------------------------
#
# The hosted alternative, for a machine that will not carry the local model
# stack. It converts a document by **sending it to a third party**, which is
# why it is never a default: the backend is a setting and the key is a
# credential, so choosing it is two deliberate acts.
#
# Unlike MinerU, there is no batch endpoint. A batch is one request per
# document, and `ConversionBatch` fits that unchanged because it already
# reports per document. The module docstring's guess that hosted conversion
# would want batching because "one request beats several" was wrong.

_DATALAB_URL: Final = "https://www.datalab.to/api/v1/convert"
_DATALAB_KEY_VARIABLE: Final = "DATALAB_API_KEY"

# What the API accepts. Narrower than its marketing copy, which says "PDFs,
# Word documents, spreadsheets and images" without naming extensions, so this
# lists only what kennis has a `SourceFormat` for anyway.
DATALAB_FORMATS: Final[frozenset[SourceFormat]] = frozenset(
    {"pdf", "docx", "pptx", "xlsx"}
)

# A submitted document is not converted when the response returns. The server
# hands back a URL to poll, and these bound the wait: 2s is the interval the
# API's own example uses, and 300 polls is its example ceiling, so a document
# gets ten minutes before kennis gives up. Unbounded polling is the one way
# an HTTP call becomes a hang, which is what the timeout rule forbids.
_POLL_SECONDS: Final = 2.0
_MAX_POLLS: Final = 300
_REQUEST_TIMEOUT: Final = 120.0


class DatalabConverter:
    """The hosted binary-document converter.

    `front_page` is always empty and that is a capability difference, not an
    oversight. MinerU returns a content list that classifies page furniture,
    which is exactly where a paper stamps its arXiv id or DOI; this API
    returns markdown. A caller must not read the empty mapping as "this paper
    states no identity" - it means "this converter cannot tell".
    """

    name = "datalab"
    formats = DATALAB_FORMATS

    def __init__(
        self,
        api_key: str | None = None,
        *,
        client: httpx.Client | None = None,
        poll_seconds: float = _POLL_SECONDS,
        max_polls: int = _MAX_POLLS,
    ) -> None:
        self.api_key = credential(_DATALAB_KEY_VARIABLE) if api_key is None else api_key
        self._client = client
        self._poll_seconds = poll_seconds
        self._max_polls = max_polls

    def is_available(self) -> bool:
        """A key is the whole requirement. There is nothing to install."""
        return bool(self.api_key)

    def install_hint(self) -> str:
        return "kennis config init"

    def convert(
        self, paths: Sequence[Path], *, page_limit: int | None = None
    ) -> ConversionBatch:
        """Convert each path, one request each, and report per document.

        `page_limit` is accepted and ignored: the API takes no page range, so
        a survey costs a whole conversion. The caller's survey is a smaller
        saving than the round trip either way.
        """
        if not paths:
            return ConversionBatch(markdown={})
        require_converter(self, paths)

        markdown: dict[Path, str] = {}
        reasons: list[str] = []
        client = self._client or httpx.Client(timeout=_REQUEST_TIMEOUT)
        try:
            for path in paths:
                try:
                    markdown[path] = self._convert_one(client, path)
                except ConversionFailed as failed:
                    reasons.append(f"{path.name}: {failed}")
        finally:
            if self._client is None:
                client.close()

        reason = "; ".join(reasons) if reasons else None
        if not markdown and reason is not None:
            raise ConversionFailed(f"datalab failed: {reason}")
        return ConversionBatch(markdown=markdown, failure_reason=reason)

    def _convert_one(self, client: httpx.Client, path: Path) -> str:
        check_url = self._submit(client, path)
        return self._await_markdown(client, check_url, path)

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self.api_key}

    def _submit(self, client: httpx.Client, path: Path) -> str:
        try:
            response = client.post(
                _DATALAB_URL,
                headers=self._headers(),
                files={"file": (path.name, path.read_bytes())},
                data={"output_format": "markdown", "mode": "balanced"},
                timeout=_REQUEST_TIMEOUT,
            )
        except httpx.HTTPError as error:
            raise ConversionFailed(f"could not reach datalab: {error}") from error
        if response.status_code >= 400:
            raise ConversionFailed(
                f"datalab refused the document ({response.status_code})"
            )
        check_url = _as_text(response.json().get("request_check_url"))
        if not check_url:
            raise ConversionFailed("datalab returned no url to poll")
        return check_url

    def _await_markdown(self, client: httpx.Client, url: str, path: Path) -> str:
        """Poll until the status settles, bounded.

        The key goes on this request too. It is a second, separate call and
        the service rejects an unauthenticated one, so a key sent only on
        submit converts nothing.
        """
        for _ in range(self._max_polls):
            try:
                result = client.get(
                    url, headers=self._headers(), timeout=_REQUEST_TIMEOUT
                ).json()
            except httpx.HTTPError as error:
                raise ConversionFailed(f"could not reach datalab: {error}") from error
            if result.get("success") is False or result.get("status") == "failed":
                raise ConversionFailed(
                    _as_text(result.get("error")) or "datalab could not convert it"
                )
            if result.get("status") == "complete":
                converted = _as_text(result.get("markdown"))
                if not converted:
                    raise ConversionFailed("datalab returned no markdown")
                return converted
            time.sleep(self._poll_seconds)
        raise ConversionFailed(
            f"datalab did not finish converting {path.name} within "
            f"{int(self._max_polls * self._poll_seconds)}s and was given up on"
        )


def _as_text(value: object) -> str:
    """A JSON field as a string, or empty when it is anything else.

    The response is other people's data: a field may be absent, null, or a
    number, and none of those should become the string "None" halfway down a
    document.
    """
    return value if isinstance(value, str) else ""


def require_converter(converter: Converter, paths: Sequence[Path]) -> None:
    """Fail now if `converter` is needed and missing, rather than once per file.

    A folder of fifty PDFs would otherwise produce fifty copies of the same
    install instructions, one at a time, over a run that cannot succeed. One
    message, built here, so intake's single-document path and the batch path
    cannot word it differently.
    """
    if not paths or converter.is_available():
        return
    formats = sorted({path.suffix.lstrip(".").upper() for path in paths})
    raise ConverterUnavailable(
        f"{converter.name} is required to convert {'/'.join(formats)} files "
        f"and is not installed. Convert the documents yourself and add the "
        f"resulting markdown instead, or install it.",
        resolution=converter.install_hint(),
    )


def default_converter() -> Converter:
    """The converter kennis uses when a caller names none.

    One indirection, so choosing between them is a change here rather than at
    every call site. The choice is `conversion.backend`, which defaults to
    the local one: sending a document to a third party is something a user
    opts into, never something a default does for them.
    """
    if load_settings().conversion.backend == "datalab":
        return DatalabConverter()
    return MineruConverter()


def _stage(paths: Sequence[Path], staged_dir: Path) -> dict[str, Path]:
    """Present a batch as one directory, and map the output back.

    `-p` takes a single path, so several documents can only be handed over as
    a directory. They are renamed on the way in because MinerU names its
    output directory after the input's stem: two `README.pdf` from different
    folders would otherwise write to the same place and one would silently
    win. Hard-linked where the filesystem allows it, since the alternative is
    copying every source into the temporary directory.
    """
    staged: dict[str, Path] = {}
    for index, path in enumerate(paths):
        target = staged_dir / (
            f"{index:04d}-{path.stem[:_STAGED_STEM_LIMIT]}{path.suffix.lower()}"
        )
        try:
            os.link(path, target)
        except OSError:
            # A different filesystem, or one without hard links.
            shutil.copy2(path, target)
        staged[target.stem] = path
    return staged


def _collect(
    staged: dict[str, Path], output_dir: Path
) -> tuple[dict[Path, str], dict[Path, str]]:
    """The markdown and page-one text MinerU produced, keyed by original path.

    MinerU nests each document's output under a directory named after its
    input stem, at a depth that varies by version and backend, so the markdown
    is found by searching that directory rather than at a fixed path. A run
    can leave more than one markdown file there; the largest is the document.
    """
    markdown: dict[Path, str] = {}
    front_page: dict[Path, str] = {}
    for stem, original in staged.items():
        produced = sorted((output_dir / stem).rglob("*.md"))
        if not produced:
            continue
        largest = max(produced, key=lambda candidate: candidate.stat().st_size)
        markdown[original] = largest.read_text(encoding="utf-8", errors="replace")
        front_page[original] = _front_page_text(largest)
    return markdown, front_page


def _failure_reason(completed: subprocess.CompletedProcess[str]) -> str:
    """The human-readable reason out of a failed run.

    MinerU reports task failures as a JSON blob on one line, far too noisy to
    hand a user verbatim; its `error` field is the part that says what went
    wrong. Falls back to the last line of output when the blob is not JSON,
    and to the exit code when there is no output at all.
    """
    output = (completed.stderr or "") + "\n" + (completed.stdout or "")
    for line in reversed(output.strip().splitlines()):
        start = line.find("{")
        if start == -1:
            continue
        try:
            payload = json.loads(line[start:])
        except json.JSONDecodeError:
            continue
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, str) and error.strip():
            return error.strip()

    lines = output.strip().splitlines()
    return lines[-1].strip() if lines else f"exit code {completed.returncode}"


def _front_page_text(markdown_path: Path) -> str:
    """Everything MinerU read off page one, including what it did not render.

    A paper's own identifier is systematically *absent* from the converted
    markdown, because MinerU classifies the `arXiv:...` stamp as page
    furniture and furniture is not body text. It survives in the content list
    beside the markdown, which is the only reason a local PDF can be
    identified at all.

    Only page one. A bibliography offers dozens of other people's identifiers
    and every one of them is a wrong answer, so the search is confined to the
    page where a paper states its own.
    """
    for suffix in ("_content_list_v2.json", "_content_list.json"):
        path = markdown_path.with_name(f"{markdown_path.stem}{suffix}")
        if not path.is_file():
            continue
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(parsed, list):
            continue
        return (
            _front_page_of_v2(parsed)
            if suffix.endswith("_v2.json")
            else _front_page_of_v1(parsed)
        )
    return ""


def _front_page_of_v2(pages: list[Any]) -> str:
    """First-page text from a `_content_list_v2.json`, furniture first."""
    furniture: list[str] = []
    body: list[str] = []
    for block in pages[0] if pages and isinstance(pages[0], list) else []:
        if not isinstance(block, dict):
            continue
        text = _v2_block_text(block)
        if not text:
            continue
        target = furniture if block.get("type") in _FURNITURE_TYPES else body
        target.append(text)
    return "\n".join(furniture + body)


def _v2_block_text(block: dict[str, Any]) -> str:
    """The plain text of one v2 content block, whatever kind it is.

    v2 nests a block's pieces under a key named after the block's own type
    (`{"type": "page_header", "content": {"page_header_content": [...]}}`), so
    the key has to be built from the type rather than looked up by name.
    """
    kind = str(block.get("type", ""))
    content = block.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, dict):
        return ""
    pieces = content.get(f"{kind}_content")
    if not isinstance(pieces, list):
        return ""
    return " ".join(
        str(piece.get("content", "")) for piece in pieces if isinstance(piece, dict)
    )


def _front_page_of_v1(blocks: list[Any]) -> str:
    """First-page text from the older flat `_content_list.json`.

    v1 has no notion of furniture - every block is `text` or `image` with a
    `page_idx` - so the ordering v2 allows is not available here. It still
    carries the aside the markdown drops, which is the part that matters.
    """
    return "\n".join(
        str(block.get("text", ""))
        for block in blocks
        if isinstance(block, dict) and block.get("page_idx") == 0 and block.get("text")
    )
