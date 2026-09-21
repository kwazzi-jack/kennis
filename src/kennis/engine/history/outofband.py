"""Changes someone made to the corpus without going through kennis.

The corpus is a directory of real files, so someone will eventually edit,
delete or drop one in by hand. Git makes every such change visible - the
working tree against the last kennis commit is the whole detection mechanism
- and design section 19 gives five rules for what to do about each.

The governing principle is one sentence: **kennis never loses data, and every
out-of-band change is reported alongside the command that would have done it
properly.** Three consequences of that are worth stating here, because each
looks wrong until the alternative is considered.

**An edit is never auto-reverted.** Reverting is a resolution the user may
choose, not the action kennis takes on noticing. Silently discarding
someone's edit does not become acceptable because git could undo it
afterwards.

**A deletion is restored rather than honoured, whoever owned it.** An
out-of-band delete carries no record of intent, and treating an accident as
an instruction is the more expensive mistake. Restoring costs an annoying
extra command; honouring costs a document.

**A hand-created file is reported and left alone.** Guessing metadata for it
would invent exactly the identity the rest of the design refuses to invent,
and deleting it would be losing data to enforce tidiness.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from typing import Final, Literal

import yaml

from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.frontmatter import split_frontmatter
from kennis.engine.history.repository import Repository

type ChangeKind = Literal["edited", "deleted", "created"]

_PLACEHOLDER: Final = ".gitkeep"


@dataclass(frozen=True, slots=True)
class OutOfBandChange:
    """One change kennis did not make, and what it did about it.

    **Facts only.** What to *say* about a change belongs to `kennis.render`,
    which both front ends share. A sentence built here would be the thing a
    front end reaches for, because it would be the easiest thing to reach
    for, and then the command line could not put the path in its own theme
    role, wrap it for a narrow terminal, or collapse three restorations into
    one line - it would hold three finished sentences rather than nine facts.
    """

    path: str
    kind: ChangeKind
    # None when the file has no readable frontmatter: a hand-created file, or
    # a document whose YAML will not parse. Unknown rather than assumed.
    owner: str | None
    document_id: str | None
    restored: bool = False


def detect_changes(repository: Repository) -> list[OutOfBandChange]:
    """Every change to the corpus that kennis did not make.

    Across all collections rather than one. An index is per collection; a
    lost document is not, and a user who deleted something wants to hear
    about it whichever collection it was in.
    """
    head = repository.head()
    changes: list[OutOfBandChange] = []
    for collection in COLLECTION_NAMES:
        for status, path in repository.status_names(scope=f"{collection}/"):
            if PurePosixPath(path).name == _PLACEHOLDER:
                continue
            changes.append(_change_for(repository, head, status, path))
    return changes


def restore_deletions(
    repository: Repository, changes: list[OutOfBandChange]
) -> list[OutOfBandChange]:
    """Put back everything that was deleted, and report what was put back.

    Only deletions. An edit is left exactly as the user left it, and a
    created file is left on disk.
    """
    restored: list[OutOfBandChange] = []
    for change in changes:
        if change.kind != "deleted":
            continue
        if repository.restore(change.path):
            restored.append(replace(change, restored=True))
        else:
            restored.append(change)
    return restored


def _change_for(
    repository: Repository, head: str | None, status: str, path: str
) -> OutOfBandChange:
    if status == "A":
        return OutOfBandChange(path=path, kind="created", owner=None, document_id=None)
    if status == "D":
        # The file is gone, so the last commit is the only place its
        # frontmatter still exists - and the rules key on `owner`.
        owner, identifier = _identity_in_history(repository, head, path)
        return OutOfBandChange(
            path=path, kind="deleted", owner=owner, document_id=identifier
        )
    owner, identifier = _identity_on_disk(repository, path)
    return OutOfBandChange(
        path=path, kind="edited", owner=owner, document_id=identifier
    )


def _identity_on_disk(
    repository: Repository, path: str
) -> tuple[str | None, str | None]:
    try:
        text = (repository.root / path).read_text(encoding="utf-8")
    except OSError:
        return None, None
    return _identity_in(text)


def _identity_in_history(
    repository: Repository, head: str | None, path: str
) -> tuple[str | None, str | None]:
    """The owner and identifier a deleted document had.

    The file is gone, so the last commit is the only place its frontmatter
    still exists.
    """
    if head is None:
        return None, None
    text = repository.show(head, path)
    return _identity_in(text) if text is not None else (None, None)


def _identity_in(text: str) -> tuple[str | None, str | None]:
    """The `owner` and `id` a document states, as far as they can be read.

    **Never raises.** The point of noticing a change is to say what was
    affected, so a document whose YAML will not parse is reported with an
    unknown owner rather than costing the whole report.
    """
    try:
        frontmatter, _ = split_frontmatter(text)
    except (ValueError, yaml.YAMLError):
        # `split_frontmatter` returns an empty mapping for a document with no
        # frontmatter, and raises only when the YAML inside one will not
        # parse - which is a document worth reporting as lost, with its owner
        # unknown rather than assumed.
        return None, None
    owner = frontmatter.get("owner")
    identifier = frontmatter.get("id")
    return (
        owner if isinstance(owner, str) else None,
        identifier if isinstance(identifier, str) else None,
    )
