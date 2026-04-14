"""Transport concentration frame-loop orchestration.

The frame-by-frame loop is orchestration logic and stays here.
Per-frame rendering is delegated to :mod:`hydromodpy.analysis.display.figures`.

The old ``build_concentration_gif`` and ``plot_web_animation`` functions
now live in :mod:`hydromodpy.analysis.display.figures.animation` as ``build_gif``
and ``build_plotly_slider``.
"""
from __future__ import annotations

from pathlib import Path

from hydromodpy.core.tools import get_logger

logger = get_logger(__name__)


# ------------------------------------------------------------------
# Data-loading helpers (unchanged)
# ------------------------------------------------------------------

def _resolve_ucn_path(model_transport) -> Path:
    """Resolve the binary concentration file path for a transport run."""
    path_file = getattr(model_transport, "path_file", None)
    if path_file is not None:
        return Path(path_file)

    full_path = getattr(model_transport, "full_path", None)
    model_name_mt = getattr(model_transport, "model_name_mt", None)
    candidates: list[Path] = []
    if full_path is not None and model_name_mt is not None:
        full_path = Path(full_path)
        candidates.extend([
            full_path / f"{model_name_mt}.UCN",
            full_path / f"{model_name_mt}.ucn",
        ])
    if full_path is not None:
        candidates.append(Path(full_path) / "MT3D001.UCN")

    for candidate in candidates:
        if candidate.exists():
            return candidate
    if candidates:
        return candidates[0]
    raise ValueError(
        "Transport plotting requires model_transport.path_file "
        "or full_path/model_name_mt."
    )


def _load_concentration_cube(model_transport):
    """Load the full 3D concentration time cube from binary output."""
    import flopy.utils.binaryfile as bf

    path_ucn = _resolve_ucn_path(model_transport)
    try:
        ucnobj = bf.UcnFile(path_ucn)
        concentration = ucnobj.get_alldata(mflay=None)
    except Exception:
        try:
            headobj = bf.HeadFile(path_ucn, text="CONCENTRATION", precision="double")
            concentration = headobj.get_alldata(mflay=None)
        except Exception:
            headobj = bf.HeadFile(path_ucn, text="CONCENTRATION", precision="single")
            concentration = headobj.get_alldata(mflay=None)

    concentration = concentration.astype(float)
    concentration[concentration >= 1e30] = float("nan")
    return concentration


def _input_concentration_mg_l(model_transport) -> float:
    """Estimate the injected concentration in mg/L for reference lines."""
    sconc_input = getattr(model_transport, "sconc_input", None)
    if sconc_input is None:
        return 0.0
    if isinstance(sconc_input, dict) and sconc_input:
        first_key = sorted(sconc_input)[0]
        return float(sconc_input[first_key].mean()) * 1000
    return float(sconc_input) * 1000


def _load_outflow_drain_array(
    model_modflow,
    stress_period: int,
    *,
    fallback_shape: tuple[int, int] | None = None,
    outflow_drain_cache: dict | None = None,
    store=None,
    sim_id: str | None = None,
):
    """Load one flow outflow mask from catalog/store or cache."""
    import numpy as np

    # Try catalog/store first.
    if store is not None and sim_id is not None:
        try:
            arr = store.query_field(sim_id, "outflow_drain", stress_period)
            return np.asarray(arr, dtype=float)
        except Exception:
            pass

    # Try pre-loaded cache.
    if outflow_drain_cache is not None:
        seep = outflow_drain_cache.get(stress_period)
        if seep is not None:
            return np.asarray(seep)

    # Fallback: zero array.
    if fallback_shape is None:
        nrow = getattr(model_modflow, "nrow", None)
        ncol = getattr(model_modflow, "ncol", None)
        if nrow is not None and ncol is not None:
            fallback_shape = (int(nrow), int(ncol))
    if fallback_shape is not None:
        return np.zeros(fallback_shape, dtype=float)

    raise KeyError(
        f"Flow outflow drainage series does not contain stress period {stress_period}."
    )


# ------------------------------------------------------------------
# Frame-loop orchestration
# ------------------------------------------------------------------

def plot_concentration_frames(
    *,
    model_transport,
    model_modflow,
    geographic,
    hydrography,
    recharge_series,
    base_raster_path: Path | None = None,
    output_dir: Path,
    prefix: str,
    dpi: int = 300,
    save_frames: bool = True,
    show_last_frame: bool = False,
) -> list[Path]:
    """Render one concentration frame per stress period and return their paths.

    Each frame is a two-panel figure:
    - top: concentration temporal evolution (delegated to
      :func:`~hydromodpy.analysis.display.figures.timeseries.render_concentration_panel`);
    - bottom: seepage map (delegated to
      :func:`~hydromodpy.analysis.display.figures.spatial.render_concentration_map`).
    """
    import geopandas as gpd
    import matplotlib.colors as mcolors
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import rasterio

    from hydromodpy.analysis.display.figures.spatial import render_concentration_map
    from hydromodpy.analysis.display.figures.timeseries import render_concentration_panel

    if save_frames:
        output_dir.mkdir(parents=True, exist_ok=True)

    concentration_cube = _load_concentration_cube(model_transport) * 1000
    nper = int(model_modflow.nper)
    offset = max(int(concentration_cube.shape[0]) - nper, 0)
    nframes = min(nper, len(recharge_series), max(int(concentration_cube.shape[0]) - offset, 0))
    if nframes <= 0:
        return []

    input_no3 = _input_concentration_mg_l(model_transport)
    recharge_month = recharge_series.iloc[:nframes] * 1000 * 30

    watershed = gpd.read_file(geographic.watershed_shp)
    streams = (
        gpd.read_file(hydrography.streams)
        if hydrography is not None and hydrography.streams is not None
        else None
    )

    dem_path = Path(
        base_raster_path
        if base_raster_path is not None
        else getattr(model_modflow, "dem_watershed_path", geographic.watershed_dem)
    )

    frame_paths: list[Path] = []
    all_box_stats: list[tuple[float, list[dict]]] = []
    mean_vals: list[float] = []
    mean_times: list[float] = []
    last_figure = None

    outflow_drain_cache: dict | None = None
    _store = getattr(model_modflow, "_store", None)
    _sim_id = getattr(model_modflow, "_sim_id", None)

    with rasterio.open(dem_path) as dem:
        dem_data = dem.read(1)
        nodata = dem.nodata if dem.nodata is not None else -9999.0
        dem_mask = np.ma.masked_where(np.isclose(dem_data, float(nodata)), dem_data)
        dem_transform = dem.transform

        for i in range(nframes):
            seep = _load_outflow_drain_array(
                model_modflow, i,
                fallback_shape=dem_data.shape,
                store=_store,
                sim_id=_sim_id,
                outflow_drain_cache=outflow_drain_cache,
            )

            concentration_surface = concentration_cube[offset + i][0]
            concentration_surface = np.ma.masked_where(seep <= 0, concentration_surface)
            values = np.asarray(concentration_surface).astype(float).ravel()
            values = values[~np.isnan(values)]
            if values.size == 0:
                continue

            # Accumulate stats
            xpos = mdates.date2num(pd.to_datetime(recharge_month.index[i]))
            mean = float(np.nanmean(values))
            box_stats = [{
                "med": float(np.nanmedian(values)),
                "mean": mean,
                "q1": float(np.nanmin(values)),
                "q3": float(np.nanmax(values)),
                "whislo": float(np.nanmin(values)),
                "whishi": float(np.nanmax(values)),
                "fliers": [],
            }]
            mean_vals.append(mean)
            mean_times.append(xpos)
            all_box_stats.append((xpos, box_stats))

            # Build 2-panel figure (ultraplot when available)
            from hydromodpy.analysis.display.common import make_figure

            fig, axs = make_figure(
                nrows=2, ncols=1, figsize=(8, 12), dpi=dpi,
                gridspec_kw={"height_ratios": [1, 3]},
            )
            ax_top, ax_bot = axs.ravel()

            # Top panel — concentration evolution
            render_concentration_panel(
                ax_top,
                box_stats=all_box_stats,
                mean_times=mean_times,
                mean_vals=mean_vals,
                recharge_month=recharge_month,
                xpos=xpos,
                input_conc=input_no3,
                nframes=nframes,
            )

            # Bottom panel — concentration map
            vmin = max(1e-6, float(np.nanmin(values)))
            vmax = max(vmin, float(np.nanmax(values)))
            norm = mcolors.LogNorm(vmin=vmin, vmax=vmax)

            concentration_display = np.ma.masked_where(
                np.isclose(dem_data, float(nodata)),
                concentration_surface.copy(),
            )
            render_concentration_map(
                ax_bot,
                dem_masked=dem_mask,
                dem_transform=dem_transform,
                concentration_masked=concentration_display,
                watershed_gdf=watershed,
                streams_gdf=streams,
                norm=norm,
            )

            fig.tight_layout()

            if save_frames:
                frame_path = output_dir / f"{prefix}_{i:03d}.png"
                fig.savefig(frame_path, dpi=dpi, bbox_inches="tight")
                frame_paths.append(frame_path)

            if show_last_frame:
                if last_figure is not None:
                    plt.close(last_figure)
                last_figure = fig
            else:
                plt.close(fig)

    if show_last_frame and last_figure is not None:
        plt.show()
        plt.close(last_figure)

    return frame_paths


# ------------------------------------------------------------------
# Backward-compatible aliases (deprecated)
# ------------------------------------------------------------------

def build_concentration_gif(**kwargs):
    """Deprecated — use :func:`hydromodpy.analysis.display.figures.animation.build_gif`."""
    from hydromodpy.analysis.display.figures.animation import build_gif
    return build_gif(**kwargs)


def plot_web_animation(**kwargs):
    """Deprecated — use :func:`hydromodpy.analysis.display.figures.animation.build_plotly_slider`."""
    from hydromodpy.analysis.display.figures.animation import build_plotly_slider
    return build_plotly_slider(**kwargs)
