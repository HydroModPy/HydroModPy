"""Typed summary contract for the standalone mesh visualization package."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

VISUALIZATION_SUMMARY_SCHEMA_VERSION = "mesh_distribution_v1"


@dataclass(frozen=True)
class VisualizationSummary:
    """Compact and stable summary produced by the visualization workflow."""

    bundle_dir: Path
    mesh_file: Path
    node_count: int
    cell_count: int
    edge_count: int
    crs: str | None
    constraints_mode: str | None
    geology_available: bool
    geology_keys: tuple[str, ...]
    hydraulic_properties_available: bool
    hydraulic_conductivity_available: bool
    hydraulic_conductivity_cell_count: int
    storage_coefficient_available: bool
    storage_coefficient_cell_count: int
    river_edge_count: int
    boundary_edge_count: int
    geology_interface_edge_count: int
    color_field: str
    show_topography_panel: bool
    topography_field: str
    topography_render_mode: str
    figure_output_path: Path | None
    summary_output_path: Path | None

    def to_mapping(self) -> dict[str, Any]:
        """Serialize the typed summary to the stable JSON payload."""

        return {
            "summary_schema_version": VISUALIZATION_SUMMARY_SCHEMA_VERSION,
            "bundle_dir": str(self.bundle_dir),
            "mesh_file": str(self.mesh_file),
            "node_count": int(self.node_count),
            "cell_count": int(self.cell_count),
            "edge_count": int(self.edge_count),
            "crs": self.crs,
            "constraints_mode": self.constraints_mode,
            "geology_available": bool(self.geology_available),
            "geology_keys": list(self.geology_keys),
            "hydraulic_properties_available": bool(self.hydraulic_properties_available),
            "hydraulic_conductivity_available": bool(self.hydraulic_conductivity_available),
            "hydraulic_conductivity_cell_count": int(self.hydraulic_conductivity_cell_count),
            "storage_coefficient_available": bool(self.storage_coefficient_available),
            "storage_coefficient_cell_count": int(self.storage_coefficient_cell_count),
            "river_edge_count": int(self.river_edge_count),
            "boundary_edge_count": int(self.boundary_edge_count),
            "geology_interface_edge_count": int(self.geology_interface_edge_count),
            "color_field": str(self.color_field),
            "show_topography_panel": bool(self.show_topography_panel),
            "topography_field": str(self.topography_field),
            "topography_render_mode": str(self.topography_render_mode),
            "figure_output_path": (
                None if self.figure_output_path is None else str(self.figure_output_path)
            ),
            "summary_output_path": (
                None if self.summary_output_path is None else str(self.summary_output_path)
            ),
        }


__all__ = [
    "VISUALIZATION_SUMMARY_SCHEMA_VERSION",
    "VisualizationSummary",
]
