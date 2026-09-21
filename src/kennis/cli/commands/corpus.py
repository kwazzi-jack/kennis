"""`kennis corpus`: the commands that read a corpus, and the one that makes one.

A command chooses **what** to say; `kennis.render` says it. A command that
builds its own sentence is the thing concern #81 was spent removing.
"""

from __future__ import annotations

from pathlib import Path

import click

from kennis.cli import display
from kennis.cli.context import Context, resolve_context
from kennis.cli.group import KennisGroup
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.errors import CorpusNotFound, KennisError
from kennis.engine.history.outofband import detect_changes
from kennis.engine.history.repository import Repository, initialise_corpus
from kennis.engine.locking import corpus_lock
from kennis.render.words import count_of, describe_change


@click.group(name="corpus", cls=KennisGroup)
def corpus_group() -> None:
    """The machine-global document corpus."""


@corpus_group.command(name="init")
def init_command() -> None:
    """Create the corpus and start its history."""
    context = resolve_context()
    initialise_corpus(context.corpus_root)
    display.operation("Created", f"corpus at {context.corpus_root}")


@corpus_group.command(name="status")
def status_command() -> None:
    """What the corpus holds, and what has changed since kennis last looked."""
    context = _existing_corpus()

    total = 0
    for name in COLLECTION_NAMES:
        facts = Collection(root=context.corpus_root, name=name).survey()
        total += len(facts)
        unreadable = [fact for fact in facts if fact.problem]
        display.operation(name.capitalize(), count_of(len(facts), "document"))
        for fact in unreadable:
            # Read through `survey`, the lenient reader, on purpose:
            # `DocumentInvalid` names this command as its resolution, so a
            # status that used the strict reader would die on exactly the
            # corpus it exists to diagnose. Concern #21.
            display.detail("!", f"{fact.md_path.name}: {fact.problem}")

    if total == 0:
        display.note("the corpus has no documents yet")

    # No index yet is not an error and must not read like one.
    display.note("the corpus has not been indexed yet")

    repository = Repository(context.corpus_root)
    for change in detect_changes(repository):
        display.detail("~", describe_change(change))


@corpus_group.command(name="list")
@click.option(
    "--collection",
    type=click.Choice(COLLECTION_NAMES),
    help="Only this collection. All three by default.",
)
def list_command(collection: str | None) -> None:
    """Every document in the corpus."""
    context = _existing_corpus()
    shown = 0
    for name in [collection] if collection else list(COLLECTION_NAMES):
        for document in (
            Collection(root=context.corpus_root, name=name).contents().documents
        ):
            shown += 1
            display.detail(" ", f"{document.id}  {document.md_path.name}")
    if shown == 0:
        display.note("no documents")


@corpus_group.command(name="tree")
@click.option(
    "--collection",
    type=click.Choice(COLLECTION_NAMES),
    help="Only this collection. All three by default.",
)
def tree_command(collection: str | None) -> None:
    """The corpus as the directories it really is."""
    context = _existing_corpus()
    for name in [collection] if collection else list(COLLECTION_NAMES):
        root = context.corpus_root / name
        if not root.is_dir():
            continue
        display.operation(name.capitalize())
        for path in sorted(root.rglob("*")):
            if path.name.startswith("."):
                continue
            depth = len(path.relative_to(root).parts) - 1
            marker = "/" if path.is_dir() else ""
            display.detail(" ", f"{'  ' * depth}{path.name}{marker}")


def _existing_corpus() -> Context:
    """The context, refusing early if there is no corpus to act on.

    Checked here rather than left to the first engine call, so every command
    fails the same way with the same resolution rather than each one
    discovering it somewhere different.
    """
    context = resolve_context()
    if not (context.corpus_root / ".git").is_dir():
        raise CorpusNotFound(
            f"there is no kennis corpus at {context.corpus_root}",
            resolution="kennis corpus init",
        )
    return context


__all__ = ["KennisError", "Path", "corpus_group", "corpus_lock"]
