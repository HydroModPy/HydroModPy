"""Forcing and boundary-resolution helpers for the Boussinesq solver."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Real
from typing import Any, Callable

import numpy as np

from hydromodpy.core.units.volumetric_flow import (
    convert_to_m3_per_s,
    normalize_m3_per_s_unit,
)
from hydromodpy.process.flow.initial_conditions import FlowInitialConditions
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from hydromodpy.solver.utils.mesh.gmsh_grid import load_planar_mesh
from hydromodpy.solver.utils.mesh.gmsh_grid.catchment_mesh_bundle_reader import (
    CatchmentMeshBundle,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.planar_forcing_discretization import (
    discretize_fields_on_planar_mesh,
    discretize_points_on_planar_mesh,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.runtime_support import (
    GmshSupportMetadata,
    build_gmsh_support_metadata,
)


@dataclass(frozen=True)
class ResolvedDirichletSupport:
    """One resolved Dirichlet support over cells and/or edges.

    The canonical semantics is cell-based because that is the active solve
    representation. The edge support is retained because diagnostics and
    regression helpers still need an edge-oriented projection.
    """

    label: str
    edge_indices: np.ndarray
    cell_indices: np.ndarray
    head_value_m: float


@dataclass(frozen=True)
class BoussinesqForcingResolver:
    """Resolve process-level forcing payloads to Boussinesq runtime arrays."""

    mesh: BoussinesqMesh
    flow: object
    time_grid: object
    mesh_bundle: CatchmentMeshBundle | None = None
    planar_mesh_loader: Callable[[Any], object] = load_planar_mesh
    support_metadata: GmshSupportMetadata | None = None

    def resolve_initial_head_field(self) -> np.ndarray:
        """Resolve the canonical `Flow` initial condition into cell heads."""
        initial_conditions = getattr(self.flow, "initial_conditions", None)
        if not isinstance(initial_conditions, FlowInitialConditions):
            raise TypeError(
                "Boussinesq expects flow.initial_conditions to be one "
                "FlowInitialConditions instance."
            )

        head_ic = initial_conditions.h
        ic_type = str(head_ic.type).strip().lower()
        if ic_type == "top":
            return np.asarray(self.mesh.z_top_m, dtype=float)
        if ic_type == "bottom":
            return np.asarray(self.mesh.z_bottom_m, dtype=float)
        if ic_type == "custom":
            if head_ic.value is None:
                raise ValueError("flow.ic.value is required when flow.ic.type='custom'.")
            return np.full(self.mesh.n_cells, float(head_ic.value), dtype=float)
        raise ValueError(f"Unsupported flow.ic.type for boussinesq: '{head_ic.type}'.")

    def resolve_recharge_series(self, nper: int) -> tuple[float | np.ndarray, ...]:
        """Resolve one recharge payload per stress period."""
        active = tuple(getattr(self.flow, "active_sinks_sources", ()) or ())
        if "recharge" not in active:
            return tuple(0.0 for _ in range(int(nper)))

        recharge_cfg = self.recharge_config()
        if recharge_cfg is None:
            return tuple(0.0 for _ in range(int(nper)))

        heterogeneous_source = getattr(recharge_cfg, "heterogeneous_source", None)
        if heterogeneous_source is not None:
            return self.resolve_heterogeneous_recharge_series(
                heterogeneous_source=heterogeneous_source,
                nper=nper,
                first_clim=getattr(recharge_cfg, "first_clim", "mean"),
                interpolation_method=getattr(
                    recharge_cfg,
                    "interpolation_method",
                    "nearest",
                ),
            )

        series = self.recharge_period_series(
            payload=getattr(recharge_cfg, "values", 0.0),
            nper=int(nper),
            first_clim=getattr(recharge_cfg, "first_clim", "mean"),
            label="flow.sinks_sources.recharge.values",
        )
        return tuple(float(value) for value in np.asarray(series, dtype=float).tolist())

    def resolve_heterogeneous_recharge_series(
        self,
        *,
        heterogeneous_source: object,
        nper: int,
        first_clim: object,
        interpolation_method: str,
    ) -> tuple[np.ndarray, ...]:
        """Discretize heterogeneous recharge onto the current Gmsh cell set."""
        solver_mesh = self.planar_mesh_for_forcing()
        simulation_window = (
            getattr(self.time_grid, "window", None) if self.time_grid is not None else None
        )
        if getattr(heterogeneous_source, "has_fields", False):
            raw_arrays = discretize_fields_on_planar_mesh(
                load_result=heterogeneous_source,
                planar_mesh=solver_mesh,
                nper=int(nper),
                simulation_window=simulation_window,
                method=str(interpolation_method),
            )
        elif getattr(heterogeneous_source, "has_points", False):
            raw_arrays = discretize_points_on_planar_mesh(
                load_result=heterogeneous_source,
                planar_mesh=solver_mesh,
                nper=int(nper),
                simulation_window=simulation_window,
                method=str(interpolation_method),
            )
        else:
            raw_arrays = {
                int(kper): np.zeros(self.mesh.n_cells, dtype=float)
                for kper in range(int(nper))
            }

        return self.apply_first_clim_to_cellwise_recharge(
            raw_arrays=raw_arrays,
            nper=int(nper),
            first_clim=first_clim,
        )

    def planar_mesh_for_forcing(self):
        """Return the planar mesh used to discretize spatial forcings."""
        planar_mesh = getattr(self.mesh, "planar_mesh", None)
        if planar_mesh is not None:
            return planar_mesh
        if self.mesh_bundle is None:
            raise RuntimeError(
                "Spatial forcings require either one runtime planar mesh or one "
                "mesh bundle exposing mesh_path."
            )
        return self.planar_mesh_loader(self.mesh_bundle.mesh_path)

    def apply_first_clim_to_cellwise_recharge(
        self,
        *,
        raw_arrays: Mapping[int, np.ndarray],
        nper: int,
        first_clim: object,
    ) -> tuple[np.ndarray, ...]:
        """Apply the historical `first_clim` convention to cellwise recharge."""
        if nper <= 0:
            return ()

        arrays = {
            int(kper): np.asarray(values, dtype=float).reshape(-1)
            for kper, values in raw_arrays.items()
        }
        if not arrays:
            return tuple(np.zeros(self.mesh.n_cells, dtype=float) for _ in range(nper))

        stacked = np.stack(tuple(arrays.values()), axis=0)
        flow_regime = str(getattr(self.flow, "flow_regime", "transient")).strip().lower()
        if flow_regime == "steady" or nper <= 1:
            mean_array = np.nanmean(stacked, axis=0)
            return (np.asarray(mean_array, dtype=float).reshape(-1),)

        result = {
            kper: arrays.get(kper, np.zeros(self.mesh.n_cells, dtype=float)).copy()
            for kper in range(nper)
        }
        if first_clim == "mean":
            result[0] = np.nanmean(stacked, axis=0)
        elif first_clim == "first":
            pass
        elif self.is_scalar_number(first_clim):
            result[0] = np.full(self.mesh.n_cells, float(first_clim), dtype=float)
        else:
            raise ValueError(
                "flow.sinks_sources.recharge.first_clim must be 'mean', 'first', "
                "or a numeric value."
            )
        return tuple(
            np.asarray(result[kper], dtype=float).reshape(-1).copy()
            for kper in range(nper)
        )

    def resolve_well_flux_by_period(self, nper: int) -> np.ndarray:
        """Resolve all localized well fluxes to one cell vector per period."""
        active = tuple(getattr(self.flow, "active_sinks_sources", ()) or ())
        if "wells" not in active:
            return np.zeros((nper, self.mesh.n_cells), dtype=float)

        sinks_sources = getattr(self.flow, "sinks_sources", {})
        wells = sinks_sources.get("wells", {}) if isinstance(sinks_sources, Mapping) else {}
        if not isinstance(wells, Mapping) or not wells:
            return np.zeros((nper, self.mesh.n_cells), dtype=float)

        by_period = np.zeros((nper, self.mesh.n_cells), dtype=float)
        for well_id, well_cfg in wells.items():
            cell_index = self.resolve_well_cell_index(str(well_id), well_cfg)
            flux_series = self.resolve_well_flux_series(str(well_id), well_cfg, nper)
            by_period[:, cell_index] += flux_series
        return by_period

    def runtime_mesh_support(self) -> GmshSupportMetadata | None:
        """Return runtime support metadata when available."""
        if self.support_metadata is not None:
            return self.support_metadata
        if self.mesh_bundle is not None:
            return build_gmsh_support_metadata(self.mesh_bundle)
        return None

    def require_runtime_mesh_support(self, *, label: str) -> GmshSupportMetadata:
        """Return runtime support metadata or raise a clear support-resolution error."""
        support = self.runtime_mesh_support()
        if support is None:
            raise ValueError(
                f"{label} requires runtime gmsh support metadata but mesh support is unavailable."
            )
        return support

    @staticmethod
    def boundary_attr(boundary: object, field_name: str, default=None):
        """Read one field from either a mapping payload or a typed BC object."""
        if isinstance(boundary, Mapping):
            return boundary.get(field_name, default)
        return getattr(boundary, field_name, default)

    def boundary_support_label(self, boundary: object) -> str | None:
        """Return one normalized explicit support label when configured."""
        raw_value = self.boundary_attr(boundary, "support_label", None)
        if raw_value is None:
            return None
        label = str(raw_value).strip()
        return None if label == "" else label

    def resolve_labelled_support(
        self,
        *,
        boundary: object,
        bc_id: str,
    ) -> tuple[str, np.ndarray, np.ndarray] | None:
        """Resolve one explicit support label to edge and cell indices."""
        support_label = self.boundary_support_label(boundary)
        if support_label is None:
            return None
        support = self.require_runtime_mesh_support(label=f"flow.bc.{bc_id}")
        edge_indices = np.asarray(
            support.edge_indices_for_label(support_label),
            dtype=int,
        ).reshape(-1)
        cell_indices = np.asarray(
            support.cell_indices_for_label(support_label),
            dtype=int,
        ).reshape(-1)
        if edge_indices.size == 0 or cell_indices.size == 0:
            raise ValueError(
                f"flow.bc.{bc_id}.support_label='{support_label}' did not match any runtime mesh support."
            )
        return (f"flow.bc.{bc_id} [{support_label}]", edge_indices, cell_indices)

    def resolve_side_dirichlet_support(
        self,
        *,
        boundary: object,
        bc_id: str,
    ) -> tuple[str, np.ndarray, np.ndarray]:
        """Resolve one side-Dirichlet support with optional explicit label."""
        labelled_support = self.resolve_labelled_support(boundary=boundary, bc_id=bc_id)
        if labelled_support is not None:
            return labelled_support

        edge_indices = self.mesh.boundary_edge_indices_for_side(bc_id)
        if edge_indices.size == 0:
            raise ValueError(
                f"Boundary '{bc_id}' is active but no matching boundary edge was found."
            )
        cell_indices = self.mesh.boundary_cell_indices_for_side(bc_id)
        if cell_indices.size == 0:
            raise ValueError(
                f"Boundary '{bc_id}' is active but no matching boundary cell was found."
            )
        return (f"flow.bc.{bc_id}", edge_indices, cell_indices)

    def resolve_stream_dirichlet_support(
        self,
        *,
        boundary: object,
    ) -> tuple[str, np.ndarray, np.ndarray]:
        """Resolve the stream support with optional explicit support label."""
        labelled_support = self.resolve_labelled_support(boundary=boundary, bc_id="stream")
        if labelled_support is not None:
            return labelled_support

        support = self.runtime_mesh_support()
        if support is not None:
            edge_indices = np.asarray(support.river_edge_indices(), dtype=int).reshape(-1)
            cell_indices = np.asarray(support.river_cell_indices(), dtype=int).reshape(-1)
        else:
            edge_indices = self.mesh.river_edge_indices()
            cell_indices = self.mesh.river_cell_indices()
        if edge_indices.size == 0:
            raise ValueError(
                "Boundary 'stream' is active but no edge is tagged is_river in the mesh bundle."
            )
        if cell_indices.size == 0:
            raise ValueError(
                "Boundary 'stream' is active but no cell is tagged by river support in the mesh bundle."
            )
        return ("flow.bc.stream", edge_indices, cell_indices)

    def project_dirichlet_supports_to_edges(
        self,
        supports: tuple[ResolvedDirichletSupport, ...] | list[ResolvedDirichletSupport],
    ) -> np.ndarray:
        """Project one resolved support set to the edge-aligned support view."""
        edge_values = np.full(self.mesh.n_edges, np.nan, dtype=float)
        for support in supports:
            self.assign_boundary_head_edges(
                edge_values,
                edge_indices=support.edge_indices,
                head_value_m=support.head_value_m,
                label=support.label,
            )
        return edge_values

    def project_dirichlet_supports_to_cells(
        self,
        supports: tuple[ResolvedDirichletSupport, ...] | list[ResolvedDirichletSupport],
    ) -> np.ndarray:
        """Project one resolved support set to the canonical cell-aligned view."""
        cell_values = np.full(self.mesh.n_cells, np.nan, dtype=float)
        for support in supports:
            self.assign_prescribed_head_cells(
                cell_values,
                cell_indices=support.cell_indices,
                head_value_m=support.head_value_m,
                label=support.label,
            )
        return cell_values

    def resolved_dirichlet_supports_by_period(
        self,
        nper: int,
        *,
        ocean_series_m: np.ndarray | None = None,
    ) -> tuple[tuple[ResolvedDirichletSupport, ...], ...]:
        """Resolve all Dirichlet supports once, then reuse them across projections."""
        supports_by_period: list[list[ResolvedDirichletSupport]] = [
            [] for _ in range(int(nper))
        ]
        boundary_conditions = self.boundary_conditions_mapping()

        def append_support(
            *,
            label: str,
            edge_indices: np.ndarray,
            cell_indices: np.ndarray,
            series: np.ndarray,
        ) -> None:
            for kper, head_value in enumerate(np.asarray(series, dtype=float).tolist()):
                supports_by_period[kper].append(
                    ResolvedDirichletSupport(
                        label,
                        np.asarray(edge_indices, dtype=int).copy(),
                        np.asarray(cell_indices, dtype=int).copy(),
                        float(head_value),
                    )
                )

        for bc_id in ("west_side", "east_side", "south_side", "north_side"):
            if not self.is_bc_active(bc_id):
                continue
            boundary = self.require_active_dirichlet_boundary(
                boundary_conditions=boundary_conditions,
                bc_id=bc_id,
            )
            label, edge_indices, cell_indices = self.resolve_side_dirichlet_support(
                boundary=boundary,
                bc_id=bc_id,
            )
            append_support(
                label=label,
                edge_indices=edge_indices,
                cell_indices=cell_indices,
                series=self.boundary_value_series(
                    boundary=boundary,
                    bc_id=bc_id,
                    nper=nper,
                ),
            )

        if self.is_bc_active("stream"):
            boundary = self.require_active_dirichlet_boundary(
                boundary_conditions=boundary_conditions,
                bc_id="stream",
            )
            label, edge_indices, cell_indices = self.resolve_stream_dirichlet_support(
                boundary=boundary,
            )
            append_support(
                label=label,
                edge_indices=edge_indices,
                cell_indices=cell_indices,
                series=self.boundary_value_series(
                    boundary=boundary,
                    bc_id="stream",
                    nper=nper,
                ),
            )

        if ocean_series_m is not None and np.asarray(ocean_series_m, dtype=float).size > 0:
            for kper, head_value in enumerate(np.asarray(ocean_series_m, dtype=float).tolist()):
                supports_by_period[kper].append(
                    ResolvedDirichletSupport(
                        "flow.bc.ocean",
                        self.ocean_support_edge_indices(float(head_value)),
                        np.flatnonzero(
                            self.ocean_supported_cell_mask(float(head_value))
                        ).astype(int, copy=False),
                        float(head_value),
                    )
                )

        return tuple(tuple(period_supports) for period_supports in supports_by_period)

    @staticmethod
    def require_active_dirichlet_boundary(
        *,
        boundary_conditions: Mapping[str, object],
        bc_id: str,
    ) -> object:
        """Return one active boundary object after validating Dirichlet semantics."""
        boundary = boundary_conditions.get(bc_id)
        if boundary is None:
            raise ValueError(f"Active boundary '{bc_id}' is missing from flow.bc.")
        boundary_type = str(getattr(boundary, "type", "dirichlet")).strip().lower()
        if boundary_type != "dirichlet":
            raise ValueError(
                f"Boundary '{bc_id}' must be Dirichlet for the current "
                "boussinesq backend slice."
            )
        return boundary

    def resolve_ocean_series(self, nper: int) -> np.ndarray | None:
        """Resolve the ocean stage series when the ocean boundary is active."""
        if not self.is_bc_active("ocean"):
            return None
        boundary = self.boundary_conditions_mapping().get("ocean")
        if boundary is None:
            raise ValueError("Active boundary 'ocean' is missing from flow.bc.")
        boundary_type = str(getattr(boundary, "type", "dirichlet")).strip().lower()
        if boundary_type != "dirichlet":
            raise ValueError(
                "Boundary 'ocean' must be Dirichlet for the current "
                "boussinesq backend slice."
            )
        return self.boundary_value_series(boundary=boundary, bc_id="ocean", nper=nper)

    def ocean_support_edge_indices(
        self,
        ocean_stage_m: float | np.ndarray | None,
    ) -> np.ndarray:
        """Return boundary edges influenced by the current ocean stage."""
        if ocean_stage_m is None or np.asarray(ocean_stage_m, dtype=float).size == 0:
            return np.asarray([], dtype=int)
        sea_threshold_m = float(np.max(np.asarray(ocean_stage_m, dtype=float)))
        boundary_mask = np.asarray(self.mesh.boundary_edge_mask, dtype=bool)
        non_river_mask = ~np.asarray(self.mesh.edge_is_river, dtype=bool)
        owner_cell_indices = np.asarray(self.mesh.edge_cell_a, dtype=int)
        coastal_mask = self.mesh.z_top_m[owner_cell_indices] <= sea_threshold_m
        return np.flatnonzero(boundary_mask & non_river_mask & coastal_mask).astype(
            int,
            copy=False,
        )

    def ocean_supported_cell_mask(
        self,
        ocean_stage_m: float | np.ndarray | None,
    ) -> np.ndarray:
        """Return one boolean mask marking ocean-influenced cells."""
        mask = np.zeros(self.mesh.n_cells, dtype=bool)
        for edge_index in self.ocean_support_edge_indices(ocean_stage_m).tolist():
            mask[int(self.mesh.edge_cell_a[edge_index])] = True
        return mask

    def ocean_supported_cell_masks_by_period(
        self,
        ocean_series_m: np.ndarray | None,
        *,
        nper: int,
    ) -> tuple[np.ndarray, ...]:
        """Return one ocean support mask per stress period."""
        if ocean_series_m is None or np.asarray(ocean_series_m, dtype=float).size == 0:
            return tuple(np.zeros(self.mesh.n_cells, dtype=bool) for _ in range(int(nper)))
        series = np.asarray(ocean_series_m, dtype=float).reshape(-1)
        if series.size != int(nper):
            raise ValueError(
                "ocean_series_m length must match nper when building support masks."
            )
        return tuple(
            self.ocean_supported_cell_mask(float(head_value))
            for head_value in series.tolist()
        )

    def resolve_drainage_conductance_series(self, nper: int) -> np.ndarray:
        """Return one drainage conductance value per period."""
        if not self.is_bc_active("drainage"):
            return np.zeros(nper, dtype=float)
        boundary = self.boundary_conditions_mapping().get("drainage")
        if boundary is None:
            raise ValueError("Active boundary 'drainage' is missing from flow.bc.")
        boundary_type = str(getattr(boundary, "type", "cauchy")).strip().lower()
        if boundary_type not in {"cauchy", "robin"}:
            raise ValueError(
                "Boundary 'drainage' must be of type cauchy/robin for the "
                "current boussinesq backend slice."
            )
        return self.simple_period_series(
            getattr(boundary, "value", None),
            nper=nper,
            label="flow.bc.drainage.value",
        )

    def resolve_well_cell_index(self, well_id: str, well_cfg: object) -> int:
        """Project one well location to one cell of the triangular mesh."""
        layer = getattr(well_cfg, "layer", 0)
        if layer is not None and int(layer) != 0:
            raise NotImplementedError(
                f"Well '{well_id}' targets layer={int(layer)} but the current "
                "boussinesq backend is 2D and supports only layer 0."
            )

        cell_payload = getattr(well_cfg, "cell", None)
        location_mode = str(getattr(well_cfg, "location_mode", "") or "").strip().lower()
        if cell_payload is not None or location_mode in {"", "cell"}:
            raise NotImplementedError(
                f"Well '{well_id}' uses structured-grid cell addressing. "
                "The current boussinesq backend on gmsh triangles supports "
                "only coordinate-based wells (absolute_xy or relative_xy)."
            )
        if location_mode == "absolute_xy":
            x_m = float(getattr(well_cfg, "x"))
            y_m = float(getattr(well_cfg, "y"))
        elif location_mode == "relative_xy":
            x_rel = float(getattr(well_cfg, "x_rel"))
            y_rel = float(getattr(well_cfg, "y_rel"))
            x_m = self.mesh.x_min_m + x_rel * (self.mesh.x_max_m - self.mesh.x_min_m)
            y_m = self.mesh.y_min_m + y_rel * (self.mesh.y_max_m - self.mesh.y_min_m)
        else:
            raise ValueError(
                f"Unsupported well location mode for '{well_id}': {location_mode!r}."
            )
        return self.mesh.locate_cell_index_for_point(x_m, y_m, allow_nearest=True)

    def resolve_well_flux_series(
        self,
        well_id: str,
        well_cfg: object,
        nper: int,
    ) -> np.ndarray:
        """Resolve one well rate to one value per period in m3/s."""
        forcing = getattr(well_cfg, "forcing", None)
        if forcing is not None:
            from hydromodpy.process.flow.time_forcing import (
                resolve_period_values_from_forcing,
            )

            raw_values = resolve_period_values_from_forcing(
                forcing=forcing,
                simulation_window=getattr(self.time_grid, "window", None)
                if self.time_grid is not None
                else None,
                nper=int(nper),
                label=f"flow.sinks_sources.wells.{well_id}.forcing",
            )
            raw_units = getattr(forcing, "units", None) or getattr(well_cfg, "units", "m3/s")
            canonical_units = normalize_m3_per_s_unit(str(raw_units))
            return np.asarray(
                [
                    convert_to_m3_per_s(
                        value,
                        unit=canonical_units,
                        label=f"flow.sinks_sources.wells.{well_id}.forcing[{idx}]",
                    )
                    for idx, value in enumerate(raw_values)
                ],
                dtype=float,
            )
        return self.simple_period_series(
            getattr(well_cfg, "flux", None),
            nper=nper,
            label=f"flow.sinks_sources.wells.{well_id}.flux",
        )

    @staticmethod
    def assign_prescribed_head_cells(
        cell_values_m: np.ndarray,
        *,
        cell_indices: np.ndarray,
        head_value_m: float,
        label: str,
    ) -> None:
        """Assign one prescribed head to a set of cells with overlap checks."""
        candidate = float(head_value_m)
        for cell_index in np.asarray(cell_indices, dtype=int).tolist():
            previous = float(cell_values_m[cell_index])
            if np.isfinite(previous) and not np.isclose(previous, candidate, rtol=0.0, atol=1.0e-12):
                raise ValueError(
                    f"{label} overlaps another prescribed-head BC on cell {cell_index} "
                    f"with conflicting values ({previous} vs {candidate})."
                )
            cell_values_m[cell_index] = candidate

    @staticmethod
    def assign_boundary_head_edges(
        edge_values_m: np.ndarray,
        *,
        edge_indices: np.ndarray,
        head_value_m: float,
        label: str,
    ) -> None:
        """Assign one boundary head to a set of supported edges with overlap checks."""
        candidate = float(head_value_m)
        for edge_index in np.asarray(edge_indices, dtype=int).tolist():
            previous = float(edge_values_m[edge_index])
            if np.isfinite(previous) and not np.isclose(previous, candidate, rtol=0.0, atol=1.0e-12):
                raise ValueError(
                    f"{label} overlaps another boundary-head support on edge {edge_index} "
                    f"with conflicting values ({previous} vs {candidate})."
                )
            edge_values_m[edge_index] = candidate

    def boundary_value_series(
        self,
        *,
        boundary: object,
        bc_id: str,
        nper: int,
    ) -> np.ndarray:
        """Resolve one boundary condition to one head value per period."""
        forcing = getattr(boundary, "forcing", None)
        if forcing is not None:
            from hydromodpy.process.flow.time_forcing import (
                resolve_period_values_from_forcing,
            )

            return np.asarray(
                resolve_period_values_from_forcing(
                    forcing=forcing,
                    simulation_window=getattr(self.time_grid, "window", None)
                    if self.time_grid is not None
                    else None,
                    nper=int(nper),
                    label=f"flow.bc.{bc_id}.forcing",
                ),
                dtype=float,
            )
        return self.simple_period_series(
            getattr(boundary, "value", None),
            nper=nper,
            label=f"flow.bc.{bc_id}.value",
        )

    def recharge_period_series(
        self,
        *,
        payload: object,
        nper: int,
        first_clim: object,
        label: str,
    ) -> np.ndarray:
        """Resolve the canonical recharge payload to one value per period."""
        if nper <= 0:
            return np.asarray([], dtype=float)
        if payload is None:
            return np.zeros(nper, dtype=float)
        if isinstance(payload, Mapping):
            series = np.zeros(nper, dtype=float)
            for raw_key, raw_value in payload.items():
                if isinstance(raw_key, bool) or not isinstance(raw_key, Real):
                    raise TypeError(f"{label} mapping keys must be integer period indices.")
                kper = int(raw_key)
                if float(raw_key) != float(kper):
                    raise TypeError(f"{label} mapping keys must be integer period indices.")
                if kper < 0 or kper >= int(nper):
                    raise ValueError(
                        f"{label} mapping key {kper} is outside [0, {int(nper) - 1}]."
                    )
                series[kper] = float(raw_value)
            return series
        if self.is_scalar_number(payload):
            return np.full(nper, float(payload), dtype=float)

        sequence = self.payload_to_sequence(payload, label=label)
        if sequence.size == 1:
            return np.full(nper, float(sequence[0]), dtype=float)
        if sequence.size < int(nper):
            raise ValueError(
                f"{label} length ({int(sequence.size)}) must be 1 or at least nper ({int(nper)})."
            )

        series = np.zeros(nper, dtype=float)
        if first_clim == "mean":
            series[0] = float(np.nanmean(sequence))
        elif first_clim == "first":
            series[0] = float(sequence[0])
        elif self.is_scalar_number(first_clim):
            series[0] = float(first_clim)
        else:
            raise ValueError(
                "flow.sinks_sources.recharge.first_clim must be 'mean', 'first', "
                "or a numeric value."
            )
        for kper in range(1, int(nper)):
            series[kper] = float(sequence[kper])
        return series

    @staticmethod
    def simple_period_series(
        payload: object,
        *,
        nper: int,
        label: str,
    ) -> np.ndarray:
        """Resolve one scalar or explicit period sequence to length `nper`."""
        if nper <= 0:
            return np.asarray([], dtype=float)
        if payload is None:
            raise ValueError(f"{label} is required.")
        if BoussinesqForcingResolver.is_scalar_number(payload):
            return np.full(nper, float(payload), dtype=float)
        sequence = BoussinesqForcingResolver.payload_to_sequence(payload, label=label)
        if sequence.size == 1:
            return np.full(nper, float(sequence[0]), dtype=float)
        if sequence.size != int(nper):
            raise ValueError(
                f"{label} length ({int(sequence.size)}) must be 1 or match nper ({int(nper)})."
            )
        return sequence.astype(float, copy=False)

    @staticmethod
    def payload_to_sequence(
        payload: object,
        *,
        label: str,
    ) -> np.ndarray:
        """Convert one runtime payload to a flat numeric sequence."""
        if hasattr(payload, "iloc"):
            size = len(payload)
            values = [payload.iloc[idx] for idx in range(size)]
            return np.asarray(values, dtype=float).reshape(-1)
        try:
            array = np.asarray(payload, dtype=float).reshape(-1)
        except Exception as exc:
            raise TypeError(
                f"{label} must be numeric or a sequence of numeric values."
            ) from exc
        if array.size == 0:
            raise ValueError(f"{label} cannot be empty.")
        return array.astype(float, copy=False)

    @staticmethod
    def is_scalar_number(value: object) -> bool:
        """Return true for numeric scalars while excluding booleans."""
        return isinstance(value, Real) and not isinstance(value, bool)

    @staticmethod
    def has_active_recharge_payload(
        payloads_by_period: tuple[float | np.ndarray, ...],
    ) -> bool:
        """Return whether at least one recharge payload contains a non-zero value."""
        return any(
            bool(np.any(np.asarray(payload, dtype=float) != 0.0))
            for payload in payloads_by_period
        )

    def recharge_config(self) -> object | None:
        """Return the recharge config object when the flow contract provides one."""
        sinks_sources = getattr(self.flow, "sinks_sources", {})
        if not isinstance(sinks_sources, Mapping):
            return None
        return sinks_sources.get("recharge")

    def boundary_conditions_mapping(self) -> Mapping[str, object]:
        """Return the boundary-condition mapping from the flow contract."""
        boundary_conditions = getattr(self.flow, "boundary_conditions", {})
        if not isinstance(boundary_conditions, Mapping):
            raise TypeError("flow.boundary_conditions must be a mapping")
        return boundary_conditions

    def is_bc_active(self, bc_id: str) -> bool:
        """Return whether one boundary id is active in the current flow setup."""
        active = getattr(self.flow, "active_bc", ())
        return bc_id in active


__all__ = ["BoussinesqForcingResolver", "ResolvedDirichletSupport"]
