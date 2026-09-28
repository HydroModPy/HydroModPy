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
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.display.maps.axes import overlay_watershed_contour
from hydromodpy.display.maps.mesh_geometry import face_centroids, face_polygons
from hydromodpy.results.derive.snapped_network import (
    snap_settings_of_run,
    stored_snapped_network,
)
from hydromodpy.results.run.particles import read_particle_tracks

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run

logger = get_logger(__name__)


class OverlayUnavailable(RuntimeError):
    """Raised when a requested overlay has no data in this run."""


def _resolve_timestep(sim: Run, timestep: int | None) -> int:
    from hydromodpy.display.maps.ugrid import last_timestep

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
    tracks = read_particle_tracks(sim)
    if not tracks:
        raise OverlayUnavailable("run has no particle pathlines")
    step = max(1, len(tracks) // max_tracks)
    for track in tracks[::step]:
        ax.plot(track[:, 0], track[:, 1], lw=0.5, color="0.15", alpha=0.7, zorder=4)


_MAPPED_ROLES: dict[str, str] = {
    "reference": "maximal",
    "reference_permanent": "minimal",
}
"""The mapped network roles, and the snapped map a run stores for each."""

SNAPPED_MARKER_SIZE = 4.0
"""Marker area, in points squared, of one snapped cell on a map."""


@dataclass(frozen=True)
class NetworkMap:
    """The network a map draws for one role, and which map of it that is.

    ``kind`` is ``"snapped"`` when the frame is the snapped map the run
    stored, one point per mapped cell at the centre of the cell it moved
    onto, and ``"raw"`` when it is the network as persisted.
    """

    role: str
    frame: Any
    kind: str
    snap_mode: str

    @property
    def snapped(self) -> bool:
        """True when the frame is the snapped map."""
        return self.kind == "snapped"

    def label(self) -> str | None:
        """Return the line naming the map drawn, or None when the snap is off."""
        if self.role not in _MAPPED_ROLES or self.snap_mode == "off":
            return None
        if self.snapped:
            return "snapped map ([geographic.snap_streams] apply)"
        if self.snap_mode == "apply":
            return "raw map: the run stored no snapped map"
        return f"raw map ([geographic.snap_streams] {self.snap_mode})"


def network_map_of_role(sim: Run, role: str = "reference") -> NetworkMap:
    """Return the network a map draws for one role.

    ``[geographic.snap_streams]`` applies to every consumer of the mapped
    network. In ``apply`` the ``reference`` and ``reference_permanent`` roles
    draw the snapped map the run stored
    (:mod:`~hydromodpy.results.derive.snapped_network`), the map the network
    metrics read. In ``diagnose`` and ``off``, and for any other role, the
    raw network is drawn. A run in ``apply`` that stored no snapped map draws
    the raw one and says so.
    """
    settings = snap_settings_of_run(sim)
    snap_mode = "off" if settings is None else str(settings.mode)
    map_role = _MAPPED_ROLES.get(role)
    if map_role is not None and snap_mode == "apply":
        snapped = stored_snapped_network(sim, map_role=map_role)
        if snapped is not None:
            return NetworkMap(role=role, frame=snapped, kind="snapped", snap_mode=snap_mode)
        logger.warning(
            "Run %s: [geographic.snap_streams] mode = 'apply', but the run stored no snapped "
            "%s map. The %s network is drawn raw.",
            getattr(sim, "sim_id", "?"),
            map_role,
            role,
        )
    frame = sim.hydrographic_network(role)
    return NetworkMap(role=role, frame=frame, kind="raw", snap_mode=snap_mode)


def plot_network_map(
    ax: Axes,
    network: NetworkMap,
    frame: Any | None = None,
    *,
    color: str,
    linewidth: float,
    alpha: float,
    zorder: int,
    label: str | None = None,
) -> None:
    """Draw a network map: lines when raw, one square per cell when snapped.

    ``frame`` replaces ``network.frame`` when the caller reprojected it.
    """
    gdf = network.frame if frame is None else frame
    style: dict[str, Any] = {"color": color, "alpha": alpha, "zorder": zorder}
    if label is not None:
        style["label"] = label
    if network.snapped:
        gdf.plot(ax=ax, marker="s", markersize=SNAPPED_MARKER_SIZE, linewidth=0.0, **style)
    else:
        gdf.plot(ax=ax, linewidth=linewidth, **style)


def draw_network(ax: Axes, sim: Run, *, role: str = "reference", **_) -> None:
    """Reference (or generated) hydrographic network.

    A mapped role draws the snapped map under ``[geographic.snap_streams]
    mode = "apply"`` (:func:`network_map_of_role`); the artist's label names
    the map drawn.
    """
    if not sim.has_hydrographic_network(role):
        raise OverlayUnavailable(f"run has no '{role}' hydrographic network")
    network = network_map_of_role(sim, role)
    if network.frame is None or network.frame.empty:
        raise OverlayUnavailable(f"'{role}' hydrographic network is empty")
    note = network.label()
    plot_network_map(
        ax,
        network,
        color="tab:blue",
        linewidth=0.9,
        alpha=0.9,
        zorder=4,
        label=None if note is None else f"{role} network, {note}",
    )
    if note is not None:
        logger.info("Overlay 'network' draws the %s network: %s.", role, note)


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


__all__ = [
    "OVERLAYS",
    "SNAPPED_MARKER_SIZE",
    "NetworkMap",
    "OverlayUnavailable",
    "apply_overlays",
    "network_map_of_role",
    "plot_network_map",
]
