# What cannot run where, and why

Milestone / step: v0.7e, portability
Date: 2026-09-29

## What I am about to do

The last two items I can do from #363 without a decision from
Brian. Both are skips, and a skip is the thing most likely to
quietly disable a test everywhere, so the unit is mostly about
making that impossible.

**The converter fakes need a POSIX shell.** `conftest.py`'s
`fake_mineru` writes a `#!/bin/sh` script and chmods it, and
`test_converters.py` writes a second one inline for the timeout
test. Windows has neither a shebang nor `/bin/sh`, so
`MineruConverter().is_available()` is false and every test that
depends on one fails. Nothing about kennis is wrong.

Making the fake portable is not available: kennis resolves the
binary with `shutil.which` and invokes the resolved path directly,
which is correct for a real MinerU on Windows - a console script
installs as `mineru.exe` - and cannot work for a `.cmd` shim,
because `CreateProcess` will not run a batch file. So the honest
answer is a skip that says so. #392 holds the larger question,
which is Brian's: whether any CI job should install the real thing.

**One filename is illegal on Windows.**
`test_a_path_containing_an_arrow_is_not_read_as_a_rename` uses
`notes/a -> b.md`, and `>` cannot appear in a Windows filename at
all. The umlaut tests beside it should now pass there, because
v0.7d fixed the decode, so this is one test rather than five.

## How I expect it to work

A new `tests/platforms.py` holding the reasons and the markers,
because three places need them - the fixture, the timeout test and
the arrow test - and a reason repeated three times is a reason that
will disagree with itself. The credentials skip v0.7d put inline in
`test_setup.py` moves there too, so there is one place that answers
"what does not run where".

The `fake_mineru` fixture calls `pytest.skip` rather than carrying
a marker, so every test that takes it is covered and so is the next
one somebody writes. The two standalone cases take the marker.

**The guard is the point of the unit.** An unconditional skip would
disable seventeen tests on every platform and the suite would go
green saying so in a line nobody reads. So a test asserts that on a
POSIX platform none of these markers skips anything - which fails
if a condition is inverted, dropped, or written as a bare
`pytest.mark.skip`. And a second asserts every marker has a
non-empty reason, because a skip without one is a test that
disappeared.

## What I expect to be uncertain or difficult

Whether `pytest.skip` inside a fixture reports its reason
legibly. I think it does - pytest attributes the skip to the test
and prints the reason with `-rs` - but I have not checked, and if
it does not then a reader sees seventeen skips with no explanation,
which is worse than the failure it replaces.

Whether asserting "nothing skips here" is testable without running
the suite twice. I expect to assert the marker objects directly
rather than collect the suite, which is weaker but honest about
being so.

Whether moving the credentials skip is scope creep. It is three
lines and it is the same question; I think leaving one reason in
`test_setup.py` and two in a module called `platforms.py` is worse
than moving it, but it is a judgement call.

## What actually happened that I did not expect


**The verification was better than the plan.** I doubted whether
asserting "nothing skips here" was testable without running the
suite twice, and said I would settle for asserting the marker
objects. Then forcing `_WINDOWS = True` and running the whole suite
did both jobs at once: 20 tests skipped with legible reasons, and
`test_nothing_is_skipped_on_this_platform` **failed**, because
`os.name` was still `posix` while the condition said otherwise.
That is the guard doing exactly its job, observed rather than
argued, and it is a better demonstration than the injection that
followed.

The reasons print well. `-rs` gives the full sentence per test,
which was the thing I could not check from the sketch.

**`git checkout -- <file>` reverted an uncommitted edit I wanted.**
Restoring `tests/platforms.py` from a backup and `tests/conftest.py`
from git looked symmetrical and was not: conftest's skip was not
committed, so checkout threw it away and the suite passed without
it. Caught by grepping for the line rather than by the suite, which
had nothing to say - a fixture that does not skip on Linux behaves
identically either way. **A `git checkout` on a file with
uncommitted work in it is a delete**, and "restore the experiment"
is exactly the moment that is easy to forget.

**20 skips, not the 14 #363 counted.** The eleven with the shell
reason are nine in `test_converters.py` and two in
`test_input_matrix.py`; the rest are the arrow, the credentials
mode, and pre-existing marked skips. I cannot reconcile that against
#363's fourteen without a Windows run, and I have not tried to -
#363 sorted failures by cause from a CI log, and some of its
converter group may fail for a neighbouring reason that this does
not cover. The next Windows run will say.

`tests/platforms.py` imports as `platforms`, not `tests.platforms`:
there is no `tests/__init__.py` and pytest puts the test directory
on `sys.path` itself. Worth knowing before the next module that
wants to be shared between test files.
