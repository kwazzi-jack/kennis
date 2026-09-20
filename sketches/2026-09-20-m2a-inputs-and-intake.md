# Milestone 2, steps 1-3: inputs, intake, and the converter interface

Milestone / step: `design/plan.md`, "Milestone 2", items 1, 2 and 3.
Date: 2026-09-20

Previous sketch: `2026-09-20-m1-documents-on-disk.md`. What it left: a corpus
that can read, write, move and remove a document, derive an identifier from a
natural key, and resolve a handle against a collection - with nothing yet able
to *produce* a document from something a user names.

The plan says milestone 2 is four or five sessions. This one takes three
steps rather than two because steps 2 and 3 are one thing: intake's whole job
is to classify a source and hand the binary cases to a converter, so an
interface with nothing behind it would leave intake untestable on exactly the
path that needed the interface. Steps 4 (the notes add path), 5 (literature)
and 6 (docs) are the sessions after this.

## What I am about to do

Get from something typed on a command line to markdown in memory, without
touching the corpus. Three pieces: expanding an argument into concrete inputs,
classifying a source and converting it, and the converter interface that the
binary formats go through.

## How I expect it to work

### The tree this adds

```
src/kennis/engine/
  _glob.py               # one shell-pattern dialect, shared
  corpus/
    inputs.py            # argument -> concrete inputs
    intake.py            # source -> Converted (markdown plus provenance)
    converters.py        # the converter interface, and MinerU behind it
```

`_glob.py` sits at the engine root for the reason boepie's does: two callers
want the same dialect for different things. `corpus.inputs` expands a pattern
into the files it names, and search will filter indexed documents on their
group with the same words. `--group 'quartical/*'` and
`corpus add 'quartical/*'` selecting different sets from the same string would
be a bug nobody could see.

### `engine/_glob.py`

The .gitignore dialect, which is what anybody typing it expects: `*` and `?`
stop at a separator, `**` crosses them, and a leading `**/` is an optional run
of segments so `**/gains` matches a top-level `gains` too. `fnmatch` cannot
express this - its `*` crosses `/` - so it is a regex translation.

### `engine/corpus/inputs.py`

```
resolve_inputs(arguments, *, extra_file_types=()) -> ResolvedInputs
```

Handles only the part that is the same for every collection and needs neither
the network nor the corpus: which *files* an argument names. An arXiv
identifier, a DOI or a URL passes through untouched, because resolving one
means fetching it and that belongs to the collection's own resolver.

Two rules worth restating because they are the whole reason this module is not
left to the shell:

- **Patterns are expanded here.** A pattern the shell already expanded arrives
  as several existing paths and passes straight through; one it did not
  arrives as a literal string and is expanded here. Both routes end in the
  same list, which is what makes the command behave the same under bash, zsh
  and fish - they disagree about `**` - and on Windows, where the shell never
  expands arguments at all. It also sidesteps the argument-length ceiling.
- **A pattern matching nothing is an error, never zero files.** Quietly adding
  nothing is the one outcome that looks like success and is not.

A directory is walked behind the format accept-list, with its own subdirectory
structure mirrored onto corpus groups. Symlinks are skipped, files and
directories both: a link can point outside the tree the user named. Build and
cache directories are pruned by name - not for safety, since the accept-list
already excludes their contents, but because there is no reason to walk a
`node_modules` to discard every file in it.

What a walk declined is *kept*, not dropped. A walk that silently ignored half
a directory would leave the user believing the corpus holds something it does
not.

### `engine/corpus/intake.py`

```
detect_format(path)                     -> SourceFormat
convert_local_file(path, *, converter)  -> Converted
convert_url(url, *, client=None)        -> Converted
title_from_markdown(markdown, fallback) -> str
```

`Converted` is markdown plus everything the `source` block of milestone 1's
schema needs: `via`, `format`, `origin`, `sha256`, the retained original bytes
when asked for, and a title the source suggested.

Classification is by suffix, not by content sniffing: the formats that matter
are unambiguous by extension, and a wrong guess on a binary file is caught by
the converter anyway. Text-shaped sources are read verbatim - a `.py` file's
own bytes are already the best representation of it, and any converter would
only lose information. Code is fenced with its language, so the chunker treats
it as one block rather than reflowing it as prose. Binary documents go to the
converter.

**The accept-list and the classifier deliberately disagree**, and this is the
subtle part of the port. `detect_format` asked about an unknown suffix answers
"code", which is right when a user named one file explicitly and vouched for
it. `SUPPORTED_SUFFIXES` is the separate accept-list a directory walk works
from, because the same answer applied to a walk is catastrophic: the encoding
ladder below never fails, so a walk would ingest an ELF binary, a `.pyc` or a
git pack file as a fenced block of mojibake, silently, and index it.

The encoding ladder is utf-8, utf-8-sig, cp1252, latin-1. Latin-1 never fails,
which is the point: a text file written on a Windows box must not take the
whole batch down over one stray byte. This is also half of the plan's "never
surfaces as a `UnicodeDecodeError`" - the other half is that binary formats
never reach it.

Titles are taken from a leading `# ` heading with inline markdown unwrapped.
That is the plan's "a document whose title contains markdown emphasis produces
a clean title": MinerU renders a bold DOCX heading as `# **Title**`, and
without stripping, the markers reach the title field and from there every
search hit, every listing line, and the filename. The stripping is
deliberately narrow - emphasis and link syntax and nothing else - so an
identifier like `snake_case_name`, whose underscores are not a matched pair
around the whole word, survives intact.

### `engine/corpus/converters.py`

The interface first, because there will be two implementations and only one
exists in v0.1:

```
class Converter(Protocol):
    name: str
    formats: frozenset[SourceFormat]
    def is_available(self) -> bool: ...
    def install_hint(self) -> str: ...
    def convert(self, paths, *, page_limit=None) -> ConversionBatch: ...
```

`convert` takes a *sequence*, and that is the design rather than a
convenience. MinerU spends around twenty seconds loading its model stack
before it converts anything, so a process per document pays that toll every
time; boepie measured 41 seconds for one document alone against 88 for four in
one call. Hosted conversion will have the same shape for a different reason -
one request with several documents beats several requests.

`ConversionBatch` reports **per document**, not one pass or fail:
`markdown: dict[Path, str]`, `front_page: dict[Path, str]`, and a
`failure_reason` for the process itself. That is the plan's "a converter
failure fails only its own document": a path missing from `markdown` is that
document's failure alone, and the caller turns it into one `ItemFinished` with
`Outcome.FAILED` while the rest of the batch proceeds.

`front_page` exists because a paper's own identifier is systematically
*absent* from the converted markdown. MinerU classifies the `arXiv:1805.03410v2
[astro-ph.IM]` stamp as page furniture, and furniture is not body text; it
survives only in the content list beside the markdown, which is discarded with
the run. Carrying it out is the only reason a local PDF can be identified at
all, and milestone 2 step 5 is what consumes it. Only page one: a bibliography
offers dozens of other people's identifiers and every one is a wrong answer.

`MineruConverter` drives the CLI rather than the Python API, because MinerU
imports torch at import time and that would make every `kennis` invocation pay
for a dependency almost no command uses. A subprocess also keeps a model crash
from taking the process down with it. Timeout and `stdin=subprocess.DEVNULL`
as the project rule requires, with the timeout in two terms because the cost
has two: a startup grace for the model load, plus a per-document allowance.

`is_available()` is `shutil.which("mineru") is not None`, checked **once per
batch rather than once per file**. A folder of fifty PDFs would otherwise
produce fifty copies of the same install instructions, one at a time, over a
run that cannot succeed. That check plus `install_hint()` is the plan's "a
missing converter reports how to install it, and never surfaces as an
`ImportError`".

### The `mineru` extra, and a contradiction I have to resolve to write this

`install_hint()` has to name a real command. The plan's project file writes the
extra as `conversion = ["mineru[pipeline]>=3"]`; design section 13 writes
`Requires: uv sync --extra mineru`. I flagged this at milestone 0 and left the
extra out. It can no longer be left out, because an error naming a command
that does not exist is worse than either spelling.

I am taking the design's name, `mineru`, on two grounds: CLAUDE.md says the
design wins on behaviour and the string a user is told to type is behaviour,
and it is the spelling the settings file will print in `config show`. I will
report what it costs the lockfile, because `mineru[pipeline]` pulls torch.

### New domain exceptions

`InputError`, `ConverterUnavailable` and `ConversionFailed` in
`engine/errors.py`. `InputError` is raised rather than collected as a failed
outcome: it means the command as typed cannot be carried out, and running the
rest of the batch would leave the user to find the gap in a summary.

### The tests

Three of the plan's eight belong to this session; the other five need the add
path or literature.

- a document whose title contains markdown emphasis produces a clean title;
- a missing converter reports how to install it, and never surfaces as an
  `ImportError` or a `UnicodeDecodeError`;
- a converter failure fails only its own document.

Plus, for the two ported modules: pattern expansion under each shell's
disagreement, a pattern matching nothing, an existing path beating pattern
interpretation, directory walks and their groups, the accept-list against a
walk, symlink skipping, the encoding ladder, and fenced code.

No test touches the network or the real `mineru`. The URL path takes an
optional client so a test supplies `httpx.MockTransport`; the MinerU tests put
a fake `mineru` script on `PATH`.

## What I expect to be uncertain or difficult

- **The `mineru[pipeline]` resolution.** It pulls torch, and I do not know
  whether it resolves under `requires-python = ">=3.12"` at all, nor how many
  thousand lines it adds to `uv.lock`. If the cost is unreasonable I will say
  so rather than absorb it quietly, and the fallback is a bare `mineru>=3`.
- **Faking `mineru` convincingly.** The output discovery searches
  `output_dir/<stem>/**/*.md` and takes the largest, because the depth varies
  by version and backend. A fake that writes one file at one depth tests the
  search only shallowly, and I may find I have written a test that passes for
  a layout the real tool does not produce.
- **Whether `Converter` should be a Protocol or an ABC.** A Protocol keeps the
  engine from needing a registry that imports every implementation, which
  matters because the hosted one will want `httpx` and credentials. But
  `is_available`/`install_hint` are exactly the methods a base class would
  give for free, and I may be choosing structural typing for its own sake.
- **Where the converter is chosen.** intake needs *a* converter for a PDF, and
  in v0.1 there is one. Passing it in keeps intake honest and testable;
  defaulting to MinerU inside intake is what every call site would otherwise
  write. I expect to pass it in and provide a `default_converter()`, and to be
  unsure whether that is one indirection too many.
- **`filterwarnings = ["error"]` meeting bs4 and markdownify.** Both are
  chatty libraries, and `XMLParsedAsHTMLWarning` in particular fires on input
  that merely looks like XML. A test feeding it a fragment may fail for a
  reason that has nothing to do with the assertion.

## What actually happened that I did not expect

**The encoding ladder had a dead entry, and writing the test is what found
it.** boepie orders it `utf-8, utf-8-sig, cp1252, latin-1`, and `utf-8-sig` in
that position is unreachable: plain `utf-8` decodes a byte-order mark
*successfully*, as a leading U+FEFF, rather than failing and falling through.
So a BOM-prefixed file - which is most text written by a Windows editor -
reads with an invisible U+FEFF as its first character, which then survives into
the document's first line, its `# ` heading, its title and its filename. The
ladder here is `utf-8-sig, utf-8, cp1252, latin-1`: `utf-8-sig` decodes
BOM-less UTF-8 identically, so preferring it costs nothing and makes the entry
do the job it was added for. This is a behaviour change from the port, taken
deliberately.

**The plan's `mineru[pipeline]>=3` no longer resolves to what it names.**
mineru is at 4.0.4 and its extras are `all`, `dev`, `full`, `test` and
`torch` - there is no `pipeline`. uv accepts the requirement and warns:
`The package mineru==4.0.4 does not have an extra named pipeline`, then
resolves the base package and silently drops the extra. boepie is unaffected
because its lockfile pins a 3.x that still had it. Two further facts: the base
package already depends on torch, so there is nothing lighter to choose; and
mineru declares `requires-python <3.15,>=3.10` while kennis declares `>=3.12`
uncapped, so `uv sync --extra mineru` would fail to resolve on 3.15.

I declared `mineru = ["mineru>=3"]` - the design's spelling of the extra name,
not the plan's `conversion` - and left the backend-extra question open, because
nothing in this session runs a real conversion and the right answer depends on
which 4.x extra corresponds to what `pipeline` used to provide. The lockfile
grew from 3,138 to 4,494 lines (136 to 201 packages), and `uv sync --extra
mineru` dry-runs clean on 3.12.

**`require_available` wanted to be a free function, not a method.** My first
pass put it on `MineruConverter` and had intake's single-document path reach
for it with `hasattr`, which is the shape of a Protocol that is not carrying
its weight. `require_converter(converter, paths)` in `converters.py` builds
the one message both paths use, from `converter.name` and
`converter.install_hint()`, so the batch path and the single-document path
cannot word the same failure differently.

**Two of the predicted difficulties were real and two were not.** The
Protocol-versus-base-class question answered itself the moment the message
moved out: with `require_converter` free, the Protocol needs only
`is_available`, `install_hint`, `convert`, `name` and `formats`, and a base
class would add nothing. `filterwarnings = ["error"]` never fired on bs4 or
markdownify, including on the fragment tests - `XMLParsedAsHTMLWarning` wants
input that opens with an XML declaration, which none of these do.

The fake MinerU was the one that bit, twice, and both times in the test rather
than the code. A `\x00` sentinel in an environment variable is a `ValueError`
from `os.environ` before the subprocess is reached, and `a_pdf()` did not
create its parent directory, so the same-stem collision test failed on the
fixture rather than on the thing it was testing. The fake does exercise the
output search properly: it writes two markdown files at a nested depth and the
converter takes the larger, which is the behaviour that exists because the
real tool's depth varies by version and backend.

**Passing the converter in was the right call and cost one line.**
`convert_local_file(path, converter=None)` falls back to
`default_converter()`, so no call site has to know about MinerU, and every
test of intake uses a stub with no subprocess anywhere. The indirection I was
unsure about turned out to be what keeps the whole intake test file fast and
offline.
