# Four more of the Windows list

Milestone / step: v0.7d, portability
Date: 2026-09-29

## What I am about to do

Four of the remaining #363 items. One of them is a correction to
what v0.7c concluded.

**The correction first.** #386 said git's `core.autocrlf` could
undo v0.7c's fix but could not bite until remotes landed, because
nothing checks a corpus out. That was wrong.
`Repository.restore` runs `git checkout <commit> -- <path>`, which
writes the working tree, and `operations.py::restore_hand_deletions`
calls it from `add_documents`, `build_indexes` and
`synchronise_corpus`. Delete a document by hand on Windows, run
`kennis corpus add`, and git puts it back as CRLF. No clone
required. So the `.gitattributes` line goes in now.

**Git's output is decoded with the wrong codec.**
`engine/history/git.py::git` runs `subprocess.run(..., text=True)`
with no `encoding=`, so Python decodes with the locale encoding:
UTF-8 here, the ANSI code page there. Git emits paths as UTF-8, so
`ete.md` with accents comes back mojibake on Windows. The parser
itself is already right - `--porcelain -z` disables git's octal
quoting entirely.

**A lock test asserts `filelock`'s behaviour, not kennis's.**
`test_the_lock_is_never_committed` checks `lock_path(corpus).is_file()`
*after* the command released the lock. `filelock` leaves the file
behind on Unix and deletes it on release on Windows, where locks are
mandatory. kennis is fine; the test is asserting an implementation
detail of a dependency.

**The credentials guarantee is reworded rather than enforced.**

## How I expect it to work

**`.gitattributes`.** `* text=auto eol=lf` above the existing rules,
and `index/** -diff` becomes `index/** -diff -text`. The second is
not caution about `text=auto`'s binary detection - that is reliable,
it looks for NUL bytes - but about saying the intent where the file
is read rather than relying on a heuristic for generated artefacts
kennis knows are binary. Later rules win in gitattributes, so the
existing `*.npy binary` still overrides `*`.

An existing corpus does not get this, because kennis writes no
migrations. That is the second manual step after the `.gitignore`
one and it goes in CLAUDE.md beside it.

**The codec.** `encoding="utf-8"` on the one `subprocess.run` in
`git.py`. Deliberately *not* also `errors=`: today the call is
strict UTF-8 on a UTF-8 locale, so adding the encoding alone changes
nothing on Linux and fixes Windows, where adding `errors="replace"`
would silently corrupt a path kennis then uses to address a file.
A path that will not decode should raise.

**The lock test.** Assert while the lock is held rather than after:

    added(run, a_source(...))
    with corpus_lock(corpus):
        assert lock_path(corpus).is_file()
        assert ".kennis.lock" not in tracked(corpus)

The `is_file()` line is doing real work and must stay - without it
the second assertion passes trivially on Windows for a file that was
never there, which is the #66 shape. Holding the lock is what makes
both true on both platforms.

**The credentials wording.** Brian's reading, and I agree with it
for a reason worth writing down: `0600` protects against *other
unprivileged users of the same machine*, and the Windows per-user
profile ACL protects against exactly that same set. The two are
materially equivalent; neither protects against the same user's own
processes, and neither protects against root or Administrator. So
`pywin32` would buy the ability to say kennis set it and no actual
protection, at the cost of a Windows-only dependency with a
post-install step on the platform that is already weakest.

So `design.md`'s table says what is true on each platform, and the
test asserts per-platform rather than asserting `0600` everywhere.

## What I expect to be uncertain or difficult

Whether `* text=auto eol=lf` disturbs anything already committed.
It should not - it changes the *working tree* ending on checkout and
the staging normalisation, and everything kennis writes is already
LF after v0.7c - but a corpus that already holds a CRLF file would
see it normalised on its next commit, which shows as a diff nobody
asked for. I expect no such file to exist and I expect to be unable
to prove that here.

Whether the lock test still fails for the right reason if the
`.gitignore` entry goes. That is the thing it exists to catch, so
the injection has to remove the ignore rather than the assertion.

Whether `encoding="utf-8"` is observable from Linux at all. I expect
not directly - the locale here is UTF-8, so the two are the same
call - so the test has to read the argument, and it has to say that
is what it is doing rather than pretending to measure a decode.

## What actually happened that I did not expect


**#387 arrived twice more, and the second one was inverted.** The
codec test searched `inspect.getsource` for `encoding="utf-8"`, and
the comment I had just written to explain the argument contains it -
so I moved to an `ast` walk, which is what #387 had already said to
do. Then the *negative* test, asserting no `errors=`, failed against
correct code, because the same comment says "No `errors=`:". A
textual negative is satisfied by prose exactly as a textual positive
is. Both tests now share one helper that returns the `.run(...)`
calls as syntax, and neither can be satisfied by anything written
about them. That is six instances of this family now (#337, #360,
#373, #387, and these two), and the rule has earned its place: where
a structural assertion exists, a textual one is a mistake, not a
shortcut.

**`ls-files` quotes and I nearly tested the wrong thing.** The first
version of the round-trip asserted that an accented filename came
back from `git ls-files` - and it failed on Linux, where the locale
is UTF-8 and the decode is already right. The cause was
`core.quotePath`, which `ls-files` honours and `--porcelain -z` does
not. The test was exercising a command kennis does not parse: a grep
confirmed `ls-files` appears only in the test helpers. Rewritten
against `status_names`, which is the real path, it passes here and
is the one that means something on Windows. Had I not checked, I
would have "fixed" quoting that was never in the way.

**The lock injection was inert before it was anything.** Removing the
*comment* above `.kennis.lock` in `_GITIGNORE` left the rule intact,
so the harness proved nothing and reported a miss. #318's
instruction - find out whether the test is hollow or the change was
inert before touching the test - took about a minute here, and the
test needed no change at all.

Nothing about the `.gitattributes` rule was difficult, and the
worry about disturbing committed content was unfounded for a reason
I had not thought of: the rule only ever applies to a repository
created after it, since kennis writes no migrations, and such a
repository has no CRLF in it to normalise.

The credentials decision came out where Brian read it, and the
reason is worth stating once: `0600` and the Windows per-user
profile ACL deny the same set - other unprivileged accounts on the
machine. Neither stops the user's own processes; neither stops root
or Administrator. `pywin32` would buy the sentence "kennis set it"
and no protection, on the platform whose install path is already
the weakest.
