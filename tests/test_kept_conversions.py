"""A conversion is kept a day, so running a failed add again does not
convert again (14e, #507).

An add is prepared in a mirror and discarded when it fails, so before this a
retry paid for every conversion a second time - minutes of MinerU, or money
with a hosted converter. Kept by the source's content and the converter's
name under `.git/kennis-conversions/`, which no commit stages.
"""

from __future__ import annotations

import os
import time
from collections.abc import Sequence
from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis import operations
from kennis.cli.__main__ import main
from kennis.context import existing_corpus
from kennis.engine.corpus import add as adding
from kennis.engine.corpus.add import AddOptions
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.conversions import (
    KeptConversions,
    conversions_root,
    forget_old_conversions,
)
from kennis.engine.corpus.converters import ConversionBatch, Converter
from kennis.engine.events import Outcome
from kennis.engine.history.repository import Repository


class CountingConverter:
    """Records every path it was asked to convert: the count is the
    property, since a kept conversion is one that never reaches here."""

    formats = frozenset({"pdf"})

    def __init__(self, name: str = "counting") -> None:
        self.name = name
        self.converted: list[Path] = []

    def is_available(self) -> bool:
        return True

    def install_hint(self) -> str:
        return "install the counting converter"

    def convert(self, paths: Sequence[Path]) -> ConversionBatch:
        self.converted.extend(paths)
        return ConversionBatch(
            markdown={path: f"# {path.stem}\n\nConverted.\n" for path in paths},
            front_page={path: f"front of {path.stem}" for path in paths},
            repairs={path: 2 for path in paths},
        )


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    return tmp_path / "corpus"


def a_pdf(path: Path, body: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


def test_the_same_content_is_converted_once(tmp_path: Path):
    inner = CountingConverter()
    first = a_pdf(tmp_path / "a" / "paper.pdf", b"%PDF one\n")
    again = a_pdf(tmp_path / "b" / "renamed.pdf", b"%PDF one\n")

    KeptConversions(inner, tmp_path / "kept").convert([first])
    batch = KeptConversions(inner, tmp_path / "kept").convert([again])

    assert inner.converted == [first]
    assert batch.markdown == {again: "# paper\n\nConverted.\n"}
    assert batch.front_page == {again: "front of paper"}
    assert batch.repairs == {again: 2}


def test_only_what_is_not_kept_reaches_the_converter(tmp_path: Path):
    inner = CountingConverter()
    known = a_pdf(tmp_path / "known.pdf", b"%PDF known\n")
    new = a_pdf(tmp_path / "new.pdf", b"%PDF new\n")
    kept = KeptConversions(inner, tmp_path / "kept")
    kept.convert([known])

    batch = kept.convert([known, new])

    assert inner.converted == [known, new]
    assert set(batch.markdown) == {known, new}


def test_another_converter_does_not_reuse_a_conversion(tmp_path: Path):
    """Two converters write different markdown for one PDF; the one chosen
    now is the one whose text a person expects."""
    source = a_pdf(tmp_path / "paper.pdf", b"%PDF one\n")
    KeptConversions(CountingConverter("mineru"), tmp_path / "kept").convert([source])
    other = CountingConverter("datalab")

    KeptConversions(other, tmp_path / "kept").convert([source])

    assert other.converted == [source]


def test_a_kept_conversion_costs_nothing_again(tmp_path: Path):
    """A hosted converter reports what a run cost; a run answered wholly
    from what was kept was not paid for, so it reports nothing."""
    source = a_pdf(tmp_path / "paper.pdf", b"%PDF one\n")
    kept = KeptConversions(CountingConverter(), tmp_path / "kept")
    kept.convert([source])

    assert kept.convert([source]).cost_cents is None


def test_a_conversion_older_than_a_day_is_forgotten(tmp_path: Path):
    corpus = tmp_path / "corpus"
    kept = KeptConversions(CountingConverter(), conversions_root(corpus))
    kept.convert([a_pdf(tmp_path / "old.pdf", b"%PDF old\n")])
    kept.convert([a_pdf(tmp_path / "new.pdf", b"%PDF new\n")])
    entries = sorted(conversions_root(corpus).iterdir())
    assert len(entries) == 2
    day_and_a_bit = time.time() - 25 * 3600
    os.utime(entries[0], (day_and_a_bit, day_and_a_bit))

    forget_old_conversions(corpus)

    assert sorted(conversions_root(corpus).iterdir()) == entries[1:]


def test_running_a_failed_add_again_converts_nothing_again(
    corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The whole path: the first add converts and then fails, so nothing of
    it is published; the second adds the paper from the kept conversion."""
    inner = CountingConverter()
    monkeypatch.setattr(adding, "default_converter", lambda: inner)
    source = a_pdf(tmp_path / "sources" / "paper.pdf", b"%PDF paper\n")
    context = existing_corpus()
    real = operations._ADDERS["notes"]

    def converts_then_fails(
        target: Collection,
        identifiers: list[str],
        options: AddOptions,
        **rest: object,
    ) -> object:
        real(target, identifiers, options)
        raise OSError(28, "No space left on device")

    with monkeypatch.context() as failing:
        failing.setitem(operations._ADDERS, "notes", converts_then_fails)
        with pytest.raises(OSError):
            operations.add_documents(context, "notes", [str(source)], AddOptions())
    assert not list((context.corpus_root / "notes").rglob("*.md"))

    again = operations.add_documents(context, "notes", [str(source)], AddOptions())

    assert [outcome.outcome for outcome in again.outcomes] == [Outcome.ADDED]
    assert inner.converted == [source]
    assert Repository(context.corpus_root).is_clean()


def test_the_wrapper_is_a_converter(tmp_path: Path):
    kept: Converter = KeptConversions(CountingConverter(), tmp_path)
    assert isinstance(kept, Converter)
