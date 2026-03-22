"""Build the visualization summary for one loaded mesh bundle.

This module keeps the typed summary contract internal as long as possible and
converts to a JSON-friendly mapping only at the public boundary.
"""

from __future__ import annotations

import math

from mesh.display.geometry import (
    has_continuous_node_topography,
)
from mesh.schema import MeshVisualizationData
from mesh.visualization_summary import VisualizationSummary


def _count_numeric_values(mesh, field_name: str) -> int:
    """Count cells exposing a finite numeric value for one field."""

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


def build_visualization_summary_contract(
    data: MeshVisualizationData,
) -> VisualizationSummary:
    """Build the typed summary contract for one visualization run."""

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

    return VisualizationSummary(
        bundle_dir=mesh.bundle_dir,
        mesh_file=mesh.mesh_path,
        node_count=mesh.n_nodes,
        cell_count=mesh.n_cells,
        edge_count=mesh.n_edges,
        crs=metadata.get("crs"),
        constraints_mode=metadata.get("constraints_mode"),
        geology_available=bool(metadata.get("geology", {}).get("available", False)),
        geology_keys=tuple(geology_keys),
        hydraulic_properties_available=hydraulic_properties_available,
        hydraulic_conductivity_available=hydraulic_conductivity_cell_count > 0,
        hydraulic_conductivity_cell_count=hydraulic_conductivity_cell_count,
        storage_coefficient_available=storage_coefficient_cell_count > 0,
        storage_coefficient_cell_count=storage_coefficient_cell_count,
        river_edge_count=int(sum(1 for edge in mesh.edges if bool(edge.is_river))),
        boundary_edge_count=int(
            sum(1 for edge in mesh.edges if str(edge.edge_kind) == "boundary")
        ),
        geology_interface_edge_count=int(
            sum(
                1
                for edge in mesh.edges
                if str(edge.edge_kind) == "geology_interface"
            )
        ),
        color_field=str(config.plot.color_field),
        show_topography_panel=bool(config.plot.show_topography_panel),
        topography_field=str(config.plot.topography_field),
        topography_render_mode=(
            "continuous_on_nodes"
            if has_continuous_node_topography(mesh)
            else "fallback_on_cells"
        ),
        figure_output_path=config.figure_output_path,
        summary_output_path=config.summary_output_path,
    )


def build_visualization_summary(
    data: MeshVisualizationData,
) -> dict[str, object]:
    """Build the stable public JSON-style summary payload."""

    return build_visualization_summary_contract(data).to_mapping()


__all__ = [
    "build_visualization_summary",
    "build_visualization_summary_contract",
]
