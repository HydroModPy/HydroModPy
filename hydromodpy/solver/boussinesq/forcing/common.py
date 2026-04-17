"""Common forcing-resolution helpers for the Boussinesq solver."""

from __future__ import annotations

from collections.abc import Mapping
from numbers import Real

import numpy as np

from hydromodpy.solver.utils.mesh.gmsh_grid.runtime_support import (
    GmshSupportMetadata,
    build_gmsh_support_metadata,
)


class ForcingCommonMixin:
    """Shared helpers reused across forcing-resolution specializations."""

    mesh: object
    flow: object
    time_grid: object
    mesh_bundle: object | None
    planar_mesh_loader: object
    support_metadata: GmshSupportMetadata | None

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
            if np.isfinite(previous) and not np.isclose(
                previous,
                candidate,
                rtol=0.0,
                atol=1.0e-12,
            ):
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
            if np.isfinite(previous) and not np.isclose(
                previous,
                candidate,
                rtol=0.0,
                atol=1.0e-12,
            ):
                raise ValueError(
                    f"{label} overlaps another boundary-head support on edge {edge_index} "
                    f"with conflicting values ({previous} vs {candidate})."
                )
            edge_values_m[edge_index] = candidate

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
        if ForcingCommonMixin.is_scalar_number(payload):
            return np.full(nper, float(payload), dtype=float)
        sequence = ForcingCommonMixin.payload_to_sequence(payload, label=label)
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


__all__ = ["ForcingCommonMixin"]
