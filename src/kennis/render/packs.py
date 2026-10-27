"""Wording for the pack commands.

The engine returns a `PackProblem` carrying a kind and the fields that kind
needs; the sentence lives here, because a front end that was handed the
sentence could not rewrap it, group it, or say it differently. Concern #81.
"""

from __future__ import annotations

from collections.abc import Sequence

from kennis.engine.pack.installed import InstalledPack, Overlap, PackRemoval
from kennis.engine.pack.resolve import Action, Verdict
from kennis.engine.pack.store import PackInstall
from kennis.engine.pack.update import PackUpdate
from kennis.engine.pack.validate import PackProblem, PackReport, VersionRefusal
from kennis.engine.refusals import Refusal
from kennis.render.refusals import describe_refusal as describe_add_refusal
from kennis.render.words import count_of, joined

_DIGEST_SHOWN = 12


def describe_install(install: PackInstall) -> str:
    """What an install did, and the word `repaired` earning its place.

    Three outcomes rather than two, because "the provider shipped something
    new" and "what was here was damaged and has been put back" are
    different facts about the machine, and a reader seeing `repaired`
    twice in a row has something to investigate that `installed` would hide.
    """
    counted = count_of(install.files, "file")
    if install.outcome == "unchanged":
        return f"{counted}, already installed"
    if install.outcome == "repaired":
        return f"{counted}, restored after the store was found damaged"
    return f"{counted} installed"


def describe_declarations(install: PackInstall) -> str | None:
    """What the pack asked for that no file was copied for, or None.

    **Declared, never added.** Literature is fetched and documentation is
    crawled by a sync that does not exist yet, so a word implying the
    papers are in the corpus would promise something untrue.
    """
    parts = []
    if install.literature:
        parts.append(count_of(install.literature, "paper"))
    if install.docs:
        parts.append(count_of(install.docs, "documentation site"))
    if not parts:
        return None
    return f"{' and '.join(parts)} declared, not yet fetched"


def describe_unselected(count: int) -> str:
    """Files in a declared source that no `include` pattern matched.

    Said out loud because the default is `**/*.md`, so a PDF or a `.csv`
    an author dropped into the source is discarded by a pattern they may
    never have written. A file an explicit `exclude:` removed is not
    counted here: that one was intent.
    """
    # No pronoun. The first wording ended "so no digest was recorded for
    # it", which reads as "5 files ... for it" - the same slip as "1 file
    # disagree" earlier in this milestone. Avoiding the construction is
    # more reliable than conditioning on the count twice in one sentence.
    return f"{count_of(count, 'file')} matched no include pattern"


def describe_copied(relative: str) -> str:
    """A local file `pack add` copied into the pack."""
    return f"copied into the pack as {relative}"


def describe_deleted(relative: str) -> str:
    """A copy `pack remove` deleted, because no entry names it any more."""
    return f"deleted {relative}, which no entry names any more"


def describe_verdict(report: PackReport) -> str:
    """What a clean check actually established.

    **Two amounts of checking share one exit code.** A pack with no
    `generated` block is valid and had no digest compared, and reporting
    both as "valid" would use one word for two different assurances - which
    matters most in a release pipeline, where a forgotten `pack update` is
    exactly what this command is run to catch.
    """
    if report.digests_checked:
        return "valid, and the digests agree with the content"
    return "valid, and no digest was checked: there is no generated block"


def describe_recorded(result: PackUpdate) -> str:
    """What an update wrote, or found it did not need to write."""
    counted = count_of(result.files, "file")
    if result.outcome == "unchanged":
        return f"{counted} already recorded, so the file is untouched"
    return f"{counted} recorded"


def describe_described(key: str, citekey: str) -> str:
    """One paper `pack update` described, and the citekey written into its
    entry: the handle the person cites it by from now on."""
    return f"{key} as {citekey}"


def describe_undescribed(keys: Sequence[str]) -> str:
    """Papers `pack update` could make no citekey for (#459).

    Said because the consequence is not visible here: each machine's sync
    then makes its own, against its own corpus, and two machines can file
    the paper under different citekeys.
    """
    return (
        f"no citekey could be made for {joined(list(keys))}, so each corpus "
        "makes its own when it adds the paper; give `citekey:` to fix one"
    )


def describe_problem(problem: PackProblem) -> str:
    """One line about one finding, naming the file it is about."""
    if problem.kind == "overlapping-sources":
        return (
            f"{problem.path} and {problem.other} are the same tree or one "
            "contains the other, so a file under them has two destinations"
        )
    if problem.kind == "source-missing":
        return f"{problem.path} is declared and is not a directory in the pack"
    if problem.kind == "escapes-root":
        return f"{problem.path} resolves outside the pack and has not been read"
    if problem.kind == "symlink":
        return f"{problem.path} is a symlink, and a pack's files are not followed"
    if problem.kind == "digest-mismatch":
        return (
            f"{problem.path} has changed since the last update: the file "
            f"records {_short(problem.recorded)} and holds "
            f"{_short(problem.actual)}"
        )
    if problem.kind == "digest-absent":
        return f"{problem.path} has a recorded digest and is not in the pack"
    if problem.kind == "file-missing":
        return f"{problem.path} is declared and is not a file in the pack"
    if problem.kind == "declared-twice":
        return f"{problem.path} is named by two entries, so it would be added twice"
    return f"{problem.path} is in the pack and has no recorded digest"


def describe_refusal(refusal: VersionRefusal) -> str:
    """Why this kennis may not read this pack, in its own words.

    Not a defect in the file, so the wording never suggests editing it.
    """
    if refusal.kind == "schema-too-new":
        return (
            f"this pack is written against schema {refusal.required} and this "
            f"kennis understands {refusal.available}"
        )
    return f"this pack needs kennis {refusal.required} and this is {refusal.available}"


def remedy_for(refusal: VersionRefusal) -> str:
    """The command that resolves a refusal.

    The same one for both kinds, because both mean the installed kennis is
    behind what the pack was written for. Rule 4.4: it runs as printed.
    """
    del refusal
    return "uv tool upgrade kennis"


def describe_update_needed(count: int) -> str:
    """The one line that says why every digest finding below it happened.

    Every digest problem has the same cause - the content changed and the
    generated block was not rewritten - so saying it once above the list is
    better than repeating it on every line.

    The command that fixes it - `kennis pack update` - is printed once
    beside this line rather than on every finding, for the same reason.
    """
    if count == 1:
        return "1 file disagrees with the generated block"
    return f"{count} files disagree with the generated block"


def _short(digest: str | None) -> str:
    """Enough of a digest to compare by eye, and no more."""
    if digest is None:
        return "nothing"
    return digest[:_DIGEST_SHOWN]


# ---------------------------------------------------------------------------
# Reading the store: `pack list`, `pack status`, `pack uninstall`
# ---------------------------------------------------------------------------

# How a pack's kind of item is named to a reader. The engine's `OverlapKind`
# is the section name, which is the right key and the wrong noun: "notes"
# says nothing about what two packs are fighting over.
_OVERLAP_NOUNS = {
    "literature": "paper",
    "docs": "documentation project",
    "notes": "note",
    "context": "context file",
}


def describe_installed(installed: InstalledPack) -> str:
    """One pack in a listing: what it is, and how much of it there is."""
    state = installed.state
    return f"{state.pack_version}, {count_of(len(state.files), 'file')}"


def describe_holdings(packs: Sequence[InstalledPack]) -> tuple[str, ...]:
    """What this installation holds, one line per pack.

    **Design section 11, and the shared-bytes property is the point.**
    These lines are the generated half of the MCP server's `instructions=`
    block, and they are also what `kennis pack list` prints, so what a
    user reads about their own machine and what a model is told about it
    cannot drift apart.

    Ordered by pack id rather than by install time, because the two
    callers must produce the same bytes on every run and a listing whose
    order depends on when things were added does not.

    A pack whose declaration will not parse is named by its id alone. It
    is still installed and still holds files, so leaving it out would
    describe the installation as smaller than it is - and the id is the
    one fact the store has without the declaration.
    """
    lines: list[str] = []
    for installed in sorted(packs, key=lambda one: one.state.pack_id):
        declaration = installed.declaration
        if declaration is None:
            lines.append(installed.state.pack_id)
            continue
        identity = declaration.pack
        if identity.description:
            lines.append(f"{identity.name} - {identity.description}")
        else:
            lines.append(identity.name)
    return tuple(lines)


def describe_when(installed: InstalledPack) -> str:
    """The two timestamps, and which one means what.

    Both are shown because they answer different questions: the first says
    how long this pack has been the incumbent for anything it shares, and
    the second says whether the provider has run recently. A reader given
    only one of them cannot tell a pack installed today from one installed
    a year ago and refreshed this morning.
    """
    state = installed.state
    if state.first_applied_at == state.applied_at:
        return f"added {state.first_applied_at}"
    return f"added {state.first_applied_at}, last applied {state.applied_at}"


def describe_damage(installed: InstalledPack) -> str | None:
    """What is wrong with this pack's store, or None when nothing is.

    Two different faults, because the repairs differ: content that no
    longer matches what was recorded is fixed by the provider handing the
    pack over again, and a declaration that will not parse is a file
    kennis itself wrote and copied.
    """
    if not installed.verified:
        return (
            "the stored content does not match what was recorded, so this "
            "pack is not believed"
        )
    if installed.declaration is None:
        return "the stored declaration could not be read"
    return None


def describe_unreadable(names: tuple[str, ...]) -> str:
    """Directories under `packs/` that are not installed packs.

    A half-written store: the content directory is there and the state
    file is not. Said out loud because `add` will rewrite it without
    comment and nothing else would ever mention it.
    """
    return (
        f"{count_of(len(names), 'directory', plural='directories')} in the store "
        f"with no readable state: {', '.join(names)}"
    )


def describe_overlap(overlap: Overlap) -> str:
    """Two packs declaring one item, and which of them keeps it.

    Named as a fact about the packs rather than as a warning, because it
    is not a fault: two providers can legitimately ship the same paper.
    What the reader needs is which one wins, and the answer is stable -
    the earliest installation, never the most recent.
    """
    noun = _OVERLAP_NOUNS[overlap.kind]
    return (
        f"{noun} '{overlap.key}' is declared by {joined(overlap.pack_ids)}; "
        f"{overlap.owner} owns it, as the earliest installation"
    )


def describe_lost_source(installed: InstalledPack) -> str:
    """A damaged pack whose source file is no longer on this machine.

    Names the provider rather than a command, because the command that
    fixes it is the provider's own and kennis does not know what it is
    called. The recorded path is quoted so a reader can see whether it is
    a checkout they still have somewhere.
    """
    return (
        f"the pack was added from '{installed.state.source_path}', which is no "
        "longer there; run the provider that built it again"
    )


def describe_removal(removal: PackRemoval) -> str:
    """What `pack uninstall` dropped from the store.

    A partial install is worded differently rather than as "0 files":
    nothing recorded what was in that directory, which is not the same
    claim as the directory having been empty.
    """
    if not removal.recorded:
        return "dropped; no state file recorded what was in it"
    return f"{count_of(removal.files, 'file')} dropped from the store"


# ---------------------------------------------------------------------------
# Converging a destination: `context sync`
# ---------------------------------------------------------------------------

# What each verdict says about one address. Two of them are skips and read
# entirely differently, which is why the report keeps verdicts rather than
# collapsing them into the stream's `SKIPPED`.
_VERDICT_WORDS: dict[Verdict, str] = {
    "write": "added",
    "rewrite": "updated",
    "adopt": "taken over",
    "delete": "removed: no pack declares it now",
    "keep": "unchanged",
    "edited": "you edited this: the pack's text is back, your edit a note of yours",
    "yours": "yours; a pack declares it and will not touch it",
}


def describe_action(action: Action, name: str | None = None) -> str:
    """One line about one address, for a front end that prints the
    address nowhere else on the line - the command line.

    `name` is what the reader knows the document by, where that is not
    the address: a corpus document's place, since its address is the
    pack's own (`c.md` inside its notes source).
    """
    return f"{name or action.address}: {describe_outcome_of(action)}"


def describe_outcome_of(action: Action) -> str:
    """What happened to one address, naming who it belongs to.

    The owner is named on the lines where it changed or is in question,
    and left out where it would be noise: "unchanged" does not need to
    repeat which pack shipped a file that nothing happened to.
    """
    word = _VERDICT_WORDS[action.verdict]
    if action.verdict in {"write", "rewrite"} and action.declaration is not None:
        return f"{word} by {action.declaration.pack_id}"
    if action.verdict == "adopt" and action.declaration is not None:
        previous = action.existing.owner if action.existing else "another pack"
        return f"{word} by {action.declaration.pack_id}, which was {previous}"
    return word


# A count's word in a sync's headline, in the order the headline gives
# them. The same words the lines use, so the headline and the list
# beneath it cannot disagree (Brian, 2026-10-12). `edited` and `yours`
# share one: both are left to the user, and the lines say why.
_COUNT_WORDS: tuple[tuple[tuple[Verdict, ...], str], ...] = (
    (("write",), "added"),
    (("rewrite",), "updated"),
    (("adopt",), "taken over"),
    (("delete",), "removed"),
    (("keep",), "unchanged"),
    (("edited",), "copied as yours"),
    (("yours",), "left as yours"),
)


def verdict_word(name: str) -> str:
    """A verdict's name, as an event quotes it, in a reader's words; a
    name kennis does not know is shown as it is rather than hidden."""
    for verdicts, word in _COUNT_WORDS:
        if name in verdicts:
            return word
    return name


def describe_sync(counts: dict[Verdict, int], *, noun: str = "file") -> str:
    """The one line above the detail: each kind of outcome, counted.

    In the lines' own words and a fixed order - `1 document added, 2
    unchanged` - so a destination where nothing moved does not read like
    one where everything did, and a file kennis declined to write is
    "left as yours", never counted with what was unchanged: saying so
    would report the protection as if it were agreement.

    Takes the counts rather than either sync's result, because the two
    destinations differ in what they hold and not at all in how the line
    reads - `noun` is the whole of the difference.
    """
    parts = [
        (count, word)
        for verdicts, word in _COUNT_WORDS
        if (count := sum(counts.get(verdict, 0) for verdict in verdicts))
    ]
    if not parts:
        return "nothing declared by any installed pack"
    (first, word), *rest = parts
    return ", ".join(
        [
            f"{count_of(first, noun)} {word}",
            *(f"{count} {word}" for count, word in rest),
        ]
    )


def describe_after_install() -> str:
    """What an install has not done yet, said once after one."""
    return (
        "its papers, documentation and notes arrive with a corpus sync, and "
        "a project reads its context once the project declares it"
    )


def describe_bundle_sync(removed: int, made_yours: int) -> str:
    """The line above a context sync's detail: what it changed, counted.

    A sync writes nothing new any more (14g), so a project whose bundle
    no earlier kennis copied into is told that nothing changed.
    """
    parts = [
        *(
            [f"{count_of(removed, 'copy', 'copies')} of a pack's file removed"]
            if removed
            else []
        ),
        *(
            [f"{count_of(made_yours, 'edited copy', 'edited copies')} made yours"]
            if made_yours
            else []
        ),
    ]
    return ", ".join(parts) if parts else "nothing to change"


def describe_made_yours() -> str:
    """Why a pack's file in the bundle is now the person's.

    Said once above the list, because every such file has the one cause:
    an earlier kennis copied it, the person edited it, and an edit is
    kept rather than replaced by the pack's text.
    """
    return (
        "an edited copy of a pack's file is yours now and replaces the "
        "pack's in this project's search"
    )


def describe_declared(declared: Sequence[str]) -> str:
    return f"this project uses {', '.join(declared)}"


def describe_not_installed(missing: Sequence[str]) -> str:
    """Packs a project declares that this machine has not got: its search
    leaves them out until they are added."""
    return f"declared but not installed here: {', '.join(missing)}"


def describe_no_declaration() -> str:
    return "this project declares no packs, so its search reads none"


def describe_kept_copies(count: int) -> str:
    """Why a pack's note was put back although the person had edited it:
    the edit is a note of theirs now (14g, #514)."""
    return (
        f"{count_of(count, 'note')} a pack owns had your edits; each edit is "
        "kept as a note of yours, and the pack's text is back"
    )


def describe_kept_copy(original: str, copy: str) -> str:
    return f"{original}: your edit is now {copy}"


def describe_sync_summary(counts: dict[Verdict, int]) -> str:
    """The one line a sync's commit carries into the corpus history.

    Verdicts rather than outcomes, and in a fixed order, so that two
    commits doing the same thing read the same way in `corpus history`.
    """
    named = [
        f"{count} {verdict}"
        # `edited` writes too: a note of the person's, and the pack's text
        # back (#514).
        for verdict in ("write", "rewrite", "adopt", "delete", "edited")
        if (count := counts.get(verdict, 0))
    ]
    return ", ".join(named) if named else "nothing to change"


def describe_unfetched(failed: tuple[str, ...]) -> str:
    """Declarations whose fetch did not succeed, named.

    Named rather than counted: which paper did not arrive is the whole
    of what a reader needs, and the identifier is what they would search
    for. Worded as a state rather than as an error, because the next run
    tries again - nothing was written, so nothing has to be undone.
    """
    return (
        f"{count_of(len(failed), 'declaration')} could not be fetched and "
        f"will be tried again: {joined(sorted(failed))}"
    )


def describe_why_unfetched(address: str, refusal: Refusal) -> str:
    """One paper a sync could not fetch, and what the add said about it -
    for a paper with no reachable copy, where to download one."""
    return f"{address}: {describe_add_refusal(refusal)}"


def describe_deferred(deferred: tuple[tuple[str, str], ...]) -> str:
    """Declarations that lost to an earlier-installed pack.

    Not an error: two providers may legitimately ship the same file. A
    provider whose content never appears has no other way to find out
    why, which is the reason this is said at all.
    """
    packs = joined(sorted({pack_id for _, pack_id in deferred}))
    return (
        f"{count_of(len(deferred), 'file')} declared by {packs} "
        "already belongs to a pack installed earlier"
    )


def describe_what_uninstall_cannot_reach() -> str:
    """The sentence `pack uninstall` closes with.

    Section 9 states the limit and says it must be stated: kennis keeps no
    registry of the projects a user has, so it cannot clean `.context/` in
    N checkouts, and a user running `remove` will reasonably expect the
    workspace content to be gone.
    """
    return (
        "nothing this pack supplied has been removed: the corpus keeps its "
        "documents until the next sync, and each project keeps its content "
        "until it is synchronised there"
    )


__all__ = [
    "describe_action",
    "describe_after_install",
    "describe_bundle_sync",
    "describe_copied",
    "describe_damage",
    "describe_declarations",
    "describe_declared",
    "describe_deferred",
    "describe_deleted",
    "describe_described",
    "describe_holdings",
    "describe_install",
    "describe_installed",
    "describe_kept_copies",
    "describe_kept_copy",
    "describe_lost_source",
    "describe_made_yours",
    "describe_no_declaration",
    "describe_not_installed",
    "describe_outcome_of",
    "describe_overlap",
    "describe_problem",
    "describe_recorded",
    "describe_refusal",
    "describe_removal",
    "describe_sync",
    "describe_sync_summary",
    "describe_undescribed",
    "describe_unfetched",
    "describe_unreadable",
    "describe_unselected",
    "describe_update_needed",
    "describe_verdict",
    "describe_what_uninstall_cannot_reach",
    "describe_when",
    "describe_why_unfetched",
    "verdict_word",
]
