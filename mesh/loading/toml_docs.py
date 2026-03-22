"""Public documentation strings and key sets for the mesh viewer TOML."""

from __future__ import annotations

from mesh.schema import ALLOWED_COLOR_FIELDS, ALLOWED_TOPOGRAPHY_FIELDS


def _format_allowed_values(values: set[str]) -> str:
    return ", ".join(f"`{value}`" for value in sorted(values))


MAIN_LABEL = "[mesh_distribution]"
PLOT_LABEL = "[mesh_distribution.plot]"

MAIN_ALLOWED_KEYS = {
    "bundle_dir",
    "figure_output_path",
    "summary_output_path",
    "show_window",
    "plot",
}
PLOT_ALLOWED_KEYS = {
    "color_field",
    "color_map",
    "figure_size",
    "dpi",
    "title",
    "show_topography_panel",
    "topography_field",
    "topography_cmap",
    "topography_title",
    "show_mesh_edges",
    "mesh_edge_color",
    "mesh_edge_linewidth",
    "show_boundaries",
    "show_geology_interfaces",
    "show_river_edges",
    "annotate_cell_ids",
}

TOML_PARAMETER_DESCRIPTIONS = {
    "[mesh_distribution].bundle_dir": (
        "Path to the bundle directory to reload. It may be absolute or "
        "relative to the TOML file."
    ),
    "[mesh_distribution].figure_output_path": (
        "Optional output path for the overview PNG. If omitted, no figure is "
        "written to disk."
    ),
    "[mesh_distribution].summary_output_path": (
        "Optional output path for the JSON summary. If omitted, no JSON file is "
        "written to disk."
    ),
    "[mesh_distribution].show_window": (
        "Whether to open an interactive matplotlib window at the end of the run."
    ),
    "[mesh_distribution.plot].color_field": (
        "Field used to color cells in the structural panel. "
        f"Allowed values: {_format_allowed_values(ALLOWED_COLOR_FIELDS)}."
    ),
    "[mesh_distribution.plot].color_map": (
        "Matplotlib colormap name applied to `color_field`."
    ),
    "[mesh_distribution.plot].figure_size": (
        "Figure size as `[width, height]` in inches."
    ),
    "[mesh_distribution.plot].dpi": "Output figure resolution in DPI.",
    "[mesh_distribution.plot].title": (
        "Explicit title of the main panel. If omitted, a default title is "
        "built from `color_field`."
    ),
    "[mesh_distribution.plot].show_topography_panel": (
        "Whether to show the topography panel on the right side of the figure."
    ),
    "[mesh_distribution.plot].topography_field": (
        "Cell field used by the topography-panel fallback when nodal "
        "elevations are not sufficient. "
        f"Allowed values: {_format_allowed_values(ALLOWED_TOPOGRAPHY_FIELDS)}."
    ),
    "[mesh_distribution.plot].topography_cmap": (
        "Matplotlib colormap name used by the topography panel."
    ),
    "[mesh_distribution.plot].topography_title": (
        "Explicit title of the topography panel. If omitted, a default title "
        "is built automatically."
    ),
    "[mesh_distribution.plot].show_mesh_edges": (
        "Whether mesh edges are drawn in the panels."
    ),
    "[mesh_distribution.plot].mesh_edge_color": (
        "Matplotlib color used for mesh edges, for example a grayscale value "
        '(`"0.35"`) or a named color.'
    ),
    "[mesh_distribution.plot].mesh_edge_linewidth": (
        "Line width of mesh edges in points."
    ),
    "[mesh_distribution.plot].show_boundaries": (
        "Whether domain boundary edges are drawn."
    ),
    "[mesh_distribution.plot].show_geology_interfaces": (
        "Whether interfaces between geology units are drawn."
    ),
    "[mesh_distribution.plot].show_river_edges": (
        "Whether edges tagged as rivers are drawn."
    ),
    "[mesh_distribution.plot].annotate_cell_ids": (
        "Whether cell identifiers are added at cell centroids."
    ),
}


def get_toml_parameter_descriptions() -> dict[str, str]:
    """Return the public documentation strings for all supported TOML keys."""

    return dict(TOML_PARAMETER_DESCRIPTIONS)


__all__ = [
    "MAIN_ALLOWED_KEYS",
    "MAIN_LABEL",
    "PLOT_ALLOWED_KEYS",
    "PLOT_LABEL",
    "TOML_PARAMETER_DESCRIPTIONS",
    "get_toml_parameter_descriptions",
]
