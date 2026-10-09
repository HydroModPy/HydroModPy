"""Particle pathlines a run tracked, read from its ``particles`` group.

The MODFLOW 6 PRT and MODPATH extractors write the same vectorized layout, so
one reader serves both backends and both tracking directions. The figures, the
map overlay and the solver tests read pathlines through here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from hydromodpy.results.run import Run

__all__ = [
    "PARTICLE_COLUMNS",
    "has_particle_tracks",
    "particle_frame",
    "particle_time_to_days",
    "read_particle_tracks",
    "travel_time",
]

PARTICLE_COLUMNS: tuple[str, ...] = ("particle", "step", "x", "y", "z", "time_days")
"""Columns of :func:`particle_frame` every run gives; ``status`` and ``reason`` follow when stored."""

_DAYS_PER_YEAR = 365.25
# Tracking-time unit written by the extractors on the ``particles`` group,
# expressed in days. Both MODFLOW 6 PRT and MODPATH record "days".
_DAYS_PER_UNIT: dict[str, float] = {
    "second": 1.0 / 86400.0,
    "seconds": 1.0 / 86400.0,
    "minute": 1.0 / 1440.0,
    "minutes": 1.0 / 1440.0,
    "hour": 1.0 / 24.0,
    "hours": 1.0 / 24.0,
    "day": 1.0,
    "days": 1.0,
    "year": _DAYS_PER_YEAR,
    "years": _DAYS_PER_YEAR,
}


def has_particle_tracks(run: Run, *, timed: bool = False) -> bool:
    """Return whether at least one particle moved, reading two steps per particle.

    An extractor may leave an empty ``particles`` group behind, which
    ``Run.has_field("particles")`` counts as present, or record release points
    only. A pathline needs two positions, and the extractors pad each one with
    NaN after its last step, so the first two steps tell. ``timed`` also asks
    for a clock on those two steps, which a travel time is read from.
    """
    names = ("x", "y", "time") if timed else ("x", "y")
    sz = run._catalog.open_zarr(run.sim_id)
    try:
        grp = sz.root.get("particles")
        if grp is None or any(name not in grp for name in names):
            return False
        heads = [np.atleast_2d(np.asarray(grp[name][..., :2], dtype="float64")) for name in names]
    finally:
        sz.close()
    n_particles = min(head.shape[0] for head in heads)
    if n_particles == 0 or min(head.shape[1] for head in heads) < 2:
        return False
    finite = np.logical_and.reduce([np.isfinite(head[:n_particles, :2]) for head in heads])
    return bool(finite.all(axis=1).any())


def particle_time_to_days(run: Run) -> float:
    """Return the factor converting stored particle times into days.

    Reads the ``time_units`` attribute the extractors write on the
    ``particles`` group. Defaults to 1.0 (days), the unit both backends use.
    """
    sz = run._catalog.open_zarr(run.sim_id)
    try:
        grp = sz.root.get("particles")
        unit = str(dict(grp.attrs).get("time_units", "days")).strip().lower() if grp else "days"
    finally:
        sz.close()
    return _DAYS_PER_UNIT.get(unit, 1.0)


def read_particle_tracks(run: Run) -> list[np.ndarray]:
    """Return one ``(n_steps, 4)`` ``x, y, z, time`` array per particle.

    The store layout is vectorized ``x``, ``y``, ``z`` and ``time`` arrays
    shaped ``(n_particles, max_steps)`` under ``particles/``, padded with
    NaN. Padding is stripped here so callers get clean polylines. ``time``
    stays in the stored unit; use :func:`particle_time_to_days` to convert.
    """
    sz = run._catalog.open_zarr(run.sim_id)
    try:
        grp = sz.root.get("particles")
        if grp is None or "x" not in grp or "y" not in grp:
            return []
        x = np.atleast_2d(np.asarray(grp["x"], dtype="float64"))
        y = np.atleast_2d(np.asarray(grp["y"], dtype="float64"))
        z = (
            np.atleast_2d(np.asarray(grp["z"], dtype="float64"))
            if "z" in grp
            else np.full_like(x, np.nan)
        )
        t = (
            np.atleast_2d(np.asarray(grp["time"], dtype="float64"))
            if "time" in grp
            else np.full_like(x, np.nan)
        )
        n = min(x.shape[0], y.shape[0], z.shape[0], t.shape[0])
        tracks: list[np.ndarray] = []
        for i in range(n):
            valid = np.isfinite(x[i]) & np.isfinite(y[i])
            if valid.sum() < 2:
                continue
            tracks.append(np.column_stack((x[i, valid], y[i, valid], z[i, valid], t[i, valid])))
        return tracks
    finally:
        sz.close()


def particle_frame(run: Run) -> pd.DataFrame:
    """Return every recorded position of every particle, one row per position.

    Columns: ``particle`` (index of the particle, from 0), ``step`` (index of
    the record along its path, from 0), ``x``, ``y`` (mesh coordinates, in
    the CRS of the run), ``z`` (elevation, m) and ``time_days`` (absolute time
    of the simulation, in days). ``status`` and ``reason`` follow when the
    solver file carried them, as the solver codes. The padding the store adds
    after the last record of a particle is left out. ``frame.attrs`` holds the
    ``source_solver`` and the ``source_file`` the paths were read from. A run
    with no particle process gives an empty frame with the same columns.
    """
    sz = run._catalog.open_zarr(run.sim_id)
    try:
        grp = sz.root.get("particles")
        if grp is None or "x" not in grp or "y" not in grp:
            return pd.DataFrame(
                {
                    name: pd.Series(dtype="int64" if name in ("particle", "step") else "float64")
                    for name in PARTICLE_COLUMNS
                }
            )
        attrs = dict(grp.attrs)
        arrays = {
            name: np.atleast_2d(np.asarray(grp[name], dtype="float64"))
            for name in ("x", "y", "z", "time", "status", "reason")
            if name in grp
        }
    finally:
        sz.close()
    unit = str(attrs.get("time_units", "days")).strip().lower()
    to_days = _DAYS_PER_UNIT.get(unit, 1.0)
    x = arrays["x"]
    blank = np.full_like(x, np.nan)
    kept = np.isfinite(x) & np.isfinite(arrays["y"])
    particle, step = np.nonzero(kept)
    columns: dict[str, np.ndarray] = {
        "particle": particle.astype("int64"),
        "step": step.astype("int64"),
        "x": x[kept],
        "y": arrays["y"][kept],
        "z": arrays.get("z", blank)[kept],
        "time_days": arrays.get("time", blank)[kept] * to_days,
    }
    for extra in ("status", "reason"):
        if extra in arrays:
            columns[extra] = arrays[extra][kept]
    frame = pd.DataFrame(columns)
    frame.attrs["source_solver"] = attrs.get("source_solver")
    frame.attrs["source_file"] = attrs.get("source_file")
    return frame


def travel_time(track: np.ndarray) -> float:
    """Return the elapsed tracking time along one pathline, in stored units."""
    times = track[:, 3]
    finite = times[np.isfinite(times)]
    if finite.size < 2:
        return float("nan")
    return float(abs(finite[-1] - finite[0]))
