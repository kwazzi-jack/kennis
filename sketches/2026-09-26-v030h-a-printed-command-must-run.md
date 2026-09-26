# v0.3.0h - a printed command must run as printed

Concern #233, opened four milestones ago and never acted on. Rule 4.4 says
a command kennis prints must run as printed. #265 records three violations
of it inside milestone 7 alone: `pack validate` naming `pack update` before
it existed, `pack init` inheriting a resolution that runs but does not
help, and `pack add` naming `corpus sync` in backticks when there is no
such command. Three in one milestone with no automated guard is a recurring
defect rather than three accidents.

This is written **before** units 6 and 7 rather than after, because unit 7
is exactly where `corpus sync` and `context sync` stop being false, and
unit 6 will want to name them. Writing the guard first means the remaining
work is done under it instead of audited afterwards.

## 1. What I am about to do

One test module, `tests/test_printed_commands.py`, that finds every
`kennis ...` invocation kennis can print and asserts it resolves against
the real click command tree - the command path exists, and every long
option in the literal part is an option that command accepts.

## 2. How I expect it to work

**Collection is static, over the AST of `src/kennis/`.** A runtime approach
would only see the strings a test happened to trigger, and the whole point
is to catch the string on the path nobody runs.

The walk visits every `ast.Constant` holding a `str`, and every
`ast.JoinedStr`, in every file under `src/kennis/`. From a `JoinedStr` it
takes the literal `Constant` pieces and stops at the first
`FormattedValue`: `f"kennis pack validate {path}"` contributes
`kennis pack validate ` and the argument is not our business.

From each string it extracts candidate invocations two ways:

- the string, or a backticked span inside it, beginning with `kennis `;
- nothing else. `uv tool upgrade kennis` does not start with `kennis ` and
  is not a kennis command, so it is not a candidate.

**Resolution walks the real click tree.** `kennis.cli.__main__.main` is the
root group. For a candidate's tokens: consume leading tokens while the
current object is a `click.Group` and the token names one of its commands.
The first token that is not a subcommand ends the path. Then:

- if no token was consumed, the candidate is `kennis` alone, which is fine;
- if a consumed path is a `Group` and the remaining tokens are not empty
  and the next one does not start with `-`, that is an unknown subcommand
  and a failure;
- every remaining token starting with `--` must be in the resolved
  command's option names. A token starting with a single `-` is checked the
  same way, since click records short flags in the same list.
- a bare remaining token that is not an option is an argument, and
  arguments are not checked: their values are the caller's.

The failure message names the file, the line and the candidate, because a
guard that says "some string is wrong" costs more than it saves.

**Where the strings live.** Three producers, and the walk covers all of
them because it walks everything:

| producer | example |
|---|---|
| `resolution=` on a `KennisError` | `resolution="kennis corpus init"` |
| `display.next_step` / `display.hint` | `display.next_step("kennis corpus index")` |
| a sentence in `render/` | "... and name `kennis corpus claim <id>`" |

A placeholder like `<id>` is a bare token, so it is treated as an argument
and not checked - correct, since rule 4.4 is about the command being real,
not about the value being one.

## 3. What I expect to be uncertain or difficult

**False positives from prose.** A docstring saying "run kennis corpus index
once" would be picked up. That is arguably right - it is still a command
kennis prints, if only in `--help`. I expect a handful of hits in docstrings
and expect them all to be real commands, so the guard costs nothing. If a
docstring sentence trips it wrongly I would rather reword the docstring
than exempt docstrings, because `--help` text is printed output.

**Option names on a group versus its command.** `kennis -q corpus add`
puts a root-group option before the subcommand. I do not think any printed
string does this, but the walk has to not choke on it: a token starting
with `-` before any subcommand should be checked against the group's own
options rather than ending the path.

**The guard must fail.** Injecting a fake command (`kennis corpus frobnify`)
into a resolution string must fail it, and injecting a fake option
(`--nonexistent`) must fail it too. Both injections assert they applied.

## 4. What actually happened that I did not expect

**The first collector was too broad, and the breadth was not a nuisance -
it was a wrong model of the problem.** Reading any string that begins with
the program name gave nineteen failures, of which fifteen were the
collector's fault: `KennisError.default_message` is "kennis could not
complete the operation", and `logging.info("kennis %s", __version__)` is a
format string. The fix was not a filter but a distinction I had not drawn
in section 2: a string is a command either because the **site** says so -
a `resolution=`, a `default_resolution`, `display.next_step`,
`display.hint` - or because it is **backticked**. Prose is neither. That
distinction is also the honest one, since backticks are already how this
codebase marks code.

**`--help` is not in `command.params`.** Click supplies the help option
from the context, so walking a command's own parameters does not find it
and six printed `kennis <something> --help` strings failed. Allowed
unconditionally, under both spellings `context_settings` configures.

**Four real violations, all of them docstrings naming unbuilt commands**:
`kennis register --force` in the report-grammar example at the top of
`display.py`, `kennis sync > log.txt` in `progress_bar`, `kennis setup` in
`following_steps`, and `kennis serve` in `logs.py`. I had expected
docstrings to be a source of false positives and instead they were the
only source of true ones - every `resolution=` and every `next_step` in
the project already resolved. The rule holds where it is enforced by
running the command, and fails where nobody runs anything.

**The guard caught my own fix.** Rewording `following_steps` I wrote "the
ones design section 9 lists as `kennis init`, `kennis sync` and
`kennis setup`", which is three more backticked non-commands, and the test
went red again immediately. This is the clearest evidence it works that I
could have asked for, and it was free.

**Two things I did not expect to find.** `following_steps` has no caller
at all (#268), and `display.command` has none either. And the guard is
blind to a backticked command written without the program name - the same
docstring that said `kennis setup` also said `corpus sync` and
`corpus index`, neither of which exists, and neither was flagged (#269).
So the four violations found are a lower bound, not a total.

