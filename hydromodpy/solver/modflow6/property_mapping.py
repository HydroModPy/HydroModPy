"""Property mapping helpers specialized for MODFLOW 6 cell-based layouts."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.solver.modflow_common.runtime_arrays import (
    resolve_flow_property_runtime_overrides,
)
from hydromodpy.solver.modflow_nwt.modflow.property_mapping import (
    resolve_required_flow_properties,
    resolve_flow_property_arrays as resolve_structured_flow_property_arrays,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.gmsh_planar_mesh import GmshPlanarMesh2D

logger = get_logger(__name__)
_DEFAULT_CELL_SAMPLES_PER_AXIS = 8


def _coerce_spatial_support_field(zone_obj, *, support_id: str | None = None):
    if zone_obj is None:
        support_label = support_id if support_id is not None else "<unspecified>"
        raise ValueError(
            f"Missing spatial support '{support_label}' in domain for heterogeneous mapping"
        )
    if not hasattr(zone_obj, "on_mesh"):
        raise TypeError(
            "Domain spatial support must expose 'on_mesh(...)'. Expected a Field-compatible object."
        )
    if not hasattr(zone_obj, "identifier"):
        raise TypeError(
            "Domain spatial support must expose 'identifier'. Expected a Field-compatible object."
        )
    return zone_obj


def _resolve_spatial_support_from_domain(*, domain: object, support_id: str) -> object:
    normalized_support_id = str(support_id).strip()
    if normalized_support_id == "":
        raise ValueError("field_spatial_id cannot be empty for heterogeneous mapping")

    resolver = getattr(domain, "resolve_spatial_support", None)
    if callable(resolver):
        return resolver(normalized_support_id)

    zones = getattr(domain, "zones", {})
    if not isinstance(zones, dict):
        raise TypeError("domain.zones must be a dictionary")

    by_zone_id = zones.get(normalized_support_id.lower())
    if by_zone_id is not None:
        return by_zone_id

    matches = [
        zone_obj
        for zone_obj in zones.values()
        if str(getattr(zone_obj, "identifier", "")).strip() == normalized_support_id
    ]
    if len(matches) > 1:
        raise ValueError(f"Multiple domain zones match spatial support '{normalized_support_id}'.")
    return matches[0] if matches else None


def _resolve_field_param(*, flow: object, aliases: tuple[str, ...], property_label: str):
    if flow is None or not hasattr(flow, "parameters"):
        raise ValueError("Missing flow object or flow.parameters for property mapping")
    parameters = getattr(flow, "parameters", {})
    if not isinstance(parameters, dict):
        raise TypeError("flow.parameters must be a dictionary")

    for alias in aliases:
        if alias in parameters:
            param_obj = parameters[alias]
            if not hasattr(param_obj, "to_mesh_field"):
                raise TypeError(
                    f"Cannot map {property_label}: selected parameter '{alias}' "
                    "does not expose to_mesh_field(...)"
                )
            return str(alias), param_obj

    aliases_txt = ", ".join(aliases)
    raise ValueError(f"Cannot map {property_label}: missing flow parameter among ({aliases_txt})")


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
    if planar_mesh is not None:
        return planar_mesh
    return GmshPlanarMesh2D.from_hydro_mesh(solver_mesh.planar_mesh)


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

    logger.info(
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
    "resolve_flow_property_arrays",
    "resolve_required_flow_properties",
]
