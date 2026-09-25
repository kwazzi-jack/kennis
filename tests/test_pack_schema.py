"""The `.ken.yml` schema: design section 7, milestone 7 unit 1.

Pure data. Nothing here reads the filesystem except the one test that
compares the committed JSON Schema against the models it was generated from,
and nothing here touches a store.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kennis.engine.errors import PackInvalid
from kennis.engine.pack.schema import (
    SCHEMA_VERSION,
    ContentSource,
    LiteratureEntry,
    Pack,
    PackIdentity,
    load_pack,
    schema_document,
    schema_path,
)

MINIMAL = """
kennis:
  schema_version: 1

pack:
  id: boepie
  name: "stimela pipelines"
  version: "0.1.0"
"""


def a_pack(body: str = MINIMAL) -> Pack:
    return load_pack(body)


HEADER_EXTRA = """
kennis:
  schema_version: 1
  unknown_key: 1
pack:
  id: a
  name: n
  version: "1"
"""

IDENTITY_EXTRA = """
kennis:
  schema_version: 1
pack:
  id: a
  name: n
  version: "1"
  unknown_key: 1
"""

CONTENT_SOURCE_EXTRA = """
kennis:
  schema_version: 1
pack:
  id: a
  name: n
  version: "1"
corpus:
  notes:
    - source: n/
      unknown_key: 1
"""


# ---------------------------------------------------------------------------
# The shape of a valid file
# ---------------------------------------------------------------------------


def test_the_minimal_pack_is_the_header_and_the_identity():
    """Everything below `pack:` has a default, so a provider scaffolding a
    pack has a valid file before it has any content."""
    pack = a_pack()

    assert pack.pack.id == "boepie"
    assert pack.kennis.schema_version == 1
    assert pack.kennis.min_version is None
    assert pack.corpus.literature == []
    assert pack.corpus.notes == []
    assert pack.context == []
    assert pack.generated is None


def test_a_content_source_defaults_to_markdown_at_any_depth():
    """`include: ["**/*.md"]` is the default in section 7, not a value every
    pack has to spell out."""
    source = ContentSource(source="notes/")

    assert source.include == ["**/*.md"]
    assert source.exclude == []
    assert source.group is None


def test_the_worked_example_from_the_design_parses():
    """The YAML in design section 7, reduced to the parts that carry data.
    If the models and the document disagree, one of them is wrong, and this
    is the test that says so."""
    pack = a_pack("""
kennis:
  schema_version: 1
  min_version: "0.2"
pack:
  id: boepie
  name: "stimela pipelines"
  version: "0.1.0"
  description: "Radio interferometry data reduction with stimela."
  homepage: "https://github.com/example/boepie"
corpus:
  literature:
    - citekey: smirnovRevisitingRIMEI2011
      title: "Revisiting the radio interferometer measurement equation I"
      arxiv_id: "1101.1764"
      doi: "10.1051/0004-6361/201016082"
      authors: "Smirnov, O. M."
      year: 2011
  docs:
    - project: stimela
      base_url: "https://stimela.readthedocs.io/en/latest/"
      exclude: []
  notes:
    - source: notes/
      group: stimela
      include: ["**/*.md"]
      exclude: []
context:
  - source: content/
    include: ["**/*.md"]
    exclude: []
generated:
  at: "2026-09-18T17:40:00Z"
  by: "kennis 0.1.0"
  content:
    context:
      - source: content/
        files:
          "index.md": "9c1d"
    notes:
      - source: notes/
        files:
          "conventions.md": "7e05"
""")

    assert pack.corpus.literature[0].year == 2011
    assert pack.corpus.docs[0].project == "stimela"
    assert pack.corpus.notes[0].group == "stimela"
    assert pack.context[0].source == "content/"
    assert pack.generated is not None
    assert pack.generated.content.notes[0].files == {"conventions.md": "7e05"}


# ---------------------------------------------------------------------------
# What is refused, and why
# ---------------------------------------------------------------------------


def test_an_unknown_key_is_refused_and_named():
    """`extra="forbid"`, section 7. With pydantic's default the key is
    dropped in silence, so a pack using a section a newer kennis understands
    installs cleanly on an older one and is quietly missing content."""
    with pytest.raises(PackInvalid) as raised:
        a_pack("""
kennis:
  schema_version: 1
pack:
  id: boepie
  name: "stimela pipelines"
  version: "0.1.0"
agent:
  domain: "radio astronomy"
""")

    assert "agent" in str(raised.value)


@pytest.mark.parametrize(
    "section",
    [
        HEADER_EXTRA,
        IDENTITY_EXTRA,
        CONTENT_SOURCE_EXTRA,
    ],
    ids=["header", "identity", "content-source"],
)
def test_every_model_forbids_extras_not_only_the_outer_one(section: str):
    """The reason section 7 gives for `extra="forbid"` is about a section a
    newer kennis understands, and a new field inside an existing section is
    the same failure. A nested model left on pydantic's default would drop
    it silently."""
    with pytest.raises(PackInvalid) as raised:
        a_pack(section)

    assert "unknown_key" in str(raised.value)


def test_a_literature_entry_needs_a_real_identifier():
    """Section 3: every literature entry needs an arXiv id, a DOI or an ADS
    bibcode, because a citekey invented from a title cites nothing and
    defeats duplicate detection. Refused at authoring time so the installing
    user never meets the question."""
    with pytest.raises(PackInvalid) as raised:
        a_pack("""
kennis:
  schema_version: 1
pack:
  id: boepie
  name: n
  version: "1"
corpus:
  literature:
    - citekey: someTitle2011
      title: "A paper with no identifier"
""")

    message = str(raised.value)
    assert "arxiv_id" in message and "doi" in message and "bibcode" in message


@pytest.mark.parametrize("identifier", ["arxiv_id", "doi", "bibcode"])
def test_any_one_of_the_three_identifiers_is_enough(identifier: str):
    entry = LiteratureEntry(citekey="k", title="t", **{identifier: "x"})

    assert getattr(entry, identifier) == "x"


@pytest.mark.parametrize(
    "identifier",
    ["Boepie", "boepie_pack", "-boepie", "boepie pack", "", "boepie/pack"],
    ids=["capital", "underscore", "leading-dash", "space", "empty", "slash"],
)
def test_a_pack_id_that_is_not_a_slug_is_refused(identifier: str):
    """`^[a-z0-9][a-z0-9-]*$`, section 7. The id is the dedupe key, it names
    a directory in the store, and it appears in `owner: pack:<id>` - so a
    value with a space or a slash in it would be three different kinds of
    problem at once."""
    with pytest.raises(ValueError):
        PackIdentity(id=identifier, name="n", version="1")


def test_a_pack_id_may_end_in_a_digit_a_letter_or_a_dash():
    """The last of these is the design's pattern being taken literally. A
    trailing dash is permitted by `^[a-z0-9][a-z0-9-]*$`, and the two places
    the id is used - a directory name in the store and `owner: pack:<id>` -
    are indifferent to it. Written down because the first draft of this test
    assumed the opposite and the pattern is the authority."""
    assert PackIdentity(id="boepie-2", name="n", version="1").id == "boepie-2"
    assert PackIdentity(id="b", name="n", version="1").id == "b"
    assert PackIdentity(id="boepie-", name="n", version="1").id == "boepie-"


def test_a_description_longer_than_the_cap_is_refused():
    """Section 11 puts this string into an MCP server's instructions, so its
    length is a budget rather than a formality."""
    with pytest.raises(ValueError):
        PackIdentity(id="a", name="n", version="1", description="x" * 501)


def test_a_year_that_is_not_a_number_is_refused():
    """`year_min` filtering compares numerically; a string year invites a
    lexicographic comparison bug at the filter."""
    with pytest.raises(ValueError):
        # Validated from a mapping rather than constructed with a keyword,
        # because a string year is what the annotation forbids: the keyword
        # form would need a silenced type error to express the thing being
        # tested, and a pack file arrives as a mapping anyway.
        LiteratureEntry.model_validate(
            {"citekey": "k", "title": "t", "arxiv_id": "1", "year": "two thousand"}
        )


@pytest.mark.parametrize(
    "source",
    ["/etc/passwd", "../outside/", "notes/../../outside", "~/notes"],
    ids=["absolute", "parent", "parent-inside", "home"],
)
def test_a_source_that_leaves_the_pack_root_is_refused(source: str):
    """The string half of section 7's path hygiene. Whether a *discovered*
    file resolves under the pack root is a filesystem question and belongs
    with the walk; whether the *declared* path could ever stay inside is a
    property of the string and belongs here."""
    with pytest.raises(ValueError):
        ContentSource(source=source)


def test_yaml_that_is_not_a_mapping_is_refused_as_a_pack_not_as_a_crash():
    with pytest.raises(PackInvalid):
        a_pack("- just\n- a\n- list\n")


def test_yaml_that_does_not_parse_is_refused_as_a_pack():
    """A broken file is a pack failure with a field path the author can act
    on, not a `yaml.YAMLError` escaping the engine."""
    with pytest.raises(PackInvalid):
        a_pack("kennis:\n  schema_version: [unclosed\n")


def test_the_error_names_the_field_path():
    """Section 5 step 1: refuse naming the field path. A message that says
    only "invalid" makes the author hunt."""
    with pytest.raises(PackInvalid) as raised:
        a_pack(
            "kennis:\n  schema_version: not-a-number\n"
            "pack:\n  id: a\n  name: n\n  version: '1'\n"
        )

    assert "kennis.schema_version" in str(raised.value)


# ---------------------------------------------------------------------------
# The published JSON Schema
# ---------------------------------------------------------------------------


def test_the_committed_schema_matches_the_models():
    """Section 7: the models are the single declaration and the JSON Schema
    is generated from them, so there is no second source to drift. This is
    the test that makes that true rather than intended."""
    committed = json.loads(schema_path().read_text(encoding="utf-8"))

    assert committed == schema_document()


def test_the_schema_is_shipped_in_the_wheel_not_only_in_the_repository():
    """Section 18: `pack validate` uses the local copy, so it has to be
    inside the installed package rather than beside it."""
    installed = schema_path()

    assert installed.is_file()
    assert "kennis" in installed.parts


def test_the_schema_forbids_the_same_key_the_models_forbid():
    """An editor validating against the published file and kennis validating
    against the models must give the same answer, or the header line section
    18 writes into every scaffold is worse than useless."""
    document = schema_document()

    assert document["additionalProperties"] is False
    for definition in document["$defs"].values():
        if definition.get("type") == "object":
            assert definition["additionalProperties"] is False, definition


def test_the_schema_version_is_one_and_the_file_is_named_for_it():
    """Section 18: the path is versioned, so schema 1 never changes meaning
    and schema 2 is a new file."""
    assert SCHEMA_VERSION == 1
    assert schema_path().name == "ken-1.json"


def test_a_schema_version_this_kennis_does_not_know_is_still_parsed_here():
    """Refusing a newer `schema_version` is unit 2's job, not this one's:
    it is a different failure with a different fix ("upgrade kennis"), and
    deciding it here would mean the models could not be used to read a file
    in order to report what is wrong with it."""
    pack = a_pack(
        "kennis:\n  schema_version: 99\npack:\n  id: a\n  name: n\n  version: '1'\n"
    )

    assert pack.kennis.schema_version == 99


def test_the_generated_block_is_absent_from_a_hand_written_pack(tmp_path: Path):
    """`generated:` is written by `pack update`, so a pack that has never
    been updated is valid without it and nothing downstream may assume it."""
    del tmp_path
    assert a_pack().generated is None
