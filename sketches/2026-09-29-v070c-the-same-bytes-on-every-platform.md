# The same bytes, and the same root, on every platform

Milestone / step: v0.7c, portability
Date: 2026-09-29

## What I am about to do

The first two items from the Windows list (#363). Both are defects
in kennis rather than in its tests, neither has a design question
in it, and between them they account for about fourteen of the
forty-nine failures.

**One: kennis writes CRLF on Windows and then hashes the bytes.**
`engine/atomic.py::replace_file` opens its temporary file with
`os.fdopen(handle, "w", encoding=encoding)` and no `newline=`, so
Python translates `\n` to `os.linesep`. Every corpus document,
every converged bundle file and every settings file kennis writes
on Windows lands as CRLF. `pack/content.py::content_digest` then
hashes `path.read_bytes()`, so the same logical document digests
differently on the two platforms - and `installed.py` and
`store.py` compare that digest and report a mismatch as the file
having been tampered with. The most alarming message available for
the most benign cause.

**Two: a drive letter is absolute and is not recognised as one.**
`corpus/inputs.py::_expand_pattern` decides where to start
searching with `text.startswith("/")`, which is true of `/a/b` and
false of `C:/a/b`. So `kennis corpus add "C:\papers\*.pdf"`
anchors at `Path(".")`, builds `./C:/papers`, finds no such
directory and refuses with "matched no files".

## How I expect it to work

**The newline.** `newline="\n"` on the text branch of
`replace_file`, and on the eight `write_text` calls under
`engine/`. Reading needs nothing: Python's universal newlines
already normalise CRLF to LF on read, so a source file with CRLF
is read correctly today. It is only the writing that varies.

This is the whole of it - one keyword in the one place every
document goes through, plus the writers that do not. I expect the
`.gitattributes` kennis writes to be irrelevant here, because git
normalises what is *in the repository* and `read_bytes` reads the
working tree.

**The anchor.** A pure helper that splits a pattern at its anchor:

    split_at_anchor(PureWindowsPath(r"C:\a\*.pdf"))
        -> ("C:\\", ["a", "*.pdf"])
    split_at_anchor(PurePosixPath("/a/*.pdf"))
        -> ("/", ["a", "*.pdf"])
    split_at_anchor(PurePosixPath("a/*.pdf"))
        -> ("", ["a", "*.pdf"])

It takes an already-constructed `PurePath` rather than a string,
which is the only way a test running on Linux can exercise the
Windows case at all - `Path(r"C:\a\b")` here is a single filename
with backslashes in it. No parameter is added for the test's sake;
the caller passes the `Path` it already built.

`_expand_pattern` then starts at `Path(anchor)` when there is one
and `Path(".")` when there is not. Two fudges fall out with it:
the `if segment != ""` filter on the literal segments and the
`+ (1 if text.startswith("/") else 0)` on the remainder both
existed only to skip the empty segment that splitting `/a/b`
produces, and stripping the anchor first means there is no empty
segment.

## What I expect to be uncertain or difficult

Whether `newline="\n"` is enough, or whether something downstream
re-introduces CRLF. `git` with `core.autocrlf=true` is the obvious
candidate on a Windows checkout, and the corpus *is* a git
repository. If git converts on checkout then the working tree has
CRLF whatever kennis wrote, and the digest diverges again for a
document that came back through a clone. I expect the corpus's own
`.gitattributes` to be the right place for that and I expect to
find it does not currently say so.

Whether any test asserts the current behaviour. A test that writes
through `replace_file` and reads back with `read_text` sees LF
either way, so I expect none to break - which also means none of
them would have caught this, which is the point.

Whether `split_at_anchor` belongs in `_glob.py` or in `inputs.py`.
`_glob.py` is the shared *dialect*, and anchoring is not part of a
dialect; search imports it and does not need this. I expect to
keep it local to `inputs.py`.

Whether I can verify either fix without a Windows machine. The
anchor, yes - `PureWindowsPath` is exactly for this. The newline,
only partly: I can assert the file object is opened with the
argument, and I can assert that writing a string containing `\n`
produces LF bytes, but on Linux that passes without the fix. So
the test has to be about the *call*, and it has to say so.

## What actually happened that I did not expect


**The `core.autocrlf` worry was right and is not fixed here.** The
corpus's `.gitattributes` names only the index (`*.npy binary`,
`index/** -diff`) and says nothing about `eol`. Git for Windows
defaults to `core.autocrlf=true`, which converts LF to CRLF *in the
working tree on checkout* - and `content_digest` reads the working
tree. So a corpus that arrived by clone would have the same
divergence back, whatever `replace_file` wrote.

It is not fixed because it cannot bite yet: remotes, clones and
cross-machine synchronisation are deferred by a decision taken
before planning, so no corpus is ever checked out. Fixing it is one
line - `* text=auto eol=lf` above the existing rules, where the
later `*.npy binary` still wins - but it changes what `corpus init`
writes, kennis has no migrations, and an existing corpus would need
it appended by hand. That is the second such manual step after the
`.gitignore` one, so it waits for the milestone that makes it
matter. #386, status `watch`.

**A writer in `cli/` that the test was built not to see.** The
first version of the newline test listed six modules under
`engine/`, with a comment defending the list - "adding a writer is a
decision someone makes deliberately". It was wrong on its own
terms: `cli/commands/config.py:275` was already writing a settings
file the platform's way, and the list I had just written excluded
it. A rule that holds for every writer has to be checked against
every writer, and the scan found the one the reasoning had talked
itself out of looking for.

**#337 for the fourth time, in the place I had just written.** The
test asserted `newline="\n"` appeared in `inspect.getsource`. The
function's own docstring explains why `newline="\n"` is there, so
deleting it from the call changed nothing the test could see, and
the injection was not caught. This is the same shape as the
`samesite=strict` comment (#373) and the vendored-notice substring
(#337): a string asserted against a file that also contains the
prose about that string. The remedy this time is an `ast` walk of
the `os.fdopen` call and its `newline` keyword, which cannot be
satisfied by prose at all - and that is a better remedy than
stripping comments, because it asserts the thing rather than its
spelling.

Worth stating as the general lesson: **every one of these four was a
test I wrote in the same hour as the code it describes, and in every
case the explanation and the assertion were the same words.** The
habit that produces it is writing the comment first.

Nothing broke. Not one of the 3,000 existing tests changed
behaviour, which is what the sketch predicted and for the reason it
predicted: a test that writes through `replace_file` and reads back
with `read_text` sees LF either way, so none of them could have
caught this and none of them noticed it being fixed.
