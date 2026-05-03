"""Simulated active drainage-network map computed from accumulation flux."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from hydromodpy.display._map_axes import overlay_watershed_contour, style_map_axes
from hydromodpy.display._ugrid import render_face_field
from hydromodpy.display.catalog import register
from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.spatial.geographic.core.hydrographic_network import (
    project_gdf_for_metric_operations,
)

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


@register
class SimulatedActiveNetworkMap(BaseFigure):
    """Map the active drainage network inferred from a simulated flux field."""

    spec = FigureSpec(
        name="simulated_active_network",
        title="Simulated active network",
        kind="spatial",
        required_fields=("accumulation_flux",),
        default_figsize=(7.0, 5.5),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        variable: str = "accumulation_flux",
        threshold: float = 0.0,
        mode: Literal["last", "any", "persistent", "perennial", "persistence"] = "persistent",
        persistence_threshold: float = 0.5,
        timestep: int | None = None,
        cmap: str | None = None,
        **_,
    ) -> Axes:
        values = sim.simulated_active_network_mask(
            variable=variable,
            threshold=threshold,
            mode=mode,
            persistence_threshold=persistence_threshold,
            timestep=timestep,
        )
        is_persistence = mode == "persistence"
        label = "Active persistence (0-1)" if is_persistence else "Active network (1 = active)"
        render_face_field(
            ax,
            sim,
            values,
            cmap=cmap or ("viridis" if is_persistence else "Blues"),
            vmin=0.0,
            vmax=1.0,
            cbar_label=label,
        )
        overlay_watershed_contour(ax, sim)
        style_map_axes(ax)
        mode_label = mode if mode != "persistent" else f"persistent >= {persistence_threshold:g}"
        ax.set_title(f"Simulated active network ({mode_label}) - {sim.name or sim.sim_id}")
        return ax


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
        mode: Literal["last", "any", "persistent", "perennial", "persistence"] = "persistent",
        persistence_threshold: float = 0.5,
        timestep: int | None = None,
        buffer_m: float = 0.0,
        cmap: str = "Blues",
        reference_color: str = "#9b1c1c",
        **_,
    ) -> Axes:
        import matplotlib.pyplot as plt
        from matplotlib.lines import Line2D
        from matplotlib.patches import Patch

        values = sim.simulated_active_network_mask(
            variable=variable,
            threshold=threshold,
            mode=mode,
            persistence_threshold=persistence_threshold,
            timestep=timestep,
        )
        display_values = values.astype("float64", copy=True)
        if mode != "persistence":
            display_values[display_values <= 0.0] = float("nan")

        active_cmap = plt.get_cmap(cmap).copy()
        active_cmap.set_bad((1.0, 1.0, 1.0, 0.0))
        render_face_field(
            ax,
            sim,
            display_values,
            cmap=active_cmap,
            vmin=0.0,
            vmax=1.0,
            cbar_label=(
                "Active persistence (0-1)"
                if mode == "persistence"
                else "Simulated active cells"
            ),
        )

        reference = sim.hydrographic_network("reference")
        try:
            watershed = sim.geographic("watershed")
            fallback_crs = None if watershed is None or watershed.empty else watershed.crs
        except Exception:
            fallback_crs = None
        reference = project_gdf_for_metric_operations(reference, fallback_crs=fallback_crs)
        reference.plot(
            ax=ax,
            color=reference_color,
            linewidth=1.25,
            alpha=0.98,
            zorder=6,
        )
        overlay_watershed_contour(ax, sim, color="#404040", linewidth=0.9, alpha=0.65)
        style_map_axes(ax)
        mode_label = mode if mode != "persistent" else f"persistent >= {persistence_threshold:g}"
        ax.set_title(f"Simulated active vs reference ({mode_label}) - {sim.name or sim.sim_id}")

        try:
            metrics = sim.simulated_active_network_overlap_metrics(
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
                Patch(facecolor=plt.get_cmap(cmap)(0.75), edgecolor="none", label="simulated active"),
                Line2D([0], [0], color=reference_color, lw=1.5, label="reference"),
            ],
            loc="lower right",
            framealpha=0.9,
        )
        return ax
