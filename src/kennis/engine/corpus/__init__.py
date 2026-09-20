"""The corpus: documents on disk, and the rules that make one findable.

Three collections - `notes`, `literature` and `docs` - are one ingestion
pipeline with different processing layered on it, not three different kinds of
thing. `notes` is the base case: anything text-bearing goes in, and a
surrogate identifier plus a content digest are the whole of its identity.
`literature` is notes plus bibliographic processing, `docs` is notes plus
site-structure processing. That is why a document can sensibly be moved
between them.
"""

from __future__ import annotations
