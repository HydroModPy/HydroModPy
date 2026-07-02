"""Property mapping helpers specialized for MODFLOW 6 cell-based layouts."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.solver.field_property_mapping import (
    coerce_spatial_support_field as _coerce_spatial_support_field,
)
from hydromodpy.solver.field_property_mapping import (
    resolve_field_param as _resolve_field_param,
)
from hydromodpy.solver.field_property_mapping import (
    resolve_spatial_support_from_domain as _resolve_spatial_support_from_domain,
)
from hydromodpy.solver.modflow_common.property_mapping import (
    resolve_flow_property_arrays as resolve_structured_flow_property_arrays,
)
from hydromodpy.solver.modflow_common.property_mapping import (
    resolve_required_flow_properties,
)
from hydromodpy.solver.modflow_common.runtime_arrays import (
    resolve_flow_property_runtime_overrides,
)
from hydromodpy.spatial.mesh.gmsh_grid.gmsh_planar_mesh import GmshPlanarMesh2D

logger = get_logger(__name__)
_DEFAULT_CELL_SAMPLES_PER_AXIS = 8


def _resolve_field_discretization(
    *,
    support_field: object,
    planar_mesh,
    geometry_cache: dict[tuple[int, int], object],
) -> object:
    cell_samples_per_axis = int(
        getattr(
            support_field,
            "default_cell_samples_per_axis",
            _DEFAULT_CELL_SAMPLES_PER_AXIS,
        )
        or _DEFAULT_CELL_SAMPLES_PER_AXIS
    )
    cache_key = (id(support_field), cell_samples_per_axis)
    cached = geometry_cache.get(cache_key)
    if cached is not None:
        return cached
    discretized = support_field.on_mesh(
        planar_mesh,
        cell_samples_per_axis=cell_samples_per_axis,
    )
    geometry_cache[cache_key] = discretized
    return discretized


def _resolve_planar_mesh(planar_mesh: object | None, solver_mesh) -> object:
    from hydromodpy.spatial.mesh.cell_types import CellType

    hydro = getattr(solver_mesh, "planar_mesh", None)
    # On a Voronoi (ragged POLYGON) solver grid the property MUST be mapped onto the
    # Voronoi cells, so ignore any triangular seed planar_mesh passed in: use the
    # polygon field mesh (arbitrary-arity area sampling; the fixed-arity
    # GmshPlanarMesh2D bridge cannot wrap a ragged mesh).
    if hydro is not None and CellType.POLYGON in getattr(hydro, "cell_types", ()):
        from hydromodpy.spatial.field.meshes.polygon_field_mesh import PolygonFieldMesh

        return PolygonFieldMesh(hydro)
    if planar_mesh is not None:
        return planar_mesh
    return GmshPlanarMesh2D.from_hydro_mesh(hydro)


def _build_cellular_property_from_flow_domain(
    *,
    flow: object,
    domain: object,
    planar_mesh,
    solver_mesh,
    geometry_cache: dict[tuple[int, int], object],
    flow_param_candidates: tuple[str, ...],
    target_attr: str,
    property_label: str,
) -> tuple[np.ndarray, np.ndarray]:
    selected_name, param_obj = _resolve_field_param(
        flow=flow,
        aliases=flow_param_candidates,
        property_label=property_label,
    )

    if getattr(param_obj, "is_heterogeneous", False):
        if domain is None:
            raise ValueError(
                f"Cannot map {property_label}: missing domain for heterogeneous parameter"
            )
        required_field_id = str(getattr(param_obj, "field_spatial_id", "")).strip()
        support_field = _coerce_spatial_support_field(
            _resolve_spatial_support_from_domain(
                domain=domain,
                support_id=required_field_id,
            ),
            support_id=required_field_id,
        )
        field_discretization = _resolve_field_discretization(
            support_field=support_field,
            planar_mesh=planar_mesh,
            geometry_cache=geometry_cache,
        )
        planar_mesh_values = param_obj.to_mesh_field(
            field_discretization,
            label=target_attr,
            depth=0.0,
        )
        support_label = f"domain support '{required_field_id}'"
    else:
        field_discretization = None
        planar_mesh_values = param_obj.to_mesh_field(
            mesh=planar_mesh,
            label=target_attr,
            depth=0.0,
        )
        support_label = "direct homogeneous mapping"

    values_2d = np.asarray(planar_mesh.to_cell_values(planar_mesh_values.cell_values), dtype=float)
    layer_center_depths = np.asarray(solver_mesh.layer_center_depths(), dtype=float)
    nlay = int(solver_mesh.nlay)
    n_cells = int(solver_mesh.n_cells)
    values_3d = np.empty((nlay, n_cells), dtype=float)

    for layer_idx in range(nlay):
        layer_depth = np.asarray(layer_center_depths[layer_idx], dtype=float)
        if field_discretization is None:
            layer_mesh_values = param_obj.to_mesh_field(
                mesh=planar_mesh,
                label=target_attr,
                depth=layer_depth,
            )
        else:
            layer_mesh_values = param_obj.to_mesh_field(
                field_discretization,
                label=target_attr,
                depth=layer_depth,
            )
        values_3d[layer_idx, :] = np.asarray(
            planar_mesh.to_cell_values(layer_mesh_values.cell_values),
            dtype=float,
        ).reshape(-1)

    logger.debug(
        "%s mapped from flow.%s using %s",
        property_label,
        selected_name,
        support_label,
    )
    return values_3d.copy(), values_2d.copy()


def _zero_property_arrays(*, solver_mesh) -> tuple[np.ndarray, np.ndarray]:
    nlay = int(solver_mesh.nlay)
    n_cells = int(solver_mesh.n_cells)
    return (
        np.zeros((nlay, n_cells), dtype=float),
        np.zeros((n_cells,), dtype=float),
    )


def _support_cell_vector(
    mesh_support: object | None,
    attr_name: str,
    *,
    n_cells: int,
    positive: bool,
) -> np.ndarray | None:
    if mesh_support is None:
        return None
    values = getattr(mesh_support, attr_name, None)
    if values is None:
        return None
    arr = np.asarray(values, dtype=float).reshape(-1)
    if arr.size != int(n_cells):
        return None
    valid = np.isfinite(arr)
    if positive:
        valid &= arr > 0.0
    if not np.any(valid):
        return None
    return np.where(valid, arr, np.nan)


def fill_missing_flow_properties_from_mesh_support(
    flow_params: dict[str, np.ndarray],
    *,
    mesh_support: object | None,
    solver_mesh: object,
) -> dict[str, np.ndarray]:
    """Complete invalid unstructured MF6 properties from mesh-bundle metadata."""
    if getattr(solver_mesh, "is_structured", False):
        return flow_params

    n_cells = int(solver_mesh.n_cells)
    support_k = _support_cell_vector(
        mesh_support,
        "cell_hydraulic_conductivity_m_s",
        n_cells=n_cells,
        positive=True,
    )
    if support_k is None:
        return flow_params

    out = dict(flow_params)
    for key in ("hk", "hk_value"):
        if key not in out:
            continue
        arr = np.asarray(out[key], dtype=float).copy()
        invalid = ~np.isfinite(arr) | (arr <= 0.0)
        if not np.any(invalid):
            continue
        if arr.ndim == 1:
            replacement = np.broadcast_to(support_k, arr.shape)
        elif arr.ndim == 2 and arr.shape[1] == n_cells:
            replacement = np.broadcast_to(support_k.reshape(1, -1), arr.shape)
        else:
            continue
        replace_mask = invalid & np.isfinite(replacement) & (replacement > 0.0)
        if not np.any(replace_mask):
            continue
        arr[replace_mask] = replacement[replace_mask]
        out[key] = arr
        logger.debug(
            "Completed %s for %d unstructured cell value(s) from mesh bundle conductivity.",
            key,
            int(np.count_nonzero(replace_mask)),
        )
    return out


def resolve_flow_property_arrays(
    *,
    flow: object,
    domain: object,
    solver_mesh,
    planar_mesh: object | None = None,
    required_properties: frozenset[str] | set[str] | None = None,
    optional_fill_values: Mapping[str, float] | None = None,
    runtime_property_overrides: Mapping[str, object] | None = None,
) -> dict[str, np.ndarray]:
    """Resolve canonical K/Sy/Ss arrays for MF6 structured or cell-based meshes."""
    if getattr(solver_mesh, "is_structured", False):
        return resolve_structured_flow_property_arrays(
            flow=flow,
            domain=domain,
            solver_mesh=solver_mesh,
            required_properties=required_properties,
            optional_fill_values=optional_fill_values,
            runtime_property_overrides=runtime_property_overrides,
        )

    mapping_specs = [
        ("K", ("K", "k"), "hk", "hk_value", "Hydraulic conductivity"),
        ("Sy", ("Sy", "SY", "sy", "S", "s"), "sy", "sy_value", "Specific yield"),
        ("Ss", ("Ss", "SS", "ss"), "ss", "ss_value", "Specific storage"),
    ]

    required = (
        {str(name).strip() for name in required_properties}
        if required_properties is not None
        else {"K", "Sy", "Ss"}
    )
    optional_defaults = {
        str(name).strip(): float(value) for name, value in (optional_fill_values or {}).items()
    }
    mesh_2d = _resolve_planar_mesh(planar_mesh, solver_mesh)
    geometry_cache: dict[tuple[int, int], object] = {}
    out: dict[str, np.ndarray] = {}
    parameters = getattr(flow, "parameters", {})
    if not isinstance(parameters, dict):
        raise TypeError("flow.parameters must be a dictionary")
    runtime_overrides = resolve_flow_property_runtime_overrides(
        runtime_property_overrides,
        solver_mesh,
        required_properties=required,
        optional_fill_values=optional_fill_values,
    )

    for canonical_name, aliases, target_3d_attr, target_surface_attr, label in mapping_specs:
        if target_3d_attr in runtime_overrides:
            out[target_3d_attr] = np.asarray(
                runtime_overrides[target_3d_attr],
                dtype=float,
            ).copy()
            out[target_surface_attr] = np.asarray(
                runtime_overrides[target_surface_attr],
                dtype=float,
            ).copy()
            continue
        has_parameter = any(candidate in parameters for candidate in aliases)
        if not has_parameter and canonical_name not in required:
            fill_value = optional_defaults.get(canonical_name, None)
            if fill_value is None:
                continue
            values_3d, values_2d = _zero_property_arrays(solver_mesh=solver_mesh)
            if fill_value != 0.0:
                values_3d.fill(fill_value)
                values_2d.fill(fill_value)
            out[target_3d_attr] = values_3d
            out[target_surface_attr] = values_2d
            continue

        values_3d, values_2d = _build_cellular_property_from_flow_domain(
            flow=flow,
            domain=domain,
            planar_mesh=mesh_2d,
            solver_mesh=solver_mesh,
            geometry_cache=geometry_cache,
            flow_param_candidates=aliases,
            target_attr=target_3d_attr,
            property_label=label,
        )
        out[target_3d_attr] = values_3d
        out[target_surface_attr] = values_2d

    return out


__all__ = [
    "fill_missing_flow_properties_from_mesh_support",
    "resolve_flow_property_arrays",
    "resolve_required_flow_properties",
]
