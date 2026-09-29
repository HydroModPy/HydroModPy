"""HydroModPy ASCII banner."""

from __future__ import annotations

from rich.text import Text

from hydromodpy.core.progress import console

_HYDRO_STYLE = "bold #29ABE2"
_MOD_STYLE = "bold #2D5F8B"
_PY_STYLE = "bold #FFC20E"
_TAGLINE_STYLE = "dim"

_LETTER_LINES = [
    r"      __  __          __             __  ____          __  ______    ",
    r"     / / / /         / /            /  \/   /         / / / __  /    ",
    r"    / /_/ /_  ______/ /________    /       /___  ____/ / / /_/ /_  __",
    r"   / __  / / / / __  / ___/ __ \  / /\,-/ / __ \/ __  / / ____/ / / /",
    r"  / / / / /_/ / /_/ / /  / /_/ / / /   / / /_/ / /_/ / / /   / /_/ / ",
    r" /_/ /_/\__, /_____/_/   \____/ /_/   /_/\____/_____/ /_/____\__, /  ",
]
# Per-line column splits between the Hydro, Mod and Py letter groups. The
# slanted font joins neighbour letters with a shared stroke, so the art keeps
# a blank column where the color changes: every letter is drawn whole in its
# group's color. The boundaries shift left on lower lines, following the slant.
_SPLITS = [(37, 59), (36, 58), (35, 57), (34, 56), (33, 55), (32, 54)]
_FOOTER = r"       /____/   Hydrological Modelling in Python   /_____________/"
# Starts of the Hydro y descender, the tagline and the swash under Py.
_FOOTER_SPLITS = (7, 13, 51)

_banner_printed = False


def _banner() -> Text:
    """Build the banner colored like the project logo."""
    text = Text(no_wrap=True)
    for line, (hydro_end, mod_end) in zip(_LETTER_LINES, _SPLITS, strict=True):
        text.append(line[:hydro_end], style=_HYDRO_STYLE)
        text.append(line[hydro_end:mod_end], style=_MOD_STYLE)
        text.append(line[mod_end:] + "\n", style=_PY_STYLE)
    descender, tagline, swash = _FOOTER_SPLITS
    text.append(_FOOTER[:descender])
    text.append(_FOOTER[descender:tagline], style=_HYDRO_STYLE)
    text.append(_FOOTER[tagline:swash], style=_TAGLINE_STYLE)
    text.append(_FOOTER[swash:] + "\n", style=_PY_STYLE)
    return text


def print_hydromodpy() -> None:
    """Print the HydroModPy banner once."""
    global _banner_printed
    if _banner_printed:
        return
    console.print(_banner())
    _banner_printed = True


__all__ = ["print_hydromodpy"]
