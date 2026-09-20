"""The converter interface, and MinerU behind it.

No test runs the real MinerU. A fake `mineru` on `PATH` is enough to pin the
contract that matters: one process per batch, per-document reporting, a
timeout, and an install hint when the tool is absent.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from kennis.engine.corpus.converters import (
    ConversionBatch,
    MineruConverter,
    MineruOptions,
    default_converter,
)
from kennis.engine.errors import ConversionFailed, ConverterUnavailable

# A fake MinerU. It parses the flags the converter passes, writes one markdown
# file per staged input in the nested layout the real tool produces, and can
# be told to fail one document or all of them.
FAKE_MINERU = r"""#!/bin/sh
set -e
while [ $# -gt 0 ]; do
    case "$1" in
        -p) input_dir="$2"; shift 2 ;;
        -o) output_dir="$2"; shift 2 ;;
        -b) backend="$2"; shift 2 ;;
        -s|-e) shift 2 ;;
        *) shift ;;
    esac
done
echo "backend=$backend" >> "$MINERU_FAKE_LOG"
echo "device=${MINERU_DEVICE_MODE-unset} source=${MINERU_MODEL_SOURCE-unset}" \
    >> "$MINERU_FAKE_LOG"
for staged in "$input_dir"/*; do
    stem=$(basename "$staged")
    stem=${stem%.*}
    case "$stem" in
        *$MINERU_FAKE_SKIP*) continue ;;
    esac
    mkdir -p "$output_dir/$stem/auto"
    printf '# %s\n\nConverted body.\n' "$stem" > "$output_dir/$stem/auto/$stem.md"
    printf 'tiny\n' > "$output_dir/$stem/auto/${stem}_small.md"
    printf '[{"type":"page_aside_text","page_idx":0,' > "$tmp_json"
    printf '"text":"arXiv:1101.1764v2 [astro-ph.IM]"}]' >> "$tmp_json"
    cp "$tmp_json" "$output_dir/$stem/auto/${stem}_content_list.json"
done
exit "${MINERU_FAKE_EXIT-0}"
"""


@pytest.fixture
def fake_mineru(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Put a fake `mineru` first on PATH and return the log it writes."""
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    script = binary_dir / "mineru"
    log = tmp_path / "mineru.log"
    script.write_text(
        FAKE_MINERU.replace("$tmp_json", str(tmp_path / "content.json")),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{binary_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("MINERU_FAKE_LOG", str(log))
    monkeypatch.setenv("MINERU_FAKE_SKIP", "__never_matches__")
    return log


@pytest.fixture
def no_mineru(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An environment with no `mineru` anywhere on PATH."""
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))


def a_pdf(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.7\nnot really a pdf\n")
    return path


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def test_the_converter_knows_whether_it_can_run(fake_mineru: Path):
    assert MineruConverter().is_available() is True


def test_an_absent_converter_says_so(no_mineru: None):
    assert MineruConverter().is_available() is False


def test_a_missing_converter_reports_how_to_install_it(no_mineru: None, tmp_path: Path):
    """Never an `ImportError`: the tool is driven as a subprocess precisely so
    that its absence is a fact to report rather than an import that explodes."""
    with pytest.raises(ConverterUnavailable) as raised:
        MineruConverter().convert([a_pdf(tmp_path / "paper.pdf")])

    message = f"{raised.value} {raised.value.resolution}"
    assert "mineru" in message
    assert "--extra mineru" in message


def test_the_install_hint_is_reported_once_for_a_whole_batch(
    no_mineru: None, tmp_path: Path
):
    """A folder of fifty PDFs would otherwise produce fifty copies of the same
    instructions, one at a time, over a run that cannot succeed."""
    paths = [a_pdf(tmp_path / f"paper-{index}.pdf") for index in range(50)]

    with pytest.raises(ConverterUnavailable) as raised:
        MineruConverter().convert(paths)

    assert str(raised.value).count("--extra") <= 1


def test_the_hint_names_the_formats_that_needed_the_converter(
    no_mineru: None, tmp_path: Path
):
    with pytest.raises(ConverterUnavailable) as raised:
        MineruConverter().convert(
            [a_pdf(tmp_path / "a.pdf"), a_pdf(tmp_path / "b.docx")]
        )

    assert "DOCX" in str(raised.value)
    assert "PDF" in str(raised.value)


def test_converting_nothing_needs_no_converter(no_mineru: None):
    """An empty batch must not fail on a tool it was never going to run."""
    assert MineruConverter().convert([]) == ConversionBatch(markdown={})


def test_the_converter_declares_which_formats_it_handles():
    assert MineruConverter().formats == frozenset({"pdf", "docx", "pptx", "xlsx"})


def test_the_default_converter_is_the_only_one_v0_1_has():
    assert isinstance(default_converter(), MineruConverter)


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------


def test_a_batch_comes_back_keyed_by_the_original_path(
    fake_mineru: Path, tmp_path: Path
):
    first = a_pdf(tmp_path / "first.pdf")
    second = a_pdf(tmp_path / "second.pdf")

    batch = MineruConverter().convert([first, second])

    assert set(batch.markdown) == {first, second}
    assert "Converted body." in batch.markdown[first]


def test_two_documents_of_the_same_name_do_not_collide(
    fake_mineru: Path, tmp_path: Path
):
    """MinerU names its output directory after the input's stem, so two
    `README.pdf` from different folders would write to the same place and one
    would silently win."""
    first = a_pdf(tmp_path / "one" / "README.pdf")
    second = a_pdf(tmp_path / "two" / "README.pdf")

    batch = MineruConverter().convert([first, second])

    assert set(batch.markdown) == {first, second}


def test_the_whole_batch_is_one_process(fake_mineru: Path, tmp_path: Path):
    """MinerU spends around twenty seconds loading its model stack before it
    converts anything, so a process per document pays that toll every time."""
    paths = [a_pdf(tmp_path / f"p{index}.pdf") for index in range(4)]

    MineruConverter().convert(paths)

    assert fake_mineru.read_text(encoding="utf-8").count("backend=") == 1


def test_the_largest_markdown_output_is_the_one_taken(
    fake_mineru: Path, tmp_path: Path
):
    """The nesting depth varies by version and backend, so the markdown is
    found by searching rather than by a hardcoded path - and a run can leave
    more than one file."""
    batch = MineruConverter().convert([a_pdf(tmp_path / "paper.pdf")])

    assert "Converted body." in batch.markdown[tmp_path / "paper.pdf"]


def test_page_one_text_is_carried_out_of_the_temporary_directory(
    fake_mineru: Path, tmp_path: Path
):
    """A paper's own identifier is systematically absent from the converted
    markdown - MinerU classifies the `arXiv:` stamp as page furniture - and it
    survives only in the content list, which is discarded with the run."""
    path = a_pdf(tmp_path / "paper.pdf")

    batch = MineruConverter().convert([path])

    assert "arXiv:1101.1764v2" in batch.front_page[path]


def test_a_converter_failure_fails_only_its_own_document(
    fake_mineru: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A path missing from `markdown` is that document's failure alone. The
    tool converts what it can and records the rest in its own log, so one bad
    file must not cost the others."""
    good = a_pdf(tmp_path / "good.pdf")
    bad = a_pdf(tmp_path / "doomed.pdf")
    monkeypatch.setenv("MINERU_FAKE_SKIP", "doomed")

    batch = MineruConverter().convert([good, bad])

    assert good in batch.markdown
    assert bad not in batch.markdown


def test_a_nonzero_exit_with_some_output_is_a_reason_not_a_failure(
    fake_mineru: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    good = a_pdf(tmp_path / "good.pdf")
    monkeypatch.setenv("MINERU_FAKE_EXIT", "1")

    batch = MineruConverter().convert([good])

    assert good in batch.markdown
    assert batch.failure_reason is not None


def test_a_run_that_produced_nothing_at_all_is_a_failure(
    fake_mineru: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("MINERU_FAKE_SKIP", "doomed")
    monkeypatch.setenv("MINERU_FAKE_EXIT", "1")

    with pytest.raises(ConversionFailed):
        MineruConverter().convert([a_pdf(tmp_path / "doomed.pdf")])


def test_a_converter_that_cannot_be_started_is_reported_not_raised_raw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """An unexecutable file on PATH is found by `which` and then fails to run;
    the caller must see a domain exception rather than an `OSError`."""
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    (binary_dir / "mineru").write_text("not executable", encoding="utf-8")
    monkeypatch.setenv("PATH", f"{binary_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(
        "kennis.engine.corpus.converters.shutil.which",
        lambda name: str(binary_dir / "mineru"),
    )

    with pytest.raises(ConversionFailed):
        MineruConverter().convert([a_pdf(tmp_path / "paper.pdf")])


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------


def test_the_backend_is_passed_as_a_flag(fake_mineru: Path, tmp_path: Path):
    MineruConverter(MineruOptions(backend="vlm-transformers")).convert(
        [a_pdf(tmp_path / "paper.pdf")]
    )

    assert "backend=vlm-transformers" in fake_mineru.read_text(encoding="utf-8")


def test_a_setting_of_auto_is_expressed_by_the_variable_being_absent(
    fake_mineru: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """MinerU rejects the literal string: "MINERU_MODEL_SOURCE=auto is not
    supported. Unset it to use auto detection." The variable is actively
    removed, so an `auto` already exported in the user's shell cannot reach
    it either."""
    monkeypatch.setenv("MINERU_MODEL_SOURCE", "auto")

    MineruConverter(MineruOptions(model_source="auto")).convert(
        [a_pdf(tmp_path / "paper.pdf")]
    )

    assert "source=unset" in fake_mineru.read_text(encoding="utf-8")


def test_an_explicit_setting_reaches_the_process(fake_mineru: Path, tmp_path: Path):
    MineruConverter(MineruOptions(model_source="huggingface")).convert(
        [a_pdf(tmp_path / "paper.pdf")]
    )

    assert "source=huggingface" in fake_mineru.read_text(encoding="utf-8")


def test_a_page_limit_restricts_the_run(fake_mineru: Path, tmp_path: Path):
    """Two pages are enough to learn what every document in a folder *is*, at
    about a second each against sixteen for a full conversion."""
    batch = MineruConverter().convert([a_pdf(tmp_path / "paper.pdf")], page_limit=2)

    assert batch.markdown


def test_a_run_that_overruns_its_timeout_is_cancelled_and_says_nothing_was_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """There was no timeout at all in the original, which meant one wedged
    conversion hung the whole command with nothing to interrupt but Ctrl-C."""
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    script = binary_dir / "mineru"
    script.write_text("#!/bin/sh\nsleep 30\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{binary_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr("kennis.engine.corpus.converters._STARTUP_GRACE_SECONDS", 0)
    monkeypatch.setattr("kennis.engine.corpus.converters._SECONDS_PER_DOCUMENT", 1)

    with pytest.raises(ConversionFailed) as raised:
        MineruConverter().convert([a_pdf(tmp_path / "paper.pdf")])

    assert "Nothing was written" in str(raised.value)
