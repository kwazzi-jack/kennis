# Cite a passage and open it

A `kennis://` link names one passage of one document:

```text
kennis://open/k7f2a9c1x0/14
```

`k7f2a9c1x0` is the document's identifier and `14` the chunk, the same pair
a search hit prints as `id=k7f2a9c1x0 chunk=14`. The link says nothing about
where kennis is running, so it still works after the service has stopped and
started again on another port.

## Open a link or a handle

```
kennis open kennis://open/k7f2a9c1x0/14
kennis open smirnov2011 --chunk 14
```

Either form opens the kennis window at the document, with the passage marked
and scrolled to. The second takes anything `kennis read` takes: an
identifier, a title, a citekey or a DOI. The service is started if it is not
running. `--no-browser` prints the address instead of opening it.

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
