"""Packs: knowledge that arrives from outside, as data and never as code.

Design sections 2, 3, 5 to 10. A provider hands kennis a `.ken.yml` file
that declares what it ships; kennis validates it, stores it, and converges
the corpus and a workspace's bundle with what every installed pack declares.

`schema` is the whole of this package's vocabulary: every other module in
milestone 7 is stated in terms of its models.
"""

from __future__ import annotations

from kennis.engine.pack.content import (
    SourceContent,
    content_digest,
    read_source,
)
from kennis.engine.pack.scaffold import DEFAULT_VERSION, SCHEMA_URL, scaffold_pack
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
from kennis.engine.pack.store import (
    PackInstall,
    PackState,
    install_pack,
    pack_root,
    packs_root,
    read_state,
)
from kennis.engine.pack.update import GENERATED_MARKER, PackUpdate, update_pack
from kennis.engine.pack.validate import (
    PackProblem,
    PackReport,
    VersionRefusal,
    validate_pack,
    version_refusal,
)

__all__ = [
    "DEFAULT_VERSION",
    "GENERATED_MARKER",
    "SCHEMA_URL",
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
    "PackInstall",
    "PackProblem",
    "PackReport",
    "PackState",
    "PackUpdate",
    "SourceContent",
    "VersionRefusal",
    "content_digest",
    "install_pack",
    "load_pack",
    "pack_root",
    "packs_root",
    "read_source",
    "read_state",
    "scaffold_pack",
    "schema_document",
    "schema_path",
    "update_pack",
    "validate_pack",
    "version_refusal",
]
