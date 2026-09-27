"""The third adapter over `render/theme.py`'s semantic roles.

`rich` gets one, `prompt_toolkit` gets one, and this is the CSS one.
The design's reason for declaring roles separately from any library is
exactly this moment: three style systems, one palette, and no colour
defined twice.

**Nothing here names a colour.** The registry names them; this maps
each role to a custom property and lets the stylesheet refer to it. A
literal colour in this file is the drift the roles exist to prevent,
and a test asserts every value came from the registry.
"""

from __future__ import annotations

from kennis.render.theme import ANSI_COLOURS, ROLES, AnsiColour

# Every colour the registry may name, as the browser knows it. Not a
# palette - a transliteration. The registry decides which role wears
# which; this only says what each is called in CSS.
#
# Eight of the nine are identities, which is why this looks redundant.
# The ninth is not: `bright_black` is the terminal's name for the grey
# that `muted` and `dim` wear, and CSS has no such keyword. Writing the
# map out in full rather than falling back to the ANSI name for unknown
# colours is deliberate - a fallback would emit `bright_black` as a CSS
# colour, which no browser understands, and the text would render in
# whatever it inherited with nothing to show that a colour was lost.
CSS_COLOURS: dict[AnsiColour, str] = {
    "black": "black",
    "red": "red",
    "green": "green",
    "yellow": "yellow",
    "blue": "blue",
    "magenta": "magenta",
    "cyan": "cyan",
    "white": "white",
    "bright_black": "gray",
}

# The registry may gain a colour. If it does, this adapter must gain a
# name for it, and finding out at import is better than finding out
# when a role renders as unstyled text on someone else's machine.
_MISSING = set(ANSI_COLOURS) - set(CSS_COLOURS)
if _MISSING:
    raise RuntimeError(f"no CSS name for ANSI colour(s): {sorted(_MISSING)}")


def css_variables() -> str:
    """One custom property per role, for a `:root` block.

    A role with no colour still gets a property, set to `inherit`:
    `unchanged` is deliberately uncoloured because it is the absence of
    news, and omitting it would make a stylesheet referring to it fall
    back to nothing rather than to the surrounding text.
    """
    lines: list[str] = []
    for name, role in ROLES.items():
        value = CSS_COLOURS[role.colour] if role.colour else "inherit"
        lines.append(f"  --role-{name}: {value};")
    return "\n".join(lines)


def css_weights() -> str:
    """The attribute half of a role, as a class per role.

    Separate from the colour because CSS keeps them apart: a colour is
    one property and bold, dim, italic and underline are four others,
    and a single custom property cannot carry all five.
    """
    blocks: list[str] = []
    for name, role in ROLES.items():
        declarations = [f"color: var(--role-{name});"]
        if role.bold:
            declarations.append("font-weight: 700;")
        if role.dim:
            declarations.append("opacity: 0.7;")
        if role.italic:
            declarations.append("font-style: italic;")
        if role.underline:
            declarations.append("text-decoration: underline;")
        body = " ".join(declarations)
        blocks.append(f".role-{name} {{ {body} }}")
    return "\n".join(blocks)


def stylesheet() -> str:
    """The whole generated stylesheet: the roles, then the layout.

    Generated rather than a static file because the roles are, and a
    static copy would be the second place a colour lives.
    """
    return f":root {{\n{css_variables()}\n}}\n\n{css_weights()}\n\n{_LAYOUT}"


# Layout only. No colour appears here: every visible colour comes
# through a `--role-` property above, so the eight-colour restriction
# the design applies to the terminal applies here too.
_LAYOUT = """\
* { box-sizing: border-box; }

body {
  margin: 0;
  font-family: system-ui, sans-serif;
  line-height: 1.5;
}

main { max-width: 60rem; margin: 0 auto; padding: 1.5rem; }

code, pre { font-family: ui-monospace, monospace; }
"""


__all__ = ["CSS_COLOURS", "css_variables", "css_weights", "stylesheet"]
