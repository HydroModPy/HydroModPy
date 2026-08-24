"""The simulated stream network drawn over the mapped one, on shaded relief.

This is the figure to open before trusting any number. A criterion that
balances two downslope distances says nothing about where the linework sits:
a residual near zero is compatible with a simulated network that ignores the
talwegs of the routing surface entirely. That failure is obvious to the eye
and invisible in the cost, so the check is a picture and not a scalar.

The relief is a hillshade computed from the per-cell topography the run
persisted, in greys only, so the two networks keep the whole colour axis. They
are told apart by shape as well as by hue: the mapped network fills its cells,
the simulated one is drawn inset on top, and the pair survives a greyscale
print.

Both networks are rebuilt from what the run persisted, through the
construction the criterion scores, so the picture answers for the numbers
beside it. The simulated one moves with the seepage threshold, which the
figure names on the page.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display.colormaps import HIGH_CONTRAST_TRIPLET
from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.figures._stream_comparison import (
    annotate_note,
    cell_count,
    checked_cells,
    comparison_from_run,
    threshold_note,
)
from hydromodpy.display.map_axes import style_map_axes
from hydromodpy.display.mesh_geometry import face_centroids, face_polygons
from hydromodpy.display.overlays import apply_overlays
from hydromodpy.results.derive.stream_network import unavailable_reason_for_comparison

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run

NETWORK_COLORS: dict[str, str] = {
    "observed": HIGH_CONTRAST_TRIPLET[0],
    "simulated": HIGH_CONTRAST_TRIPLET[2],
}
"""One colour per network, the darkest for the mapped reference."""

RELIEF_GREYS: tuple[str, str] = ("#8a8a8a", "#fafafa")
"""Shadow and light of the hillshade, both lighter than either network."""

_SIMULATED_INSET = 0.58
"""Side of the simulated patch as a fraction of its cell."""

_RELIEF_MIN_SPREAD = 0.02
"""Below this illumination range, the relief is flat and keeps the full scale."""

_DEFAULT_OVERLAYS: tuple[str, ...] = ("watershed", "outlet")


@register
class SeepageNetworkReferenceOverlay(BaseFigure):
    """Simulated stream cells over the mapped ones, on a shaded relief.

    Both networks are read from the run inside the scored catchment: the
    mapped one is the linework the project declares, projected onto the mesh,
    the simulated one is what the release flux generates downslope. Where they
    overlap the figure shows the simulated patch sitting inside the mapped
    cell, which is the agreement.
    """

    spec = FigureSpec(
        name="seepage_network_reference_overlay",
        title="Simulated network over reference",
        kind="comparison",
        required_fields=("release_flux",),
        default_figsize=(7.8, 5.8),
    )

    def unavailable_reason(self, sim: Run) -> str | None:
        """Return why this run holds no stream comparison, or None when it does."""
        return unavailable_reason_for_comparison(sim) or super().unavailable_reason(sim)

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        tau_specific_ratio: float | None = None,
        diagonal_neighbors: bool | None = None,
        timestep: int | None = None,
        azimuth_deg: float = 315.0,
        altitude_deg: float = 45.0,
        overlays: tuple[str, ...] | list[str] | None = None,
        **_,
    ) -> Axes:
        from matplotlib.patches import Patch

        comparison = comparison_from_run(
            sim,
            tau_specific_ratio=tau_specific_ratio,
            diagonal_neighbors=diagonal_neighbors,
            timestep=timestep,
        )
        polygons = face_polygons(sim)
        n_faces = len(polygons)
        observed_mask = checked_cells(comparison.mapped, n_faces, "mapped network")
        simulated_mask = checked_cells(comparison.simulated, n_faces, "simulated network")

        notes: list[str] = [threshold_note(comparison)]
        elevation = _read_topography(sim, n_faces)
        if elevation is None:
            notes.append("no per-cell topography in this run: the relief background is missing")
        elif not np.isfinite(elevation).any():
            notes.append("the topography holds no finite cell: the relief background is missing")
        else:
            _add_relief(
                ax,
                polygons,
                _hillshade(
                    face_centroids(sim),
                    np.asarray(sim.mesh.face_node_connectivity),
                    elevation,
                    azimuth_deg=azimuth_deg,
                    altitude_deg=altitude_deg,
                ),
            )

        _add_cells(
            ax,
            [polygons[index] for index in np.flatnonzero(observed_mask)],
            color=NETWORK_COLORS["observed"],
            label="_observed network",
            zorder=2,
        )
        _add_cells(
            ax,
            [_inset(polygons[index]) for index in np.flatnonzero(simulated_mask)],
            color=NETWORK_COLORS["simulated"],
            label="_simulated network",
            zorder=3,
        )
        if not observed_mask.any():
            notes.append("the mapped network is empty: nothing to compare the simulated one to")
        if not simulated_mask.any():
            notes.append("the simulated network is empty: the model produced no stream cell")

        ax.update_datalim(np.concatenate(polygons))
        ax.autoscale_view()
        apply_overlays(ax, sim, _DEFAULT_OVERLAYS if overlays is None else overlays)
        style_map_axes(ax)
        ax.set_title(f"{self.spec.title} - {sim.name or sim.sim_id}")

        handles = [
            Patch(
                facecolor=NETWORK_COLORS["observed"],
                edgecolor="none",
                label=f"mapped network ({cell_count(observed_mask)})",
            ),
            Patch(
                facecolor=NETWORK_COLORS["simulated"],
                edgecolor="none",
                label=f"simulated network ({cell_count(simulated_mask)})",
            ),
        ]
        extra, _labels = ax.get_legend_handles_labels()
        ax.legend(handles=handles + extra, loc="best", fontsize=9, framealpha=0.9)
        annotate_note(ax, "\n".join(notes))
        return ax


def _add_relief(ax: Axes, polygons: list[np.ndarray], shading: np.ndarray) -> None:
    """Draw the hillshade under everything else, in greys only."""
    from matplotlib.collections import PolyCollection
    from matplotlib.colors import LinearSegmentedColormap

    ax.add_collection(
        PolyCollection(
            polygons,
            array=shading,
            cmap=LinearSegmentedColormap.from_list("shaded_relief", list(RELIEF_GREYS)),
            clim=_relief_limits(shading),
            edgecolors="none",
            label="_relief",
            zorder=0,
        )
    )


def _relief_limits(shading: np.ndarray) -> tuple[float, float]:
    """Return the grey scale of the hillshade, stretched over its own range.

    A gentle catchment lights within a narrow band of the theoretical
    ``[0, 1]``, and left on that range it prints as one flat plate with no
    talweg in it. The percentiles keep a handful of extreme cells from eating
    the whole scale, and a relief with no spread at all keeps the full range
    rather than exploding into noise.
    """
    finite = shading[np.isfinite(shading)]
    if finite.size == 0:
        return (0.0, 1.0)
    low, high = (float(value) for value in np.percentile(finite, [2.0, 98.0]))
    return (low, high) if high - low > _RELIEF_MIN_SPREAD else (0.0, 1.0)


def _add_cells(
    ax: Axes,
    polygons: list[np.ndarray],
    *,
    color: str,
    label: str,
    zorder: int,
) -> None:
    """Draw one network as flat patches, or nothing when it holds no cell."""
    from matplotlib.collections import PolyCollection

    if not polygons:
        return
    ax.add_collection(
        PolyCollection(
            polygons,
            facecolors=color,
            edgecolors="none",
            label=label,
            zorder=zorder,
        )
    )


def _inset(polygon: np.ndarray) -> np.ndarray:
    """Return the cell polygon shrunk about its centre.

    The simulated network keeps the geometry of its cells while staying
    visibly narrower than the mapped one underneath, so the two are told
    apart by shape and not only by colour.
    """
    centre = polygon.mean(axis=0)
    return centre + (polygon - centre) * _SIMULATED_INSET


def _read_topography(sim: Run, n_faces: int) -> np.ndarray | None:
    """Return the per-cell land surface, or None when the run has none."""
    if not sim.has_field("topography"):
        return None
    elevation = np.asarray(sim.field("topography"), dtype="float64").ravel()
    if elevation.size != n_faces:
        raise ValueError(f"the topography holds {elevation.size} cells, the mesh holds {n_faces}.")
    return elevation


def _hillshade(
    centroids: np.ndarray,
    face_node_connectivity: np.ndarray,
    elevation: np.ndarray,
    *,
    azimuth_deg: float,
    altitude_deg: float,
) -> np.ndarray:
    """Return the illumination of every face, in ``[0, 1]``.

    The surface normal comes from a plane fitted over the faces sharing a
    node, which is defined on a structured grid and on a Voronoi or
    triangular mesh alike, so the relief reads the same whatever the solver
    discretized with.
    """
    left, right = _node_neighbour_pairs(face_node_connectivity)
    gradient_x, gradient_y = _surface_gradient(centroids, elevation, left, right)
    azimuth = np.radians(azimuth_deg)
    altitude = np.radians(altitude_deg)
    light = (
        np.sin(azimuth) * np.cos(altitude),
        np.cos(azimuth) * np.cos(altitude),
        np.sin(altitude),
    )
    normal_length = np.sqrt(gradient_x**2 + gradient_y**2 + 1.0)
    illumination = (-gradient_x * light[0] - gradient_y * light[1] + light[2]) / normal_length
    # A cell with no elevation keeps none: shading it like flat ground would
    # invent a surface where the run holds nothing.
    return np.where(np.isfinite(elevation), np.clip(illumination, 0.0, 1.0), np.nan)


def _node_neighbour_pairs(face_node_connectivity: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return every ordered pair of distinct faces sharing at least one node."""
    fnc = np.asarray(face_node_connectivity)
    faces = np.repeat(np.arange(fnc.shape[0]), fnc.shape[1])
    nodes = fnc.reshape(-1)
    keep = nodes >= 0 if fnc.dtype.kind in "iu" else ~np.isnan(nodes)
    faces, nodes = faces[keep], nodes[keep].astype(int)

    order = np.argsort(nodes, kind="stable")
    faces, nodes = faces[order], nodes[order]
    starts = np.flatnonzero(np.concatenate(([True], nodes[1:] != nodes[:-1])))
    counts = np.diff(np.concatenate((starts, [nodes.size])))
    per_entry_start = np.repeat(starts, counts)
    per_entry_count = np.repeat(counts, counts)

    total = int(per_entry_count.sum())
    block_start = np.cumsum(per_entry_count) - per_entry_count
    within = np.arange(total) - np.repeat(block_start, per_entry_count)
    left = np.repeat(faces, per_entry_count)
    right = faces[np.repeat(per_entry_start, per_entry_count) + within]
    distinct = left != right
    return left[distinct], right[distinct]


def _surface_gradient(
    centroids: np.ndarray,
    elevation: np.ndarray,
    left: np.ndarray,
    right: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(dz/dx, dz/dy)`` per face, from a plane fit over its neighbours."""
    finite = np.isfinite(elevation)
    keep = finite[left] & finite[right]
    left, right = left[keep], right[keep]
    delta_x = centroids[right, 0] - centroids[left, 0]
    delta_y = centroids[right, 1] - centroids[left, 1]
    delta_z = elevation[right] - elevation[left]

    n_faces = centroids.shape[0]
    moments = []
    for product in (
        delta_x * delta_x,
        delta_x * delta_y,
        delta_y * delta_y,
        delta_x * delta_z,
        delta_y * delta_z,
    ):
        total = np.zeros(n_faces, dtype="float64")
        np.add.at(total, left, product)
        moments.append(total)
    sum_xx, sum_xy, sum_yy, sum_xz, sum_yz = moments

    # A ridge term keeps the 2x2 system solvable where the neighbours of a
    # face line up on a single direction, which a one-cell-wide mesh does.
    ridge = 1e-3 * (sum_xx + sum_yy)
    sum_xx = sum_xx + ridge
    sum_yy = sum_yy + ridge
    determinant = sum_xx * sum_yy - sum_xy * sum_xy

    gradient_x = np.zeros(n_faces, dtype="float64")
    gradient_y = np.zeros(n_faces, dtype="float64")
    solvable = determinant > 0.0
    gradient_x[solvable] = (
        sum_yy[solvable] * sum_xz[solvable] - sum_xy[solvable] * sum_yz[solvable]
    ) / determinant[solvable]
    gradient_y[solvable] = (
        sum_xx[solvable] * sum_yz[solvable] - sum_xy[solvable] * sum_xz[solvable]
    ) / determinant[solvable]
    return gradient_x, gradient_y
