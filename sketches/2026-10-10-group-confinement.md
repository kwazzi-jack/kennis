# A group is a folder inside its collection

Milestone / step: found during milestone 11, unit 11f (the tree's Move)
Date: 2026-10-10

## What I am about to do

Refuse a group name that would put a document anywhere but inside its
collection. Found while writing 11f's Move form, which takes a group
typed by the reader: nothing anywhere checks one. Measured in a scratch
corpus before writing this:

- `corpus add -n esc.md --group ../../outside` wrote `outside/esc.md`
  beside the corpus;
- `remember "..." --group /some/absolute/path` wrote the note there.

The MCP `remember` tool passes an agent's `group` to the same code, so
an agent could write a markdown file anywhere the user can write. A
pack's `content[].group` is unchecked too, while its `source` beside it
is checked against exactly this (anchor, `~`, `..`, in both path
flavours) - and a pack is data from outside.

## How I expect it to work

One rule in `engine/groups.py`, with no imports from the rest of the
engine so the pack schema can use it:

- `group_problem(group) -> str | None`: why a group is refused, or
  nothing. Checked as both `PurePosixPath` and `PureWindowsPath`, as the
  pack's `source` is (#385, #403): an anchor (root or drive), a leading
  `~`, a `..` segment, or a segment beginning with `.` - a dot-prefixed
  name is bookkeeping to `iter_documents`, so a document filed there is
  written and then never seen again (the reason `title_filename` strips
  a leading dot).
- `checked_group(group)` raises `InputError` with that reason.
- `group_directory(base, group)` checks and joins; every join of a group
  onto a path goes through it - `add.py` twice, `moving.move_target`,
  `context/notes.py`.

And earlier, so a refusal comes before any download: `AddOptions` and
`RememberOptions` check `group` in `__post_init__`, and the pack schema
validates `group` as it does `source`.

Empty stays the top level: `""` and `None` both mean no group.

## What I expect to be uncertain or difficult

- Whether any existing test or pack fixture uses a group the rule now
  refuses (a dot segment, say). If so, that is the rule meeting a real
  case and needs a decision rather than an exemption.
- `__post_init__` on a frozen, slotted dataclass: raising is fine; it
  must not assign.

## What actually happened that I did not expect

- **Two of the four reaches were not in the sketch.** A pack's docs
  `project` is a directory name too and reached the same join unchecked,
  and so did a docs page's `--project`. Both now go through the rule.
- **`..` begins with a dot.** The dot-segment check refuses every climb
  on its own, so an injection removing the climb check was inert - but
  the reason the reader is told would have been "hidden" rather than
  "climbs out". A test now asserts each refusal's reason.
- **The joins are a second line nobody reaches.** `AddOptions` refuses a
  bad group or project on construction, so an injection at the join in
  `add.py` is inert. Kept on purpose: the join is the place a future
  writer that builds no options would pass through.
- No existing test, fixture or pack used a group the rule refuses.

