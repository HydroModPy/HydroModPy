"""Config helpers for the reference 3D FieldParam case family."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hydromodpy.core.config.path_helpers import resolve_path
from hydromodpy.spatial.field.core.field_param import FieldParam
from hydromodpy.spatial.mesh.gmsh_grid.cases._common import (
    load_case_section,
    resolve_case_config_path,
)


def resolve_reference_3d_fieldparam_config_path(raw_config: str | Path) -> Path:
    """Resolve the 3D FieldParam config path from cwd or script directory."""

    return resolve_case_config_path(raw_config, script_dir=Path(__file__).resolve().parent)


def _optional_nested_section(
    payload: Mapping[str, Any], dotted_path: str
) -> Mapping[str, Any] | None:
    from hydromodpy.core.config.path_helpers import get_nested_section

    try:
        return get_nested_section(payload, dotted_path)
    except (KeyError, ValueError):
        return None


def resolve_reference_3d_fieldparam_run_config(
    config_toml: str | Path,
    *,
    section: str = "case",
) -> dict[str, Any]:
    """Load the main `run` config used by the 3D FieldParam case."""

    config_path = Path(config_toml).resolve()
    payload = _load_case_payload(config_path)
    section_cfg = load_case_section(config_path, section=section)
    vertical_override = _optional_nested_section(payload, f"{section}.field_param_vertical_profile")

    return {
        "reference_2d_config": resolve_path(
            section_cfg["reference_2d_config"], base_dir=config_path.parent
        ),
        "reference_2d_section": str(section_cfg.get("reference_2d_section", "case")).strip()
        or "case",
        "reference_3d_mesh_config": resolve_path(
            section_cfg["reference_3d_mesh_config"],
            base_dir=config_path.parent,
        ),
        "reference_3d_mesh_section": str(
            section_cfg.get("reference_3d_mesh_section", "case")
        ).strip()
        or "case",
        "depth": float(section_cfg.get("depth", 0.0)),
        "cell_samples_per_axis": (
            None
            if section_cfg.get("cell_samples_per_axis") is None
            else max(2, int(section_cfg["cell_samples_per_axis"]))
        ),
        "strict_field_spatial_id_match": bool(
            section_cfg.get("strict_field_spatial_id_match", True)
        ),
        "output_summary_json": section_cfg.get("output_summary_json"),
        "output_values_npy": section_cfg.get("output_values_npy"),
        "output_overview_png": section_cfg.get("output_overview_png"),
        "field_param_vertical_profile": (
            None if vertical_override is None else dict(vertical_override)
        ),
    }


def resolve_reference_3d_postprocess_config(
    config_toml: str | Path,
    *,
    section: str = "case",
) -> dict[str, Any]:
    """Load the `postprocess` companion config."""

    config_path = Path(config_toml).resolve()
    section_cfg = load_case_section(config_path, section=section)
    return {
        "reference_3d_fieldparam_config": resolve_path(
            section_cfg["reference_3d_fieldparam_config"],
            base_dir=config_path.parent,
        ),
        "reference_3d_fieldparam_section": str(
            section_cfg.get("reference_3d_fieldparam_section", "case")
        ).strip()
        or "case",
        "label": str(section_cfg.get("label", "field_param_value")).strip() or "field_param_value",
        "value_name": str(section_cfg.get("value_name", "field_param_value")).strip()
        or "field_param_value",
        "depth_name": str(section_cfg.get("depth_name", "prism_center_depth")).strip()
        or "prism_center_depth",
        "output_summary_json": section_cfg.get("output_summary_json"),
        "output_values_npy": section_cfg.get("output_values_npy"),
        "output_vtu": section_cfg.get("output_vtu"),
    }


def resolve_reference_3d_visualization_config(
    config_toml: str | Path,
    *,
    section: str = "case",
) -> dict[str, Any]:
    """Load the lightweight figure-building companion config."""

    config_path = Path(config_toml).resolve()
    section_cfg = load_case_section(config_path, section=section)
    return {
        "reference_3d_postprocess_config": resolve_path(
            section_cfg["reference_3d_postprocess_config"],
            base_dir=config_path.parent,
        ),
        "reference_3d_postprocess_section": str(
            section_cfg.get("reference_3d_postprocess_section", "case")
        ).strip()
        or "case",
        "output_summary_json": section_cfg.get("output_summary_json"),
        "output_layers_png": section_cfg.get("output_layers_png"),
        "output_profiles_png": section_cfg.get("output_profiles_png"),
    }


def resolve_reference_interactive_viewer_config(
    config_toml: str | Path,
    *,
    section: str = "case",
) -> dict[str, Any]:
    """Load the companion config of the interactive PyVista viewer."""

    config_path = Path(config_toml).resolve()
    section_cfg = load_case_section(config_path, section=section)
    return {
        "reference_3d_postprocess_config": resolve_path(
            section_cfg["reference_3d_postprocess_config"],
            base_dir=config_path.parent,
        ),
        "reference_3d_postprocess_section": str(
            section_cfg.get("reference_3d_postprocess_section", "case")
        ).strip()
        or "case",
        "value_name": str(section_cfg.get("value_name", "field_param_value")).strip()
        or "field_param_value",
        "depth_name": str(section_cfg.get("depth_name", "prism_center_depth")).strip()
        or "prism_center_depth",
        "cmap": str(section_cfg.get("cmap", "viridis")).strip() or "viridis",
        "show_edges": bool(section_cfg.get("show_edges", False)),
        "opacity": float(section_cfg.get("opacity", 1.0)),
        "vertical_exaggeration": float(section_cfg.get("vertical_exaggeration", 1.0)),
        "show": bool(section_cfg.get("show", True)),
        "off_screen": bool(section_cfg.get("off_screen", False)),
        "output_summary_json": section_cfg.get("output_summary_json"),
        "output_screenshot_png": section_cfg.get("output_screenshot_png"),
    }


def override_field_param_vertical_profile(
    field_param: FieldParam, vertical_profile: Mapping[str, Any] | None
) -> FieldParam:
    """Return a new FieldParam with one overridden vertical-profile section."""

    if vertical_profile is None:
        return field_param
    payload = field_param.as_dict()
    payload["vertical_profile"] = dict(vertical_profile)
    return FieldParam.from_dict(payload)


def _load_case_payload(config_toml: Path) -> dict[str, Any]:
    import tomllib

    return tomllib.loads(config_toml.read_text(encoding="utf-8-sig"))


__all__ = [
    "override_field_param_vertical_profile",
    "resolve_reference_3d_fieldparam_config_path",
    "resolve_reference_3d_fieldparam_run_config",
    "resolve_reference_3d_postprocess_config",
    "resolve_reference_3d_visualization_config",
    "resolve_reference_interactive_viewer_config",
]
