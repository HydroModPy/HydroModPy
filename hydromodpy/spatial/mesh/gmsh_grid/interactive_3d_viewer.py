"""Optional PyVista-based interactive viewer for extruded 3D meshes.

This module intentionally stays above the mesh/discretization core. It only
consumes `ExtrudedPrismMesh3D` and `ExtrudedPrismMeshWithValues` objects that
already carry all geometry and cell-wise values needed for interactive QA.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.spatial.mesh.gmsh_grid._deps import require_pyvista as _require_pyvista
from hydromodpy.spatial.mesh.gmsh_grid.extruded_mesh_values import (
    ExtrudedPrismMeshWithValues,
    ExtrudedVerticalProfile,
)
from hydromodpy.spatial.mesh.gmsh_grid.extruded_prism_mesh import (
    ExtrudedPrismMesh3D,
)

_DEFAULT_VALUE_NAME = "field_param_value"
_DEFAULT_DEPTH_NAME = "prism_center_depth"


@dataclass(frozen=True)
class PrismPickInfo:
    """Typed metadata for one picked prism in the interactive viewer."""

    prism_index: int
    layer_index: int
    source_cell_index: int
    centroid: tuple[float, float, float]
    value: float
    vertical_profile: ExtrudedVerticalProfile
    prism_center_depth: float | None = None

    def to_mapping(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "prism_index": int(self.prism_index),
            "layer_index": int(self.layer_index),
            "source_cell_index": int(self.source_cell_index),
            "centroid": _rounded_list(self.centroid),
            "value": round(float(self.value), 12),
            "vertical_profile": self.vertical_profile.to_mapping(),
        }
        if self.prism_center_depth is not None:
            payload["prism_center_depth"] = round(float(self.prism_center_depth), 12)
        return payload


@dataclass(frozen=True)
class SourceColumnSelection:
    """Typed description of one highlighted source column."""

    source_cell_index: int
    vertical_profile: ExtrudedVerticalProfile

    def to_mapping(self) -> dict[str, Any]:
        return {
            "source_cell_index": int(self.source_cell_index),
            "vertical_profile": self.vertical_profile.to_mapping(),
        }


def _require_mesh_3d(mesh_3d: ExtrudedPrismMesh3D) -> ExtrudedPrismMesh3D:
    """Validate and return the expected 3D mesh type."""
    if not isinstance(mesh_3d, ExtrudedPrismMesh3D):
        raise TypeError("mesh_3d must be an ExtrudedPrismMesh3D instance")
    return mesh_3d


def _require_mesh_with_values(
    mesh_with_values: ExtrudedPrismMeshWithValues,
) -> ExtrudedPrismMeshWithValues:
    """Validate and return the expected valued 3D mesh type."""
    if not isinstance(mesh_with_values, ExtrudedPrismMeshWithValues):
        raise TypeError("mesh_with_values must be an ExtrudedPrismMeshWithValues instance")
    return mesh_with_values


def _vtk_cell_type_for_mesh(mesh_3d: ExtrudedPrismMesh3D) -> int:
    """Map the HydroModPy prism type to the matching VTK cell identifier."""
    pv = _require_pyvista()
    if mesh_3d.cell_type_2d == "triangle":
        return int(pv.CellType.WEDGE)
    if mesh_3d.cell_type_2d == "quadrilateral":
        return int(pv.CellType.HEXAHEDRON)
    raise ValueError(f"Unsupported 2D cell type for PyVista conversion: {mesh_3d.cell_type_2d}")


def _build_cells_array(connectivity: np.ndarray) -> np.ndarray:
    """Convert a connectivity matrix to the VTK flat cell-array layout."""
    conn = np.asarray(connectivity, dtype=np.int64)
    widths = np.full((conn.shape[0], 1), conn.shape[1], dtype=np.int64)
    return np.hstack((widths, conn)).reshape(-1)


def _rounded_list(values, *, ndigits: int = 12) -> list[float]:
    """Round one numeric sequence for compact selection payloads."""
    return [round(float(v), ndigits) for v in np.asarray(values, dtype=float).reshape(-1)]


def build_pyvista_grid(mesh_3d: ExtrudedPrismMesh3D):
    """Convert one `ExtrudedPrismMesh3D` into a PyVista `UnstructuredGrid`."""
    mesh = _require_mesh_3d(mesh_3d)
    pv = _require_pyvista()
    # VTK expects one flattened cell array with a leading width per cell.
    cells = _build_cells_array(np.asarray(mesh.prism_connectivity, dtype=np.int64))
    celltypes: np.ndarray[Any, Any] = np.full(
        mesh.n_prisms, _vtk_cell_type_for_mesh(mesh), dtype=np.uint8
    )
    points = np.asarray(mesh.points_xyz, dtype=float)
    grid = pv.UnstructuredGrid(cells, celltypes, points)
    grid.cell_data["layer_index"] = np.asarray(mesh.layer_indices, dtype=np.int32)
    grid.cell_data["source_cell_index"] = np.asarray(mesh.source_cell_indices, dtype=np.int32)
    grid.point_data["point_layer_index"] = np.asarray(mesh.point_layer_indices, dtype=np.int32)
    grid.point_data["point_base_index"] = np.asarray(mesh.point_base_indices, dtype=np.int32)
    return grid


def build_pyvista_grid_with_values(
    mesh_with_values: ExtrudedPrismMeshWithValues,
    *,
    value_name: str = _DEFAULT_VALUE_NAME,
    depth_name: str = _DEFAULT_DEPTH_NAME,
):
    """Convert one valued prism mesh into a PyVista grid with scalar metadata."""
    mesh_values = _require_mesh_with_values(mesh_with_values)
    grid = build_pyvista_grid(mesh_values.mesh)
    grid.cell_data[str(value_name)] = np.asarray(mesh_values.flat_values, dtype=float)
    if mesh_values.prism_center_depths is not None:
        grid.cell_data[str(depth_name)] = np.asarray(
            mesh_values.flat_prism_center_depths, dtype=float
        )
    if mesh_values.label is not None:
        grid.field_data["value_label"] = np.asarray([str(mesh_values.label)], dtype=str)
    return grid


def add_vertical_exaggeration(grid, factor: float):
    """Return one copy of the grid with its Z coordinates scaled."""
    factor_float = float(factor)
    if not np.isfinite(factor_float) or factor_float <= 0.0:
        raise ValueError("vertical exaggeration factor must be strictly positive and finite")
    scaled = grid.copy(deep=True)
    points = np.asarray(scaled.points, dtype=float).copy()
    points[:, 2] *= factor_float
    scaled.points = points
    scaled.field_data["vertical_exaggeration"] = np.asarray([factor_float], dtype=float)
    return scaled


def add_layer_slice(
    plotter, grid, *, layer_index: int, value_name: str | None = None, **mesh_kwargs
):
    """Extract one full layer and add it to the plotter."""
    layer_idx = int(layer_index)
    layer_ids = np.where(np.asarray(grid.cell_data["layer_index"], dtype=int) == layer_idx)[0]
    if layer_ids.size == 0:
        raise IndexError(f"layer_index out of range for the current grid: {layer_idx}")
    layer_grid = grid.extract_cells(layer_ids)
    scalars = None if value_name is None else str(value_name)
    actor = plotter.add_mesh(layer_grid, scalars=scalars, **mesh_kwargs)
    return layer_grid, actor


def add_threshold(
    plotter,
    grid,
    *,
    scalar_name: str,
    value_range: tuple[float, float],
    **mesh_kwargs,
):
    """Threshold the grid on one scalar range and add the result."""
    vmin, vmax = [float(v) for v in value_range]
    thresholded = grid.threshold((vmin, vmax), scalars=str(scalar_name))
    actor = plotter.add_mesh(thresholded, scalars=str(scalar_name), **mesh_kwargs)
    return thresholded, actor


def add_clip_plane(
    plotter,
    grid,
    *,
    normal: str | tuple[float, float, float] = "z",
    origin: tuple[float, float, float] | None = None,
    scalar_name: str | None = None,
    **mesh_kwargs,
):
    """Clip the grid with one plane and add the clipped result."""
    clipped = grid.clip(normal=normal, origin=origin)
    scalars = None if scalar_name is None else str(scalar_name)
    actor = plotter.add_mesh(clipped, scalars=scalars, **mesh_kwargs)
    return clipped, actor


def add_bounds_axes(plotter) -> None:
    """Add basic bounds/axes aids to the active plotter."""
    plotter.show_bounds(grid="back", location="outer", ticks="outside")
    plotter.add_axes()


def extract_source_column_grid(
    mesh_with_values: ExtrudedPrismMeshWithValues, source_cell_index: int
):
    """Return the 3D column associated with one 2D source-cell index."""
    mesh_values = _require_mesh_with_values(mesh_with_values)
    source_idx = int(source_cell_index)
    if source_idx < 0 or source_idx >= mesh_values.n_cells_2d:
        raise IndexError(f"source_cell_index out of range: {source_idx}")
    grid = build_pyvista_grid_with_values(mesh_values)
    cell_ids = np.where(np.asarray(grid.cell_data["source_cell_index"], dtype=int) == source_idx)[0]
    return grid.extract_cells(cell_ids)


def extract_prism_pick_info(
    mesh_with_values: ExtrudedPrismMeshWithValues,
    prism_index: int,
) -> dict[str, Any]:
    """Return metadata and the associated vertical profile for one picked prism."""
    mesh_values = _require_mesh_with_values(mesh_with_values)
    prism_idx = int(prism_index)
    if prism_idx < 0 or prism_idx >= mesh_values.n_cells_3d:
        raise IndexError(f"prism_index out of range: {prism_idx}")
    prism = mesh_values.mesh.prisms[prism_idx]
    value = float(mesh_values.flat_values[prism_idx])
    pick_info = PrismPickInfo(
        prism_index=prism_idx,
        layer_index=int(prism.layer_index),
        source_cell_index=int(prism.source_cell_index),
        centroid=tuple(float(v) for v in prism.centroid),
        value=value,
        vertical_profile=mesh_values.build_vertical_profile(int(prism.source_cell_index)),
    )
    if mesh_values.prism_center_depths is not None:
        flat_depths = mesh_values.flat_prism_center_depths
        if flat_depths is None:
            raise ValueError(
                "flat_prism_center_depths should be available when prism_center_depths is set"
            )
        pick_info = PrismPickInfo(
            prism_index=pick_info.prism_index,
            layer_index=pick_info.layer_index,
            source_cell_index=pick_info.source_cell_index,
            centroid=pick_info.centroid,
            value=pick_info.value,
            vertical_profile=pick_info.vertical_profile,
            prism_center_depth=float(flat_depths[prism_idx]),
        )
    return pick_info.to_mapping()


def _build_plotter(
    *,
    title: str | None = None,
    off_screen: bool = False,
):
    """Create the PyVista plotter used by the interactive helpers."""
    pv = _require_pyvista()
    return pv.Plotter(title=None if title is None else str(title), off_screen=bool(off_screen))


def _highlight_selection(
    plotter,
    mesh_with_values: ExtrudedPrismMeshWithValues,
    *,
    prism_index: int | None,
    source_cell_index: int | None,
):
    """Highlight a picked prism or a whole source column and summarize it."""
    selection_payload: dict[str, Any] | None = None
    if prism_index is not None:
        selection_payload = extract_prism_pick_info(mesh_with_values, int(prism_index))
        grid = build_pyvista_grid_with_values(mesh_with_values)
        selection_grid = grid.extract_cells([int(prism_index)])
        plotter.add_mesh(
            selection_grid,
            color="#fde047",
            line_width=3.0,
            show_edges=True,
            opacity=1.0,
        )
    elif source_cell_index is not None:
        source_idx = int(source_cell_index)
        selection_payload = SourceColumnSelection(
            source_cell_index=source_idx,
            vertical_profile=mesh_with_values.build_vertical_profile(source_idx),
        ).to_mapping()
        column_grid = extract_source_column_grid(mesh_with_values, source_idx)
        plotter.add_mesh(
            column_grid, color="#fb7185", line_width=2.5, show_edges=True, opacity=0.85
        )
    return selection_payload


def show_interactive_mesh_3d(
    mesh_3d: ExtrudedPrismMesh3D,
    *,
    show_edges: bool = True,
    color: str = "#94a3b8",
    opacity: float = 1.0,
    vertical_exaggeration: float = 1.0,
    title: str | None = None,
    show: bool = True,
    off_screen: bool = False,
    screenshot_path: str | Path | None = None,
):
    """Open one interactive PyVista viewer on the bare 3D mesh."""
    mesh = _require_mesh_3d(mesh_3d)
    grid = build_pyvista_grid(mesh)
    display_grid = (
        grid
        if float(vertical_exaggeration) == 1.0
        else add_vertical_exaggeration(grid, vertical_exaggeration)
    )
    plotter = _build_plotter(
        title=title,
        off_screen=(bool(off_screen) or screenshot_path is not None or not show),
    )
    plotter.add_mesh(
        display_grid,
        color=str(color),
        opacity=float(opacity),
        show_edges=bool(show_edges),
    )
    add_bounds_axes(plotter)
    plotter.reset_camera()
    if screenshot_path is not None:
        screenshot_obj = Path(screenshot_path).resolve()
        screenshot_obj.parent.mkdir(parents=True, exist_ok=True)
        plotter.screenshot(str(screenshot_obj))
    if show:
        plotter.show()
    return {
        "grid": grid,
        "display_grid": display_grid,
        "plotter": plotter,
    }


def show_interactive_values_3d(
    mesh_with_values: ExtrudedPrismMeshWithValues,
    *,
    value_name: str = _DEFAULT_VALUE_NAME,
    depth_name: str = _DEFAULT_DEPTH_NAME,
    cmap: str = "viridis",
    show_edges: bool = False,
    opacity: float = 1.0,
    threshold_range: tuple[float, float] | None = None,
    clip_normal: str | tuple[float, float, float] | None = None,
    clip_origin: tuple[float, float, float] | None = None,
    vertical_exaggeration: float = 1.0,
    highlight_source_cell_index: int | None = None,
    highlight_prism_index: int | None = None,
    title: str | None = None,
    show: bool = True,
    off_screen: bool = False,
    screenshot_path: str | Path | None = None,
):
    """Open one interactive PyVista viewer on 3D prism values.

    The viewer deliberately exposes a few simple QA tools only: thresholding,
    clipping, vertical exaggeration, and optional highlighting of one prism or
    one source column.
    """
    mesh_values = _require_mesh_with_values(mesh_with_values)
    grid = build_pyvista_grid_with_values(
        mesh_values,
        value_name=value_name,
        depth_name=depth_name,
    )
    display_grid = (
        grid
        if float(vertical_exaggeration) == 1.0
        else add_vertical_exaggeration(grid, vertical_exaggeration)
    )
    plotter = _build_plotter(
        title=title,
        off_screen=(bool(off_screen) or screenshot_path is not None or not show),
    )

    active_grid = display_grid
    if threshold_range is not None:
        active_grid, _ = add_threshold(
            plotter,
            display_grid,
            scalar_name=str(value_name),
            value_range=threshold_range,
            cmap=str(cmap),
            show_edges=bool(show_edges),
            opacity=float(opacity),
        )
    elif clip_normal is not None:
        active_grid, _ = add_clip_plane(
            plotter,
            display_grid,
            normal=clip_normal,
            origin=clip_origin,
            scalar_name=str(value_name),
            cmap=str(cmap),
            show_edges=bool(show_edges),
            opacity=float(opacity),
        )
    else:
        plotter.add_mesh(
            display_grid,
            scalars=str(value_name),
            cmap=str(cmap),
            show_edges=bool(show_edges),
            opacity=float(opacity),
        )

    selection_payload = _highlight_selection(
        plotter,
        mesh_values,
        prism_index=highlight_prism_index,
        source_cell_index=highlight_source_cell_index,
    )
    add_bounds_axes(plotter)
    plotter.reset_camera()

    screenshot_obj = None
    if screenshot_path is not None:
        screenshot_obj = Path(screenshot_path).resolve()
        screenshot_obj.parent.mkdir(parents=True, exist_ok=True)
        plotter.screenshot(str(screenshot_obj))
    if show:
        plotter.show()

    return {
        "grid": grid,
        "display_grid": active_grid,
        "plotter": plotter,
        "selection": selection_payload,
        "screenshot_path": None if screenshot_obj is None else str(screenshot_obj),
    }
