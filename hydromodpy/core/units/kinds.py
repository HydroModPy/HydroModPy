"""Quantity kinds: what a stored variable measures and how a figure shows it.

Each registered variable names one kind. The kind gives the stored unit, the
unit a figure shows, the sign, and how a map reduces a layered variable.
Nothing here is written to a run store.
"""

from __future__ import annotations

from dataclasses import dataclass

SIGNS = ("positive", "negative", "both")
SCALES = ("sequential", "diverging", "cyclic", "categorical")
SEQUENTIAL, DIVERGING, CYCLIC, CATEGORICAL = SCALES
LAYER_REDUCTIONS = ("sum", "top", None)


@dataclass(frozen=True, slots=True)
class QuantityKind:
    """One kind of quantity.

    ``per_area`` means a map divides the value by the cell area before it
    converts to the display unit. ``layers`` says how a layered variable is
    reduced to one value per cell on a map. ``isolines`` means a map draws
    contour lines by default. ``cumulates_to`` names the kind a running sum
    over time gives. ``extensive`` means the values of cells add up over a zone.
    """

    stored_unit: str
    display_unit: str
    sign: str = "positive"
    log: bool = False
    cyclic: bool = False
    categorical: bool = False
    per_area: bool = False
    layers: str | None = "top"
    drawable: bool = True
    isolines: bool = False
    cumulates_to: str | None = None
    extensive: bool = False

    def __post_init__(self) -> None:
        if self.sign not in SIGNS:
            raise ValueError(f"sign must be one of {SIGNS}, got {self.sign!r}")
        if self.layers not in LAYER_REDUCTIONS:
            raise ValueError(f"layers must be one of {LAYER_REDUCTIONS}, got {self.layers!r}")


QUANTITY_KINDS: dict[str, QuantityKind] = {
    "head": QuantityKind("m", "m", isolines=True),
    "elevation": QuantityKind("m", "m", layers=None),
    "depth": QuantityKind("m", "m"),
    "thickness": QuantityKind("m", "m", layers="sum"),
    "distance": QuantityKind("m", "m", layers=None),
    "cell_flow": QuantityKind(
        "m3 s-1",
        "mm/day",
        sign="both",
        per_area=True,
        layers="sum",
        cumulates_to="depth",
        extensive=True,
    ),
    "flux_per_area": QuantityKind(
        "m s-1", "mm/day", sign="both", layers="sum", cumulates_to="depth"
    ),
    "flow": QuantityKind("m3 s-1", "m3 s-1", layers=None, cumulates_to="volume"),
    "conductivity": QuantityKind("m s-1", "m s-1", log=True),
    "fraction": QuantityKind("1", "1"),
    "ratio": QuantityKind("1", "1"),
    "specific_storage": QuantityKind("m-1", "m-1", log=True),
    "angle": QuantityKind("degree", "degree"),
    "azimuth": QuantityKind("degree", "degree", sign="both", cyclic=True),
    "concentration": QuantityKind("kg m-3", "mg/L"),
    "mass_flux": QuantityKind("kg s-1", "g/day", layers="sum", extensive=True),
    "volume": QuantityKind("m3", "m3", layers=None),
    "area": QuantityKind("m2", "m2", layers=None),
    "score": QuantityKind("1", "1", layers=None),
    "category": QuantityKind("1", "1", categorical=True),
    "index": QuantityKind("1", "1", layers=None, drawable=False),
}


def scale_of(kind: QuantityKind, sign: str | None = None) -> str:
    """Return the colour scale family of a kind, with an optional sign override."""
    if kind.categorical:
        return CATEGORICAL
    if kind.cyclic:
        return CYCLIC
    return DIVERGING if (sign or kind.sign) == "both" else SEQUENTIAL
