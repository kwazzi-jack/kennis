# The browser's diagnostics are not kennis's report

Milestone / step: after milestone 11's realignment (#447)
Date: 2026-10-12

## What I am about to do

Stop the browser's own messages reaching the terminal `kennis gui`
prints to. Brian saw, after kennis's lines:

    Opening in existing browser session.
    [1:1:...] ERROR:content/zygote/zygote_main_linux.cc:197] Failed
    sending zygote boot message: Broken pipe (32)

Both are written by the Brave process `webbrowser.open` starts. They
mean nothing to the person, and an ERROR line under kennis's address
reads as kennis failing (#319: a library's diagnostics are not kennis's
report).

## How I expect it to work

`webbrowser.open` starts the browser with `subprocess.Popen` and no
redirection, so the child inherits file descriptors 1 and 2. A new
`serve._open_quietly(url)` flushes Python's streams, duplicates 1 and 2
aside, points both at `os.devnull` with `os.dup2`, calls
`webbrowser.open`, and restores both in a `finally`. A child started in
that window keeps `/dev/null` for its whole life; kennis's own output
returns when the call does. `xdg-open` execs the browser, so the browser
inherits `xdg-open`'s descriptors, which are the null ones.

Not a filter on the browser's messages: there is nothing in them kennis
could act on, and kennis printed the address before opening, so a
browser that fails to open leaves the person a way in.

## What I expect to be uncertain or difficult

- The window during which kennis's own stderr is null. uvicorn logs at
  warning level from its thread; a warning in those few milliseconds
  would be lost. Accepted: the server has just started and is idle.
- Under pytest's capture, descriptors 1 and 2 are pytest's files. The
  restore must put them back exactly, or later tests lose their output.
- Windows: `os.dup2` works on descriptors 1 and 2 there too.

## What actually happened that I did not expect

- **The first test could not see a missing restore.** It wrote "kennis
  after" with `print`, and under `capfd` pytest's `sys.stdout` writes to
  its capture file directly, not through descriptor 1. It writes with
  `os.write(1, ...)` now, which is what uvicorn and a child would use.
- **An injection opened a real browser.** The test of `run` replaced
  `_open_quietly` but not `webbrowser.open`, so the injection that
  bypassed the first called the second for real: the test failed, with
  a teardown error, and a tab at a dead address probably opened on
  Brian's desktop. Both are replaced now.
- Checked for real: `kennis gui` with `BROWSER` pointing at a script
  that prints Brave's two lines shows only kennis's four.
- Injections: three, all caught after the two fixes above.
