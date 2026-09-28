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

The persistence mode counts the timesteps a cell flows, and "flows" is then
the definition the network criterion scores
(:func:`hydromodpy.core.stream_extent.flowing_cells`): the downstream closure
of the cells releasing above ``tau * R * A`` on the criterion graph, above the
visible flow, with the settings the run's sealed network output scored with.
A persistence drawn on ``accumulation_flux > 0`` would colour another network
than the one the trial and the persistence maps beside it read. A caller who
names a ``variable`` or a ``threshold`` asks for that field cut instead, and
a run the criterion graph cannot be rebuilt on falls back to it and says why.

The overlay against the mapped linework is the second figure of this module.
Neither reads a solver: both take a per-cell field and the reduction
:mod:`hydromodpy.results.derive.views` resolves for the regime of the run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.stream_extent import VisibleFlow, parse_visible_flow
from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.figures._memo import RunMemo
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
from hydromodpy.display.maps.axes import (
    RELATIVE_MAP_LEGEND_SIZE,
    overlay_watershed_contour,
    style_map_axes,
    style_relative_km_axes,
)
from hydromodpy.display.maps.geo import project_gdf_for_metric_operations
from hydromodpy.display.maps.mesh_geometry import face_polygons
from hydromodpy.display.maps.overlays import NetworkMap, network_map_of_role, plot_network_map
from hydromodpy.display.maps.ugrid import render_face_field
from hydromodpy.display.style import HIGH_CONTRAST_TRIPLET, PREFERRED_CMAPS, get_cmap
from hydromodpy.results.derive import views
from hydromodpy.results.derive.network_criterion_settings import (
    NetworkCriterionSettings,
    network_criterion_settings,
)
from hydromodpy.results.derive.stream_extent import (
    flow_geometry_from_run,
    flowing_share,
    unavailable_reason_for_flow,
)
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

_FLOWING_TITLE = "flowing persistence"
_FLOWING_NOTE = "the share of the timesteps each cell flows, drawn uncut"
_FLOWING_CBAR = "Flowing persistence (0-1)"
_ACTIVE_CBAR = "Active persistence (0-1)"

_DEFAULT_VARIABLE = "accumulation_flux"
_DEFAULT_THRESHOLD = 0.0

_FLOWING_MEMO = RunMemo()


@register
class SimulatedActiveNetworkMap(BaseFigure):
    """Map the active drainage network inferred from a simulated flux field.

    ``variable`` and ``threshold`` are the cut: a cell is active where the
    field exceeds the threshold, ``accumulation_flux > 0`` when left out, and
    ``mode`` says how the timesteps are reduced to one answer. In the
    ``persistence`` mode with neither named, a cell is active where it flows
    as the network criterion says, with the run's sealed criterion settings
    (``output`` names the calibration output when the run sealed several).
    ``extent`` picks the frame: ``catchment`` crops to the delineated
    watershed, ``mesh`` keeps the whole modelled domain.
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
        variable: str | None = None,
        threshold: float | None = None,
        mode: CellFieldActiveMode | None = None,
        persistence_threshold: float = 0.5,
        timestep: int | None = None,
        cmap: str | None = None,
        output: str | None = None,
        extent: MapExtentName = "catchment",
        **_,
    ) -> Axes:
        is_persistence = views.resolve_cell_field_active_mode(sim, mode) == "persistence"
        flowing: FlowingPersistence | None = None
        fallback: str | None = None
        if is_persistence and variable is None and threshold is None:
            flowing, fallback = flowing_persistence(sim, output=output)
        field_variable = _DEFAULT_VARIABLE if variable is None else variable
        field_threshold = _DEFAULT_THRESHOLD if threshold is None else float(threshold)

        if flowing is not None:
            values = flowing.share
            mode_label = _FLOWING_NOTE
        else:
            values = views.cell_field_active_mask(
                sim,
                variable=field_variable,
                threshold=field_threshold,
                mode=mode,
                persistence_threshold=persistence_threshold,
                timestep=timestep,
            )
            mode_label = views.cell_field_active_mode_label(
                sim,
                mode=mode,
                persistence_threshold=persistence_threshold,
            )
        polygons = face_polygons(sim)
        fraction = np.asarray(values, dtype="float64").reshape(-1)
        active = fraction > 0.0

        modelled = np.isfinite(fraction)
        if is_persistence:
            cbar_label = _ACTIVE_CBAR if flowing is None else _FLOWING_CBAR
            handles = _draw_persistence(ax, sim, polygons, fraction, modelled, cmap, cbar_label)
        else:
            handles = _draw_active(ax, polygons, modelled, active)
        overlay_watershed_contour(ax, sim)
        style_map_axes(ax)
        if flowing is not None:
            title_mode = _FLOWING_TITLE
        else:
            title_mode = _PERSISTENCE_TITLE if is_persistence else mode_label
        ax.set_title(f"{self.spec.title} ({title_mode}) - {sim.name or sim.sim_id}")

        window = map_extent(sim, polygons, extent=extent)
        if flowing is not None:
            notes = [
                flowing.definition(),
                f"reduced over time as: {_FLOWING_NOTE}",
                flowing.settings.note(),
            ]
        else:
            units = self.field_descriptor_for(field_variable).units
            notes = [
                f"active where {field_variable} > {field_threshold:g} {units}",
                f"reduced over time as: {_PERSISTENCE_NOTE if is_persistence else mode_label}",
            ]
            if fallback is not None:
                notes.append(f"not the criterion's flowing cells: {fallback}")
        notes.append(f"frame: {window.name}")
        hidden = window.outside_note(active, "the active network")
        if hidden is not None:
            notes.append(hidden)
        map_legend(ax, handles, note="\n".join(notes))
        window.apply(ax)
        return ax


@dataclass(frozen=True, slots=True)
class FlowingPersistence:
    """The share of the timesteps each cell flows, and how "flows" was cut."""

    share: np.ndarray
    """(n_cells,) share of the run's timesteps the cell flows, NaN off the graph."""

    settings: NetworkCriterionSettings
    visible_flow: VisibleFlow

    def definition(self) -> str:
        """Return the line naming the definition of flowing the map draws."""
        visible = (
            "no visible-flow threshold"
            if self.visible_flow.geometric
            else f"visible flow {self.visible_flow.label()}"
        )
        return (
            f"flowing as the network criterion scores it: seepage closure, "
            f"tau = {self.settings.tau_specific_ratio:g}, {visible}"
        )


def flowing_persistence(
    sim: Run, *, output: str | None = None
) -> tuple[FlowingPersistence | None, str | None]:
    """Return the criterion persistence of a run, or None and why it cannot be drawn.

    The settings are the run's sealed network output: its seepage threshold,
    graph, map rasterisation and, when it scored two bounds, its visible flow;
    the defaults otherwise, the visible flow included. Memoised on the run.
    """
    try:
        settings = network_criterion_settings(sim, output=output)
    except ValueError as exc:
        return None, f"its sealed network output cannot be read ({exc})"
    reason = unavailable_reason_for_flow(sim, tau_specific_ratio=settings.tau_specific_ratio)
    if reason is not None:
        return None, reason
    visible = parse_visible_flow(settings.extent_rules.visible_flow)

    def build() -> FlowingPersistence:
        geometry = flow_geometry_from_run(
            sim,
            tau_specific_ratio=settings.tau_specific_ratio,
            diagonal_neighbors=settings.diagonal_neighbors,
            observed_rasterization=settings.observed_rasterization,
            weighting=settings.weighting,
            observed_position_accuracy_m=settings.observed_position_accuracy_m,
        )
        return FlowingPersistence(
            share=flowing_share(sim, geometry, visible_flow=visible),
            settings=settings,
            visible_flow=visible,
        )

    return _FLOWING_MEMO.get_or_build(sim, (settings, visible), build), None


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
    cbar_label: str,
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
        cbar_label=cbar_label,
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

        network = network_map_of_role(sim, "reference")
        try:
            watershed = sim.geographic("watershed")
            fallback_crs = None if watershed is None or watershed.empty else watershed.crs
        except Exception:
            fallback_crs = None
        reference = project_gdf_for_metric_operations(network.frame, fallback_crs=fallback_crs)
        plot_network_map(
            ax,
            network,
            reference,
            color=reference_color,
            linewidth=1.25,
            alpha=0.98,
            zorder=6,
        )
        map_note = network.label()
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
                        *([] if map_note is None else [map_note]),
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
                _reference_handle(network, reference_color),
            ],
            loc="lower right",
            fontsize=RELATIVE_MAP_LEGEND_SIZE,
            framealpha=0.9,
        )
        return ax


def _reference_handle(network: NetworkMap, color: str):
    """Return the legend entry of the reference map, naming the snapped map when drawn."""
    from matplotlib.lines import Line2D

    if network.snapped:
        return Line2D(
            [0],
            [0],
            color=color,
            lw=0.0,
            marker="s",
            markersize=4.0,
            label="Reference network (snapped)",
        )
    return Line2D([0], [0], color=color, lw=1.5, label="Reference network")
