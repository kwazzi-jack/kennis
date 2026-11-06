# Cite a passage and open it

A `kennis://` link names one passage of one document:

```text
kennis://open/k7f2a9c1x0/14
```

`k7f2a9c1x0` is the document's identifier and `14` the chunk, the same pair
a search hit prints as `id=k7f2a9c1x0 chunk=14`, and `kennis search` prints
each hit's link on the line under that. The link says nothing about where
kennis is running, so it still works after the service has stopped and
started again on another port.

On a terminal the printed link is also a hyperlink to itself, drawn
underlined: the text you see is the link, so it can be copied as it is, and
a terminal that supports hyperlinks opens it on a click (most need Ctrl or
Cmd held, and some ask first). Piped into a file, it is the text alone.

### A passage of a project's context

A file in a project's `.context/` has no identifier, so its link names the
project and the file:

```text
kennis://context/tron/2?path=decisions%2Fimaging.md
```

`tron` is this machine's name for the project (`kennis context list`), the
path is the file's place in its `.context/`, and `2` the chunk. A search
prints such a hit as `path=.context/decisions/imaging.md chunk=2`, with the
link under it. The link opens wherever the project is known by that name; a
renamed file, or a project known by another name on another machine, breaks
it. A pack's context is a copy in the project (see
[Use a pack](project-context.md#use-a-pack)), so it is linked the same way.

## Cite a passage

```
kennis cite id=k7f2a9c1x0 chunk=14
```

takes a search hit's handle as the search prints it, both words, and prints
the citation, its link and the entry for a list of references:

```text
Cited (Smirnov, Tasse and Other, 2011, sec. 2.1)
  + kennis://open/k7f2a9c1x0/14
  Smirnov, O.M., Tasse, C. and Other, A. (2011) "Revisiting ...". Available at: ...
```

Several passages can be cited at once, each as `id=... chunk=...`, as a
project's `path=... chunk=...`, as a `kennis://` link, or as any handle
`kennis read` takes (a title, a citekey, a DOI), which cites the whole
document. A project's passage is cited as a note is, by its title in quotes,
with the project and file as its reference; a `path=` that starts at
`.context/` is the project you run `kennis cite` in.

An agent does the same through the MCP tool `cite`, and is told to cite
every passage its answer relies on that way rather than writing a citation
or a link itself. Each citation comes back as a markdown link, which opens the
passage when clicked where links are shown, and as the bare `kennis://` link
for where they are not.

### Where in the document

The citation names the narrowest place the passage can be found, by the first
of these that the passage offers:

1. a figure, table or equation the passage itself holds: a caption line such
   as `Figure 3.` or `Table 2:`, or an equation numbered with `\tag{4}`. A
   sentence that mentions "Figure 3" does not count, since it points
   elsewhere;
2. the number of the section the passage is in, such as `2.1` or `A.1`, or of
   the nearest numbered section above it;
3. the heading's own words, for an unnumbered section such as "Abstract".

A passage before any heading is cited by the document alone. Page numbers are
not used yet: converting a PDF does not keep them.

Every locator is approximate. It is read from the converted text, and a
converter can misread a number, or a paper can print none.

If two passages cited together would read the same, as two passages of a note
do, each is marked as reading the same as the other, because their links open
different places.

### The style

Citations are formatted by a [CSL](https://citationstyles.org) style:
Harvard (Cite Them Right) unless you name another. Any `.csl` file works,
such as one from the [Zotero style repository](https://www.zotero.org/styles):

```
kennis config set literature.citation_style ~/styles/monthly-notices-of-the-royal-astronomical-society.csl
```

A note is not formatted by the style. It has no author or date, so it is
cited by its title in quotes.

## Open a link or a handle

```
kennis open kennis://open/k7f2a9c1x0/14
kennis open smirnov2011 --chunk 14
```

Either form opens the kennis window at the document, with the passage marked
and scrolled to. The second takes anything `kennis read` takes: an
identifier, a title, a citekey or a DOI. The service is started if it is not
running. `--no-browser` prints the address instead of opening it.

If a kennis window is already open, the passage is shown in it rather than in
a new tab: in the kennis tab you used last, or the one opened last. The tab
changes where it is; most browsers do not let a page bring itself to the
front, so you may need to switch to it. A new tab opens only when no kennis
window answers within two seconds, for instance when none is open or the
browser has put the tab to sleep.

The passage is marked only while the collection's index is up to date, as
for a search hit; otherwise the document opens unmarked.

## Make a clicked link open kennis

```
kennis link register
```

This tells your desktop, for your account only, to run `kennis open` when a
`kennis://` link is clicked:

| system | what is written |
|---|---|
| Linux | `~/.local/share/applications/kennis-link.desktop`, made the default for `kennis://` in `~/.config/mimeapps.list` |
| Windows | the key `HKEY_CURRENT_USER\Software\Classes\kennis` |
| macOS | nothing yet: only an installed application can claim a link there, which kennis does not build |

Once registered, a link opens kennis from a terminal that shows links (GNOME
Terminal, Warp, the terminal in VS Code), from Claude Code's answers, and
from anything else that hands an unknown kind of link to the system. VS Code
asks once whether to trust it.

The registration runs this installation of kennis by its full path. Run the
command again after moving the installation, and run

```
kennis link remove
```

before uninstalling kennis: `uv tool uninstall` removes nothing outside the
tool's own folder. `remove` takes away only what `register` wrote, and leaves
a `kennis://` handler that another program registered alone.

A link opened from a click reports a failure, such as a document that has
since been removed, only in kennis's log, because there is no terminal to
print it in.

## When kennis runs on another machine

A clicked link is opened by the computer you are sitting at. If kennis and
the agent run on a machine you reached over `ssh`, the link arrives at your
own computer, which does not hold that corpus. Run `kennis open` with the
link on the machine kennis runs on, with `--no-browser`, and open the
address it prints through a forwarded port, as for
[`kennis gui`](the-interface.md#a-browser-tab).
