# Milestone 5, out of band: git quotes a path and kennis did not unquote it

Milestone / step: a defect found while auditing the git layer, not a plan item.
Date: 2026-09-22

Previous sketch: `2026-09-22-m5g-config-and-setup.md`.

## What I am about to do

Make `Repository.status_names` and `Repository.diff_names` read paths that
git has not mangled, by asking git not to mangle them.

Brian asked whether the git testing was thorough. Auditing it found 82 tests
across five files and one thing none of them does: use a path that is not
ASCII. Git quotes such a path in its porcelain output, and kennis strips the
quotes without decoding what is inside them.

    $ git status --porcelain -- notes
    ?? "notes/G\303\266ttingen notes.md"

kennis reads that as the literal string `notes/G\303\266ttingen notes.md`,
which names no file. The consequence, reproduced:

    ~ notes/M\303\274ller 2020.md was deleted outside kennis
      and could not be restored

**A document whose title is not ASCII cannot be restored after an
out-of-band deletion.** For a corpus of papers this is not exotic: it is
every author called Mueller, Goncalves or Schrodinger spelled correctly.

## How I expect it to work

`-z` on both commands. Git emits NUL-terminated records and never quotes,
because NUL is the one byte a path cannot contain.

`GitResult` grows `records()` beside `lines()`, splitting stdout on NUL and
dropping the empty tail. The two commands then differ in shape and the
parsers have to differ with them:

| command | record shape |
|---|---|
| `status --porcelain -z` | `XY <path>` per record; a rename adds a *second* record holding the old path, **new first, then old** |
| `diff --name-status -z` | `<status>` and `<path>` are separate records; `R`/`C` is `<status>`, `<old>`, `<new>` |

So `status` is one record per entry with the status inside it, and `diff` is
two records per entry. That asymmetry is git's, not a choice.

The ` -> ` parsing in `status_names` goes away: it exists only because the
non-`-z` form joins a rename into one line. Under `-z` there is no arrow to
find, and a path containing the literal characters ` -> ` stops being a
misparse waiting to happen.

## What I expect to be uncertain or difficult

- **Whether the rename order is what I think.** The `-z` status format puts
  the new path first and the old second, which is the opposite of the
  displayed `old -> new`. I believe this but have not proved it, and getting
  it backwards would report a rename as a deletion of the wrong file. It
  gets its own test against a real rename rather than a fixture.
- **Whether `lines()` has other callers that also want `records()`.**
  `show` and `head` read single values, `is_clean` reads emptiness. I expect
  only these two to change.
- **Undecodable bytes.** A filename need not be valid UTF-8. `subprocess`
  with `text=True` decodes with the locale's encoding and would raise or
  replace. `-z` does not solve that; it solves quoting. Recording it rather
  than fixing it, because a corpus whose filenames kennis itself wrote is
  always valid UTF-8, and a hand-placed file with invalid bytes is a
  narrower case than the one being fixed.

## What actually happened that I did not expect

**The rename orders are opposite, and checking took one minute.** The sketch
flagged this as the risky part and it was the only prediction that paid.
`status --porcelain -z` emits `R  <new>` then `<old>`; `diff --name-status
-z` emits `R100`, `<old>`, `<new>`. Both were verified against a real rename
before either parser was written, which is why neither was written backwards.

**The quoting was the smaller of the two defects.** Fixing the path revealed
that the restore it fed never happened at all: `restore_deletions` was
implemented, tested eight ways and called by no command (#128). So the
original symptom - "deleted outside kennis and could not be restored" - was
two independent faults wearing one sentence, and the sentence was false in
both halves. It had not been tried, and the path it named did not exist.

**Worse than not restoring: `index` committed the deletion.** `_commit`
stages the scope, so the next write turned an accidental `rm` into history.
The auto-restore had to run *before* the operation inside the same lock,
which is now what `_undo_hand_deletions` says in its docstring, because
running it afterwards passes every test that checks the file is back and
still commits a tree that had the file missing.

**A third thing was unwired.** `remedies_for` was exported, tested and
printed by nothing, so every out-of-band change arrived without the command
the design says must accompany it. Wiring it then showed that one of those
commands does not work: `corpus add` on a path inside the corpus copies the
file rather than adopting it, leaving `dropped.md` inert and `dropped (2).md`
beside it (#129). Rule 4.4 was written this morning and caught its fourth
case by lunchtime.

**An injection did not apply, and that is what caught a corrupted tree.**
The "diff drops -z" injection reported its pattern missing. The cause was not
the pattern: an interrupted earlier run had left the flag stripped from the
working tree. Every test still passed, because the tests that need it are the
two committed-path ones and they had been green a moment earlier. Without
rule #66 - the injection must assert that it applied - the suite would have
been read as evidence that a file missing its fix was fine.
