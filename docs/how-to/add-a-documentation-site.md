# Add a documentation site

The `docs` collection holds the documentation of the software you use. One
command reads a whole site, or one part of it, and saves each page as a
markdown document you can search and read without a connection:

```
kennis corpus add -d https://pydantic.dev/docs/validation/latest/
kennis corpus index --collection docs
```

The first line fetches the pages and files them under a project, here
`pydantic`. The second makes them searchable; adding alone does not.

This page explains what the address you give decides, how kennis finds and
reads the pages, what happens when you add a site again, and what kennis
does to stay within what a site permits.

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

Every page of a site is filed under one project, which is a folder of the
`docs` collection: `docs/pydantic/Installation.md`. A search can be narrowed
to it with `--project pydantic`.

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
`stimela/cabs` is refused, because every page of a site is filed directly
inside its project.

A page you wrote yourself can join a project too, from a file:

```
kennis corpus add my-tutorial.md -d --project stimela
```

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

Two things are not kept:

- **Figures stay on the site.** A page keeps the address of each image, but
  the window does not load images from other sites, because loading one
  tells that site which page you are reading. It shows a placeholder naming
  the host instead.
- **A code block's language is not recorded yet**, so code from a crawled
  site is shown without syntax colouring.

## Adding the same site again

A page is identified by its project and its path on the site. Adding a site
again therefore never makes a second copy:

- pages already held are reported as unchanged (`=`), and are **not**
  fetched again;
- pages the site has added since are fetched and added.

**A page that changed on the site is not updated.** To take a newer copy of
one page, remove it and add the site again; only the removed page is
fetched:

```
kennis corpus remove <handle> --collection docs
kennis corpus add -d https://pydantic.dev/docs/validation/latest/
```

There is no single command yet that refreshes a whole project.

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
- **It goes slowly.** One request at a time, at least 0.2 seconds apart,
  or as far apart as the site's `Crawl-delay` asks, up to 30 seconds. A
  page already held costs no request at all.
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
project name if the one kennis would make is not the one you want.
**Check site** asks the site which of the three ways kennis would use,
before anything is added. The crawl then runs in the background and
reports its progress in the strip at the bottom of the page.

## When something goes wrong

| what you see | why, and what to do |
|---|---|
| far fewer pages than the site has | the address names a folder inside the manual; start from its root |
| exactly `--max-pages` pages | the site is larger than the limit; raise it or narrow the address |
| "the page has no documentation in it" for every page | the site's theme is one kennis does not recognise yet; please report the address |
| a page is out of date | remove it and add the site again (see above) |
| nothing found, and the site works in a browser | the site may build its pages with JavaScript, which kennis does not run; or its `robots.txt` forbids crawlers |
