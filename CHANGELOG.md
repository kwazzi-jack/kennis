## v0.12.3 (2026-10-28)

### Fix

- **literature**: look up dois one at a time, retry a refused lookup and brace an organisation

## v0.12.2 (2026-10-28)

### Feat

- cancel running tasks, write pack entries in braces and keep biblatex author lists

## v0.12.1 (2026-10-27)

### Feat

- **pack**: edit pack files from the command line, describe papers by doi and fetch in parallel

## v0.12.0 (2026-10-22)

## v0.11.0 (2026-10-21)

### Feat

- **service**: make every write to the corpus all or nothing, published whole and recovered after a crash

### Fix

- **service**: replace a service whose installed code differs from the client's, not only its version
- **service**: wait briefly for the owner lock so a starting service does not take another process's probe for a service
- **windows**: print a moved document's place with forward slashes, quote frontmatter strings in single quotes, and refuse read-only files in every test as windows does

### Perf

- **cli**: import only what a command uses, so every command starts in about half the time

## v0.10.0 (2026-10-20)

### Feat

- **context**: search every project with the packs it declares in place, and keep what kennis obtained read-only with copies as the person's own
- **service**: run one kennis service per corpus with the command line, the window and the MCP server as its clients
- **corpus**: remove, put back and return the corpus to a point in its history from the command line and the window alike
- **literature**: ask arxiv only what its robots.txt allows, as often as it asks, and refuse a test's request to a real host
- **pack**: declare notes by address or in any format kennis converts, papers by identifier alone, and read arxiv metadata from the abs page
- **docs**: file documentation by version, choose, refresh and remove versions, and keep each code block's language

## v0.9.0 (2026-10-17)

### Feat

- **config**: name each setting in the file that kennis does not read
- **gui**: run one window at a time and let a second launch open it or replace it
- **gui**: ask in a dialog when something else changed the corpus and say what changed
- **gui**: draw each link by what it does and open every link out of kennis in a new tab
- **backup**: say what encryption does not settle and link to what to check before using a cloud folder
- **settings**: offer every setting on the settings page and read the logging section that nothing read
- **gui**: name the window's keys where each control is pointed at and in the palette rather than as caps in the bar
- **brand**: draw the whole open book in the window's bar and the docs header
- **gui**: choose a pack file with kennis's own chooser and pass nothing down from a form to its controls
- **gui**: put each problem in one place and offer its ways out as controls
- **gui**: draw the status bar as one slim line whose job opens a panel, and redraw open branches after a write
- **gui**: say a paper is being looked up, and show what was found as a card
- **pack**: file a pack's papers and notes under the pack's id and move what is filed elsewhere
- **gui**: draw groups inside groups and offer every level where a group is typed
- **gui**: fill the title and citekey from a paper's preview, marked until edited
- **gui**: draw the open book beside the name in the window's bar

### Fix

- **gui**: draw the browser's own parts in the theme and style the pages that were left plain
- **docs**: read starlight and material pages and never take a card for the page
- **sync**: name each document by where it is in the corpus and commit a sync as the corpus
- **groups**: remove the spaces around each part of a group and store it that way

## v0.8.0 (2026-10-15)

### Feat

- **gui**: show the open book as the window's icon, and as the logo of the docs and readme

### Fix

- **pack**: point the scaffold's editor header at the schema where it is committed, under src/kennis/schema

## v0.7.0 (2026-10-14)

### Feat

- **gui**: give the Paper tab two ways in, Identifier and PDF, each showing and adding from only its own fields
- **gui**: offer Sync and Index as buttons where outcomes printed commands, and say on the corpus page in a word whether each collection is searchable
- **gui**: give Sync the usual foot with Sync corpus as its action, and have Index mark and choose what needs indexing
- **gui**: suggest the groups already held in every group field, and show Project on the Files tab only for docs
- **gui**: reword the window shorter and plainer, move explanations into info tips, and show each field's default as its placeholder
- **gui**: an info tip, the browser's own popover beside a label, for words that need not take a line
- **gui**: give the file picker two clear buttons, say back what was chosen, and fold the typed path away
- **gui**: choose files and folders with the browser's own picker, sent to kennis wherever it runs, and record them as uploaded
- **docs**: add a link to a file as one document instead of crawling the site it sits on
- **add**: read any text file at an address as the same file on disk would be, LaTeX and reStructuredText included
- **pack**: declare a paper by one identifier and an optional url, and have a sync say where to download what it could not fetch
- **literature**: ask, with what was found, when a fetched document names a different paper from the identifier given, instead of filing it
- **literature**: fetch a DOI's published open copy through Unpaywall when given an email, offer an accepted manuscript without taking it, and say where to download the rest
- **literature**: read arXiv's own DOI as the arXiv paper it names
- **gui**: list the corpus's own changes on the activity page, from a terminal or an agent as well as this window
- **gui**: link a paper's identifiers and fetched source, offer its citekey to the clipboard, and end the reader's breadcrumb with its title
- **gui**: let the palette find documents by title and past searches once something is typed
- **gui**: give every dialog Add's foot and anchor it near the top, and read a summary of one in the singular
- **gui**: answer an add the form can correct inside the dialog, keeping what was typed
- **gui**: put a card's title before its measures, frame every box all round instead of striping one side, and draw no bar for a title-only chunk
- **gui**: offer more from a collection whose results filled their quota
- **gui**: welcome an empty corpus with what kennis is and the first things to add
- **gui**: show an outcome's items that need the reader first and fold a long list of the rest
- **gui**: put an index button beside what needs indexing, in the strip and in add and sync outcomes
- **gui**: keep the bar's names and the pane as a drawer at phone width, keep row menus in the window, and tell state by shape
- **gui**: announce live results and job steps through status regions, add a skip link, and let the reader scroll from the keyboard
- **gui**: name every dialog field and radio group with a label, announce a note's outcome and put focus back in its box
- **gui**: set text at the reading measure by default, and give document tables padding, rules and aligned digits
- **gui**: say a keywords-only search once as a quiet notice with its way forward, and give problem, not-found and locked answers a page
- **gui**: send a content security policy that allows scripts only from kennis and remote images only where asked
- **gui**: give each collection its own measured colour across cards, groups, the pane and documents
- **gui**: let the panes and the strip be resized, collapse the strip, and draw scrollbars in the theme
- **gui**: make each hit one card whose head carries its measures, title and section
- **gui**: fit the text to the pane by default and head each passage with its section
- **gui**: set each passage in a card opened by a chevron and slide what opens
- **gui**: bring dialogs, menus, results and pages in with short css motion
- **gui**: choose each control by a rule and draw every input as the mockup does
- **gui**: draw a passage once, faded where it is cut, and grow it in place
- **gui**: open a document with its breadcrumbs, byline and an inspector of details, matches and outline
- **config**: write every setting to the configuration file and ask before replacing it
- **gui**: add a backup section to settings that backs up, tests and redraws itself
- **backup**: add an encrypted archive of the corpus with create, check and restore
- **gui**: add kennis's configuration to settings with what each change costs
- **gui**: add a settings page with this window's preferences behind a gear
- **gui**: add a palette of every action and place behind ctrl k
- **gui**: mark each document's index state in the tree and give every row a menu
- **gui**: add one kind at a time with a preview of the add and a chooser for this computer
- **gui**: show each hit's measures as bars beside one opening passage and call the lexical measure keywords
- **gui**: report what a job is doing on every page and answer a plain form with a page
- **gui**: open kennis in a browser tab and stop it from the page
- **gui**: rebuild the window as a three-pane workbench

### Fix

- reach a zero deadline on Windows's coarse clock, and make two tests hold on Windows (short temp path, racing appends)
- **gui**: space the Index dialog's count from its collection, and say docs needs a project on the Files tab
- **literature**: read a bibcode named with its scheme, as a pack sync names one
- **docs**: hold a sitemap to the page limit, as the index and the crawl are
- **docs**: wait only before a page that will be asked for, not before every page a re-crawl already holds
- **net**: end every response kennis reads at 50 MB or five minutes, so a trickling host cannot hold a command open
- **sync**: draw one bar through a sync's fetches and crawls, pace its papers for arXiv, and stop re-crawling a changed project every run
- **docs**: key a page by the site's own root or its whole path, so the address an add starts from never files it twice
- **add**: refuse a local docs page with no project before anything is crawled, and in the open form in the window
- **convert**: repair a ligature in a quoted word or between two prices
- **convert**: keep a staged filename short enough that mineru's output stays under the Windows path limit
- **config**: say the credentials file is kept in the user profile on Windows, where file modes protect nothing
- **literature**: read LaTeX accents in a BibTeX title or author as the letters they make
- **convert**: end mineru's helpers with it when a run times out, and let a locked staging file not mask the error
- **convert**: end an add on a refused API key with its remedy, and name conversion.batch_size when a run times out
- **docs**: stop reading a response past 50 MB, honour robots.txt's Crawl-delay, and say who is crawling
- **config**: name a refused setting's source and repair, and let config set mend a bad file or variable
- **corpus**: never let a kept original's name replace its document or leave its directory
- **literature**: keep an accented name's letters in its citekey, and read mineru's output as utf-8 on every platform
- **config**: refuse a word that is not true or false, write the key before the file atomically, and say when the environment overrides a set value
- **convert**: fail only the run that failed, and turn datalab's non-json replies, refused polls and refused keys into a document's refusal
- **convert**: repair only what a ligature loses, keep each letter's case, and never touch an address
- **docs**: keep every request and redirect on the site being read, resolve links where a redirect landed, and scope by directory
- **literature**: refuse arxiv's error entry and an entry for another paper as metadata, and an identifier that does not parse
- **literature**: read legacy arxiv urls whole, name the legacy archives, match hosts exactly, and parse bibtex keys and nested braces
- **gui**: leave a command's --help out of the window's remedies, where its dialogs are
- **gui**: redraw the strip and the pane after a move, and call a collection page's unknown name a collection
- **gui**: keep the search key out of the empty box, and show a setting the environment decides as decided rather than saved
- **gui**: stop fading dim text, darken the muted grey for the pane, and give every link and placeholder a token colour
- **gui**: list jobs by the order they started, since two started within one windows clock tick tie
- **corpus**: never take a source from the corpus, configuration, state or log, so adding their parent cannot copy them in
- **gui**: empty a written note's title with its text so the next note is not given it
- **context**: dump a note's and a pack file's frontmatter rather than format it, so a colon in a title stays yaml
- **gui**: accept a plain form's post, whose origin no-referrer sends as null, by its fetch site
- **gui**: give every form htmx posts a plain action and method so it posts without a script
- **gui**: keep a search the browser prefetched out of the reader's history
- **gui**: say which document deleted by hand a move from the tree put back
- **corpus**: refuse a second init as a corpus that exists, not one that is busy
- **gui**: tell the reader of a job that stopped part-way that running it again carries on
- **chunking**: open an oversized block's window with the heading above it rather than leaving the heading alone
- **gui**: draw a domain error any route raises as a page with its remedy, and keep a refused backup folder beside its field
- **gui**: say which documents deleted by hand an add, index, sync or note put back
- **gui**: move the page's revision with this window's own writes so the banner names only other writers
- **gui**: refuse a write from another page on loopback, and hold each window's token under its own port
- **gui**: run every route on a worker thread so no page or write stops the server
- **gui**: report a job that dies of an unexpected exception as failed, not finished
- **corpus**: commit what an interrupted add, move, sync or note wrote under its own name
- **history**: commit past a person's signing and hooks, and call a refused commit what it is
- **remember**: restore a hand deletion before a note is committed, and say so
- **index**: record the commit an index was built from before reading its documents
- **corpus**: keep only each index's pointer and binding in history, and rebuild the rest
- **gui**: redraw the strip and pane after a job, ask twice on ctrl-c during one, and settle four more open concerns
- **gui**: keep a job's warnings when its outcome replaces the live item lines
- **gui**: report a sync once, in the words its lines use, and call a current index up to date
- **gui**: keep the browser's own messages out of the terminal kennis prints to
- **gui**: draw the add dialog as the mockup does and keep the settings choices rule off its radios
- **gui**: draw the search box and the head of the results as the mockup does
- **gui**: scroll only the centre pane and say where the corpus stands in the strip and pane
- **gui**: open a passage as the mockup drew it, in ink, with tables as tables
- **setup**: offer each embedding backend's own model and width when it is chosen
- **setup**: write an api key under the variable its reader asks for
- **corpus**: keep each collection's index lock out of the corpus history
- **engine**: refuse a group or docs project that leaves its collection
- **gui**: post repairs to the add route, choose no candidate, and add skip and registry links

### Refactor

- **convert**: drop the page limit no caller passes
- **gui**: split the application into a router per area around one module of shared responses
- **gui**: keep the layout stylesheet in its own css file rather than a python string
- **gui**: match every job report exhaustively so a report without a page fails the type check
- **embedding**: remove the vector width setting, which the model fixes

### Perf

- **gui**: walk a collection for its page and the pane only when the corpus has changed
- **holdings**: count a corpus again only when its commit, working tree or indexes have changed

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
