"""What cannot run where, and why.

One place rather than a `skipif` at each site, because a reason repeated
is a reason that will disagree with itself - and because a reader asking
"what does kennis not cover on Windows" should have somewhere to look
that is not a grep.

**Every marker here is conditional, and `test_platforms.py` fails if one
stops being.** An unconditional skip disables its tests on every platform
and the suite reports it in a line nobody reads; that is a worse outcome
than the failure being skipped, because a failure is at least loud.

Nothing here excuses a defect. A skip is for something the platform
cannot express - a shell it has not got, a filename it will not accept, a
permission model it does not have. Where kennis was wrong the fix was to
kennis: see concerns #384, #385, #388 and #391, all of which were found
in the same sweep as these and none of which is skipped.
"""

from __future__ import annotations

import os

import pytest

# Windows has no `/bin/sh` and no shebang, so a fake executable written as
# a shell script cannot run. Making the fake portable is not available
# either: kennis resolves the binary with `shutil.which` and invokes the
# resolved path directly, which is right for a real MinerU there - a
# console script installs as `mineru.exe` - and cannot work for a `.cmd`
# shim, because `CreateProcess` will not run a batch file.
#
# What is skipped is kennis's *handling* of a converter, which is
# platform-independent logic covered on Linux and macOS. Concern #392
# holds the larger question, which is that no CI job on any platform
# installs a real MinerU.
NO_POSIX_SHELL = (
    "the fake mineru is a /bin/sh script, which Windows cannot execute; "
    "a .cmd shim cannot replace it because kennis invokes the resolved "
    "path directly and CreateProcess will not run a batch file (#392)"
)

# `>` is not a legal character in a Windows filename, so the fixture
# cannot be created at all. The test is about `-z` status parsing not
# mistaking a filename for the ` -> ` of a rename, which is a real hazard
# and is covered everywhere the filename is expressible.
NO_ARROW_IN_A_FILENAME = (
    "a Windows filename may not contain '>', so `notes/a -> b.md` cannot "
    "be created (#363)"
)

# Windows has no POSIX file mode: `chmod` toggles only the read-only flag
# and the file reports 0666. What protects the key there is the config
# directory's ACL, which denies the same set 0600 denies. The guarantee is
# stated per platform in design.md and asserted everywhere by
# `test_the_credentials_file_is_where_the_platform_protects_it`.
NO_FILE_MODES = (
    "Windows has no POSIX file mode, so 0600 is not expressible; the "
    "config directory's ACL is what protects the key there (#389)"
)

_WINDOWS = os.name == "nt"

needs_a_posix_shell = pytest.mark.skipif(_WINDOWS, reason=NO_POSIX_SHELL)
needs_arrow_filenames = pytest.mark.skipif(_WINDOWS, reason=NO_ARROW_IN_A_FILENAME)
needs_file_modes = pytest.mark.skipif(_WINDOWS, reason=NO_FILE_MODES)

# What `test_platforms.py` iterates. A marker missing from here is one
# nothing checks, so the guard asserts this names every marker the module
# defines.
MARKERS = (
    needs_a_posix_shell,
    needs_arrow_filenames,
    needs_file_modes,
)

__all__ = [
    "MARKERS",
    "NO_ARROW_IN_A_FILENAME",
    "NO_FILE_MODES",
    "NO_POSIX_SHELL",
    "needs_a_posix_shell",
    "needs_arrow_filenames",
    "needs_file_modes",
]
