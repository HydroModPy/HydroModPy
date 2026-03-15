"""Project one FieldParam onto every layer of an extruded prism mesh.

The key idea in this module is that the spatial support stays planar even when
the final values are 3D. The support field is first discretized on the base
2D mesh, then the FieldParam is reevaluated at the center depth of each prism
to build a full `(n_layers, n_cells_2d)` result.

This keeps the workflow simple: reuse the mature 2D discretization logic, then
add the vertical dimension only where depth-dependent values are needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from hydromodpy.solver.utils.mesh.gmsh_grid.extruded_prism_mesh import (
    ExtrudedPrismMesh3D,
)


@dataclass(frozen=True)
class ExtrudedFieldParamDiscretizationResult:
    """Result bundle for one 3D discretization run on an extruded prism mesh."""

    values_3d: np.ndarray
    values_2d: np.ndarray
    planar_mesh_values: object
    planar_mesh: object
    mesh_3d: ExtrudedPrismMesh3D
    field_discretization: object | None
    prism_center_depths: np.ndarray


def _compute_prism_center_depths(mesh_3d: ExtrudedPrismMesh3D) -> np.ndarray:
    """Return positive-downward prism-center depths shaped as (n_layers, n_cells_2d)."""
    _, _, z_centers = mesh_3d.prism_centroids()
    z_centers = np.asarray(z_centers, dtype=float).reshape(-1)
    top_reference = float(mesh_3d.z_interfaces[0])
    depth_flat = np.abs(z_centers - top_reference)

    n_layers = int(mesh_3d.n_layers)
    n_cells_2d = int(mesh_3d.planar_mesh.n_cells)
    depth_grid: np.ndarray[Any, Any] = np.full(
        (n_layers, n_cells_2d), np.nan, dtype=float
    )

    for prism_idx, (layer_idx, source_idx) in enumerate(
        zip(mesh_3d.layer_indices, mesh_3d.source_cell_indices, strict=True)
    ):
        layer_idx = int(layer_idx)
        source_idx = int(source_idx)
        if not np.isnan(depth_grid[layer_idx, source_idx]):
            raise ValueError(
                "Extruded prism mesh contains duplicate prisms for one (layer, source_cell) slot"
            )
        depth_grid[layer_idx, source_idx] = float(depth_flat[prism_idx])

    if np.any(~np.isfinite(depth_grid)):
        raise ValueError(
            "Extruded prism mesh does not define exactly one prism center depth "
            "for every (layer, source_cell_2d) slot"
        )
    return depth_grid


def discretize_fieldparam_on_extruded_mesh(
    *,
    support_field=None,
    field_param,
    mesh_3d: ExtrudedPrismMesh3D,
    cell_samples_per_axis: int | None = None,
    depth: float = 0.0,
    strict_field_spatial_id_match: bool = True,
    geology_field=None,
) -> ExtrudedFieldParamDiscretizationResult:
    """Discretize one FieldParam on one extruded prism mesh.

    The support projection stays strictly planar:
    1. support is discretized on ``mesh_3d.planar_mesh``,
    2. one planar reference map is computed,
    3. values are reevaluated on every prism layer using prism-center depths.
    """
    if support_field is not None and geology_field is not None:
        raise ValueError(
            "Use either 'support_field' or legacy 'geology_field', not both."
        )
    if support_field is None:
        support_field = geology_field

    if not isinstance(mesh_3d, ExtrudedPrismMesh3D):
        raise TypeError("mesh_3d must be an ExtrudedPrismMesh3D instance")
    if not hasattr(field_param, "to_mesh_field"):
        raise TypeError("field_param must expose `to_mesh_field(...)`")

    is_heterogeneous = bool(getattr(field_param, "is_heterogeneous", False))
    if is_heterogeneous and support_field is None:
        raise ValueError("Heterogeneous field requires 'support_field'")
    if support_field is not None and not hasattr(support_field, "on_mesh"):
        raise TypeError("support_field must expose `on_mesh(...)`")
    if support_field is not None and not hasattr(support_field, "identifier"):
        raise TypeError("support_field must expose `identifier`")

    if is_heterogeneous and strict_field_spatial_id_match:
        required_field_id = str(getattr(field_param, "field_spatial_id", "")).strip()
        support_field_id = str(getattr(support_field, "identifier", "")).strip()
        if (
            required_field_id
            and support_field_id
            and required_field_id != support_field_id
        ):
            raise ValueError(
                "field_param.field_spatial_id does not match support_field.identifier: "
                f"{required_field_id!r} != {support_field_id!r}"
            )

    planar_mesh = mesh_3d.planar_mesh
    default_n_sub = (
        int(getattr(support_field, "default_cell_samples_per_axis", 8))
        if support_field is not None
        else 8
    )
    n_sub = max(2, int(cell_samples_per_axis or default_n_sub))

    field_discretization = None
    if support_field is not None:
        field_discretization = support_field.on_mesh(
            planar_mesh,
            cell_samples_per_axis=n_sub,
        )

    if field_discretization is None:
        planar_mesh_values = field_param.to_mesh_field(
            mesh=planar_mesh, depth=float(depth)
        )
    else:
        planar_mesh_values = field_param.to_mesh_field(
            field_discretization,
            depth=float(depth),
        )
    values_2d = np.asarray(
        planar_mesh.to_cell_values(planar_mesh_values.cell_values), dtype=float
    ).reshape(-1)

    prism_center_depths = _compute_prism_center_depths(mesh_3d) + float(depth)
    n_layers = int(mesh_3d.n_layers)
    n_cells_2d = int(planar_mesh.n_cells)
    values_3d: np.ndarray[Any, Any] = np.empty((n_layers, n_cells_2d), dtype=float)

    for layer_idx in range(n_layers):
        layer_depth = np.asarray(prism_center_depths[layer_idx], dtype=float)
        if field_discretization is None:
            layer_mesh_values = field_param.to_mesh_field(
                mesh=planar_mesh,
                depth=layer_depth,
            )
        else:
            layer_mesh_values = field_param.to_mesh_field(
                field_discretization,
                depth=layer_depth,
            )
        values_3d[layer_idx, :] = np.asarray(
            planar_mesh.to_cell_values(layer_mesh_values.cell_values),
            dtype=float,
        ).reshape(-1)

    return ExtrudedFieldParamDiscretizationResult(
        values_3d=values_3d,
        values_2d=values_2d,
        planar_mesh_values=planar_mesh_values,
        planar_mesh=planar_mesh,
        mesh_3d=mesh_3d,
        field_discretization=field_discretization,
        prism_center_depths=prism_center_depths,
    )
