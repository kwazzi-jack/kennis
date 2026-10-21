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
process id are in a record in kennis's state directory, readable by your
account alone. That record is how a client finds it.

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

Ctrl-C on a command stops the watching, not the task. The task goes on in
the service, and the command prints `kennis service watch <task>` to follow
it again.

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
