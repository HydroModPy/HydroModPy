"""What the heads figure needs, rebuilt from a finished run.

``observed_network_heads_map`` draws the mapped lines, the trace the heads
rule draws down the criterion graph, and how each head landed. It is about
the heads rule specifically, not about whichever rule actually scored the
run, so this view always redraws under ``"heads"``: with the run's own sealed
radius and area when it was scored that way, the criterion's defaults
otherwise. Everything else it reads from the run's sealed network output
(:mod:`hydromodpy.results.derive.network_criterion_settings`), through the
one redraw every other network figure shares
(:func:`hydromodpy.results.derive.stream_network.network_comparison_from_run`).

A run that carries the permanent reaches of its map is drawn from both sets of
heads, as a calibration scores its maximal map: the full network's trace, and
the permanent network's trace on top of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.stream_criterion_defaults import STREAM_CRITERION_DEFAULTS
from hydromodpy.results.derive.network_criterion_settings import network_criterion_settings
from hydromodpy.results.derive.stream_network import network_comparison_from_run

if TYPE_CHECKING:
    from hydromodpy.core.stream_geometry import NetworkGeometry
    from hydromodpy.results.run import Run

__all__ = ("MapHeads", "NetworkHeadsView", "network_heads_view_from_run")

PERMANENT_ROLE = "reference_permanent"


@dataclass(frozen=True, slots=True)
class MapHeads:
    """The heads trace of one mapped network.

    ``traced`` is a ``(n_cells,)`` bool mask on the criterion graph.
    ``head_xy`` and ``landing_xy`` pair row for row, kept heads only;
    ``lost_xy`` are the free ends no landing cell was found for. ``forced_xy``
    are the centres of the forced heads, the foot of each dam of the run: they
    are not free ends of the map and have no landing. ``indices`` is
    :attr:`hydromodpy.core.stream_heads.HeadTrace.indices`.
    """

    traced: np.ndarray
    head_xy: np.ndarray
    landing_xy: np.ndarray
    lost_xy: np.ndarray
    forced_xy: np.ndarray
    indices: dict[str, float]


@dataclass(frozen=True, slots=True)
class NetworkHeadsView:
    """The heads trace of a run, and what draws it.

    ``mapped_lines_xy`` is one ``(n, 2)`` array per mapped line, reprojected to
    the mesh CRS. ``catchment`` is a ``(n_cells,)`` bool mask on the criterion
    graph. ``full`` is the trace of the mapped network; ``permanent`` the
    trace of its permanent reaches, None when the run carries none.
    """

    mapped_lines_xy: tuple[np.ndarray, ...]
    catchment: np.ndarray
    full: MapHeads
    permanent: MapHeads | None
    settings_note: str
    redrawn_as_heads: bool
    """True when the run was not sealed under the heads rule and this view
    forced it, with the criterion's default radius and area."""


def network_heads_view_from_run(
    sim: Run,
    *,
    role: str = "reference",
    output: str | None = None,
) -> NetworkHeadsView:
    """Return the heads trace of a run, drawn under the heads rule.

    The seepage threshold, the neighbour graph and the positional accuracy are
    the run's sealed network output (:func:`network_criterion_settings`), or
    the criterion's defaults when it sealed none. The rasterisation is always
    ``"heads"``; its radius and area are the run's sealed ones when the output
    was scored with ``"heads"``, the criterion's defaults otherwise: the
    figure exists to show that rule, not whichever one scored the run.
    """
    settings = network_criterion_settings(sim, output=output)
    under_heads = settings.observed_rasterization == "heads"
    knobs = {
        "tau_specific_ratio": settings.tau_specific_ratio,
        "diagonal_neighbors": settings.diagonal_neighbors,
        "observed_rasterization": "heads",
        "observed_position_accuracy_m": settings.observed_position_accuracy_m,
        "heads_snap_radius_m": (
            settings.heads_snap_radius_m
            if under_heads
            else STREAM_CRITERION_DEFAULTS.heads_snap_radius_m
        ),
        "heads_min_drained_area_km2": (
            settings.heads_min_drained_area_km2
            if under_heads
            else STREAM_CRITERION_DEFAULTS.heads_min_drained_area_km2
        ),
    }
    comparison = network_comparison_from_run(sim, role=role, **knobs)
    permanent = None
    if role != PERMANENT_ROLE and sim.has_hydrographic_network(PERMANENT_ROLE):
        permanent = _map_heads(
            sim, network_comparison_from_run(sim, role=PERMANENT_ROLE, **knobs).geometry
        )
    return NetworkHeadsView(
        mapped_lines_xy=_lines_in_mesh_crs(sim.hydrographic_network(role), sim.mesh.crs),
        catchment=np.asarray(comparison.geometry.catchment, dtype=bool),
        full=_map_heads(sim, comparison.geometry),
        permanent=permanent,
        settings_note=settings.note(),
        redrawn_as_heads=not under_heads,
    )


def _map_heads(sim: Run, geometry: NetworkGeometry) -> MapHeads:
    """Return the heads trace a redrawn geometry holds."""
    trace = geometry.heads
    if trace is None:
        raise ValueError(f"{sim.sim_id}: the heads redraw built no trace.")
    kept = trace.head_cell >= 0
    centres = np.asarray(geometry.metric.centroids, dtype=float)[:, :2]
    return MapHeads(
        traced=np.asarray(trace.traced, dtype=bool),
        head_xy=trace.head_xy[kept],
        landing_xy=centres[trace.head_cell[kept]],
        lost_xy=trace.head_xy[~kept],
        forced_xy=centres[trace.forced_cell],
        indices=trace.indices,
    )


def _lines_in_mesh_crs(network, mesh_crs: str | None) -> tuple[np.ndarray, ...]:
    """Return every line of a mapped network as one ``(n, 2)`` array, mesh CRS."""
    if network is None or network.empty:
        return ()
    gdf = network
    if mesh_crs and network.crs is not None and str(network.crs) != str(mesh_crs):
        gdf = network.to_crs(mesh_crs)
    lines: list[np.ndarray] = []
    for geometry in gdf.geometry:
        lines.extend(_line_parts(geometry))
    return tuple(lines)


def _line_parts(geometry) -> list[np.ndarray]:
    """Flatten one geometry into its ``(n, 2)`` line coordinate arrays."""
    if geometry is None or geometry.is_empty:
        return []
    parts = getattr(geometry, "geoms", None)
    if parts is not None:
        flat: list[np.ndarray] = []
        for part in parts:
            flat.extend(_line_parts(part))
        return flat
    coords = np.asarray(geometry.coords, dtype=float)
    return [coords] if coords.shape[0] >= 2 else []
