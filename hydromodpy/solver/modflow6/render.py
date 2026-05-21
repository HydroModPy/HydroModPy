"""MODFLOW 6 matplotlib overlays for native mesh PNG and runtime support overview.

Note: the runtime-support overview helpers in this module are retained for
backward compatibility with the original modflow6.py surface. The canonical
overlay rendering path used by post-processing lives in ``diagnostics.py``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

import numpy as np

from hydromodpy.core.io.filesystem import create_folder
from hydromodpy.core.logging import get_logger
from hydromodpy.solver.modflow6.diagnostics import (
    build_support_overlay_specs,
    build_well_overlay_specs,
)
from hydromodpy.solver.modflow6.diagnostics import (
    export_runtime_support_overview as _export_runtime_support_overview,
)
from hydromodpy.solver.modflow6.diagnostics import (
    support_cell_polygons as _support_cell_polygons,
)
from hydromodpy.solver.modflow6.diagnostics import (
    support_edge_segments as _support_edge_segments,
)
from hydromodpy.solver.modflow_common.options import ModflowPostprocessOptions

logger = get_logger(__name__)


def windows_extended_length_path(path: str) -> str:
    """Return a Windows long-path spelling while keeping normal paths unchanged."""
    if os.name != "nt":
        return path
    normalized = os.path.normpath(os.path.abspath(path))
    if normalized.startswith("\\\\?\\"):
        return normalized
    if normalized.startswith("\\\\"):
        return "\\\\?\\UNC\\" + normalized.lstrip("\\")
    return "\\\\?\\" + normalized


def render_native_mesh_png(
    *,
    model,
    cell_series: Mapping[str, np.ndarray],
    times_array: np.ndarray,
    prefix: str,
) -> None:
    """Write PNG figures for native mesh cell series."""
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    from matplotlib.ticker import ScalarFormatter
    from mpl_toolkits.axes_grid1 import make_axes_locatable

    from hydromodpy.spatial.mesh.plotting import plot_cell_values

    figure_dir = os.path.join(model.save_file, "_figures", "native_mesh")
    create_folder(figure_dir)
    field_styles = {
        "watertable_elevation": ("Hydraulic head", "Head [m]", "viridis"),
        "watertable_depth": ("Water-table depth", "Top - h [m]", "Blues"),
        "seepage_areas": ("Seepage areas", "Seepage [m/day]", "Reds"),
        "outflow_drain": ("Drain discharge", "Discharge [m/day]", "magma"),
        "accumulation_flux": (
            "Accumulation flux",
            "Accumulated flow [m/day]",
            "plasma",
        ),
        "concentration_seepage": (
            "Seepage concentration",
            "Concentration [-]",
            "viridis",
        ),
        "mass_seepage": ("Seepage mass", "Mass [-]", "cividis"),
        "mass_accumulated": (
            "Accumulated mass",
            "Accumulated mass [-]",
            "inferno",
        ),
    }

    for name, values in cell_series.items():
        for tidx, time_value in enumerate(times_array.tolist()):
            flat = np.asarray(values[tidx], dtype=float).reshape(-1).copy()
            flat[~np.isfinite(flat)] = np.nan
            flat[flat <= -9999.0] = np.nan
            finite = flat[np.isfinite(flat)]
            if finite.size == 0:
                continue

            vmin = float(np.nanmin(finite))
            vmax = float(np.nanmax(finite))
            if np.isclose(vmin, vmax):
                vmax = vmin + 1.0

            field_title, colorbar_label, cmap = field_styles.get(
                str(name),
                (
                    str(name).replace("_", " ").title(),
                    str(name).replace("_", " "),
                    "viridis",
                ),
            )
            fig, ax = plt.subplots(figsize=(7.2, 6.0), dpi=220)
            mappable = plot_cell_values(
                ax,
                model.solver_mesh.planar_mesh,
                flat,
                cmap=cmap,
                show_mesh=True,
                vmin=vmin,
                vmax=vmax,
            )
            ax.set_title(
                f"{field_title} | t={float(time_value):.12g} s",
                fontsize=10.5,
                loc="left",
                pad=5.0,
            )
            ax.set_xlabel("x (m)", fontsize=9)
            ax.set_ylabel("y (m)", fontsize=9)
            ax.ticklabel_format(style="plain", axis="both", useOffset=False)
            ax.tick_params(axis="both", labelsize=8, length=3.0, pad=2.0)

            divider = make_axes_locatable(ax)
            cax = divider.append_axes("right", size="3.8%", pad=0.06)
            cbar = fig.colorbar(mappable, cax=cax)
            cbar.set_label(colorbar_label, fontsize=8.5, labelpad=6.0)
            cbar.ax.tick_params(labelsize=7.5, length=2.5, pad=1.5)
            formatter = ScalarFormatter(useMathText=True)
            formatter.set_powerlimits((-2, 3))
            cbar.formatter = formatter
            cbar.update_ticks()

            fig.subplots_adjust(left=0.08, right=0.94, bottom=0.11, top=0.9)
            output_path = os.path.join(
                figure_dir,
                f"{prefix}_{name}_t({int(tidx)}).png",
            )
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            fig.savefig(
                windows_extended_length_path(output_path),
                bbox_inches="tight",
            )
            plt.close(fig)


def support_edge_segments(model, support: object, edge_indices: np.ndarray) -> list[np.ndarray]:
    """Return XY segments for one sequence of runtime support edge indices."""
    del model
    return _support_edge_segments(support, edge_indices)


def support_cell_polygons(model, support: object, cell_ids: np.ndarray) -> list[np.ndarray]:
    """Return XY polygons for one sequence of runtime support cell ids."""
    del model
    return _support_cell_polygons(support, cell_ids)


def support_overlay_specs(model) -> list[tuple[str, np.ndarray, str]]:
    """Return active runtime support selections to visualize on one overview figure."""
    return build_support_overlay_specs(model)


def well_overlay_specs(model) -> list[dict[str, object]]:
    """Return resolved well locations suitable for diagnostic plotting."""
    return build_well_overlay_specs(model)


def export_runtime_support_overview(model, *, options: ModflowPostprocessOptions) -> None:
    """Write one diagnostic figure showing runtime gmsh supports used by the solver."""
    _export_runtime_support_overview(model, options=options)
