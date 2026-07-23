"""Particle pathlines drawn over the catchment footprint.

Reads the vectorized particle arrays written by the MODFLOW 6 PRT and the
MODPATH extractors, so the same figure serves both backends and both
tracking directions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.map_axes import (
    RELATIVE_MAP_COLORBAR_LABEL_SIZE,
    RELATIVE_MAP_COLORBAR_TICK_SIZE,
    style_relative_km_axes,
)
from hydromodpy.display.overlays import apply_overlays

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run

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


def particle_time_to_days(sim: Run) -> float:
    """Return the factor converting stored particle times into days.

    Reads the ``time_units`` attribute the extractors write on the
    ``particles`` group. Defaults to 1.0 (days), the unit both backends use.
    """
    sz = sim._catalog.open_zarr(sim.sim_id)
    try:
        grp = sz.root.get("particles")
        unit = str(dict(grp.attrs).get("time_units", "days")).strip().lower() if grp else "days"
    finally:
        sz.close()
    return _DAYS_PER_UNIT.get(unit, 1.0)


def read_particle_tracks(sim: Run) -> list[np.ndarray]:
    """Return one ``(n_steps, 4)`` ``x, y, z, time`` array per particle.

    The store layout is vectorized ``x``, ``y``, ``z`` and ``time`` arrays
    shaped ``(n_particles, max_steps)`` under ``particles/``, padded with
    NaN. Padding is stripped here so callers get clean polylines. ``time``
    stays in the stored unit; use :func:`particle_time_to_days` to convert.
    """
    sz = sim._catalog.open_zarr(sim.sim_id)
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


@register
class ParticleTracks(BaseFigure):
    """Plan view of particle pathlines, coloured by travel time."""

    spec = FigureSpec(
        name="particle_tracks",
        title="Particle pathlines",
        kind="particles",
        required_fields=("particles",),
        default_figsize=(7.0, 5.5),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        cmap: str = "magma_r",
        lw: float = 0.7,
        max_tracks: int = 500,
        color_by: str = "travel_time",
        overlays: tuple[str, ...] | list[str] | None = None,
        **_,
    ) -> Axes:
        from matplotlib.collections import LineCollection

        tracks = read_particle_tracks(sim)
        if not tracks:
            raise ValueError(f"no particle pathlines stored for sim {sim.sim_id}")

        step = max(1, len(tracks) // max_tracks)
        selected = tracks[::step]
        segments = [track[:, :2] for track in selected]

        to_days = particle_time_to_days(sim)
        travel_years = np.array(
            [_travel_time(track) * to_days / _DAYS_PER_YEAR for track in selected],
            dtype="float64",
        )
        has_time = bool(np.isfinite(travel_years).any()) and color_by == "travel_time"

        collection = LineCollection(segments, linewidths=lw, cmap=cmap)
        if has_time:
            collection.set_array(travel_years)
        else:
            collection.set_color("0.2")
        ax.add_collection(collection)
        ax.set_aspect("equal", adjustable="datalim")
        ax.autoscale_view()

        if has_time:
            cbar = ax.figure.colorbar(collection, ax=ax, fraction=0.046, pad=0.04)
            cbar.set_label("Travel time (years)", fontsize=RELATIVE_MAP_COLORBAR_LABEL_SIZE)
            cbar.ax.tick_params(labelsize=RELATIVE_MAP_COLORBAR_TICK_SIZE)

        apply_overlays(ax, sim, ("watershed", "seepage") if overlays is None else overlays)
        style_relative_km_axes(ax)
        shown = f"{len(selected)} of {len(tracks)}" if step > 1 else f"{len(tracks)}"
        ax.set_title(f"{self.spec.title} - {sim.name or sim.sim_id}\n{shown} pathlines")
        handles, _labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(loc="best", fontsize=8, framealpha=0.9)
        return ax


def _travel_time(track: np.ndarray) -> float:
    """Return the elapsed tracking time along one pathline, in stored units."""
    times = track[:, 3]
    finite = times[np.isfinite(times)]
    if finite.size < 2:
        return float("nan")
    return float(abs(finite[-1] - finite[0]))
