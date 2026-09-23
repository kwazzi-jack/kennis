"""What a corpus costs as it grows.

Two kinds of assertion, and the difference matters. The **scan counts** are
deterministic and run by default: they pin how many times a command reads the
whole collection, which is the thing that decides the shape of the cost
curve. The **timings** are marked `slow`, are machine-dependent, and carry
bounds loose enough to catch a change of complexity rather than a change of
hardware.

Nothing here asserts that kennis is fast. It asserts that adding the
thousandth document does not cost a thousand times what the first one did.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Final

import pytest

from kennis.engine.corpus.add import add_notes
from kennis.engine.corpus.collection import Collection
from kennis.engine.history.freshness import index_freshness
from kennis.engine.history.repository import Repository, initialise_corpus


@pytest.fixture
def scans(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Every full read of a collection, in order.

    Counted rather than timed, because the count is what a reader can reason
    about: `survey` and `contents` both walk every document and parse its
    frontmatter, so one call is one pass over the corpus whatever the machine.
    """
    recorded: list[str] = []

    def counted[Result](
        name: str, original: Callable[[Collection], Result]
    ) -> Callable[[Collection], Result]:
        def counting(self: Collection) -> Result:
            recorded.append(name)
            return original(self)

        return counting

    monkeypatch.setattr(Collection, "survey", counted("survey", Collection.survey))
    monkeypatch.setattr(
        Collection, "contents", counted("contents", Collection.contents)
    )
    yield recorded


@pytest.fixture
def notes(tmp_path: Path) -> Collection:
    initialise_corpus(tmp_path / "corpus")
    return Collection(root=tmp_path / "corpus", name="notes")


def sources(tmp_path: Path, count: int, *, prefix: str = "note") -> list[str]:
    directory = tmp_path / "sources"
    directory.mkdir(parents=True, exist_ok=True)
    made: list[str] = []
    for number in range(count):
        path = directory / f"{prefix}-{number}.md"
        path.write_text(
            f"# {prefix} {number}\n\nSediment and calibration, item {number}.\n",
            encoding="utf-8",
        )
        made.append(str(path))
    return made


def test_one_add_of_many_files_scans_the_collection_once(
    notes: Collection, tmp_path: Path, scans: list[str]
):
    """`Uniqueness` is loaded once per batch and updated in place, so the
    second document in a command sees the first without a second pass."""
    add_notes(notes, sources(tmp_path, 25))

    assert scans.count("survey") == 1


def test_adding_one_file_at_a_time_scans_once_per_command(
    notes: Collection, tmp_path: Path, scans: list[str]
):
    """The cost that actually bites. Each command rebuilds the uniqueness
    record from the whole collection, so adding documents one at a time is
    quadratic in the corpus overall - acceptable, and worth knowing before a
    future caller loops over ten thousand files expecting otherwise."""
    for source in sources(tmp_path, 5):
        add_notes(notes, [source])

    assert scans.count("survey") == 5


# ---------------------------------------------------------------------------
# Timed. Bounds loose enough to catch a change of complexity, not of hardware.
# ---------------------------------------------------------------------------

# Big enough that a quadratic term dominates and small enough to build in a
# few seconds. Freshness is the claim being checked, not the corpus size.
_MANY: Final = 400


@pytest.mark.slow
def test_freshness_costs_what_changed_and_not_what_is_held(
    notes: Collection, tmp_path: Path
):
    """Design section 12 claims freshness is a diff, so O(changed files)
    rather than O(corpus). With four hundred documents held and one changed,
    it must therefore cost far less than reading the collection does.

    Asserted as a ratio against a full survey measured on the same machine in
    the same run, so the bound says something about complexity rather than
    about this laptop.
    """
    add_notes(notes, sources(tmp_path, _MANY))
    repository = Repository(notes.root)
    repository.commit("add", scope="notes", summary=f"{_MANY} added")
    built_from = repository.head()
    assert built_from is not None

    one = next(notes.path.rglob("*.md"))
    one.write_text(one.read_text(encoding="utf-8") + "\nAn edit.\n", encoding="utf-8")

    started = time.monotonic()
    notes.survey()
    reading_everything = time.monotonic() - started

    started = time.monotonic()
    freshness = index_freshness(repository, collection="notes", built_from=built_from)
    diffing = time.monotonic() - started

    assert freshness.state == "stale"
    assert freshness.changed == 1
    # Measured at 0.06 of a survey on the development machine, so half leaves
    # eight times the headroom for a slower one. The bound has to sit below
    # 1.0 to mean anything: a freshness that walked the corpus would score
    # about 1.0, so a looser bound would pass the very regression it names.
    assert diffing < reading_everything * 0.5


@pytest.mark.slow
def test_a_large_batch_add_stays_linear(notes: Collection, tmp_path: Path):
    """One scan per batch means four times the documents costs about four
    times as much, not sixteen. The bound is eight, which a quadratic term
    would break and a slow machine would not.
    """
    started = time.monotonic()
    add_notes(notes, sources(tmp_path, 100, prefix="small"))
    small = time.monotonic() - started

    started = time.monotonic()
    add_notes(notes, sources(tmp_path, 400, prefix="large"))
    large = time.monotonic() - started

    assert len(notes.contents().documents) == 500
    assert large < small * 8
