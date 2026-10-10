# 11e. Decisions

Milestone / step: milestone 11, unit 11e (`design/plan.md`), concerns #412, #420
Date: 2026-10-10

## What I am about to do

Make a refusal that needs a choice into one a reader can decide well:
each candidate identifier links to its own page, opened in a new tab
that learns nothing of kennis, nothing is chosen for the reader, and
**Skip** stands beside the repair.

And first, two defects found reading the template this unit edits:
**every repair form posts to `/manage/add`**, a route 11a removed, so
"Add it to notes instead" and "Use this identifier" have answered 404
since 11a; and the ambiguous-identity form **checks its first
candidate**, which is kennis choosing which paper this is - the thing
`repairs.py` says it never does. No test saw either: the repair test
posts its own fields to `/add` rather than reading the form the page
drew, and the "chooses none" test reads `repairs_for` and not the
template.

## How I expect it to work

**The repair form** gets `action="/add" method="post"` beside
`hx-post="/add"` - the route every Add tab posts to - and the busy-button
rule every other form has. A test reads the form's own route and fields
from the rendered outcome and submits exactly those, which is what a
browser does.

**No candidate is checked**, and the radios are `required`, so the
browser asks and kennis never picks.

**Each candidate links to its page**: `https://arxiv.org/abs/<id>`,
`https://doi.org/<doi>`, `https://ui.adsabs.harvard.edu/abs/<bibcode>/abstract`.
`gui/repairs.py` composes the address, because a template choosing by
kind would be a template deciding where a paper lives (#332's rule).
`target="_blank" rel="noopener noreferrer"`: the opened page cannot reach
back into kennis's window and is not told where the reader came from.
The value is the link text; the accessible name says it opens elsewhere.

**Skip** is a GET form beside the repairs, `hx-get="/skip"`, that replaces
the item's repairs with one sentence: nothing was added, and the rest of
the add went on. No engine change - the item was already refused. Without
a script it is a page saying the same, which is honest if not useful.

**Every response carries `Referrer-Policy: no-referrer`.** A document's
own outbound links - citations in a converted paper - would otherwise
tell the remote site the origin they were followed from. The browser's
default already withholds the path, so this states the rule rather
than relying on a default.

## What I expect to be uncertain or difficult

- Whether a DOI needs quoting in a URL path: a DOI may hold `<`, `>`,
  `#` and `?`. `doi.org` resolves percent-encoded DOIs; quote with `/`
  kept.
- Where the Skip sentence goes when the outcome is on the job page
  rather than in the strip. `closest .repairs` should hold in both.

## What actually happened that I did not expect

- **The two defects were exactly as read, and the repair had been dead
  since 11a.** Every repair form - "Add it to notes instead" on every
  refused Markdown file, "Use this identifier" on every ambiguous front
  page - posted to `/manage/add`, which answered 404. Three tests
  covered repairs and none could see it: one posted its own fields to
  `/add`, one checked `repairs_for` in Python, and one asserted that
  `/manage/add` is 404 - true, and the very thing the form was posting
  to. Each now reads the form the page drew and sends what it sends.
  The pre-checked candidate was the template contradicting `repairs.py`
  in the same way #431 was the File tab contradicting `corpus add`.
- **The 11c guard caught this unit's first stylesheet.** The Skip
  sentence took the class `.skipped`, which is the search page's row for
  a scope the sweep did not reach. Renamed `.skip-note`. The guard did
  what it was written for on its first chance.
- Measured in the browser rather than inferred: a tab opened through
  `noopener noreferrer` has no `window.opener` and an empty
  `document.referrer`. The walk did not follow a candidate to arxiv.org;
  the attributes were measured on a local link instead.
- The refusal sentence the window shows says "settle it with
  --identifier" - a command-line flag, in a window whose way out is the
  form beneath it. Not this unit's: `render/refusals.py` words the
  refusal for both front ends (#434).
- 12 injections, all caught.
