# The graphical interface

`kennis gui` opens the corpus in a browser tab: search, read, browse, write a
note, and run the whole of corpus management without a terminal.

```
kennis gui
```

## A browser tab

kennis serves a local web interface and opens it in your own browser.
There is no separate window: everything the interface does happens in
the tab.

**Closing the tab does not stop kennis.** Use **Quit** at the end of the
bar, or press Ctrl-C in the terminal that ran `kennis gui`. Quit refuses
while an add, an index or a sync is running, because stopping then would
cut the operation off part of the way through.

On a remote machine - a cluster login node, say - forward the port and
open the address on your own computer:

```
kennis gui --no-browser
```

`--no-browser` prints the address and opens nothing. Without it, a
machine with no display may start a text browser such as `lynx` in the
terminal instead.

## The address and the token

The command prints something like this and then blocks until you close it:

```text
Serving the kennis interface
  + http://127.0.0.1:41287/?token=cQ6Nr53qZECwtkvA7QyWRjowELeIlbcZkETGEwOv7Nw
The token is in the address and lasts for this run only.
```

Three things about that address are deliberate.

**It is loopback.** `127.0.0.1`, spelled out rather than `localhost`, and
never `0.0.0.0`. Your corpus is not on the network.

**The port is the kernel's choice.** A fixed port collides with whatever
else is on 8000, and - more to the point - makes the interface predictable
to find for anything else running on the same machine.

**The token is minted for this run and is not stored.** Loopback is *not*
private on a shared machine: any other process, and any other account on
the same host, can reach 127.0.0.1. Cluster login nodes have other people
on them. The token arrives once in the address and is then held in a
cookie, so it is not on every request line and not sitting in the address
bar to be copied into a chat window by accident.

Every request is checked, including one for a stylesheet and one for a
route that does not exist.

## Searching and reading

The four scopes - `notes`, `literature`, `docs` and this project's
`.context/` bundle - are the same four `kennis search` offers, and a hit's
words come from the same code, so the window and a terminal never disagree
about a title, a level or a handle.

Each hit shows its measures above its title: an icon for the measure
(keywords, or meaning), a bar of five cells and the level in words. The
bar's colour is a third way of reading the level, after the number of cells
filled and the word, so nothing depends on telling the colours apart. The
key at the head of the results says what each measure is measured against;
open it for the details. Hits are listed in the order the search ranked
them, which combines both measures by rank, so a hit with weaker bars can
be listed first.

The passage under a hit shows the part around the first match. **Show the
whole passage** opens it in place to the whole chunk, the text before and
after appearing around what was already shown, and the arrow beside the
title opens the document at that passage.

Opening a hit renders the document as HTML: headings, tables, code blocks,
and mathematics typeset with KaTeX.

**A figure is never fetched on your behalf.** A converted paper refers to
images held elsewhere, and requesting one would tell that site which
document you are reading. So remote images are blocked, the host is named,
and there is a control to load them if you want them. Conversion keeps no
image files, so a reference to a local figure is always dangling and shows
as a placeholder rather than a broken image.

## Managing the corpus

The bar along the top holds the operations that change things. Each opens
a dialog, or a page if scripts are off:

| action | what it does |
|---|---|
| Add | a paper, a documentation site, a file or folder, or several groups at once |
| Note | write a note into the corpus or this project's bundle |
| Index | build the search index for one collection or all three |
| Sync | converge the corpus, or this project's bundle, with every installed pack |
| Pack | install a pack from the path to its `.ken.yml` |

**Add has a tab for each kind of thing.** Paper has two ways in, as Zotero
has them: **Identifier** takes an arXiv ID, a DOI or an ADS bibcode and
looks it up as you type; **PDF** takes a PDF, chosen, by web address or by
path, with its identifier when the PDF does not show it or shows the wrong
one. Only the fields of the way chosen show, and only they are added from.
Documentation site takes the address of
its first page; File takes a file or a folder and asks which collection;
Several by group takes a block per group, one item per line. Every field
says whether it is required, and an optional one says what an empty field
becomes. As you type, the dialog previews what the add would do: the
paper's title and the citekey it would get, a paper you already hold, or
the reason the add would refuse. It asks arXiv only once the identifier is
complete.

**Choose files** opens your own computer's file dialog, and **Choose a
folder** sends a whole folder with its sub-folders. The files go to kennis
through the same connection as the page, so this works the same when kennis
runs on another machine behind `ssh -L`. A document added this way records
that it was uploaded, under the name it was sent with. A path typed into
the field instead is read on the computer kennis runs on, without copying;
**Browse**, in a Several by group block, lists that computer's folders.

Each operation runs in the background and reports in the strip at the
bottom of every page, so a document conversion or a documentation crawl
shows what it is doing rather than appearing to hang.

**One operation runs at a time.** A second is refused and told which one is
in the way. That is not an arbitrary limit: kennis takes one corpus-wide
lock per operation, so a second would be refused anyway.

**A busy corpus is something to try again, not an error.** If a terminal is
indexing while you press Add, the interface says the corpus is busy and
that nothing was changed.

## When an add is refused

An add can be refused for reasons that have an obvious way out, and the
interface offers it as a button rather than as a command to retype.

A paper with no arXiv identifier, DOI or ADS bibcode on its first page
cannot go to literature - it has no bibliographic identity, so its citekey
would be invented and duplicate detection would have nothing to compare.
The refusal comes with **Add it to notes instead**, with the path already
filled in. Notes is a real answer here rather than a consolation prize:
notes have no natural key by design.

A first page offering two arXiv identifiers gets one radio button per
identifier. kennis does not choose, because choosing would be deciding
which paper it is.

Where kennis cannot repair the refusal itself - a paper whose text sits
behind a publisher needs a file only you can supply - it gives the sentence
and the command, and no button that would not work.

## Noticing that something changed

A tab left open all afternoon is looking at a corpus a terminal may have
written to. Each page carries the revision it was drawn at and asks again
when the tab regains focus, so you are told to reload rather than shown
something stale.

It checks **on focus, never on a timer**. A timer would spend a subprocess
a minute forever, at an interval nobody can choose correctly.
