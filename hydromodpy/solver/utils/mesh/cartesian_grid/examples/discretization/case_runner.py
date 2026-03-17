"""Accessory case runners for SGrid/FieldParam discretization workflows."""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path

import numpy as np

from hydromodpy.field.geology.geology_field import GeologyField
from hydromodpy.field.core.field_param import FieldParam
from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_config import SGridConfig
from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_from_config import (
    build_sgrid_from_config,
)
from hydromodpy.solver.utils.mesh.cartesian_grid.examples.discretization.run_demo_config import (
    SGridFieldParamDiscretizationConfig,
)
from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_fieldparam_discretization import (
    SGridFieldParamDiscretizationResult,
    discretize_fieldparam_on_sgrid,
)


def _coerce_config(
    config: SGridFieldParamDiscretizationConfig | Mapping[str, object],
) -> SGridFieldParamDiscretizationConfig:
    """Normalize config input to one validated Pydantic object."""
    if isinstance(config, SGridFieldParamDiscretizationConfig):
        return config
    if isinstance(config, Mapping):
        return SGridFieldParamDiscretizationConfig.model_validate(dict(config))
    raise TypeError("config must be a SGridFieldParamDiscretizationConfig or a mapping")


def _summary_payload(
    result: SGridFieldParamDiscretizationResult,
    *,
    field_param: FieldParam,
    geology_field: GeologyField,
) -> dict[str, object]:
    """Build a compact JSON-serializable summary for quick run diagnostics."""
    arr2d = np.asarray(result.values_2d, dtype=float)
    arr3d = np.asarray(result.values_3d, dtype=float)
    return {
        "shape": [int(v) for v in arr2d.shape],
        "shape_3d": [int(v) for v in arr3d.shape],
        "nlay": int(arr3d.shape[0]),
        "min": float(np.nanmin(arr2d)),
        "max": float(np.nanmax(arr2d)),
        "min_3d": float(np.nanmin(arr3d)),
        "max_3d": float(np.nanmax(arr3d)),
        "field_param_id": str(getattr(field_param, "identifier", "")),
        "field_param_kind": str(getattr(field_param, "kind", "")),
        "geology_field_id": str(getattr(geology_field, "identifier", "")),
    }


def run_discretization_case(
    config: SGridFieldParamDiscretizationConfig | Mapping[str, object],
) -> SGridFieldParamDiscretizationResult:
    """Run one discretization case from validated config."""
    cfg = _coerce_config(config)

    geology_field = GeologyField.from_dict(cfg.geology)
    field_param = FieldParam.from_dict(cfg.field_param)
    sgrid_cfg = SGridConfig.from_mapping(cfg.sgrid)
    sgrid = build_sgrid_from_config(sgrid_cfg)

    result = discretize_fieldparam_on_sgrid(
        geology_field=geology_field,
        field_param=field_param,
        sgrid=sgrid,
        cell_samples_per_axis=cfg.cell_samples_per_axis,
        depth=cfg.depth,
        strict_field_spatial_id_match=cfg.strict_field_spatial_id_match,
    )

    if cfg.output_npy is not None:
        out_path = Path(cfg.output_npy)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(out_path, result.values_2d)

    if cfg.output_summary_json is not None:
        summary_path = Path(cfg.output_summary_json)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        payload = _summary_payload(
            result,
            field_param=field_param,
            geology_field=geology_field,
        )
        summary_path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

    return result


def run_discretization_case_from_toml(
    config_toml: str | Path,
    *,
    section: str = "case",
) -> SGridFieldParamDiscretizationResult:
    """Load one TOML case and run discretization."""
    cfg = SGridFieldParamDiscretizationConfig.from_toml(config_toml, section=section)
    return run_discretization_case(cfg)

