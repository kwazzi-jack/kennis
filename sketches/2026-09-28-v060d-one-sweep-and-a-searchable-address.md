# v0.6d: one sweep, and a search you can go back to

2026-09-28

## 1. What I am about to do

Brian: the design is right, the interface is clunky. Driving it under
Playwright rather than guessing turned that into six defects, and the
first is the worst.

1. **Search, open a hit, press Back - the results are gone.** The
   query never enters the address. `hx-get="/hits"` swaps a fragment
   in and the URL stays `/?token=...`, so nothing is bookmarkable, a
   reload loses the search, and Back lands on a form with the text
   restored by the browser and an empty list under it. Measured:
   `after Back -> query box: "gains", hits: 0`.
2. **Changing the scope does not re-run the search.** `hx-trigger`
   listens to `input[name=q]` only, so picking `literature` leaves
   the notes results on screen under a literature label.
3. **The search box is not focused.** `autofocus` is on the element
   and `document.activeElement` is `body`.
4. **Search covers one scope, defaulting to notes.** `kennis search`
   sweeps all four. From a cold start the window answers nothing
   until the reader knows to change a dropdown.
5. **A document page has no way back** - its only links are the
   figures control and two citations.
6. **`remember` leaves the text in the box** after writing it, so the
   button writes a second copy.

Decided with Brian: fix 4 by **extracting the sweep** rather than
adding a third copy of it, which closes concern #314.

## 2. How I expect it to work

### The sweep moves to `retrieval.py`

`cli/commands/search.py` holds the sweep privately: for each selected
scope, load its index or record why not, pick the mode that index can
run, search, and keep the hits per collection. #314 called this a
parallel implementation of `retrieval.mode_for` and said the right
fix was to build the sweep *from* `search_scope` - deferred at the
time because it changes the command line inside a milestone about a
different front end. This milestone is about this front end, and the
window needs the same sweep, so it moves.

What moves, and what does not:

- `Skipped`, `sweep()`, `_load`, `_why_skipped`, and the refusal when
  nothing could be searched, go to `retrieval.py`.
- **The report stays in the command line.** Grouping skips by reason,
  the margin, the ordering of groups on screen - those are how one
  front end says it. The sweep returns values.
- **`Skipped` loses its sentence.** It carries `name` and
  `resolution` today plus a `reason` string that is `"no index yet"`
  at both of its two construction sites. A value that carries the
  facts must not also carry a sentence built from them, so the words
  move to `render/` and `Skipped` keeps the name and the command.
  This is the #81 rule and the same shape as 9e's refusals.

The ordering rule comes with it: groups are keyed in `SCOPE_NAMES`
order and never sorted by best hit, because ranking groups against
each other reintroduces the cross-collection comparison that
`basis_phrase` exists to refuse.

### The search goes in the address

The page becomes a real URL: `/?q=gains&scope=everywhere`. htmx gets
`hx-push-url="true"` so a live search updates the address as it goes,
and the server already reads `q` and `scope` as query parameters, so
a reload and a Back both reconstruct the page from them without any
client state.

That is the whole fix for defect 1, and it also gives bookmarking and
sharing for free. The token is a cookie already, so it need not be in
the address for a reload to work.

**The trigger gains the select**: `changed from:select[name=scope]`
alongside the text input, so picking a scope re-runs the search.

### Everywhere is a scope

The selector gains `everywhere`, first and default. `sweep` already
returns per-collection groups, so the page renders one `.basis` line
and one list per collection that answered, and a line naming the
scopes it skipped with the command that fixes each.

That makes the window's answer the same shape as `kennis search`'s,
which is what a reader moving between the two should find.

### Getting back

A document page gains a line above the title: the collection it is
in, as a link, and - when the reader arrived from a search - the
search itself. The second needs the query, which means carrying it
in the hit's link. That is one more parameter on an href that
already carries two.

### The form clears

`remember` swaps its outcome in and leaves the textarea alone, which
is how a reader writes the same note twice. On a successful write the
form is reset; on a refusal it is not, because the text is the thing
the reader would otherwise have to type again.

## 3. What I expect to be uncertain or difficult

**Whether the command line's output survives the extraction
byte-for-byte.** `--quiet` lost six guards in a port and nothing
noticed for five milestones (#88). The sweep has an ordering rule, a
skip-grouping rule, a per-scope mode fallback and a refusal that
names the first skipped scope's own command. The test that matters
is not that the sweep returns the right values; it is that
`kennis search` prints what it printed before. I will capture its
output on the real corpus first and compare.

**`named`.** The sweep behaves differently for a scope the user asked
for by name than for one swept into: a missing index is fatal for the
first and ordinary for the second. The window's `everywhere` is never
named and its explicit scopes always are, so the flag has to cross
the boundary rather than being inferred from the count.

**`hx-push-url` and the token.** The address currently carries the
token on first load. If htmx pushes `/?q=...` without it, a reload
must still authenticate from the cookie. I think it does - the
middleware checks the cookie and the query - but a pushed URL that
locks the reader out on reload would be a bad way to find out.

**Whether `everywhere` should be the default at all.** It is what the
command line does, and it is right for a cold start. It also makes
the common case - searching the notes you just wrote - slower and
noisier. I may find the default wants to be `everywhere` only until
the reader picks something.

## 4. What actually happened that I did not expect

**The address fix was wrong in exactly the way the suite could not
see.** `hx-push-url="true"` pushes the URL htmx *fetched*, which is
`/hits?q=...` - a fragment with no page around it. Every test asked
the server for `/?q=...` and got a correct page, so the suite was
green while Back landed on a bare list of results on a blank
document. Walking the interface found it in one step. The server now
names the address with an `HX-Push-Url` response header.

Then the attribute turned out to be dead markup. An injection
removing it was not caught, and rather than weaken the test I
measured which it was (#318): removed the attribute, walked the
interface, and Back still restored the query and all nine hits -
because the header pushes regardless. Since the attribute alone
pushes the *wrong* URL, keeping it is worse than removing it: the
next reader would trust it and delete the header. Concern #340.

**Section 3 worried about the wrong thing.** I expected the risk to
be the command line's output changing byte-for-byte, and captured a
recording to compare. The output was identical. What actually broke
was a behaviour with no visible output at all: the skip *grouping*.
The pre-extraction code gave every skipped collection the shared
resolution `kennis corpus index` and grouped by it; I made the
resolution specific, `--collection <name>`, which is better per scope
and means two entries can never merge. The recording could not show
it, because Brian's corpus has nothing unindexed.

**And the test for that grouping had never been able to fail.** Its
fixture indexed notes and left one collection unindexed, and one
scope groups onto one line whatever the code does. This is the third
time in this project a fixture too small to distinguish the cases has
hidden a defect. Concern #341.

**A score is a rank, and I did not know that.** I tried to test "the
groups are never ranked by best hit" by injecting a sort on the best
hit's score. Nothing failed. Chasing whether the test was hollow
found that search fuses by reciprocal rank - `sum 1 / (60 + rank)` -
so the best hit of every group scores exactly 1/61, and sorting by it
is inert by construction. Two collections with wildly different term
frequencies both returned 0.0164; lengthening one document and adding
a second to its collection did not move it.

That is worth more than the test. **`Hit.result.score` carries no
information comparable across collections** - not "a different
scale", but a function of rank. The property had to be restated as
one that can fail: ask for the scopes in the reverse order and assert
they come back in `SCOPE_NAMES` order. My first version passed
`SCOPE_NAMES` and asserted against `SCOPE_NAMES`, so the defect
satisfied it. Concern #342.

**A PEP 695 alias is not the thing it aliases.** The extracted mode
check was written `get_args(Mode)`, and `Mode` is
`type Mode = Literal[...]`, so `get_args` returned `()`: every mode
was rejected and the refusal listing the valid ones listed none.
Silent, total, and caught only by running the real command.
Concern #339.

**What section 3 asked and the answer.** `hx-push-url` and the token:
no problem - the middleware reads the cookie, and a pushed `/?q=...`
without a token authenticates fine. Whether `everywhere` should be
the default: yes, and it is not noisier in practice, because each
group is separately ranked and headed by its own scale, so three
groups of three read as three answers rather than nine.

**What it cost to find any of this.** Sixteen injections, all caught,
found nothing the suite did not already know. The four defects in
this unit came from one recording of the real command and three walks
of the real interface.
