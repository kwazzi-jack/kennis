"""Bibliographic processing: what makes literature more than notes.

Three modules, split by what they need rather than by what they are about.
`identifiers` recognises the ways a paper can already be named and touches
nothing; `citekeys` mints a name for one that arrived without; `metadata` is
the only part that fetches.
"""

from __future__ import annotations
