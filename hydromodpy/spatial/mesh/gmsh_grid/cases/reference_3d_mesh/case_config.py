"""Config helpers for the reference 3D prism-mesh case."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.core.config.path_helpers import resolve_path
from hydromodpy.spatial.mesh.gmsh_grid.cases._common import (
    load_case_section,
    resolve_case_config_path,
)


def resolve_reference_3d_mesh_config_path(raw_config: str | Path) -> Path:
    """Resolve the 3D mesh case config path from cwd or script directory."""

    return resolve_case_config_path(raw_config, script_dir=Path(__file__).resolve().parent)


def resolve_reference_3d_mesh_config(
    config_toml: str | Path,
    *,
    section: str = "case",
) -> dict[str, Any]:
    """Load and validate the public TOML config of the reference 3D mesh case."""

    config_path = Path(config_toml).resolve()
    section_cfg = load_case_section(config_path, section=section)
    layer_thicknesses = np.asarray(section_cfg.get("layer_thicknesses", []), dtype=float).reshape(
        -1
    )
    if layer_thicknesses.size == 0:
        raise ValueError("layer_thicknesses cannot be empty for the 3D reference mesh case")
    return {
        "reference_2d_config": resolve_path(
            section_cfg["reference_2d_config"], base_dir=config_path.parent
        ),
        "reference_2d_section": str(section_cfg.get("reference_2d_section", "case")).strip()
        or "case",
        "top_z": float(section_cfg.get("top_z", 0.0)),
        "layer_thicknesses": [float(v) for v in layer_thicknesses],
        "output_summary_json": section_cfg.get("output_summary_json"),
    }


__all__ = [
    "resolve_reference_3d_mesh_config",
    "resolve_reference_3d_mesh_config_path",
]
