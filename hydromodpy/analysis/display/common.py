"""Shared utilities used by the display package.

The goal of this module is to centralize the repetitive plumbing used by the
plotting code:
- resolving the conventional output folders used by HydroModPy;
- creating directories only when disk output is really requested;
- applying one consistent Matplotlib lifecycle policy (save, show, close).

Keeping these concerns here makes the plotting functions easier to read, because
they can stay focused on data extraction and figure composition.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import matplotlib.pyplot as plt
import pandas as pd

from hydromodpy.analysis.display.display_config import DisplayOptions

if TYPE_CHECKING:
    from hydromodpy.data.contracts.load_result import LoadResult
    from hydromodpy.analysis.display.flow_payloads import FlowSpatialFigurePayload


def make_figure(*, nrows=1, ncols=1, figsize=None, dpi=300, **kw):
    """Create a Matplotlib figure and axes.

    Accepts extra kwargs (``sharex``, ``sharey``, ``hspace``, etc.)
    and forwards what ``plt.subplots`` accepts.  Unknown keys are
    silently dropped so callers written for ultraplot still work.
    """
    # Filter kwargs to only what plt.subplots supports.
    gridspec_keys = {"hspace", "wspace", "height_ratios", "width_ratios"}
    subplot_kw = {}
    gridspec_kw = {}
    for k, v in kw.items():
        if k in gridspec_keys:
            gridspec_kw[k] = v
        elif k in ("sharex", "sharey"):
            # plt.subplots accepts bool or 'row'/'col'/'all', not int.
            subplot_kw[k] = bool(v) if isinstance(v, (int, float)) else v
    fig, axs = plt.subplots(
        nrows, ncols, figsize=figsize, dpi=dpi,
        gridspec_kw=gridspec_kw or None,
        **subplot_kw,
    )
    return fig, axs


def _single_axes(axs):
    """Normalise *axs* returned by :func:`make_figure` to a single Axes.

    Both Matplotlib and ultraplot may return either a bare Axes or an
    array-like container when ``nrows=ncols=1``; this helper handles both.
    """
    import numpy as np

    if isinstance(axs, np.ndarray):
        return axs.flat[0]
    try:
        return axs[0]
    except (TypeError, KeyError, IndexError):
        return axs


def _extract_recharge_series_m_per_day(
    recharge_result: "LoadResult | None",
) -> pd.Series | None:
    """Extract a recharge time series in m/day from a LoadResult.

    Data managers output mm/day; this converts to m/day to match the
    unit expected by the display layer.
    """
    if recharge_result is None:
        return None
    from hydromodpy.process.forcing.forcing_bridge import build_forcing_series

    return build_forcing_series(
        recharge_result, unit_conversion_factor=0.001, label="recharge"
    )


def ensure_dir(path: Path) -> Path:
    """Ensure an output directory exists and return the same path.

    This helper is intentionally tiny, but it avoids repeating
    ``mkdir(parents=True, exist_ok=True)`` across the package.
    Returning the path keeps call sites concise when building save targets.
    """

    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_model_figure_dir(workspace, run_id: str) -> Path:
    """Build the standard figure output directory for one run.

    Uses ``<project_root>/exports/<run_id>/figures/`` so that all
    user-facing outputs live under ``exports/``.
    """
    return Path(workspace.project_root) / "exports" / run_id / "figures"


def resolve_shared_figure_dir(workspace) -> Path:
    """Build the shared figure directory used for workspace-level outputs."""
    return Path(workspace.project_root) / "figures"


def load_field_dict_from_store(
    store,
    sim_id: str,
    variable: str,
) -> dict | None:
    """Load a multi-timestep spatial field from a SimulationCatalog (or compatible store).

    Returns a dict mapping timestep index to ndarray, or ``None``
    if the variable is not found.  This is the canonical way to load
    spatial field data for display — all display modules should use it
    instead of reading ``.npy`` files.
    """
    import numpy as np

    try:
        sims = store.list_simulations(sim_id=sim_id)
        if sims.empty:
            return None
        raw_nt = sims.iloc[0].get("n_timesteps")
        try:
            n_timesteps = int(raw_nt) if raw_nt is not None and not pd.isna(raw_nt) else 1
        except (TypeError, ValueError):
            n_timesteps = 1
    except Exception:
        n_timesteps = 1

    result: dict[int, np.ndarray] = {}
    for t in range(max(n_timesteps, 1)):
        try:
            result[t] = store.query_field(sim_id, variable, t)
        except Exception:
            break
    # Scan beyond n_timesteps in case metadata was incomplete.
    if result:
        t = max(result) + 1
        while True:
            try:
                result[t] = store.query_field(sim_id, variable, t)
                t += 1
            except Exception:
                break
    return result if result else None


def resolve_flow_base_raster(flow_model, geographic) -> Path:
    """Return the raster template aligned with the active flow solver grid.

    New solver runs can decouple their planar discretization from the native
    geographic DEM. When that happens, plots must use the solver template
    raster instead of the original geographic raster, otherwise overlays and
    array-based diagnostics drift out of alignment.
    """

    path = getattr(flow_model, "dem_watershed_path", None)
    if path is None:
        path = getattr(geographic, "watershed_dem", None)
    if path is None:
        raise ValueError("Unable to resolve a base raster for flow display outputs")
    return Path(path)


def _maximize_figure_window() -> None:
    """Maximize the current matplotlib window (best-effort, backend-agnostic)."""
    try:
        mgr = plt.get_current_fig_manager()
        try:
            mgr.window.showMaximized()       # Qt5 / Qt6
        except AttributeError:
            try:
                mgr.window.state("zoomed")   # TkAgg on Windows
            except AttributeError:
                try:
                    mgr.frame.Maximize(True)  # WxAgg
                except AttributeError:
                    pass
    except Exception:
        pass


def finalize_figure(
    fig,
    *,
    options: DisplayOptions,
    save_path: Path | None = None,
) -> None:
    """Apply the common save/show/close policy for a Matplotlib figure.

    Every plotting function eventually delegates to this helper so that figure
    behavior stays predictable:
- if ``options.save`` is enabled and a path is provided, the figure is written;
- if ``options.show`` is enabled, Matplotlib displays the figure;
- otherwise, the figure is explicitly closed to avoid accumulating open figures
  in non-interactive runs such as tests, scripts, or CI.
    """

    if options.save and save_path is not None:
        # Create the output tree lazily so display-only runs do not touch disk.
        ensure_dir(save_path.parent)
        fig.savefig(save_path, dpi=options.dpi, bbox_inches="tight")

    if options.show:
        _maximize_figure_window()
        plt.show()
    else:
        # Always close in non-interactive mode to avoid leaking Matplotlib state.
        plt.close(fig)


def plot_common_flow_spatial_outputs(
    payload: "FlowSpatialFigurePayload | None",
    *,
    options: DisplayOptions,
    output_dir: Path,
) -> bool:
    """Render generic flow spatial figures from the common payload."""
    if payload is None:
        return False

    from hydromodpy.analysis.display.figures.flow_synthesis import (
        FLOW_SPATIAL_FIELD_SPECS,
        plot_flow_spatial_field,
        plot_flow_state_triptych,
    )

    has_dynamic_fields = any(
        getattr(payload, attr_name) is not None
        for attr_name in (
            "watertable_elevation_m",
            "watertable_depth_m",
            "seepage_areas_m_per_day",
            "outflow_drain_m_per_day",
            "accumulation_flux_m_per_day",
        )
    )

    if options.flow.is_enabled("state_triptych", default=True):
        plot_flow_state_triptych(
            payload=payload,
            options=options,
            save_path=output_dir / "flow_state_triptych.png",
        )

    if options.flow.is_enabled("watertable_map", default=True):
        for field_name, spec in FLOW_SPATIAL_FIELD_SPECS.items():
            if field_name == "top_elevation":
                continue
            values = getattr(payload, spec.attr_name)
            if values is None:
                continue
            plot_flow_spatial_field(
                payload=payload,
                field_name=field_name,
                options=options,
                save_path=output_dir / f"{field_name}.png",
            )

    return has_dynamic_fields
