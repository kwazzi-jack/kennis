# The reader chooses which legs run

Milestone / step: v0.7b, retrieval reporting
Date: 2026-09-29

## What I am about to do

v0.7a made each leg report its own band. This is the other half of
the option Brian chose: a control that says which legs run at all.

The engine has had this since milestone 1. `sweep` takes
`mode: str | None`, `kennis search --mode` passes it, and
`_runnable` degrades it per index when there is no dense leg to
run. Nothing is being added to the engine. What is missing is that
the window has no way to say it, and the address has no place to
carry it.

## How I expect it to work

**The words are the band's words.** The bands say `lexical:` and
`meaning:`; the selector must say the same, or a reader learns two
vocabularies for one distinction. `bm25`, `dense` and `hybrid` are
the engine's names for the mechanisms and stay in the engine.

    value      shown as
    ""         As configured
    hybrid     Lexical and meaning
    bm25       Lexical only
    dense      Meaning only

**The default is the empty value and it is not "hybrid".** `sweep`
with `mode=None` lets each scope use its own setting, and the
bundle's is lexical *by design* - design section 13, because a
dense bundle index costs what `retrieval.context_method` exists to
avoid. Sending `hybrid` for a reader who touched nothing would ask
the bundle for a leg it deliberately does not have, land `context`
in `Sweep.degraded`, and print "the context index has no dense leg,
so this ran as a lexical search" - which
`test_a_context_search_does_not_report_a_missing_dense_leg` exists
to say is wrong. When the reader *does* choose `dense`, the same
warning becomes correct, because then they asked.

**The mode is in the address, like the scope.** `/?q=&scope=&mode=`
on both routes, `HX-Push-Url` carries it, so Back, reload and a
shared link reproduce the search with no client state. Concern
#340 is the reason the header names the page rather than the
fetched URL, and that stays.

**An unknown mode is named, not ignored.** Parallel to
`unknown_scope`: it becomes `context["problem"]` and the search
does not run. `retrieval.as_mode` raises `SettingsError` whose
resolution is `kennis config get retrieval.corpus_method`, which is
the wrong remedy for someone who edited a URL, so the window checks
against its own offered values the way `_theme_choice` does.

**The history records it.** `Search.mode`, and `shown_recents`
composes it into the `href` so offering a search again reproduces
the one that ran. It is shown in the detail line only when it is
not the default, because "everywhere, 9+ hits, as configured" is
three facts where two were asked for.

`recent()` reads the field with a default rather than requiring it.
The project writes no migrations and keeps no compatibility shims,
but this is the user's own data and the alternative is that adding
a column silently empties their history - `recent()` swallows a
`KeyError` and returns nothing.

**Two selects in one form.** `hx-trigger` names
`change from:select[name=scope]`; it needs the mode's too, by name
rather than `from:select`, because htmx resolves that selector
against the document and the theme control in the sidebar is a
`select`. `searching.js` compares `#answered`'s `data-query` and
`data-scope` against the form to decide whether the results are
stale, so it needs `data-mode` as well or changing the mode shows
no indicator.

## What I expect to be uncertain or difficult

Whether "As configured" is the right first option. It is accurate
and ordinary English, but it describes kennis's state rather than
the reader's intent, which is the one thing `gui/words.py`'s rule
says not to do. The alternative is to drop it and make `hybrid` the
default, which is wrong for the bundle for the reason above. I
expect to keep it and be uneasy.

Whether a mode belongs in the collapse rule. `_same_search` ignores
the scope deliberately - changing it re-runs one search rather than
making two - and the same argument applies to the mode. But the
scope argument rests on the 400ms box, and the mode is not typed.
I expect to treat it like the scope and to find out from the tests
whether that reads oddly in the list.

Whether the degraded warning now fires where it did not. Choosing
`dense` or `hybrid` explicitly makes it correct for the bundle, so
the existing test that asserts it stays silent has to keep passing
for the default path and a new one has to assert it *speaks* on the
chosen path. If I only write the second, I will not have tested the
thing that matters.

## What actually happened that I did not expect


Two of the three worries came out the other way round, and a third
thing turned up that was nothing to do with the mode.

**"As configured" was right and the unease was misplaced.** The
alternative - make `hybrid` the default - is not merely wrong for
the bundle, it is wrong *visibly*: `corpus_method` defaults to
`hybrid` and the machine this runs on has an embedding backend, so
the two look identical on a corpus and differ only on the bundle,
which is exactly where a mistake would be hardest to see.

**The mode does belong in the collapse rule**, and the test that
said so was worth nothing until it was rewritten. Recording twice
in a row is collapsed by the *typing* rule, so an exact-repeat rule
that kept entries differing in mode changed nothing and the
injection into it was inert - #318's shape again. Planting an entry
older than `COLLAPSE_WINDOW_SECONDS` leaves only the rule under
test, and then the injection fails as it should.

**The degraded warning was not "now firing where it did not"; it
had never fired at all in the window.** `Sweep.degraded` has
reached the command line since milestone 1 and `_hits_context`
simply never read it, so `kennis search` printed "the notes index
has no dense leg, so this ran as a lexical search" and the page
said nothing. It mattered little while nobody could ask the page
for a dense leg. A control offering "Meaning only" that silently
returns lexical results is a control that lies, so the selector is
what made the omission matter rather than what caused it. #381.

Two tests I wrote were hollow and one subject was uncovered, all
three found by injection and none by reading:

- `"psychic" in page.text` passed whether or not the message named
  the mode, because the marker carries `data-mode="psychic"` either
  way. It now reads the warning paragraph and looks inside it.
- `"mode" in code` for `searching.js` passed after the comparison
  was deleted, because `select[name=mode]` and the variable it is
  read into both survive. It now asserts the comparison.
- Nothing drove the interface and then read the mode back out of
  the history; every test supplied it directly, so the one line
  passing it from the request to `history.record` was untested.

**And the thing that had nothing to do with the mode.** Walking
Back and Forward: the address said `scope=notes`, the results said
`notes`, and the scope control said `all`. htmx caches the page and
restores its own snapshot, and the snapshot does not carry the
search form, which sits outside the swapped `#hits`. This has been
true since v0.6d and no test could see it - the suite drives the
app with a client, not a browser, and a browser is the only thing
with a Back button. `hx-history="false"` makes Back and Forward
navigations the server answers, which is what #340's decision said
was happening all along. #383.

Concern #375 arrived for the second time as well: the theme test
found its control by *excluding* the options carrying `data-hint`,
so the mode's options - which have no hints - were read as the
theme's the day they appeared. Scoping by exclusion is the defect;
both tests now name their select.
