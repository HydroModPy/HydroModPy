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
from hydromodpy.physics.flow.boundary_condition_registry import (
    active_side_dirichlet_boundary_ids,
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
    indices = np.asarray(edge_indices, dtype=int).reshape(-1)
    if indices.size == 0:
        return []
    node_x_m = np.asarray(getattr(support, "node_x_m", ()), dtype=float).reshape(-1)
    node_y_m = np.asarray(getattr(support, "node_y_m", ()), dtype=float).reshape(-1)
    edge_node_a = np.asarray(getattr(support, "edge_node_a_index", ()), dtype=int).reshape(-1)
    edge_node_b = np.asarray(getattr(support, "edge_node_b_index", ()), dtype=int).reshape(-1)
    segments: list[np.ndarray] = []
    for edge_index in indices.tolist():
        if edge_index < 0 or edge_index >= edge_node_a.size or edge_index >= edge_node_b.size:
            continue
        node_a = int(edge_node_a[edge_index])
        node_b = int(edge_node_b[edge_index])
        segments.append(
            np.asarray(
                [
                    [float(node_x_m[node_a]), float(node_y_m[node_a])],
                    [float(node_x_m[node_b]), float(node_y_m[node_b])],
                ],
                dtype=float,
            )
        )
    return segments


def support_cell_polygons(model, support: object, cell_ids: np.ndarray) -> list[np.ndarray]:
    """Return XY polygons for one sequence of runtime support cell ids."""
    indices = np.asarray(cell_ids, dtype=int).reshape(-1)
    if indices.size == 0:
        return []
    node_x_m = np.asarray(getattr(support, "node_x_m", ()), dtype=float).reshape(-1)
    node_y_m = np.asarray(getattr(support, "node_y_m", ()), dtype=float).reshape(-1)
    cell_node_indices = tuple(getattr(support, "cell_node_indices", ()) or ())
    polygons: list[np.ndarray] = []
    for cell_id in np.unique(indices).tolist():
        if cell_id < 0 or cell_id >= len(cell_node_indices):
            continue
        node_indices = np.asarray(cell_node_indices[int(cell_id)], dtype=int).reshape(-1)
        if node_indices.size < 3:
            continue
        polygons.append(
            np.column_stack(
                [
                    node_x_m[node_indices],
                    node_y_m[node_indices],
                ]
            ).astype(float, copy=False)
        )
    return polygons


def support_overlay_specs(model) -> list[tuple[str, np.ndarray, str]]:
    """Return active runtime support selections to visualize on one overview figure."""
    if model.flow is None:
        return []

    overlays: list[tuple[str, np.ndarray, str]] = []
    color_by_bc = {
        "west_side": "#d62728",
        "east_side": "#1f77b4",
        "north_side": "#ff7f0e",
        "south_side": "#9467bd",
        "stream": "#17becf",
        "ocean": "#2ca02c",
    }
    boundary_conditions = model._boundary_conditions_mapping()
    for bc_id in active_side_dirichlet_boundary_ids(model.flow):
        if not model._is_bc_active(bc_id):
            continue
        boundary = boundary_conditions.get(bc_id)
        if boundary is None:
            continue
        cell_ids = np.asarray(
            model._boundary_support_cell_ids(boundary=boundary, bc_id=bc_id),
            dtype=int,
        ).reshape(-1)
        if cell_ids.size == 0:
            continue
        support_label = model._boundary_attr(boundary, "support_label", None)
        label = str(bc_id)
        if support_label is not None:
            label = f"{bc_id} [{str(support_label)}]"
        overlays.append((label, cell_ids, color_by_bc[bc_id]))

    if model._is_bc_active("stream"):
        stream_series = model._resolve_stream_boundary_series()
        stream_mask = model._stream_chd_support_mask(stream_series)
        stream_cell_ids = np.flatnonzero(np.asarray(stream_mask, dtype=bool)).astype(
            int, copy=False
        )
        if stream_cell_ids.size > 0:
            stream_boundary = boundary_conditions.get("stream")
            support_label = (
                None
                if stream_boundary is None
                else model._boundary_attr(
                    stream_boundary,
                    "support_label",
                    None,
                )
            )
            label = "stream"
            if support_label is not None:
                label = f"stream [{str(support_label)}]"
            overlays.append((label, stream_cell_ids, color_by_bc["stream"]))

    if model._is_bc_active("ocean"):
        ocean_series = model._resolve_ocean_boundary_series()
        ocean_mask = model._ocean_chd_support_mask(ocean_series)
        ocean_cell_ids = np.flatnonzero(np.asarray(ocean_mask, dtype=bool)).astype(int, copy=False)
        if ocean_cell_ids.size > 0:
            overlays.append(("ocean", ocean_cell_ids, color_by_bc["ocean"]))

    return overlays


def well_overlay_specs(model) -> list[dict[str, object]]:
    """Return resolved well locations suitable for diagnostic plotting."""
    if model.flow is None:
        return []
    active = getattr(model.flow, "active_sinks_sources", [])
    if "wells" not in active:
        return []

    sinks_sources = getattr(model.flow, "sinks_sources", {})
    if not isinstance(sinks_sources, Mapping):
        return []
    wells = sinks_sources.get("wells", {})
    if not isinstance(wells, Mapping):
        return []

    support = getattr(model, "runtime_mesh_support", None)
    grid = None if model.grid_ctx is None else model.grid_ctx.grid
    items: list[dict[str, object]] = []
    for well_id, well_cfg in wells.items():
        try:
            _, cell_id = model._resolve_well_disv_cell(
                well_id=str(well_id),
                well_cfg=well_cfg,
                grid=grid,
            )
        except Exception:
            continue

        if support is not None and 0 <= int(cell_id) < int(getattr(support, "n_cells", 0)):
            x_m = float(
                np.asarray(support.cell_centroid_x_m, dtype=float).reshape(-1)[int(cell_id)]
            )
            y_m = float(
                np.asarray(support.cell_centroid_y_m, dtype=float).reshape(-1)[int(cell_id)]
            )
        else:
            continue
        items.append(
            {
                "id": str(well_id),
                "cell_id": int(cell_id),
                "x_m": x_m,
                "y_m": y_m,
            }
        )
    return items


def export_runtime_support_overview(model, *, options: ModflowPostprocessOptions) -> None:
    """Write one diagnostic figure showing runtime gmsh supports used by the solver."""
    if not getattr(options, "native_mesh_png", False):
        return
    support = getattr(model, "runtime_mesh_support", None)
    if support is None:
        return

    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection, PolyCollection
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    figure_dir = os.path.join(model.save_file, "_figures", "native_mesh")
    create_folder(figure_dir)

    all_edge_indices = np.arange(
        np.asarray(getattr(support, "edge_ids", ()), dtype=int).size, dtype=int
    )
    all_segments = support_edge_segments(model, support, all_edge_indices)
    if not all_segments:
        return

    node_x_m = np.asarray(getattr(support, "node_x_m", ()), dtype=float).reshape(-1)
    node_y_m = np.asarray(getattr(support, "node_y_m", ()), dtype=float).reshape(-1)
    fig, axs = plt.subplots(1, 2, figsize=(14.8, 6.4), dpi=220)
    ax_active, ax_labels = axs

    for ax in (ax_active, ax_labels):
        ax.add_collection(LineCollection(all_segments, colors="0.80", linewidths=0.8, zorder=1))
        ax.set_aspect("equal")
        ax.set_xlim(float(np.min(node_x_m)), float(np.max(node_x_m)))
        ax.set_ylim(float(np.min(node_y_m)), float(np.max(node_y_m)))
        ax.set_xlabel("x (m)", fontsize=9)
        ax.set_ylabel("y (m)", fontsize=9)
        ax.ticklabel_format(style="plain", axis="both", useOffset=False)
        ax.tick_params(axis="both", labelsize=8, length=3.0, pad=2.0)

    active_handles: list[object] = []
    for label, cell_ids, color in support_overlay_specs(model):
        polygons = support_cell_polygons(model, support, cell_ids)
        if not polygons:
            continue
        ax_active.add_collection(
            PolyCollection(
                polygons,
                facecolors=color,
                edgecolors=color,
                linewidths=1.4,
                alpha=0.22,
                zorder=2,
            )
        )
        active_handles.append(Patch(facecolor=color, edgecolor=color, alpha=0.22, label=label))

    river_indices = np.asarray(support.river_edge_indices(), dtype=int).reshape(-1)
    river_segments = support_edge_segments(model, support, river_indices)
    if river_segments:
        river_collection = LineCollection(
            river_segments,
            colors="#17becf",
            linewidths=2.0,
            alpha=0.95,
            zorder=3,
        )
        ax_active.add_collection(river_collection)
        ax_labels.add_collection(
            LineCollection(
                river_segments,
                colors="#17becf",
                linewidths=2.0,
                alpha=0.95,
                zorder=3,
            )
        )
        active_handles.append(Line2D([0], [0], color="#17becf", lw=2.0, label="river edges"))

    well_items = well_overlay_specs(model)
    if well_items:
        ax_active.scatter(
            [float(item["x_m"]) for item in well_items],
            [float(item["y_m"]) for item in well_items],
            marker="x",
            s=55.0,
            linewidths=1.5,
            color="black",
            zorder=4,
        )
        for item in well_items:
            ax_active.text(
                float(item["x_m"]),
                float(item["y_m"]),
                str(item["id"]),
                fontsize=7.5,
                color="black",
                ha="left",
                va="bottom",
                zorder=5,
            )
        active_handles.append(
            Line2D([0], [0], marker="x", color="black", linestyle="None", label="wells")
        )

    label_handles: list[object] = []
    label_values = sorted(
        {
            str(value)
            for value in getattr(support, "boundary_labels_by_edge_id", {}).values()
            if str(value).strip() != ""
        }
    )
    palette = (
        "#d62728",
        "#1f77b4",
        "#ff7f0e",
        "#9467bd",
        "#8c564b",
        "#e377c2",
        "#7f7f7f",
        "#bcbd22",
    )
    for index, label in enumerate(label_values):
        edge_indices = np.asarray(support.edge_indices_for_label(label), dtype=int).reshape(-1)
        segments = support_edge_segments(model, support, edge_indices)
        if not segments:
            continue
        color = palette[index % len(palette)]
        ax_labels.add_collection(
            LineCollection(
                segments,
                colors=color,
                linewidths=2.4,
                alpha=0.95,
                zorder=2,
            )
        )
        x_mid = float(
            np.mean(np.asarray(support.edge_midpoint_x_m, dtype=float).reshape(-1)[edge_indices])
        )
        y_mid = float(
            np.mean(np.asarray(support.edge_midpoint_y_m, dtype=float).reshape(-1)[edge_indices])
        )
        ax_labels.text(
            x_mid,
            y_mid,
            label,
            fontsize=7.5,
            color=color,
            ha="center",
            va="center",
            bbox={
                "facecolor": "white",
                "edgecolor": color,
                "alpha": 0.75,
                "pad": 1.5,
            },
            zorder=4,
        )
        label_handles.append(Line2D([0], [0], color=color, lw=2.4, label=label))

    ax_active.set_title("Active supports", fontsize=10.5, loc="left", pad=5.0)
    ax_labels.set_title("Support labels", fontsize=10.5, loc="left", pad=5.0)
    if active_handles:
        ax_active.legend(
            handles=active_handles,
            loc="upper center",
            bbox_to_anchor=(0.5, -0.12),
            ncol=min(3, len(active_handles)),
            fontsize=7.5,
            frameon=True,
            framealpha=0.92,
        )
    if label_handles:
        ax_labels.legend(
            handles=label_handles,
            loc="upper center",
            bbox_to_anchor=(0.5, -0.12),
            ncol=min(3, len(label_handles)),
            fontsize=7.5,
            frameon=True,
            framealpha=0.92,
        )
    else:
        ax_labels.text(
            0.5,
            0.5,
            "No labeled runtime supports",
            transform=ax_labels.transAxes,
            ha="center",
            va="center",
            fontsize=9,
            color="0.35",
        )

    fig.suptitle("Runtime support overview", fontsize=11.5, y=0.96)
    fig.subplots_adjust(left=0.055, right=0.985, bottom=0.2, top=0.88, wspace=0.12)
    output_path = os.path.join(figure_dir, "flow_support_overview.png")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fig.savefig(windows_extended_length_path(output_path), bbox_inches="tight")
    plt.close(fig)
