"""Packs: knowledge that arrives from outside, as data and never as code.

Design sections 2, 3, 5 to 10. A provider hands kennis a `.ken.yml` file
that declares what it ships; kennis validates it, stores it, and converges
the corpus and a workspace's bundle with what every installed pack declares.

`schema` is the whole of this package's vocabulary: every other module in
milestone 7 is stated in terms of its models.
"""

from __future__ import annotations

from kennis.engine.pack.schema import (
    SCHEMA_VERSION,
    ContentSource,
    CorpusSection,
    DocsEntry,
    GeneratedBlock,
    GeneratedContent,
    GeneratedSource,
    KennisHeader,
    LiteratureEntry,
    Pack,
    PackIdentity,
    load_pack,
    schema_document,
    schema_path,
)

__all__ = [
    "SCHEMA_VERSION",
    "ContentSource",
    "CorpusSection",
    "DocsEntry",
    "GeneratedBlock",
    "GeneratedContent",
    "GeneratedSource",
    "KennisHeader",
    "LiteratureEntry",
    "Pack",
    "PackIdentity",
    "load_pack",
    "schema_document",
    "schema_path",
]
