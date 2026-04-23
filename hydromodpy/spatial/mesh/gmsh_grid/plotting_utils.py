"""Gather small plotting helpers shared by the Gmsh reference scripts.

This file centralizes Matplotlib utilities that are reused across examples and
comparison cases: backend switching, axis formatting, blocking display, and
colorbar formatting. It exists to keep plotting policies consistent without
mixing them into the mesh and discretization core.
"""

from __future__ import annotations

import matplotlib
import numpy as np
from matplotlib import pyplot as plt
from matplotlib.ticker import ScalarFormatter

from hydromodpy.spatial.mesh.plot_window_utils import maximize_figure_windows


def disable_axis_offset(ax) -> None:
    """Disable scientific offset notation on x/y axes."""
    formatter = ScalarFormatter(useMathText=False)
    formatter.set_scientific(False)
    formatter.set_useOffset(False)
    ax.xaxis.set_major_formatter(formatter)
    ax.yaxis.set_major_formatter(formatter)


def maybe_scientific_colorbar(cbar, values) -> None:
    """Switch colorbar ticks to scientific notation when the value range demands it."""
    arr = np.asarray(values, dtype=float)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return
    finite_abs = np.abs(finite)
    vmax = float(np.nanmax(finite_abs))
    nonzero = finite_abs[finite_abs > 0.0]
    vmin_nonzero = float(np.nanmin(nonzero)) if nonzero.size else vmax
    use_sci = (vmax >= 1.0e4) or (vmin_nonzero > 0.0 and vmin_nonzero <= 1.0e-3)
    if not use_sci:
        return
    formatter = ScalarFormatter(useMathText=True)
    formatter.set_powerlimits((-2, 2))
    cbar.formatter = formatter
    cbar.update_ticks()


def ensure_interactive_backend_for_show() -> None:
    """Switch to a GUI backend when running from inline/Agg contexts."""
    backend = str(matplotlib.get_backend()).strip().lower()
    if ("inline" not in backend) and ("agg" not in backend):
        return
    for candidate in ("TkAgg", "QtAgg"):
        try:
            plt.switch_backend(candidate)
            return
        except Exception:
            continue


def show_figures_blocking(*figures) -> None:
    """Show one or many Matplotlib figures in blocking mode."""
    ensure_interactive_backend_for_show()
    plt.ioff()
    visible = [fig for fig in figures if fig is not None]
    for fig in figures:
        if fig is None:
            continue
        manager = getattr(fig.canvas, "manager", None)
        if manager is not None:
            try:
                manager.show()
            except Exception:
                pass
        try:
            fig.show()
        except Exception:
            pass
    maximize_figure_windows(*visible)
    plt.show(block=True)
