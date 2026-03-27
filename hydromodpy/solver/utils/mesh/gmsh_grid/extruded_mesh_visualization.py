"""Lightweight 3D visualization helpers for extruded mesh values.

This module stays intentionally simple: it produces 2D layer maps and vertical
profiles from `ExtrudedPrismMeshWithValues`, without introducing any 3D
interactive viewer. That keeps the plotting layer separate from mesh storage
and discretization while still providing practical QA figures.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import matplotlib

matplotlib.use("Agg", force=True)
from matplotlib import pyplot as plt
import numpy as np

from hydromodpy.solver.utils.mesh.gmsh_grid.extruded_mesh_values import (
    ExtrudedVerticalProfile,
    ExtrudedPrismMeshWithValues,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.plotting_utils import (
    disable_axis_offset,
    maybe_scientific_colorbar,
)

_PROFILE_COLORS = ("#dc2626", "#2563eb", "#16a34a", "#d97706", "#7c3aed")


@dataclass(frozen=True)
class SourceCellMarkerSpec:
    """Typed marker description for one selected planar source cell."""

    label: str
    color: str
    source_cell_index: int
    xy: tuple[float, float]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "SourceCellMarkerSpec":
        return cls(
            label=str(payload["label"]),
            color=str(payload["color"]),
            source_cell_index=int(payload["source_cell_index"]),
            xy=(float(payload["xy"][0]), float(payload["xy"][1])),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "label": str(self.label),
            "color": str(self.color),
            "source_cell_index": int(self.source_cell_index),
            "xy": [float(self.xy[0]), float(self.xy[1])],
        }


@dataclass(frozen=True)
class VisualizationProfileSummary:
    """Compact JSON-friendly profile summary used by visualization sidecars."""

    label: str
    source_cell_index: int
    xy: tuple[float, float]
    profile: ExtrudedVerticalProfile

    def to_mapping(self) -> dict[str, Any]:
        payload = self.profile.to_mapping()
        payload.pop("layer_indices", None)
        payload["label"] = str(self.label)
        payload["source_cell_index"] = int(self.source_cell_index)
        payload["xy"] = [
            _round_float(float(self.xy[0]), ndigits=6),
            _round_float(float(self.xy[1]), ndigits=6),
        ]
        payload["values"] = [
            _round_float(v) for v in np.asarray(payload["values"], dtype=float)
        ]
        if "depths" in payload:
            payload["depths"] = [
                _round_float(v) for v in np.asarray(payload["depths"], dtype=float)
            ]
        return payload


@dataclass(frozen=True)
class ExtrudedVisualizationSummary:
    """Typed summary of the selected slices used in QA figures."""

    n_layers: int
    n_cells_2d: int
    n_cells_3d: int
    selected_layers: tuple[int, ...]
    selected_layer_mean_values: tuple[float, ...]
    selected_layer_mean_depths: tuple[float, ...]
    selected_profiles: tuple[VisualizationProfileSummary, ...]

    def to_mapping(self) -> dict[str, Any]:
        return {
            "n_layers": int(self.n_layers),
            "n_cells_2d": int(self.n_cells_2d),
            "n_cells_3d": int(self.n_cells_3d),
            "selected_layers": [int(v) for v in self.selected_layers],
            "selected_layer_mean_values": [
                _round_float(v) for v in self.selected_layer_mean_values
            ],
            "selected_layer_mean_depths": [
                _round_float(v) for v in self.selected_layer_mean_depths
            ],
            "selected_profiles": [
                profile.to_mapping() for profile in self.selected_profiles
            ],
        }


def _coerce_marker_specs(
    marker_specs: Sequence[Mapping[str, Any] | SourceCellMarkerSpec] | None,
) -> list[SourceCellMarkerSpec]:
    if marker_specs is None:
        return []
    return [
        spec if isinstance(spec, SourceCellMarkerSpec) else SourceCellMarkerSpec.from_mapping(spec)
        for spec in marker_specs
    ]


def _build_source_cell_marker_spec_contracts(
    mesh_with_values: ExtrudedPrismMeshWithValues,
    *,
    source_cell_indices: Sequence[int] | None = None,
    labels: Sequence[str] | None = None,
    colors: Sequence[str] | None = None,
) -> list[SourceCellMarkerSpec]:
    """Return typed marker specs from 2D source-cell indices."""
    source_indices = _normalize_indices(
        (
            select_default_source_cell_indices(mesh_with_values.n_cells_2d)
            if source_cell_indices is None
            else source_cell_indices
        ),
        upper_bound=mesh_with_values.n_cells_2d,
        label="source_cell",
    )
    cx, cy = mesh_with_values.mesh.planar_mesh.cell_centroids()
    cx_arr = np.asarray(cx, dtype=float).reshape(-1)
    cy_arr = np.asarray(cy, dtype=float).reshape(-1)

    specs: list[SourceCellMarkerSpec] = []
    for idx, source_idx in enumerate(source_indices):
        label = (
            str(labels[idx])
            if labels is not None and idx < len(labels)
            else f"P{idx + 1}"
        )
        color = (
            str(colors[idx])
            if colors is not None and idx < len(colors)
            else _PROFILE_COLORS[idx % len(_PROFILE_COLORS)]
        )
        specs.append(
            SourceCellMarkerSpec(
                label=label,
                color=color,
                source_cell_index=int(source_idx),
                xy=(
                    float(cx_arr[int(source_idx)]),
                    float(cy_arr[int(source_idx)]),
                ),
            )
        )
    return specs


def _round_float(value: float, ndigits: int = 12) -> float:
    """Round one float for compact JSON-friendly summaries."""
    return round(float(value), ndigits)


def _normalize_indices(
    indices: Iterable[int] | None, *, upper_bound: int, label: str
) -> list[int]:
    """Validate, deduplicate and preserve the order of requested indices."""
    if indices is None:
        return []
    unique: list[int] = []
    for raw in indices:
        idx = int(raw)
        if idx < 0 or idx >= int(upper_bound):
            raise IndexError(f"{label} index out of range: {idx}")
        if idx not in unique:
            unique.append(idx)
    return unique


def select_default_layer_indices(n_layers: int, *, max_layers: int = 3) -> list[int]:
    """Select representative layer indices across the vertical extent."""
    n_layers_int = int(n_layers)
    if n_layers_int <= 0:
        return []
    if n_layers_int <= max(1, int(max_layers)):
        return [int(v) for v in range(n_layers_int)]
    candidates = [0, n_layers_int // 2, n_layers_int - 1]
    selected: list[int] = []
    for idx in candidates:
        idx_int = int(idx)
        if idx_int not in selected:
            selected.append(idx_int)
    return selected[: max(1, int(max_layers))]


def select_default_source_cell_indices(
    n_cells_2d: int, *, max_profiles: int = 3
) -> list[int]:
    """Select representative 2D source cells for vertical profiles."""
    n_cells_int = int(n_cells_2d)
    if n_cells_int <= 0:
        return []
    if n_cells_int <= max(1, int(max_profiles)):
        return [int(v) for v in range(n_cells_int)]
    candidates = [0, n_cells_int // 2, n_cells_int - 1]
    selected: list[int] = []
    for idx in candidates:
        idx_int = int(idx)
        if idx_int not in selected:
            selected.append(idx_int)
    return selected[: max(1, int(max_profiles))]


def build_source_cell_marker_specs(
    mesh_with_values: ExtrudedPrismMeshWithValues,
    *,
    source_cell_indices: Sequence[int] | None = None,
    labels: Sequence[str] | None = None,
    colors: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Return XY marker specs from 2D source-cell indices."""
    return [
        spec.to_mapping()
        for spec in _build_source_cell_marker_spec_contracts(
            mesh_with_values,
            source_cell_indices=source_cell_indices,
            labels=labels,
            colors=colors,
        )
    ]


def plot_source_cell_markers(
    ax,
    marker_specs: Sequence[Mapping[str, Any] | SourceCellMarkerSpec],
) -> None:
    """Overlay labelled source-cell markers on a planar map."""
    for spec in _coerce_marker_specs(marker_specs):
        x, y = [float(v) for v in spec.xy]
        label = str(spec.label)
        color = str(spec.color)
        ax.scatter(
            [x],
            [y],
            s=74,
            color=color,
            edgecolors="white",
            linewidths=0.9,
            zorder=9,
        )
        ax.text(
            x,
            y,
            label,
            color="white",
            fontsize=9,
            weight="bold",
            ha="center",
            va="center",
            zorder=10,
        )


def plot_planar_cell_values(
    ax,
    *,
    mesh,
    values,
    title: str,
    cmap: str = "viridis",
    show_mesh: bool = True,
    vmin: float | None = None,
    vmax: float | None = None,
):
    """Plot one 2D layer on a planar mesh with consistent axis formatting.

    Uses the unified ``HydroMesh`` plotting pipeline internally.
    """
    from hydromodpy.spatial.mesh.plotting import plot_cell_values as _unified_plot

    hydro_mesh = mesh.to_hydro_mesh()
    mappable = _unified_plot(
        ax,
        hydro_mesh,
        values,
        cmap=cmap,
        show_mesh=show_mesh,
        vmin=vmin,
        vmax=vmax,
    )
    ax.set_title(title, fontsize=14)
    ax.set_xlabel("x [m]", fontsize=11)
    ax.set_ylabel("y [m]", fontsize=11)
    ax.tick_params(labelsize=9)
    ax.set_aspect("equal")
    disable_axis_offset(ax)
    return mappable


def build_layer_maps_figure(
    mesh_with_values: ExtrudedPrismMeshWithValues,
    *,
    layer_indices: Sequence[int] | None = None,
    marker_specs: Sequence[Mapping[str, Any]] | None = None,
    title: str = "Layer maps on the extruded prism mesh",
    value_label: str = "Field parameter value",
):
    """Build a compact figure with one panel per selected layer."""
    if not isinstance(mesh_with_values, ExtrudedPrismMeshWithValues):
        raise TypeError(
            "mesh_with_values must be an ExtrudedPrismMeshWithValues instance"
        )
    selected_layers = _normalize_indices(
        (
            select_default_layer_indices(mesh_with_values.n_layers)
            if layer_indices is None
            else layer_indices
        ),
        upper_bound=mesh_with_values.n_layers,
        label="layer",
    )
    if not selected_layers:
        raise ValueError("At least one layer must be selected for plotting")

    marker_payload = _coerce_marker_specs(marker_specs)
    values_3d = np.asarray(mesh_with_values.values_3d, dtype=float)
    depth_3d = None
    if mesh_with_values.prism_center_depths is not None:
        depth_3d = np.asarray(mesh_with_values.prism_center_depths, dtype=float)
    vmin = float(np.nanmin(values_3d))
    vmax = float(np.nanmax(values_3d))

    fig, axes = plt.subplots(
        1,
        len(selected_layers) + 1,
        figsize=(6.0 * len(selected_layers) + 1.1, 5.6),
        dpi=150,
        gridspec_kw={"width_ratios": [1.0] * len(selected_layers) + [0.055]},
        squeeze=False,
    )
    axes_flat = list(axes.reshape(-1))
    map_axes = axes_flat[: len(selected_layers)]
    cbar_ax = axes_flat[-1]

    # Keep one shared color scale so layer-to-layer comparisons stay visual.
    mappable = None
    for ax, layer_idx in zip(map_axes, selected_layers, strict=True):
        layer_title = f"Layer {int(layer_idx) + 1}"
        if depth_3d is not None:
            layer_title += (
                f"\nmean depth = {float(np.mean(depth_3d[int(layer_idx)])):.1f} m"
            )
        mappable = plot_planar_cell_values(
            ax,
            mesh=mesh_with_values.mesh.planar_mesh,
            values=values_3d[int(layer_idx)],
            title=layer_title,
            vmin=vmin,
            vmax=vmax,
        )
        if marker_payload:
            plot_source_cell_markers(ax, marker_payload)

    cbar = fig.colorbar(mappable, cax=cbar_ax, orientation="vertical")
    cbar.set_label(str(value_label), fontsize=11, rotation=90, labelpad=12)
    cbar.ax.tick_params(labelsize=9)
    maybe_scientific_colorbar(cbar, values_3d)

    fig.suptitle(str(title), fontsize=16)
    fig.subplots_adjust(left=0.05, right=0.97, top=0.88, bottom=0.12, wspace=0.18)
    return fig


def build_vertical_profiles_figure(
    mesh_with_values: ExtrudedPrismMeshWithValues,
    *,
    marker_specs: Sequence[Mapping[str, Any]] | None = None,
    title: str = "Vertical profiles on selected 2D source cells",
):
    """Build a figure with one vertical profile subplot per selected source cell."""
    if not isinstance(mesh_with_values, ExtrudedPrismMeshWithValues):
        raise TypeError(
            "mesh_with_values must be an ExtrudedPrismMeshWithValues instance"
        )
    specs = (
        _build_source_cell_marker_spec_contracts(mesh_with_values)
        if marker_specs is None
        else _coerce_marker_specs(marker_specs)
    )
    if not specs:
        raise ValueError(
            "At least one source cell must be selected for profile plotting"
        )

    fig, axes = plt.subplots(
        1,
        len(specs),
        figsize=(4.6 * len(specs), 4.9),
        dpi=150,
        squeeze=False,
    )
    axes_flat = list(axes.reshape(-1))
    for ax, spec in zip(axes_flat, specs, strict=True):
        profile = mesh_with_values.build_vertical_profile(int(spec.source_cell_index))
        values = np.asarray(profile.values, dtype=float)
        depths = np.asarray(() if profile.depths is None else profile.depths, dtype=float)
        if depths.size == 0:
            depths = np.arange(values.size, dtype=float)
        ax.plot(
            values,
            depths,
            marker="o",
            ms=5.8,
            lw=2.1,
            color=str(spec.color),
        )
        ax.set_title(
            f"{spec.label} (cell {int(spec.source_cell_index)})", fontsize=12
        )
        ax.set_xlabel("Field parameter value", fontsize=10)
        ax.set_ylabel("Depth [m]", fontsize=10)
        ax.tick_params(labelsize=9)
        ax.grid(True, color="0.90", lw=0.8)
        ax.invert_yaxis()
        x, y = [float(v) for v in spec.xy]
        ax.text(
            0.02,
            0.02,
            f"xy=({x:.0f}, {y:.0f})",
            transform=ax.transAxes,
            ha="left",
            va="bottom",
            fontsize=8,
            bbox={
                "boxstyle": "round,pad=0.35",
                "fc": "white",
                "ec": "0.85",
                "alpha": 0.94,
            },
        )

    fig.suptitle(str(title), fontsize=15)
    fig.subplots_adjust(left=0.06, right=0.985, top=0.87, bottom=0.14, wspace=0.28)
    return fig


def build_visualization_summary(
    mesh_with_values: ExtrudedPrismMeshWithValues,
    *,
    layer_indices: Sequence[int] | None = None,
    marker_specs: Sequence[Mapping[str, Any] | SourceCellMarkerSpec] | None = None,
) -> dict[str, Any]:
    """Return a compact JSON-friendly summary of selected visual slices."""
    selected_layers = _normalize_indices(
        (
            select_default_layer_indices(mesh_with_values.n_layers)
            if layer_indices is None
            else layer_indices
        ),
        upper_bound=mesh_with_values.n_layers,
        label="layer",
    )
    specs = (
        _build_source_cell_marker_spec_contracts(mesh_with_values)
        if marker_specs is None
        else _coerce_marker_specs(marker_specs)
    )
    selected_layer_mean_depths = (
        ()
        if mesh_with_values.prism_center_depths is None
        else tuple(
            float(
                np.mean(
                    np.asarray(
                        mesh_with_values.prism_center_depths[int(layer_idx)],
                        dtype=float,
                    )
                )
            )
            for layer_idx in selected_layers
        )
    )
    summary = ExtrudedVisualizationSummary(
        n_layers=int(mesh_with_values.n_layers),
        n_cells_2d=int(mesh_with_values.n_cells_2d),
        n_cells_3d=int(mesh_with_values.n_cells_3d),
        selected_layers=tuple(int(v) for v in selected_layers),
        selected_layer_mean_values=tuple(
            float(
                np.mean(
                    np.asarray(mesh_with_values.values_3d[int(layer_idx)], dtype=float)
                )
            )
            for layer_idx in selected_layers
        ),
        selected_layer_mean_depths=selected_layer_mean_depths,
        selected_profiles=tuple(
            VisualizationProfileSummary(
                label=str(spec.label),
                source_cell_index=int(spec.source_cell_index),
                xy=(float(spec.xy[0]), float(spec.xy[1])),
                profile=mesh_with_values.build_vertical_profile(
                    int(spec.source_cell_index)
                ),
            )
            for spec in specs
        ),
    )
    return summary.to_mapping()
