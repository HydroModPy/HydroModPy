"""Shared MODFLOW DRN fallback conductance derived from hydraulic conductivity."""

from __future__ import annotations

import numpy as np


def hk_fallback_drain_conductance(*, hk: float, cell_area: float, top_thickness: float) -> float:
    """High DRN conductance for a free seepage face when none is configured.

    A DRN cell removes water when the head rises above the drain elevation (here
    the cell top), with flux = conductance * (head - drain_elevation); conductance
    has units m2/s. When the user gives no conductance we fabricate a high one so
    the cell behaves like a free seepage face, using

        C = K * cell_area / top_layer_thickness   (m/s * m2 / m = m2/s).

    The 1e-12 floor exists only for degenerate (zero-thickness or zero-K) cells.
    """
    length = float(top_thickness)
    if not np.isfinite(length) or length <= 0.0:
        length = 1.0
    return max(float(hk) * float(cell_area) / length, 1e-12)


__all__ = ["hk_fallback_drain_conductance"]
