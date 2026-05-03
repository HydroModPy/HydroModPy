"""Recharge-resolution helpers for the Boussinesq forcing resolver."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from hydromodpy.physics.flow.regime import normalize_flow_regime
from hydromodpy.physics.forcing.validation import ensure_non_negative_numeric_payload
from hydromodpy.spatial.mesh.gmsh_grid.planar_forcing_discretization import (
    discretize_fields_on_planar_mesh,
    discretize_points_on_planar_mesh,
)


class RechargeResolutionMixin:
    """Resolve recharge payloads to one scalar or cell vector per period."""

    mesh: object
    flow: object
    time_grid: object

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
                int(kper): np.zeros(self.mesh.n_cells, dtype=float) for kper in range(int(nper))
            }

        return self.apply_first_clim_to_cellwise_recharge(
            raw_arrays=raw_arrays,
            nper=int(nper),
            first_clim=first_clim,
        )

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
        ensure_non_negative_numeric_payload(arrays, label="flow.sinks_sources.recharge.values")
        for kper, values in arrays.items():
            if values.size != int(self.mesh.n_cells):
                raise ValueError(
                    "flow.sinks_sources.recharge.values must resolve to one value per "
                    f"Boussinesq cell; period {kper} has {values.size}, "
                    f"expected {int(self.mesh.n_cells)}."
                )
        if not arrays:
            return tuple(np.zeros(self.mesh.n_cells, dtype=float) for _ in range(nper))

        stacked = np.stack(tuple(arrays.values()), axis=0)
        flow_regime = normalize_flow_regime(getattr(self.flow, "flow_regime", "transient"))
        if flow_regime == "steady" or nper <= 1:
            mean_array = np.mean(stacked, axis=0)
            return (np.asarray(mean_array, dtype=float).reshape(-1),)

        result = {
            kper: arrays.get(kper, np.zeros(self.mesh.n_cells, dtype=float)).copy()
            for kper in range(nper)
        }
        if first_clim == "mean":
            result[0] = np.mean(stacked, axis=0)
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
            np.asarray(result[kper], dtype=float).reshape(-1).copy() for kper in range(nper)
        )


__all__ = ["RechargeResolutionMixin"]
