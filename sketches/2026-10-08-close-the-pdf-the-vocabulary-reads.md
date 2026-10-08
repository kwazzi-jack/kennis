# Close the PDF the ligature vocabulary reads

Milestone / step: defect reported by Brian from `kennis corpus add -l` on
0.6.2, outside the plan
Date: 2026-10-08

## What I am about to do

Close the `PdfDocument` that `ligatures.py::text_layer_vocabulary` opens,
so pypdfium2 stops listing open objects at interpreter exit and a
long-lived process stops holding the source PDF.

## How I expect it to work

`MineruConverter.convert` -> `text_layer_vocabulary(pdf_path)` once per
converted PDF, when `conversion.repair_ligatures` is on (the default). It
opens `pypdfium2.PdfDocument(pdf_path)`, and for each page a `PdfPage` and
a `PdfTextPage`, and closes none of them. pypdfium2 registers each with a
`weakref.finalize` and, at exit, closes what is left and writes the list
to stderr with `os.write` - which is the message Brian saw after a
successful add.

`PdfDocument` is a context manager whose `__exit__` is `close()`, and
`close()` closes the document's kids (pages, text pages) first. So one
`with` around the walk closes all of it, on the exception path too.

Tests: in-process, record the `PdfDocument` the function creates and
assert its `raw` is None afterwards (what `close()` sets); and a real
subprocess that calls the function on the reportlab fixture and asserts
stderr does not contain "still open", which is the symptom itself.

## What I expect to be uncertain or difficult

- Whether the exit message fires in a subprocess at all with the default
  `DEBUG_AUTOCLOSE` level, or only under some setting - the subprocess
  test is worthless unless it fails before the fix.
- Whether a page object surviving in a local after the loop keeps a
  reference that `close()` then has to cut.

## What actually happened that I did not expect

- **The subprocess test was hollow twice before it could fail**, and each
  time for a reason the sketch had half-named. First, the unclosed
  document is in a reference cycle and a collection freed it before exit
  in a short process: `gc.disable()`. Still passing - the document was
  provably alive at exit and nothing was printed. Second, the message
  depends on **atexit order**: pypdfium2's `destroy_lib` (registered on
  import) lists what it closes, while `weakref.finalize`'s own exit
  handler (registered on the first `finalize` anyone creates) closes the
  same objects silently. Last registered runs first, so the list appears
  only when some import created a `finalize` before pypdfium2 loaded -
  true of the command line, false of `-c`. A dummy `finalize` before the
  import made the test fail against the defect.
- Found by asking `gc.get_referrers` in a run of the real command, not
  by reasoning: the in-process reproductions all came back clean.
- `uv run --extra mineru` to reproduce installed 55 packages into the
  project venv; restored with CI's `uv sync --extra mcp --extra gui`
  before the gate, so the suite ran against what CI runs.
