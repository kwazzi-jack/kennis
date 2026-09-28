# v0.5 unit 9e: a refusal a form can be built from

Date: 2026-09-28

## 1. What I am about to do

`AddOutcome.reason` is a `str | None`. Unit 9f needs to offer a repair
form when an add is refused, and a form cannot be built from a
sentence without parsing it. So the reason becomes a typed union: one
frozen dataclass per way an add can be refused, carrying the facts,
with the phrasing in `render/` under an exhaustive `match`.

The same treatment #285 and #289 gave `Diagnostic.message`. That is
precedent in this repository rather than a new idea, and mypy
enforcing the match is what made it hold.

## 2. How I expect it to work

**What I found before starting, which changes the unit's value.**

`AddOutcome.reason` is read **nowhere**. `_report_add` prints titles
and identifiers grouped by outcome and never the reason. The reason
does reach `ItemFinished` and so the log file, and `ItemFinished`'s
docstring says that is deliberate - "what the log keeps and the report
usually drops", because a docs add of three hundred pages would put
three hundred lines above the summary.

Right for three hundred pages, wrong for one. `kennis corpus add -l
paper.pdf` that refuses prints the paper's name under a failure
marker and nothing else, while the sentence explaining what to do -
"no arXiv id, DOI or ADS bibcode found on its first page ... Supply
one with --identifier, or add it as a note instead" - is written to a
log the user has no reason to open.

So this unit does two things: make the refusal structured, and
surface it. Failures are the case worth printing and `display.details`
already caps the list, so the cap is not a new problem.

**The union, from the sites rather than from imagination.** Eighteen
`AddOutcome` constructions, of which these refuse:

| dataclass | facts it carries |
|---|---|
| `NoIdentity` | the name, so a form can offer `--identifier` |
| `AmbiguousIdentity` | the kind, and every value found |
| `NoPublisherText` | which identifier kind, and its value |
| `NoArxivText` | the name, the arXiv id, why arXiv declined |
| `NotAnInput` | the identifier that names nothing |
| `BibliographyHasNoDocuments` | the path, and every entry lacking one |
| `ConversionProducedNothing` | the path, and the converter's own words |
| `AlreadyHeld` | which document it duplicates |
| `AlreadyHeldAsPage` | the project and key |
| `InputSkipped` | the path, and why intake declined it |
| `OperationFailed` | an exception kennis is quoting |

`OperationFailed` is the one that stays a string, and legitimately:
it wraps `str(error)`, which is text kennis is quoting rather than
composing - one of the three stated exceptions to the phrasing rule.

**The commands come out of the sentences.** `_no_identity_reason`
currently ends "...or add it as a note instead: `kennis corpus add -n
'<path>'`". A command-line invocation composed in the engine and
embedded mid-sentence is what the phrasing rule exists to prevent; a
graphical front end cannot use it and would have to strip it. The
facts move to the dataclass and the command moves to `render/`, where
the exception for "a resolution that is a command string" applies.

`logs.py` renders the union, as it already does for
`Diagnostic.detail` - it sits outside every front end and may import
`render/`.

## 3. What I expect to be uncertain or difficult

- Whether `ItemFinished.reason` should take the union too, or stay a
  string. It is one field on a generic event that several operations
  emit, not just `add`.
- How many tests assert on reason text. Twenty-seven lines mention
  `.reason` across the suite, and some are other dataclasses entirely.
- Whether `InputSkipped` belongs here at all: `SkippedInput.reason`
  is intake's own field and converting it widens the unit.
- Whether printing failures with their reasons makes a bad docs crawl
  unreadable. `display.details` caps, but the cap was chosen for
  names rather than sentences.

## 4. What actually happened that I did not expect

**The union had to widen past add, and that turned out to be right.**
I planned `AddRefusal` on `AddOutcome` alone, and then found that the
log would lose its per-item sentence unless `ItemFinished` carried the
typed value too - and `ItemFinished` is emitted by pack validate, pack
update and both syncs as well. Two fields on one event (`reason` and
`refusal`) is the duplication the project's posture forbids, so the
union became `Refusal` and those four callers wrap their verdict names
in `Quoted`. Four call sites, and one field instead of two.

`Quoted` is the part I expected to feel like a cheat and does not.
`str(error)` and `problem.kind` are text kennis is repeating, which
#81 already exempts; a member that says "this is quoted" is more
honest than a `str` field that does not distinguish the two cases.

**`SkippedInput.reason` did have to change**, which section 3 listed
as an open question. Leaving it a string would have meant mapping
`"symlink"` back to a member at the `_skipped` call site, which is
parsing a sentence kennis wrote - exactly the thing the unit exists to
stop.

**The scope question in section 3 had a wrong premise.** I worried
that printing failures with their reasons would make a bad docs crawl
unreadable. It cannot: `_pages_of` *raises* rather than refusing, so a
docs add has no refused items at all. The three-hundred-line fear was
about a case that does not exist in this code.

**Nothing broke that the type checker did not find.** Twenty-one tests
failed on the first full run and every one was a mechanical
adaptation; mypy found the one real place I had missed (`logs.py`).
Each adaptation made the test stronger, because a dataclass comparison
says more than a substring: `assert refusal == AmbiguousIdentity(...,
values=("2409.19750", "1101.1764"))` pins the order and the kind,
where `assert "2409.19750" in reason` passed for any sentence
containing the digits.

**The no-command property needed a second attempt.** My first version
asserted `"kennis " not in described`, which failed on "kennis cannot
tell which names the paper" - prose using the program as the subject
of a verb. Forbidding that would push the wording into contortions to
satisfy the test, so the check is now against the real top-level
command names, built from `main.commands` and asserted non-empty.

**Running the command found what thirteen caught injections did not.**
Third unit running. `kennis corpus add -l welman2024` printed a
correct refusal and wrote *no item line to the log*, because
`_papers_of` settles some arguments before the loop that emits
`ItemFinished`. The report had it and the stream did not, which is the
asymmetry backwards. Concern #323, fixed in this unit with its own
test and its own injection.
