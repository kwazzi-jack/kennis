"""The typed refusal union, and the words a front end puts on one.

Unit 9e. The property these tests exist to hold is that **no refusal
sentence contains a command**: `engine/corpus/add.py` used to build
"Settle it with --identifier, or add it as a note instead: kennis
corpus add -n '<path>'", and a command buried in a sentence can only be
offered to someone who will retype it. A graphical interface needs the
facts as fields and the command on its own.
"""

from __future__ import annotations

import shlex
from dataclasses import fields, is_dataclass
from pathlib import Path

import click
import pytest

from kennis.cli.__main__ import main
from kennis.engine import refusals as refusal_module
from kennis.engine.refusals import (
    AmbiguousIdentity,
    BibliographyIncomplete,
    NoArxivText,
    NoIdentity,
    NoPublisherText,
    NotAnInput,
    NothingConverted,
    Quoted,
    Refusal,
    SameContent,
    SamePage,
    SamePaper,
    SymlinkSkipped,
    UnsupportedFormat,
)
from kennis.render.refusals import describe_refusal, remedies_for_refusal

# One of every member, so a test can be exhaustive without the union
# being introspectable. `test_every_member_of_the_union_is_sampled`
# below is what keeps this list honest when a fourteenth is added.
EVERY_REFUSAL: list[Refusal] = [
    Quoted(text="the converter is not installed"),
    SameContent(document_id="aaaaaaaaaa"),
    SamePaper(document_id="bbbbbbbbbb"),
    SamePage(project="numpy", key="reference/arrays"),
    NoIdentity(named="/tmp/paper.pdf"),
    AmbiguousIdentity(
        named="/tmp/paper.pdf", kind="arxiv", values=("2409.19750", "1101.1764")
    ),
    NoPublisherText(kind="doi", value="10.1093/mnras/stab1234"),
    NoArxivText(named="2409.19750", arxiv_id="2409.19750", declined="406"),
    NoArxivText(named="2409.19750", arxiv_id="2409.19750"),
    NotAnInput(identifier="nonsense"),
    BibliographyIncomplete(name="refs.bib", citekeys=("one", "two")),
    NothingConverted(name="paper.pdf", problem="mineru produced nothing"),
    NothingConverted(name="paper.pdf"),
    SymlinkSkipped(),
    UnsupportedFormat(suffix=".zip"),
]


def test_every_member_of_the_union_is_sampled():
    """A fourteenth refusal must reach every test in this file.

    Without this, adding a member and a `match` arm satisfies mypy and
    the sample list silently stops being exhaustive - the tests below
    would all still pass while proving nothing about the new one.
    """
    sampled = {type(refusal) for refusal in EVERY_REFUSAL}
    declared = {
        value
        for name, value in vars(refusal_module).items()
        if is_dataclass(value) and not name.startswith("_")
    }

    assert sampled == declared


def test_every_refusal_has_a_distinct_code():
    """The code is what serialises: an MCP client cannot match on a
    Python class, and two conditions sharing a name are one condition
    as far as anything reading the log is concerned."""
    codes = [type(refusal).code for refusal in EVERY_REFUSAL]

    assert len(set(codes)) == len({type(refusal) for refusal in EVERY_REFUSAL})


def test_every_refusal_is_worded():
    """`describe_refusal` is exhaustive by construction - a missing arm
    is a type error - but mypy checks the *declared* union and this
    checks the values."""
    for refusal in EVERY_REFUSAL:
        described = describe_refusal(refusal)

        assert described, refusal
        assert not described.endswith("."), described
        assert described[0].islower() or not described[0].isalpha(), described


def test_no_refusal_sentence_carries_a_command():
    """The property of this unit. A front end must be able to render the
    sentence as text and the remedy as an action, and it cannot do that
    if the sentence has `kennis corpus add -n '/tmp/x.pdf'` inside it.

    Checked against the real command names rather than against the word
    `kennis`, which a sentence may legitimately use as the subject of a
    verb - "kennis cannot tell which names the paper" is prose, and
    forbidding it would push the wording into contortions to satisfy
    the test.
    """
    invocations = [f"kennis {name}" for name in main.commands]
    assert "kennis corpus" in invocations

    for refusal in EVERY_REFUSAL:
        described = describe_refusal(refusal)
        for invocation in invocations:
            assert invocation not in described, (refusal, invocation)


def command_accepts(invocation: str) -> str:
    """Empty if the command line would accept `invocation`, else why not.

    The same parse-don't-run check `tests/test_render.py` uses for the
    other family of remedies, repeated here rather than shared: a
    helper imported between test modules is one more thing that can be
    changed for the wrong file's sake.
    """
    words = shlex.split(invocation)
    if words[0] != "kennis":
        return f"does not start with kennis: {invocation}"

    node: click.Command = main
    rest = words[1:]
    while rest and isinstance(node, click.Group):
        found = node.commands.get(rest[0])
        if found is None:
            return f"no command '{rest[0]}' in '{node.name}'"
        node, rest = found, rest[1:]

    try:
        with node.make_context(node.name, list(rest), resilient_parsing=False):
            return ""
    except click.ClickException as refused:
        return refused.format_message()


def test_every_remedy_runs_as_printed():
    """Rules.md 4.4. A remedy with `<file>` in it is why this returns
    nothing for the refusals whose way out needs a document only the
    user can name."""
    for refusal in EVERY_REFUSAL:
        for remedy in remedies_for_refusal(refusal):
            assert command_accepts(remedy) == "", remedy


def test_a_path_with_a_space_survives_its_remedy():
    """The remedy is a command string, so the name goes through
    `shlex.quote`. Without it the command parses as two arguments and
    rule 4.4 is broken by a filename."""
    remedies = remedies_for_refusal(NoIdentity(named="/tmp/two words.pdf"))

    assert remedies == ("kennis corpus add -n '/tmp/two words.pdf'",)
    assert command_accepts(remedies[0]) == ""


def test_an_unidentified_paper_is_offered_notes():
    """Notes is a real answer, not a consolation prize: notes have no
    natural key by design."""
    assert remedies_for_refusal(NoIdentity(named="/tmp/paper.pdf")) == (
        "kennis corpus add -n /tmp/paper.pdf",
    )


def test_an_ambiguous_page_is_not_settled_on_the_users_behalf():
    """Offering `--identifier 2409.19750` would be choosing which paper
    this is. The values are carried so a chooser can be built; the
    command kennis prints is the one that is right either way."""
    ambiguous = AmbiguousIdentity(
        named="/tmp/paper.pdf", kind="arxiv", values=("2409.19750", "1101.1764")
    )

    for remedy in remedies_for_refusal(ambiguous):
        assert "--identifier" not in remedy


def test_a_paper_whose_text_is_elsewhere_is_not_offered_notes():
    """Two different refusals with two different remedies. No identity
    means `add it as a note`; no text means supply the document,
    because the paper's identity was established perfectly well and
    filing it in notes would put a known paper in the wrong
    collection."""
    for refusal in (
        NoPublisherText(kind="doi", value="10.1093/mnras/stab1234"),
        NoArxivText(named="x", arxiv_id="2409.19750"),
    ):
        assert remedies_for_refusal(refusal) == ()
        assert "-n" not in describe_refusal(refusal)


def test_a_refusal_carries_its_facts_rather_than_a_count():
    """A chooser cannot be built from "more than one", and a repair form
    cannot be built from "2 entries"."""
    ambiguous = AmbiguousIdentity(
        named="/tmp/paper.pdf", kind="arxiv", values=("2409.19750", "1101.1764")
    )
    incomplete = BibliographyIncomplete(name="refs.bib", citekeys=("one", "two"))

    assert ambiguous.values == ("2409.19750", "1101.1764")
    assert incomplete.citekeys == ("one", "two")


def test_a_refusal_is_frozen_and_hashable():
    """An event is a record of something that already happened, so no
    subscriber may edit one before the next sees it - and a front end
    that groups identical refusals needs them in a set."""
    refusal = NoIdentity(named="/tmp/paper.pdf")

    # Through `setattr` with the name in a variable, which is neither
    # of the two things this repository refuses: writing the assignment
    # directly needs a silenced type error, and `setattr` with a
    # literal name is what ruff's B010 objects to. The behaviour at
    # runtime is the point, so a check of `__dataclass_params__` would
    # be testing the declaration instead.
    attribute = "named"
    with pytest.raises(AttributeError):
        setattr(refusal, attribute, "/tmp/other.pdf")
    assert len({refusal, NoIdentity(named="/tmp/paper.pdf")}) == 1


def test_no_refusal_field_is_a_path():
    """Everything a refusal carries has to cross a wire: the MCP server
    serialises it and the graphical interface puts it in HTML. A `Path`
    is also an absolute path on this machine, which names the user's
    account to whoever reads it."""
    for refusal in EVERY_REFUSAL:
        if not is_dataclass(type(refusal)):
            continue
        for member in fields(type(refusal)):
            value = getattr(refusal, member.name)
            assert not isinstance(value, Path), (refusal, member.name)
