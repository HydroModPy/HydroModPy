"""Pydantic config for SGrid + GeologyField + FieldParam discretization cases."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import sys
import tomllib
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


def _find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "hydromodpy").is_dir():
            return parent
    return current.parents[0]


REPO_ROOT = _find_repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.data_managers.variables.geology.config_cases import validate_geology_config_data
from hydromodpy.field.core.field_param_config import (
    resolve_field_param_config_payload,
    validate_resolved_field_param_data,
)
from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_config import (
    validate_sgrid_config_data,
)
from hydromodpy.solver.utils._config_helpers import get_nested_section, resolve_path


def _resolve_optional_mapping_path(
    payload: dict[str, Any],
    *,
    key: str,
    base_dir: Path,
) -> None:
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
        _resolve_optional_mapping_path(
            source_data,
            key="reference_raster_path",
            base_dir=base_dir,
        )
        out["source"] = source_data

    _resolve_optional_mapping_path(out, key="clip_polygon_path", base_dir=base_dir)

    landsea = out.get("landsea")
    if isinstance(landsea, Mapping):
        landsea_data = dict(landsea)
        _resolve_optional_mapping_path(landsea_data, key="path", base_dir=base_dir)
        out["landsea"] = landsea_data
    return out


def _resolve_field_param_paths(
    payload: Mapping[str, Any], *, base_dir: Path
) -> dict[str, Any]:
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


def _resolve_sgrid_paths(payload: Mapping[str, Any], *, base_dir: Path) -> dict[str, Any]:
    out = dict(payload)
    _resolve_optional_mapping_path(out, key="top_path", base_dir=base_dir)
    _resolve_optional_mapping_path(out, key="bot_path", base_dir=base_dir)
    return out


class SGridFieldParamDiscretizationConfig(BaseModel):
    """Configuration for standalone field-parameter discretization on an SGrid."""

    model_config = ConfigDict(extra="forbid")

    geology: dict[str, Any] = Field(
        description=(
            "Embedded geology payload (same content as section `[geology]` "
            "in a geology config TOML)."
        )
    )
    field_param: dict[str, Any] = Field(
        description=(
            "Embedded field-parameter payload (same content as a full "
            "`field_param_config.toml`: `field`, `field_homogeneous`, "
            "`field_heterogeneous`, `field_vertical_profile`)."
        )
    )
    sgrid: dict[str, Any] = Field(
        description=(
            "Embedded SGrid payload (same keys as section `[sgrid]` "
            "in SGrid config TOML)."
        )
    )

    cell_samples_per_axis: int | None = Field(
        default=None,
        ge=2,
        description=(
            "Optional override for geology_field.on_mesh(...). "
            "If omitted, geology default is used."
        ),
    )
    depth: float = Field(
        default=0.0,
        description="Depth passed to FieldParam.to_mesh_field(..., depth=...).",
    )
    strict_field_spatial_id_match: bool = Field(
        default=True,
        description=(
            "If true, heterogeneous field_param.field_spatial_id must match "
            "geology field identifier."
        ),
    )

    output_npy: Path | None = Field(
        default=None,
        description=(
            "Optional output `.npy` path for planar discretized values_2d "
            "(kept for existing map-based visualizations)."
        ),
    )
    output_summary_json: Path | None = Field(
        default=None,
        description="Optional output JSON summary path.",
    )

    @field_validator("geology", mode="before")
    @classmethod
    def _validate_geology_payload(cls, value):
        if not isinstance(value, Mapping):
            raise ValueError("geology must be a mapping")
        return validate_geology_config_data(value)

    @field_validator("field_param", mode="before")
    @classmethod
    def _validate_field_param_payload(cls, value):
        if not isinstance(value, Mapping):
            raise ValueError("field_param must be a mapping")
        payload = dict(value)
        if any(
            key in payload
            for key in (
                "field",
                "field_homogeneous",
                "field_heterogeneous",
                "field_vertical_profile",
            )
        ):
            payload = resolve_field_param_config_payload(
                payload,
                base_dir=Path.cwd(),
                section_label="field_param",
            )
        return validate_resolved_field_param_data(payload)

    @field_validator("sgrid", mode="before")
    @classmethod
    def _validate_sgrid_payload(cls, value):
        if not isinstance(value, Mapping):
            raise ValueError("sgrid must be a mapping")
        return validate_sgrid_config_data(value)

    @field_validator("output_npy", "output_summary_json", mode="before")
    @classmethod
    def _expand_user_path(cls, value):
        if value is None:
            return None
        return Path(value).expanduser()

    @classmethod
    def from_toml(
        cls,
        config_path: str | Path,
        *,
        section: str = "case",
    ) -> "SGridFieldParamDiscretizationConfig":
        """Load one case section from TOML and resolve relative paths."""
        path = Path(config_path).expanduser().resolve()
        payload = tomllib.loads(path.read_text(encoding="utf-8-sig"))
        section_cfg = dict(get_nested_section(payload, section))
        base = path.parent

        geology_cfg = section_cfg.get("geology")
        if isinstance(geology_cfg, Mapping):
            section_cfg["geology"] = _resolve_geology_paths(geology_cfg, base_dir=base)

        field_param_cfg = section_cfg.get("field_param")
        if isinstance(field_param_cfg, Mapping):
            field_param_cfg = _resolve_field_param_paths(field_param_cfg, base_dir=base)
            section_cfg["field_param"] = resolve_field_param_config_payload(
                field_param_cfg,
                base_dir=base,
                section_label="field_param",
            )

        sgrid_cfg = section_cfg.get("sgrid")
        if isinstance(sgrid_cfg, Mapping):
            section_cfg["sgrid"] = _resolve_sgrid_paths(sgrid_cfg, base_dir=base)

        for key in ("output_npy", "output_summary_json"):
            raw = section_cfg.get(key)
            if raw is None:
                continue
            section_cfg[key] = resolve_path(raw, base_dir=base)

        return cls.model_validate(section_cfg)


def validate_sgrid_fieldparam_discretization_data(
    config_data: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate one mapping payload for SGrid field-parameter discretization."""
    if not isinstance(config_data, Mapping):
        raise ValueError("discretization configuration must be a mapping")
    try:
        parsed = SGridFieldParamDiscretizationConfig.model_validate(dict(config_data))
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    return parsed.model_dump(mode="python", exclude_none=True)


def load_sgrid_fieldparam_discretization_toml(
    config_path: str | Path,
    *,
    section: str = "case",
) -> dict[str, Any]:
    """Load TOML and return validated config payload."""
    path = Path(config_path).expanduser().resolve()
    try:
        parsed = SGridFieldParamDiscretizationConfig.from_toml(path, section=section)
    except ValidationError as exc:
        raise ValueError(f"Invalid discretization config in {path}: {exc}") from exc
    except (ValueError, KeyError) as exc:
        raise ValueError(f"Invalid discretization config in {path}: {exc}") from exc
    return parsed.model_dump(mode="python", exclude_none=True)
