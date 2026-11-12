"""A converted paper and the images it links, through every operation.

The images a conversion links are written beside the document (#134), so a
paper with a figure is a directory holding `content.md` and image files. The
shape existed before any real add produced it; these tests take one such
paper through what a person does with a document - add, index, search,
move, remove, restore, return - and through what goes wrong: an image
deleted by hand.

The image is a JPEG's first bytes, which are not valid UTF-8, so anything
that reads every file of a collection as text fails here rather than in
somebody's corpus.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis import operations
from kennis.cli.__main__ import main
from kennis.context import Context, existing_corpus
from kennis.engine.corpus import add as adding
from kennis.engine.corpus.add import AddOptions
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.converters import ConversionBatch
from kennis.engine.corpus.document import Document
from kennis.engine.errors import HistoryUnwritable
from kennis.engine.events import Outcome
from kennis.engine.history.repository import Repository

JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01"
FIGURE = "0123456789abcdef.jpg"


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
                    f"# {path.stem}\n\nResidual maps of the patch.\n\n"
                    f"![]({FIGURE})  \nFigure 1. Residuals after calibration.\n"
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


def a_paper(context: Context, tmp_path: Path, name: str = "Residuals") -> Document:
    """One paper with a figure, added the way every front end adds one."""
    source = tmp_path / "sources" / f"{name}.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"%PDF " + name.encode() + b"\n")
    report = operations.add_documents(context, "notes", [str(source)], AddOptions())
    assert [outcome.outcome for outcome in report.outcomes] == [Outcome.ADDED]
    return the_paper(context, name)


def notes_of(context: Context) -> Collection:
    return Collection(root=context.corpus_root, name="notes")


def the_paper(context: Context, title: str = "Residuals") -> Document:
    (document,) = [
        held
        for held in notes_of(context).contents().documents
        if held.frontmatter.title == title
    ]
    return document


def image_of(document: Document) -> Path:
    assert document.wrapper_dir is not None
    return document.wrapper_dir / FIGURE


def tracked(context: Context) -> list[str]:
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--", "notes"],
        cwd=context.corpus_root,
        capture_output=True,
        check=True,
        timeout=30,
        stdin=subprocess.DEVNULL,
    )
    # Without the placeholder `corpus init` records so that an empty
    # collection is a directory git keeps.
    return sorted(
        name.decode()
        for name in listed.stdout.split(b"\0")
        if name and not name.endswith(b".gitkeep")
    )


def run(*arguments: str) -> str:
    result = CliRunner().invoke(main, list(arguments))
    assert result.exit_code == 0, result.output
    return result.output


# ---------------------------------------------------------------------------
# Added
# ---------------------------------------------------------------------------


def test_the_paper_and_its_image_are_recorded_together(
    context: Context, tmp_path: Path
) -> None:
    document = a_paper(context, tmp_path)

    assert image_of(document).read_bytes() == JPEG
    assert tracked(context) == [
        f"notes/Residuals/{FIGURE}",
        "notes/Residuals/content.md",
    ]
    assert Repository(context.corpus_root).is_clean()


def test_git_stores_the_image_byte_for_byte(context: Context, tmp_path: Path) -> None:
    """The corpus's `.gitattributes` says `* text=auto eol=lf`, which
    rewrites line endings in whatever git takes for text. An image holding
    a CRLF pair must come back out of a commit as it went in."""
    with_crlf = JPEG + b"\r\n\x00more\r\n"

    class Converter(FigureConverter):
        def convert(self, paths: Sequence[Path]) -> ConversionBatch:
            batch = super().convert(paths)
            return ConversionBatch(
                markdown=batch.markdown,
                images={path: {FIGURE: with_crlf} for path in paths},
            )

    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(adding, "default_converter", Converter)
        document = a_paper(context, tmp_path)
    image_of(document).unlink()
    Repository(context.corpus_root).restore(f"notes/Residuals/{FIGURE}")

    assert image_of(document).read_bytes() == with_crlf


def test_the_paper_is_one_document_and_its_index_is_current(
    context: Context, tmp_path: Path
) -> None:
    """The image is a changed path under `notes/` like any other, and must
    count as part of its paper: neither a second document nor a reason the
    index is out of date."""
    a_paper(context, tmp_path)
    operations.build_indexes(context, "notes")

    status = run("corpus", "status")

    assert "Notes 1 document" in status
    assert "the notes index is up to date" in status


def test_the_paper_is_found_by_its_caption_and_read(
    context: Context, tmp_path: Path
) -> None:
    document = a_paper(context, tmp_path)
    operations.build_indexes(context, "notes")

    found = run("search", "residuals after calibration", "--mode", "bm25")
    read = run("read", document.id)

    assert f"id={document.id}" in found
    assert f"![]({FIGURE})" in read


def test_the_tree_shows_the_paper_as_one_line(context: Context, tmp_path: Path) -> None:
    a_paper(context, tmp_path)

    tree = run("corpus", "tree")

    assert "Residuals" in tree
    assert FIGURE not in tree
    assert "content.md" not in tree


# ---------------------------------------------------------------------------
# Changed by hand
# ---------------------------------------------------------------------------


def test_an_image_deleted_by_hand_is_put_back_by_the_next_write(
    context: Context, tmp_path: Path
) -> None:
    """Every write restores hand deletions first. Before images were kept
    that step read each deleted file's committed content as text."""
    document = a_paper(context, tmp_path)
    image_of(document).unlink()

    a_paper(context, tmp_path, name="Another")

    assert image_of(document).read_bytes() == JPEG
    assert Repository(context.corpus_root).is_clean()


def test_an_image_deleted_by_hand_does_not_stop_an_index_build(
    context: Context, tmp_path: Path
) -> None:
    document = a_paper(context, tmp_path)
    image_of(document).unlink()

    operations.build_indexes(context, "notes")

    assert image_of(document).read_bytes() == JPEG


# ---------------------------------------------------------------------------
# Moved, removed, put back, returned to
# ---------------------------------------------------------------------------


def test_moving_the_paper_moves_its_image(context: Context, tmp_path: Path) -> None:
    document = a_paper(context, tmp_path)
    before = image_of(document)

    operations.move_a_document(context, notes_of(context), document, group="radio")

    moved = the_paper(context)
    assert image_of(moved).read_bytes() == JPEG
    assert image_of(moved).parent.parent.name == "radio"
    assert not before.exists()
    assert Repository(context.corpus_root).is_clean()


def test_removing_the_paper_removes_its_image(context: Context, tmp_path: Path) -> None:
    document = a_paper(context, tmp_path)

    operations.remove_a_document(context, notes_of(context), document)

    assert tracked(context) == []
    assert not image_of(document).parent.exists()
    assert Repository(context.corpus_root).is_clean()


def test_restoring_the_paper_restores_its_image(
    context: Context, tmp_path: Path
) -> None:
    document = a_paper(context, tmp_path)
    held = Repository(context.corpus_root).head()
    assert held is not None
    operations.remove_a_document(context, notes_of(context), document)

    operations.restore_a_document(context, document.id, commit=held)

    assert image_of(the_paper(context)).read_bytes() == JPEG
    assert Repository(context.corpus_root).is_clean()


def test_a_restore_that_fails_leaves_nothing_of_the_paper_behind(
    context: Context, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fails at the commit, after the markdown and the image are both back
    on disk. All of it has to go again, the directory included: an image
    left behind is an untracked file, and an empty directory left behind
    is a group holding nothing."""
    document = a_paper(context, tmp_path)
    held = Repository(context.corpus_root).head()
    assert held is not None
    operations.remove_a_document(context, notes_of(context), document)
    removed = Repository(context.corpus_root).head()

    real_commit = Repository.commit

    def refused(
        self: Repository, operation: str, *, scope: str, summary: str
    ) -> str | None:
        if operation != "restore":
            return real_commit(self, operation, scope=scope, summary=summary)
        assert image_of(document).is_file(), "the failure came before the restore"
        raise HistoryUnwritable("git refused the commit")

    with monkeypatch.context() as failing:
        failing.setattr(Repository, "commit", refused)
        with pytest.raises(HistoryUnwritable):
            operations.restore_a_document(context, document.id, commit=held)

    assert not image_of(document).parent.exists()
    assert Repository(context.corpus_root).head() == removed
    assert Repository(context.corpus_root).is_clean()


def test_returning_to_a_point_brings_the_image_back_and_takes_it_away(
    context: Context, tmp_path: Path
) -> None:
    before = Repository(context.corpus_root).head()
    assert before is not None
    document = a_paper(context, tmp_path)
    held = Repository(context.corpus_root).head()
    assert held is not None

    operations.return_corpus_to(context, before)
    gone = not image_of(document).exists()
    operations.return_corpus_to(context, held)

    assert gone
    assert image_of(the_paper(context)).read_bytes() == JPEG
    assert Repository(context.corpus_root).is_clean()
