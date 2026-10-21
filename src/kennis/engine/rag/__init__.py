"""Retrieval: chunking, lexical and dense indexes, and ranked search.

Source-agnostic by design. Nothing here knows what frontmatter is or which
collections exist - a loader turns documents into `Document` values and
everything downstream works on those, which is what will let the context
bundle use the same engine as the corpus.
"""
