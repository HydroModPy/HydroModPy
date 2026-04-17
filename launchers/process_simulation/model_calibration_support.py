"""Public model-calibration runtime support built from a prepared launcher.

This module translates one prepared ``HydroModPyLauncher`` runtime into the
hydraulic support contract consumed by the model-calibration workflow.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from hydromodpy.simulation.model_calibration_support import (
    ModelCalibrationRuntimeSupportUnavailable,
    RuntimeHydraulicPropertySupport,
    bundle_zone_fractions,
    labels_from_zone_fractions,
    parse_property_support_id,
    parse_property_values_by_key,
    resolve_flow_property_config,
    select_runtime_preparation_flow_solver,
    setup_mesh_paths_from_runtime,
    surface_property_vector,
)
from hydromodpy.solver.modflow_common.discretization_spatial import (
    build_spatial_discretization,
)


def build_runtime_hydraulic_property_support(
    *,
    launcher: Any,
    raw_simulation_toml: dict[str, Any],
    solver_families: tuple[str, ...],
    property_names: tuple[str, ...],
) -> RuntimeHydraulicPropertySupport:
    """Build hydraulic support from one already prepared process-simulation launcher."""
    selected_solver = select_runtime_preparation_flow_solver(
        solver_families=solver_families,
    )
    if selected_solver is None:
        raise ModelCalibrationRuntimeSupportUnavailable(
            "No runtime-preparation flow solver is available for calibration support."
        )

    launcher.prepare_runtime()
    setup_state = launcher.run_state.setup
    if setup_state.flow is None or setup_state.domain is None:
        raise ModelCalibrationRuntimeSupportUnavailable(
            "Prepared launcher runtime does not expose both flow and domain state."
        )

    if selected_solver == "modflow6":
        from hydromodpy.solver.modflow6.property_mapping import (
            resolve_flow_property_arrays as resolve_runtime_property_arrays,
        )

        sgrid_config = launcher.cfg.modflow6.sgrid
    elif selected_solver == "modflownwt":
        from hydromodpy.solver.modflow_nwt.modflow.property_mapping import (
            resolve_flow_property_arrays as resolve_runtime_property_arrays,
        )

        sgrid_config = launcher.cfg.modflownwt.sgrid
    else:
        raise ModelCalibrationRuntimeSupportUnavailable(
            f"Unsupported runtime-preparation solver '{selected_solver}'."
        )

    grid_ctx = build_spatial_discretization(
        domain=setup_state.domain,
        sgrid_config=sgrid_config,
        runtime_planar_mesh=getattr(setup_state, "mesh_planar", None),
        runtime_mesh_support=getattr(setup_state, "mesh_support", None),
    )
    solver_mesh = grid_ctx.solver_mesh
    required_properties = {
        name for name in property_names if str(name).strip() in {"K", "Sy"}
    }
    if not required_properties:
        required_properties = {"K"}

    runtime_arrays = resolve_runtime_property_arrays(
        flow=setup_state.flow,
        domain=setup_state.domain,
        solver_mesh=solver_mesh,
        planar_mesh=getattr(setup_state, "mesh_planar", None),
        required_properties=required_properties,
        optional_fill_values={"Sy": 0.0},
    )

    base_property_arrays: dict[str, tuple[float, ...]] = {}
    if "hk_value" in runtime_arrays:
        base_property_arrays["K"] = surface_property_vector(
            runtime_arrays["hk_value"],
            solver_mesh=solver_mesh,
        )
    if "sy_value" in runtime_arrays:
        base_property_arrays["Sy"] = surface_property_vector(
            runtime_arrays["sy_value"],
            solver_mesh=solver_mesh,
        )

    lithology_labels: tuple[str, ...] | None = None
    bundle_has_labels = False
    zone_fractions_by_property: dict[str, dict[str, tuple[float, ...]]] = {}
    zone_fractions_by_key: dict[str, tuple[float, ...]] = {}
    base_property_values_by_key: dict[str, dict[str, float]] = {}
    support_id_by_property: dict[str, str] = {}

    mesh_bundle = getattr(setup_state, "mesh_bundle", None)
    if mesh_bundle is not None:
        bundle_labels = tuple(
            str(getattr(cell, "geology_key", "") or "").strip()
            for cell in getattr(mesh_bundle, "cells", ())
        )
        if any(bundle_labels):
            lithology_labels = bundle_labels
            bundle_has_labels = True
        zone_fractions_by_key = bundle_zone_fractions(
            mesh_bundle,
            n_cells=max(1, int(getattr(solver_mesh, "n_cells", 1))),
        )
        if zone_fractions_by_key:
            for property_name in sorted(required_properties):
                zone_fractions_by_property[str(property_name)] = dict(
                    zone_fractions_by_key
                )

    domain = setup_state.domain
    mesh_for_support = getattr(setup_state, "mesh_planar", None)
    if mesh_for_support is None and bool(getattr(solver_mesh, "is_structured", False)):
        try:
            from hydromodpy.solver.utils import build_field_mesh_from_sgrid

            mesh_for_support = build_field_mesh_from_sgrid(solver_mesh)
        except Exception:
            mesh_for_support = None
    if mesh_for_support is None:
        solver_planar_mesh = getattr(solver_mesh, "planar_mesh", None)
        if hasattr(solver_planar_mesh, "cells"):
            mesh_for_support = solver_planar_mesh
    if mesh_for_support is None and hasattr(solver_mesh, "cells"):
        mesh_for_support = solver_mesh

    support_id_used: str | None = None
    mixed_support_ids = False
    if domain is not None and mesh_for_support is not None:
        for property_name in sorted(required_properties):
            property_name = str(property_name)
            property_cfg = resolve_flow_property_config(
                raw_simulation_toml=raw_simulation_toml,
                property_name=property_name,
            )
            zone_values = parse_property_values_by_key(property_cfg)
            if zone_values:
                base_property_values_by_key[property_name] = zone_values

            support_id = parse_property_support_id(property_cfg)
            if support_id is None:
                continue
            resolver = getattr(domain, "resolve_spatial_support", None)
            if not callable(resolver):
                continue
            try:
                support_field = resolver(support_id)
            except Exception:
                continue
            if support_field is None or not hasattr(support_field, "on_mesh"):
                continue
            try:
                discretization = support_field.on_mesh(mesh_for_support)
                zone_keys, fractions_by_zone = discretization.weighted_components()
            except Exception:
                continue
            normalized_fractions = {
                str(zone_key).strip(): tuple(
                    float(value)
                    for value in np.asarray(
                        fractions_by_zone[zone_key],
                        dtype=float,
                    ).reshape(-1)
                )
                for zone_key in zone_keys
                if str(zone_key).strip() != ""
            }
            if not normalized_fractions:
                continue

            support_id_by_property[property_name] = str(support_id)
            zone_fractions_by_property[property_name] = normalized_fractions

            if support_id_used is None:
                support_id_used = str(support_id)
                if not zone_fractions_by_key:
                    zone_fractions_by_key = normalized_fractions
            elif str(support_id) != support_id_used:
                mixed_support_ids = True
                if not bundle_has_labels:
                    zone_fractions_by_key = {}

            if property_name in base_property_arrays:
                continue
            if not zone_values:
                continue
            if not all(zone_key in zone_values for zone_key in normalized_fractions):
                continue
            weighted = np.zeros(
                max(1, int(getattr(solver_mesh, "n_cells", 1))),
                dtype=float,
            )
            for zone_key, fractions in normalized_fractions.items():
                weighted += np.asarray(fractions, dtype=float) * float(
                    zone_values[zone_key]
                )
            base_property_arrays[str(property_name)] = tuple(
                float(value) for value in weighted
            )

    if zone_fractions_by_key and not mixed_support_ids and lithology_labels is None:
        lithology_labels = labels_from_zone_fractions(zone_fractions_by_key)

    source = f"runtime_prepared_{selected_solver}"
    if bundle_has_labels:
        source += "_geology"
    elif zone_fractions_by_property or zone_fractions_by_key or lithology_labels is not None:
        source += "_zones"
    mesh_bundle_dir, mesh_path, mesh_summary_path = setup_mesh_paths_from_runtime(
        setup_state
    )
    return RuntimeHydraulicPropertySupport(
        n_cells=max(1, int(getattr(solver_mesh, "n_cells", 1))),
        lithology_labels=lithology_labels,
        base_property_arrays=base_property_arrays,
        zone_fractions_by_property=zone_fractions_by_property,
        zone_fractions_by_key=zone_fractions_by_key,
        base_property_values_by_key=base_property_values_by_key,
        support_id_by_property=support_id_by_property,
        source=source,
        mesh_bundle_dir=mesh_bundle_dir,
        mesh_path=mesh_path,
        mesh_summary_path=mesh_summary_path,
    )


__all__ = ["build_runtime_hydraulic_property_support"]
