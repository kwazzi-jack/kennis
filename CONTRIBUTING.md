# Contributing to kennis

kennis is experimental and changes without deprecation before v1.0.0. A
change is welcome when it comes with tests and follows the rules below.

## Setting up

kennis uses [uv](https://docs.astral.sh/uv/) for everything; do not use
`pip`.

```
uv sync
uv run pre-commit install --install-hooks --hook-type commit-msg
uv run pytest
```

The hooks run ruff, mypy (also as it would on Windows), an ASCII check and
the commit message checks below. The default test run leaves out tests that
need the network, a browser, a real service process or a large corpus; each
has a marker named in `pyproject.toml` and runs with `uv run pytest -m
<marker>`.

## Branches

`main` is what the next release is cut from. Nobody commits to it directly.

1. Open a branch from an up-to-date `main` for each unit of work, named
   `<type>/<short-description>` in lowercase with hyphens, where `<type>` is
   one of the commit types below: `feat/tags`, `fix/windows-paths`,
   `docs/contributing`.
2. Keep the branch to one logical change. A second change gets a second
   branch.
3. Bring in later work from `main` by rebasing onto it, not by merging it
   into the branch.
4. Open a pull request into `main`. The test workflow runs on Linux, macOS
   and Windows, and it must pass on all of them before the request is
   merged.
5. The pull request is squash-merged, so it lands on `main` as one commit
   whose message is the pull request's title. The branch is then deleted.

## Commit messages

Every commit, on a branch and on `main`, has a one-line message in the
[Conventional Commits](https://www.conventionalcommits.org/) form:

```
<type>(<scope>): <description>
```

- `<type>` is one of `feat`, `fix`, `docs`, `refactor`, `perf`, `test`,
  `build`, `ci` or `chore`.
- `<scope>` names the part of kennis changed, such as `context`, `gui` or
  `search`.
- The description is lowercase, in the imperative mood, with no trailing
  period: `feat(context): tag a document or a passage`.
- A breaking change puts `!` after the scope:
  `feat(context)!: copy a declared pack's context into the project`.
- No body, no footer and no trailers.

A pull request's title follows the same form, because squashing makes it
the commit message on `main`. commitizen reads those messages to decide
the next version, so a malformed title is a version decision lost.

## Code

- Type hints everywhere; mypy runs in strict mode.
- ASCII only, in every file: no em dashes, arrows, curly quotes or other
  non-ASCII characters.
- The engine (`src/kennis/engine/`) never prints and never imports an
  interface library; words for a person live in `src/kennis/render/`.
  `tests/test_architecture.py` enforces the layering.
- Write the test before the change, and check that it fails without the
  change.

## Tests

The default suite runs in parallel, one worker per logical CPU:

```
uv run pytest -n logical
```

CI runs it that way on every platform. Plain `uv run pytest` runs the
same tests one at a time, which is easier to read when one fails. The
`service` and `browser` runs stay serial, because they start real
processes.

Parallel workers are safe only because no test shares anything with
another. Fixtures in `tests/conftest.py` that apply to every test already
point the home directory, kennis's state and configuration directories,
the corpus location and the working directory into the test's own
`tmp_path`, and refuse network access. A new test keeps that true:

- Write files only under `tmp_path`, never at a fixed path.
- Set an environment variable or replace a module's attribute only through
  `monkeypatch`, which undoes it when the test ends; never assign
  `os.environ` directly or leave a module-level value changed.
- Bind a server to port 0 and read the port the kernel chose; never use a
  fixed port.
- A test that needs the network is marked `network`, and one that starts a
  real kennis service process is marked `service`.
- Wait for an event, not for a time: a loaded machine wakes late, and
  Windows' clock ticks only every 15.6 ms. Before reading what a job did,
  wait for the job to finish.
- To bound how long something took, read the clock before the action that
  starts it, never after: on a loaded machine the gap between the two is
  subtracted from the measured time.
- Find a line of output by something only that line can contain. A short
  word such as `add` can also turn up inside a commit hash, which is
  hexadecimal.

A test that passes in a serial run and fails in a parallel one is either
sharing something with another test, or depending on timing that the
extra load has changed. So far it has always been the second.

## Releases

Releases are cut from `main` by the maintainer, batched rather than one per
change.
