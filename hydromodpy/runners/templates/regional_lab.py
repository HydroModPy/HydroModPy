"""Helpers to render canonical TOML templates for the regional-lab launcher."""

from __future__ import annotations

from pathlib import Path


def render_regional_lab_template() -> str:
    """Render one hand-written template for the current regional-lab contract."""
    lines = [
        "# Auto-generated regional-lab launcher template.",
        "# Usage:",
        "#   python -m launchers regional-lab run config_regional_lab.toml",
        "#   python -m launchers regional-lab bootstrap-catalog --help",
        "# The bootstrap helper can scan one mesh_run_root when no fresh batch",
        "# manifest is available.",
        "",
        "[regional_lab]",
        'lab_id = "headwater_regional_lab"',
        'output_root = "regional_lab/headwater_regional_lab"',
        "# Set execute = false to inspect the expanded plan without running child launchers.",
        "execute = false",
        "continue_on_error = true",
        "validate_config_paths = true",
        "resume_from_report = true",
        "skip_completed_cases = true",
        "",
        "[regional_lab.catalog]",
        'path = "site_catalog.csv"',
        'format = "csv"',
        'site_id_field = "site_id"',
        'site_label_field = "site_label"',
        'cluster_id_field = "cluster_id"',
        'cluster_label_field = "cluster_label"',
        'cluster_family_field = "cluster_family"',
        'cluster_scale_field = "cluster_scale"',
        'region_field = "region_id"',
        'source_selection_field = "source_selection_id"',
        'status_field = "site_status"',
        'maturity_field = "maturity"',
        'tags_field = "tags"',
        'enabled_field = "enabled"',
        'required_fields = ["source_selection_id", "site_status", "maturity"]',
        'path_fields = ["simulation_reference_config", "backend_comparison_config"]',
        'tag_separator = ";"',
        "",
        "[regional_lab.selection]",
        "# Optional global filters applied before recipe expansion.",
        'tags = ["mesh_ready"]',
        "",
        "[[regional_lab.cluster_rule]]",
        'id = "headwater_100km2_rule"',
        'field_equals = { source_selection_id = "scan_headwater_100km2" }',
        'set_cluster_id = "headwater_100km2"',
        'set_cluster_label = "Headwater 100 km2"',
        'set_cluster_family = "headwater"',
        'set_cluster_scale = "100km2"',
        'cluster_tags = ["regional_headwater"]',
        "",
        "[[regional_lab.recipe]]",
        'id = "mf6_reference"',
        'label = "MF6 reference replay"',
        'launcher = "simulation"',
        'families = ["headwater"]',
        'scales = ["100km2"]',
        'required_fields = ["simulation_reference_config"]',
        "# The config-path template can use any catalog field plus:",
        "# {site_id}, {cluster_id}, {region_id}, {lab_id}, {recipe_id}, {recipe_label},",
        "# plus all raw or path-resolved fields present in the catalog row.",
        'config_path_template = "{simulation_reference_config}"',
        "",
        "[[regional_lab.recipe]]",
        'id = "backend_compare"',
        'label = "Backend comparison"',
        'launcher = "method-comparison"',
        '# Optional: constrain recipes using platform-specific backends.',
        '# allowed_platforms = ["linux"]',
        'families = ["headwater"]',
        'scales = ["100km2"]',
        'required_fields = ["backend_comparison_config"]',
        'config_path_template = "{backend_comparison_config}"',
    ]
    return "\n".join(lines) + "\n"


def write_regional_lab_template(output_path: str | Path) -> None:
    """Render and write one regional-lab template to disk."""
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_regional_lab_template(), encoding="utf-8")


__all__ = (
    "render_regional_lab_template",
    "write_regional_lab_template",
)
