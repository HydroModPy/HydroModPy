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

import matplotlib.pyplot as plt

from hydromodpy.display.options import DisplayOptions


def ensure_dir(path: Path) -> Path:
    """Ensure an output directory exists and return the same path.

    This helper is intentionally tiny, but it avoids repeating
    ``mkdir(parents=True, exist_ok=True)`` across the package.
    Returning the path keeps call sites concise when building save targets.
    """

    path.mkdir(parents=True, exist_ok=True)
    return path


def _resolve_custom_output_root(workspace, options: DisplayOptions | None) -> Path | None:
    """Resolve an optional custom display output root from runtime options."""

    if options is None or options.output_dir is None:
        return None

    root = Path(options.output_dir)
    if root.is_absolute():
        return root
    return workspace.catch_folder / root


def resolve_model_figure_dir(
    workspace,
    model_name: str,
    *,
    options: DisplayOptions | None = None,
) -> Path:
    """Build the standard figure output directory for one model run.

    The returned path points to the model-specific post-processing tree under
    ``workspace.simulations_folder`` by default.

    When ``options.output_dir`` is configured, the destination becomes:
    ``<output_dir>/<model_name>/``. Relative ``output_dir`` values are resolved
    from ``workspace.catch_folder``.
    """

    custom_root = _resolve_custom_output_root(workspace, options)
    if custom_root is not None:
        return custom_root / model_name
    return workspace.simulations_folder / model_name / "_postprocess" / "_figures"


def resolve_shared_figure_dir(
    workspace,
    *,
    options: DisplayOptions | None = None,
) -> Path:
    """Build the shared figure directory used for workspace-level outputs.

    This is useful for figures that summarize several models or that belong to
    the workspace as a whole rather than to a single simulation subfolder.
    """

    custom_root = _resolve_custom_output_root(workspace, options)
    if custom_root is not None:
        return custom_root / "_shared"
    return workspace.simulations_folder / "_figures"


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
        plt.show()
    else:
        # Always close in non-interactive mode to avoid leaking Matplotlib state.
        plt.close(fig)
