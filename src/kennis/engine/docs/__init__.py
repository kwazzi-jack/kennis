"""Docs: notes plus site-structure processing.

A page's identity is its project and its page key, which is what lets the
same site be added twice without writing a second copy of it. Discovery -
which pages a site has - is `discover`; fetching and converting one of them
is `fetch`; what a site is, and what its project may be called, is `sites`.
"""

from __future__ import annotations

from kennis.engine.docs.discover import (
    DiscoveredPage,
    Discovery,
    discover_pages,
    discovery_mode,
    page_key,
)
from kennis.engine.docs.fetch import convert_page, fetch_page
from kennis.engine.docs.sites import DocsSite, project_name_from_url

__all__ = [
    "DiscoveredPage",
    "Discovery",
    "DocsSite",
    "convert_page",
    "discover_pages",
    "discovery_mode",
    "fetch_page",
    "page_key",
    "project_name_from_url",
]
