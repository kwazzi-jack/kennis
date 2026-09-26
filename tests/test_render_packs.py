"""The sentences a reader gets from the pack commands.

The engine names a finding and never phrases it (#81), so every word a
user reads about a pack is produced here - and until this module existed
`render/packs.py` was the least tested file in the project at 74%, with
five of `describe_problem`'s seven kinds having no test at all. The
wording layer is the part a defect in is visible to a person and invisible
to every other test.

These are unit tests of pure functions: they build the engine value the
renderer takes and assert on the string. Nothing here touches disk.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final, cast

import pytest

from kennis.engine.pack.installed import (
    InstalledPack,
    Overlap,
    OverlapKind,
    PackRemoval,
)
from kennis.engine.pack.resolve import Action, Verdict
from kennis.engine.pack.resolve import Declaration as PackDeclaration
from kennis.engine.pack.resolve import Existing as PackExisting
from kennis.engine.pack.schema import KennisHeader, Pack, PackIdentity
from kennis.engine.pack.store import InstallOutcome, PackInstall, PackState
from kennis.engine.pack.update import PackUpdate
from kennis.engine.pack.validate import (
    PackProblem,
    PackReport,
    ProblemKind,
    VersionRefusal,
)
from kennis.render.packs import (
    describe_action,
    describe_claim_needed,
    describe_damage,
    describe_declarations,
    describe_deferred,
    describe_install,
    describe_installed,
    describe_lost_source,
    describe_moved,
    describe_overlap,
    describe_problem,
    describe_recorded,
    describe_refusal,
    describe_removal,
    describe_sync,
    describe_sync_summary,
    describe_unfetched,
    describe_unreadable,
    describe_unselected,
    describe_update_needed,
    describe_verdict,
    describe_what_remove_cannot_reach,
    describe_when,
    remedy_for,
)

DIGEST = "a" * 64
OTHER_DIGEST = "b" * 64


def a_pack(identifier: str = "boepie") -> Pack:
    return Pack(
        kennis=KennisHeader(schema_version=1),
        pack=PackIdentity(id=identifier, name="n", version="1.0.0"),
    )


def a_state(
    *,
    pack_id: str = "boepie",
    files: dict[str, str] | None = None,
    first_applied_at: str = "2026-01-01T00:00:00Z",
    applied_at: str = "2026-01-01T00:00:00Z",
    source_path: str = "/provider/p.ken.yml",
) -> PackState:
    return PackState(
        pack_id=pack_id,
        pack_version="1.0.0",
        schema_version=1,
        file_sha256=DIGEST,
        files=files if files is not None else {"notes/one.md": DIGEST},
        first_applied_at=first_applied_at,
        applied_at=applied_at,
        applied_by="0.2",
        source_path=source_path,
    )


# Tells "the test said nothing about the declaration" apart from "the test
# said there is none", which is the state this renderer has a branch for.
_DEFAULT_DECLARATION: Final = Pack(
    kennis=KennisHeader(schema_version=1),
    pack=PackIdentity(id="boepie", name="n", version="1.0.0"),
)


def an_installed(
    *,
    declaration: Pack | None = _DEFAULT_DECLARATION,
    verified: bool = True,
    applied_at: str = "2026-01-01T00:00:00Z",
    source_path: str = "/provider/p.ken.yml",
) -> InstalledPack:
    return InstalledPack(
        state=a_state(applied_at=applied_at, source_path=source_path),
        declaration=declaration,
        verified=verified,
    )


# ---------------------------------------------------------------------------
# describe_problem: one sentence per kind, and there are seven kinds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("source-missing", "is declared and is not a directory"),
        ("escapes-root", "resolves outside the pack"),
        ("symlink", "is a symlink"),
        ("digest-absent", "has a recorded digest and is not in the pack"),
        ("undigested", "has no recorded digest"),
    ],
)
def test_each_simple_problem_names_its_file_and_says_what_is_wrong(
    kind: ProblemKind, expected: str
):
    sentence = describe_problem(PackProblem(kind=kind, path="notes/one.md"))

    assert sentence.startswith("notes/one.md")
    assert expected in sentence


def test_an_overlap_names_both_trees_and_why_it_matters():
    """Both, because the reader has to know which pair to separate, and one
    of them alone is not actionable."""
    sentence = describe_problem(
        PackProblem(kind="overlapping-sources", path="notes/", other="notes/deep/")
    )

    assert "notes/" in sentence
    assert "notes/deep/" in sentence
    assert "two destinations" in sentence


def test_a_digest_mismatch_shows_both_sides_shortened():
    """Enough of each hash to compare by eye, and no more: a pair of
    64-character strings on one line is unreadable and says nothing a
    12-character prefix does not."""
    sentence = describe_problem(
        PackProblem(
            kind="digest-mismatch",
            path="notes/one.md",
            recorded=DIGEST,
            actual=OTHER_DIGEST,
        )
    )

    assert DIGEST[:12] in sentence
    assert OTHER_DIGEST[:12] in sentence
    assert DIGEST not in sentence


def test_a_missing_digest_side_reads_as_a_word_not_an_empty_string():
    sentence = describe_problem(
        PackProblem(kind="digest-mismatch", path="notes/one.md", actual=OTHER_DIGEST)
    )

    assert "nothing" in sentence


def test_every_problem_kind_is_covered_by_this_module():
    """The seven kinds are a closed set, and a new one added to the engine
    with no sentence here would fall through to the final `return` and be
    described as undigested - wrong, and silent."""
    kinds: tuple[ProblemKind, ...] = (
        "overlapping-sources",
        "source-missing",
        "escapes-root",
        "symlink",
        "digest-mismatch",
        "digest-absent",
        "undigested",
    )
    described = {describe_problem(PackProblem(kind=kind, path="p")) for kind in kinds}

    assert len(described) == len(kinds), "two kinds share a sentence"


# ---------------------------------------------------------------------------
# refusals
# ---------------------------------------------------------------------------


def test_a_schema_refusal_names_both_versions():
    sentence = describe_refusal(
        VersionRefusal(kind="schema-too-new", required="9", available="1")
    )

    assert "schema 9" in sentence
    assert "1" in sentence


def test_a_version_refusal_never_suggests_editing_the_file():
    """A refusal is not a defect in the pack, so the wording must not send
    an author to fix a file that is correct."""
    sentence = describe_refusal(
        VersionRefusal(kind="kennis-too-old", required="9.0", available="0.2")
    )

    assert "9.0" in sentence
    assert "fix" not in sentence
    assert "edit" not in sentence


def test_both_refusals_resolve_the_same_way():
    upgrade = "uv tool upgrade kennis"
    schema = VersionRefusal(kind="schema-too-new", required="9", available="1")
    old = VersionRefusal(kind="kennis-too-old", required="9.0", available="0.2")

    assert remedy_for(schema) == upgrade
    assert remedy_for(old) == upgrade


# ---------------------------------------------------------------------------
# validate's verdict, update's report
# ---------------------------------------------------------------------------


def test_a_pack_with_a_generated_block_is_told_the_digests_agreed():
    report = PackReport(
        path=Path("p.ken.yml"),
        pack=a_pack(),
        refusal=None,
        problems=(),
        digests_checked=True,
    )

    assert "digests agree" in describe_verdict(report)


def test_a_pack_with_no_generated_block_is_told_less_was_checked():
    """Two amounts of checking share one exit code, and a release pipeline
    is exactly where a forgotten `pack update` should be caught."""
    report = PackReport(
        path=Path("p.ken.yml"),
        pack=a_pack(),
        refusal=None,
        problems=(),
        digests_checked=False,
    )

    assert "no digest was checked" in describe_verdict(report)


def test_one_disagreeing_file_takes_a_singular_verb():
    assert describe_update_needed(1) == "1 file disagrees with the generated block"


def test_several_disagreeing_files_take_a_plural_verb():
    assert describe_update_needed(3) == "3 files disagree with the generated block"


def test_an_unchanged_update_says_the_file_was_not_touched():
    result = PackUpdate(
        path=Path("p.ken.yml"), outcome="unchanged", files=2, unselected=0
    )

    assert "untouched" in describe_recorded(result)


def test_a_changed_update_says_what_it_recorded():
    result = PackUpdate(
        path=Path("p.ken.yml"), outcome="updated", files=2, unselected=0
    )

    assert describe_recorded(result) == "2 files recorded"


def test_unselected_files_are_counted_without_a_pronoun():
    """ "5 files ... for it" is the agreement slip this wording avoids by
    not using the construction at all."""
    assert describe_unselected(5) == "5 files matched no include pattern"
    assert describe_unselected(1) == "1 file matched no include pattern"


# ---------------------------------------------------------------------------
# installing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        ("installed", "2 files installed"),
        ("unchanged", "already installed"),
        ("repaired", "damaged"),
    ],
)
def test_each_install_outcome_reads_differently(outcome: InstallOutcome, expected: str):
    """`repaired` earns its place: a reader seeing it twice in a row has
    something to investigate that `installed` would hide."""
    install = PackInstall(
        pack_id="boepie", outcome=outcome, files=2, literature=0, docs=0
    )

    assert expected in describe_install(install)


def test_a_pack_that_copies_nothing_still_says_what_it_asked_for():
    install = PackInstall(
        pack_id="boepie", outcome="installed", files=0, literature=2, docs=1
    )

    described = describe_declarations(install)
    assert described is not None
    assert "2 papers" in described
    assert "1 documentation site" in described
    # Never "added": nothing is fetched until a sync, and a word implying
    # the papers are in the corpus would promise something untrue.
    assert "not yet fetched" in described


def test_a_pack_with_only_content_declares_nothing_extra():
    install = PackInstall(
        pack_id="boepie", outcome="installed", files=3, literature=0, docs=0
    )

    assert describe_declarations(install) is None


# ---------------------------------------------------------------------------
# reading the store
# ---------------------------------------------------------------------------


def test_a_listed_pack_shows_its_version_and_size():
    assert describe_installed(an_installed()) == "1.0.0, 1 file"


def test_a_pack_added_and_never_re_applied_shows_one_timestamp():
    """Two identical timestamps on one line say nothing twice."""
    described = describe_when(an_installed())

    assert described == "added 2026-01-01T00:00:00Z"


def test_a_re_applied_pack_shows_both_timestamps():
    """They answer different questions: how long this pack has been the
    incumbent, and whether the provider has run recently."""
    described = describe_when(
        an_installed(applied_at="2026-06-01T00:00:00Z"),
    )

    assert "added 2026-01-01T00:00:00Z" in described
    assert "last applied 2026-06-01T00:00:00Z" in described


def test_an_intact_pack_has_nothing_wrong_with_it():
    assert describe_damage(an_installed()) is None


def test_a_store_that_does_not_verify_says_the_pack_is_not_believed():
    described = describe_damage(an_installed(verified=False))

    assert described is not None
    assert "not believed" in described


def test_an_unparseable_declaration_is_reported_as_its_own_fault():
    """A different repair from damaged content: this is a file kennis
    itself wrote and copied."""
    described = describe_damage(an_installed(declaration=None))

    assert described == "the stored declaration could not be read"


def test_damaged_content_is_reported_before_an_unreadable_declaration():
    """Both at once is one pack, and the content is the one a sync acts
    on, so it is the one named."""
    described = describe_damage(an_installed(declaration=None, verified=False))

    assert described is not None
    assert "not believed" in described


def test_a_lost_source_quotes_the_path_and_names_the_provider():
    described = describe_lost_source(an_installed(source_path="/gone/p.ken.yml"))

    assert "/gone/p.ken.yml" in described
    assert "run the provider" in described


def test_unreadable_directories_are_counted_and_named():
    described = describe_unreadable(("alpha", "beta"))

    assert "2 directories" in described
    assert "alpha, beta" in described


def test_one_unreadable_directory_takes_the_singular():
    assert describe_unreadable(("alpha",)).startswith("1 directory")


# ---------------------------------------------------------------------------
# overlaps
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "noun"),
    [
        ("literature", "paper"),
        ("docs", "documentation project"),
        ("notes", "note"),
        ("context", "context file"),
    ],
)
def test_an_overlap_is_named_by_what_it_is_not_by_its_section(
    kind: OverlapKind, noun: str
):
    """ "notes" is the right diff key and the wrong noun: it says nothing
    about what two packs are fighting over."""
    overlap = Overlap(kind=kind, key="k", pack_ids=("alpha", "beta"), owner="alpha")

    assert describe_overlap(overlap).startswith(noun)


def test_an_overlap_names_both_packs_with_a_conjunction():
    """ "declared by alpha, beta" mid-sentence reads as a list that was cut
    off."""
    overlap = Overlap(
        kind="docs", key="stimela", pack_ids=("alpha", "beta"), owner="alpha"
    )

    described = describe_overlap(overlap)
    assert "alpha and beta" in described
    assert "alpha owns it" in described


def test_three_packs_sharing_one_item_all_appear():
    overlap = Overlap(
        kind="docs",
        key="stimela",
        pack_ids=("alpha", "beta", "gamma"),
        owner="beta",
    )

    described = describe_overlap(overlap)
    assert "alpha, beta and gamma" in described
    assert "beta owns it" in described


def test_the_overlap_says_why_that_pack_owns_it():
    """The rule is stable and not obvious - earliest, never most recent -
    and a reader who does not know it cannot predict the next run."""
    overlap = Overlap(
        kind="docs", key="stimela", pack_ids=("alpha", "beta"), owner="alpha"
    )

    assert "earliest installation" in describe_overlap(overlap)


# ---------------------------------------------------------------------------
# removing
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Converging a bundle
# ---------------------------------------------------------------------------


def a_sync(**counts: int) -> dict[Verdict, int]:
    """The counts a sync produced, which is all the summary line reads.
    Rebuilt as a `Verdict` map rather than passed through, because
    `**kwargs` widens the key type to `str`."""
    verdicts: dict[Verdict, int] = {}
    for name, count in counts.items():
        verdict: Verdict = cast(Verdict, name)
        verdicts[verdict] = count
    return verdicts


def test_a_sync_that_did_nothing_and_had_nothing_to_do_says_so():
    assert describe_sync(a_sync()) == "nothing declared by any installed pack"


def test_a_sync_that_changed_nothing_says_the_bundle_is_in_step():
    assert describe_sync(a_sync(keep=3)) == "3 files already in step"


def test_a_sync_counts_only_what_it_actually_changed():
    described = describe_sync(a_sync(write=1, rewrite=1, keep=4))

    assert described == "2 files changed, of 6"


def test_a_file_kennis_declined_to_write_is_not_reported_as_in_step():
    """It is precisely a file that is not in step. Saying otherwise would
    report the protection as if it were agreement."""
    described = describe_sync(a_sync(keep=2, edited=1))

    assert described == "2 files in step, 1 left as yours"


def test_a_bundle_where_everything_is_the_users_does_not_say_zero():
    assert describe_sync(a_sync(yours=2)) == "2 files left as yours"


def test_the_corpus_counts_documents_rather_than_files():
    """The same line for both destinations, and the noun is the whole of
    the difference: a bundle holds files and a corpus holds documents."""
    described = describe_sync(a_sync(write=2, keep=1), noun="document")

    assert described == "2 documents changed, of 3"


def test_the_commit_summary_names_only_what_changed():
    """It lands in `corpus history`, where "3 keep" is the absence of
    news and would make two different commits read the same."""
    summary = describe_sync_summary(a_sync(write=2, keep=5, delete=1))

    assert summary == "2 write, 1 delete"


def test_a_commit_summary_for_a_sync_that_changed_nothing_still_reads():
    assert describe_sync_summary(a_sync(keep=3)) == "nothing to change"


def test_a_deferred_declaration_names_the_pack_that_lost():
    """A provider whose content never appears has no other way to find
    out why."""
    described = describe_deferred((("one.md", "beta"), ("two.md", "beta")))

    assert "2 files" in described
    assert "beta" in described
    assert "installed earlier" in described


def test_the_edit_summary_says_how_to_keep_the_file_for_good():
    """Reported every run otherwise, which is correct and eventually
    tiresome - so the way out has to be said."""
    described = describe_claim_needed(1)

    assert "owner: user" in described


def a_declaration(pack_id: str = "alpha") -> PackDeclaration:
    return PackDeclaration(
        address="one.md",
        pack_id=pack_id,
        digest=DIGEST,
        store_path=Path("/store/one.md"),
    )


def an_existing(owner: str = "pack:beta") -> PackExisting:
    return PackExisting(
        address="one.md",
        owner=owner,
        body_digest=DIGEST,
        written_digest=DIGEST,
        pack_digest=DIGEST,
    )


@pytest.mark.parametrize(
    ("verdict", "expected"),
    [
        ("write", "added by alpha"),
        ("rewrite", "updated by alpha"),
        ("delete", "no pack declares it now"),
        ("keep", "unchanged"),
        ("edited", "you edited this"),
        ("yours", "yours"),
    ],
)
def test_each_verdict_reads_as_what_happened(verdict: Verdict, expected: str):
    action = Action(
        address="one.md",
        verdict=verdict,
        declaration=a_declaration(),
        existing=an_existing(),
    )

    described = describe_action(action)
    assert described.startswith("one.md: ")
    assert expected in described


def test_a_file_taken_over_names_both_owners():
    """Which pack has it now and which had it before, because the fact
    that ownership moved is the whole content of the line."""
    action = Action(
        address="one.md",
        verdict="adopt",
        declaration=a_declaration(),
        existing=an_existing(),
    )

    described = describe_action(action)
    assert "alpha" in described
    assert "pack:beta" in described


def test_a_removal_counts_what_it_dropped():
    removal = PackRemoval(pack_id="boepie", files=3, recorded=True)

    assert describe_removal(removal) == "3 files dropped from the store"


def test_a_partial_install_is_not_reported_as_zero_files():
    """0 there means nothing recorded what was in the directory, which is
    a different claim from the directory having been empty."""
    removal = PackRemoval(pack_id="boepie", files=0, recorded=False)

    described = describe_removal(removal)
    assert "no state file" in described
    assert "0 files" not in described


def test_remove_says_what_it_could_not_reach():
    """A user running `remove` will reasonably expect the content to be
    gone, and it is not - not from the corpus and not from any project.
    Both scopes are named, because each is reached by its own sync."""
    described = describe_what_remove_cannot_reach()

    assert "corpus" in described
    assert "project" in described
    assert "nothing this pack supplied has been removed" in described


def test_an_unfetched_declaration_is_named_and_not_counted_alone():
    """Which paper did not arrive is the whole of what a reader needs,
    and the identifier is what they would search for."""
    described = describe_unfetched(("arxiv:2409.19750", "doi:10.1000/x"))

    assert "arxiv:2409.19750" in described
    assert "doi:10.1000/x" in described
    assert "tried again" in described


def test_one_unfetched_declaration_takes_the_singular():
    assert describe_unfetched(("arxiv:1",)).startswith("1 declaration")


def test_a_moved_file_is_named_with_both_paths():
    """Both, because the declared address is how a pack refers to the
    file and the path is where the reader will find it."""
    said = describe_moved((("conventions/naming.md", "conventions/.naming.md"),))

    assert "conventions/naming.md" in said
    assert "conventions/.naming.md" in said


def test_several_moved_files_are_counted_and_listed():
    said = describe_moved(
        (("a.md", ".a.md"), ("b.md", "kept/b.md")),
    )

    assert said.startswith("2 files")
    assert "a.md is at .a.md" in said
    assert "b.md is at kept/b.md" in said
