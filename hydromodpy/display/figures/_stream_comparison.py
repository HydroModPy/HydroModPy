"""What the stream-network maps share: one comparison, one palette.

Three maps read the same partition of a catchment from three angles: where the
two networks agree, how far apart they run, and what the pair looks like on the
relief. They read it through one function and colour it with one palette,
because two derivations of one partition is how a map comes to disagree with
the map printed beside it, and with the numbers a trial published.

Nothing here decides anything: the partition comes from
:mod:`hydromodpy.results.derive.stream_network`, which rebuilds it through the
construction the calibration criterion scores.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display.colormaps import HIGH_CONTRAST_TRIPLET
from hydromodpy.results.derive.stream_network import (
    AGREEMENT_EXCESS,
    AGREEMENT_MISSING,
    AGREEMENT_NEITHER,
    AGREEMENT_VALID,
    NetworkComparison,
    agreement_label,
    network_comparison_from_run,
)

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run

AGREEMENT_COLORS: dict[int, str] = {
    AGREEMENT_NEITHER: "#EDEDED",
    AGREEMENT_VALID: HIGH_CONTRAST_TRIPLET[0],
    AGREEMENT_EXCESS: HIGH_CONTRAST_TRIPLET[1],
    AGREEMENT_MISSING: HIGH_CONTRAST_TRIPLET[2],
}
"""One colour per agreement class, the darkest for the agreement itself.

The three lightnesses sit far enough apart for the classes to survive a
greyscale print and every common colour-vision deficiency. The cells no network
claims cover most of a catchment and take a light grey: drawn in anything
stronger they would carry the eye instead of the three classes the maps exist
for.
"""

CRITERION_NAMES: dict[int, str] = {
    AGREEMENT_VALID: "valid",
    AGREEMENT_EXCESS: "excess",
    AGREEMENT_MISSING: "missing",
}
"""The name a trial publishes each class under, as ``n_valid`` and its two peers."""

_NOTE_BOX = {"facecolor": "white", "alpha": 0.9, "edgecolor": "#c8c8c8"}
"""The box every note of the gallery sits in."""


def comparison_from_run(
    sim: Run,
    *,
    tau_specific_ratio: float | None = None,
    diagonal_neighbors: bool | None = None,
    timestep: int | None = None,
) -> NetworkComparison:
    """Rebuild the stream comparison of one run, at the knobs a caller named.

    A knob left as None keeps the default of the criterion rather than
    repeating it here: a threshold declared twice is a map that drifts from the
    numbers it illustrates.
    """
    named = {
        "tau_specific_ratio": tau_specific_ratio,
        "diagonal_neighbors": diagonal_neighbors,
        "timestep": timestep,
    }
    return network_comparison_from_run(
        sim, **{key: value for key, value in named.items() if value is not None}
    )


def class_label(value: int) -> str:
    """Return the legend label of one agreement class, under both its names."""
    name = CRITERION_NAMES.get(int(value))
    label = agreement_label(value)
    return label if name is None else f"{name}: {label}"


def threshold_note(comparison: NetworkComparison) -> str:
    """Return the line naming the threshold the partition was cut at.

    The three classes move with it, so a map that does not carry it leaves a
    reader guessing which of several partitions is on the page.
    """
    ratio = comparison.tau_specific_ratio
    if ratio == 0.0:
        return "seepage threshold: none (tau = 0), every releasing cell is a stream"
    return f"seepage threshold: tau = {ratio:g} of the mean recharge a cell receives"


def annotate_note(ax: Axes, text: str) -> None:
    """Put one note at the foot of a map, in the box the gallery uses."""
    ax.annotate(
        text,
        xy=(0.5, 0.03),
        xycoords="axes fraction",
        ha="center",
        va="bottom",
        fontsize=9,
        bbox=_NOTE_BOX,
        zorder=10,
    )


def cell_count(mask: np.ndarray) -> str:
    """Return the size of one group of cells, written for a legend entry."""
    count = int(np.asarray(mask, dtype=bool).sum())
    return f"{count} cell" if count == 1 else f"{count} cells"


def checked_cells(values: np.ndarray, n_faces: int, label: str) -> np.ndarray:
    """Return one per-cell array, checked against the mesh the figure draws.

    The comparison is built on the persisted topography and the figure draws
    the persisted connectivity; a run whose two disagree would otherwise paint
    one cell with the class of another.
    """
    array = np.asarray(values).reshape(-1)
    if array.size != n_faces:
        raise ValueError(f"the {label} holds {array.size} cells, the mesh holds {n_faces}.")
    return array


__all__ = (
    "AGREEMENT_COLORS",
    "CRITERION_NAMES",
    "annotate_note",
    "cell_count",
    "checked_cells",
    "class_label",
    "comparison_from_run",
    "threshold_note",
)
