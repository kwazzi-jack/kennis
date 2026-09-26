"""Wording for the pack commands.

The engine returns a `PackProblem` carrying a kind and the fields that kind
needs; the sentence lives here, because a front end that was handed the
sentence could not rewrap it, group it, or say it differently. Concern #81.
"""

from __future__ import annotations

from kennis.engine.corpus.document import Document
from kennis.engine.corpus.schema import pack_id_of
from kennis.engine.pack.installed import InstalledPack, Overlap, PackRemoval
from kennis.engine.pack.resolve import ACTING, Action, Verdict
from kennis.engine.pack.store import PackInstall
from kennis.engine.pack.update import PackUpdate
from kennis.engine.pack.validate import PackProblem, PackReport, VersionRefusal
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
# Reading the store: `pack list`, `pack status`, `pack remove`
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
    """What `pack remove` dropped from the store.

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
    "edited": "you edited this, so it has been left as it is",
    "yours": "yours; a pack declares it and will not touch it",
}


def describe_action(action: Action) -> str:
    """One line about one address, naming who it belongs to.

    The owner is named on the lines where it changed or is in question,
    and left out where it would be noise: "unchanged" does not need to
    repeat which pack shipped a file that nothing happened to.
    """
    word = _VERDICT_WORDS[action.verdict]
    if action.verdict in {"write", "rewrite"} and action.declaration is not None:
        return f"{action.address}: {word} by {action.declaration.pack_id}"
    if action.verdict == "adopt" and action.declaration is not None:
        previous = action.existing.owner if action.existing else "another pack"
        return (
            f"{action.address}: {word} by {action.declaration.pack_id}, "
            f"which was {previous}"
        )
    return f"{action.address}: {word}"


def describe_sync(counts: dict[Verdict, int], *, noun: str = "file") -> str:
    """The one line above the detail, counting what actually happened.

    Counts the verdicts that changed something and says so, rather than
    counting every address looked at: a destination where nothing moved
    should not report the same number as one where everything did.

    Takes the counts rather than either sync's result, because the two
    destinations differ in what they hold and not at all in how the line
    reads - `noun` is the whole of the difference.
    """
    changed = sum(count for verdict, count in counts.items() if verdict in ACTING)
    looked = sum(counts.values())
    if not looked:
        return "nothing declared by any installed pack"
    if changed:
        return f"{count_of(changed, noun)} changed, of {looked}"
    held = counts.get("edited", 0) + counts.get("yours", 0)
    if held:
        # Not "already in step": something kennis declined to write is
        # precisely something that is *not* in step, and saying otherwise
        # would report the protection as if it were agreement.
        if looked == held:
            return f"{count_of(held, noun)} left as yours"
        return f"{count_of(looked - held, noun)} in step, {held} left as yours"
    return f"{count_of(looked, noun)} already in step"


def describe_claim_needed(count: int) -> str:
    """Why an edited file was left alone, said once above the list.

    Every edited file has the same cause and the same two answers - keep
    the edit and take the file, or discard it and let the pack own it
    again - so saying it once is better than repeating it per line.
    """
    return (
        f"{count_of(count, 'file')} kennis would have written carries your "
        "own edits, so none of them was changed; set `owner: user` in a "
        "file to keep it and stop it being reported"
    )


def describe_corpus_claim_needed(count: int) -> str:
    """Why an edited corpus document was left alone.

    Names `kennis corpus claim`, which the bundle's wording cannot: a
    corpus document is addressed by an identifier and a command is the
    only handle on it, where a bundle file is open in the user's editor
    and one line of its frontmatter is the whole transfer. Section 5
    step 4a names this command for exactly this case.
    """
    return (
        f"{count_of(count, 'document')} kennis would have written carries "
        "your own edits, so none of them was changed"
    )


def describe_owner(document: Document) -> str:
    """Who may overwrite or delete this document, after a transfer."""
    pack_id = pack_id_of(document.frontmatter.owner)
    if pack_id is None:
        return "yours now; no sync will rewrite it or remove it"
    return f"{pack_id}'s again; the next sync may rewrite it or remove it"


def describe_sync_summary(counts: dict[Verdict, int]) -> str:
    """The one line a sync's commit carries into the corpus history.

    Verdicts rather than outcomes, and in a fixed order, so that two
    commits doing the same thing read the same way in `corpus history`.
    """
    named = [
        f"{count} {verdict}"
        for verdict in ("write", "rewrite", "adopt", "delete")
        if (count := counts.get(verdict, 0))
    ]
    return ", ".join(named) if named else "nothing to change"


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


def describe_what_remove_cannot_reach() -> str:
    """The sentence `pack remove` closes with.

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
    "describe_claim_needed",
    "describe_corpus_claim_needed",
    "describe_damage",
    "describe_declarations",
    "describe_deferred",
    "describe_install",
    "describe_installed",
    "describe_lost_source",
    "describe_overlap",
    "describe_owner",
    "describe_problem",
    "describe_recorded",
    "describe_refusal",
    "describe_removal",
    "describe_sync",
    "describe_sync_summary",
    "describe_unreadable",
    "describe_unselected",
    "describe_update_needed",
    "describe_verdict",
    "describe_what_remove_cannot_reach",
    "describe_when",
]
