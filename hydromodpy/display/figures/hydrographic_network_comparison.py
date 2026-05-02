"""Standard comparison figure for reference vs generated hydrographic networks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hydromodpy.display._map_axes import overlay_watershed_contour, style_map_axes
from hydromodpy.display.catalog import register
from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.geo import GeoFigureMixin

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure as MplFigure

    from hydromodpy.results.run import Run
    from hydromodpy.spatial.geographic.core.hydrographic_network_comparison import (
        HydrographicNetworkComparison,
    )


@register
class HydrographicNetworkComparisonFigure(GeoFigureMixin, BaseFigure):
    """Reference, generated, overlay, then diff view for canonical networks."""

    spec = FigureSpec(
        name="hydrographic_network_comparison",
        title="Hydrographic network comparison",
        kind="comparison",
        default_figsize=(20.0, 5.8),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        tolerance_m: float = 50.0,
        reference_role: str = "reference",
        candidate_role: str = "generated",
        **_,
    ) -> Axes:
        comparison = sim.hydrographic_network_comparison(
            reference_role=reference_role,
            candidate_role=candidate_role,
            tolerance_m=tolerance_m,
        )
        self._draw_single_network(
            ax,
            sim,
            comparison,
            gdf=comparison.reference_gdf,
            color="#222222",
            linewidth=1.4,
            title="Loaded reference",
            subtitle="data.hydrography",
            length_m=comparison.reference_total_length_m,
        )
        return ax

    def plot(
        self,
        sim: Run,
        *,
        tolerance_m: float = 50.0,
        reference_role: str = "reference",
        candidate_role: str = "generated",
        figsize: tuple[float, float] | None = None,
        dpi: int = 150,
        save_path=None,
        **_,
    ) -> MplFigure:
        import matplotlib.pyplot as plt

        comparison = sim.hydrographic_network_comparison(
            reference_role=reference_role,
            candidate_role=candidate_role,
            tolerance_m=tolerance_m,
        )

        fig, axes = plt.subplots(
            1,
            4,
            figsize=figsize or self.spec.default_figsize,
            dpi=dpi,
            constrained_layout=True,
        )
        self._draw_single_network(
            axes[0],
            sim,
            comparison,
            gdf=comparison.reference_gdf,
            color="#222222",
            linewidth=1.4,
            title="Loaded reference",
            subtitle="data.hydrography",
            length_m=comparison.reference_total_length_m,
        )
        self._draw_single_network(
            axes[1],
            sim,
            comparison,
            gdf=comparison.candidate_gdf,
            color="#2a6f97",
            linewidth=1.2,
            title="Generated from DEM",
            subtitle="geographic.river_network",
            length_m=comparison.candidate_total_length_m,
        )
        self._draw_overlay(axes[2], sim, comparison)
        self._draw_difference(axes[3], sim, comparison)
        fig.suptitle(
            f"Hydrographic network comparison - {sim.name or sim.sim_id[:8]}",
            fontweight="bold",
            fontsize=13,
        )
        if save_path is not None:
            from pathlib import Path

            self._save(fig, Path(save_path), dpi=dpi)
        return fig

    def _draw_single_network(
        self,
        ax: Axes,
        sim: Run,
        comparison: HydrographicNetworkComparison,
        *,
        gdf,
        color: str,
        linewidth: float,
        title: str,
        subtitle: str,
        length_m: float,
    ) -> None:
        self._plot_lines(
            ax,
            gdf,
            color=color,
            linewidth=linewidth,
            label=title.lower(),
            alpha=0.95,
        )
        self._finalize_map(ax, sim, comparison, title=title)
        ax.text(
            0.02,
            0.98,
            _single_network_summary_text(
                gdf,
                subtitle=subtitle,
                length_m=length_m,
            ),
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=8.2,
            bbox={"facecolor": "white", "alpha": 0.88, "edgecolor": "#c8c8c8"},
        )

    def _draw_overlay(
        self,
        ax: Axes,
        sim: Run,
        comparison: HydrographicNetworkComparison,
    ) -> None:
        self._plot_tolerance_buffer(
            ax,
            comparison,
            facecolor="#9ecae1",
            alpha=0.18,
            label=f"ref tolerance ({comparison.tolerance_m:.0f} m)",
        )
        self._plot_lines(
            ax,
            comparison.reference_gdf,
            color="#222222",
            linewidth=1.4,
            label="reference",
            alpha=0.95,
        )
        self._plot_lines(
            ax,
            comparison.candidate_gdf,
            color="#2a6f97",
            linewidth=1.15,
            label="generated",
            alpha=0.8,
        )
        self._finalize_map(ax, sim, comparison, title="Overlay + tolerance")
        if ax.has_data():
            ax.legend(
                handles=_overlay_legend_handles(comparison.tolerance_m),
                loc="lower right",
                fontsize=8,
                frameon=True,
            )

    def _draw_difference(
        self,
        ax: Axes,
        sim: Run,
        comparison: HydrographicNetworkComparison,
    ) -> None:
        self._plot_tolerance_buffer(
            ax,
            comparison,
            facecolor="#d9ecf7",
            alpha=0.14,
            label=f"ref tolerance ({comparison.tolerance_m:.0f} m)",
        )
        self._plot_lines(
            ax,
            comparison.reference_matched_gdf,
            color="#c4c4c4",
            linewidth=1.1,
            label="reference matched",
            alpha=1.0,
        )
        self._plot_lines(
            ax,
            comparison.candidate_matched_gdf,
            color="#6ea8c7",
            linewidth=0.9,
            label="generated near ref",
            alpha=0.65,
        )
        self._plot_lines(
            ax,
            comparison.reference_missing_gdf,
            color="#c0392b",
            linewidth=1.5,
            label="reference missing",
            alpha=0.95,
        )
        self._plot_lines(
            ax,
            comparison.candidate_extra_gdf,
            color="#d97706",
            linewidth=1.5,
            label="generated extra",
            alpha=0.95,
        )
        self._finalize_map(ax, sim, comparison, title=f"Diff @ {comparison.tolerance_m:.0f} m")
        ax.text(
            0.02,
            0.98,
            _comparison_summary_text(comparison),
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=8.5,
            bbox={"facecolor": "white", "alpha": 0.88, "edgecolor": "#c8c8c8"},
        )
        if ax.has_data():
            ax.legend(
                handles=_diff_legend_handles(comparison.tolerance_m),
                loc="lower right",
                fontsize=8,
                frameon=True,
            )

    def _finalize_map(
        self,
        ax: Axes,
        sim: Run,
        comparison: HydrographicNetworkComparison,
        *,
        title: str,
    ) -> None:
        overlay_watershed_contour(
            ax,
            sim,
            color="#404040",
            linewidth=0.9,
            alpha=0.7,
            target_crs=comparison.crs,
        )
        bounds = _combined_total_bounds(
            comparison.reference_gdf,
            comparison.candidate_gdf,
        )
        if bounds is not None:
            xmin, ymin, xmax, ymax = bounds
            dx = xmax - xmin
            dy = ymax - ymin
            pad_x = max(dx * 0.04, 1.0)
            pad_y = max(dy * 0.04, 1.0)
            ax.set_xlim(xmin - pad_x, xmax + pad_x)
            ax.set_ylim(ymin - pad_y, ymax + pad_y)
        style_map_axes(ax)
        self.add_scale_bar(ax)
        self.add_north_arrow(ax)
        ax.set_title(title)

    @staticmethod
    def _plot_lines(
        ax: Axes,
        gdf,
        *,
        color: str,
        linewidth: float,
        label: str,
        alpha: float,
    ) -> None:
        if gdf is None or gdf.empty:
            return
        gdf.plot(ax=ax, color=color, linewidth=linewidth, alpha=alpha, label=label, zorder=4)

    @staticmethod
    def _plot_tolerance_buffer(
        ax: Axes,
        comparison: HydrographicNetworkComparison,
        *,
        facecolor: str,
        alpha: float,
        label: str,
    ) -> None:
        if float(comparison.tolerance_m) <= 0.0:
            return
        buffer_gdf = _buffer_gdf(
            comparison.reference_gdf,
            tolerance_m=float(comparison.tolerance_m),
        )
        if buffer_gdf is None or buffer_gdf.empty:
            return
        buffer_gdf.plot(
            ax=ax,
            facecolor=facecolor,
            edgecolor="none",
            alpha=alpha,
            label=label,
            zorder=1,
        )


class _HydrographicNetworkDifferenceRoleFigure(HydrographicNetworkComparisonFigure):
    """Single-panel diff view focused on one discrepancy family."""

    panel_title: str

    def plot(
        self,
        sim: Run,
        *,
        tolerance_m: float = 50.0,
        reference_role: str = "reference",
        candidate_role: str = "generated",
        figsize: tuple[float, float] | None = None,
        dpi: int = 150,
        save_path=None,
        **_,
    ) -> MplFigure:
        import matplotlib.pyplot as plt

        comparison = sim.hydrographic_network_comparison(
            reference_role=reference_role,
            candidate_role=candidate_role,
            tolerance_m=tolerance_m,
        )
        fig, ax = plt.subplots(
            1,
            1,
            figsize=figsize or self.spec.default_figsize,
            dpi=dpi,
            constrained_layout=True,
        )
        self._draw_focus(ax, sim, comparison)
        fig.suptitle(
            f"Hydrographic network comparison - {sim.name or sim.sim_id[:8]}",
            fontweight="bold",
            fontsize=13,
        )
        if save_path is not None:
            from pathlib import Path

            self._save(fig, Path(save_path), dpi=dpi)
        return fig

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        tolerance_m: float = 50.0,
        reference_role: str = "reference",
        candidate_role: str = "generated",
        **_,
    ) -> Axes:
        comparison = sim.hydrographic_network_comparison(
            reference_role=reference_role,
            candidate_role=candidate_role,
            tolerance_m=tolerance_m,
        )
        self._draw_focus(ax, sim, comparison)
        return ax

    def _draw_focus(
        self,
        ax: Axes,
        sim: Run,
        comparison: HydrographicNetworkComparison,
    ) -> None:
        raise NotImplementedError


@register
class HydrographicNetworkReferenceMissingOnlyFigure(_HydrographicNetworkDifferenceRoleFigure):
    spec = FigureSpec(
        name="hydrographic_network_reference_missing_only",
        title="Reference missing-only view",
        kind="comparison",
        default_figsize=(8.2, 5.8),
    )
    panel_title = "Reference missing only"

    def _draw_focus(
        self,
        ax: Axes,
        sim: Run,
        comparison: HydrographicNetworkComparison,
    ) -> None:
        self._plot_tolerance_buffer(
            ax,
            comparison,
            facecolor="#f4e5e2",
            alpha=0.18,
            label=f"ref tolerance ({comparison.tolerance_m:.0f} m)",
        )
        self._plot_lines(
            ax,
            comparison.reference_gdf,
            color="#bbbbbb",
            linewidth=1.2,
            label="reference context",
            alpha=0.95,
        )
        self._plot_lines(
            ax,
            comparison.candidate_gdf,
            color="#9dc2d7",
            linewidth=0.9,
            label="generated context",
            alpha=0.45,
        )
        self._plot_lines(
            ax,
            comparison.reference_missing_gdf,
            color="#c0392b",
            linewidth=1.8,
            label="reference missing",
            alpha=0.98,
        )
        self._finalize_map(ax, sim, comparison, title=self.panel_title)
        ax.text(
            0.02,
            0.98,
            "\n".join(
                [
                    "Focus: reference traces not matched",
                    f"missing ref: {_fmt_km(comparison.missing_reference_length_m)}",
                    f"ref coverage: {_fmt_ratio(comparison.reference_coverage_ratio)}",
                    f"tolerance: {_fmt_m(comparison.tolerance_m)}",
                ]
            ),
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=8.4,
            bbox={"facecolor": "white", "alpha": 0.88, "edgecolor": "#c8c8c8"},
        )
        if ax.has_data():
            ax.legend(
                handles=_reference_missing_legend_handles(comparison.tolerance_m),
                loc="lower right",
                fontsize=8,
                frameon=True,
            )


@register
class HydrographicNetworkGeneratedExtraOnlyFigure(_HydrographicNetworkDifferenceRoleFigure):
    spec = FigureSpec(
        name="hydrographic_network_generated_extra_only",
        title="Generated extra-only view",
        kind="comparison",
        default_figsize=(8.2, 5.8),
    )
    panel_title = "Generated extra only"

    def _draw_focus(
        self,
        ax: Axes,
        sim: Run,
        comparison: HydrographicNetworkComparison,
    ) -> None:
        self._plot_tolerance_buffer(
            ax,
            comparison,
            facecolor="#fff0d9",
            alpha=0.18,
            label=f"ref tolerance ({comparison.tolerance_m:.0f} m)",
        )
        self._plot_lines(
            ax,
            comparison.reference_gdf,
            color="#b0b0b0",
            linewidth=1.1,
            label="reference context",
            alpha=0.8,
        )
        self._plot_lines(
            ax,
            comparison.candidate_gdf,
            color="#9dc2d7",
            linewidth=0.95,
            label="generated context",
            alpha=0.55,
        )
        self._plot_lines(
            ax,
            comparison.candidate_extra_gdf,
            color="#d97706",
            linewidth=1.8,
            label="generated extra",
            alpha=0.98,
        )
        self._finalize_map(ax, sim, comparison, title=self.panel_title)
        ax.text(
            0.02,
            0.98,
            "\n".join(
                [
                    "Focus: generated traces outside ref match",
                    f"extra gen: {_fmt_km(comparison.extra_candidate_length_m)}",
                    f"gen match: {_fmt_ratio(comparison.candidate_match_ratio)}",
                    f"tolerance: {_fmt_m(comparison.tolerance_m)}",
                ]
            ),
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=8.4,
            bbox={"facecolor": "white", "alpha": 0.88, "edgecolor": "#c8c8c8"},
        )
        if ax.has_data():
            ax.legend(
                handles=_generated_extra_legend_handles(comparison.tolerance_m),
                loc="lower right",
                fontsize=8,
                frameon=True,
            )


def _combined_total_bounds(*gdfs) -> tuple[float, float, float, float] | None:
    import numpy as np

    bounds: list[tuple[float, float, float, float]] = []
    for gdf in gdfs:
        if gdf is None or gdf.empty:
            continue
        minx, miny, maxx, maxy = [float(v) for v in gdf.total_bounds]
        if np.isfinite([minx, miny, maxx, maxy]).all():
            bounds.append((minx, miny, maxx, maxy))
    if not bounds:
        return None
    return (
        min(item[0] for item in bounds),
        min(item[1] for item in bounds),
        max(item[2] for item in bounds),
        max(item[3] for item in bounds),
    )


def _buffer_gdf(gdf, *, tolerance_m: float):
    import geopandas as gpd
    from shapely.ops import unary_union

    if gdf is None or gdf.empty or tolerance_m <= 0.0:
        return None
    union = unary_union(list(gdf.geometry))
    if union.is_empty:
        return None
    polygon = union.buffer(float(tolerance_m))
    if polygon.is_empty:
        return None
    return gpd.GeoDataFrame(geometry=[polygon], crs=gdf.crs)


def _comparison_summary_text(comparison: HydrographicNetworkComparison) -> str:
    return "\n".join(
        [
            f"ref length: {_fmt_km(comparison.reference_total_length_m)}",
            f"gen length: {_fmt_km(comparison.candidate_total_length_m)}",
            f"ref coverage: {_fmt_ratio(comparison.reference_coverage_ratio)}",
            f"gen match: {_fmt_ratio(comparison.candidate_match_ratio)}",
            f"length F1: {_fmt_ratio(comparison.length_f1_ratio)}",
            f"missing ref: {_fmt_km(comparison.missing_reference_length_m)}",
            f"extra gen: {_fmt_km(comparison.extra_candidate_length_m)}",
            f"Hausdorff: {_fmt_m(comparison.hausdorff_distance_m)}",
        ]
    )


def _single_network_summary_text(gdf, *, subtitle: str, length_m: float) -> str:
    segment_count = 0 if gdf is None else int(len(getattr(gdf, "index", [])))
    return "\n".join(
        [
            subtitle,
            f"segments: {segment_count}",
            f"length: {_fmt_km(length_m)}",
        ]
    )


def _fmt_ratio(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{100.0 * value:.1f}%"


def _fmt_km(length_m: float | None) -> str:
    if length_m is None:
        return "-"
    return f"{length_m / 1000.0:.2f} km"


def _fmt_m(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1f} m"


def _overlay_legend_handles(tolerance_m: float):
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    return [
        Patch(facecolor="#9ecae1", edgecolor="none", alpha=0.18, label=f"ref tolerance ({tolerance_m:.0f} m)"),
        Line2D([0], [0], color="#222222", linewidth=1.4, label="reference"),
        Line2D([0], [0], color="#2a6f97", linewidth=1.15, label="generated"),
    ]


def _diff_legend_handles(tolerance_m: float):
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    return [
        Patch(facecolor="#d9ecf7", edgecolor="none", alpha=0.14, label=f"ref tolerance ({tolerance_m:.0f} m)"),
        Line2D([0], [0], color="#c4c4c4", linewidth=1.1, label="reference matched"),
        Line2D([0], [0], color="#6ea8c7", linewidth=0.9, label="generated near ref"),
        Line2D([0], [0], color="#c0392b", linewidth=1.5, label="reference missing"),
        Line2D([0], [0], color="#d97706", linewidth=1.5, label="generated extra"),
    ]


def _reference_missing_legend_handles(tolerance_m: float):
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    return [
        Patch(facecolor="#f4e5e2", edgecolor="none", alpha=0.18, label=f"ref tolerance ({tolerance_m:.0f} m)"),
        Line2D([0], [0], color="#bbbbbb", linewidth=1.2, label="reference context"),
        Line2D([0], [0], color="#9dc2d7", linewidth=0.9, label="generated context"),
        Line2D([0], [0], color="#c0392b", linewidth=1.8, label="reference missing"),
    ]


def _generated_extra_legend_handles(tolerance_m: float):
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    return [
        Patch(facecolor="#fff0d9", edgecolor="none", alpha=0.18, label=f"ref tolerance ({tolerance_m:.0f} m)"),
        Line2D([0], [0], color="#b0b0b0", linewidth=1.1, label="reference context"),
        Line2D([0], [0], color="#9dc2d7", linewidth=0.95, label="generated context"),
        Line2D([0], [0], color="#d97706", linewidth=1.8, label="generated extra"),
    ]
