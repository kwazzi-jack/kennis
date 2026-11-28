# Commands

Every command, generated from the `click` definitions kennis actually runs.
Nothing on this page is transcribed, so an option shown here is an option
the installed version accepts.

!!! note "A printed command runs as printed"
    kennis attaches the command that resolves an error to the error itself,
    and that command is meant to be copied and run without editing. The
    same rule applies to this page.

::: mkdocs-click
    :module: kennis.cli.__main__
    :command: main
    :prog_name: kennis
    :depth: 1
    :style: table

## Exit status

Every command ends with one of these statuses. A program running kennis
can act on the number; the log (`kennis.log` in the state directory) names
the status of any command that did not end with `DONE`.

| Status | Name | Meaning |
|---|---|---|
| 0 | DONE | The command did what it was asked. Adding a document already held is `DONE`: nothing needed doing. |
| 1 | FAILED | Something refused or failed: an add that was refused, a pack that does not validate, a paper a sync could not fetch or convert. The report above it says which. |
| 2 | USAGE | An option or argument could not be read. The message names it. |
| 3 | INCOMPLETE | `kennis corpus sync` did everything it could, and some of a pack's papers still need your own copy: skipped at the prompt, or not asked for because nothing was there to ask on. `kennis corpus status` names them until each is supplied. |
| 130 | INTERRUPTED | Stopped on request: Ctrl-C, a cancelled confirmation, a stopped task. |

When a sync both fails for one paper and leaves another waiting for your
copy, it exits `FAILED`, because the failure is the one your copy of a
paper cannot answer.
