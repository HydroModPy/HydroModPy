"""Shared MODFLOW DRN row arithmetic: fallback conductance and discharge band."""

from __future__ import annotations

import numpy as np


def hk_fallback_drain_conductance(
    *,
    hk: float,
    cell_area: float,
    top_thickness: float,
    floor_m2_s: float,
) -> float:
    """High DRN conductance for a free seepage face when none is configured.

    A DRN cell removes water when the head rises above the drain elevation (here
    the cell top), with flux = conductance * (head - drain_elevation); conductance
    has units m2/s. When the user gives no conductance we fabricate a high one so
    the cell behaves like a free seepage face, using

        C = K * cell_area / top_layer_thickness   (m/s * m2 / m = m2/s).

    ``floor_m2_s`` (``solver.drain_conductance_floor_m2_s``) exists only for
    degenerate cells: a zero-thickness cell would divide by zero, a zero-K cell
    would emit a zero conductance MODFLOW reads as no drain at all. A degenerate
    thickness falls back to one metre for the same reason, and the floor then
    catches whatever the product gives.
    """
    length = float(top_thickness)
    if not np.isfinite(length) or length <= 0.0:
        length = 1.0
    return max(float(hk) * float(cell_area) / length, float(floor_m2_s))


def drain_discharge_band(
    *,
    top: float,
    conductance: float,
    top_thickness: float,
    band_depth: float,
) -> tuple[float, float]:
    """Return the (elevation, conductance) one drain cell gets for a band of depth D.

    A single drain elevation states that the land inside a cell is flat. The one
    remedy the USGS documents for that is a sub-cell discharge band, not an
    elevation edit: UZF1 exposes ``SURFDEP``, "a real value equal to the average
    undulation depth within a finite-difference cell", and MODFLOW 6 carries the
    same idea into DRN as ``DDRN``, with ``HDRN = land surface - DDRN/2`` and
    ``CDRN = Kv*A/DDRN``. The conductance grows with D because "the area through
    which flow occurs increases as the head at the drain increases".

    So, with ``D = band_depth`` metres and ``C`` the conductance the run would
    otherwise use::

        elevation = top - D / 2
        conductance = C * top_thickness / D

    **The multiplier is the layer thickness, not the cell area, and it has to
    be.** The conductance this scales is already ``C = Kv*A/b`` with ``b`` the
    top-layer thickness, so ``C * b/D = Kv*A/D``, which is ``CDRN`` exactly.
    Scaling by ``A/D`` instead would leave ``Kv*A^2/(b*D)``, an m3/s where a
    conductance is m2/s, too high by ``A/b``: on the Nancon (A = 2500 m2,
    b = 30 m) that is a factor of 83, enough to turn every drain into a free
    seepage face and take the conductance out of the calibration.

    ``band_depth <= 0`` disables the band and returns the row untouched, which is
    what every run did before this option existed.
    """
    if band_depth <= 0.0:
        return float(top), float(conductance)
    return (
        float(top) - 0.5 * float(band_depth),
        float(conductance) * float(top_thickness) / float(band_depth),
    )


__all__ = ["drain_discharge_band", "hk_fallback_drain_conductance"]
