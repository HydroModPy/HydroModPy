"""Pydantic schema and TOML loader for hydrometry station-set configuration."""

from __future__ import annotations

from pathlib import Path
import tomllib
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class HydrometrySectionSchema(BaseModel):
    """General hydrometry request settings."""

    model_config = ConfigDict(extra="forbid")

    variable: str = Field(
        default="QmnJ",
        description="Hydrometric variable requested from the source (for example daily discharge code).",
    )
    display: bool = Field(
        default=False,
        description="If true, display diagnostic information while loading station data.",
    )
    date_start: str | None = Field(
        default=None,
        description="Optional inclusive start date filter applied to the requested time series.",
    )
    date_end: str | None = Field(
        default=None,
        description="Optional inclusive end date filter applied to the requested time series.",
    )

    @field_validator("variable")
    @classmethod
    def _validate_variable(cls, value):
        text = str(value).strip()
        if not text:
            raise ValueError("hydrometry.variable cannot be empty")
        return text

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

    mode: Literal["api", "local"] = Field(
        default="api",
        description="Hydrometry source mode: remote API lookup or local exported files.",
    )
    local_data_dir: str | None = Field(
        default=None,
        description="Local directory containing previously exported station files when mode='local'.",
    )

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
    """Station selection options (list of stations or geographic mask)."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["stations", "mask"] = Field(
        ...,
        description="Station selection mode: explicit station ids or spatial mask filtering.",
    )
    station_ids: list[str] | None = Field(
        default=None,
        description="Explicit list of hydrometric station identifiers used when mode='stations'.",
    )
    mask_path: str | None = Field(
        default=None,
        description="Path to the polygon mask used to keep stations intersecting the study area when mode='mask'.",
    )

    @field_validator("station_ids")
    @classmethod
    def _validate_station_ids(cls, value):
        if value is None:
            return None
        ids = [str(v).strip() for v in list(value)]
        if len(ids) == 0:
            raise ValueError("selection.station_ids cannot be empty")
        if any(not item for item in ids):
            raise ValueError("selection.station_ids cannot contain empty values")
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
        if self.mode == "stations" and self.station_ids is None:
            raise ValueError("selection.station_ids is required when selection.mode='stations'")
        if self.mode == "mask" and self.mask_path is None:
            raise ValueError("selection.mask_path is required when selection.mode='mask'")
        return self


class OutputSectionSchema(BaseModel):
    """Export options for loaded station series."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=False,
        description="If true, export the loaded station series to disk after selection.",
    )
    path: str = Field(
        default="hydromodpy/data_managers/hydrometry/exports",
        description="Destination directory for exported hydrometry files.",
    )
    export_mode: Literal["lite", "full"] = Field(
        default="lite",
        description="Export payload level: 'lite' for compact outputs, 'full' for all available files.",
    )

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value):
        text = str(value).strip()
        if text == "":
            raise ValueError("output.path cannot be empty")
        return text


class HydrometryTomlSchema(BaseModel):
    """Top-level TOML schema."""

    model_config = ConfigDict(extra="forbid")

    hydrometry: HydrometrySectionSchema = Field(
        ...,
        description="General hydrometry request block.",
    )
    source: SourceSectionSchema = Field(
        ...,
        description="Hydrometry source selection block.",
    )
    selection: SelectionSectionSchema = Field(
        ...,
        description="Hydrometry station-selection block.",
    )
    output: OutputSectionSchema = Field(
        default_factory=OutputSectionSchema,
        description="Optional export block for loaded station series.",
    )


def _resolve_path(path_value: str, base_dir: Path) -> str:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return str(path)


def validate_hydrometry_config_data(config_data: Mapping[str, Any]) -> dict[str, Any]:
    """Validate raw hydrometry station-set configuration mapping."""
    if not isinstance(config_data, Mapping):
        raise ValueError("Hydrometry configuration must be a mapping")
    try:
        parsed = HydrometryTomlSchema.model_validate(dict(config_data))
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    return parsed.model_dump(mode="python", exclude_none=True)


def load_hydrometry_toml(config_path: str | Path) -> dict[str, Any]:
    """
    Load and validate hydrometry station-set TOML configuration.

    Relative paths are resolved against the TOML file directory.
    """
    path = Path(config_path).expanduser().resolve()
    with path.open("rb") as stream:
        payload = tomllib.load(stream)

    try:
        cfg = validate_hydrometry_config_data(payload)
    except ValueError as exc:
        raise ValueError(f"Invalid hydrometry configuration in {path}: {exc}") from exc

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
