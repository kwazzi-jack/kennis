"""`kennis setup`: the settings, the corpus and an agent, in one walk (#682).

Each step is skipped when it is already done, and says so, so running it
again is safe. Packs and a project's context are described at the end and
never offered (Brian, 2026-11-17: offering them reads as advertising, and
whoever runs this has probably read how kennis works).
"""

from __future__ import annotations

from pathlib import Path

import click

from kennis.cli import display
from kennis.cli.group import KennisCommand

# The agents the walk can connect, as the reader types them.
_CLAUDE_CODE = "claude-code"
_OTHER = "other"
_NONE = "none"
_INDENT = "  "


@click.command(cls=KennisCommand, name="setup")
def setup_command() -> None:
    """Set kennis up: the settings, the corpus, and an agent to serve.

    Safe to run again: the settings are kept unless you ask to change them,
    an existing corpus is kept, and an agent already serving kennis is left
    as it is.
    """
    _settings_step()
    _corpus_step()
    _agent_step()
    _what_next()


def _settings_step() -> None:
    from kennis.cli.commands.config import walk_the_settings
    from kennis.engine.settings import config_path

    display.heading("Settings")
    path = config_path()
    if path.is_file():
        # On its own line: a long path wrapped across two cannot be copied.
        display.info("already written, at:")
        display.path(path)
        if not click.confirm(f"{_INDENT}change the settings?", default=False):
            display.operation("Kept", str(path))
            return
    walk_the_settings()


def _corpus_step() -> None:
    from kennis.context import resolve_context
    from kennis.engine.history.repository import initialise_corpus

    display.info()
    display.heading("Corpus")
    # Resolved after the settings are written: `corpus.root` is one of them.
    root = resolve_context().corpus_root
    if (root / ".git").is_dir():
        display.info("already a corpus, at:")
        display.path(root)
    else:
        initialise_corpus(root)
        display.operation("Created", f"corpus at {root}")


def _agent_step() -> None:
    from kennis import setting_up

    display.info()
    display.heading("Agent")
    if not setting_up.mcp_installed():
        # `kennis serve` would refuse, so there is nothing to connect yet.
        display.info("serving an agent needs the mcp extra, which is not installed")
        display.next_step(setting_up.MCP_INSTALL, note="then `kennis setup` again")
        return
    display.muted(
        "An agent - Claude Code, or any client that speaks MCP - can search, "
        "read and cite what kennis holds."
    )
    choices = [_OTHER, _NONE]
    if setting_up.claude_on_path():
        choices.insert(0, _CLAUDE_CODE)
    chosen: str = click.prompt(
        f"{_INDENT}connect",
        type=click.Choice(choices),
        default=_NONE,
        show_choices=True,
    )
    kennis = setting_up.this_kennis()
    if chosen == _CLAUDE_CODE:
        _connect_claude_code(kennis)
    elif chosen == _OTHER:
        display.info("add this to the agent's MCP configuration:")
        display.plain(setting_up.server_block(kennis))
    else:
        display.info("no agent connected; `kennis setup` again connects one")


def _connect_claude_code(kennis: Path) -> None:
    from kennis import setting_up

    if setting_up.claude_serves_kennis():
        display.info("Claude Code already serves kennis; left as it is")
        return
    answered = setting_up.add_to_claude_code(kennis)
    if answered.returncode != 0:
        display.warning(
            "Claude Code did not add kennis: "
            + (answered.stderr.strip() or f"exit status {answered.returncode}")
        )
        display.info("add this to ~/.claude.json by hand instead:")
        display.plain(setting_up.server_block(kennis))
        return
    display.operation("Connected", "Claude Code, for every project")
    display.detail("+", f"{kennis} serve")
    display.guidance("a session already open picks it up after `/mcp`")


def _what_next() -> None:
    """Each command on a line of its own under what it does, so none is
    wrapped where it cannot be copied."""
    display.info()
    display.heading("Next")
    for said, command in (
        ("The window, onto the corpus:", "kennis gui"),
        (
            "A pack brings a field's papers, documentation and notes:",
            "kennis pack install <source>",
        ),
        (
            "A project's own notes, committed with it, in its repository:",
            "kennis context init",
        ),
    ):
        display.info(said)
        display.info(f"  {display.command(command)}")


__all__ = ["setup_command"]
