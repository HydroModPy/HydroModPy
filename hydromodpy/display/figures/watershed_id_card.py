"""Watershed identity-card multi-panel figure.

Combines a topography map, outlet marker, a hydrograph preview and
a metadata table into a single compact summary figure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display._map_axes import (
    overlay_watershed_contour,
    style_date_axis,
    style_map_axes,
)
from hydromodpy.display.catalog import register
from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.geo import GeoFigureMixin

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure as MplFigure

    from hydromodpy.results.contracts import RasterField
    from hydromodpy.results.run import Run


# Raster keys written by ``persist_geographic_to_store``. The historical
# "dem" key is kept as a fallback so this figure also works on older Zarrs.
_DEM_RASTER_CANDIDATES = ("watershed_dem", "dem", "watershed_fill")


@register
class WatershedIdCardFigure(GeoFigureMixin, BaseFigure):
    """Four-panel summary: topography, hydrograph, metadata table."""

    spec = FigureSpec(
        name="watershed_id_card",
        title="Watershed identity card",
        kind="comparison",
        default_figsize=(11.5, 7.5),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        **_,
    ) -> Axes:
        ax.set_axis_off()
        ax.text(
            0.5,
            0.5,
            "watershed_id_card has its own plot()",
            ha="center",
            va="center",
        )
        return ax

    def plot(
        self,
        sim: Run,
        *,
        figsize: tuple[float, float] | None = None,
        dpi: int = 150,
        save_path=None,
        **_,
    ) -> MplFigure:
        import matplotlib.pyplot as plt
        from matplotlib.gridspec import GridSpec

        fig = plt.figure(
            figsize=figsize or self.spec.default_figsize,
            dpi=dpi,
            constrained_layout=True,
        )
        # Give the map a bit more vertical room than the hydrograph, and the
        # identity column is narrow since it only holds a compact table.
        gs = GridSpec(2, 2, figure=fig, width_ratios=[3.0, 1.3], height_ratios=[2.2, 1.0])

        ax_topo = fig.add_subplot(gs[0, 0])
        ax_hydro = fig.add_subplot(gs[1, 0])
        ax_meta = fig.add_subplot(gs[:, 1])

        self._draw_topography(ax_topo, sim)
        self._draw_hydrograph(ax_hydro, sim)
        self._draw_metadata(ax_meta, sim)

        fig.suptitle(
            f"Watershed ID card - {sim.name or sim.sim_id[:8]}",
            fontweight="bold",
            fontsize=14,
        )
        if save_path is not None:
            from pathlib import Path

            self._save(fig, Path(save_path), dpi=dpi)
        return fig

    # ------------------------------------------------------------------
    # panel helpers
    # ------------------------------------------------------------------

    def _draw_topography(self, ax: Axes, sim: Run) -> None:
        dem, raster = self._load_dem(sim)
        if dem is None:
            ax.set_axis_off()
            ax.text(
                0.5,
                0.5,
                "no DEM ingested for this run",
                ha="center",
                va="center",
                transform=ax.transAxes,
                fontsize=10,
                color="gray",
            )
            ax.set_title("Topography")
            return

        extent = _extent_from_transform(raster, dem.shape) if raster else None
        # Mask nodata (stored as very-negative sentinel by HMP) so imshow
        # does not smear the colormap across void pixels.
        nodata = raster.nodata if raster else None
        dem_plot = dem.astype(float)
        if nodata is not None:
            dem_plot = np.where(np.isclose(dem_plot, float(nodata)), np.nan, dem_plot)
        dem_plot = np.where(dem_plot < -1e30, np.nan, dem_plot)

        im = ax.imshow(
            dem_plot,
            cmap="terrain",
            origin="upper",
            extent=extent,
            interpolation="nearest",
        )
        ax.figure.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label="Elevation (m)")
        overlay_watershed_contour(ax, sim, color="black", linewidth=1.2)
        self._mark_outlet(ax, sim)
        style_map_axes(ax)
        ax.set_title("Topography")

    def _load_dem(self, sim: Run):
        for name in _DEM_RASTER_CANDIDATES:
            try:
                raster = sim.geographic_raster(name)
            except Exception:
                continue
            if raster.data is None:
                continue
            arr = np.asarray(raster.data)
            if arr.ndim == 3 and arr.shape[0] == 1:
                arr = arr[0]
            if arr.size == 0:
                continue
            return arr, raster
        return None, None

    def _mark_outlet(self, ax: Axes, sim: Run) -> None:
        """Plot a small red star at the outlet station when available."""
        try:
            # geographic_metadata stores outlet coordinates as x_outlet / y_outlet.
            meta = sim._catalog.read_geographic_metadata(sim.sim_id)
        except Exception:
            return
        if not isinstance(meta, dict):
            return
        x_out = _as_float(meta.get("x_outlet"))
        y_out = _as_float(meta.get("y_outlet"))
        if x_out is None or y_out is None:
            return
        ax.plot(
            x_out,
            y_out,
            marker="*",
            markersize=12,
            color="red",
            markeredgecolor="black",
            linestyle="None",
            label="outlet",
            zorder=10,
        )

    def _draw_hydrograph(self, ax: Axes, sim: Run) -> None:
        try:
            ts = sim.timeseries("discharge", station="_catchment")
        except Exception:
            ax.text(
                0.5,
                0.5,
                "no hydrograph",
                ha="center",
                va="center",
                transform=ax.transAxes,
                color="gray",
            )
            ax.set_title("Outlet discharge")
            return

        ax.plot(ts.index, ts.values, color="steelblue", lw=1.2)
        ax.set_ylabel("Q (m³/s)")
        ax.set_xlabel("Date")
        ax.grid(True, ls=":", lw=0.4)
        style_date_axis(ax)
        ax.set_title("Outlet discharge")

    def _draw_metadata(self, ax: Axes, sim: Run) -> None:
        ax.set_axis_off()
        sid = str(sim.sim_id or "")
        sid_short = f"{sid[:8]}…" if len(sid) > 10 else sid
        rows: list[tuple[str, str]] = [
            ("ID", sid_short),
            ("Name", str(sim.name or "-")),
            ("Project", str(sim.project or "-")),
            ("Solver", str(sim.solver or "-")),
            ("Regime", str(sim.flow_regime or "-")),
            ("Status", str(sim.status or "-")),
            ("Cells", _as_int_str(sim.n_cells)),
            ("Layers", _as_int_str(sim.n_layers)),
            ("Timesteps", _as_int_str(sim.n_timesteps)),
        ]
        table = ax.table(
            cellText=[[k, v] for k, v in rows],
            loc="center",
            colWidths=[0.45, 0.55],
            cellLoc="left",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(9)
        table.scale(1.0, 1.4)
        # Lightly tint the label column so the two-column table reads as
        # key/value rather than a raw grid.
        for (_row_idx, col_idx), cell in table.get_celld().items():
            if col_idx == 0:
                cell.set_facecolor("#f2f2f2")
                cell.set_text_props(fontweight="bold")
            cell.set_edgecolor("#c8c8c8")
        ax.set_title("Identity")


# ---------------------------------------------------------------------------
# utilities
# ---------------------------------------------------------------------------


def _extent_from_transform(raster: RasterField, shape: tuple[int, ...]) -> list[float] | None:
    """Compute a matplotlib ``extent`` from a rasterio-style affine transform.

    ``raster.transform`` is stored as a flat 6-tuple (a, b, c, d, e, f). The
    grid extent for ``imshow`` with ``origin='upper'`` is
    ``[xmin, xmax, ymin, ymax]``.
    """
    t = raster.transform
    if not t or len(t) < 6:
        return None
    a, b, c, d, e, f = (float(v) for v in t[:6])
    if shape is None or len(shape) < 2:
        return None
    rows, cols = shape[-2:]
    xmin = c
    xmax = c + a * cols
    ymax = f
    ymin = f + e * rows
    return [xmin, xmax, ymin, ymax]


def _as_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int_str(value) -> str:
    if value in (None, 0):
        return "-"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)
