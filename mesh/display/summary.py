"""Construction du resume JSON pour la distribution des maillages."""

from __future__ import annotations

import math
from typing import Any

from mesh.display.figure import (
    has_continuous_node_topography,
)
from mesh.schema import MeshVisualizationData


def _count_numeric_values(mesh, field_name: str) -> int:
    """Compte les cellules disposant d'une valeur numerique exploitable."""
    count = 0
    for cell in mesh.cells:
        raw_value = getattr(cell, field_name, None)
        if raw_value is None:
            continue
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            count += 1
    return count


def build_visualization_summary(
    data: MeshVisualizationData,
) -> dict[str, Any]:
    """Construit un resume compact et facilement partageable."""

    mesh = data.mesh
    config = data.config
    metadata = dict(mesh.metadata)
    hydraulic_metadata = metadata.get("hydraulic_properties", {})
    geology_keys = sorted(
        {
            str(cell.geology_key)
            for cell in mesh.cells
            if str(cell.geology_key).strip() != ""
        }
    )
    hydraulic_conductivity_cell_count = _count_numeric_values(
        mesh,
        "hydraulic_conductivity_m_s",
    )
    storage_coefficient_cell_count = _count_numeric_values(
        mesh,
        "storage_coefficient",
    )
    hydraulic_properties_available = bool(
        hydraulic_metadata.get("available", False)
        or hydraulic_conductivity_cell_count > 0
        or storage_coefficient_cell_count > 0
    )

    return {
        "summary_schema_version": "mesh_distribution_v1",
        "bundle_dir": str(mesh.bundle_dir),
        "mesh_file": str(mesh.mesh_path),
        "node_count": int(mesh.n_nodes),
        "cell_count": int(mesh.n_cells),
        "edge_count": int(mesh.n_edges),
        "crs": metadata.get("crs"),
        "constraints_mode": metadata.get("constraints_mode"),
        "geology_available": bool(metadata.get("geology", {}).get("available", False)),
        "geology_keys": geology_keys,
        "hydraulic_properties_available": hydraulic_properties_available,
        "hydraulic_conductivity_available": hydraulic_conductivity_cell_count > 0,
        "hydraulic_conductivity_cell_count": hydraulic_conductivity_cell_count,
        "storage_coefficient_available": storage_coefficient_cell_count > 0,
        "storage_coefficient_cell_count": storage_coefficient_cell_count,
        "river_edge_count": int(sum(1 for edge in mesh.edges if bool(edge.is_river))),
        "boundary_edge_count": int(
            sum(1 for edge in mesh.edges if str(edge.edge_kind) == "boundary")
        ),
        "geology_interface_edge_count": int(
            sum(
                1
                for edge in mesh.edges
                if str(edge.edge_kind) == "geology_interface"
            )
        ),
        "color_field": str(config.plot.color_field),
        "show_topography_panel": bool(config.plot.show_topography_panel),
        "topography_field": str(config.plot.topography_field),
        "topography_render_mode": (
            "continuous_on_nodes"
            if has_continuous_node_topography(mesh)
            else "fallback_on_cells"
        ),
        "figure_output_path": (
            None if config.figure_output_path is None else str(config.figure_output_path)
        ),
        "summary_output_path": (
            None if config.summary_output_path is None else str(config.summary_output_path)
        ),
    }


__all__ = [
    "build_visualization_summary",
]
