# v0.5 documentation: catching up with what is built

Date: 2026-09-28

## 1. What I am about to do

The documentation describes kennis 0.1.1. Since then packs, the
context bundle, the MCP server and the graphical interface have all
been built, and `docs/index.md` still says the MCP server "is not"
built and is "planned for 0.2.0 and later".

The repository is public, so this is the outward-facing description
of the project, three milestones behind.

Two new pages, one correction, and - first - a test, because nothing
checks the documentation at all today.

## 2. How I expect it to work

**The test comes first and is the interesting part.** rules.md 4.4
says a printed command runs as printed. That is enforced for a
`KennisError`'s resolution and for `remedies_for`, both by parsing the
command against the real `click` tree. The documentation is the place
kennis prints the *most* commands and the place a reader is most
likely to copy one, and nothing checks it.

`tests/test_docs.py`:

- every `kennis ...` line in a fenced block under `docs/`, and in
  `README.md`, parses against `kennis.cli.__main__.main`;
- every page under `docs/` appears in `mkdocs.yml`'s nav, and every
  nav entry names a page that exists.

Shell operators are cut before parsing - `kennis read x > x.md` is a
redirection, and the command is the part before the `>`. A line that
is a placeholder rather than an invocation is still an invocation as
far as `click` is concerned: `<file>` parses as an argument, which is
right, because the reader will replace it.

**Then the two pages.** `how-to/serve-an-agent.md` for `kennis serve`
and the nine tools; `how-to/the-interface.md` for `kennis gui`. Both
task-shaped, as the other how-tos are.

**Then `docs/index.md`'s status**, which is the one paragraph that is
actively false.

## 3. What I expect to be uncertain or difficult

- How many commands in the docs already fail to parse. I expect
  between zero and five, and zero would be surprising for three
  milestones of drift.
- Whether `mkdocs-click` renders `kennis gui` without help - it reads
  the click tree, and `gui` is defined there, so it should.
- Whether the nav check is worth having or is bureaucracy. A page not
  in the nav is a page nobody reaches, which is the same as not
  writing it.
- The tutorial may now be wrong in a way the parser cannot see: a
  command that parses but no longer does what the prose says.

## 4. What actually happened that I did not expect

**Every one of the 157 commands already parsed.** I predicted between
zero and five failures and said zero would be surprising. It was
zero. The prose went stale over three milestones and the commands did
not, which says the risk here is a true sentence about a false world
rather than a command that fails when copied - and that is the harder
kind to test for.

**Four of the first eleven failures were my parser, not the docs.**
A trailing `# what this does` is a shell comment and has to be
dropped; `kennis --help` is a real invocation of the group and my
walker was treating `--help` as a missing subcommand; `--from
jottings.md` is a `click.Path(exists=True)` and cannot parse anywhere
the reader has not already made the file; and a command wrapped
across lines with a trailing backslash was being read as two
fragments. Each needed the parser to be more like a shell, which is
the standard the rule is really about.

**The fence state machine was wrong in a way that read as a docs
defect.** A single `inside` flag that also read the fence tag treats
the *closing* fence of a `text` block - which carries no tag - as the
opening of a copyable one, and then parses every following paragraph
as a command. "kennis crawls from that page" was reported as an
unknown subcommand `crawls`. Two flags, one for inside and one for
copyable. This is #318's lesson from the other side: when a check
fails, establish whether the subject is wrong or the instrument is.

**The synopsis needed a convention rather than an exemption.** One
line in the documentation is notation - `--collection
<literature|docs|notes>` cannot parse, because `--collection` is a
`click.Choice`. I could have taught the test to ignore angle
brackets, which would have quietly exempted every placeholder
everywhere. Tagging the block `text` says the same thing to the
reader, in the source, at the one place it is true.

**The scanner is the hollow spot, so it has its own test.** Every
other test in the file checks commands the scanner hands it, so a
scanner that found none would leave the file green while checking
nothing. `test_the_scanner_actually_finds_the_commands` asserts more
than a hundred, and the injection that stops the scanner seeing
fenced blocks is caught by it.

**`mkdocs-click` needed nothing.** `kennis gui` appeared in the
generated command reference by itself, which is what that page's
first sentence promises and is pleasant to have confirmed.

**And the thing I did not expect at all: `tests/test_docs.py` already
existed, and I overwrote it.** Four tests from concern #219 - the
generated settings table, the nav entries, a `--strict` build, the
card grid rendering - destroyed by a heredoc at a path I had not
looked at. Nothing caught it: the suite was green, the replacement
file was well tested, and every gate passed. What showed it was the
slow suite reporting 7 where the previous run reported 9. Recovered
from git and merged by hand. Concern #328, and the lesson is that a
count moving without a reason is evidence.
