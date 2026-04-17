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

from numbers import Integral
from pathlib import Path
from typing import TYPE_CHECKING

import matplotlib.pyplot as plt
import pandas as pd

from hydromodpy.analysis.display.options import DisplayOptions

if TYPE_CHECKING:
    from hydromodpy.data.contracts.load_result import LoadResult


def make_figure(*, nrows=1, ncols=1, figsize=None, dpi=300, **kw):
    """Create a figure, preferring ultraplot when available.

    Falls back to plain Matplotlib so display code works even when the
    optional ``ultraplot`` dependency is not installed.
    """
    try:
        import ultraplot as uplt

        fig, axs = uplt.subplots(
            nrows=nrows, ncols=ncols, figsize=figsize, dpi=dpi, **kw
        )
    except ImportError:
        matplotlib_kw = dict(kw)
        adjust_kw: dict[str, float] = {}
        for key in ("hspace", "wspace"):
            value = matplotlib_kw.pop(key, None)
            if value is not None:
                adjust_kw[key] = float(value)
        for key in ("sharex", "sharey"):
            value = matplotlib_kw.get(key)
            if isinstance(value, Integral) and not isinstance(value, bool):
                matplotlib_kw[key] = bool(value)
        fig, axs = plt.subplots(
            nrows,
            ncols,
            figsize=figsize,
            dpi=dpi,
            **matplotlib_kw,
        )
        if adjust_kw:
            fig.subplots_adjust(**adjust_kw)
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


def add_figure_legend(fig, *legend_args, fallback_loc: str | None = "bottom", **legend_kwargs):
    """Add a figure-level legend with a fallback for ``ultraplot`` panel locs.

    Matplotlib accepts locations such as ``"lower center"`` for figure-level
    legends. ``ultraplot`` routes figure legends through its panel system and
    rejects those values, expecting panel-oriented locations such as
    ``"bottom"``. This helper preserves the Matplotlib-style call and retries
    with a panel location only when that specific incompatibility is raised.
    """
    try:
        return fig.legend(*legend_args, **legend_kwargs)
    except KeyError as exc:
        requested_loc = legend_kwargs.get("loc")
        if fallback_loc is None or requested_loc is None:
            raise
        if "Invalid panel location" not in str(exc):
            raise

    retry_kwargs = dict(legend_kwargs)
    retry_kwargs["loc"] = fallback_loc
    return fig.legend(*legend_args, **retry_kwargs)


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


def resolve_artifact_figure_dir(workspace, artifact_id: str) -> Path:
    """Build the standard figure output directory for one solver artifact.

    The returned path points to the run-specific post-processing tree under
    ``workspace.simulations_folder``. Plotting functions use this location as
    their default destination for PNG exports tied to one run execution.
    """

    return workspace.simulations_folder / artifact_id / "_postprocess" / "_figures"


def resolve_model_figure_dir(workspace, run_id: str) -> Path:
    """Backward-compatible alias for :func:`resolve_artifact_figure_dir`."""
    return resolve_artifact_figure_dir(workspace, run_id)


def resolve_shared_figure_dir(workspace) -> Path:
    """Build the shared figure directory used for workspace-level outputs.

    This is useful for figures that summarize several models or that belong to
    the workspace as a whole rather than to a single simulation subfolder.
    """

    return workspace.simulations_folder / "_figures"


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
