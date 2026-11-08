"""Helpers for the ``BoussinesqFlowAdapter``.

The Boussinesq backend accepts either:

- one runtime planar cell mesh, its properties mapped from the profiles of the
  ``Model`` and its domain like the MODFLOW adapters do, or
- one ``CatchmentMeshBundle`` read from the folder of the ``exchange_mesh`` option,
  which carries its own properties per cell (the validation runtimes).

A bundle is never completed from the profiles of the ``Model``: a ``K`` or ``Sy``
profile next to a bundle is refused, and so is a property override, so one
property never has two silent sources. On a cell mesh the override wins over the
profile, for K and Sy, and the properties Boussinesq does not read are refused.
Keeping these helpers out of the adapter file makes the adapter symmetrical with
``solver/modflow6/adapter.py`` and ``solver/modflow_nwt``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

import numpy as np

from hydromodpy.core.exceptions import MeshError
from hydromodpy.mesh.io.bundle import CatchmentMeshBundle, load_catchment_mesh_bundle
from hydromodpy.model.model import Model
from hydromodpy.model.properties.property_table import (
    FLOW_PROPERTY_SPECS,
    require_positive_conductivity,
    require_positive_storage,
    resolve_flow_property_runtime_overrides,
    resolve_required_flow_properties,
)
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from hydromodpy.solver.boussinesq.options import BoussinesqOptions
from hydromodpy.solver.boussinesq.property_mapping import resolve_flow_property_arrays

_PARAMETER_ALIASES = {
    "K": ("K", "k"),
    "Sy": ("Sy", "SY", "sy", "S", "s"),
}


def _has_profile(profiles: Mapping[str, object], canonical_name: str) -> bool:
    """Tell whether one canonical property has a profile, under any of its aliases."""
    return any(alias in profiles for alias in _PARAMETER_ALIASES.get(canonical_name, ()))


def resolve_runtime_solver_mesh(model: Model) -> BoussinesqMesh | None:
    """Build one direct solver mesh from the cell mesh, domain and profiles of ``model``.

    ``None`` when the model has no cell mesh or domain, or lacks a profile the
    regime reads: the run then needs the mesh bundle of ``exchange_mesh``.
    """
    cell_mesh = model.geometry.cells
    domain = model.geometry.domain
    if cell_mesh is None or domain is None:
        return None

    profiles = model.properties.profiles
    required_properties = resolve_required_flow_properties(
        flow_regime=model.time.regime, storage=("Sy",)
    )
    if not all(_has_profile(profiles, name) for name in required_properties):
        return None

    property_arrays = resolve_flow_property_arrays(
        profiles=profiles,
        domain=domain,
        cell_mesh=cell_mesh,
        required_properties=required_properties,
        runtime_property_overrides=model.properties.overrides,
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
    require_positive_conductivity(conductivity, active_mask=active, profiles=profiles)
    require_positive_storage(
        storage,
        None,
        active_mask=active,
        iconvert=1,
        steady=["Sy" not in required_properties],
        profiles=profiles,
    )
    return BoussinesqMesh.from_cell_mesh(
        cell_mesh,
        domain=domain,
        hydraulic_conductivity_m_s=conductivity,
        storage_coefficient=storage,
    )


def _refuse_flow_properties_on_bundle(
    profiles: Mapping[str, object],
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
        if not _has_profile(profiles, canonical_name):
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
    model: Model,
    *,
    bundle: CatchmentMeshBundle,
) -> BoussinesqMesh:
    """Build one solver mesh from a bundle and the properties it carries."""
    regime = model.time.regime
    _refuse_property_overrides_on_bundle(model.properties.overrides, bundle=bundle)
    hydraulic_view = bundle.metadata_view.hydraulic_properties
    default_k = hydraulic_view.conductivity.default_value
    default_storage = hydraulic_view.storage_coefficient.default_value
    _refuse_flow_properties_on_bundle(
        model.properties.profiles,
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


def resolve_solver_mesh(
    model: Model, options: BoussinesqOptions
) -> tuple[BoussinesqMesh, CatchmentMeshBundle | None]:
    """Return the solver mesh of a run, and the mesh bundle it was read from or ``None``.

    The bundle of ``options.exchange_mesh`` stands in for the cell mesh and the
    properties of the ``Model`` when it is set. Without it the run builds its mesh
    from the cell mesh, the domain and the profiles of the ``Model``, and a model
    that has none of them is refused.
    """
    if options.exchange_mesh is not None:
        bundle = load_catchment_mesh_bundle(options.exchange_mesh)
        return resolve_bundle_solver_mesh(model, bundle=bundle), bundle
    mesh = resolve_runtime_solver_mesh(model)
    if mesh is None:
        raise MeshError(
            "flow/boussinesq needs either the planar cell mesh of the model, with its "
            "domain and the K and Sy profiles the regime reads, or the mesh bundle "
            "folder of [solver.boussinesq] exchange_mesh."
        )
    return mesh, None


__all__ = [
    "resolve_bundle_solver_mesh",
    "resolve_runtime_solver_mesh",
    "resolve_solver_mesh",
]
