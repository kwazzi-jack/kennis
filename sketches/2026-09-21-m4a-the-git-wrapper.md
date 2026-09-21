# Milestone 4, step 1: the git wrapper and an initialised corpus

Milestone / step: `design/plan.md`, "Milestone 4", items 1, 2 and 3.
Date: 2026-09-21

Previous sketch: `2026-09-21-m3e-search.md`, which finished milestone 3.
What it left: documents can be added, indexed and searched, and nothing is
recorded about how the corpus got that way.

## What I am about to do

**This milestone is new code, not a port.** boepie has no git at all, so
unlike milestone 3 there is nothing to read for prior art and nothing to
check the plan's description against. That cuts both ways: no inherited
defects, and no inherited debugging either.

Milestone 4 has six items and splits the way 2 and 3 did:

| step | what | why it is its own step |
|---|---|---|
| 1 (this) | the git wrapper, `corpus init`, commit after mutation | everything else needs a repository to exist |
| 2 | index freshness from the `built_from` commit | needs commits to diff between |
| 3 | out-of-band change detection, the five rules | needs freshness and `git status` |
| 4 | `corpus history` and `corpus restore` | reads and rewinds what the rest wrote |

## How I expect it to work

### The tree this adds

```
src/kennis/engine/history/
  __init__.py
  git.py        # the binary, run under the external-process discipline
  repository.py # what a corpus repository is: init, commit, status
```

`history/` sits beside `corpus/` and `rag/` rather than inside `corpus/`,
because the context bundle and the pack store are both plausible future
callers and none of this knows what a document is.

### Running git at all

Every call goes through one function, subject to the discipline CLAUDE.md
states and `converters.py` already follows: **a timeout on every call, `stdin`
closed, `check=False`, and the failure returned rather than raised where the
caller can act on it.**

`stdin=subprocess.DEVNULL` is not decoration here. Git will block on a
terminal prompt for credentials or an editor, and a kennis command that hangs
with no output is the worst failure mode available. With stdin closed it
fails instead, which is something a caller can report.

Two more decisions that belong in one place rather than at every call site:

- **A fixed environment.** `GIT_TERMINAL_PROMPT=0`, no pager, and the
  author identity forced, so a machine with no `user.email` configured does
  not fail on the first commit. A corpus commit is kennis's, not the user's
  hand-written one, and inheriting a global identity would attribute machine
  actions to a person.
- **`-c core.hooksPath=/dev/null` or equivalent.** A user's global hooks
  firing inside a corpus commit is a class of surprise kennis cannot debug.
  I want to check whether this is worth the obscurity.

The result type is a small value - exit status, stdout, stderr - and
`GitUnavailable` is raised only when the binary itself is missing, which is
checked once rather than inferred from a failure.

### `corpus init`

Creates the corpus root and the three collection directories, runs `git
init`, and writes two files that are part of the corpus rather than
incidental to it:

- **`.gitattributes`** marking the index files binary. Without it git tries
  to diff `embeddings.npy` and `chunks.jsonl` as text, which is slow, useless
  and produces conflict markers inside a numpy array.
- **`README.md`** stating what the corpus contains - converted third-party
  text - and that kennis will never create a remote. The plan asks for this
  specifically, and the reason is that a directory full of paper text with no
  statement of provenance is exactly the thing that gets pushed to a public
  forge by accident.

**No partially initialised state on failure.** If git is missing, the
directory must not be left half-made: the plan's first test says so. So the
binary is checked before anything is written.

### A commit after each mutating command

`commit(operation, counts)` writes a structured message:

```
add(literature): 3 added, 1 unchanged
```

The shape matters because something will parse it later - `corpus history`
is step 4 of this milestone - and because a human reading `git log` in the
corpus should see what kennis did, not "update".

Two things I want to get right now rather than retrofit:

- **A commit with nothing staged is not an error and not an empty commit.**
  Re-adding a document that was already there changes no file, and both
  `--allow-empty` and a raised error are wrong: the first fills history with
  noise, the second fails a command that succeeded.
- **The commit is the last step of the operation**, after the files are
  written and the report is built, so an interrupted command leaves an
  uncommitted working tree rather than a commit describing work that did not
  finish.

## What I expect to be uncertain or difficult

- **Testing without a git binary.** The plan's first test requires the
  absent-git case. Injecting the path to the binary is the obvious seam, but
  it has to be a seam the production path really uses, not one that exists
  only for tests.
- **`git init` default branch name.** Git warns about `init.defaultBranch`
  on some versions, and under `filterwarnings = ["error"]` that is stderr
  rather than a Python warning, so it will not fail tests - it will just make
  every call's stderr non-empty, which a naive failure check would misread.
- **Whether the author identity should be configurable.** Forcing it is right
  for machine commits; a user who wants their own name on them has a
  reasonable case. I do not want to invent a setting before settings exist.
- **Empty-commit detection.** `git commit` exits non-zero when there is
  nothing staged, and distinguishing that from a real failure means reading
  the message or checking `git status` first. The second is a second call and
  is clearer.
- **Whether `corpus init` should commit its own scaffolding.** A repository
  whose first commit is the README and `.gitattributes` has a base to diff
  against; one with no commits at all makes every later `git diff <sha>`
  a special case.

## What actually happened that I did not expect

**A timeout test that could not have timed out, and it failed rather than
passing quietly.** I wrote `git hash-object --stdin-paths` with a
one-millisecond timeout, expecting it to hang. With stdin closed - which this
module guarantees - it reaches end-of-file and exits at once, so the test
failed on the first run. That is the good case: the third hollow test in this
project (#63, #67, and now #71) and the first found by its own failure rather
than by injecting a defect. The replacement provokes the timeout rather than
waiting for one, because what is under test is kennis's handling of an
expired call, not whether some git command is slow.

**Empty directories do not survive a commit, and my own test hid it.** The
test asserting that init creates three collections passed against the
filesystem while the commit contained none of them, because git tracks files
rather than directories. A corpus restored from history or moved by `git
bundle` would have arrived without its collections. A `.gitkeep` each.
Concern #73.

**Forcing the author identity turned out to be load-bearing rather than
tidy.** I wrote it down as a principle - machine commits should not carry a
person's name - and then found the practical half while testing: a machine
that has never configured `user.email` fails on its very first commit, which
is `corpus init`. So the principled choice and the working one coincide,
which is not something I would have predicted from the principle alone.

**Nothing about `init.defaultBranch` mattered.** I had flagged git's warning
about it as a risk, on the grounds that non-empty stderr could be misread as
failure. It does warn, and nothing reads stderr on success, so it never
surfaced. The prediction was right about the behaviour and wrong about
whether it was a problem.

**The hooks question answered itself in a smaller form than I expected.** I
had wondered whether `core.hooksPath=/dev/null` was worth the obscurity.
`GIT_CONFIG_NOSYSTEM=1` covers the system-level case with a documented
variable and no argument at every call site, which is enough for the failure I
was actually worried about.

**I still do not know whether the author identity should be configurable.**
Listed as uncertain in the sketch, and it stays uncertain: forcing it is
right for machine commits, and a user wanting their own name on them has a
reasonable case. Deciding now would mean inventing a setting before settings
exist, so it waits.
