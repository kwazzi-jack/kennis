# What the first Windows run found

Milestone / step: #363, after the push - the first real Windows run (CI on
271bce9, v0.6.1): 16 failed, 2998 passed, 21 skipped
Date: 2026-10-08

## What I am about to do

Fix the four product defects the run exposed and the four test assumptions
it disproved, after Brian decided (2026-10-08) that a pack's digest treats
CRLF and LF as the same.

## How I expect it to work

Product, each testable on Linux:

1. `pack/content.py::content_digest` hashes `data.replace(b"\r\n", b"\n")`.
   Every caller digests text - a pack file, its markdown content, a
   document body - so the change is one line. An LF-only file digests as
   before, so no existing pack or store changes. Fixes the seven pack
   tests on Windows, where `a_file`'s default `write_text` wrote CRLF.
2. `corpus/intake.py::read_text_file` normalises `\r\n` and lone `\r` to
   `\n` after decoding - what universal newlines do, and what #384 said
   reading already did. It decodes `read_bytes()`, so it never did, on
   any platform: a CRLF markdown file added on Linux carries `\r` into
   `Document.body` today.
3. `pack/schema.py::_stays_under_the_pack_root` asks both path flavours:
   refused if either `PurePosixPath` or `PureWindowsPath` has an anchor,
   or either has `..` among its parts. A pack is data written on one
   platform and installed on another, so the host's `Path` is the wrong
   question - `/etc/passwd` has no drive and passed on Windows, and
   `C:\x`, `\x` and `..\x` pass on Linux today. Testable here by
   parametrising with the Windows forms.
4. `render/refusals.py` quotes a remedy's argument for the platform:
   `shlex.quote` on POSIX, `subprocess.list2cmdline` on Windows, which
   double-quotes only when needed and runs in both cmd and PowerShell.
   Two named functions so both are tested on Linux; the one chosen
   depends on `os.name`.

Tests:

5. `an_interpreter_with` names the fake `mineru.exe` on Windows:
   `shutil.which(name, path=...)` only finds a PATHEXT name there, and a
   real uv tool venv holds `Scripts\mineru.exe` beside `python.exe`, so
   kennis is right and the fixture was POSIX-shaped.
6. The stale-index test picks the note through `bundle_notes`, not the
   first `glob` hit: NTFS lists `.skeleton.md` before `Four minutes.md`,
   so it edited the skeleton - which the loader ignores - and changed
   only its line endings. #362's shape again.
7. The docs test compares `as_posix()` paths with the nav.
8. The byte-for-byte pack test writes its fixture with `newline="\n"`:
   kennis writes LF (#384), so a CRLF pack file is normalised on rewrite,
   and that is the policy rather than a loss. Recorded as a consequence
   in the concern.

## What I expect to be uncertain or difficult

- Nothing here can be run on Windows locally. Each product fix gets a
  test that fails on Linux first; the test fixes can only be checked by
  the next CI run, so the claim is "expected to pass", not "passes".
- Whether normalising in `read_text_file` changes any stored document's
  digest. Only for a source that had CRLF, and no corpus document was
  ever added from one here; Brian's corpus is LF.
- Whether `list2cmdline` of a path with no space returns it bare - it
  should, which keeps the Linux-visible test meaningful.

## What actually happened that I did not expect

- **A test pinned the defect on purpose.** `test_line_endings_are_not_normalised`
  asserted that CRLF and LF digest differently, "worth pinning so nobody
  'fixes' it into a text-mode read". It was the one failure in the full
  suite after the fix, and it is the record that the raw-bytes digest
  was a stance and not an oversight - reversed by Brian's decision, not
  by drift. Reversed in place with the old wording quoted.
- **#384's "reading needs nothing" was false on every platform**, not
  just Windows. Nothing had ever added a CRLF source here, so nothing
  saw it.
- The insertion of the quoting helpers landed between two import
  statements, and ruff caught it, not a test.
- As expected, `list2cmdline` leaves a path without spaces bare, which
  is what lets `test_a_refused_add_offers_the_command_that_resolves_it`
  check the Windows dispatch on the next run unchanged.
