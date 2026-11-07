"""Helpers for the ``BoussinesqFlowAdapter``.

The Boussinesq backend accepts either:

- one runtime planar cell mesh, its properties mapped from ``Flow``/``Domain``
  like the MODFLOW adapters do, or
- one ``CatchmentMeshBundle`` read from a bundle folder, which carries its own
  properties per cell (the validation runtimes).

A bundle is never completed from ``Flow`` parameters: a flow ``K`` or ``Sy`` next
to a bundle is refused, and so is a runtime property override, so
one property never has two silent sources. On a cell mesh the override wins over
the flow, for K and Sy, and the properties Boussinesq does not read are refused.
Keeping these helpers out of the adapter file makes the adapter symmetrical with
``solver/modflow6/adapters/flow.py`` and ``solver/modflow_nwt``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import numpy as np

from hydromodpy.model.properties.property_table import (
    FLOW_PROPERTY_SPECS,
    require_positive_conductivity,
    require_positive_storage,
    resolve_flow_property_runtime_overrides,
    resolve_required_flow_properties,
)
from hydromodpy.model.time.regime import normalize_flow_regime
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from hydromodpy.solver.boussinesq.property_mapping import resolve_flow_property_arrays
from hydromodpy.spatial.mesh.io.bundle import (
    CatchmentMeshBundle,
    load_catchment_mesh_bundle,
)


def resolve_mesh_bundle(setup_state: object) -> CatchmentMeshBundle:
    """Return the catchment mesh bundle attached to the run setup."""
    preloaded = getattr(setup_state, "mesh_bundle", None)
    if preloaded is not None:
        return preloaded

    mesh_summary = getattr(setup_state, "mesh_summary", None)
    if isinstance(mesh_summary, dict):
        bundle_dir = str(mesh_summary.get("output_exchange_bundle_dir", "")).strip()
        if bundle_dir != "":
            bundle = load_catchment_mesh_bundle(bundle_dir)
            setup_state.mesh_bundle = bundle
            return bundle

    raise ValueError(
        "flow/boussinesq requires either a runtime planar mesh with Flow/Domain "
        "property mapping support, or one CatchmentMeshBundle read from a bundle "
        "folder. Provide state.setup.cell_mesh or state.setup.mesh_bundle, "
        "or set output_exchange_bundle_dir in state.setup.mesh_summary."
    )


def _has_required_flow_parameters(*, flow: object, required_properties: frozenset[str]) -> bool:
    """Tell whether the Flow runtime already exposes the direct-mapping properties."""
    parameters = getattr(flow, "parameters", {})
    if not isinstance(parameters, dict):
        return False

    alias_map = {
        "K": ("K", "k"),
        "Sy": ("Sy", "SY", "sy", "S", "s"),
    }
    for canonical_name in required_properties:
        aliases = alias_map.get(canonical_name, ())
        if not any(alias in parameters for alias in aliases):
            return False
    return True


def _has_any_flow_parameter(*, flow: object, canonical_name: str) -> bool:
    """Tell whether one canonical flow parameter alias is available."""
    alias_map = {
        "K": ("K", "k"),
        "Sy": ("Sy", "SY", "sy", "S", "s"),
    }
    parameters = getattr(flow, "parameters", {})
    if not isinstance(parameters, dict):
        return False
    aliases = alias_map.get(str(canonical_name).strip(), ())
    return any(alias in parameters for alias in aliases)


def resolve_runtime_solver_mesh(setup_state: object) -> BoussinesqMesh | None:
    """Build one direct solver mesh from runtime mesh + Flow/Domain mapping."""
    cell_mesh = getattr(setup_state, "cell_mesh", None)
    if cell_mesh is None:
        return None

    flow = getattr(setup_state, "flow", None)
    domain = getattr(setup_state, "domain", None)
    if flow is None or domain is None:
        return None

    required_properties = resolve_required_flow_properties(
        flow_regime=str(getattr(flow, "flow_regime", "transient")), storage=("Sy",)
    )
    if not _has_required_flow_parameters(
        flow=flow,
        required_properties=required_properties,
    ):
        return None

    property_arrays = resolve_flow_property_arrays(
        flow=flow,
        domain=domain,
        cell_mesh=cell_mesh,
        required_properties=required_properties,
        runtime_property_overrides=getattr(setup_state, "flow_runtime_overrides", None),
    )
    conductivity = np.asarray(
        property_arrays["hydraulic_conductivity_m_s"],
        dtype=float,
    )
    storage = np.asarray(
        property_arrays.get(
            "storage_coefficient",
            np.zeros(cell_mesh.n_cells, dtype=float),
        ),
        dtype=float,
    )
    # One convertible layer, every cell active. Every regime reads K, only a
    # transient run requires and reads Sy.
    active = np.ones(conductivity.size, dtype=bool)
    require_positive_conductivity(conductivity, active_mask=active, flow=flow)
    require_positive_storage(
        storage,
        None,
        active_mask=active,
        iconvert=1,
        steady=["Sy" not in required_properties],
        flow=flow,
    )
    mesh_summary = getattr(setup_state, "mesh_summary", None)
    output_mesh = (
        str(mesh_summary.get("output_mesh", "")).strip() if isinstance(mesh_summary, dict) else ""
    )
    return BoussinesqMesh.from_cell_mesh(
        cell_mesh,
        domain=domain,
        hydraulic_conductivity_m_s=conductivity,
        storage_coefficient=storage,
        source_path=Path(output_mesh).expanduser() if output_mesh != "" else None,
    )


def _refuse_flow_properties_on_bundle(
    flow: object,
    *,
    bundle: CatchmentMeshBundle,
    bundle_carries: dict[str, bool],
) -> None:
    """Refuse a flow K or Sy on a run whose cells come from a mesh bundle.

    A bundle carries its properties per cell (or as a metadata default). A flow
    parameter next to it would either overwrite them in silence or be ignored in
    silence; it is neither. A flow parameter is mapped on a cell mesh only.
    """
    labels = {"K": "hydraulic_conductivity_m_s", "Sy": "storage_coefficient"}
    for canonical_name, column in labels.items():
        if flow is None or not _has_any_flow_parameter(flow=flow, canonical_name=canonical_name):
            continue
        source = f"the mesh bundle {bundle.bundle_dir}"
        if bundle_carries[canonical_name]:
            raise ValueError(
                f"Two sources set {canonical_name} for flow/boussinesq: {source} carries "
                f"'{column}' (per cell or as a metadata default) and [flow.param."
                f"{canonical_name}] sets it too. Keep one: drop the flow parameter, or "
                "drop the bundle values."
            )
        raise ValueError(
            f"[flow.param.{canonical_name}] cannot be mapped on {source}: a bundle run "
            f"reads '{column}' from the bundle. Write the values in the bundle, or run "
            "on a cell mesh (state.setup.cell_mesh)."
        )


def _refuse_property_overrides_on_bundle(overrides: object, *, bundle: CatchmentMeshBundle) -> None:
    """Refuse a runtime property override on a run whose cells come from a bundle.

    The bundle carries its properties per cell, and an override would be
    dropped in silence.
    """
    resolved = resolve_flow_property_runtime_overrides(
        overrides if isinstance(overrides, Mapping) else None,
        nlay=1,
        n_cells=len(bundle.cells),
    )
    named = [canonical for canonical, _, name, _ in FLOW_PROPERTY_SPECS if name in resolved]
    if named:
        raise ValueError(
            f"A runtime override sets {', '.join(named)} on the mesh bundle "
            f"{bundle.bundle_dir}, which carries its properties per cell and reads no "
            "override. Write the values in the bundle, or run on a cell mesh "
            "(state.setup.cell_mesh)."
        )


def resolve_bundle_solver_mesh(
    setup_state: object,
    *,
    bundle: CatchmentMeshBundle,
) -> BoussinesqMesh:
    """Build one solver mesh from a bundle and the properties it carries."""
    flow = getattr(setup_state, "flow", None)
    regime = normalize_flow_regime(getattr(flow, "flow_regime", "transient"))
    _refuse_property_overrides_on_bundle(
        getattr(setup_state, "flow_runtime_overrides", None), bundle=bundle
    )
    hydraulic_view = bundle.metadata_view.hydraulic_properties
    default_k = hydraulic_view.conductivity.default_value
    default_storage = hydraulic_view.storage_coefficient.default_value
    _refuse_flow_properties_on_bundle(
        flow,
        bundle=bundle,
        bundle_carries={
            "K": default_k is not None
            or any(cell.hydraulic_conductivity_m_s is not None for cell in bundle.cells),
            "Sy": default_storage is not None
            or any(cell.storage_coefficient is not None for cell in bundle.cells),
        },
    )

    completed_cells = []
    for bundle_cell in bundle.cells:
        conductivity = bundle_cell.hydraulic_conductivity_m_s
        if conductivity is None:
            if default_k is None:
                raise ValueError(
                    "Boussinesq requires hydraulic_conductivity_m_s for every cell; "
                    f"cannot complete missing value on cell_id={int(bundle_cell.cell_id)}."
                )
            conductivity = default_k

        storage = bundle_cell.storage_coefficient
        if storage is None:
            if default_storage is not None:
                storage = default_storage
            elif regime == "steady":
                storage = 0.0
            else:
                raise ValueError(
                    "Boussinesq requires storage_coefficient for every cell; "
                    "provide one bundle default or per-cell bundle values. Missing "
                    f"value on cell_id={int(bundle_cell.cell_id)}."
                )

        completed_cells.append(
            replace(
                bundle_cell,
                hydraulic_conductivity_m_s=float(conductivity),
                storage_coefficient=float(storage),
            )
        )

    completed_bundle = replace(bundle, cells=tuple(completed_cells))
    return BoussinesqMesh.from_bundle(completed_bundle)


__all__ = [
    "resolve_bundle_solver_mesh",
    "resolve_mesh_bundle",
    "resolve_runtime_solver_mesh",
]
