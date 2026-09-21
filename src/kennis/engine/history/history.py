"""Reading what kennis did, and putting a document back as it was.

The commit messages were given a structure in step 1 - `add(notes): 3 added`
rather than "update" - precisely so this step could read them back. This is
where that pays.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Final

import yaml

from kennis.engine.errors import DocumentNotFound
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
class RestoredDocument:
    """What a restore put back, and where it came from."""

    document_id: str
    path: str
    commit: str


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
