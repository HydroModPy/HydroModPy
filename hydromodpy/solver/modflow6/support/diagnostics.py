"""Diagnostic plotting helpers for MODFLOW 6 runtime support exports."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Protocol

import numpy as np

from hydromodpy.core.io import filesystem
from hydromodpy.physics.flow.boundary_condition_registry import (
    active_side_dirichlet_boundary_ids,
)
from hydromodpy.solver.modflow6.builders.boundary_conditions import (
    boundary_attr,
    boundary_conditions_mapping,
    boundary_support_cell_ids,
    is_bc_active,
    ocean_chd_support_mask,
    resolve_ocean_boundary_series,
    resolve_stream_boundary_series,
    stream_chd_support_mask,
)
from hydromodpy.solver.modflow6.builders.wells import resolve_well_disv_cell
from hydromodpy.solver.modflow_common.options import ModflowPostprocessOptions
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh

_BOUNDARY_FAMILY_PREFIX = "boundary:"


class RuntimeSupportOverviewModel(Protocol):
    """Minimal MODFLOW-6 contract consumed by runtime support overview exports."""

    flow: object | None
    save_file: str
    solver_mesh: SolverMesh
    grid_ctx: object | None


def mesh_edge_segments(cell_mesh: PlanarCellMesh) -> np.ndarray:
    """Return every mesh edge as an ``(m, 2, 2)`` array of XY end points."""
    nodes = cell_mesh.geometry.edge_nodes
    return _node_segments(cell_mesh, nodes[:, 0], nodes[:, 1])


def family_edge_segments(cell_mesh: PlanarCellMesh, family: str) -> np.ndarray:
    """Return the faces of one face family as an ``(m, 2, 2)`` array of XY end points."""
    table = cell_mesh.face_families
    rows = cell_mesh.face_rows(family)
    if table is None or not rows.any():
        return np.empty((0, 2, 2), dtype=float)
    return _node_segments(cell_mesh, table.node_a[rows], table.node_b[rows])


def _node_segments(cell_mesh: PlanarCellMesh, node_a: np.ndarray, node_b: np.ndarray) -> np.ndarray:
    vertices = np.asarray(cell_mesh.mesh.vertices, dtype=float)
    return np.stack([vertices[node_a], vertices[node_b]], axis=1)


def cell_outlines(cell_mesh: PlanarCellMesh, cell_ids: np.ndarray) -> list[np.ndarray]:
    """Return the XY outline of each distinct cell of ``cell_ids``."""
    ids = np.unique(np.asarray(cell_ids, dtype=np.int64).reshape(-1))
    ids = ids[(ids >= 0) & (ids < cell_mesh.n_cells)]
    vertices = np.asarray(cell_mesh.mesh.vertices, dtype=float)
    rows = cell_mesh.geometry.padded_connectivity[ids]
    return [vertices[row[row >= 0]] for row in rows]


def build_support_overlay_specs(
    model: RuntimeSupportOverviewModel,
) -> list[tuple[str, np.ndarray, str]]:
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
    boundary_conditions = boundary_conditions_mapping(model)
    for bc_id in active_side_dirichlet_boundary_ids(model.flow):
        boundary = boundary_conditions.get(bc_id)
        if boundary is None:
            continue
        cell_ids = np.asarray(
            boundary_support_cell_ids(model, boundary=boundary, bc_id=bc_id),
            dtype=int,
        ).reshape(-1)
        if cell_ids.size == 0:
            continue
        support_label = boundary_attr(boundary, "support_label", None)
        label = str(bc_id)
        if support_label is not None:
            label = f"{bc_id} [{str(support_label)}]"
        overlays.append((label, cell_ids, color_by_bc[bc_id]))

    if is_bc_active(model, "stream"):
        stream_series = resolve_stream_boundary_series(model)
        stream_mask = stream_chd_support_mask(model, stream_series)
        stream_cell_ids = np.flatnonzero(np.asarray(stream_mask, dtype=bool)).astype(
            int, copy=False
        )
        if stream_cell_ids.size > 0:
            stream_boundary = boundary_conditions.get("stream")
            support_label = (
                None
                if stream_boundary is None
                else boundary_attr(
                    stream_boundary,
                    "support_label",
                    None,
                )
            )
            label = "stream"
            if support_label is not None:
                label = f"stream [{str(support_label)}]"
            overlays.append((label, stream_cell_ids, color_by_bc["stream"]))

    if is_bc_active(model, "ocean"):
        ocean_series = resolve_ocean_boundary_series(model)
        ocean_mask = ocean_chd_support_mask(model, ocean_series)
        ocean_cell_ids = np.flatnonzero(np.asarray(ocean_mask, dtype=bool)).astype(int, copy=False)
        if ocean_cell_ids.size > 0:
            overlays.append(("ocean", ocean_cell_ids, color_by_bc["ocean"]))

    return overlays


def build_well_overlay_specs(model: RuntimeSupportOverviewModel) -> list[dict[str, object]]:
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

    centroids = model.solver_mesh.cell_centroids()
    items: list[dict[str, object]] = []
    for well_id, well_cfg in wells.items():
        try:
            _, cell_id = resolve_well_disv_cell(model, well_id=str(well_id), well_cfg=well_cfg)
        except Exception:
            continue
        items.append(
            {
                "id": str(well_id),
                "cell_id": int(cell_id),
                "x_m": float(centroids[int(cell_id), 0]),
                "y_m": float(centroids[int(cell_id), 1]),
            }
        )
    return items


def export_runtime_support_overview(
    model: RuntimeSupportOverviewModel,
    *,
    options: ModflowPostprocessOptions,
) -> None:
    """Write one diagnostic figure showing runtime gmsh supports used by the solver."""
    if not getattr(options, "native_mesh_png", False):
        return
    cell_mesh = model.solver_mesh.cell_mesh

    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection, PolyCollection
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    figure_dir = os.path.join(model.save_file, "_figures", "native_mesh")
    filesystem.create_folder(figure_dir)

    all_segments = mesh_edge_segments(cell_mesh)
    if not all_segments.size:
        return

    node_x_m = np.asarray(cell_mesh.mesh.vertices[:, 0], dtype=float)
    node_y_m = np.asarray(cell_mesh.mesh.vertices[:, 1], dtype=float)
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
    for label, cell_ids, color in build_support_overlay_specs(model):
        polygons = cell_outlines(cell_mesh, cell_ids)
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

    river_segments = family_edge_segments(cell_mesh, "rivers")
    if river_segments.size:
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

    well_items = build_well_overlay_specs(model)
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
    table = cell_mesh.face_families
    label_values = (
        []
        if table is None
        else sorted(
            name.removeprefix(_BOUNDARY_FAMILY_PREFIX)
            for name in table.names
            if name.startswith(_BOUNDARY_FAMILY_PREFIX) and cell_mesh.face_rows(name).any()
        )
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
        segments = family_edge_segments(cell_mesh, f"{_BOUNDARY_FAMILY_PREFIX}{label}")
        if not segments.size:
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
        x_mid = float(segments[:, :, 0].mean())
        y_mid = float(segments[:, :, 1].mean())
        ax_labels.text(
            x_mid,
            y_mid,
            label,
            fontsize=7.5,
            color=color,
            ha="center",
            va="center",
            bbox={"facecolor": "white", "edgecolor": color, "alpha": 0.75, "pad": 1.5},
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
    fig.savefig(
        os.path.join(figure_dir, "flow_support_overview.png"),
        bbox_inches="tight",
    )
    plt.close(fig)


__all__ = [
    "RuntimeSupportOverviewModel",
    "build_support_overlay_specs",
    "build_well_overlay_specs",
    "cell_outlines",
    "export_runtime_support_overview",
    "family_edge_segments",
    "mesh_edge_segments",
]
