"""Repairing ligature damage against the PDF's own text layer.

MinerU resolves an `ff`, `fi` or `fl` ligature to one character instead of
two, so `different` is stored as `diferent`. BM25 tokenises what is stored,
so a search for `different` cannot match it and the dense leg embeds a
misspelling; a reindex does not help, because the text on disk is wrong.
Concerns #135, #136.

**The reference is authoritative about what the PDF says, not about what is
correct.** It is also incomplete - 4.5% of the correct words in a known-good
conversion were absent from it, because pypdfium2 cannot read text inside a
figure (#152). So absence alone is weak evidence, and the pass additionally
requires the damage to look like the damage: an inserted `f`, `i` or `l`
landing beside its own twin.

The test that matters most here is the last one. A repair pass that only
ever ran against damaged input would have shipped `column` -> `columns`.
"""

from __future__ import annotations

from kennis.engine.corpus.ligatures import repair_ligatures

# The vocabulary a PDF's text layer would yield. Written out rather than
# extracted, so these tests state the rule rather than a document.
VOCABULARY = frozenset(
    {
        "different",
        "differently",
        "effect",
        "effects",
        "sufficient",
        "offset",
        "columns",
        "column",
        "behaviour",
        "through",
        "calibration",
        "the",
        "and",
    }
)


def test_a_dropped_ligature_half_is_restored():
    repaired, count = repair_ligatures("the diferent gains", VOCABULARY)

    assert repaired == "the different gains"
    assert count == 1


def test_every_occurrence_is_repaired_and_counted():
    repaired, count = repair_ligatures("efects and efects and efect", VOCABULARY)

    assert repaired == "effects and effects and effect"
    assert count == 3


def test_a_word_already_in_the_vocabulary_is_left_alone():
    """The reference agrees with the converter, so there is nothing to do -
    this is the ordinary case and must be untouched."""
    text = "the different calibration effects"

    repaired, count = repair_ligatures(text, VOCABULARY)

    assert repaired == text
    assert count == 0


def test_capitalisation_is_preserved():
    repaired, _ = repair_ligatures("Diferent gains", VOCABULARY)

    assert repaired == "Different gains"


# ---------------------------------------------------------------------------
# What it must refuse
# ---------------------------------------------------------------------------


def test_a_plural_is_not_invented():
    """`column` is a correct word. It was absent from one paper's reference
    only because pypdfium2 could not read the figure caption it appeared in,
    and the unconstrained rule pluralised it six times in correct text.
    Concern #152."""
    vocabulary = VOCABULARY - {"column"}

    repaired, count = repair_ligatures("the left column shows", vocabulary)

    assert repaired == "the left column shows"
    assert count == 0


def test_a_spelling_is_not_changed_to_another_the_document_uses():
    """`behavior` -> `behaviour` changes the author's spelling. The inserted
    `u` is not a ligature letter and does not double."""
    repaired, count = repair_ligatures("the behavior of the gains", VOCABULARY)

    assert repaired == "the behavior of the gains"
    assert count == 0


def test_a_word_is_not_changed_into_a_different_word():
    """`trough` -> `through` changes the meaning outright."""
    repaired, count = repair_ligatures("a trough in the data", VOCABULARY)

    assert repaired == "a trough in the data"
    assert count == 0


def test_an_insertion_that_does_not_double_is_refused():
    """The defect is a ligature glyph resolving to one character instead of
    two, so the lost character always sits beside its own twin. Anything
    else is a different word, not this damage."""
    repaired, count = repair_ligatures("ofset", VOCABULARY)
    assert repaired == "offset" and count == 1

    # `columns` is reachable from `column` by inserting `s`, which neither
    # doubles nor is a ligature letter.
    repaired, count = repair_ligatures("column", VOCABULARY - {"column"})
    assert repaired == "column" and count == 0


def test_a_ligature_letter_that_does_not_double_is_refused():
    """Isolates the doubling constraint from the alphabet constraint.

    `behalf` is reachable from `behal` by inserting `f`, which *is* a
    ligature letter - but at the end of the word, with no `f` beside it. A
    ligature that lost half of itself always leaves its twin behind, so this
    is not that damage.
    """
    repaired, count = repair_ligatures("on behal of", frozenset({"behalf", "on", "of"}))

    assert repaired == "on behal of"
    assert count == 0


def test_a_doubling_that_is_not_a_ligature_letter_is_refused():
    """Isolates the alphabet constraint from the doubling constraint.

    `success` is reachable from `sucess` by inserting `c` beside the `c`
    that is already there, so the doubling test alone would allow it. But
    `c` has no ligature, so this is somebody's typo and not the defect this
    pass repairs - and a pass that repairs typos is the one that turned
    `untargeted` into `untargetted`. Concern #153.
    """
    repaired, count = repair_ligatures("a sucess", frozenset({"success"}))

    assert repaired == "a sucess"
    assert count == 0


def test_a_short_token_is_never_repaired():
    """Short words are dense in one-insertion neighbours, and a real short
    token is usually a symbol."""
    repaired, count = repair_ligatures("of", VOCABULARY | {"off"})

    assert repaired == "of"
    assert count == 0


def test_an_ambiguous_token_is_left_alone():
    """Two candidates means the evidence does not name one repair, and
    guessing between them is exactly what this pass must not do.

    The token is constructed. Under the doubling constraint a token with two
    *distinct* candidates is hard to find in real text - which is a property
    of the constraint worth noticing, not a reason to leave the guard
    untested. Here `ofof` admits `offof` (doubling the first `f`) and
    `ofoff` (doubling the second).
    """
    vocabulary = frozenset({"offof", "ofoff"})

    repaired, count = repair_ligatures("ofof", vocabulary)

    assert repaired == "ofof"
    assert count == 0


def test_mathematics_is_not_repaired():
    """A token inside `$...$` is notation, and changing it changes an
    equation."""
    text = "the $diferent$ term"

    repaired, count = repair_ligatures(text, VOCABULARY)

    assert repaired == text
    assert count == 0


def test_code_is_not_repaired():
    text = "the `diferent` flag"

    repaired, count = repair_ligatures(text, VOCABULARY)

    assert repaired == text
    assert count == 0


# ---------------------------------------------------------------------------
# The control
# ---------------------------------------------------------------------------


def test_the_pass_is_a_no_op_on_undamaged_text():
    """**The test this module exists for.**

    A repair pass validated only against damaged input looks perfect and
    corrupts correct documents. Run against text with no ligature damage,
    this must change nothing at all - and the unconstrained version of this
    rule failed exactly here, making 6 wrong repairs on one clean conversion
    and 21 on another. Concerns #151, #153.
    """
    clean = (
        "The different effects of the calibration are sufficient. "
        "The left column shows the behavior through the offset, "
        "and the columns differently show the effect."
    )
    vocabulary = VOCABULARY - {"column", "behaviour"}

    repaired, count = repair_ligatures(clean, vocabulary)

    assert repaired == clean
    assert count == 0
