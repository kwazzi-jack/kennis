"""The vendored icons, inlined into the page.

**Inlined, not linked.** Lucide draws with `stroke="currentColor"`, which
an inline `<svg>` resolves against the text around it and an `<img>`
cannot: an icon in an `<img>` would be one colour in both themes and
never the colour of the label beside it.

Each file is read once. The licence comment Lucide puts at the top of
every file is dropped from the inlined copy - `NOTICE.txt` and
`LICENSE-Lucide.txt` carry it for the distribution, which is what the
ISC licence asks - and the tag is folded onto one line with Lucide's
own class replaced by `icon`, which is what the stylesheet sizes.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path
from typing import Final

from markupsafe import Markup

_ICONS: Final = Path(__file__).parent / "static" / "vendor" / "icons"


@cache
def icon(name: str) -> Markup:
    """The icon called `name`, as markup ready to place in a template.

    An unknown name raises rather than rendering nothing: a missing icon
    would leave a button with a gap where its picture was, and the
    template that asked would never find out. `name` comes from a
    template or from `words`, never from a request.
    """
    path = _ICONS / f"{name}.svg"
    if not path.is_file():
        raise KeyError(f"no vendored icon called {name!r}")
    source = path.read_text(encoding="utf-8")
    without_comment = re.sub(r"<!--.*?-->", "", source, flags=re.DOTALL)
    folded = " ".join(without_comment.split())
    # Hidden from assistive technology: every icon sits beside a label
    # or inside a control that carries its own name, and a screen reader
    # announcing "image" before each would be noise.
    classed = re.sub(
        r'class="[^"]*"', 'class="icon" aria-hidden="true"', folded, count=1
    )
    return Markup(classed)


__all__ = ["icon"]
