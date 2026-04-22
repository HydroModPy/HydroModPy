"""Drainage and ocean-support helpers for the Boussinesq forcing resolver."""

from __future__ import annotations

import numpy as np


class DrainageResolutionMixin:
    """Resolve ocean supports and top-drainage conductances by period."""

    mesh: object

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
                "Boundary 'ocean' must be Dirichlet for the current boussinesq backend slice."
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
            raise ValueError("ocean_series_m length must match nper when building support masks.")
        return tuple(
            self.ocean_supported_cell_mask(float(head_value)) for head_value in series.tolist()
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


__all__ = ["DrainageResolutionMixin"]
