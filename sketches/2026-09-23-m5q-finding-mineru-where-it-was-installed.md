# Finding mineru where kennis's own installation put it

Milestone / step: Brian installed `kennis[mineru]` as a uv tool and was told
mineru was not installed.
Date: 2026-09-23

Previous sketch: `2026-09-23-m5p-what-first-real-use-found.md`.

## What I am about to do

    uv tool install "kennis[mineru] @ ../PhD/kennis/"
    ...
    + mineru==3.4.5
    Installed 1 executable: kennis

    kennis corpus add -l "...pdf"
    error: mineru is required to convert PDF files and is not installed.
      hint: run `uv sync --extra mineru`

Neither a uv syntax problem nor a failed install. Verified on his machine:
`~/.local/share/uv/tools/kennis/bin/mineru` exists and
`import mineru` succeeds from that environment's interpreter. `uv tool
install` links only the *requested* package's entry points, and says so in
the line above: one executable, kennis. So mineru is installed and is not on
PATH, and `is_available` asks `shutil.which("mineru")`.

Two fixes.

**Look beside the interpreter as well as on PATH.** The interpreter running
kennis is inside the same environment mineru was installed into, so its
directory is where to find it when PATH does not. `_executable(name)` does
both, and `_run` passes the resolved path rather than the bare name - a
subprocess given the name resolves it against PATH again, which is the place
it is not.

**Name the command that actually resolves it.** `uv sync --extra mineru` is
right in a source checkout and meaningless to someone who installed the tool:
there is no project to sync. `_from_source_checkout()` decides, by looking
for a `pyproject.toml` above `src/kennis/`, and the hint is
`uv tool install "kennis[mineru]"` otherwise.

## How I expect it to work

    def _executable(name: str) -> str | None:
        beside = shutil.which(name, path=str(Path(sys.executable).parent))
        return beside or shutil.which(name)

`shutil.which` with an explicit path rather than joining by hand, so Windows
still applies PATHEXT.

## What I expect to be uncertain or difficult

1. **Which of the two wins.** I have written it interpreter-first above.
2. Whether `_from_source_checkout` can tell an editable install from a real
   one. I think it does not need to: an editable install *is* a checkout, and
   `uv sync --extra mineru` is the right answer for it.
3. Whether a pip or pipx user gets a command that does not fit. They do, and
   I am accepting it: the project mandates uv, and the two cases it has are
   the two this distinguishes.

## What actually happened that I did not expect

### Uncertainty 1 was the whole problem, and I got it the wrong way round

Interpreter-first broke sixteen tests. `fake_mineru` substitutes a fake by
prepending a directory to PATH, and with the interpreter's own directory
consulted first, this checkout's real `.venv/bin/mineru` won every time. The
suite went from a second to thirty-two, and three tests failed with
`mineru failed: No supported documents found` - the real converter, running
against a fixture written for a fake.

**Prepending to PATH is how a person substitutes one build of a tool for
another.** Looking elsewhere first silently ignores that, which is a worse
bug than the one being fixed, because it is invisible whenever both exist.
PATH first; the interpreter's directory is the fallback for when PATH has no
answer at all, which is exactly and only the tool-install case.

The order is now a test of its own, because nothing else would have caught
putting it back.

### The `no_mineru` fixture was not what it said

Its docstring said "an environment with no `mineru` anywhere on PATH", and
that was enough while PATH was the only place kennis looked. With the
fallback it no longer is: four tests asserting absence passed PATH emptiness
and then found the checkout's own mineru beside the interpreter. Three of
them ran it.

The fixture now empties both, and its docstring says "anywhere kennis looks"
rather than naming one mechanism. A fixture that names a mechanism rather
than a property goes stale the moment the mechanism widens.

### What it does now

From a real `uv tool install "kennis[mineru]"`, with nothing on PATH:

    available : True
    resolved  : .../tools/kennis/bin/mineru
    checkout? : False
    hint      : uv tool install "kennis[mineru]"

and from this checkout:

    checkout? : True
    hint      : uv sync --extra mineru

End to end from that tool install, with nothing on PATH: a PDF converted by
mineru, `Added 1 document in 20.8s`.

### An injection found the branch I had verified by hand and not by test

`_from_source_checkout` returning `True` for everything passed the whole
suite. The hint test patches the predicate, so it exercises both hints and
neither detection; the other test covers only the true case, which is the
one this tree is in. Every installed user would have been told to sync a
project they do not have, and I had checked that they would not - by hand,
against a real tool install, which is evidence that expires the moment
somebody edits the predicate.

The predicate is now `_is_source_checkout(root)`, taking the root as an
argument, so both answers are reachable from a temporary directory. This is
#179 from the other side: there, an injection could not reach the behaviour;
here, the behaviour had no test to reach.
