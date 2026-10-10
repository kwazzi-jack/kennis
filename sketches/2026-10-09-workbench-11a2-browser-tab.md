# 11a2. A browser-tab application

Milestone / step: milestone 11, unit 11a2 (`design/plan.md`), concern #420
Date: 2026-10-09

## What I am about to do

Remove `pywebview`. `kennis gui` serves the same pages and opens them in
the person's own browser, always; the bar gains a Quit button, because
closing a tab no longer ends the process.

## How I expect it to work

**Launch.** `gui/serve.py::run(on_ready, *, open_browser=True)` starts
uvicorn on a thread exactly as now, hands the address to `on_ready`, then
calls `webbrowser.open(url)` unless told not to, and blocks on a
`threading.Event` - the *quit* event - until it is set or Ctrl-C arrives.
Then `server.should_exit = True` and the thread is joined, as now.
`_shown_in_a_window`, `_DropsBackendProbes`, `_WINDOW_TITLE` and the
`browser_only`/`on_no_window` parameters go.

**`--browser` becomes `--no-browser`.** There is nothing left to choose
between, so the old flag goes; but under `ssh -L` on a machine with no
display, `webbrowser.open` does not fail - it finds `www-browser`, `lynx`
or `w3m` and runs a text browser in the terminal kennis is printing to.
`--no-browser` (Jupyter's name for the same thing) prints the address and
opens nothing.

**Quit.** `build_app(token, on_quit=...)`: the callback is held on
`app.state`, defaulting to one that does nothing so every existing test's
`build_app(token)` still works. `POST /quit` is an ordinary form in the
bar - no htmx, so it works without a script and the answer is a whole
page - and answers with a page saying kennis has stopped and the tab can
be closed, then calls `on_quit`. In `run`, `on_quit` sets the quit event;
the main thread wakes, sets `should_exit`, and uvicorn finishes the
in-flight response before closing, so the page arrives.

**Quit refuses while a job runs.** A job is a daemon thread holding the
corpus lock and possibly half way through a commit; stopping the server
ends the process and kills it there. `Jobs.running()` (public, under the
guard) is asked; if a job is running, `/quit` answers with the shell and a
sentence naming the operation, and does not call `on_quit`. Ctrl-C has
the same hazard today and is not changed here - noted, not fixed.

**Words** in `gui/words.py`: the button's label, the stopped page, the
refusal. The command line's guidance line says how to stop: the Quit
button, or Ctrl-C.

**Dependency**: `uv remove --optional gui pywebview`; the architecture
test's blocked-import set loses `webview`.

## What I expect to be uncertain or difficult

- Whether uvicorn sends the stopped page before closing when
  `should_exit` is set from another thread during the request. I expect
  yes - shutdown waits for open connections - but it is a guess.
- Whether `webbrowser.open` really launches a console browser on a
  headless Linux machine; the reason for `--no-browser` rests on it.
- The token guard: `/quit` must be behind it like everything else; the
  middleware covers all routes, but the guard test should name it,
  because a route that stops the process is the one a hostile local
  process would most like to reach.

## What actually happened that I did not expect

- **The background task is not what delivers the page.** An injection
  that called `on_quit` before answering was not caught, and the reason
  was not a hollow test: uvicorn's graceful shutdown waits for requests
  already in flight, so the page arrives either way. The docstring had
  claimed the opposite (#318's shape again). It now says what holds:
  the order is stated rather than relied on, and what uvicorn will not
  do is answer the *next* request - which is why the stylesheet is
  inline. The sketch's first uncertainty is answered: yes, it sends it.
- The second uncertainty is confirmed from the standard library's own
  source: `webbrowser.register_standard_browsers` registers
  `www-browser`, `links`, `elinks`, `lynx` and `w3m` whenever `TERM` is
  set, so `--no-browser` is needed, not merely tidy.
- **`uv remove --optional gui pywebview` uninstalled every extra** from
  the development environment, because it syncs the default set
  afterwards - the hazard `docs/getting-started/install.md` warns about
  for `uv sync`. Restored with `uv sync --extra mcp --extra gui`;
  anything else that was installed (the `mineru` extra) is not.
- `test_every_class_the_templates_use_is_styled` caught `quit` and
  `stopped` without rules - the guard working as meant.
- The stopped page's text falls back to the system serif: the vendored
  face is a font file the server will not serve once it has stopped.
  Acceptable for one sentence; not inlined.
- Walked in the headless shell against Brian's corpus: Quit sits at the
  end of the bar, the stopped page arrives, no script errors, and the
  `kennis gui --no-browser` process exits 0.
- Seven injections, six caught; the seventh is the first item above.
