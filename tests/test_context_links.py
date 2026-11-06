"""kennis:// links to context passages in a project's bundle (#623).

A corpus passage has had a link since #595. A context passage is a file in a
project's `.context/`, addressed by where it is rather than by an
identifier, so its link names the project and the path. A pack's context is
a copy in the bundle (#624), so it has no link form of its own. `kennis
search` prints it, `kennis cite` and the MCP `cite`
tool write it, and `kennis open` shows the passage it names (Brian,
2026-11-05: an agent's citation is how the person sees exactly what it
means).
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.links import (
    ContextTarget,
    LinkTarget,
    NotAKennisLink,
    context_link,
    link_to,
    target_of,
)

# --- the link itself ------------------------------------------------------


def test_a_context_link_reads_back_as_the_project_path_and_chunk() -> None:
    """A project's name may hold `/` (#512) and a path a space, so both are
    percent-encoded, and both survive the round trip."""
    link = context_link("PhD/tron", "discussions/A burst (**).md", 3)

    assert link.startswith("kennis://context/")
    assert " " not in link
    assert target_of(link) == ContextTarget(
        project="PhD/tron", path="discussions/A burst (**).md", chunk=3
    )


def test_a_colon_in_a_file_name_is_an_ordinary_character() -> None:
    link = context_link("tron", "RX J1726 (**): a pair.md", 0)

    assert target_of(link) == ContextTarget("tron", "RX J1726 (**): a pair.md", 0)


def test_the_corpus_link_is_unchanged() -> None:
    assert link_to("abc123", 4) == "kennis://open/abc123/4"
    assert target_of("kennis://open/abc123/4") == LinkTarget("abc123", 4)


@pytest.mark.parametrize(
    "text",
    [
        "kennis://context/p/1",  # no path
        "kennis://context/p/1?path=",  # an empty path
        "kennis://context/p/1?path=../secrets.md",
        "kennis://context/p/1?path=a/../../b.md",
        "kennis://context/p/1?path=%2Fetc%2Fpasswd",  # absolute
        "kennis://context/p/1?path=a%5Cb.md",  # a backslash
        "kennis://context/p/1?path=a//b.md",  # an empty segment
        "kennis://context/p/1?path=C%3Aa.md",  # a Windows drive
        "kennis://context/p/1?path=a.md&project=q",  # a second key
        "kennis://context/p/1?path=a.md#top",  # a fragment
        "kennis://context/p/x?path=a.md",  # a chunk that is not a number
        "kennis://context//1?path=a.md",  # no project
        "kennis://pack/tron/1?path=a.md",  # the store's form, gone (#624)
        "kennis://elsewhere/p/1?path=a.md",
    ],
)
def test_anything_else_is_refused(text: str) -> None:
    with pytest.raises(NotAKennisLink):
        target_of(text)


# --- a project beside a corpus ---------------------------------------------

NOTE_PATH = "discussions/A burst (**).md"
NOTE = """\
---
title: 'A burst: is it coherent?'
owner: user
---

## Lightcurve

The flare rose for a minute and a half and decayed over two and a half.

## Spectrum

The emission stops at a sharp edge near 1.25 GHz, which reads as a maser.
"""


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A corpus, and a project called `tron` whose bundle holds one note,
    indexed; the working directory is the project."""
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    monkeypatch.setenv("KENNIS_CHUNKING_SIZE", "100")
    monkeypatch.setenv("KENNIS_CHUNKING_OVERLAP", "0")
    monkeypatch.delenv("KENNIS_CONTEXT_DIR", raising=False)
    run = CliRunner()
    assert run.invoke(main, ["corpus", "init"]).exit_code == 0
    root = tmp_path / "tron"
    root.mkdir()
    monkeypatch.chdir(root)
    assert run.invoke(main, ["context", "init", "--here"]).exit_code == 0
    note = root / ".context" / NOTE_PATH
    note.parent.mkdir(parents=True)
    note.write_text(NOTE, encoding="utf-8")
    indexed = run.invoke(main, ["context", "index"])
    assert indexed.exit_code == 0, indexed.output
    return root


_HANDLE = re.compile(r"path=(?P<path>\S.*?) chunk=(?P<chunk>[0-9]+)$")


def test_a_context_hit_prints_its_chunk_and_the_link_that_opens_it(
    project: Path,
) -> None:
    found = CliRunner().invoke(
        main, ["search", "sharp edge maser", "--collection", "context"]
    )

    assert found.exit_code == 0, found.output
    lines = found.output.splitlines()
    handles = [
        (index, matched)
        for index, line in enumerate(lines)
        if (matched := _HANDLE.search(line)) is not None
    ]
    assert handles, found.output
    for index, handle in handles:
        target = target_of(lines[index + 1].strip())
        assert target == ContextTarget(
            project="tron",
            path=handle.group("path").removeprefix(".context/"),
            chunk=int(handle.group("chunk")),
        )


def spectrum_chunk(project: Path) -> int:
    found = CliRunner().invoke(
        main, ["search", "sharp edge maser", "--collection", "context"]
    )
    matched = _HANDLE.search(found.output.splitlines()[_first_handle(found.output)])
    assert matched is not None
    return int(matched.group("chunk"))


def _first_handle(output: str) -> int:
    return next(
        index
        for index, line in enumerate(output.splitlines())
        if _HANDLE.search(line) is not None
    )


def test_kennis_cite_takes_a_context_hit_as_search_prints_it(project: Path) -> None:
    chunk = spectrum_chunk(project)

    cited = CliRunner().invoke(
        main, ["cite", f"path=.context/{NOTE_PATH}", f"chunk={chunk}"]
    )

    assert cited.exit_code == 0, cited.output
    assert '"A burst: is it coherent?"' in cited.output
    assert "Spectrum" in cited.output
    assert context_link("tron", NOTE_PATH, chunk) in cited.output


def test_kennis_cite_takes_a_context_link(project: Path) -> None:
    link = context_link("tron", NOTE_PATH, spectrum_chunk(project))

    cited = CliRunner().invoke(main, ["cite", link])

    assert cited.exit_code == 0, cited.output
    assert link in cited.output


def test_another_project_s_hit_is_cited_by_its_whole_path(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A search from elsewhere prints another project's file by its whole
    path, and that is what is given back."""
    chunk = spectrum_chunk(project)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    whole = project / ".context" / NOTE_PATH

    cited = CliRunner().invoke(main, ["cite", f"path={whole}", f"chunk={chunk}"])

    assert cited.exit_code == 0, cited.output
    assert context_link("tron", NOTE_PATH, chunk) in cited.output


def test_a_file_the_bundle_does_not_hold_is_refused(project: Path) -> None:
    cited = CliRunner().invoke(main, ["cite", "path=.context/nothing.md", "chunk=0"])

    assert cited.exit_code != 0
    assert "nothing.md" in cited.output


def test_the_tool_cites_a_context_hit_by_its_path(project: Path) -> None:
    from kennis.mcp.tools.cite import CiteRequest, cite

    chunk = spectrum_chunk(project)

    answer = cite([CiteRequest(path=f".context/{NOTE_PATH}", chunk=chunk)])

    link = context_link("tron", NOTE_PATH, chunk)
    assert f"link: {link}" in answer
    assert 'markdown: ["A burst: is it coherent?", ' in answer
    assert f"]({link})" in answer


def test_the_tool_refuses_a_request_naming_two_handles(project: Path) -> None:
    from kennis.mcp.tools.cite import CiteRequest, cite

    answer = cite([CiteRequest(document_id="abc", path=".context/a.md")])

    assert "exactly one of" in answer


# --- opening ----------------------------------------------------------------


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    import kennis.client.process as process
    import kennis.gui.browser as browser
    from kennis.client import api
    from test_links import RECORD

    addresses: list[str] = []
    monkeypatch.setattr(process, "ensure_service", lambda root, **_: RECORD)
    monkeypatch.setattr(browser, "open_quietly", addresses.append)
    monkeypatch.setattr(browser.webbrowser, "open", lambda *_, **__: pytest.fail())
    monkeypatch.setattr(api, "show_in_window", lambda *_, **__: False)
    return addresses


def test_a_context_link_opens_the_passage_in_its_project(
    project: Path, opened: list[str]
) -> None:
    link = context_link("tron", NOTE_PATH, 1)

    result = CliRunner().invoke(main, ["open", link])

    assert result.exit_code == 0, result.output
    (address,) = opened
    parts = urlsplit(address)
    assert unquote(parts.path) == f"/bundle/{NOTE_PATH}"
    assert parse_qs(parts.query) == {
        "project": ["tron"],
        "chunk": ["1"],
        "token": ["the-token"],
    }
    assert parts.fragment == "chunk-1"


def test_a_link_to_an_unknown_project_is_refused(
    project: Path, opened: list[str]
) -> None:
    result = CliRunner().invoke(main, ["open", context_link("nowhere", NOTE_PATH, 0)])

    assert result.exit_code != 0
    assert opened == []
    assert "nowhere" in result.output


def test_a_link_to_a_file_the_project_does_not_hold_is_refused(
    project: Path, opened: list[str]
) -> None:
    result = CliRunner().invoke(main, ["open", context_link("tron", "gone.md", 0)])

    assert result.exit_code != 0
    assert opened == []
    assert "gone.md" in result.output


def test_the_link_search_prints_is_the_one_open_follows(
    project: Path, opened: list[str]
) -> None:
    """End to end: the link under a hit, given to `kennis open` as printed,
    opens that hit's file at that chunk."""
    found = CliRunner().invoke(main, ["search", "maser", "--collection", "context"])
    line = found.output.splitlines()[_first_handle(found.output) + 1].strip()

    result = CliRunner().invoke(main, ["open", *shlex.split(line)])

    assert result.exit_code == 0, result.output
    (address,) = opened
    assert unquote(urlsplit(address).path) == f"/bundle/{NOTE_PATH}"


def test_a_request_the_tool_cannot_resolve_costs_only_itself(project: Path) -> None:
    """Its refusal stands at its own position, and the passage after it is
    cited and numbered as asked."""
    from kennis.mcp.tools.cite import CiteRequest, cite

    chunk = spectrum_chunk(project)

    answer = cite(
        [
            CiteRequest(path="not-in-a-bundle.md", chunk=0),
            CiteRequest(path=f".context/{NOTE_PATH}", chunk=chunk),
        ]
    )

    first, second = answer.split("\n\n")
    assert first.startswith("[1] not-in-a-bundle.md")
    assert second.startswith('[2] "A burst: is it coherent?"')
