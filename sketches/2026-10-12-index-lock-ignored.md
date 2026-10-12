# The index lock file is not history (#444)

Milestone / step: engine fixes logged during milestones 12 and 13 (#444)
Date: 2026-10-12

## What I am about to do

Keep `index/<collection>/.lock` out of the corpus repository. `corpus
init` writes the ignore line, and Brian's existing corpus gets the line
and an untracking by hand, as earlier `.gitignore` additions did.

## How I expect it to work

`history/repository.py::_GITIGNORE` gains `index/*/.lock` with a comment
saying what the file is. `locking.index_lock` creates the file the first
time a collection is built; `Repository.commit` stages with `git add
--all .`, which skips an ignored path that is not yet tracked. So a corpus
created after this change never tracks it, and nothing else has to know.

A corpus created before it already tracks the three files, and an ignore
rule does not untrack a tracked path. kennis writes no migrations
(CLAUDE.md, the `.gitignore` lines of v0.6a), so the remedy there is
`git rm --cached` on each, once, by hand. The pack store's
`_ensure_ignored` is the one exception and is not a precedent to copy:
it exists because an install would otherwise commit the whole store,
which is a cost, where three empty files are not.

The test builds an index through the command line, so `.lock` exists,
and asserts that `git ls-files` does not name it and that the
repository is clean while it exists.

## What I expect to be uncertain or difficult

- Whether `index_lock` leaves the file behind after release. filelock's
  `FileLock` on POSIX does not delete it; if it did, the test would pass
  for a file that is never there, which is #390's shape. The test must
  assert the file exists before asserting it is untracked.
- Whether `Repository.restore("index")` (the backup restore, #443)
  depended on the lock being in HEAD. It should not: `index_lock`
  creates the file when it needs it.

## What actually happened that I did not expect

- Nothing about the mechanism. The test failed for the stated reason
  (`index/notes/.lock` in `git ls-files`) before the line existed and
  passes after, so the fix's absence is the injection and it is caught.
- filelock leaves the file behind after release, so the `is_file`
  guard holds and the test is not #390's shape.
- Brian's corpus tracked three of them, `docs`, `literature` and
  `notes`. The line was appended there and `git rm --cached` run on
  each; the files stay on disk, now ignored, and the change is staged
  rather than committed, for the next kennis write to sweep in.
