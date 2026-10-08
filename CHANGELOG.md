## v0.6.3 (2026-10-08)

### Fix

- **engine**: close the pdf the ligature vocabulary reads

## v0.6.2 (2026-10-08)

### Fix

- **engine**: read crlf as lf in pack digests and text sources, and check pack paths for both platforms

## v0.6.1 (2026-10-08)

### Feat

- **cli**: print pack list as a json document a provider can parse

## v0.6.0 (2026-10-07)

### Feat

- **gui**: let the reader choose which retrieval legs run
- **gui**: let the reader choose light, dark or the system
- **gui**: put the menu in a sidebar, and split the gutter from the monospace
- **gui**: say when the results are not yet for what is in the box
- **gui**: name the scope in the search box, and hold the enter key still
- **gui**: render a hit snippet, mark the query in it, and colour code
- **gui**: offer recent searches again, and raise the wordmark
- **gui**: sweep every scope by default and put the search in the address
- **gui**: give the interface a palette, a reading measure and a margin
- **gui**: open a hit at the chunk it matched, in both stores
- **engine**: lock each collection's index separately from the corpus

### Fix

- **engine**: decode git as utf-8 and keep line endings out of the platform
- **engine**: write LF and anchor a pattern at its drive on every platform
- **render**: let each retrieval leg report its own relevance band
- **gui**: render the maths in a hit snippet instead of quoting its dollars
- **render**: typeset the maths a paper actually writes
- **render**: count the note that was written, and say what happened plainly

## v0.5.0 (2026-09-28)

### Feat

- **gui**: manage the corpus from the interface, with progress and repairs
- **engine**: make a refusal a typed value and separate its remedy
- **gui**: write notes from the interface and share the write sequence
- **gui**: browse collections, index freshness and packs
- **gui**: search the four scopes and render a document as html
- **gui**: add kennis gui, a token-guarded local interface and the theme adapter
- **mcp**: add the read and remember tools, and relative document paths
- **mcp**: add the four search tools and share hit rendering with the cli
- **mcp**: add kennis serve, the generated instructions block and list_corpus
- **corpus**: fetch the papers and documentation sites a pack declares
- **corpus**: add kennis corpus sync, claim and disown for pack notes
- **pack**: add kennis context sync, pack list, pack status and pack remove
- **pack**: add kennis pack add and the pack store
- **pack**: report pack operations through the event stream
- **pack**: add kennis pack init and kennis pack update
- **pack**: add kennis pack validate
- **pack**: add the ken.yml schema and its published json schema

### Fix

- **gui**: drop pywebview's backend probe tracebacks and explain the browser fallback
- **context**: follow a pack file the user hid rather than duplicating it
- **pack**: report files no include matched and declarations that ship nothing
- **display**: give the skipped and failed markers their own theme roles

### Refactor

- **events**: name the diagnostic condition and phrase it in render

## v0.2.0 (2026-09-25)

### Feat

- **context**: keep a bundle's index out of the repository
- **context**: add reset and a retrieval method setting for the bundle
- **context**: report what a bundle holds and whether its index is in step
- **search**: make context a fourth scope of the collection selector
- **context**: index a bundle with the corpus retrieval engine
- **context**: remember into the project's bundle rather than the corpus
- **context**: find the bundle governing a directory, and scaffold one

### Fix

- **search**: return three hits per scope by default, not five
- **history**: decide index freshness by recorded digest, not by the diff alone
- **remember**: write a chosen title into the note so a search can find it
- **search**: group results by collection so each keeps its own scale

## v0.1.1 (2026-09-25)

### Feat

- **cli**: highlight code blocks in read and search output
- **cli**: rework what search and read show, and how documents are named

### Fix

- **cli**: style headings and listings that were printing as footnotes
- **conversion**: find mineru in the environment kennis was installed into
- **cli**: correct what the config, the add report and the progress bar say

## v0.1.0 (2026-09-23)

### Feat

- **remember**: write a note from prose and index it in the same command
- **conversion**: normalise converter html and repair ligature damage from the text layer
- **conversion**: make the datalab mode a setting and report what a conversion cost
- **settings**: read an api key from a .env file in the config directory
- **conversion**: add the datalab backend and read stored credentials
- **cli**: add the config command and the guided setup
- **literature**: require a paper's text and stop resolving a doi to arxiv
- **cli**: add the search and read commands
- **cli**: add the corpus mutating commands and the display event sink
- **cli**: add the corpus read commands, logging and error handling
- **settings**: add the settings layer and the corpus lock
- **history**: add corpus history and document restore
- **history**: detect and resolve changes made outside kennis
- **history**: derive index freshness from the commit it was built from
- **history**: add the git wrapper and corpus initialisation
- **rag**: add ranked search with reciprocal rank fusion and span reading
- **rag**: build and publish an index with an atomic swap
- **rag**: add the corpus loader and record source schemes correctly
- **rag**: add embedding backends and the binding-keyed vector cache
- **rag**: add chunking, the search models and the bm25 index
- **docs**: add the docs collection, site discovery and the arxiv fetcher
- **literature**: add identifiers, citekeys, arxiv metadata and the paper add path
- **corpus**: add the notes ingestion path
- **corpus**: add input resolution, format intake and the converter interface
- **corpus**: add documents on disk, surrogate ids and collection resolution
- **scaffold**: add errors, events, theme, display and the architecture tests

### Fix

- **docs**: honour the page limit for sphinx sites and report a site that yielded nothing
- **history**: read git paths as bytes and restore deletions before a write
- **intake**: convert a url by what the server sends and accept urls in literature
- **corpus**: read and resolve past a document that cannot be validated
- **corpus**: survive a document the collection cannot validate

### Refactor

- **render**: move wording out of the engine into a shared renderer

## v0.0.0 (2026-09-20)
