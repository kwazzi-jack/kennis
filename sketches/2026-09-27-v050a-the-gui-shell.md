# v0.5 unit 9a: the shell - a window, a port nobody else can use, and a theme

Date: 2026-09-27

## 1. What I am about to do

`kennis gui`. A third front end: a local web interface served in-process,
shown in a native window where the operating system provides one and in a
browser tab where it does not.

This unit builds nothing a user would call a feature. It builds the four
things that are expensive to add later: the process shape, the token, the
theme adapter, and the architecture invariant that keeps `gui/` a peer of
`cli/` and `mcp/` rather than a client of either.

## 2. How I expect it to work

**One process.** `uvicorn` runs the app on a thread; the main thread opens
`pywebview` and blocks until the window closes; closing the window stops the
server. In browser mode there is no window, so the command blocks until
interrupted and says so.

**The window is optional and its absence is not an error.** `pywebview`'s
backend is per platform - WebView2 on Windows, WKWebView on macOS, WebKitGTK
on Linux - and on Linux nothing installs it by default. So: try the window,
and on failure open a browser tab. The same page either way. A `--browser`
flag forces the fallback, because that is the mode that works over `ssh -L`.

**The port is private, and this is the part that must be right the first
time.** Bind `127.0.0.1` explicitly, take port 0 and let the kernel choose,
mint a token per launch, and require it. Loopback is not private on a shared
machine and Brian works on cluster login nodes. Concern #309.

The token is checked by middleware, not per route, so a route added later
cannot forget it. It arrives once as `?token=...` and is then held in a
cookie, so it is not in every subsequent URL.

**The theme is adapted, not redefined.** `render/theme.py` already declares
semantic roles against eight ANSI colours, for exactly this. The adapter
emits one CSS custom property per role. **Its test is exhaustive** - every
role in the registry must appear - so adding a role and not styling it fails,
which is the property that made `render/diagnostics.py`'s match worth having.

**`gui/` is a peer.** It imports neither `cli/` nor `mcp/`; nothing in
`engine/` or `render/` imports it. One more forbidden set in
`test_architecture.py`, written now, before there is anything to get wrong.
And `kennis --help` must work with the extra uninstalled, so the web imports
live inside the command body, as `serve` does.

**Two pieces of configuration that are prerequisites rather than polish:**

- The `ascii-only` pre-commit hook runs on `types: [text]`, which is every
  staged text file, and unit 9b vendors KaTeX, which is Unicode by its
  nature. Add `exclude:` to the hook and `--exclude-dir=vendor` to
  `scripts/check_ascii.sh`, so the rule stays absolute outside one named
  directory. Concern #308.
- CI runs `ubuntu-latest` only, and this milestone's whole justification was
  that it works on three platforms. Widen the matrix. Concern #310.

## 3. What I expect to be uncertain or difficult

- Whether `pywebview` can be imported at all on this machine without a
  backend, or whether it raises on import rather than on window creation.
  The fallback depends on which, and I have not checked.
- Shutting down cleanly. `uvicorn` in a thread with a window on the main
  thread is two lifetimes; I expect the untidy case to be closing the window
  mid-operation while the engine holds the corpus lock.
- Whether a cookie survives `pywebview`'s webview at all. If it does not, the
  token stays in the URL and the test has to say so rather than the code
  pretending otherwise.
- Testing the window. I do not think it can be tested, and I would rather say
  that than write something that passes without exercising it. The server,
  the token and the theme all test properly through `TestClient`.
- Whether widening CI to three platforms breaks tests that assume POSIX
  paths. I expect it does, and that finding out is the point.

## 4. What actually happened that I did not expect

**Two of my injections were false passes, and the stricter check found
the second only after it found the first.** I ran seven, and read
seven "caught". Both the sixth and seventh were lies.

The seventh named `tests/test_gui_serve.py`, a file that does not
exist. `pytest` exits non-zero on a usage error exactly as it does on
a failure, so a missing test file reads as a caught defect. This is
#66 again - "the injection must assert that it applied" - in a form
the rule as written does not cover: the *replacement* applied
perfectly, and it was the *verdict* that was unearned.

Tightening the harness to require the word `failed` in pytest's output
then exposed the fourth injection as the same thing for a different
reason: `_unused = (COOKIE_NAME, token, httponly=True, ...)` is a
syntax error, so the suite failed at collection and never ran a test.
A valid injection - turning the condition to `if False:` - is caught
properly.

So the harness itself needed the treatment it exists to apply. The
general rule to carry forward: **a non-zero exit is not evidence of a
test failing.** A missing file, a syntax error, a collection error and
an import error all exit non-zero, and all three of those are things
an injection can cause by accident.

**`create_window` does not need a backend; `start()` does.** Section 3
guessed the fallback might have to sit around the import. Measured:
`import webview` succeeds with no backend installed, `create_window`
succeeds, and `start()` is where the absence surfaces - as
`AttributeError: 'NoneType' object has no attribute 'initialize'` from
pywebview's own internals. So the fallback wraps `start()`, and it
catches broadly rather than narrowly, because that error is not a
contract and the three platforms fail three undocumented ways.

**The palette has nine colours, not eight.** The design says "one of
the eight standard ANSI colours" in two places and `render/theme.py`
declares nine - `bright_black` is in `AnsiColour` and `muted` wears
it. It matters here because CSS has no `bright_black` keyword: a map
that fell back to the ANSI name would emit a colour no browser
understands, the text would render unstyled, and nothing would say a
colour had been lost. The adapter now names all nine explicitly and
raises at import if the registry gains a tenth.

**My own test compared the wrong two things.** I wrote "the adapter
defines no colour of its own" as "every emitted value is in the set of
registry colours" - which compares a CSS name against an ANSI one and
fails for `gray` even when correct. The property I wanted is tighter
and simpler: each role emits *its own* colour, transliterated. A
plausible-but-wrong mapping fails that and would have passed the
first.

**I wrote the command with the address printed after the block.**
`run()` blocks until the window closes, so `display.detail("+", url)`
after it would have shown the address once the interface had already
shut down - and in browser mode, where `webbrowser.open` can fail
silently, that address is the only way in. Caught by reading it back
rather than by a test, which is the honest account: nothing in the
suite would have noticed.
