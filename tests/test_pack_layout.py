"""A pack file kennis writes is readable (Brian, 2026-10-27, #558).

Each entry kennis writes is a mapping in braces with one key per line, in
one order per section - for a paper the identifier first and the authors,
a list, last - and set off from the next by a blank line. An entry kennis
changes is written again whole in that form; what lies between entries is
the person's and stays. `kennis pack format` puts every entry in that form.
Non-ASCII stays escaped: "it is still a system file" (Brian, 2026-10-28).

Nothing here reaches a host: every client is an `httpx.MockTransport`.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import yaml
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.engine.corpus.add import AddOptions
from kennis.engine.errors import PackInvalid
from kennis.engine.events import Outcome
from kennis.engine.pack.editing import add_to_pack, remove_from_pack
from kennis.engine.pack.formatting import format_pack
from kennis.engine.pack.schema import LiteratureEntry, load_pack
from kennis.engine.pack.update import GENERATED_MARKER, update_pack
from kennis.engine.refusals import ShippedTwice

HEADER = (
    'kennis:\n  schema_version: 1\npack:\n  id: alpha\n  name: n\n  version: "1.0.0"\n'
)

FEED = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
    "<id>http://arxiv.org/abs/1101.1764v1</id>"
    "<published>2011-01-10T12:00:00Z</published>"
    "<title>Revisiting the RIME</title>"
    "<author><name>Oleg Smirnov</name></author>"
    "<author><name>Ines Pastor</name></author>"
    "</entry></feed>"
)


def arxiv() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if "1101.1764" in str(request.url) and "/html/" not in str(request.url):
            return httpx.Response(
                200, text=FEED, headers={"content-type": "application/atom+xml"}
            )
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def nowhere() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"asked {request.url}")

    return httpx.Client(transport=httpx.MockTransport(handler))


def a_pack(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "alpha.ken.yml"
    path.write_text(f"{HEADER}{body}", encoding="utf-8")
    return path


def authored(path: Path) -> str:
    return path.read_text(encoding="utf-8").partition(GENERATED_MARKER)[0]


def updated(path: Path) -> None:
    update_pack(path, arxiv=arxiv(), request_delay_seconds=0)


DESCRIBED = (
    "    - {\n"
    '        identifier: "1101.1764",\n'
    '        citekey: "smirnovRevisitingRime2011",\n'
    '        title: "Revisiting the RIME",\n'
    "        year: 2011,\n"
    "        authors: [\n"
    '          "Oleg Smirnov",\n'
    '          "Ines Pastor",\n'
    "        ],\n"
    "      }\n"
)


# ---------------------------------------------------------------------------
# What kennis writes
# ---------------------------------------------------------------------------


def test_a_described_paper_is_one_braced_entry_identifier_first_authors_last(
    tmp_path: Path,
):
    path = a_pack(tmp_path, "corpus:\n  literature:\n    - identifier: '1101.1764'\n")

    updated(path)

    assert "  literature:\n" + DESCRIBED in path.read_text(encoding="utf-8")


def test_the_authors_own_fields_take_their_place_in_the_order(tmp_path: Path):
    path = a_pack(
        tmp_path,
        "corpus:\n  literature:\n    - group: rime\n      identifier: '1101.1764'\n",
    )

    updated(path)

    written = yaml.safe_load(path.read_text(encoding="utf-8"))
    entry = written["corpus"]["literature"][0]
    assert list(entry) == [
        "identifier",
        "citekey",
        "title",
        "year",
        "group",
        "authors",
    ]
    assert entry["group"] == "rime"


def test_an_entry_on_one_line_is_described_too(tmp_path: Path):
    """It was refused, because a field had no line of its own to go on;
    now the entry is written again whole."""
    path = a_pack(tmp_path, "corpus:\n  literature:\n    - {identifier: '1101.1764'}\n")

    updated(path)

    assert DESCRIBED in path.read_text(encoding="utf-8")


def test_entries_kennis_adds_are_set_apart_by_a_blank_line(tmp_path: Path):
    path = a_pack(tmp_path, "corpus:\n  literature: []\n")

    add_to_pack(
        path,
        "literature",
        ["2101.00001", "doi:10.1093/mnras/staf2144."],
        AddOptions(),
        arxiv=nowhere_but_404(),
        request_delay_seconds=0,
    )

    assert (
        "  literature:\n"
        "    - {\n"
        '        identifier: "2101.00001",\n'
        "      }\n"
        "\n"
        "    - {\n"
        '        identifier: "10.1093/mnras/staf2144",\n'
        "      }\n"
    ) in path.read_text(encoding="utf-8")


def nowhere_but_404() -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(404))
    )


def test_an_identifier_kennis_writes_is_written_one_way(tmp_path: Path):
    """`doi:`, a trailing full stop and an arXiv DOI each name a paper that
    has one plain spelling; the entry's key was already that spelling."""
    path = a_pack(tmp_path, "corpus:\n  literature: []\n")

    add_to_pack(
        path,
        "literature",
        ["doi:10.1093/mnras/staf2144.", "10.48550/arXiv.2101.00001"],
        AddOptions(),
        arxiv=nowhere_but_404(),
        request_delay_seconds=0,
    )

    entries = yaml.safe_load(path.read_text(encoding="utf-8"))["corpus"]["literature"]
    assert [entry["identifier"] for entry in entries] == [
        "10.1093/mnras/staf2144",
        "2101.00001",
    ]


def test_what_lies_between_entries_stays(tmp_path: Path):
    path = a_pack(
        tmp_path,
        "corpus:\n  literature:\n"
        "    # The RIME, first.\n"
        "    - identifier: '1101.1764'\n"
        "\n"
        "    # Kept as it was.\n"
        "    - citekey: other2020\n"
        "      identifier: '2001.00001'\n",
    )

    updated(path)

    text = path.read_text(encoding="utf-8")
    assert "    # The RIME, first.\n" + DESCRIBED + "\n    # Kept as it was.\n" in text
    assert "    - citekey: other2020\n      identifier: '2001.00001'\n" in text


def test_a_second_update_writes_nothing(tmp_path: Path):
    path = a_pack(tmp_path, "corpus:\n  literature:\n    - identifier: '1101.1764'\n")
    updated(path)
    before = path.read_bytes()

    update_pack(path, arxiv=nowhere(), request_delay_seconds=0)

    assert path.read_bytes() == before


def test_a_title_beyond_ascii_is_written_escaped(tmp_path: Path):
    path = a_pack(tmp_path, "corpus:\n  literature: []\n")

    add_to_pack(
        path,
        "literature",
        ["2101.00001"],
        AddOptions(title="TRON \u2013 I", citekey="tron2025"),
        arxiv=nowhere(),
        request_delay_seconds=0,
    )

    text = path.read_text(encoding="utf-8")
    assert text.isascii()
    assert '        title: "TRON \\u2013 I",\n' in text
    assert load_pack(text).corpus.literature[0].title == "TRON \u2013 I"


def test_a_page_joining_its_project_writes_the_project_again_whole(
    tmp_path: Path,
):
    (tmp_path / "pages").mkdir()
    for name in ("one.md", "two.md"):
        (tmp_path / "pages" / name).write_text(f"# {name}\n", encoding="utf-8")
    path = a_pack(tmp_path, "corpus:\n  docs: []\n")
    options = AddOptions(project="tool", version="1.0")

    for name in ("one.md", "two.md"):
        add_to_pack(path, "docs", [str(tmp_path / "pages" / name)], options)

    assert (
        "  docs:\n"
        "    - {\n"
        '        project: "tool",\n'
        '        version: "1.0",\n'
        "        pages: [\n"
        '          "pages/one.md",\n'
        '          "pages/two.md",\n'
        "        ],\n"
        "      }\n"
    ) in path.read_text(encoding="utf-8")


def test_a_file_leaving_an_include_list_writes_its_entry_again(tmp_path: Path):
    (tmp_path / "context").mkdir()
    for name in ("a.md", "b.md"):
        (tmp_path / "context" / name).write_text(f"# {name}\n", encoding="utf-8")
    path = a_pack(tmp_path, "context: []\n")
    add_to_pack(
        path,
        "context",
        [str(tmp_path / "context" / "a.md"), str(tmp_path / "context" / "b.md")],
        AddOptions(),
    )

    remove_from_pack(path, ["context/a.md"])

    assert (
        "context:\n"
        "  - {\n"
        '      source: "context/",\n'
        "      include: [\n"
        '        "b.md",\n'
        "      ],\n"
        "    }\n"
    ) in path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Authors are a list
# ---------------------------------------------------------------------------


def test_authors_are_a_list_and_the_corpus_reads_them_joined():
    entry = LiteratureEntry.model_validate(
        {"identifier": "1101.1764", "authors": ["Smirnov, O", "Heywood, I"]}
    )

    assert entry.author_line == "Smirnov, O and Heywood, I"


def test_authors_written_as_one_string_are_refused_naming_the_command():
    with pytest.raises(PackInvalid, match="kennis pack format") as raised:
        load_pack(
            f"{HEADER}corpus:\n  literature:\n"
            "    - identifier: '1101.1764'\n"
            "      authors: 'Smirnov, O and Heywood, I'\n"
        )

    assert raised.value.resolution is not None
    assert "kennis pack format" in raised.value.resolution


# ---------------------------------------------------------------------------
# kennis pack format
# ---------------------------------------------------------------------------


AS_WRITTEN_BY_0_12 = (
    "# yaml-language-server: $schema=https://example/ken-1.json\n" + HEADER + "\n"
    "corpus:\n"
    "  literature:\n"
    "    # The RIME.\n"
    '    - citekey: "smirnovRevisitingRime2011"\n'
    '      title: "Revisiting \\u2013 the RIME"\n'
    '      authors: "Smirnov, O and Heywood, I"\n'
    "      year: 2011\n"
    '      identifier: "doi:10.1093/mnras/staf2144."\n'
    "    - identifier: '2101.00001'\n"
    "\n"
    "  notes:\n"
    '    - source: "notes/"\n'
    '      group: "kept"\n'
    "\n"
    "# A closing remark.\n"
)


def test_format_writes_every_entry_in_kennis_s_form(tmp_path: Path):
    (tmp_path / "notes").mkdir()
    path = a_pack(tmp_path, "")
    path.write_text(AS_WRITTEN_BY_0_12, encoding="utf-8")

    assert format_pack(path)

    assert authored(path) == (
        "# yaml-language-server: $schema=https://example/ken-1.json\n" + HEADER + "\n"
        "corpus:\n"
        "  literature:\n"
        "    # The RIME.\n"
        "    - {\n"
        '        identifier: "10.1093/mnras/staf2144",\n'
        '        citekey: "smirnovRevisitingRime2011",\n'
        '        title: "Revisiting \\u2013 the RIME",\n'
        "        year: 2011,\n"
        "        authors: [\n"
        '          "Smirnov, O",\n'
        '          "Heywood, I",\n'
        "        ],\n"
        "      }\n"
        "\n"
        "    - {\n"
        '        identifier: "2101.00001",\n'
        "      }\n"
        "\n"
        "  notes:\n"
        "    - {\n"
        '        source: "notes/",\n'
        '        group: "kept",\n'
        "      }\n"
        "\n"
        "# A closing remark.\n"
    )
    assert load_pack(path.read_text(encoding="utf-8")).corpus.literature[0].authors == [
        "Smirnov, O",
        "Heywood, I",
    ]


def test_format_twice_changes_nothing_the_second_time(tmp_path: Path):
    (tmp_path / "notes").mkdir()
    path = a_pack(tmp_path, "")
    path.write_text(AS_WRITTEN_BY_0_12, encoding="utf-8")
    format_pack(path)
    before = path.read_bytes()

    assert not format_pack(path)
    assert path.read_bytes() == before


def test_format_refuses_a_file_that_does_not_parse_and_writes_nothing(
    tmp_path: Path,
):
    path = a_pack(tmp_path, "corpus:\n  literature:\n    - identifier: [\n")
    before = path.read_bytes()

    with pytest.raises(PackInvalid):
        format_pack(path)

    assert path.read_bytes() == before


def test_pack_format_on_the_command_line_says_what_it_did(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    (tmp_path / "notes").mkdir()
    path = a_pack(tmp_path, "")
    path.write_text(AS_WRITTEN_BY_0_12, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    first = CliRunner().invoke(main, ["pack", "format"])
    second = CliRunner().invoke(main, ["pack", "format"])

    assert first.exit_code == 0, first.output
    assert "Formatted alpha.ken.yml" in first.output
    assert second.exit_code == 0, second.output
    assert "already formatted" in second.output


# ---------------------------------------------------------------------------
# #557: what replaying rarg-brain found
# ---------------------------------------------------------------------------


def context_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "context"
    folder.mkdir()
    for name in ("constraints.md", "glossary.md"):
        (folder / name).write_text(f"# {name}\n", encoding="utf-8")
    return folder


def test_a_folder_added_after_its_files_ships_all_of_it(tmp_path: Path):
    """`pack add -c context/*` then `pack add -c context/`: the second named
    the whole folder and was told it was there already, so a file put in it
    afterwards would not have shipped."""
    folder = context_folder(tmp_path)
    path = a_pack(tmp_path, "context: []\n")
    options = AddOptions(group="context")
    add_to_pack(path, "context", sorted(str(one) for one in folder.iterdir()), options)

    addition = add_to_pack(path, "context", [str(folder)], options)

    [outcome] = addition.report.outcomes
    assert outcome.outcome is Outcome.ADDED
    [entry] = load_pack(path.read_text(encoding="utf-8")).context
    assert entry.source == "context/"
    assert entry.named_files is None
    assert entry.group == "context"


def test_a_folder_declared_already_is_named_as_the_pack_names_it(tmp_path: Path):
    folder = context_folder(tmp_path)
    path = a_pack(tmp_path, "context: []\n")
    add_to_pack(path, "context", [str(folder)], AddOptions())

    addition = add_to_pack(path, "context", [str(folder)], AddOptions())

    [outcome] = addition.report.outcomes
    assert outcome.outcome is Outcome.UNCHANGED
    assert outcome.title == "context/"


def test_an_add_that_would_ship_a_file_twice_is_refused(tmp_path: Path):
    """`pack add -n files/` declared kennis's own copy folder, so the next
    file copied into it had two destinations, and `pack validate` refused
    the pack `pack add` had written."""
    (tmp_path / "files").mkdir()
    (tmp_path / "files" / "kept.md").write_text("# kept\n", encoding="utf-8")
    outside = tmp_path.parent / f"{tmp_path.name}-outside.md"
    outside.write_text("# outside\n", encoding="utf-8")
    path = a_pack(tmp_path, "corpus:\n  notes: []\n")
    add_to_pack(path, "notes", [str(tmp_path / "files")], AddOptions())
    before = path.read_bytes()

    addition = add_to_pack(path, "notes", [str(outside)], AddOptions())

    [outcome] = addition.report.outcomes
    assert outcome.outcome is Outcome.FAILED
    assert outcome.refusal == ShippedTwice(
        path="files/", other=f"files/notes/{outside.name}"
    )
    assert path.read_bytes() == before


def test_pack_remove_counts_what_it_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    folder = context_folder(tmp_path)
    path = a_pack(tmp_path, "context: []\n")
    add_to_pack(path, "context", [str(folder)], AddOptions())
    monkeypatch.chdir(tmp_path)

    removed = CliRunner().invoke(main, ["pack", "remove", "-y", "context"])

    assert removed.exit_code == 0, removed.output
    assert "Removed 1 entry" in removed.output
    assert "Removed alpha.ken.yml" not in removed.output
