"""Watershed ID-card figure: topography panel and metadata table."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.calibration.reporting.network_transient import io as _nt_io
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.run import Run

_float = _nt_io.coerce_float


def _open_first_run(root: Path) -> tuple[Catalog, Run]:
    catalog = Catalog(root)
    try:
        sims = catalog.simulations
        if sims.empty:
            raise RuntimeError(f"no simulation in {root}")
        return catalog, Run.from_id(catalog, str(sims.iloc[0]["sim_id"]))
    except Exception:
        catalog.close()
        raise


def _save_watershed_id_card(root: Path, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    path.parent.mkdir(parents=True, exist_ok=True)
    catalog: Catalog | None = None
    fig = None
    try:
        try:
            catalog, run = _open_first_run(root)
        except Exception:
            fig = _plot_watershed_id_card_placeholder(root)
        else:
            fig = _plot_watershed_id_card(run)
        fig.savefig(path, dpi=150, bbox_inches="tight")
    finally:
        if fig is not None:
            plt.close(fig)
        if catalog is not None:
            catalog.close()


def _plot_watershed_id_card(run: Run):
    import matplotlib.pyplot as plt
    from matplotlib.gridspec import GridSpec

    fig = plt.figure(figsize=(11.5, 7.5), dpi=150, constrained_layout=True)
    gs = GridSpec(1, 2, figure=fig, width_ratios=[3.0, 1.3])
    ax_topo = fig.add_subplot(gs[0, 0])
    ax_meta = fig.add_subplot(gs[0, 1])

    _draw_watershed_topography(ax_topo, run)
    _draw_watershed_metadata(ax_meta, run)
    fig.suptitle(
        f"Watershed ID card - {run.name or str(run.sim_id)[:8]}",
        fontweight="bold",
        fontsize=14,
    )
    return fig


def _plot_watershed_id_card_placeholder(root: Path):
    import matplotlib.pyplot as plt
    from matplotlib.gridspec import GridSpec

    fig = plt.figure(figsize=(11.5, 7.5), dpi=150, constrained_layout=True)
    gs = GridSpec(1, 2, figure=fig, width_ratios=[3.0, 1.3])
    ax_topo = fig.add_subplot(gs[0, 0])
    ax_meta = fig.add_subplot(gs[0, 1])

    ax_topo.set_axis_off()
    ax_topo.text(
        0.5,
        0.5,
        "reference run unavailable",
        ha="center",
        va="center",
        transform=ax_topo.transAxes,
        fontsize=10,
        color="gray",
    )
    ax_topo.set_title("Topography")

    ax_meta.set_axis_off()
    rows = [
        ("Reference", root.name or "-"),
        ("Status", "unavailable"),
    ]
    table = ax_meta.table(
        cellText=[[key, value] for key, value in rows],
        loc="center",
        colWidths=[0.45, 0.55],
        cellLoc="left",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.0, 1.4)
    for (_row_idx, col_idx), cell in table.get_celld().items():
        if col_idx == 0:
            cell.set_facecolor("#f2f2f2")
            cell.set_text_props(fontweight="bold")
        cell.set_edgecolor("#c8c8c8")
    ax_meta.set_title("Identity")
    fig.suptitle("Watershed ID card", fontweight="bold", fontsize=14)
    return fig


def _draw_watershed_topography(ax: Any, run: Run) -> None:
    dem, raster = _load_run_dem(run)
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

    extent = _extent_from_transform(raster, dem.shape) if raster is not None else None
    nodata = getattr(raster, "nodata", None)
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
    _mark_watershed_outlet(ax, run)
    ax.set_title("Topography")
    ax.set_aspect("equal")
    ax.grid(True, color="#d7dee5", linewidth=0.4, alpha=0.55)
    ax.set_xlabel("x")
    ax.set_ylabel("y")


def _load_run_dem(run: Run) -> tuple[np.ndarray | None, Any | None]:
    for name in ("watershed_dem", "dem", "watershed_fill"):
        try:
            raster = run.geographic_raster(name)
        except Exception:
            continue
        data = getattr(raster, "data", None)
        if data is None:
            continue
        arr = np.asarray(data)
        if arr.ndim == 3 and arr.shape[0] == 1:
            arr = arr[0]
        if arr.size:
            return arr, raster
    return None, None


def _mark_watershed_outlet(ax: Any, run: Run) -> None:
    try:
        meta = run._catalog.read_geographic_metadata(run.sim_id)
    except Exception:
        return
    if not isinstance(meta, dict):
        return
    x_out = _float(meta.get("x_outlet"))
    y_out = _float(meta.get("y_outlet"))
    if not np.isfinite(x_out) or not np.isfinite(y_out):
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
    ax.legend(loc="best")


def _draw_watershed_metadata(ax: Any, run: Run) -> None:
    ax.set_axis_off()
    sid = str(run.sim_id or "")
    sid_short = f"{sid[:8]}..." if len(sid) > 10 else sid
    rows = [
        ("ID", sid_short),
        ("Name", str(run.name or "-")),
        ("Project", str(run.project or "-")),
        ("Solver", str(run.solver or "-")),
        ("Regime", str(run.flow_regime or "-")),
        ("Status", str(run.status or "-")),
        ("Cells", _as_int_str(run.n_cells)),
        ("Layers", _as_int_str(run.n_layers)),
        ("Timesteps", _as_int_str(run.n_timesteps)),
    ]
    table = ax.table(
        cellText=[[key, value] for key, value in rows],
        loc="center",
        colWidths=[0.45, 0.55],
        cellLoc="left",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.0, 1.4)
    for (_row_idx, col_idx), cell in table.get_celld().items():
        if col_idx == 0:
            cell.set_facecolor("#f2f2f2")
            cell.set_text_props(fontweight="bold")
        cell.set_edgecolor("#c8c8c8")
    ax.set_title("Identity")


def _extent_from_transform(raster: Any, shape: tuple[int, ...]) -> list[float] | None:
    transform = getattr(raster, "transform", None)
    if not transform or len(transform) < 6 or len(shape) < 2:
        return None
    a, _b, c, _d, e, f = (float(value) for value in transform[:6])
    rows, cols = shape[-2:]
    xmin = c
    xmax = c + a * cols
    ymax = f
    ymin = f + e * rows
    return [xmin, xmax, ymin, ymax]


def _as_int_str(value: Any) -> str:
    if value in (None, 0):
        return "-"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)
