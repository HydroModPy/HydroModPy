"""Helpers to render canonical TOML templates for method-comparison."""

from __future__ import annotations

from pathlib import Path


def render_method_comparison_template() -> str:
    """Render one hand-written template for the current launcher contract."""
    lines = [
        "# Auto-generated method-comparison launcher template.",
        "# Usage:",
        "#   python -m launchers method-comparison run config_method_comparison.toml",
        "",
        "[method_comparison]",
        'comparison_id = "flow_method_scan"',
        'base_simulation_config = "run_flow_common.toml"',
        'output_root = "method_comparison/flow_method_scan"',
        "run_variants = true",
        "continue_on_error = true",
        'reference_variant = "mf6_gmsh_fine"',
        "",
        "[[method_comparison.variant]]",
        'id = "mf6_gmsh_fine"',
        'label = "MODFLOW 6, Gmsh fine"',
        'solver = "modflow6"',
        'mesh_mode = "mesh_catchment"',
        'mesh_label = "gmsh_fine"',
        "",
        "[method_comparison.variant.overlay.simulation]",
        'run_id = "mf6_gmsh_fine"',
        "",
        "[method_comparison.variant.overlay.mesh_catchment]",
        'constraints_mode = "geology_rivers"',
        "",
        "[[method_comparison.variant]]",
        'id = "boussinesq_same_mesh"',
        'label = "Boussinesq, reused Gmsh mesh"',
        'solver = "boussinesq"',
        'mesh_mode = "mesh_input"',
        'mesh_label = "gmsh_fine"',
        "",
        "[method_comparison.variant.overlay.simulation]",
        'run_id = "boussinesq_same_mesh"',
        "",
        "[method_comparison.variant.overlay.mesh_input]",
        'bundle_dir = "results_stable/mesh/mesh_catchment_bundle"',
        "",
        "[[method_comparison.observable]]",
        'name = "head_pz_01"',
        'variable = "watertable_elevation"',
        'support = "point"',
        "x = 265611.933",
        "y = 6784182.776",
        'time = "all"',
        'unit = "m"',
        "",
        "[[method_comparison.observable]]",
        'name = "outlet_flux"',
        'variable = "outlet_flux"',
        'support = "outlet"',
        "# Provide an explicit outlet location for a strict extraction.",
        "x = 266887.015",
        "y = 6785678.673",
        'time = "all"',
        'time_reducer = "last"',
        "# Canonical outlet flux is emitted in m3/s when the launcher can resolve it",
        "# from direct outlet discharge, Boussinesq drainage, or accumulation_flux",
        "# plus the outlet-cell area.",
        "# For a known outlet cell, use:",
        "# cell_index = 42",
        "# Exploratory fallback only:",
        "# allow_domain_proxy = true",
    ]
    return "\n".join(lines) + "\n"


def write_method_comparison_template(output_path: str | Path) -> None:
    """Render and write one method-comparison template to disk."""
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_method_comparison_template(), encoding="utf-8")


__all__ = (
    "render_method_comparison_template",
    "write_method_comparison_template",
)
