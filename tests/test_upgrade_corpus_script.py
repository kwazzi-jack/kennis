"""The script that brings an older corpus to v0.15.0's shape.

Brian, 2026-11-21: papers converted before #38 link images the corpus
never kept, so they are converted again - with MinerU 4, text and images,
under the same identifier - and `tags.yml` becomes annotations. A
standalone script that decides by reading the corpus and changes it only
through `kennis` commands, run here through the command line in this
process, with every host answering 404 here.
"""

from __future__ import annotations

import hashlib
import importlib.util
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.engine.annotations import ANNOTATIONS_FILENAME, read_annotations
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.document import Document
from kennis.engine.corpus.schema import LiteratureFrontmatter
from kennis.engine.pack.update import update_pack

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "upgrade_corpus.py"

PDF = b"%PDF-1.4 a paper\n"
PACK = (
    'kennis:\n  schema_version: 1\npack:\n  id: alpha\n  name: n\n  version: "1.0.0"\n'
    "corpus:\n"
    "  literature:\n"
    "    - citekey: smirnovRevisitingRIMEI2011\n"
    '      title: "Revisiting the RIME"\n'
    '      authors: ["Smirnov, O. M."]\n'
    "      year: 2011\n"
    '      identifier: "1101.1764"\n'
    "      group: rime\n"
    "      file: papers/rime.pdf\n"
)
# What MinerU 3 wrote and the corpus never kept: a link into its own folder.
OLD_FIGURE = "\n![](images/0123abcd.jpg)\nFigure 1. From MinerU 3.\n"


def load_script() -> ModuleType:
    specification = importlib.util.spec_from_file_location("upgrade_corpus", SCRIPT)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    # A dataclass looks its module up while it is being made.
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


upgrade = load_script()


type Ran = tuple[int, str]


def through_the_command_line(
    arguments: Sequence[str], capture: bool = False
) -> tuple[int, str]:
    """The script's runner, as `kennis` in this process."""
    result = CliRunner().invoke(main, list(arguments))
    return result.exit_code, result.output


def ran(arguments: Sequence[str]) -> int:
    return through_the_command_line(arguments)[0]


@pytest.fixture(autouse=True)
def every_host_answers_404(monkeypatch: pytest.MonkeyPatch) -> None:
    def answered(
        transport: httpx.HTTPTransport, outgoing: httpx.Request
    ) -> httpx.Response:
        return httpx.Response(404, request=outgoing)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", answered)


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "corpus"
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(root))
    assert ran(["corpus", "init"]) == 0
    return root


def papers_in(corpus: Path) -> list[Document]:
    return list(Collection(root=corpus, name="literature").contents().documents)


def commit_by_hand(corpus: Path, message: str) -> None:
    for arguments in (["add", "--all", "."], ["commit", "-q", "-m", message]):
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=test",
                "-c",
                "user.email=test@example.invalid",
                *arguments,
            ],
            cwd=corpus,
            check=True,
            stdin=subprocess.DEVNULL,
            timeout=30,
        )


def as_mineru_3_left_it(paper: Document, corpus: Path) -> None:
    """The paper's markdown links an image beside it that is not there."""
    text = paper.md_path.read_text(encoding="utf-8")
    paper.md_path.write_text(text + OLD_FIGURE, encoding="utf-8", newline="\n")
    commit_by_hand(corpus, "as mineru 3 left it")
    # MinerU 3's kept conversion was keyed by its own variant and kept a
    # day; this one is the fixture's, made by MinerU 4 a moment ago.
    shutil.rmtree(corpus / ".git" / "kennis-conversions", ignore_errors=True)


@pytest.fixture
def pack_paper(corpus: Path, tmp_path: Path, fake_mineru: Path) -> Document:
    """A pack's paper converted from the pack's own PDF, before #38."""
    pack = tmp_path / "pack"
    (pack / "papers").mkdir(parents=True)
    (pack / "papers" / "rime.pdf").write_bytes(PDF)
    pack_file = pack / "alpha.ken.yml"
    pack_file.write_text(PACK, encoding="utf-8")
    update_pack(pack_file)
    assert ran(["pack", "install", str(pack_file)]) == 0
    assert ran(["corpus", "sync"]) == 0
    [paper] = papers_in(corpus)
    assert paper.frontmatter.source.via == "mineru", "the fixture no longer converts"
    as_mineru_3_left_it(paper, corpus)
    return paper


@pytest.fixture
def own_paper(corpus: Path, tmp_path: Path, fake_mineru: Path) -> Document:
    """A paper of the user's, converted from a PDF that is still there."""
    pdf = tmp_path / "downloads" / "rime.pdf"
    pdf.parent.mkdir()
    pdf.write_bytes(PDF)
    added = ran(
        [
            "corpus",
            "add",
            "-l",
            str(pdf),
            "--identifier",
            "arxiv:1101.1764",
            "--citekey",
            "smirnovRime2011",
            "--group",
            "mine",
        ]
    )
    assert added == 0
    [paper] = papers_in(corpus)
    as_mineru_3_left_it(paper, corpus)
    return paper


def held_images(paper: Document) -> list[Path]:
    return sorted(
        path for path in paper.md_path.parent.iterdir() if path.suffix == ".jpg"
    )


def head_of(corpus: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=corpus,
        capture_output=True,
        text=True,
        check=True,
        stdin=subprocess.DEVNULL,
        timeout=30,
    ).stdout.strip()


# Any: the script is loaded by path, so a checker cannot see its `Plan`.
def applied(corpus: Path) -> Any:
    return upgrade.upgrade_corpus(
        corpus, run=through_the_command_line, apply=True, backup=False
    )


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------


def test_a_paper_linking_images_it_does_not_hold_is_planned(
    corpus: Path, pack_paper: Document
) -> None:
    plan = upgrade.plan_upgrade(corpus)

    assert [paper.document_id for paper in plan.from_packs] == [pack_paper.id]
    assert plan.own == () and plan.left == ()


def test_a_paper_holding_its_images_is_not_planned(
    corpus: Path, pack_paper: Document, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MINERU_FAKE_IMAGES", "1")
    applied(corpus)

    assert upgrade.plan_upgrade(corpus).is_empty()


def test_a_plan_alone_changes_nothing(corpus: Path, pack_paper: Document) -> None:
    before = head_of(corpus)
    text = pack_paper.md_path.read_text(encoding="utf-8")

    upgrade.upgrade_corpus(
        corpus, run=through_the_command_line, apply=False, backup=False
    )

    assert head_of(corpus) == before
    assert pack_paper.md_path.read_text(encoding="utf-8") == text


# ---------------------------------------------------------------------------
# Converted again
# ---------------------------------------------------------------------------


def test_a_pack_s_paper_comes_back_with_its_figures_under_its_identifier(
    corpus: Path, pack_paper: Document, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MINERU_FAKE_IMAGES", "1")

    remaining = applied(corpus)

    [paper] = papers_in(corpus)
    assert isinstance(paper.frontmatter, LiteratureFrontmatter)
    assert paper.id == pack_paper.id
    assert paper.frontmatter.owner == "pack:alpha"
    assert paper.frontmatter.bib.citekey == "smirnovRevisitingRIMEI2011"
    assert "images/0123abcd.jpg" not in paper.body
    assert held_images(paper), "converted again, and still no figure held"
    assert upgrade.plan_upgrade(corpus).is_empty()
    assert remaining == upgrade.plan_upgrade(corpus)


def test_the_user_s_paper_comes_back_with_its_figures_under_its_identifier(
    corpus: Path, own_paper: Document, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MINERU_FAKE_IMAGES", "1")
    plan = upgrade.plan_upgrade(corpus)
    assert [paper.document_id for paper in plan.own] == [own_paper.id]

    applied(corpus)

    [paper] = papers_in(corpus)
    assert isinstance(paper.frontmatter, LiteratureFrontmatter)
    assert paper.id == own_paper.id
    assert paper.frontmatter.owner == "user"
    assert paper.frontmatter.bib.citekey == "smirnovRime2011"
    assert paper.md_path.parent.name != "literature"
    assert held_images(paper)


def test_a_pack_s_paper_is_found_in_the_store_of_a_corpus_that_moved(
    corpus: Path, pack_paper: Document, tmp_path: Path
) -> None:
    """The record names the store where the corpus was converted, and
    after a move nothing is there."""
    moved = tmp_path / "moved" / "corpus"
    moved.parent.mkdir()
    shutil.move(corpus, moved)

    plan = upgrade.plan_upgrade(moved)

    assert [paper.document_id for paper in plan.from_packs] == [pack_paper.id]


def test_a_pack_s_paper_whose_stored_file_changed_is_left(
    corpus: Path, pack_paper: Document
) -> None:
    [stored] = (corpus / "packs" / "alpha").rglob("rime.pdf")
    stored.chmod(0o644)
    stored.write_bytes(PDF + b"another revision\n")

    plan = upgrade.plan_upgrade(corpus)

    assert [left.paper.document_id for left in plan.left] == [pack_paper.id]
    assert plan.from_packs == ()


@pytest.mark.parametrize("how", ["moved", "changed"])
def test_a_paper_whose_pdf_is_not_the_one_converted_is_left(
    corpus: Path, own_paper: Document, tmp_path: Path, how: str
) -> None:
    pdf = tmp_path / "downloads" / "rime.pdf"
    if how == "moved":
        shutil.move(pdf, tmp_path / "elsewhere.pdf")
    else:
        pdf.write_bytes(PDF + b"another revision\n")
    before = head_of(corpus)

    remaining = applied(corpus)

    assert [left.paper.document_id for left in remaining.left] == [own_paper.id]
    assert head_of(corpus) == before
    assert hashlib.sha256(PDF).hexdigest() in own_paper.md_path.read_text(
        encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# tags.yml
# ---------------------------------------------------------------------------


def test_tags_yml_becomes_annotations_and_goes(
    corpus: Path, pack_paper: Document
) -> None:
    assert ran(["corpus", "index"]) == 0
    (corpus / "tags.yml").write_text(
        "calibration:\n"
        f"- document: {pack_paper.id}\n"
        "  chunk: 0\n"
        "  quote: Converted body.\n"
        "to-cite:\n"
        f"- document: {pack_paper.id}\n"
        "  chunk: 0\n"
        "  quote: Converted body.\n",
        encoding="utf-8",
    )
    commit_by_hand(corpus, "tags as v0.14.0 kept them")
    plan = upgrade.plan_upgrade(corpus)
    assert [(group.document_id, group.chunk, group.tags) for group in plan.tags] == [
        (pack_paper.id, 0, ("calibration", "to-cite"))
    ]

    applied(corpus)

    store = read_annotations(corpus / ANNOTATIONS_FILENAME)
    assert {
        (annotation.document, tag)
        for annotation in store.annotations
        for tag in annotation.tags
    } == {(pack_paper.id, "calibration"), (pack_paper.id, "to-cite")}
    assert not (corpus / "tags.yml").exists()


def test_a_tag_whose_words_left_its_passage_is_not_placed(
    corpus: Path, pack_paper: Document
) -> None:
    """A chunk number is a hint; the words decide, as they did in v0.14.0."""
    assert ran(["corpus", "index"]) == 0
    (corpus / "tags.yml").write_text(
        "calibration:\n"
        f"- document: {pack_paper.id}\n"
        "  chunk: 0\n"
        "  quote: Words no chunk holds.\n",
        encoding="utf-8",
    )
    commit_by_hand(corpus, "a tag whose passage changed")

    remaining = applied(corpus)

    assert [group.tags for group in remaining.unplaced] == [("calibration",)]
    assert not read_annotations(corpus / ANNOTATIONS_FILENAME).annotations
    assert (corpus / "tags.yml").exists(), "removed with a tag not placed"


def test_tags_are_placed_against_the_text_they_were_written_against(
    corpus: Path, pack_paper: Document, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Checked against the index, which still holds MinerU 3's text until
    the upgrade rebuilds it at the end - so before or after the paper is
    converted again, the words are found."""
    monkeypatch.setenv("MINERU_FAKE_IMAGES", "1")
    assert ran(["corpus", "index"]) == 0
    (corpus / "tags.yml").write_text(
        "figures:\n"
        f"- document: {pack_paper.id}\n"
        "  chunk: 0\n"
        "  quote: Figure 1. From MinerU 3.\n",
        encoding="utf-8",
    )
    commit_by_hand(corpus, "a tag on words only MinerU 3 wrote")

    remaining = applied(corpus)

    assert remaining.unplaced == ()
    tags = [
        annotation.tags
        for annotation in read_annotations(corpus / ANNOTATIONS_FILENAME).annotations
    ]
    assert tags == [("figures",)]


def test_an_apply_backs_the_corpus_up_before_anything_else(
    corpus: Path, pack_paper: Document
) -> None:
    asked: list[list[str]] = []

    def recording(arguments: Sequence[str], capture: bool = False) -> tuple[int, str]:
        asked.append(list(arguments))
        if list(arguments) == ["backup", "create"]:
            return 0, ""
        return through_the_command_line(arguments, capture)

    upgrade.upgrade_corpus(corpus, run=recording, apply=True, backup=True)

    assert asked[0] == ["backup", "create"]


def test_a_tag_s_colour_is_kept(corpus: Path, pack_paper: Document) -> None:
    (corpus / "tags.yml").write_text(
        f"calibration:\n  colour: teal\n  targets:\n  - document: {pack_paper.id}\n",
        encoding="utf-8",
    )
    commit_by_hand(corpus, "a coloured tag on a whole document")

    applied(corpus)

    store = read_annotations(corpus / ANNOTATIONS_FILENAME)
    assert store.colours == {"calibration": "teal"}
    [annotation] = store.annotations
    assert annotation.selector is None and annotation.tags == ("calibration",)


def test_only_the_papers_named_are_converted(
    corpus: Path, pack_paper: Document
) -> None:
    assert upgrade.plan_upgrade(corpus, frozenset({"someone-else"})).from_packs == ()
    named = upgrade.plan_upgrade(corpus, frozenset({pack_paper.id}))
    assert [paper.document_id for paper in named.from_packs] == [pack_paper.id]


# ---------------------------------------------------------------------------
# Ignore and attribute lines
# ---------------------------------------------------------------------------


def test_a_line_corpus_init_writes_and_the_corpus_lacks_is_added(
    corpus: Path,
) -> None:
    ignore = corpus / ".gitignore"
    lines = ignore.read_text(encoding="utf-8").splitlines()
    assert "index/*/vectors/" in lines, "the fixture no longer has the line"
    ignore.write_text(
        "\n".join(line for line in lines if line != "index/*/vectors/") + "\n",
        encoding="utf-8",
    )
    commit_by_hand(corpus, "an older corpus")

    assert upgrade.plan_upgrade(corpus).lines == {".gitignore": ("index/*/vectors/",)}
    applied(corpus)

    assert "index/*/vectors/" in ignore.read_text(encoding="utf-8").splitlines()
    assert upgrade.plan_upgrade(corpus).is_empty()


def test_the_script_s_lines_are_what_corpus_init_writes(corpus: Path) -> None:
    """By hand in the script, which runs without kennis to import; held to
    `corpus init` here, so a line added to init is added to the script."""
    for name, expected in upgrade.EXPECTED_LINES.items():
        written = tuple(
            line.strip()
            for line in (corpus / name).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
        assert written == expected, name


def test_the_plan_warns_of_a_tag_on_a_paper_converted_again(
    corpus: Path, pack_paper: Document
) -> None:
    (corpus / "tags.yml").write_text(
        f"calibration:\n- document: {pack_paper.id}\n"
        "  chunk: 0\n  quote: Converted body.\n",
        encoding="utf-8",
    )

    said = "\n".join(upgrade.described(upgrade.plan_upgrade(corpus)))

    assert "on a paper converted again" in said


# ---------------------------------------------------------------------------
# A paper removed and not written again (#694)
# ---------------------------------------------------------------------------


def test_a_pack_s_paper_that_could_not_be_converted_again_is_put_back(
    corpus: Path, pack_paper: Document, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Brian's corpus, 2026-11-22: the sync could not convert two textbooks,
    exited 0 with a warning, and the script said the corpus was upgraded
    with both removed. A paper no longer held links nothing, so planning
    again never saw them."""
    monkeypatch.setenv("MINERU_FAKE_SKIP", "rime")

    remaining = applied(corpus)

    [paper] = papers_in(corpus)
    assert paper.id == pack_paper.id
    assert "images/0123abcd.jpg" in paper.body, "not the text it had"
    assert [held.document_id for held in remaining.put_back] == [pack_paper.id]
    assert [held.document_id for held in remaining.from_packs] == [pack_paper.id]
    assert not remaining.is_empty()
    report = "\n".join(upgrade.described(remaining))
    assert f"{pack_paper.id}" in report and "put back as it was" in report


def test_the_user_s_paper_that_could_not_be_converted_again_is_put_back(
    corpus: Path, own_paper: Document, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`corpus add` reports a paper it could not convert and exits 1, and
    the script goes on to the next: it looks at what is held rather than
    trusting the exit status."""
    monkeypatch.setenv("MINERU_FAKE_SKIP", "rime")

    remaining = applied(corpus)

    [paper] = papers_in(corpus)
    assert paper.id == own_paper.id
    assert [held.document_id for held in remaining.put_back] == [own_paper.id]
    assert not remaining.is_empty()


def test_a_step_that_fails_outright_still_puts_back_what_was_removed(
    corpus: Path, pack_paper: Document
) -> None:
    def failing_sync(arguments: Sequence[str], capture: bool = False) -> Ran:
        if list(arguments[:2]) == ["corpus", "sync"]:
            return 1, "failed"
        return through_the_command_line(arguments, capture)

    with pytest.raises(upgrade.StepFailed) as raised:
        upgrade.upgrade_corpus(corpus, run=failing_sync, apply=True, backup=False)

    [paper] = papers_in(corpus)
    assert paper.id == pack_paper.id
    assert [held.document_id for held in raised.value.put_back] == [pack_paper.id]


def test_a_paper_that_could_not_be_put_back_is_named_with_its_command(
    corpus: Path, pack_paper: Document, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MINERU_FAKE_SKIP", "rime")

    def refusing_restore(arguments: Sequence[str], capture: bool = False) -> Ran:
        if list(arguments[:2]) == ["corpus", "restore"]:
            return 1, "refused"
        return through_the_command_line(arguments, capture)

    remaining = upgrade.upgrade_corpus(
        corpus, run=refusing_restore, apply=True, backup=False
    )

    assert papers_in(corpus) == []
    assert [held.document_id for held in remaining.lost] == [pack_paper.id]
    assert not remaining.is_empty()
    report = "\n".join(upgrade.described(remaining))
    assert f"kennis corpus restore {pack_paper.id}" in report
