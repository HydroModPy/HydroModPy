"""HydroModPy ASCII banner."""

from __future__ import annotations

from rich.text import Text

from hydromodpy.core.progress import console

_HYDRO_STYLE = "bold #29ABE2"
_MOD_STYLE = "bold #2D5F8B"
_PY_STYLE = "bold #FFC20E"
_TAGLINE_STYLE = "dim"

_LETTER_LINES = [
    r"      __  __          __           __  ____          ________     ",
    r"     / / / /         / /          /  \/   /         / / __  /     ",
    r"    / /_/ /_  ______/ /________  /       /___  ____/ / /_/ /_  __ ",
    r"   / __  / / / / __  / ___/ __ \/ /\,-/ / __ \/ __  / ____/ / / / ",
    r"  / / / / /_/ / /_/ / /  / /_/ / /   / / /_/ / /_/ / /   / /_/ /  ",
    r" /_/ /_/\__, /_____/_/   \____/_/   /_/\____/_____/_/____\__, /   ",
]
# Per-line column splits between the Hydro, Mod and Py letter groups.
# The font is slanted, so the boundaries shift left on lower lines.
_SPLITS = [(34, 55), (33, 55), (33, 54), (32, 53), (32, 52), (31, 53)]
_FOOTER = r"       /____/ Hydrological Modelling in Python /_____________/    "

_banner_printed = False


def _banner() -> Text:
    """Build the banner colored like the project logo."""
    text = Text(no_wrap=True)
    for line, (hydro_end, mod_end) in zip(_LETTER_LINES, _SPLITS, strict=True):
        text.append(line[:hydro_end], style=_HYDRO_STYLE)
        text.append(line[hydro_end:mod_end], style=_MOD_STYLE)
        text.append(line[mod_end:] + "\n", style=_PY_STYLE)
    text.append(_FOOTER[:7])
    text.append(_FOOTER[7:13], style=_HYDRO_STYLE)
    text.append(_FOOTER[13:47], style=_TAGLINE_STYLE)
    text.append(_FOOTER[47:62] + "\n", style=_PY_STYLE)
    return text


def print_hydromodpy() -> None:
    """Print the HydroModPy banner once."""
    global _banner_printed
    if _banner_printed:
        return
    console.print(_banner())
    _banner_printed = True


__all__ = ["print_hydromodpy"]
