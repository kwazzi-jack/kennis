"""The YAML-frontmatter codec: splitting a markdown file into its mapping and
its body, and putting the two back together.

A document is a markdown file with an optional leading YAML block delimited by
`---` lines. This module knows the delimiters and nothing about what the keys
mean; validating them against a collection's model is `corpus.schema`'s job,
and it happens at the boundary - on the way to disk and on the way back.

It sits at the engine root rather than inside `corpus/` because the context
bundle reads and writes frontmatter too, and a codec living inside `corpus/`
that `context/` reached back for would close an import loop.
"""

from __future__ import annotations

from typing import Any

import yaml

type Frontmatter = dict[str, Any]

_DELIMITER = "---"


def split_frontmatter(text: str) -> tuple[Frontmatter, str]:
    """Split `text` into its frontmatter mapping and body.

    Returns `({}, text)` unchanged when `text` has no leading `---` block, or
    when the block is left unterminated. A caller that requires frontmatter
    treats the empty mapping as the failure; this function does not decide
    that for it.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != _DELIMITER:
        return {}, text

    for line_index in range(1, len(lines)):
        if lines[line_index].strip() != _DELIMITER:
            continue
        block = "".join(lines[1:line_index])
        body = "".join(lines[line_index + 1 :])
        parsed = yaml.safe_load(block) or {}
        if not isinstance(parsed, dict):
            return {}, text
        return parsed, body.lstrip("\n")

    return {}, text


def join_frontmatter(frontmatter: Frontmatter, body: str) -> str:
    """Render `frontmatter` and `body` back into one document string.

    `sort_keys=False` keeps the model's own field order, so a document reads
    top-down in the order the schema declares rather than alphabetically.
    """
    block = yaml.safe_dump(dict(frontmatter), sort_keys=False, default_flow_style=False)
    return f"{_DELIMITER}\n{block}{_DELIMITER}\n\n{body}"
