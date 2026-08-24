"""The drainage network the routed flux keeps active, and the cut that made it.

``accumulation_flux`` is a continuous field and an active network is a set of
cells, so between the two sits a threshold. A map that shows only the result
leaves a reader unable to tell a model that drains half its catchment from one
threshold set too low, which is why the cut, the reduction over time and the
frame are all written under this map rather than left in the caller's TOML.

The active cells are one cell wide and the mesh is not, so they are drawn with
the weight of the stream maps beside them and over the same ground tone: on a
default page a cell of a fifty-metre mesh is four pixels, and a network drawn
at its true width breaks up under its own rasterisation.

The overlay against the mapped linework is the second figure of this module.
Neither reads a solver: both take a per-cell field and the reduction
:mod:`hydromodpy.results.derive.views` resolves for the regime of the run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display.colormaps import HIGH_CONTRAST_TRIPLET, PREFERRED_CMAPS, get_cmap
from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.figures._stream_comparison import (
    CELL_WEIGHT_PT,
    GROUND_COLOR,
    MapExtentName,
    cell_count,
    draw_cells,
    map_extent,
    map_legend,
    select_cells,
)
from hydromodpy.display.figures.hydrographic_network import _project_gdf_for_metric_operations
from hydromodpy.display.map_axes import (
    RELATIVE_MAP_LEGEND_SIZE,
    overlay_watershed_contour,
    style_map_axes,
    style_relative_km_axes,
)
from hydromodpy.display.mesh_geometry import face_polygons
from hydromodpy.display.ugrid import render_face_field
from hydromodpy.results.derive import views
from hydromodpy.results.derive.views import CellFieldActiveMode

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run

ACTIVE_COLOR = HIGH_CONTRAST_TRIPLET[0]
"""The colour a simulated stream carries across every map of this gallery."""

_ACTIVE_LABEL = "active network"
_MODELLED_LABEL = "modelled, not active"
_NEVER_ACTIVE_LABEL = "never active"

_TRANSPARENT = (1.0, 1.0, 1.0, 0.0)
"""What a cell outside the ramp is painted, the ground being drawn under it."""

_PERSISTENCE_TITLE = "active persistence"
_PERSISTENCE_NOTE = "the share of the timesteps each cell is active, drawn uncut"
"""What the persistence mode reduces to, said as what the map draws.

``cell_field_active_mode_label`` names this mode after the cut a caller asked
for, ``persistence >= 0.5``. That cut belongs to the ``persistent`` mode: this
one keeps the whole ``0-1`` ramp and applies no threshold at all, so borrowing
the label would print a reduction over a map that never performed it.
"""


@register
class SimulatedActiveNetworkMap(BaseFigure):
    """Map the active drainage network inferred from a simulated flux field.

    ``variable`` and ``threshold`` are the cut: a cell is active where the
    field exceeds the threshold, and ``mode`` says how the timesteps are
    reduced to one answer. ``extent`` picks the frame: ``catchment`` crops to
    the delineated watershed, ``mesh`` keeps the whole modelled domain.
    """

    spec = FigureSpec(
        name="simulated_active_network",
        title="Simulated active network",
        kind="spatial",
        required_fields=("accumulation_flux",),
        default_figsize=(7.0, 6.2),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        variable: str = "accumulation_flux",
        threshold: float = 0.0,
        mode: CellFieldActiveMode | None = None,
        persistence_threshold: float = 0.5,
        timestep: int | None = None,
        cmap: str | None = None,
        extent: MapExtentName = "catchment",
        **_,
    ) -> Axes:
        values = views.cell_field_active_mask(
            sim,
            variable=variable,
            threshold=threshold,
            mode=mode,
            persistence_threshold=persistence_threshold,
            timestep=timestep,
        )
        mode_label = views.cell_field_active_mode_label(
            sim,
            mode=mode,
            persistence_threshold=persistence_threshold,
        )
        is_persistence = views.resolve_cell_field_active_mode(sim, mode) == "persistence"
        polygons = face_polygons(sim)
        fraction = np.asarray(values, dtype="float64").reshape(-1)
        active = fraction > 0.0

        modelled = np.isfinite(fraction)
        if is_persistence:
            handles = _draw_persistence(ax, sim, polygons, fraction, modelled, cmap)
        else:
            handles = _draw_active(ax, polygons, modelled, active)
        overlay_watershed_contour(ax, sim)
        style_map_axes(ax)
        title_mode = _PERSISTENCE_TITLE if is_persistence else mode_label
        ax.set_title(f"{self.spec.title} ({title_mode}) - {sim.name or sim.sim_id}")

        window = map_extent(sim, polygons, extent=extent)
        notes = [
            f"active where {variable} > {threshold:g} {self.field_descriptor_for(variable).units}",
            f"reduced over time as: {_PERSISTENCE_NOTE if is_persistence else mode_label}",
            f"frame: {window.name}",
        ]
        hidden = window.outside_note(active, "the active network")
        if hidden is not None:
            notes.append(hidden)
        map_legend(ax, handles, note="\n".join(notes))
        window.apply(ax)
        return ax


def _draw_active(
    ax: Axes,
    polygons: list[np.ndarray],
    modelled: np.ndarray,
    active: np.ndarray,
) -> list:
    """Draw the thresholded network over the cells the model carries a value on."""
    from matplotlib.patches import Patch

    draw_cells(
        ax,
        select_cells(polygons, modelled & ~active),
        color=GROUND_COLOR,
        label=_MODELLED_LABEL,
        zorder=1,
        weight_pt=0.0,
    )
    draw_cells(
        ax,
        select_cells(polygons, active),
        color=ACTIVE_COLOR,
        label=_ACTIVE_LABEL,
        zorder=2,
        weight_pt=CELL_WEIGHT_PT,
    )
    return [
        Patch(
            facecolor=ACTIVE_COLOR,
            edgecolor="none",
            label=f"{_ACTIVE_LABEL} ({cell_count(active)})",
        ),
        Patch(
            facecolor=GROUND_COLOR,
            edgecolor="#c8c8c8",
            label=f"{_MODELLED_LABEL} ({cell_count(modelled & ~active)})",
        ),
    ]


def _draw_persistence(
    ax: Axes,
    sim: Run,
    polygons: list[np.ndarray],
    fraction: np.ndarray,
    modelled: np.ndarray,
    cmap: str | None,
) -> list:
    """Draw the per-cell active fraction, which is a scale and not a class.

    A cell active at no timestep is on the ground rather than at the foot of
    the ramp: painted in the darkest step of a sequential scale it covers the
    whole page and the network on it disappears into its own background. The
    ground is its own flat collection under the ramp, because a mapped
    collection carries one weight for every cell it holds: strokes on the
    ground would widen the 58 000 cells of it over the 2 400 the map is read
    for.
    """
    from matplotlib.patches import Patch

    ramp = get_cmap(cmap or PREFERRED_CMAPS["sequential"]).with_extremes(bad=_TRANSPARENT)
    never = modelled & (fraction <= 0.0)
    draw_cells(
        ax,
        select_cells(polygons, never),
        color=GROUND_COLOR,
        label=_NEVER_ACTIVE_LABEL,
        zorder=1,
        weight_pt=0.0,
    )
    collection = render_face_field(
        ax,
        sim,
        np.where(fraction > 0.0, fraction, np.nan),
        cmap=ramp,
        vmin=0.0,
        vmax=1.0,
        cbar_label="Active persistence (0-1)",
    )
    collection.set_edgecolor("face")
    collection.set_linewidth(CELL_WEIGHT_PT)
    collection.set_zorder(2)
    return [
        Patch(
            facecolor=GROUND_COLOR,
            edgecolor="#c8c8c8",
            label=f"{_NEVER_ACTIVE_LABEL} ({cell_count(never)})",
        )
    ]


@register
class SimulatedActiveNetworkReferenceOverlay(BaseFigure):
    """Overlay simulated active cells with the observed reference linework."""

    spec = FigureSpec(
        name="simulated_active_network_reference_overlay",
        title="Simulated active network vs reference",
        kind="comparison",
        required_fields=("accumulation_flux",),
        default_figsize=(7.8, 5.8),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        variable: str = "accumulation_flux",
        threshold: float = 0.0,
        mode: CellFieldActiveMode | None = None,
        persistence_threshold: float = 0.5,
        timestep: int | None = None,
        buffer_m: float = 0.0,
        cmap: str = "Blues",
        active_color: str = "#9ecae1",
        active_alpha: float = 0.55,
        reference_color: str = "#9b1c1c",
        **_,
    ) -> Axes:
        import matplotlib.pyplot as plt
        from matplotlib.colors import ListedColormap
        from matplotlib.lines import Line2D
        from matplotlib.patches import Patch

        values = views.cell_field_active_mask(
            sim,
            variable=variable,
            threshold=threshold,
            mode=mode,
            persistence_threshold=persistence_threshold,
            timestep=timestep,
        )
        resolved_mode = views.resolve_cell_field_active_mode(sim, mode)
        display_values = values.astype("float64", copy=True)
        if resolved_mode != "persistence":
            display_values[display_values <= 0.0] = float("nan")

        if resolved_mode == "persistence":
            active_cmap = plt.get_cmap(cmap).copy()
        else:
            active_cmap = ListedColormap([active_color])
        active_cmap.set_bad((1.0, 1.0, 1.0, 0.0))
        collection = render_face_field(
            ax,
            sim,
            display_values,
            cmap=active_cmap,
            vmin=0.0,
            vmax=1.0,
            cbar_label=(
                "Active persistence (0-1)"
                if resolved_mode == "persistence"
                else "Simulated active cells"
            ),
        )
        collection.set_alpha(active_alpha)

        reference = sim.hydrographic_network("reference")
        try:
            watershed = sim.geographic("watershed")
            fallback_crs = None if watershed is None or watershed.empty else watershed.crs
        except Exception:
            fallback_crs = None
        reference = _project_gdf_for_metric_operations(reference, fallback_crs=fallback_crs)
        reference.plot(
            ax=ax,
            color=reference_color,
            linewidth=1.25,
            alpha=0.98,
            zorder=6,
        )
        overlay_watershed_contour(ax, sim, color="#404040", linewidth=0.9, alpha=0.65)
        style_relative_km_axes(ax)
        mode_label = views.cell_field_active_mode_label(
            sim,
            mode=mode,
            persistence_threshold=persistence_threshold,
        )
        ax.set_title(f"Simulated active vs reference ({mode_label}) - {sim.name or sim.sim_id}")

        try:
            metrics = views.cell_field_network_overlap_metrics(
                sim,
                network_role="reference",
                variable=variable,
                threshold=threshold,
                mode=mode,
                persistence_threshold=persistence_threshold,
                timestep=timestep,
                buffer_m=buffer_m,
            )
        except Exception:
            metrics = {}
        if metrics:
            ax.text(
                0.02,
                0.98,
                "\n".join(
                    [
                        "cell overlap vs reference",
                        f"coverage: {float(metrics['network_coverage_ratio']):.3f}",
                        f"precision: {float(metrics['active_precision_ratio']):.3f}",
                        f"F1: {float(metrics['cell_f1_ratio']):.3f}",
                        f"Jaccard: {float(metrics['cell_jaccard_ratio']):.3f}",
                    ]
                ),
                transform=ax.transAxes,
                ha="left",
                va="top",
                fontsize=8.2,
                bbox={"facecolor": "white", "alpha": 0.9, "edgecolor": "#c8c8c8"},
                zorder=8,
            )
        ax.legend(
            handles=[
                Patch(
                    facecolor=active_color,
                    edgecolor="none",
                    alpha=active_alpha,
                    label="simulated active",
                ),
                Line2D([0], [0], color=reference_color, lw=1.5, label="BD Topage"),
            ],
            loc="lower right",
            fontsize=RELATIVE_MAP_LEGEND_SIZE,
            framealpha=0.9,
        )
        return ax
