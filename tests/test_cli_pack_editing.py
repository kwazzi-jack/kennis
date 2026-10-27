"""`kennis pack add` and `kennis pack remove` on the command line.

The editing itself is `test_pack_editing.py`'s; this is what the commands
take and what they say. A paper with no citekey makes `pack update` ask
arXiv, so a test adding one takes `offline`, whose arXiv answers 404.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.engine.events import EventSink
from kennis.engine.pack import editing
from kennis.engine.pack.schema import load_pack
from kennis.engine.pack.update import PackUpdate, update_pack

PACK = """\
kennis:
  schema_version: 1

pack:
  id: tron
  name: "TRON"
  version: "0.1.0"

corpus:
  literature:
    - citekey: smirnovRevisitingRIMEI2011
      identifier: "1101.1764"
"""


@pytest.fixture
def run() -> CliRunner:
    return CliRunner()


@pytest.fixture
def pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "tron"
    root.mkdir()
    path = root / "tron.ken.yml"
    path.write_text(PACK, encoding="utf-8")
    update_pack(path)
    monkeypatch.chdir(root)
    return path


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def updated(
        path: Path,
        *,
        events: EventSink | None = None,
        arxiv: httpx.Client | None = None,
        request_delay_seconds: float | None = None,
    ) -> PackUpdate:
        nowhere = httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(404))
        )
        return update_pack(path, events=events, arxiv=nowhere, request_delay_seconds=0)

    monkeypatch.setattr(editing, "update_pack", updated)


def test_pack_add_declares_a_paper_in_the_pack_here(run: CliRunner, pack: Path):
    result = run.invoke(
        main, ["pack", "add", "-l", "2511.10785", "--citekey", "murphyDawes2026"]
    )

    assert result.exit_code == 0, result.output
    assert "Added" in result.output
    assert "murphyDawes2026" in result.output
    declared = load_pack(pack.read_text(encoding="utf-8")).corpus.literature
    assert [one.identifier for one in declared] == ["1101.1764", "2511.10785"]


def test_pack_add_copies_a_local_file_and_says_so(
    run: CliRunner, pack: Path, tmp_path: Path
):
    pdf = tmp_path / "maccagni.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake\n")

    result = run.invoke(
        main,
        [
            "pack",
            "add",
            "-l",
            str(pdf),
            "--identifier",
            "10.48479/bhpj-nz95",
            "--citekey",
            "maccagniRFI2022",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "files/literature/maccagni.pdf" in result.output
    assert (pack.parent / "files" / "literature" / "maccagni.pdf").exists()


def test_pack_add_needs_one_destination(run: CliRunner, pack: Path):
    result = run.invoke(main, ["pack", "add", "2511.10785"])

    assert result.exit_code != 0
    assert "-l" in result.output


def test_pack_add_names_the_pack_with_pack(
    run: CliRunner, pack: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)

    result = run.invoke(
        main,
        [
            "pack",
            "add",
            "--pack",
            str(pack),
            "-n",
            "https://example.org/beam.html",
            "--title",
            "Beam",
        ],
    )

    assert result.exit_code == 0, result.output
    notes = load_pack(pack.read_text(encoding="utf-8")).corpus.note_links
    assert [(one.url, one.title) for one in notes] == [
        ("https://example.org/beam.html", "Beam")
    ]


def test_an_entry_already_declared_is_unchanged_with_nothing_written(
    run: CliRunner, pack: Path
):
    before = pack.read_bytes()

    result = run.invoke(main, ["pack", "add", "-l", "arXiv:1101.1764"])

    assert result.exit_code == 0, result.output
    assert "Added 0 entries" in result.output
    assert "= arXiv:1101.1764" in result.output
    assert pack.read_bytes() == before


@pytest.mark.usefixtures("offline")
def test_each_input_succeeds_or_fails_on_its_own_as_in_corpus_add(
    run: CliRunner, pack: Path, tmp_path: Path
):
    unknown = tmp_path / "unknown.pdf"
    unknown.write_bytes(b"%PDF-1.4 fake\n")

    result = run.invoke(
        main, ["pack", "add", "-l", "2511.10785", str(unknown), "1501.00001"]
    )

    assert result.exit_code == 0, result.output
    assert "Added 2 entries" in result.output
    [failed] = [line for line in result.output.splitlines() if "unknown.pdf" in line]
    assert failed.lstrip().startswith("!")
    assert "--identifier" in failed
    declared = load_pack(pack.read_text(encoding="utf-8")).corpus.literature
    assert [one.identifier for one in declared][-2:] == ["2511.10785", "1501.00001"]


@pytest.mark.usefixtures("offline")
def test_pack_add_names_its_destination_as_corpus_add_does(run: CliRunner, pack: Path):
    named = run.invoke(
        main, ["pack", "add", "--collection", "literature", "2511.10785"]
    )
    both = run.invoke(
        main, ["pack", "add", "--collection", "literature", "-n", "2511.10785"]
    )

    assert named.exit_code == 0, named.output
    assert both.exit_code != 0
    assert "name different collections" in both.output


def test_an_option_for_another_destination_is_refused_in_corpus_add_s_words(
    run: CliRunner, pack: Path
):
    result = run.invoke(
        main, ["pack", "add", "-n", "https://example.org/a.html", "--citekey", "x"]
    )

    assert result.exit_code != 0
    assert "--citekey applies to literature only, not to notes" in result.output


def test_pack_add_takes_no_option_corpus_add_lacks(run: CliRunner, pack: Path):
    for option in ("--authors", "--year"):
        result = run.invoke(main, ["pack", "add", "-l", "2511.10785", option, "x"])

        assert result.exit_code != 0
        assert "No such option" in result.output


def test_pack_remove_takes_an_entry_out(run: CliRunner, pack: Path):
    result = run.invoke(main, ["pack", "remove", "-y", "smirnovRevisitingRIMEI2011"])

    assert result.exit_code == 0, result.output
    assert "Removed" in result.output
    assert load_pack(pack.read_text(encoding="utf-8")).corpus.literature == []


def test_pack_remove_names_what_it_did_not_find(run: CliRunner, pack: Path):
    result = run.invoke(main, ["pack", "remove", "-y", "nosuch"])

    assert result.exit_code != 0
    assert "nosuch" in result.output


def test_pack_remove_asks_first_as_corpus_remove_does(run: CliRunner, pack: Path):
    before = pack.read_bytes()

    declined = run.invoke(
        main, ["pack", "remove", "smirnovRevisitingRIMEI2011"], input="n\n"
    )

    assert declined.exit_code != 0
    assert "smirnovRevisitingRIMEI2011" in declined.output
    assert pack.read_bytes() == before

    agreed = run.invoke(
        main, ["pack", "remove", "smirnovRevisitingRIMEI2011"], input="y\n"
    )

    assert agreed.exit_code == 0, agreed.output
    assert load_pack(pack.read_text(encoding="utf-8")).corpus.literature == []


def test_pack_add_offers_what_a_pack_can_declare():
    from kennis.cli.commands.pack import DESTINATIONS as OFFERED
    from kennis.engine.pack.editing import DESTINATIONS

    assert OFFERED == DESTINATIONS


def test_pack_add_never_ships_the_corpus(
    run: CliRunner, pack: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    corpus = tmp_path / "corpus"
    (corpus / "notes").mkdir(parents=True)
    note = corpus / "notes" / "mine.md"
    note.write_bytes(b"# Mine\n")
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(corpus))
    before = pack.read_bytes()

    result = run.invoke(main, ["pack", "add", "-n", str(note)])

    assert result.exit_code != 0
    assert "kennis's own files" in result.output
    assert pack.read_bytes() == before


def test_a_refusal_of_the_whole_command_names_pack_add_s_help(
    run: CliRunner, pack: Path, tmp_path: Path
):
    result = run.invoke(main, ["pack", "add", "-d", str(tmp_path), "--project", "tron"])

    assert result.exit_code != 0
    assert "kennis pack add --help" in result.output
    assert "corpus add --help" not in result.output


def test_pack_add_says_which_citekey_a_paper_was_given(
    run: CliRunner, pack: Path, monkeypatch: pytest.MonkeyPatch
):
    def updated(
        path: Path,
        *,
        events: EventSink | None = None,
        arxiv: httpx.Client | None = None,
        request_delay_seconds: float | None = None,
    ) -> PackUpdate:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "doi.org" and request.url.path != "/robots.txt":
                return httpx.Response(
                    200,
                    json={
                        "DOI": "10.1093/mnrasl/slaf009",
                        "title": "Mining the time axis with TRON",
                        "author": [{"family": "Smirnov", "given": "O M"}],
                        "issued": {"date-parts": [[2025]]},
                    },
                )
            return httpx.Response(404)

        registry = httpx.Client(transport=httpx.MockTransport(handler))
        return update_pack(path, events=events, arxiv=registry, request_delay_seconds=0)

    monkeypatch.setattr(editing, "update_pack", updated)

    result = run.invoke(main, ["pack", "add", "-l", "doi:10.1093/mnrasl/slaf009"])

    assert result.exit_code == 0, result.output
    assert "doi:10.1093/mnrasl/slaf009 as smirnovMiningTimeAxis2025" in result.output
    # Once, not once bare and once with its citekey (Brian, 2026-10-27).
    assert result.output.count("10.1093/mnrasl/slaf009") == 1
    # The pack ships no files, so the block's count says nothing.
    assert "files recorded" not in result.output
