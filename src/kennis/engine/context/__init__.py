"""The per-workspace context bundle.

The second scope kennis holds: the corpus is machine-global, a bundle
belongs to one project and is committed with it. See `bundle` for finding
the one that governs a directory and for scaffolding a new one.
"""

from __future__ import annotations

from kennis.engine.context.bundle import (
    BUNDLE_DIRNAME,
    INDEX_DIRNAME,
    LANDING_FILENAME,
    MANIFEST_FILENAME,
    SCHEMA_VERSION,
    SKELETON_FILENAME,
    BundleCreated,
    bundle_override,
    find_bundle,
    index_root_for,
    init_bundle,
    is_bundle_dir,
    workspace_root,
)

__all__ = [
    "BUNDLE_DIRNAME",
    "INDEX_DIRNAME",
    "LANDING_FILENAME",
    "MANIFEST_FILENAME",
    "SCHEMA_VERSION",
    "SKELETON_FILENAME",
    "BundleCreated",
    "bundle_override",
    "find_bundle",
    "index_root_for",
    "init_bundle",
    "is_bundle_dir",
    "workspace_root",
]
