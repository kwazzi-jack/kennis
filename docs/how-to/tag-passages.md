# Tag passages and documents

A tag is a short name you put on a whole document or on one passage of it,
such as `calibration` or `to-cite`. A tagged passage works as a bookmark:
`kennis tags` lists what you gathered under each tag, with the link that
opens each passage, ready to cite.

## In the window

Each result has a bookmark tab on its top edge. Point at it, tab to it or
tap it, and it lists what you can do with that passage:

- **Open at this passage**, the document with the passage marked;
- **Tag this passage**, a small dialog where you type one or more tags, with
  the tags you already use offered as you type;
- **Copy passage with citation**, which puts the passage's words on the
  clipboard in quotation marks, followed by the in-text citation your
  citation style writes, with its section or page where kennis knows it:
  "The gains were solved for per antenna ..." (Smirnov and Tasse, 2011,
  sec. 2.2). The whole passage is copied, so you shorten it where you
  quote it. The entry needs the browser's clipboard, and is not shown
  without a script.

A result shows the tags on its passage under its title, and the tags on
its whole document with a dashed border. A tagged passage's tab is drawn
in its first tag's colour.

A document's details have **Copy reference**, its full entry in your
citation style, beside the citekey's **Copy**, and **Tag this document**, and list the tags on it,
whole or on a passage, each with a button that removes it. In the text, a
tagged passage has its tags at the right of its first line.

The pane lists every tag with how much it holds. A tag's page shows its
passages first, each with its opening words, its link and a way into the
document at that passage, then its documents, then anything that needs
attention, such as a detached passage. **Search within this tag** runs the
search box kept to the tag until you choose **Show everything**.

## Colours

Every tag is drawn in one of eight colours: red, orange, yellow, green,
teal, blue, purple or pink. Unless you choose one, the colour is derived
from the tag's name, so a tag keeps its colour wherever it appears. The
name is always written beside the colour, because some of these colours
look alike to people with red-green colour blindness.

Choose a colour on the tag's page, or from the command line:

```text
kennis tag calibration --colour teal
kennis tag calibration --colour '#1f5fd1'  # any colour, as a hex code
kennis tag calibration --colour auto       # back to the colour from its name
```

A colour of your own is chosen on the tag's page with **Your own**, or
given as a hex code (quoted, because a shell reads `#` as the start of a
comment). The window keeps its hue and makes it lighter on the dark theme
or darker on the light one only as far as it takes to be seen against the
page, so a pale yellow is drawn as a darker yellow on a white page. The
file keeps the colour exactly as you chose it.

The colour derived from a name comes from a checksum of the name's letters,
not from what the name means, so `calibration` and `calibrations` are not
given similar colours.

A chosen colour is kept in the same `tags.yml` as the tag. The command
line prints tag names in one colour whatever you choose, because a
terminal's colours depend on its theme.

## Tag a search hit from the command line

Name the passage as a search prints it, or by its link:

```text
kennis tag calibration id=k7f2a9c1x0 chunk=14
kennis tag calibration kennis://open/k7f2a9c1x0/14
```

Leave out the chunk to tag the whole document; any handle `kennis read`
takes will do, such as a citekey:

```text
kennis tag to-read smirnov2011
```

Give several tags at once with commas, and several passages at once:

```text
kennis tag calibration,to-cite id=k7f2a9c1x0 chunk=14 id=p3m8q2z0rt chunk=2
```

If any passage cannot be found, nothing is tagged and each problem is named,
so you fix the command once and run it again.

## Tag names

A tag is one word: no spaces and no commas, because those separate tags as
you type them. Join words with a hyphen (`phase-calibration`). Tags are
folded to lowercase, so `Calibration` and `calibration` are the same tag. A
`/` is an ordinary character: `thesis/ch3` is a tag of its own and is not
inside `thesis`.

## See what is tagged

```text
kennis tags                # every tag and how many targets it has
kennis tags calibration    # each target, its link and its opening words
```

## For an agent

An agent connected through `kennis serve` can tag and untag with the `tag`
tool when you ask it to, search within tags with the `tags` argument of
every `search_*` tool, and see the tags in use in `list_corpus`. See
[Serve an agent](serve-an-agent.md#what-tag-will-and-will-not-do).

## Search by tag

```text
kennis search "gain solutions" --tag calibration
kennis search "gain solutions" --tag calibration --tag to-cite
```

`--tag` keeps only what the tag names: every passage of a tagged document,
and a tagged passage where it is now. It does not change the order of the
results, and with several tags only what carries all of them is kept. A
tag that nothing carries is refused, so a misspelt tag is not mistaken for
a search with no results.

## Remove a tag

```text
kennis untag calibration id=k7f2a9c1x0 chunk=14
```

## When a passage changes

kennis finds a tagged passage again by its words, not only by its chunk
number, because chunk numbers change when a document is edited, a docs page
is refreshed or kennis chunks text differently. If the words are still in
the document, the tag follows them, and `kennis tags` prints the passage's
link where it is now.

If the words are gone, the tag is listed as **detached**. kennis does not
move it to a nearby passage or widen it to the whole document, because a
bookmark that moved without telling you would point you at text you did not
choose. `kennis tags` prints the `kennis untag` command that removes it; tag
the passage you want instead.

A tag on a document that is not in an index is listed as not checked, since
there is nothing to compare the words with. `kennis corpus index` (or
`kennis context index` in a project) resolves it.

## Where tags are kept

- Tags on the corpus are in `tags.yml` at the corpus root. kennis commits
  every change to it, so it has history and is included in backups.
- Tags on a project's `.context/` files are in `.context/tags.yml`. kennis
  writes it and leaves it for you to commit with the project, so the
  project's collaborators see the same tags.

Both files are plain YAML, listed by tag, and can be edited by hand. A tag
with a chosen colour is written as `colour:` and `targets:` under its name;
any other tag is its list of targets. Each passage's chunk number is
rewritten to where its words are now whenever the file's tags change, and
the corpus's after every `kennis corpus index`, in the index's own commit.
A file kennis cannot read is reported with its path and left as it is.
