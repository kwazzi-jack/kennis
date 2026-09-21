"""The corpus as a git repository: initialising it, and recording each change.

Git is a requirement rather than an option. Design section 19 argues that
case from index freshness: a corpus where history is optional needs a second
implementation of "what changed since the index was built" for the case where
git is absent, and two implementations of one question drift apart.

So `corpus init` either produces a working repository or produces nothing at
all - the binary is checked before any directory is created, because a
half-made corpus on a machine without git is worse than a clear refusal.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.errors import CorpusBusy, CorpusNotFound
from kennis.engine.history.git import git, git_binary

_GITATTRIBUTES: Final = """\
# The index is generated, binary, and rebuilt wholesale. Git must not try to
# diff or merge it as text: doing so is slow, produces nothing a person can
# read, and can write conflict markers into the middle of a numpy array.
*.npy binary
*.jsonl -diff
index/** -diff
"""

_README: Final = """\
# kennis corpus

This directory is a kennis corpus: documents, their metadata, and the search
index built from them. It is a git repository so that every change kennis
makes is recorded and reversible.

## What is in here

Converted third-party text. Papers, documentation pages and web pages are
fetched and converted to markdown for local search, and the result is stored
here alongside the bibliographic metadata identifying where each came from.
**The copyright in that text belongs to whoever wrote it**, not to you and not
to kennis.

## kennis will never create a remote

Nothing in kennis pushes, and nothing configures a remote. That is deliberate,
because the contents above are not yours to publish. If you add a remote
yourself, you are choosing to redistribute third-party text, and the licence
terms of every document in here become your problem.

Backup and transfer without a remote is what `git bundle` is for.
"""


@dataclass(frozen=True, slots=True)
class Repository:
    """A corpus's git repository."""

    root: Path

    def head(self) -> str | None:
        """The commit the corpus is at, or None if it has no commits yet."""
        self._require_repository()
        result = git(["rev-parse", "HEAD"], cwd=self.root)
        return result.stdout.strip() if result.ok else None

    def is_clean(self) -> bool:
        """Whether the working tree matches the last commit.

        Untracked files count as unclean: a file someone dropped into the
        corpus is a change kennis has not recorded, which is exactly what
        out-of-band detection needs to see.
        """
        self._require_repository()
        return not git(["status", "--porcelain"], cwd=self.root).lines()

    def commit(self, operation: str, *, scope: str, summary: str) -> str | None:
        """Record everything in the working tree as one commit.

        Returns the new commit, or **None when there was nothing to record**.
        Re-adding a document that was already there changes no file, and
        neither available alternative is right: an empty commit fills history
        with noise, and raising fails a command that succeeded.

        The message is structured because something parses it later - `corpus
        history` - and because a person reading `git log` in their corpus
        should see what kennis did rather than "update".
        """
        self._require_repository()
        staged = git(["add", "--all", "."], cwd=self.root)
        if not staged.ok:
            raise CorpusBusy(
                f"the corpus at {self.root} could not be staged: "
                f"{staged.stderr.strip()}"
            )
        if not git(["diff", "--cached", "--name-only"], cwd=self.root).lines():
            return None

        message = f"{operation}({scope}): {summary}"
        recorded = git(["commit", "-m", message], cwd=self.root)
        if not recorded.ok:
            raise CorpusBusy(
                f"the corpus at {self.root} could not be committed: "
                f"{recorded.stderr.strip() or recorded.stdout.strip()}"
            )
        return self.head()

    def _require_repository(self) -> None:
        if not (self.root / ".git").is_dir():
            raise CorpusNotFound(
                f"{self.root} is not a kennis corpus",
                resolution=f"kennis corpus init {self.root}",
            )


def initialise_corpus(root: Path) -> Repository:
    """Create a corpus at `root` and record its scaffolding as one commit.

    **The git binary is located before anything is written.** The plan asks
    that a machine without git fails here with a clear message and no
    partially initialised state, and the only way to promise that is to find
    out first.
    """
    git_binary()
    if (root / ".git").exists():
        raise CorpusBusy(
            f"{root} is already a kennis corpus",
            resolution="kennis corpus status",
        )

    root.mkdir(parents=True, exist_ok=True)
    for name in COLLECTION_NAMES:
        (root / name).mkdir(exist_ok=True)

    started = git(["init"], cwd=root)
    if not started.ok:
        raise CorpusBusy(
            f"git could not initialise a repository at {root}: {started.stderr.strip()}"
        )

    (root / ".gitattributes").write_text(_GITATTRIBUTES, encoding="utf-8")
    (root / "README.md").write_text(_README, encoding="utf-8")
    # An empty collection directory is invisible to git, so the corpus would
    # commit with no collections in it and `corpus status` on a fresh clone
    # would find nothing. A `.gitkeep` is the conventional answer and says
    # what it is.
    for name in COLLECTION_NAMES:
        (root / name / ".gitkeep").write_text("", encoding="utf-8")

    repository = Repository(root)
    # Committed rather than left in the working tree: a repository with no
    # commits makes every later `git diff <commit>` a special case, and the
    # index records the commit it was built from.
    repository.commit("init", scope="corpus", summary="create the corpus")
    return repository
