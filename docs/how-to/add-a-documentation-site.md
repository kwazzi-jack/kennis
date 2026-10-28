# Add a documentation site

The `docs` collection holds the documentation of the software you use. One
command reads a whole site, or one part of it, and saves each page as a
markdown document you can search and read without a connection:

```
kennis corpus add -d https://pydantic.dev/docs/validation/2.12/
kennis corpus index --collection docs
```

The first line fetches the pages and files them under a project and a
version, here `pydantic` and `2.12`. The second makes them searchable;
adding alone does not.

This page explains what the address you give decides, how kennis finds and
reads the pages, how versions are kept apart and which one a search uses,
how to refresh or remove a version, and what kennis does to stay within
what a site permits.

## Choose the address

**The address decides which pages are taken.** kennis takes the folder the
address names, and fetches only pages whose address begins with that folder.
This keeps a project's blog, pricing and marketing pages out of its
documentation.

| you give | kennis takes |
|---|---|
| `https://pydantic.dev/docs/validation/latest/` | every page under `/docs/validation/latest/`: the whole manual, 92 pages |
| `https://pydantic.dev/docs/validation/latest/get-started/` | only the 9 pages under `get-started/` |
| `https://stimela.readthedocs.io/en/latest/index.html` | the folder holding that file, `/en/latest/` |
| `https://example.org/docs` | the folder `/docs/`, as if it ended in a slash |

So start from the root of the version you want, such as `/en/latest/` or
`/latest/`, rather than from a page inside it. Starting from a page inside
it is the right choice when you want only that section.

## Name the project

Every page of a site is filed under one project and one version, which are
folders of the `docs` collection: `docs/pydantic/2.12/Installation.md`. A
search can be narrowed to a project with `--project pydantic`.

Without `--project`, kennis names the project from the site's host: the
first part of the name, skipping `docs` and `www`.

| host | project |
|---|---|
| `stimela.readthedocs.io` | `stimela` |
| `docs.pytest.org` | `pytest` |
| `pydantic.dev` | `pydantic` |

Name it yourself when the host says nothing useful, or when two sites would
otherwise share a name:

```
kennis corpus add -d https://example.org/manual/ --project caracal
```

A project name becomes a folder, so it must be lowercase letters, digits,
`-` and `_`, beginning with a letter or a digit. It is one folder:
`stimela/cabs` is refused, because a project holds versions and nothing
else.

A page you wrote yourself can join a project too, from a file. It joins the
project's current version unless you name one:

```
kennis corpus add my-tutorial.md -d --project stimela
kennis corpus add my-tutorial.md -d --project stimela --version 2.2
```

## Name the version

**Each version of a project is kept apart**, in its own folder, so the 2.12
and 2.14 manuals can both be held and neither overwrites the other. kennis
reads the version from the address: the last folder that is a release
number, or one of the names sites give a moving version.

| address | version |
|---|---|
| `https://pydantic.dev/docs/validation/2.12/` | `2.12` |
| `https://stimela.readthedocs.io/en/latest/` | `latest` |
| `https://example.org/docs/v1.4.0/api/` | `v1.4.0` |
| `https://example.org/manual/` | none: the add is refused |

A release number has a dot or a leading `v`, such as `2.12`, `v2` or
`2.2.0rc1`. The names of a moving version are `latest`, `stable`, `dev`,
`main`, `master` and `nightly`.

When the address names no version, the add is refused and says so. kennis
does not invent one, because a label it made up would sit beside every
search result looking like a fact. Name it yourself:

```
kennis corpus add -d https://example.org/manual/ --version 3.1
```

Documentation with no versions at all - one edition, and no version in its
address, as `https://casacore.github.io/python-casacore/` - takes the
reserved name `unversioned`, which the refusal offers as a command you can
run as printed. A pack declares it as `version: unversioned`, and in the
window the Add dialog's **Use unversioned** fills the Version field:

```
kennis corpus add -d https://casacore.github.io/python-casacore/ --version unversioned
kennis pack add -d https://casacore.github.io/python-casacore/ --version unversioned
```

`--version` also overrides what the address says. Like a project, a
version becomes a folder, so it is letters, digits, `.`, `-` and `_`,
beginning with a letter or a digit.

**Prefer a pinned version to `latest`.** The pages at `/2.12/` describe
release 2.12 and do not change. The pages at `/latest/` describe whatever
was released most recently, and change under the copy you hold: kennis
keeps what the site said on the day it was fetched, and nothing tells you
when the site moved on. Add the release you actually use, and add the next
one beside it when you upgrade. A Sphinx site also states its own release
number, which kennis records in each page's frontmatter as `docs.release`,
so a page from `latest` still says which release it described.
## How kennis finds the pages

kennis tries three ways, in this order, and uses the first that works. The
earlier ways use a list the site itself publishes, so nothing is guessed.

| way | what kennis reads | used when |
|---|---|---|
| Sphinx index | `searchindex.js`, the page list a Sphinx site builds for its own search box | the site was built with Sphinx, as most Read the Docs sites are |
| sitemap | the sitemaps `robots.txt` names, or `/sitemap.xml` | the site publishes a sitemap |
| following links | each page's links, breadth first, from the address you gave | neither of the above exists |

Whichever way is used, only pages inside your folder are taken. The way
used is recorded in each page's frontmatter, under `docs.crawl.discovery`.

Two limits apply, and both can be changed:

```
--max-pages 300     # the most pages taken from one site, in every way
--max-depth 5       # how many links away from the start; following links only
```

A site with more pages than `--max-pages` is cut off at that number. Choose
a narrower address or raise the limit.

Some pages are never fetched. From a Sphinx site, its generated index and
search pages. When following links, any address that names a file which is
not a web page, such as a PDF, an image or a script.

## What is kept from each page

A documentation page is mostly navigation. kennis keeps the page's main
text and drops the menus, sidebars, breadcrumbs and footer around it. The
title is the page's own heading, and relative links are rewritten as full
addresses, so they still work from the corpus.

kennis recognises the main text of the common documentation themes: Sphinx
(including Furo, PyData and the Read the Docs theme), MkDocs Material and
Astro Starlight. On other sites it falls back to the page's `<main>` or
`<article>` element.

**A page with no recognisable main text is refused**, with the reason "the
page has no documentation in it". A login page, a bot challenge and a page
that is not found are all sent with the status "OK", so this check is the
only way kennis can tell them from documentation. If a whole site is refused
this way, its theme is one kennis does not recognise yet.

**A code block keeps the language its site marked**, so the window colours
it. Sphinx, Astro Starlight and MkDocs all write each block's language into
the page, and kennis copies that name into the block it saves. kennis never
guesses a language from the code itself: a block the site did not mark, or
marked with a name the highlighter does not know (Sphinx marks a terminal
session `pytest`), is shown uncoloured. Pages added before this change gain
their languages when they are added again or refreshed with `--refresh`.

**Figures stay on the site.** A page keeps the address of each image, but
the window does not load images from other sites, because loading one tells
that site which page you are reading. It shows a placeholder naming the host
instead.

**A saved page is read-only.** It is the site's text, and `--refresh`
replaces it with the site's text again, so kennis saves it without write
permission and an editor warns before you change it. To keep a version
with your own changes, copy it into a note of yours:

```
kennis corpus copy <id>
```

The copy has a new identifier, records the page it came from, and is yours
to edit; the window offers the same as "Copy into my notes" in the page's
menu in the tree.

## Which version a search uses

**Each project has a current version, and a search uses it.** The current
version is the one you added most recently, so adding 2.14 beside 2.12
moves your searches to 2.14. An ordinary search therefore never returns the
same passage twice from two versions. To see what is held, and to choose
another:

```
kennis corpus version                    # every project, current marked
kennis corpus version pydantic 2.12      # search 2.12 by default
```

To search other versions for one search only, name them:

```
kennis search "validators" --version 2.12            # every project holding 2.12
kennis search "validators" --version pydantic=2.12   # one project's 2.12
kennis search "validators" --version all             # every version held
```

`--version` can be given more than once, and a project you do not name
keeps its current version. A version that is not held is refused, with the
versions that are.

**Every result from `docs` names its version.** When you search several
versions, a passage whose text is exactly the same in each is shown once,
labelled with each version that holds it, such as `pydantic 2.12, 2.14`. A
passage that differs at all is shown once per version, which is where a
change between releases shows.

## Adding the same site again, and refreshing it

A page is identified by its project, its version and its path on the site.
Adding a site again therefore never makes a second copy:

- pages already held are reported as unchanged (`=`), and are **not**
  fetched again;
- pages the site has added since are fetched and added.

**A page that changed on the site is updated only when you ask.** A pinned
version never needs it. For a moving version such as `latest`, add the
site again with `--refresh`:

```
kennis corpus add -d https://stimela.readthedocs.io/en/latest/ --refresh
kennis corpus index --collection docs
```

For each page already held, kennis asks the site whether it has changed.
Where the site sent an `ETag` or a `Last-Modified` date with the page last
time, kennis sends them back, and a site whose page has not changed answers
"not modified" without sending the page again. Where the site sent neither,
the page is fetched in full and its text compared with the copy held.
Either way, a page whose text is unchanged is left exactly as it is, and
one that changed is rewritten in place: the same identifier, the same file,
the new text. The report counts it as updated, and the index needs building
again to search the new text.

Read the Docs sends these dates, so a refresh of a Sphinx site costs little
when little has changed. Some hosts send neither, and there every page is
fetched again in full. A refresh is paced like a first crawl.

## Removing a version

One command removes every page of a version:

```
kennis corpus remove --project pydantic --version 2.12
```

It says how many pages will go and asks first; `-y` skips the question. If
the version was the current one, the version whose pages were fetched most
recently becomes current; choose another with `kennis corpus version`. The pages stay in the corpus's history, as every
removal does.

## Staying within what a site permits

kennis reads a site the way a well-behaved crawler does:

- **It says who it is.** Every request carries the User-Agent
  `kennis-docs-fetch/<version>` with a link to kennis's repository, so a
  site's owner can see what is reading and find out why.
- **It obeys `robots.txt`.** This file is where a site states which
  automated access it allows. kennis checks every page against its rules
  before requesting it. A site that
  refuses to serve the file (status 401 or 403) is treated as forbidding
  everything, and one whose server fails is treated as asking kennis not to
  read it now.
- **It goes at a measured pace.** At most four requests at once, each
  starting at least 0.2 seconds after the one before, so a site sees no
  more than five requests a second. A site whose `robots.txt` names a
  `Crawl-delay` is asked one request at a time, that far apart, up to 30
  seconds. A page already held costs no request at all, unless you
  refresh it.
- **It stays in scope.** One site, one folder, and the limits above.

`robots.txt` says what automated access a site allows. It does not settle
everything, and these remain your decisions:

- **The site's terms of use** can add conditions that `robots.txt` cannot
  express.
- **The documentation's licence.** Many open-source projects license their
  documentation as they license their code, for example under MIT or a
  Creative Commons licence. A copy kept for your own searching is a
  different use from republishing the text.
- **Use by AI agents.** Some sites state, in `robots.txt`, whether their
  pages may be used as input to AI tools, in a line such as
  `Content-Signal: ai-input=yes`. kennis does not read these lines. If you
  serve the corpus to an agent (see [Serve an agent](serve-an-agent.md)),
  read the site's `robots.txt` yourself.
- **Sharing.** A [pack](author-a-pack.md) names a site's address and lets
  each person fetch the pages for themselves; it never carries the pages'
  text. Keep it that way.

This is guidance, not legal advice.

What the site learns from a crawl is listed under
[Your data](../privacy.md): your IP address, the pages requested, and the
User-Agent naming kennis. Nothing from your corpus is sent.

## In the window

**Add** has a **Documentation site** tab. Enter the site's address, and a
project name or a version if the ones kennis would read from the address
are not the ones you want; the preview says which version the pages will
be filed under, or that the address names none. Tick **Refresh held pages**
to refresh a version you already hold. **Check site** asks the site which
of the three ways kennis would use, before anything is added. The crawl
then runs in the background and reports its progress in the strip at the
bottom of the page.

In the side pane, each project's versions are folders, and the current one
is marked **current**. A version's menu offers **Search this version by
default** and **Remove this version**, which says how many pages will go
before anything does.

When some project holds more than one version, the search box has a
**Versions** list. Tick the versions to search; the choice is part of the
page's address, so Back and a shared link repeat it. A document page lists
the same page in the other versions held, under **Also held**.

## When something goes wrong

| what you see | why, and what to do |
|---|---|
| far fewer pages than the site has | the address names a folder inside the manual; start from its root |
| exactly `--max-pages` pages | the site is larger than the limit; raise it or narrow the address |
| "the page has no documentation in it" for every page | the site's theme is one kennis does not recognise yet; please report the address |
| the add is refused because the address names no version | name one with `--version`, or in the Version field; `unversioned` for documentation that has none |
| a page from `latest` is out of date | add the site again with `--refresh` |
| a search shows an older release than you expected | the current version is not the one you want; see `kennis corpus version` |
| nothing found, and the site works in a browser | the site may build its pages with JavaScript, which kennis does not run; or its `robots.txt` forbids crawlers |
