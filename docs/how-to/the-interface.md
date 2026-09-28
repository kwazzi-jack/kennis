# The graphical interface

`kennis gui` opens the corpus in a window: search, read, browse, write a
note, and run the whole of corpus management without a terminal.

```
kennis gui
```

Install the extra first, since the interface is not part of the base
package:

```
uv tool install "kennis[gui]"
```

## A window, or a browser tab

kennis serves a local web interface and then tries to show it in the
operating system's own webview - WebView2 on Windows, WKWebView on macOS,
WebKitGTK or Qt on Linux. Where the platform provides one you get a window.

**Where it does not, you get a browser tab, and that is not an error.**
Nothing installs a webview backend by default on Linux, so this is the
ordinary case there. kennis says so rather than letting a browser appear
with no explanation; a native window on Linux needs GTK or Qt bindings for
Python.

`--browser` skips the window and opens a tab directly:

```
kennis gui --browser
```

That is also the form to use over SSH with a forwarded port.

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
`.context/` bundle - are the same four `kennis search` offers, and a hit is
rendered by the same code, so what you see here and what you see in a
terminal agree line for line.

Opening a hit renders the document as HTML: headings, tables, code blocks,
and mathematics typeset with KaTeX.

**A figure is never fetched on your behalf.** A converted paper refers to
images held elsewhere, and requesting one would tell that site which
document you are reading. So remote images are blocked, the host is named,
and there is a control to load them if you want them. Conversion keeps no
image files, so a reference to a local figure is always dangling and shows
as a placeholder rather than a broken image.

## Managing the corpus

The **manage** page runs the operations that change things:

| section | what it does |
|---|---|
| Add | files, directories, URLs or identifiers, one per line, into one collection |
| Index | build the search index for one collection or all three |
| Synchronise | converge the corpus, or this project's bundle, with every installed pack |
| Packs | install a pack from the path to its `.ken.yml` |

Each one runs in the background and streams its progress as it goes, so a
document conversion or a documentation crawl shows what it is doing rather
than appearing to hang.

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

A window left open all afternoon is looking at a corpus a terminal may have
written to. Each page carries the revision it was drawn at and asks again
when the window regains focus, so you are told to reload rather than shown
something stale.

It checks **on focus, never on a timer**. A timer would spend a subprocess
a minute forever, at an interval nobody can choose correctly.
