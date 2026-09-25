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
