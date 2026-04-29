"""Config resolution helpers for the reference 2D geology-on-Gmsh case."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hydromodpy.master_config.path_helpers import resolve_path
from hydromodpy.spatial._protocols import get_geology_data_source
from hydromodpy.spatial.field.core.field_param_config import (
    resolve_field_param_config_payload,
    validate_resolved_field_param_data,
)
from hydromodpy.spatial.mesh.gmsh_grid import GmshPlanarMesh2D
from hydromodpy.spatial.mesh.gmsh_grid.cases._common import (
    load_case_section,
    resolve_case_config_path,
)


def resolve_reference_case_config_path(raw_config: str | Path) -> Path:
    """Resolve the reference 2D case config path from cwd or script directory."""

    return resolve_case_config_path(raw_config, script_dir=Path(__file__).resolve().parent)


def _resolve_optional_mapping_path(payload: dict[str, Any], *, key: str, base_dir: Path) -> None:
    raw = payload.get(key)
    if raw is None:
        return
    payload[key] = resolve_path(raw, base_dir=base_dir)


def _resolve_geology_paths(payload: Mapping[str, Any], *, base_dir: Path) -> dict[str, Any]:
    out = dict(payload)
    source = out.get("source")
    if isinstance(source, Mapping):
        source_data = dict(source)
        _resolve_optional_mapping_path(source_data, key="path", base_dir=base_dir)
        _resolve_optional_mapping_path(source_data, key="reference_raster_path", base_dir=base_dir)
        out["source"] = source_data

    landsea = out.get("landsea")
    if isinstance(landsea, Mapping):
        out["landsea"] = dict(landsea)
    return out


def _resolve_field_param_paths(payload: Mapping[str, Any], *, base_dir: Path) -> dict[str, Any]:
    out = dict(payload)
    heterogeneous = out.get("field_heterogeneous")
    if not isinstance(heterogeneous, Mapping):
        return out
    heterogeneous_data = dict(heterogeneous)
    source = str(heterogeneous_data.get("values_source", "inline")).strip().lower()
    if source == "csv" and heterogeneous_data.get("values_csv_file") is not None:
        heterogeneous_data["values_csv_file"] = resolve_path(
            heterogeneous_data["values_csv_file"],
            base_dir=base_dir,
        )
    out["field_heterogeneous"] = heterogeneous_data
    return out


def _resolve_mesh_paths(payload: Mapping[str, Any], *, base_dir: Path) -> dict[str, Any]:
    out = dict(payload)
    _resolve_optional_mapping_path(out, key="path", base_dir=base_dir)
    return out


def resolve_reference_case_config(
    config_toml: str | Path,
    *,
    section: str = "case",
) -> dict[str, Any]:
    """Load and validate the public TOML config of the reference 2D case."""

    config_path = Path(config_toml).resolve()
    section_cfg = load_case_section(config_path, section=section)

    mesh_cfg = _resolve_mesh_paths(dict(section_cfg.get("mesh", {})), base_dir=config_path.parent)
    geology_cfg = _resolve_geology_paths(
        dict(section_cfg.get("geology", {})), base_dir=config_path.parent
    )
    field_param_cfg = _resolve_field_param_paths(
        dict(section_cfg.get("field_param", {})),
        base_dir=config_path.parent,
    )
    field_param_resolved = resolve_field_param_config_payload(
        field_param_cfg,
        base_dir=config_path.parent,
        section_label="field_param",
    )

    return {
        "mesh": mesh_cfg,
        "geology": get_geology_data_source().validate_config(geology_cfg),
        "field_param": validate_resolved_field_param_data(field_param_resolved),
        "cell_samples_per_axis": (
            None
            if section_cfg.get("cell_samples_per_axis") is None
            else max(2, int(section_cfg["cell_samples_per_axis"]))
        ),
        "depth": float(section_cfg.get("depth", 0.0)),
        "strict_field_spatial_id_match": bool(
            section_cfg.get("strict_field_spatial_id_match", True)
        ),
        "output_figure": section_cfg.get("output_figure"),
        "output_summary_json": section_cfg.get("output_summary_json"),
    }


def build_reference_mesh_from_toml(
    config_toml: str | Path,
    *,
    section: str = "case",
) -> GmshPlanarMesh2D:
    """Load the reference planar Gmsh mesh described by the case TOML."""

    config_path = resolve_reference_case_config_path(config_toml)
    cfg = resolve_reference_case_config(config_path, section=section)
    mesh_cfg = dict(cfg["mesh"])
    return GmshPlanarMesh2D.from_file(
        mesh_cfg["path"],
        cell_type=mesh_cfg.get("cell_type"),
    )


__all__ = [
    "build_reference_mesh_from_toml",
    "resolve_reference_case_config",
    "resolve_reference_case_config_path",
]
