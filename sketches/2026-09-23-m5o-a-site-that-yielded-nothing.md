# A documentation site that yielded no pages says so

Milestone / step: found while writing the README's usage section, before
tagging v0.1.0.
Date: 2026-09-23

Previous sketch: `2026-09-23-m5n-remember.md`.

## What I am about to do

Make `kennis corpus add -d <url>` say something when discovery returns no
pages. It currently prints `Added 0 documents in 864ms` and exits 0.

Measured, against a real site:

| argument | mode chosen | path prefix | pages |
|---|---|---|---|
| `https://docs.astropy.org/en/stable/io/fits/index.html` | sitemap | `/en/stable/io/fits/` | 0 |
| `https://docs.astropy.org/en/stable/` | sphinx | `/en/stable/` | 1433 |

So the feature works and the deep URL does not, and the difference is
invisible. A person cannot tell from the output whether the site has no
pages, the prefix excluded all of them, the probe chose the wrong mode, or
the fetch failed.

## How I expect it to work

`_pages_of_site` already has everything needed at the moment it knows: the
mode `discover_pages` settled on, the prefix it derived, and that
`found.pages` is empty. One `Diagnostic` at `Severity.WARNING` emitted there,
carrying those two facts.

The words are `render/`'s, so the diagnostic states the facts and the CLI's
existing diagnostic path prints them - the engine names, it does not phrase
(#81). But `Diagnostic.message` is one of the three exceptions: it is a
`KennisError`-shaped message. The existing calls in `add.py` pass a sentence,
so this one does too rather than inventing a second mechanism for one case.

Exit code stays 0. A site that publishes nothing under the prefix asked for
is not a failure of the command, and `corpus add` of several arguments must
not fail wholesale because one of them was empty.

I am *not* changing which mode is probed, or adding a fallback from a sitemap
that matched nothing to a crawl. That is a behaviour change with its own
design question - whether a mode that finds nothing should be retried as
another - and it belongs in its own unit of work.

## What I expect to be uncertain or difficult

1. Whether the diagnostic reaches the terminal. `add_docs` takes a sink and
   the CLI's `reporting()` subscribes to it, but the diagnostics I have seen
   printed so far came from `_report_problems` at the start of an add rather
   than from the middle of one.
2. Whether `found.path_prefix` is the right thing to name. It is derived
   rather than given, so it is the surprising half of the answer - but if it
   is `None` for some modes the message has to read sensibly without it.

## What actually happened that I did not expect

### The silence was the smaller of the two defects

Writing the usage section meant running `corpus add -d` against the site
root, capped with `--max-pages 5`. It did not finish. After three minutes I
stopped it and found that `discover_pages` passes `max_pages` to the generic
crawl and **not** to `_sphinx_pages`, which takes no such argument. So the
limit was ignored in the one mode that most needs it: a crawl walks links and
stops when it runs out of them, but a Sphinx site hands over a complete list
of every page it publishes, and nothing else bounds the fetch that follows.

`--max-pages 5` against astropy enumerated all 1433 pages and began fetching
every one of them, at the polite delay, which is about seventy minutes of
somebody else's bandwidth for a request to read five pages.

That is worse than the silence this sketch was written about. An option that
is ignored is a stronger claim broken than an outcome that is unexplained,
and it is aimed at a third party rather than at the user. Both are fixed
here: the cap is applied after the robots filter, so it counts pages that may
actually be fetched, and the same real command now reads

    Added 5 documents in 16.6s

### Both uncertainties were unfounded

The diagnostic reaches the terminal through the existing `reporting()` sink
with nothing added, and `found.path_prefix` is a plain string in every mode,
so the `beneath` fallback for `None` is defensive rather than needed.

### What this says about the release

Two defects in one headline feature, both found by running a command against
a real site while writing documentation, with 1423 tests green. Neither was
reachable from the fixtures: `sphinx_site()` serves two pages, so a cap of
300 was never tested against a site that exceeded it, and no fixture served a
site that yielded nothing at all. The suite tested that discovery works, not
that its bounds bind.

The general form is the one this project keeps meeting - fixtures share a
property with each other that real input does not have - and the general
answer is the same: run the command. It is now the sixth and seventh
instances.
