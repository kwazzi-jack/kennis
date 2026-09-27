# v0.4 unit 8c, amendment: one path convention for both kinds of read

Date: 2026-09-27

## 1. What I am about to do

Concern #299. A whole-document read names its document with an absolute
path and a chunk read names the same corpus with a path relative to the
corpus root. Make both relative.

Brian's decision, taken after the first live run of the `read_*` tools
showed the two side by side.

## 2. How I expect it to work

The two lines are built by different functions:

- `describe_document(collection, document)` from `Document.md_path`,
  which is absolute because `Document` is built by walking the
  filesystem;
- `describe_span(collection, span, title)` from
  `DocumentSpan.source_path`, which the index stores relative because
  `loaders.py::_relative` says an absolute path "makes every chunk in
  the index point at nothing the moment the corpus is moved, cloned to
  another machine or restored from a backup".

That reason is about *storage*, but it applies as well to a line a
person copies into a note, and there is a second reason that applies
only to the new caller: an absolute path under `$HOME` carries the
user's account name to a model provider, and the relative path
identifies the document exactly as well.

**The relativising rule moves into the engine's layout module** rather
than being written a second time in `render/`:

```
engine/corpus/layout.py
    relative_to_corpus(path: Path, corpus_root: Path) -> str
```

`loaders.py::_relative` becomes a call to it, and `describe_document`
gains a `corpus_root` argument and calls it too. That is the point of
putting it there: the index's convention and the rendered convention
are then the same function rather than two copies that agree today.

Both callers have the root to hand - `context.corpus_root` in
`cli/commands/search.py` and in `mcp/tools/read.py`.

**Scope is one line of terminal output.** `describe_document` has
exactly two callers, and `corpus list` and `corpus tree` print
filenames and relative paths already, so the `kennis read` provenance
line is the only place in the interface where a full filesystem path
appears at all.

The test that matters is not "the path is relative" but **the two kinds
of read name the same document the same way**: read a document whole
and read a chunk of it, and assert the two provenance lines carry an
identical path. That is the property #299 was about, and it cannot be
satisfied by one side alone.

## 3. What I expect to be uncertain or difficult

- Whether any test asserts the current absolute form. If one does it
  was asserting the defect, and changing it needs saying out loud
  rather than quietly.
- `describe_span` relativises against the corpus root, but a *bundle*
  document's span does not come from the corpus at all. `kennis read`
  refuses `--collection context` and there is no `read_context`, so I
  expect no caller to be affected - but the new argument's name should
  not promise something the context path cannot keep.
- Whether a person at a terminal loses something real. They do lose a
  pasteable path. I think that belongs in `cli/` if it is wanted back,
  not in the shared line.

## 4. What actually happened that I did not expect

**I had overstated the scope in #299, and checking it strengthened the
case rather than weakening it.** The concern said `describe_document`
was shared with `kennis read` and `kennis corpus list`. It has two
callers. And `corpus list` and `corpus tree` print filenames and
relative paths already, so the `kennis read` provenance line was not
one of several places showing an absolute path - it was the only place
in the whole interface showing one. What looked like a trade-off
against an established convention was removing the single exception to
one. Worth remembering that a concern written at the moment of noticing
can carry an unchecked claim about scope, and that the claim is the
part to verify before the decision is taken rather than after.

**No test asserted the absolute form.** Section 3 worried that one
might, and that changing it would mean a test had been asserting the
defect. None did - which is its own small finding, since it means the
`kennis read` provenance path had never been pinned by anything.

**The new argument turned out not to be new.** Section 2 expected
`mcp/tools/read.py` to thread `context.corpus_root` through to the
renderer. It did not need to: `Collection.root` *is* the corpus root,
and it is the very value `loaders.py::_relative` relativises against.
So the adapter passes `held.root` and the two kinds of read are
consistent by construction rather than by two call sites happening to
be given the same thing.

**The bundle worry in section 3 was unfounded but for a reason worth
writing down.** `describe_span` takes its path from the index, which
for a bundle is the bundle's own index, and `describe_document` is
never called for a bundle document because `kennis read` refuses
`--collection context` and there is no `read_context`. So the argument
is genuinely "the corpus root" and not "whichever root applies". If a
`read_context` is ever added that stops being true, and the name will
then be a lie rather than merely narrow.
