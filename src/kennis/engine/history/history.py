"""Reading what kennis did, and putting a document back as it was.

The commit messages were given a structure in step 1 - `add(notes): 3 added`
rather than "update" - precisely so this step could read them back. This is
where that pays.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final

import yaml

from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.errors import DocumentNotFound, HistoryUnwritable, InputError
from kennis.engine.events import Outcome
from kennis.engine.frontmatter import split_frontmatter
from kennis.engine.history.git import git
from kennis.engine.history.repository import Repository

# `operation(scope): summary`, the shape `Repository.commit` writes.
_SUBJECT: Final = re.compile(
    r"^(?P<operation>[a-z]+)\((?P<scope>[^)]+)\): (?P<summary>.+)$"
)

# A unit separator, because a commit subject may contain anything a person
# typed - including tabs and pipes, which is why this is not either of those.
_SEPARATOR: Final = "\x1f"

_DEFAULT_LIMIT: Final = 50

# How far back to look for a document that is no longer in the corpus. A
# deleted document's path cannot be found by walking the corpus, so history
# is searched instead, and this bounds that search.
_SEARCH_DEPTH: Final = 200


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    """One commit, as kennis recorded it.

    `operation`, `scope` and `summary` come from the structured message.
    **A subject that does not parse is kept**, with `operation` and `scope`
    None and the whole subject as the summary: a corpus may contain a commit
    a person made by hand, and a history view that silently omits what it
    cannot categorise invents a history in which that did not happen.
    """

    commit: str
    when: datetime
    operation: str | None
    scope: str | None
    summary: str


@dataclass(frozen=True, slots=True)
class HeldDocument:
    """A document named by what a reader recognises: its identifier and
    title, and where it is (or was), relative to the corpus."""

    document_id: str
    title: str
    path: str


@dataclass(frozen=True, slots=True)
class ReturnChanges:
    """What returning the corpus to a point would do, said before it is done.

    `added` are documents the point held and the corpus does not: the
    return puts them back. `removed` are documents held now that the point
    did not hold. `changed` are held at both and differ.
    """

    commit: str
    added: tuple[HeldDocument, ...]
    removed: tuple[HeldDocument, ...]
    changed: tuple[HeldDocument, ...]

    @property
    def nothing(self) -> bool:
        return not (self.added or self.removed or self.changed)


@dataclass(frozen=True, slots=True)
class RestoredDocument:
    """What a restore put back, and where it came from."""

    document_id: str
    path: str
    commit: str


def commit_summary(counts: Mapping[str, int]) -> str:
    """The summary half of a commit subject: `2 added, 1 unchanged`.

    **This is composed in the engine and that is deliberate**, against the
    general rule that the engine names and `render/` phrases. `_SUBJECT`
    above parses these strings back, so the writer and the reader are two
    halves of one storage format rather than one of them being wording. Two
    front ends that phrased it differently would give a corpus a history that
    parses differently depending on which one touched it.

    Counts of zero are left out, and the rest keep the order they were given
    in. An empty tally yields "nothing", which `Repository.commit` will in
    practice never write: a run that did nothing leaves a clean tree and
    records no commit at all.
    """
    parts = [f"{count} {name}" for name, count in counts.items() if count]
    return ", ".join(parts) if parts else "nothing"


def outcome_summary(counts: Mapping[Outcome, int]) -> str:
    """`commit_summary` over an operation's outcome tally.

    Walked in the order the enum declares rather than the order the tally was
    built in, so the same result always yields the same subject however the
    identifiers happened to be ordered on the command line.
    """
    return commit_summary(
        {outcome.value: counts.get(outcome, 0) for outcome in Outcome}
    )


def read_history(
    repository: Repository,
    *,
    collection: str | None = None,
    limit: int = _DEFAULT_LIMIT,
) -> list[HistoryEntry]:
    """What kennis did, newest first.

    `collection` filters by the paths a commit touched, which is git deciding
    rather than kennis inferring it from the scope in the message. Those can
    differ - one commit can touch two collections - and git's answer is the
    true one.
    """
    arguments = [
        "log",
        f"--max-count={limit}",
        f"--format=%H{_SEPARATOR}%aI{_SEPARATOR}%s",
    ]
    if collection is not None:
        arguments += ["--", f"{collection}/"]

    entries: list[HistoryEntry] = []
    for line in git(arguments, cwd=repository.root).lines():
        fields = line.split(_SEPARATOR)
        if len(fields) != 3:
            continue
        commit, when, subject = fields
        matched = _SUBJECT.match(subject)
        entries.append(
            HistoryEntry(
                commit=commit,
                when=datetime.fromisoformat(when),
                operation=matched["operation"] if matched else None,
                scope=matched["scope"] if matched else None,
                summary=matched["summary"] if matched else subject,
            )
        )
    return entries


def restore_document(
    repository: Repository, document_id: str, *, commit: str
) -> RestoredDocument:
    """Put the document with `document_id` back as it was at `commit`.

    The identifier is resolved against **that commit's tree** rather than
    against the corpus on disk, because the document being restored is often
    one that is no longer there - which is the case a restore exists for.
    """
    path = _path_at(repository, commit, document_id)
    if path is None:
        raise DocumentNotFound(
            f"no document with identifier '{document_id}' existed at {commit[:12]}",
            resolution="kennis corpus history",
        )
    if not repository.restore(path, commit=commit):
        raise DocumentNotFound(
            f"'{path}' could not be restored from {commit[:12]}",
            resolution="kennis corpus history",
        )
    return RestoredDocument(document_id=document_id, path=path, commit=commit)


def _path_at(repository: Repository, commit: str, document_id: str) -> str | None:
    """The path of the document carrying `document_id`, as of `commit`.

    Read from the tree rather than searched for with `git log -S`: the latter
    finds commits where an identifier's occurrence count *changed*, which is
    close to but not the same question, and gives the wrong answer for a
    document whose identifier appears in a commit that only moved it.
    """
    listing = git(["ls-tree", "-r", "--name-only", commit], cwd=repository.root).lines()
    for path in listing[:_SEARCH_DEPTH] if len(listing) > _SEARCH_DEPTH else listing:
        if not path.endswith(".md"):
            continue
        content = repository.show(commit, path)
        if content is None:
            continue
        if _states_identifier(content, document_id):
            return path
    return None


def _states_identifier(content: str, document_id: str) -> bool:
    """Whether a document's frontmatter states this identifier.

    Read from the frontmatter rather than looked for anywhere in the text, so
    a document that merely *mentions* another's identifier - a note about a
    paper, say - is not mistaken for it.
    """
    try:
        frontmatter, _ = split_frontmatter(content)
    except (ValueError, yaml.YAMLError):
        return False
    return frontmatter.get("id") == document_id


def point_in_history(repository: Repository, commit: str) -> str:
    """The full commit `commit` names, or `InputError` naming the command
    that lists the points there are."""
    result = git(
        ["rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}"],
        cwd=repository.root,
    )
    if not result.ok or not result.stdout.strip():
        raise InputError(
            f"'{commit}' is not a point in this corpus's history",
            resolution="kennis corpus history",
        )
    return result.stdout.strip()


def what_a_return_changes(repository: Repository, commit: str) -> ReturnChanges:
    """What `return_to(commit)` would add, remove and change, by document.

    Against the working tree rather than the last commit, because a
    return replaces what is on disk, recorded or not; a file never
    recorded is counted as held now. Documents only: an asset or a docs
    project's `.current` goes with its document and is not counted.
    """
    point = point_in_history(repository, commit)
    records = git(
        ["diff", "--name-status", "-z", "--no-renames", point, "--", *COLLECTION_NAMES],
        cwd=repository.root,
    ).records()
    added: list[HeldDocument] = []
    removed: list[HeldDocument] = []
    changed: list[HeldDocument] = []
    for status, path in zip(records[::2], records[1::2], strict=False):
        if not path.endswith(".md"):
            continue
        if status == "D":
            # Gone from disk since the point: the return puts it back.
            added.append(_held_at(repository, point, path))
        elif status == "A":
            removed.append(_held_on_disk(repository, path))
        else:
            changed.append(_held_on_disk(repository, path))
    untracked = git(
        ["ls-files", "--others", "--exclude-standard", "-z", "--", *COLLECTION_NAMES],
        cwd=repository.root,
    ).records()
    removed.extend(
        _held_on_disk(repository, path) for path in untracked if path.endswith(".md")
    )
    return ReturnChanges(
        commit=point,
        added=tuple(added),
        removed=tuple(removed),
        changed=tuple(changed),
    )


def return_to(repository: Repository, commit: str) -> None:
    """Make the three collections exactly as they were at `commit`.

    Changed files back, files added since removed, files removed since
    back. **Nothing else**: `index/` holds only each index's pointer,
    which can name a build that no longer exists, so it is left as built
    and its freshness says what the return changed. The caller records
    the working tree first and commits after; this only rewrites it.
    """
    point = point_in_history(repository, commit)
    # `corpus init` records each collection's folder, so every point holds
    # all three; a pathspec naming one a hand-made corpus lacks is skipped
    # rather than refused by git.
    present = _present_collections(repository, point)
    if not present:
        return
    result = git(
        ["restore", f"--source={point}", "--staged", "--worktree", "--", *present],
        cwd=repository.root,
    )
    if not result.ok:
        raise HistoryUnwritable(
            f"the corpus could not be returned to {point[:8]}: {result.stderr.strip()}",
            resolution=f"git -C {repository.root} status",
        )


def removed_in(repository: Repository, commit: str) -> list[HeldDocument]:
    """The documents `commit` removed: held by its parent, not by it.

    What the window's history offers to put back, each by the identifier
    `restore_document` takes, read from the parent's tree.
    """
    point = point_in_history(repository, commit)
    parent = git(
        ["rev-parse", "--verify", "--quiet", f"{point}^"], cwd=repository.root
    ).stdout.strip()
    if not parent:
        return []
    records = git(
        [
            "diff",
            "--name-status",
            "-z",
            "--no-renames",
            "--diff-filter=D",
            parent,
            point,
            "--",
            *COLLECTION_NAMES,
        ],
        cwd=repository.root,
    ).records()
    return [
        _held_at(repository, parent, path)
        for path in records[1::2]
        if path.endswith(".md")
    ]


def _present_collections(repository: Repository, commit: str) -> list[str]:
    """The collections `commit`'s tree holds; a pathspec naming one it does
    not is an error to `git restore`."""
    listing = git(["ls-tree", "--name-only", commit], cwd=repository.root).lines()
    return [name for name in COLLECTION_NAMES if name in listing]


def _held_at(repository: Repository, commit: str, path: str) -> HeldDocument:
    return _held_from(repository.show(commit, path) or "", path)


def _held_on_disk(repository: Repository, path: str) -> HeldDocument:
    try:
        text = (repository.root / path).read_text(encoding="utf-8")
    except OSError:
        text = ""
    return _held_from(text, path)


def _held_from(content: str, path: str) -> HeldDocument:
    """Identifier and title from a document's frontmatter, or its filename
    when it has none kennis can read - a file someone dropped in by hand."""
    try:
        frontmatter, _ = split_frontmatter(content)
    except (ValueError, yaml.YAMLError):
        frontmatter = {}
    stem = path.rsplit("/", 1)[-1].removesuffix(".md")
    return HeldDocument(
        document_id=str(frontmatter.get("id") or ""),
        title=str(frontmatter.get("title") or stem),
        path=path,
    )
