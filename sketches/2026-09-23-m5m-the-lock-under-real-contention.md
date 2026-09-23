# Milestone 5, item 5 finished: the lock tested across processes and commands

Milestone / step: Brian - "Please do test the cross lock and then we can
start the last milestone". Closes `concerns.md` #109 item 2.
Date: 2026-09-23

Previous sketch: `2026-09-23-m5l-markdown-normalisation-and-ligature-repair.md`.

## What I am about to do

No change to `engine/locking.py`. Three tests, because the existing
cross-process test spawns a python snippet rather than a command, and the
case a user meets is two `kennis` invocations racing.

1. A real command refused while the test holds the lock.
2. Eight processes started together, contending for one corpus.
3. A holder killed, and the corpus acquirable afterwards.

## How I expect it to work

`corpus_lock(root)` takes `FileLock(str(lock_path(root)), timeout=0)` and
converts `Timeout` into `CorpusBusy`. Nothing about that changes.

(1) runs `.venv/bin/kennis corpus init` with `KENNIS_CORPUS_ROOT` pointing at
a temporary directory, writes a note, takes the lock in the test process, and
runs `kennis corpus add -n <note>`. The command must exit non-zero and print
both the word `busy` and the corpus path. This is the path from the lock
through `CorpusBusy` and `render/` to what the user actually reads, which no
existing test covers.

(2) starts eight `subprocess.Popen` children on the same corpus. Each writes
`in` on acquiring, sleeps, writes `out` on releasing, or writes `busy` if
refused. Mutual exclusion is then a property of the journal: no `in` follows
another `in` without an `out` between them.

(3) starts a holder that writes a `ready` file and sleeps 60s, waits for
`ready`, asserts `CorpusBusy` in the test process, kills the holder, and
acquires. The point is that kennis relies on the kernel releasing the lock
when the process dies, not on its own `finally` running - a `finally` does
not run for a killed process.

Each verified by injection: a per-process lock file should fail all three; a
`timeout` that blocks rather than refuses should fail (2); a marker file
cleaned up in a `finally` should fail (3).

## What I expect to be uncertain or difficult

1. **How to invoke kennis from a test.** `[project.scripts]` installs a
   console script; whether the test should use it or `-m` needs checking.
2. **Whether (2) genuinely contends**, or whether the children are staggered
   enough that each finds the lock free. If they never overlap, the test
   proves nothing and looks fine.
3. **Timing.** Eight processes and a 60-second sleeper in a suite that runs
   in 18 seconds. The kill must be unconditional or a failed assertion hangs
   the run.

## What actually happened that I did not expect

### The first two failures were not about locking at all

`python -m kennis` does not exist - the entry point is
`kennis.cli.__main__:main` and there is no `src/kennis/__main__.py` - so (1)
failed on the invocation. Uncertainty 1, resolved by using the console script
at `Path(sys.executable).parent / "kennis"`.

Then (2) and (3) failed on `ResourceWarning: unclosed file`, because
`Popen(stdout=PIPE)` leaves the read ends open and `filterwarnings =
["error"]` makes that an error. `communicate()` instead of `wait()` fixes it
and improves the test: a child that died before reaching the lock now
reports its stderr rather than being silently counted as refused. #165.

### Uncertainty 2 was the real one, and worse than I expected

Ten runs of the eight-process scenario gave one `in` and seven `busy`, every
time. So the children do contend - but the mutual-exclusion loop is
*vacuous*: with a single `in` in the journal it cannot fail. It was not that
the processes failed to overlap; it was that overlapping correctly produces
a journal with nothing for the loop to look at.

`entries.count("busy") >= 1` is the assertion that discriminates, and the
blocking injection fails on exactly that line and no other - confirmed by
reading the failure text, not the exit status. #163.

### The injection harness lied by omission

The first injection run printed MISSED three times. All three were caught.
The harness passed `--timeout=300`, `pytest-timeout` is not installed, pytest
exited before collecting, and no `FAILED` line meant "not caught". #164.

#66 says an injection must assert it applied. The harness must also assert
the suite *ran*. Three consecutive MISSED verdicts were the signal - the
arithmetic was implausible before the cause was found.

### Uncertainty 3 cost one line

The kill in (3) is now in a `finally` with no `poll()` guard, inside
`with Popen(...)`, because `Popen.__exit__` waits - and waiting on a process
that sleeps for a minute would hang the suite after any failed assertion.

## Where this leaves milestone 5

Items 1, 2, 3, 5 and 6 are done and the lock is tested under real contention.
`kennis remember` is the only item left.
