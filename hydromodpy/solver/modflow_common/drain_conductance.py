"""Shared MODFLOW DRN row arithmetic: fallback conductance and discharge band."""

from __future__ import annotations


def hk_fallback_drain_conductance(
    *,
    hk: float,
    cell_area: float,
    bed_thickness: float,
    floor_m2_s: float,
) -> float:
    """High DRN conductance for a free seepage face when none is configured.

    A DRN cell removes water when the head rises above the drain elevation (here
    the cell top). MODFLOW 6 states the law as ``qdrn = drncond * (h - drnbot)``
    (``gwf-drn.f90``) and the USGS documentation gives ``CDRN`` in m2/s, so::

        C = K * cell_area / bed_thickness   (m/s * m2 / m = m2/s)

    ``bed_thickness`` is ``solver.drain_bed_thickness_m``, the clogging layer of
    a watercourse: decimetres to a metre. It used to be the LAYER thickness,
    which is a different quantity and, at 30 m on the Nancon, thirty times too
    large. It matters because the head the drain itself imposes to pass the
    recharge is ``dh = R * bed_thickness / K``, independent of the cell size: at
    30 m the drain was the limiting resistance below K = 8.3e-6 m/s, inside the
    [1e-7, 1e-3] bracket a network calibration searches. Here the drain is a
    seepage face and must never limit: K and the recharge decide where water
    surfaces, not the boundary condition.

    Proportionality to K is preserved, so the K/R invariance the criterion rests
    on is untouched; only the scale factor changes, and it is declared instead of
    borrowed from the mesh.

    ``floor_m2_s`` (``solver.drain_conductance_floor_m2_s``) exists only for a
    degenerate cell, a zero-K one for instance, whose conductance MODFLOW would
    otherwise read as no drain at all.
    """
    return max(float(hk) * float(cell_area) / float(bed_thickness), float(floor_m2_s))


def drain_discharge_band(
    *,
    top: float,
    conductance: float,
    bed_thickness: float,
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
        conductance = C * bed_thickness / D

    **The multiplier is the bed thickness, not the cell area, and it has to
    be.** The conductance this scales is already ``C = Kv*A/M`` with ``M`` the
    drain bed thickness, so ``C * M/D = Kv*A/D``, which is ``CDRN`` exactly.
    Scaling by ``A/D`` instead would leave ``Kv*A^2/(M*D)``, an m3/s where a
    conductance is m2/s, too high by ``A/M``, enough to turn every drain into a
    free seepage face and take the conductance out of the calibration.

    ``band_depth <= 0`` disables the band and returns the row untouched, which is
    what every run did before this option existed.
    """
    if band_depth <= 0.0:
        return float(top), float(conductance)
    return (
        float(top) - 0.5 * float(band_depth),
        float(conductance) * float(bed_thickness) / float(band_depth),
    )


__all__ = ["drain_discharge_band", "hk_fallback_drain_conductance"]
