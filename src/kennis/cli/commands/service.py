"""`kennis service`: see the process that owns the corpus, follow its
tasks, or stop it.

Milestone 14. The service starts itself when a command or a window needs
it and stops itself when idle, so none of these is needed in ordinary use;
they are for a person who wants to know what is running, to follow a task
they stopped watching with Ctrl-C, or to end the service before a
reinstall.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from kennis.cli import display
from kennis.cli.group import KennisGroup
from kennis.cli.sink import DisplaySink
from kennis.client import connection
from kennis.client.calls import task, unfinished_tasks, watch
from kennis.client.process import hello, stop_service
from kennis.context import existing_corpus
from kennis.protocol.progress import Began, Queued
from kennis.protocol.record import find_service

if TYPE_CHECKING:
    pass


@click.group(name="service", cls=KennisGroup)
def service_group() -> None:
    """The kennis service that owns this corpus while it runs."""


@service_group.command(name="status")
def status_command() -> None:
    """Whether the service runs for this corpus, where it listens, and the
    tasks it has not finished.

    The address is printed without its token: the token is in the
    service's record, readable by this account alone.
    """
    from kennis.render.words import JOB_KINDS, SERVICE_NOT_RUNNING, service_running

    corpus_root = existing_corpus().corpus_root
    record = find_service(corpus_root)
    if record is None:
        display.operation("Stopped", SERVICE_NOT_RUNNING)
        return
    started = record.started.strftime("%Y-%m-%d %H:%M")
    display.operation("Running", service_running(record.pid, started, record.version))
    display.detail("+", record.address)
    answered = hello(record)
    if answered is None:
        display.warning("it holds the corpus and does not answer")
        return
    if not answered.get("busy"):
        return
    for unfinished in unfinished_tasks(connection.connect(corpus_root)):
        name = JOB_KINDS.get(unfinished.kind, unfinished.kind)
        display.detail("~", f"{name}, {unfinished.state}")
        display.next_step(f"kennis service watch {unfinished.id}")


@service_group.command(name="watch")
@click.argument("task_id", metavar="TASK")
def watch_command(task_id: str) -> None:
    """Follow a task to its end: one a command stopped watching on Ctrl-C,
    which goes on in the service."""
    from kennis.render.words import JOB_KINDS, waiting_for

    link = connection.connect(existing_corpus().corpus_root)
    followed = task(link, task_id)

    def waiting(news: Queued | Began) -> None:
        if isinstance(news, Queued):
            display.note(waiting_for(news.behind, news.ahead))

    with DisplaySink() as shown:
        watch(link, task_id, returns=object, events=shown, on_waiting=waiting)
    display.operation("Finished", JOB_KINDS.get(followed.kind, followed.kind).lower())


@service_group.command(name="stop")
def stop_command() -> None:
    """Stop the service, unless it is running a task.

    A task stopped part way keeps nothing of what it did, so the service
    refuses rather than throw that work away, and keeps running.
    """
    from kennis.render.words import SERVICE_NOT_RUNNING

    corpus_root = existing_corpus().corpus_root
    record = find_service(corpus_root)
    if record is None:
        display.operation("Stopped", SERVICE_NOT_RUNNING)
        return
    stop_service(corpus_root, record)
    display.operation("Stopped", f"the kennis service, process {record.pid}")


__all__ = ["service_group"]
