"""Named overlays that any spatial figure can draw on top of its field.

The legacy scripts composed their maps by hand: a water-table raster, the
seepage cells in black, the pathlines, the catchment outline. Here that
composition is declarative and solver-agnostic. A figure declares which
overlays it accepts, a config asks for them by name::

    [display.overrides.watertable_depth_map]
    overlays = ["seepage", "particles", "wells"]

Every overlay reads only the public :class:`~hydromodpy.results.run.Run`
interface, so it works the same on MODFLOW-NWT, MODFLOW 6 and Boussinesq
runs, on structured DIS grids and on unstructured DISV meshes. An overlay
whose data the run does not carry raises :class:`OverlayUnavailable`, which
the caller turns into an explicit skip.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display.map_axes import overlay_watershed_contour
from hydromodpy.display.mesh_geometry import face_centroids, face_polygons

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


class OverlayUnavailable(RuntimeError):
    """Raised when a requested overlay has no data in this run."""


def _resolve_timestep(sim: Run, timestep: int | None) -> int:
    from hydromodpy.display.ugrid import last_timestep

    return last_timestep(sim) if timestep is None else timestep


def draw_watershed(ax: Axes, sim: Run, *, timestep: int | None = None, **_) -> None:
    """Outline of the delineated catchment."""
    overlay_watershed_contour(ax, sim, color="black", linewidth=1.4, alpha=0.9)


def draw_seepage(ax: Axes, sim: Run, *, timestep: int | None = None, **_) -> None:
    """Cells where the water table reaches the land surface, in solid black."""
    from matplotlib.collections import PolyCollection

    if not sim.has_field("seepage_mask"):
        raise OverlayUnavailable("run has no seepage_mask field")
    mask = np.asarray(sim.field("seepage_mask", timestep=_resolve_timestep(sim, timestep)))
    mask = mask.ravel() > 0
    if not mask.any():
        return
    polygons = face_polygons(sim)
    ax.add_collection(
        PolyCollection(
            [polygons[i] for i in np.flatnonzero(mask)],
            facecolors="black",
            edgecolors="none",
            alpha=0.85,
            zorder=3,
            label="Seepage",
        )
    )


def draw_particles(ax: Axes, sim: Run, *, max_tracks: int = 400, **_) -> None:
    """Particle pathlines projected in plan view."""
    from hydromodpy.display.figures.particle_tracks import read_particle_tracks

    tracks = read_particle_tracks(sim)
    if not tracks:
        raise OverlayUnavailable("run has no particle pathlines")
    step = max(1, len(tracks) // max_tracks)
    for track in tracks[::step]:
        ax.plot(track[:, 0], track[:, 1], lw=0.5, color="0.15", alpha=0.7, zorder=4)


def draw_network(ax: Axes, sim: Run, *, role: str = "reference", **_) -> None:
    """Reference (or generated) hydrographic network."""
    if not sim.has_hydrographic_network(role):
        raise OverlayUnavailable(f"run has no '{role}' hydrographic network")
    gdf = sim.hydrographic_network(role)
    if gdf is None or gdf.empty:
        raise OverlayUnavailable(f"'{role}' hydrographic network is empty")
    gdf.plot(ax=ax, color="tab:blue", linewidth=0.9, alpha=0.9, zorder=4)


def draw_wells(ax: Axes, sim: Run, *, timestep: int | None = None, **_) -> None:
    """Pumping and injection cells, read from the well budget field.

    Reading the budget rather than the config keeps the overlay solver- and
    config-agnostic: any run whose solver wrote a well package shows its
    wells, wherever they were declared from.
    """
    if not sim.has_field("well"):
        raise OverlayUnavailable("run has no well budget field")
    step = _resolve_timestep(sim, timestep)
    flux = _flatten_cells(np.asarray(sim.field("well", timestep=step), dtype="float64"))
    active = np.flatnonzero(np.isfinite(flux) & (np.abs(flux) > 0.0))
    if active.size == 0:
        # A well is often idle at the last stress period while the package
        # exists all along. Fall back to every cell that pumps at any time, so
        # the marker never silently vanishes on a seasonal schedule.
        flux = _peak_well_flux(sim)
        active = np.flatnonzero(np.isfinite(flux) & (np.abs(flux) > 0.0))
    if active.size == 0:
        raise OverlayUnavailable("well package present but no cell ever carries a rate")
    centroids = face_centroids(sim)[active]
    pumping = flux[active] < 0.0
    for selection, marker, label in (
        (pumping, "v", "Pumping well"),
        (~pumping, "^", "Injection well"),
    ):
        if not selection.any():
            continue
        ax.scatter(
            centroids[selection, 0],
            centroids[selection, 1],
            marker=marker,
            s=70,
            facecolors="white",
            edgecolors="black",
            linewidths=1.2,
            zorder=6,
            label=label,
        )


def _flatten_cells(values: np.ndarray) -> np.ndarray:
    """Collapse every leading (layer) axis so one value remains per face."""
    if values.ndim > 1:
        return np.nansum(values, axis=tuple(range(values.ndim - 1)))
    return values


def _peak_well_flux(sim: Run) -> np.ndarray:
    """Return the signed well rate of largest magnitude over the whole run."""
    n_steps = sim.n_timesteps or 1
    peak: np.ndarray | None = None
    for step in range(n_steps):
        flux = _flatten_cells(np.asarray(sim.field("well", timestep=step), dtype="float64"))
        if peak is None:
            peak = flux
            continue
        replace = np.abs(np.nan_to_num(flux)) > np.abs(np.nan_to_num(peak))
        peak = np.where(replace, flux, peak)
    return np.zeros(0) if peak is None else peak


def draw_outlet(ax: Axes, sim: Run, **_) -> None:
    """Catchment outlet marker."""
    try:
        x, y = sim.outlet
    except Exception as exc:
        raise OverlayUnavailable("run has no outlet coordinates") from exc
    ax.scatter(
        [x],
        [y],
        marker="*",
        s=160,
        facecolors="crimson",
        edgecolors="black",
        zorder=6,
        label="Outlet",
    )


OVERLAYS: dict[str, Callable[..., None]] = {
    "watershed": draw_watershed,
    "seepage": draw_seepage,
    "particles": draw_particles,
    "network": draw_network,
    "wells": draw_wells,
    "outlet": draw_outlet,
}


def apply_overlays(
    ax: Axes,
    sim: Run,
    names: Iterable[str],
    *,
    timestep: int | None = None,
) -> list[str]:
    """Draw every named overlay on ``ax``; return the ones actually drawn.

    An unknown name is a configuration error and raises. An overlay whose
    data the run lacks is skipped and reported through the return value, so
    the same figure declaration works across runs with different processes.
    """
    from hydromodpy.core.logging import get_logger

    logger = get_logger(__name__)
    drawn: list[str] = []
    for name in names:
        try:
            painter = OVERLAYS[name]
        except KeyError as exc:
            raise KeyError(
                f"unknown overlay '{name}' (available: {', '.join(sorted(OVERLAYS))})"
            ) from exc
        try:
            painter(ax, sim, timestep=timestep)
        except OverlayUnavailable as exc:
            logger.info("Overlay '%s' skipped: %s.", name, exc)
            continue
        drawn.append(name)
    return drawn


__all__ = ["apply_overlays", "OVERLAYS", "OverlayUnavailable"]
