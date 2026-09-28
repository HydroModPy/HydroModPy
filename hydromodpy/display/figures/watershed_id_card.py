"""Watershed identity-card figure.

Combines a topography map, outlet marker and a metadata table into a single
compact summary figure.

The card opens a gallery, so every row of its table is a fact a first-time
reader can use: what was modelled, where, over which period and on which
grid. The card is drawn before the run is sealed, so it prints nothing that
changes after it is drawn, such as the run status, and nothing a reader
cannot decode, such as the run id.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.figures._instant import run_edges
from hydromodpy.display.maps.axes import (
    overlay_watershed_contour,
    style_map_axes,
)
from hydromodpy.display.style import place_legend
from hydromodpy.results.run.geographic import geographic_metadata

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure as MplFigure

    from hydromodpy.results.run import Run
    from hydromodpy.results.run.contracts import RasterField


# Raster keys written by ``persist_geographic_to_store``. The historical
# "dem" key is kept as a fallback so this figure also works on older Zarrs.
_DEM_RASTER_CANDIDATES = ("watershed_dem", "dem", "watershed_fill")

VALUE_WIDTH = 26
"""Characters a value line of the identity table holds before it wraps."""

VALUE_LINES = 2
"""Lines a value may take; a longer one is cut with an ellipsis."""

_SOLVER_NAMES: dict[str, str] = {
    "modflow6": "MODFLOW 6",
    "modflow_nwt": "MODFLOW-NWT",
    "boussinesq": "Boussinesq",
    "gr4j": "GR4J",
}
"""How the card names a solver backend."""

_MISSING_FEATURE = (KeyError, ValueError, FileNotFoundError, RuntimeError)
"""What a run raises when it never wrote the feature a row reads."""


@register
class WatershedIdCardFigure(BaseFigure):
    """Compact summary: topography and metadata table."""

    spec = FigureSpec(
        name="watershed_id_card",
        title="Watershed identity card",
        kind="spatial",
        default_figsize=(11.5, 7.5),
    )

    def unavailable_reason(self, sim: Run) -> str | None:
        """Require a DEM raster of the catchment, which ``spec`` cannot declare."""
        reason = super().unavailable_reason(sim)
        if reason is not None:
            return reason
        dem, _raster = self._load_dem(sim)
        if dem is None:
            return f"run holds no DEM raster ({', '.join(_DEM_RASTER_CANDIDATES)})"
        return None

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
        # The identity column is narrow since it only holds a compact table.
        gs = GridSpec(1, 2, figure=fig, width_ratios=[2.5, 1.5])

        ax_topo = fig.add_subplot(gs[0, 0])
        ax_meta = fig.add_subplot(gs[0, 1])

        self._draw_topography(ax_topo, sim)
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
            raise ValueError(f"run holds no DEM raster ({', '.join(_DEM_RASTER_CANDIDATES)})")

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
        place_legend(ax, fontsize=8, framealpha=0.9)
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
        """Mark the outlet the catchment was delineated from, and the declared one.

        The two are not the same point: the snap moves the declared coordinate
        onto the strongest accumulation cell within ``snap_dist``, and the
        catchment comes from the moved one. Drawing only the declared point put
        the star where the run never started.
        """
        try:
            # geographic_metadata stores outlet coordinates as x_outlet / y_outlet.
            meta = geographic_metadata(sim)
        except Exception:
            return
        if not isinstance(meta, dict):
            return
        x_out = _as_float(meta.get("x_outlet"))
        y_out = _as_float(meta.get("y_outlet"))
        if x_out is None or y_out is None:
            return

        x_snap = _as_float(meta.get("x_outlet_snapped"))
        y_snap = _as_float(meta.get("y_outlet_snapped"))
        moved = _as_float(meta.get("outlet_snap_distance_m"))
        snapped = x_snap is not None and y_snap is not None

        if snapped and moved is not None and moved > 0.0:
            # A hollow marker on the declared point, so the gap is visible.
            ax.plot(
                x_out,
                y_out,
                marker="o",
                markersize=7,
                markerfacecolor="none",
                markeredgecolor="red",
                linestyle="None",
                label=f"declared outlet ({moved:.0f} m away)",
                zorder=9,
            )
        ax.plot(
            x_snap if snapped else x_out,
            y_snap if snapped else y_out,
            marker="*",
            markersize=12,
            color="red",
            markeredgecolor="black",
            linestyle="None",
            label="outlet",
            zorder=10,
        )

    def _draw_metadata(self, ax: Axes, sim: Run) -> None:
        ax.set_axis_off()
        rows = [(key, wrap_value(value)) for key, value in identity_rows(sim)]
        table = ax.table(
            cellText=[[k, v] for k, v in rows],
            loc="center",
            colWidths=[0.4, 0.6],
            cellLoc="left",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(9)
        # A wrapped value takes the height of its lines, so no row spills
        # over the next one.
        base = 0.055
        for (row_idx, col_idx), cell in table.get_celld().items():
            lines = rows[row_idx][1].count("\n") + 1
            cell.set_height(base * (1.0 + 0.75 * (lines - 1)))
            # Lightly tint the label column so the two-column table reads as
            # key/value rather than a raw grid.
            if col_idx == 0:
                cell.set_facecolor("#f2f2f2")
                cell.set_text_props(fontweight="bold")
            cell.set_edgecolor("#c8c8c8")
        ax.set_title("Identity")


# ---------------------------------------------------------------------------
# identity rows
# ---------------------------------------------------------------------------


def identity_rows(sim: Run) -> list[tuple[str, str]]:
    """Return the ``(key, value)`` rows the identity table prints, in order.

    A row whose value the run does not hold is left out rather than printed
    as a dash.
    """
    rows: list[tuple[str, str | None]] = [
        ("Run", _text(sim.name)),
        ("Project", _text(sim.project)),
        ("Solver", _solver_name(sim.solver)),
        ("Regime", _text(sim.flow_regime)),
        ("Period", _period_text(sim)),
        ("Time steps", _steps_text(sim)),
        ("Catchment area", _area_text(sim)),
        ("Model cells", _as_int_str(sim.n_cells)),
        ("Layers", _as_int_str(sim.n_layers)),
    ]
    return [(key, value) for key, value in rows if value]


def wrap_value(text: str, *, width: int = VALUE_WIDTH, max_lines: int = VALUE_LINES) -> str:
    """Wrap one table value on its word, underscore or dash boundaries.

    Run and project names are snake_case, so a plain word wrap finds no place
    to break them. A value longer than ``max_lines`` lines ends with an
    ellipsis.
    """
    tokens = [token for token in re.split(r"(?<=[_\-\s/])", str(text)) if token]
    lines: list[str] = []
    current = ""
    for token in tokens:
        while len(token) > width:
            if current:
                lines.append(current)
                current = ""
            lines.append(token[:width])
            token = token[width:]
        if len(current) + len(token) > width and current:
            lines.append(current)
            current = ""
        current += token
    if current:
        lines.append(current)
    lines = [line.rstrip() for line in lines]
    if len(lines) > max_lines:
        kept = lines[:max_lines]
        kept[-1] = kept[-1][: width - 1].rstrip() + "\u2026"
        lines = kept
    return "\n".join(lines)


def _text(value) -> str | None:
    """Return a value as text, or None when the run holds none."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _solver_name(solver) -> str | None:
    """Return how the card names a solver backend."""
    text = _text(solver)
    if text is None:
        return None
    return _SOLVER_NAMES.get(text.lower(), text)


def _period_text(sim: Run) -> str | None:
    """Return the simulated period, first and last day included."""
    edges = run_edges(sim)
    if edges is None:
        return None
    first, end = edges[0], edges[-1]
    last = end - pd.Timedelta(1, unit="D") if end == end.normalize() else end
    return f"{first:%Y-%m-%d} to {last:%Y-%m-%d}"


def _steps_text(sim: Run) -> str | None:
    """Return the number of time steps and their cadence when it is regular."""
    count = _as_int_str(sim.n_timesteps)
    if count == "-":
        return None
    edges = run_edges(sim)
    if edges is None or len(edges) < 2:
        return count
    days = np.diff(edges.asi8) / 8.64e13
    cadence = _cadence(days)
    return f"{count} {cadence}" if cadence else count


def _cadence(days: np.ndarray) -> str | None:
    """Return the word for a regular step length in days, or None."""
    if days.size == 0:
        return None
    low, high = float(days.min()), float(days.max())
    if low == high == 1.0:
        return "daily"
    if 28.0 <= low and high <= 31.0:
        return "monthly"
    if 365.0 <= low and high <= 366.0:
        return "yearly"
    return None


def _area_text(sim: Run) -> str | None:
    """Return the area of the delineated catchment in km², or None."""
    try:
        watershed = sim.geographic("watershed")
    except _MISSING_FEATURE:
        return None
    if watershed is None or watershed.empty:
        return None
    crs = watershed.crs
    if crs is not None and not crs.is_projected:
        return None
    area_km2 = float(watershed.geometry.area.sum()) / 1e6
    if not np.isfinite(area_km2) or area_km2 <= 0.0:
        return None
    return f"{area_km2:,.1f} km²"


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
