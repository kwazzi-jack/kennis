# 11f. The tree reports state, and is a place to act

Milestone / step: milestone 11, unit 11f (`design/plan.md`), concerns #245, #93, #101
Date: 2026-10-10

## What I am about to do

Give each document in the pane's tree its index state the way an
editor's source-control view does - quiet when all is well, a letter
and a colour when not - with a group showing the worst state beneath it
and a count, and a filter that shows only what needs attention. And make
the tree a place to act: a menu per document and per group, reachable
by right-click, by a visible button and by the keyboard.

## How I expect it to work

**State per document, from the engine.** `history/freshness.py` already
sorts every flagged path into added, changed or gone and then throws the
sets away for counts. A new `document_states(...)` returns the sets
(`DocumentStates`, paths as `document_of` names them, relative to the
corpus root), and `index_freshness` becomes counts of it - one rule, two
readers. A collection with no index at all has every document unindexed;
one whose index is unverifiable has no per-document answer, and the
tree says nothing per document rather than guessing. Unreadable
documents come from `CollectionContents.unreadable` and are listed in
the tree too, by filename - today they are a count beneath it, and a
count cannot be opened or moved.

**Three states and quiet**, in `gui/words.py`: `U` not indexed, `M`
changed since indexed, `!` unreadable; each with a sentence for its
tooltip. The letter wears a role colour (`role-warning`,
`role-changed`-ish, `role-error`) - an existing role, not a new colour.
A group's summary shows the worst letter beneath it and how many need
attention. A checkbox at the head of the branch hides quiet entries with
`:has()` - CSS, no script, so it works without one.

**The menu** is a `<details class="menu">` per row with a visible
button as its summary - focusable, opens on Enter, and a script adds
right-click (`contextmenu`) and Escape. Entries: **Open**, **Move to
group** (a small form: a group name with the collection's groups offered
in a `<datalist>`, empty for the top), **Add here** (a link to the Add
dialog's File tab with the collection and group filled in), **Index this
collection** (the existing `/index` form with the collection fixed). A
group's menu has Add here and Index. **A new group exists only once
something is in it**, so "new group" is a name typed into Move or Add,
never a folder made alone. A docs page is not offered Move: its
directory is its project, which is part of its identity (#101).

**Moving is a shared operation.** The command line computes where a
moved document lands (`_target_path`, `_holding`, `_stem`) and refuses
to regroup a docs page, inside `cli/commands/corpus.py`. The window may
not import `cli/`, so the rule moves to `engine/corpus/moving.py`
(`move_target`, raising `InputError` for docs) and the sequence - lock,
restore hand deletions, move, commit - to `operations.move_a_document`,
which both front ends call, as they already do for add and index.
`POST /move` answers htmx with the collection's branch redrawn; a plain
form gets a 303 to the collection page.

**Add here** needs the Add dialog to take `collection` and `group` in
its address and fill them in. Choosing the collection there is the
reader's choice, made by choosing the row, so it is not #431 again.

## What I expect to be uncertain or difficult

- Matching `document_states` paths to tree entries: a wrapped document
  is named by its directory, a bare one by its `.md`. The tree needs the
  same spelling from `Document`, which is `relative_to_corpus` of the
  wrapper or the file.
- `:has()` support in the headless shell; it is Chromium, so it should.
- Whether a `<details>` menu inside a `<details>` tree row toggles the
  row when clicked. The summary of the inner one must not bubble a
  toggle to the outer.
- The redrawn branch after a move: the pane's `<details>` loaded the
  branch once (`toggle once`); swapping `.branch` keeps the row open.

## What actually happened that I did not expect
- **The Move form found a hole older than the window.** A group typed
  into it went straight to `collection.path / group`, and so did every
  other writer's: `../../outside` wrote beside the corpus, an absolute
  path wrote where it named, and the MCP `remember` tool takes `group`
  from an agent. Fixed in the engine first, as its own unit
  (`2026-10-10-group-confinement.md`, #435), because the tree was only
  the newest of six ways in.
- **Two `<details>` per group, and the menu cannot live in either
  obvious place.** Inside the summary is content a summary may not hold;
  inside the folder it is hidden whenever the folder is closed. It is the
  row's own child, beside the folder, positioned at the row's right. A
  pattern-matching test read the folder as the menu, which is why the
  tests now parse the page with BeautifulSoup - already a dependency.
- **The branch inherited the pane's target.** The `<details>` the branch
  arrives in carries `hx-target="find .branch"`; every form in a menu
  would have inherited it. `hx-disinherit="*"` there, and a test. #430
  again, one level up.
- **Two fixtures could not show a defect** (#352's shape): every
  document in `botany` needed attention, so counting all entries passed;
  no fixture held a wrapped document, so naming one by its `content.md`
  passed. And none built the #245 sequence, so dropping the manifest's
  digests passed. Each found by an injection that was not caught, and
  each now has a fixture that can fail.
- **`corpus status` counts the broken file among the added** (#436): the
  tree's `U` and `!` together are status's added count. The test states
  it that way rather than pretending the sets are disjoint.
- **A moved document is unindexed** until the next index, because the
  index addresses by path (#437). Seen in the walk's dark screenshot,
  which was taken after the light walk had moved one; correct, and the
  tree is what made it visible.
- The sketch's worries did not arise: `:has()` works in the headless
  shell, a right-click on a group opens its menu without folding it, and
  the redrawn branch keeps the collection open. `:focus-visible` does not
  match a programmatic `.focus()` after a mouse click, which made the
  button look unreachable until it was measured with a real Tab.
- `filled` validated a choice that the template could not have checked
  anyway; the check was inert and is gone.
- 30 injections caught of 31; the one left was the inert check above.
