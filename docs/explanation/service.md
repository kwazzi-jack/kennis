# The kennis service

Every command that reads or changes the corpus is answered by one process,
the **kennis service** for that corpus. The command line, the graphical
interface and the MCP server are its clients. You never start it yourself:
the first command that needs it starts it, and it stops by itself when it
has been idle for a while.

## How it runs

The first `kennis search`, `kennis corpus add`, `kennis gui` or agent
request finds no service and starts one, detached from the terminal that
asked. The command then waits for it to answer, which takes a moment the
first time - starting Python and loading kennis - and nothing afterwards. Every later command, window and
agent talks to the same process.

There is one service per corpus. Two commands that start one at the same
moment do not start two: the second finds the first holding the corpus and
uses it.

The service listens on `127.0.0.1` only, on a port the operating system
chooses, and checks a token on every request. Its address, token and
process id are in a record in kennis's state directory. That record is how
a client finds it, and the token in it is what lets a client in, so it is
kept from other accounts on the machine: on Linux and macOS the file itself
is readable by your account alone; on Windows, which has no such file
setting, it is kept in your user profile, whose permissions do the same.
On every system an administrator can read it, as they can read anything of
yours.

It stops after `service.idle_minutes` (30 by default) with no task queued
or running, no request in progress and no window open. The next command
starts it again.

```
kennis service status   # whether it runs, where, and its unfinished tasks
kennis service stop     # stop it now, unless it is running a task
```

`kennis service stop` and the interface's **Quit** both refuse while a task
is queued or running. The service also stops when the operating system
asks it to (`SIGTERM`), under the same condition.

## Tasks wait their turn

A write - an add, an index build, a sync, a note - is a **task** in the
service. A task that arrives while another is running waits rather than
being refused: `kennis corpus add` says what it is waiting behind and then
carries on. Tasks that cannot interfere run side by side: an index build
does not hold up a note, and a project's bundle has its own queue.

## Cancelling a task

Ctrl-C on a command cancels its task, and the command waits for it to stop
and says `Cancelled: nothing was changed`, exiting with status 130. In the
interface, a running or waiting task's panel has a **Cancel task** button.

A task stops at its next step - the next document, the next page, the next
progress report - and a PDF being converted by MinerU is stopped at once.
Until then it has written only in its copy of the collections (see below),
which is thrown away, so the corpus is exactly as it was. Once a task has
begun to place its changes in the corpus it finishes, and reports what it
did; a cancel that arrives then is too late to take effect. A task
cancelled while it waits for another never begins.

An index build is the one exception to "nothing". Each collection's index
is swapped in whole, so one finished before the cancel is a correct index of
the corpus and is kept, and the message names it: `Cancelled: the docs index
was finished first and was kept`.

To leave a task running and get the terminal back, press Ctrl-Z, which
suspends the command and not the task; `kennis service watch <task>`
follows the task again, from any terminal. Pressing Ctrl-C a second time
while a cancel is on its way stops the watching too. Windows has no Ctrl-Z;
there, open another terminal. The line under a task's progress bar says
which keys do what, with the task's id.

## A write is all or nothing

Every change to the three collections is made whole or
not at all, and every reader sees it whole or not at all.

The slow part of a write - converting a PDF, crawling a site, fetching a
paper - runs against a copy of the collections inside the corpus's `.git`
folder, made with hard links so it costs a fraction of a second. Nothing
the write does there is visible. When it finishes, the service places its
changes in the corpus and commits them, while holding every reader off for
the length of that step (a few milliseconds for a note). A read that
arrives then waits for it. A note is indexed after it is placed, so a
failure while indexing leaves the note held and says it is not yet
searchable; `kennis corpus index` builds it.

So a task that fails or is stopped part of the way through changes nothing
in the corpus. Running it again starts over. A PDF converted by the failed
attempt is not converted again: conversions are kept for a day, by the
file's content, so a retry costs only the writing.

Before it places anything, the service writes down which files it is about
to change. If the process is killed while placing - a power cut, a
`SIGKILL` - the next service to start reads that note and puts those files
back as they were, before it answers anything. The first command to reach
it then says which operation was put back, and the log records it. A
change you made by hand elsewhere in the corpus is never touched by this.

One write is refused rather than kept waiting: if another write changed the
same documents while this one was being prepared, what it prepared is out
of date. Nothing is changed, and the command or the interface says to run
it again.

## Where it reports

The service has no terminal. What it would have printed goes to the kennis
log, the same file every command writes; its location is on the `hint:`
line of any error (see [Inspect and recover](../how-to/history.md#the-log)).
A task's progress reaches the command or the window that started it as it
happens. Everything is also in the log, including a task nobody was
watching.

## Another kennis process

A command run from an older or newer kennis finds a service of another
version. If that service is idle, the command replaces it; if it is
running a task, the command says it is waiting for that task and replaces
it afterwards. Two versions never write to one corpus at once.
