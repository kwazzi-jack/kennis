# 11d. Adding, one kind at a time

Milestone / step: milestone 11, unit 11d (`design/plan.md`), concerns #413, #414, #420
Date: 2026-10-10

## What I am about to do

Split the Add dialog into four tabs - Paper, Documentation site, File,
Several by group - each with only its own fields, each field saying
whether it is required and what an empty one becomes. Give every field
that takes a path a Browse button opening kennis's own chooser. Add the
one engine function the plan asks for: a preview of what an add would
do, without doing it.

## How I expect it to work

**One route, one contract.** Every tab posts to `/add` with the fields
the route already reads: `identifiers` (one per line), `collection`,
`title`, `group`, `identifier`, `citekey`, `project`. The Paper tab fixes
`collection=literature` and the Site tab `collection=docs` in hidden
inputs; File offers the three. So the route that every existing test
posts to stays the route, and a tab is a form that shows only its own
fields. Several by group adds `kind=group` and numbered blocks
(`group-N`, `collection-N`, `lines-N`); the route turns them into one
job that calls `operations.add_documents` once per block - each block
its own lock, add and commit, because a block can name a different
collection - and merges the reports into one `AddReport`, which
`shown_add` already lays out.

**Tabs are links.** `GET /add?kind=paper|site|file|group`; each tab is
an `<a>` with `hx-get` into `#dialog`, so it is a dialog with a script
and a page without one, as every action already is. Kind defaults to
paper.

**Another group** is a button that fetches `/add/block?index=N` and is
replaced by block N and a button for N+1 - htmx `outerHTML` on itself,
so typed blocks are untouched. Without a script, two blocks are drawn.

**The preview, engine side**, in `engine/corpus/preview.py`:

- `preview_paper(collection, asked, *, citekey, title, client)` returns a
  `PaperPreview`: what `identifier_if_reference` recognises the input as
  (the same function an add's argument goes through), whether the
  collection already holds that identity (`Uniqueness.of(...)
  .identities` - local), and for an **arXiv** identifier only, arXiv's
  title, authors and year and the citekey `derive_citekey` +
  `unique_citekey` would give against the citekeys held. Network only
  when the input is a whole arXiv identifier and not already held.
- A DOI or a bibcode is **not** looked up, and the preview says the add
  would refuse it without a file - `NoPublisherText`, the refusal the add
  itself raises. The plan says "a DOI that `resolve_doi_to_arxiv` maps
  to one" is previewed as arXiv; the add deliberately does not do that
  (`_enrich`: arXiv's `doi` field is the journal DOI, so the stored
  paper would be the preprint of what was asked for). A preview that
  promised what the add will not do is worse than none. Concern to log.
- `preview_site(url, *, project, probe, client)`: the project name
  `project_name_from_url` derives (local), and `discovery_mode` only
  when `probe` is true.
- A line check for Several by group, local only: what each line is
  (arXiv, DOI, bibcode, address, file, folder, or nothing kennis
  recognises) and whether it is held. No network per line - twenty
  lines would be twenty requests to arXiv for a check.

The preview returns refusal dataclasses where it has one, so
`render/refusals.py` words them - the preview and the add say the same
sentence.

**The preview, window side.** `GET /add/preview/paper` and
`/add/preview/site` answer fragments; the Paper field triggers on
`input changed delay:600ms`. The site probe is a button. Words in
`gui/words.py` and `render/`.

**The chooser.** `GET /browse?path=&target=` lists one directory -
folders first, then files, names only, dotfiles left out - starting at
the home directory. Read-only: it never opens a file. With a script it
renders into a panel inside the dialog; a folder is a link that lists
that folder, a file is a button, and `chooser.js` writes the chosen
path into the input named by `target`. "Choose this folder" for the
fields that take a folder (File, Several by group). Without a script it
is a page of paths to copy. Under the same token as everything else.

## What I expect to be uncertain or difficult

- Whether a `<dialog>` holding a panel that swaps on every folder click
  keeps focus sensibly. Measure in the browser.
- Testing "no network until recognised" needs the lookup patched where
  the preview module calls it, and the assertion has to be that it was
  *not called*, which an injection has to be able to break.
- The several-by-group job: an `AddReport` per block merged into one
  loses which block an outcome came from. Each `AddOutcome` names its
  input, which is probably enough.
- Listing a home directory through a web route. Loopback, token,
  read-only and names only; a native chooser shows the same names.
  Still worth a concern, because it is a new kind of thing the server
  answers.

## What actually happened that I did not expect

- **The plan's DOI preview was not built, deliberately.** The plan has a
  DOI that `resolve_doi_to_arxiv` maps to arXiv previewed as that paper;
  the add records a DOI as given and refuses one with no file, because
  arXiv's `doi` field is the journal's and resolving through it stored
  the preprint of what was asked for. The preview says the add's own
  refusal instead. Design over plan where they disagree about behaviour
  (#427).
- **`2409.1975` was an arXiv identifier.** The test that typing does not
  leak caught it: the pattern took four or five digits for any month, so
  every four-digit prefix of a modern identifier was an identifier of
  its own, and a pause while typing looked up a paper that cannot exist.
  The month now decides the length - four to December 2014, five from
  January 2015 - in the engine, so the add stops asking arXiv for those
  too (#429). Nothing in the suite depended on the lenient form.
- **htmx attributes are inherited, and the dialog closed under the
  reader.** Another group, a GET from inside the add form, inherited the
  form's `hx-target="#job"` and put block 3 in the strip; and because
  htmx reported its request against the form, `dialog.js` - which closed
  on any successful request from a `data-closes-dialog` form - shut the
  dialog. Neither was visible to the suite: both came from walking the
  window. `hx-disinherit="*"` on the form, and the dialog closes only on
  the form's own POST (#430).
- **`hx-disabled-elt="find button"` found Browse.** `find` takes the first
  match, so in a tab with a Browse button the submit button was never
  disabled - which 11b's test, matching the attribute's text, could not
  see. Every form now names `button[type=submit]`.
- **The File tab chose literature for the reader.** The first radio was
  checked, the first collection is literature, and a Markdown note was
  refused there for having no paper identifier. No collection is chosen
  now, as `corpus add` chooses none; the browser asks, and the server
  refuses a missing one (#431).
- **"Required or optional" was tested as "one of the two".** An injection
  marking every field required passed, because each row still said
  exactly one word. Restated against a hand-written list of what each
  tab requires (#373's lesson, again).
- The sketch's focus worry did not arise: the chooser panel sits inside
  the dialog, so the dialog's own focus trap covers it, and choosing a
  file returns focus to the field it filled.
- 36 injections, all caught once the two harness slips (a formatter
  reflow that left an injection unapplied, and the need/optional
  weakness above) were dealt with.
