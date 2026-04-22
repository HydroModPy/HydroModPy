"""Small plotting helpers shared by geographic case launchers.

These helpers keep visual-review behavior consistent across cases:
- force one interactive backend when needed,
- maximize windows when possible,
- show figures in blocking mode.
"""

from __future__ import annotations

import matplotlib
from matplotlib import pyplot as plt
from matplotlib import rcsetup

from hydromodpy.solver.utils.mesh.plot_window_utils import maximize_figure_windows


def _normalized_backend_name() -> str:
    """Return normalized Matplotlib backend name (lowercase, without module://)."""
    backend = str(matplotlib.get_backend()).strip().lower()
    if backend.startswith("module://"):
        backend = backend[len("module://") :]
    return backend


def _is_non_interactive_backend(backend: str) -> bool:
    """Return True when backend is known to not support GUI figure windows."""
    non_interactive = {str(name).strip().lower() for name in rcsetup.non_interactive_bk}
    return ("inline" in backend) or (backend in non_interactive)


def _figures_use_non_gui_canvas(figures) -> bool:
    """Detect figures created on non-GUI canvases or base managers."""
    for fig in figures:
        canvas = getattr(fig, "canvas", None)
        if canvas is None:
            continue
        canvas_module = str(type(canvas).__module__).strip().lower()
        if (".backend_agg" in canvas_module) or canvas_module.endswith("backend_agg"):
            return True

        manager = getattr(canvas, "manager", None)
        if manager is None:
            continue
        manager_name = str(type(manager).__name__).strip()
        manager_module = str(type(manager).__module__).strip().lower()
        if manager_name == "FigureManagerBase" and "backend_bases" in manager_module:
            return True
    return False


def ensure_interactive_backend_for_show() -> bool:
    """Switch to one GUI backend when running from inline/Agg contexts."""
    backend = _normalized_backend_name()
    if not _is_non_interactive_backend(backend):
        return False
    for candidate in ("TkAgg", "QtAgg"):
        try:
            plt.switch_backend(candidate)
            return True
        except Exception:
            continue
    return False


def show_figures_blocking(*figures) -> None:
    """Show one or many figures in blocking mode and maximize window size."""
    visible = [fig for fig in figures if fig is not None]
    if not visible:
        return
    plt.ioff()

    backend = _normalized_backend_name()
    if _is_non_interactive_backend(backend):
        return
    if _figures_use_non_gui_canvas(visible):
        return

    for fig in visible:
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
    try:
        plt.pause(0.05)
    except Exception:
        pass
    try:
        plt.show(block=True)
    except Exception:
        pass
