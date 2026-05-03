"""Standalone views of one canonical hydrographic network by role."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hydromodpy.display._map_axes import overlay_watershed_contour, style_map_axes
from hydromodpy.display.catalog import register
from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.geo import GeoFigureMixin

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


class _HydrographicNetworkRoleFigure(GeoFigureMixin, BaseFigure):
    """Render one persisted hydrographic network for a fixed canonical role."""

    role: str
    color: str
    title: str
    subtitle: str

    def render(self, sim: Run, ax: Axes, **_) -> Axes:
        raw_gdf = sim.hydrographic_network(self.role)
        if raw_gdf is None or raw_gdf.empty:
            raise KeyError(
                f"hydrographic network figure '{self.spec.name}': "
                f"no '{self.role}' network for sim {sim.sim_id}"
            )

        watershed = _read_watershed(sim)
        fallback_crs = None if watershed is None else watershed.crs
        gdf = _project_gdf_for_metric_operations(raw_gdf, fallback_crs=fallback_crs)
        if watershed is not None and gdf.crs is not None and watershed.crs is not None:
            if str(watershed.crs) != str(gdf.crs):
                watershed = watershed.to_crs(gdf.crs)

        gdf.plot(ax=ax, color=self.color, linewidth=1.3, alpha=0.95, zorder=4)
        if watershed is not None and not watershed.empty:
            watershed.boundary.plot(
                ax=ax,
                color="#404040",
                linewidth=0.9,
                alpha=0.7,
                zorder=5,
            )
        else:
            overlay_watershed_contour(
                ax,
                sim,
                color="#404040",
                linewidth=0.9,
                alpha=0.7,
                target_crs=None if gdf.crs is None else str(gdf.crs),
            )
        bounds = _total_bounds(gdf)
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
        ax.set_title(self.title)
        ax.text(
            0.02,
            0.98,
            "\n".join(
                [
                    self.subtitle,
                    f"segments: {int(len(gdf.index))}",
                    f"length: {_fmt_km(_measure_linework_length_m(gdf))}",
                ]
            ),
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=8.2,
            bbox={"facecolor": "white", "alpha": 0.88, "edgecolor": "#c8c8c8"},
        )
        return ax


@register
class HydrographicNetworkReferenceFigure(_HydrographicNetworkRoleFigure):
    spec = FigureSpec(
        name="hydrographic_network_reference",
        title="Loaded hydrographic network",
        kind="comparison",
        default_figsize=(7.8, 5.8),
    )
    role = "reference"
    color = "#222222"
    title = "Loaded reference"
    subtitle = "data.hydrography"


@register
class HydrographicNetworkGeneratedFigure(_HydrographicNetworkRoleFigure):
    spec = FigureSpec(
        name="hydrographic_network_generated",
        title="Generated hydrographic network",
        kind="comparison",
        default_figsize=(7.8, 5.8),
    )
    role = "generated"
    color = "#2a6f97"
    title = "Generated from DEM"
    subtitle = "geographic.river_network"


def _total_bounds(gdf) -> tuple[float, float, float, float] | None:
    import numpy as np

    if gdf is None or gdf.empty:
        return None
    minx, miny, maxx, maxy = [float(v) for v in gdf.total_bounds]
    if not np.isfinite([minx, miny, maxx, maxy]).all():
        return None
    return (minx, miny, maxx, maxy)


def _read_watershed(sim: Run):
    try:
        gdf = sim.geographic("watershed")
    except Exception:
        return None
    if gdf is None or gdf.empty:
        return None
    return gdf


def _project_gdf_for_metric_operations(gdf, *, fallback_crs: str | object | None = None):
    if gdf is None or gdf.empty:
        return gdf

    out = gdf.copy()
    source_crs = _coerce_crs(out.crs)
    fallback = _coerce_crs(fallback_crs)
    if source_crs is None and fallback is not None:
        out = out.set_crs(fallback, allow_override=True)
        source_crs = fallback

    if source_crs is None or getattr(source_crs, "is_projected", False):
        return out

    target = None
    try:
        target = out.estimate_utm_crs()
    except Exception:
        target = None
    if target is None and fallback is not None and getattr(fallback, "is_projected", False):
        target = fallback
    return out if target is None else out.to_crs(target)


def _measure_linework_length_m(gdf) -> float:
    import numpy as np

    if gdf is None or gdf.empty:
        return 0.0
    metric_gdf = _project_gdf_for_metric_operations(gdf)
    return float(np.sum(np.asarray(metric_gdf.length, dtype=float)))


def _coerce_crs(crs_like) -> object | None:
    if crs_like in (None, ""):
        return None
    try:
        from pyproj import CRS

        return CRS.from_user_input(crs_like)
    except Exception:
        return None


def _fmt_km(length_m: float | None) -> str:
    if length_m is None:
        return "-"
    return f"{length_m / 1000.0:.2f} km"
