"""Pydantic schema and TOML loader for piezometry station-set configuration."""

from __future__ import annotations

from pathlib import Path
import tomllib
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator


class PiezometrySectionSchema(BaseModel):
    """General piezometry request settings."""

    model_config = ConfigDict(extra="forbid")

    measurement: Literal["level", "depth", "both"] = "both"
    display: bool = False
    date_start: str | None = None
    date_end: str | None = None

    @field_validator("date_start", "date_end")
    @classmethod
    def _validate_optional_date(cls, value):
        if value is None:
            return None
        text = str(value).strip()
        if text == "":
            raise ValueError("date value cannot be empty when provided")
        return text


class SourceSectionSchema(BaseModel):
    """Data source options (API or local files)."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["api", "local"] = "api"
    local_data_dir: str | None = None

    @field_validator("local_data_dir")
    @classmethod
    def _validate_optional_dir(cls, value):
        if value is None:
            return None
        text = str(value).strip()
        if text == "":
            raise ValueError("source.local_data_dir cannot be empty when provided")
        return text

    @model_validator(mode="after")
    def _validate_local_mode_requirements(self):
        if self.mode == "local" and self.local_data_dir is None:
            raise ValueError("source.local_data_dir is required when source.mode='local'")
        return self


class SelectionSectionSchema(BaseModel):
    """Piezometer selection options (list of stations or geographic mask)."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["stations", "mask"]
    piezometer_ids: list[str] | None = None
    mask_path: str | None = None

    @field_validator("piezometer_ids")
    @classmethod
    def _validate_station_ids(cls, value):
        if value is None:
            return None
        ids = [str(v).strip() for v in list(value)]
        if len(ids) == 0:
            raise ValueError("selection.piezometer_ids cannot be empty")
        if any(not item for item in ids):
            raise ValueError("selection.piezometer_ids cannot contain empty values")
        return ids

    @field_validator("mask_path")
    @classmethod
    def _validate_mask_path(cls, value):
        if value is None:
            return None
        text = str(value).strip()
        if text == "":
            raise ValueError("selection.mask_path cannot be empty when provided")
        return text

    @model_validator(mode="after")
    def _validate_selection_payload(self):
        if self.mode == "stations" and self.piezometer_ids is None:
            raise ValueError("selection.piezometer_ids is required when selection.mode='stations'")
        if self.mode == "mask" and self.mask_path is None:
            raise ValueError("selection.mask_path is required when selection.mode='mask'")
        return self


class OutputSectionSchema(BaseModel):
    """Export options for loaded piezometer series."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    path: str = "hydromodpy/data_managers/piezometry/exports"
    export_mode: Literal["lite", "full"] = "lite"

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value):
        text = str(value).strip()
        if text == "":
            raise ValueError("output.path cannot be empty")
        return text


class PiezometryTomlSchema(BaseModel):
    """Top-level TOML schema."""

    model_config = ConfigDict(extra="forbid")

    piezometry: PiezometrySectionSchema
    source: SourceSectionSchema
    selection: SelectionSectionSchema
    output: OutputSectionSchema = OutputSectionSchema()


def _resolve_path(path_value: str, base_dir: Path) -> str:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return str(path)


def validate_piezometry_config_data(config_data: Mapping[str, Any]) -> dict[str, Any]:
    """Validate raw piezometry station-set configuration mapping."""
    if not isinstance(config_data, Mapping):
        raise ValueError("Piezometry configuration must be a mapping")
    try:
        parsed = PiezometryTomlSchema.model_validate(dict(config_data))
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    return parsed.model_dump(mode="python", exclude_none=True)


def load_piezometry_toml(config_path: str | Path) -> dict[str, Any]:
    """
    Load and validate piezometry station-set TOML configuration.

    Relative paths are resolved against the TOML file directory.
    """
    path = Path(config_path).expanduser().resolve()
    with path.open("rb") as stream:
        payload = tomllib.load(stream)

    try:
        cfg = validate_piezometry_config_data(payload)
    except ValueError as exc:
        raise ValueError(f"Invalid piezometry configuration in {path}: {exc}") from exc

    base = path.parent
    source_cfg = cfg["source"]
    selection_cfg = cfg["selection"]
    output_cfg = cfg["output"]

    if source_cfg.get("local_data_dir") is not None:
        source_cfg["local_data_dir"] = _resolve_path(source_cfg["local_data_dir"], base)
    if selection_cfg.get("mask_path") is not None:
        selection_cfg["mask_path"] = _resolve_path(selection_cfg["mask_path"], base)
    if output_cfg.get("path") is not None:
        output_cfg["path"] = _resolve_path(output_cfg["path"], base)

    return cfg

