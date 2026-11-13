"""Publication theme: tokens, colour roles, ramps and the unit text helper."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from matplotlib import font_manager

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

FONTS_DIR = Path(__file__).parent / "fonts"
FONT_FAMILY = "TeX Gyre Heros"
FONT_FALLBACK = "DejaVu Sans"
FONT_FILES = ("texgyreheros-regular.ttf", "texgyreheros-bold.ttf")


def register_fonts(folder: Path = FONTS_DIR) -> str:
    """Add the TeX Gyre Heros files of ``folder`` to matplotlib and return the family to use.

    The font manager only learns the files, once each. No default of matplotlib changes.
    When a file is missing the answer is the fallback family, with one warning.
    """
    paths = [Path(folder) / name for name in FONT_FILES]
    if not all(path.is_file() for path in paths):
        logger.warning(
            "Font files of %s not found in %s, using %s.", FONT_FAMILY, folder, FONT_FALLBACK
        )
        return FONT_FALLBACK
    known = {Path(entry.fname) for entry in font_manager.fontManager.ttflist}
    for path in paths:
        if path not in known:
            font_manager.fontManager.addfont(str(path))
    return FONT_FAMILY


_FAMILY = register_fonts()

CLASS_TINTS = (0.0, 0.45, 0.7)
"""Shares of white mixed into the palette, one per pass over it, for more classes than colours."""

# Colours by meaning. A figure names a role and never writes a colour literal.
# The first 26 come from the publication atlas. The others were added by its domains.
ROLES: dict[str, str] = {
    "observed": "#222222",
    "simulated": "#004488",
    "simulated_alt": "#BB5566",
    "reference_network": "#004488",
    "network_on_relief": "#99DDFF",
    "generated_network": "#DDAA33",
    "valid": "#004488",
    "extra": "#DDAA33",
    "missing": "#BB5566",
    "outline": "#222222",
    "outlet": "#BB5566",
    "station": "#222222",
    "no_data": "#E6E6E6",
    "seepage": "#33BBEE",
    "lake": "#4477AA",
    "river": "#0077BB",
    "drain": "#009988",
    "barrier": "#CC3311",
    "well": "#EE7733",
    "window": "#DDAA33",
    "best": "#BB5566",
    "trial": "#9AA5AD",
    "recharge": "#228833",
    "evapotranspiration": "#CCBB44",
    "storage": "#AA3377",
    "inflow": "#004488",
    "outflow": "#BB5566",
    # boundaries
    "constant_head": "#66CCEE",
    # calibration
    "band": "#BBCCEE",
    "phase": "#AA3377",
    "bounds": "#555555",
    "sim2": "#EE6677",
    "soil": "#997700",
    # context
    "piezometer": "#CC3311",
    "france": "#DDDDDD",
    "region_box": "#555555",
    "weather_cell": "#999933",
    "forcing": "#44BB99",
    # fields
    "contour": "#222222",
    # geology
    "unsaturated": "#EEDD88",
    "saturated": "#77AADD",
    "water_table": "#004488",
    "layer_interface": "#555555",
    # network
    "intermittent_reach": "#EE8866",
    "matched_reference": "#009988",
    # sfr
    "bed": "#997700",
    "aquifer_head": "#332288",
    "gain": "#0077BB",
    "loss": "#CC3311",
    "dry": "#FFAABB",
    # transport
    "reference_law": "#222222",
    "turnover": "#AA4499",
    "initial_concentration": "#DDCC77",
    "input_concentration": "#882255",
}

# Series that carry no meaning of their own take these roles in order, so no hex is written twice.
CATEGORICAL_ROLES = (
    "lake",
    "simulated_alt",
    "recharge",
    "evapotranspiration",
    "seepage",
    "storage",
    "trial",
    "well",
    "drain",
    "barrier",
)

RAMPS = {"sequential": "viridis", "diverging": "RdBu_r", "cyclic": "twilight"}

# Only the quantities whose usage wants its own ramp. Others use the scale ramp.
QUANTITY_RAMPS: dict[str, str] = {
    "head": "viridis",
    "elevation": "gist_earth",
    "depth": "viridis_r",
    "thickness": "cividis",
    "conductivity": "cividis",
    "specific_storage": "cividis",
    "concentration": "magma_r",
    "cell_flow": "RdBu_r",
    "flux_per_area": "RdBu_r",
    "flow": "RdBu_r",
}


@dataclass(frozen=True)
class Theme:
    """Every number and colour a figure takes from the look, at final printed size."""

    name: str = "default"
    family: str = _FAMILY
    fallback: str = FONT_FALLBACK
    size: float = 8.0
    title_size: float = 9.0
    small: float = 7.0
    ink: str = "black"
    muted: str = "#555555"
    face: str = "white"
    line_width: float = 0.6
    data_line_width: float = 1.2
    tick_size: float = 3.5
    minor_tick_size: float = 1.8
    minor_tick_width: float = 0.45
    tick_pad: float = 2.0
    title_pad: float = 4.0
    grid_alpha: float = 0.1
    grid_width: float = 0.5
    dpi: int = 300
    roles: dict[str, str] = field(default_factory=lambda: dict(ROLES))
    ramps: dict[str, str] = field(default_factory=lambda: dict(RAMPS))
    quantity_ramps: dict[str, str] = field(default_factory=lambda: dict(QUANTITY_RAMPS))
    math_family: str = "stixsans"

    @property
    def categorical(self) -> tuple[str, ...]:
        """The categorical palette of this theme, as hex codes."""
        return tuple(self.roles[name] for name in CATEGORICAL_ROLES)

    def class_color(self, index: int) -> str:
        """Return the colour of class ``index``: the palette, then lighter variants of it.

        Each pass over the palette mixes its colours with white by the next share of
        ``CLASS_TINTS``. Past the last pass the colours start again.
        """
        palette = self.categorical
        tint = CLASS_TINTS[(index // len(palette)) % len(CLASS_TINTS)]
        base = _rgb(palette[index % len(palette)])
        return _hex(tuple(c + (1 - c) * tint for c in base))  # type: ignore[arg-type]

    def class_colors(self, count: int) -> list[str]:
        """Return ``count`` colours, all distinct up to ``len(categorical) * len(CLASS_TINTS)``."""
        return [self.class_color(i) for i in range(count)]

    def sharing_note(self, count: int) -> str:
        """Return the sentence a legend adds when ``count`` classes outrun the distinct colours."""
        shared = count - len(self.categorical) * len(CLASS_TINTS)
        return f"{shared} classes share a colour with another" if shared > 0 else ""


def _rgb(color: str) -> tuple[float, float, float]:
    return tuple(int(color[i : i + 2], 16) / 255 for i in (1, 3, 5))  # type: ignore[return-value]


def _hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{round(min(max(c, 0.0), 1.0) * 255):02X}" for c in rgb)


def _lighten(color: str, amount: float) -> str:
    return _hex(tuple(c + (1 - c) * amount for c in _rgb(color)))  # type: ignore[arg-type]


def _grey(color: str) -> str:
    r, g, b = _rgb(color)
    level = min(max(0.2126 * r + 0.7152 * g + 0.0722 * b, 0.1), 0.75)
    return _hex((level, level, level))


def _dark_role(color: str) -> str:
    r, g, b = _rgb(color)
    if 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.4:
        return _lighten(color, 0.55)
    return color


_DEFAULT = Theme()

THEMES: dict[str, Theme] = {
    "default": _DEFAULT,
    "print": replace(
        _DEFAULT,
        name="print",
        muted="#444444",
        roles={key: _grey(value) for key, value in ROLES.items()},
        ramps={"sequential": "Greys", "diverging": "PuOr", "cyclic": "twilight"},
        quantity_ramps={k: "PuOr" if v == "RdBu_r" else "Greys" for k, v in QUANTITY_RAMPS.items()},
    ),
    "dark": replace(
        _DEFAULT,
        name="dark",
        ink="#e3eaee",
        muted="#9aabb4",
        face="#182227",
        roles={key: _dark_role(value) for key, value in ROLES.items()},
    ),
}


def get_theme(name: str) -> Theme:
    """Return the theme called ``name`` or refuse with the known names."""
    try:
        return THEMES[name]
    except KeyError:
        known = ", ".join(sorted(THEMES))
        raise ValueError(f"Unknown theme {name!r}. Known themes: {known}.") from None


_UNIT_TOKEN = re.compile(r"^([^\d\s^+-]+?)(?:\^?\{?([+-]?\d+)\}?)?$")


def _unit_token(token: str, sign: int) -> str:
    match = _UNIT_TOKEN.match(token)
    if match is None:
        return token
    base = match.group(1).replace("%", r"\%")
    power = int(match.group(2) or 1) * sign
    return base if power == 1 else f"{base}^{{{power}}}"


def unit_text(unit: str) -> str:
    """Turn ``"m3 s-1"`` or ``"mm/day"`` into mathtext with real exponents in the text font.

    Every group after a ``/`` is in the denominator, so ``"m3/s/km2"`` reads m^3 s^-1 km^-2.
    """
    text = unit.strip()
    if text in ("", "1", "-"):
        return ""
    parts: list[str] = []
    for index, group in enumerate(text.split("/")):
        parts += [_unit_token(token, 1 if index == 0 else -1) for token in group.split()]
    return r"$\mathregular{" + r"\,".join(parts) + "}$"
