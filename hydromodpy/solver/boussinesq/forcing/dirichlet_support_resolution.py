"""Dirichlet-support resolution helpers for the Boussinesq forcing resolver."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from hydromodpy.solver.boussinesq.forcing_resolution import BoussinesqForcingResolver


@dataclass(frozen=True)
class ResolvedDirichletSupport:
    """One resolved Dirichlet support over cells and/or edges."""

    label: str
    edge_indices: np.ndarray
    cell_indices: np.ndarray
    head_value_m: float


class DirichletSupportResolutionMixin:
    """Resolve side, stream and ocean Dirichlet supports for the runtime."""

    mesh: object

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
        self: "BoussinesqForcingResolver",
        nper: int,
        *,
        ocean_series_m: np.ndarray | None = None,
    ) -> tuple[tuple[ResolvedDirichletSupport, ...], ...]:
        """Resolve all Dirichlet supports once, then reuse them across projections."""
        supports_by_period: list[list[ResolvedDirichletSupport]] = [[] for _ in range(int(nper))]
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
                        np.flatnonzero(self.ocean_supported_cell_mask(float(head_value))).astype(
                            int, copy=False
                        ),
                        float(head_value),
                    )
                )

        return tuple(tuple(period_supports) for period_supports in supports_by_period)

    @staticmethod
    def require_active_dirichlet_boundary(
        *,
        boundary_conditions: dict[str, object],
        bc_id: str,
    ) -> object:
        """Return one active boundary object after validating Dirichlet semantics."""
        boundary = boundary_conditions.get(bc_id)
        if boundary is None:
            raise ValueError(f"Active boundary '{bc_id}' is missing from flow.bc.")
        boundary_type = str(getattr(boundary, "type", "dirichlet")).strip().lower()
        if boundary_type != "dirichlet":
            raise ValueError(
                f"Boundary '{bc_id}' must be Dirichlet for the current boussinesq backend slice."
            )
        return boundary


__all__ = ["DirichletSupportResolutionMixin", "ResolvedDirichletSupport"]
