# Documentation that reads the code

Milestone / step: v0.1.x, concern #219
Date: 2026-09-26

## What I am about to do

Build a documentation site for kennis as it stands at v0.1.1: generated
reference where the code is already the authority, and hand-written
tutorials and how-to guides where it is not.

## How I expect it to work

### The tool choice is settled by the docstrings, not by preference

Measured across the 67 modules under `src/kennis`:

    reST field lists (`:param:`, `:returns:`)      0
    Google sections (`Args:`, `Returns:`)          0
    modules opening a paragraph with `**Bold**`   38
    backticks                                   1026

kennis's docstrings are markdown essays about why a mechanism has its shape.
Sphinx `autodoc` parses a docstring as reStructuredText, where a single
backtick is a title reference and `**` is the only thing that happens to
agree - so it would mangle 1026 spans that are already correct markdown.

So **MkDocs with Material and `mkdocstrings[python]`**, which renders a
docstring as the markdown it already is. `mkdocs-click` generates the
command reference from the real `click` objects, which is what makes the
reference obey rule 4.4 - a printed command runs as printed, because it was
read off the command rather than typed into a page.

### Four kinds of page, because "tutorials and how-tos" is two of four

Diataxis, since Brian named two of its categories. The split that matters
here is that a tutorial is read once and a how-to is returned to:

    tutorial     one narrative, start to finish, on a corpus that did not
                 exist when it began
    how-to       one task, assumed corpus, no explanation
    reference    generated: the commands, the settings, the errors
    explanation  why retrieval is two legs and one fusion, why the corpus
                 is a git repository, why the engine never prints

### What is generated and what is not

Generated, because the code is the authority and a copy would drift:

    the CLI reference        `mkdocs-click` over `kennis.cli.__main__:main`
    the settings reference   the pydantic `Settings` model
    selected engine modules  `mkdocstrings`, for the surface a caller uses

**Not the whole engine.** `kennis.engine.__init__` exports nothing, so there
is no curated public API, and rendering all 67 modules would publish
internal design prose under a heading that reads as a stability promise.
The API section covers what a caller plausibly reaches for - search, the
corpus operations, the error and event types - and says in the first line
that the rest is internal.

### Where it lives

`docs/` at the repository root, `mkdocs.yml` beside `pyproject.toml`, and a
`docs` dependency group so the site's tooling is not in anyone's runtime
install. The built site goes to `site/`, which is gitignored.

**No deployment in this unit of work.** Publishing is outward-facing and the
repository is public; a workflow that deploys on push is a decision rather
than a build step, so it is offered rather than added.

### The constraint that is easy to get wrong

`design/` and `reference/` are gitignored. The reasoning in `design.md` and
`concerns.md` is the source of most of what the explanation pages will say,
and none of it can be linked to. The pages have to restate the mechanism
and its reason in their own words, for a reader who has only the public
repository.

## What I expect to be uncertain or difficult

Whether `mkdocs-click` can introspect `KennisGroup`. It is a custom
`click.Group` subclass and the commands are `rich_click` decorated; the
plugin walks `command.params` and `command.commands`, which a subclass
should leave alone, but "should" is the word that precedes the afternoon.

Whether an essay docstring renders as useful reference. `detail()`'s
docstring explains why a marker carries the colour and never says what
`marker` is. That is the right docstring for someone reading the source and
possibly the wrong one for someone reading an API page - the signature
carries the types, so the page may be fine, or it may read as a design note
with a function name on top.

Whether the ASCII rule should extend to `docs/`. The project checker covers
`src/` and `tests/`. Material's own templates are full of unicode and are
not mine; what I write should match the rest of the repository, so the
check wants widening to `docs/` and not to `site/`.

Whether a tutorial can be written that I have actually run. A tutorial that
was reasoned out rather than executed is the documentation equivalent of a
test that never failed, and this project has a rule about that.

## What actually happened that I did not expect


**The tool choice needed no judgement once it was measured.** I expected to
weigh Sphinx against MkDocs on ergonomics and to have to justify a
preference. Counting the docstrings settled it in one command: 1026
backticks and zero reST field lists means Sphinx would corrupt the existing
text, not merely render it differently. The question turned out to be a fact
about the repository rather than a matter of taste.

**`mkdocs-click` handled `KennisGroup` with no trouble**, which was the
named uncertainty. It walks `params` and `commands`, and a `click.Group`
subclass leaves both alone.

**The essay docstrings render better as reference than I expected.** The
worry was that `detail()`'s docstring explains why a marker carries the
colour and never says what `marker` is. With `separate_signature` and
`show_signature_annotations` the annotation carries the types above the
prose, and the result reads as "here is the signature, here is why it is
shaped that way" - which is more useful than a parameter table restating
what the types already say.

**A green `--strict` build proves less than it looks, and in the same shape
as everything else this project has learned.** The home page's card grid is
`<div class="grid cards" markdown>`, and without `md_in_html` its contents
pass through as literal text. That is *valid HTML*, so the build succeeded;
and because the links inside were never parsed as links, `--strict` link
checking never saw them either. A broken page and unchecked links, reported
as success. Found by reading the rendered HTML rather than the build log -
the same move that found three defects in `read` earlier this week.

**Writing the documentation found a defect in the code.** Trying to verify
one sentence - "a dimensions mismatch is an error at index time" - showed it
was false: `embedding.dimensions` is never validated, records a false width
in `binding.json`, and forces a pointless reindex when changed. Concern
#220. This is the part of documentation that is not documentation: stating
plainly what something does is a test of whether it does it.

**Two tutorial claims written from memory were wrong.** `remember` does not
index when no index exists yet, and the lexical summary line says `relevance
relative to the best lexical match`, not `... to the best hit`. Both were
caught by running the tutorial instead of composing it, which was the fourth
uncertainty and the one that paid.

**The ASCII question answered itself.** The pre-commit hook is
`types: [text]`, not a Python filter, so `docs/` and `mkdocs.yml` were
already covered and nothing needed widening.

Five injections, all caught - and one initially refused by the harness for a
non-unique pattern, which is the guard from #66 doing its job on a pattern I
had not checked.
