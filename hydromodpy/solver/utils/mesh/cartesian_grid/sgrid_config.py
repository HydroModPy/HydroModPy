"""
Pydantic configuration model and TOML helpers for structured grid generation.

Design choices
--------------
- ``SGridConfig`` is the only validation entry point for grid settings.
- Runtime code receives a fully validated object and never re-validates
  business rules.
- TOML/mapping loaders both normalize paths and produce the same model.
"""

from __future__ import annotations

from math import isclose
from pathlib import Path
import tomllib
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class SGridConfig(BaseModel):
    """
    Single source of truth for structured-grid configuration validation.

    Each field below maps one explicit model parameter with constrained type and
    semantic description. Cross-field dependencies are validated in
    ``_validate_cross_fields``.
    """

    model_config = ConfigDict(extra="forbid")

    sgrid_type: Literal["structured", "unstructured", "vertex"] = Field(
        default="structured",
        description="Spatial grid family. Only 'structured' is currently implemented.",
    )
    lenuni: str = Field(
        default="m",
        description="Length unit label propagated to FloPy (for example 'm').",
    )
    genmtd_top: Literal["filepath"] = Field(
        default="filepath",
        description="Method used to define top surface. Currently only raster filepath is supported.",
    )
    top_path: str = Field(
        ...,
        description="Path to top DEM raster used as model top surface.",
    )
    crs: str | None = Field(
        default=None,
        description="Optional CRS identifier (for example 'EPSG:2154').",
    )
    plan_discretization_mode: Literal["raster_native", "shape"] = Field(
        default="raster_native",
        description=(
            "Planar discretization strategy: keep native raster shape or "
            "resample to explicit (ny, nx) shape."
        ),
    )
    nx: int | None = Field(
        default=None,
        ge=1,
        description="Target number of columns when plan_discretization_mode='shape'.",
    )
    ny: int | None = Field(
        default=None,
        ge=1,
        description="Target number of rows when plan_discretization_mode='shape'.",
    )

    genmtd_bot: Literal["filepath", "raster", "constant_thickness", "constant_altitude"] = Field(
        ...,
        description="Bottom-surface generation method.",
    )
    bot_path: str | None = Field(
        default=None,
        description="Path to bottom raster when genmtd_bot='filepath'.",
    )
    bot_raster: Any | None = Field(
        default=None,
        description="In-memory bottom raster array when genmtd_bot='raster'.",
    )
    thick: float | None = Field(
        default=None,
        description="Domain thickness when genmtd_bot='constant_thickness'.",
    )
    zbot: float | None = Field(
        default=None,
        description="Constant bottom elevation when genmtd_bot='constant_altitude'.",
    )

    genmtd_lay: Literal["constant", "decay", "list"] = Field(
        ...,
        description="Vertical-layering method.",
    )
    nlay: int | None = Field(
        default=None,
        ge=1,
        description="Number of model layers for constant/decay layering.",
    )
    lay_decay: float | None = Field(
        default=None,
        gt=1.0,
        description="Decay exponent (>1) for progressively thicker layers with depth.",
    )
    lay_proportions: list[float] | None = Field(
        default=None,
        description="Per-layer thickness fractions when genmtd_lay='list' (must sum to 1).",
    )

    nodata: float = Field(
        default=-9999.0,
        description="No-data sentinel value used to mask invalid raster cells.",
    )

    @field_validator("lenuni", "top_path")
    @classmethod
    def _validate_required_non_empty_text(cls, value):
        text = str(value).strip()
        if not text:
            raise ValueError("value cannot be empty")
        return text

    @field_validator("crs", "bot_path")
    @classmethod
    def _validate_optional_non_empty_text(cls, value):
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            raise ValueError("value cannot be empty when provided")
        return text

    @field_validator("top_path", "bot_path")
    @classmethod
    def _expand_user_in_paths(cls, value):
        if value is None:
            return None
        return str(Path(value).expanduser())

    @field_validator("lay_proportions")
    @classmethod
    def _validate_lay_proportions(cls, value):
        if value is None:
            return None
        arr = [float(v) for v in list(value)]
        if len(arr) == 0:
            raise ValueError("lay_proportions cannot be empty")
        if any(v <= 0 for v in arr):
            raise ValueError("lay_proportions values must be strictly positive")
        if not isclose(sum(arr), 1.0, rel_tol=0.0, abs_tol=1e-6):
            raise ValueError("lay_proportions must sum to 1.0")
        return arr

    @staticmethod
    def _require_existing_file(path_value: str | None, *, message: str):
        if path_value is None:
            raise ValueError(message)
        path = Path(path_value)
        if not path.exists():
            raise ValueError(f"File does not exist: {path}")

    @model_validator(mode="after")
    def _validate_cross_fields(self):
        if self.sgrid_type == "unstructured":
            raise ValueError("sgrid_type='unstructured' is not implemented yet")
        if self.sgrid_type == "vertex":
            raise ValueError("sgrid_type='vertex' is not implemented yet")

        if self.plan_discretization_mode == "shape":
            if self.nx is None or self.ny is None:
                raise ValueError(
                    "nx and ny are required when plan_discretization_mode='shape'"
                )
        if self.plan_discretization_mode == "raster_native":
            if self.nx is not None or self.ny is not None:
                raise ValueError(
                    "nx and ny must not be provided when "
                    "plan_discretization_mode='raster_native'"
                )

        self._require_existing_file(
            self.top_path,
            message="top_path is required when genmtd_top='filepath'",
        )

        if self.genmtd_bot == "filepath":
            self._require_existing_file(
                self.bot_path,
                message="bot_path is required when genmtd_bot='filepath'",
            )
        if self.genmtd_bot == "raster" and self.bot_raster is None:
            raise ValueError("bot_raster is required when genmtd_bot='raster'")
        if self.genmtd_bot == "constant_thickness" and self.thick is None:
            raise ValueError("thick is required when genmtd_bot='constant_thickness'")
        if self.genmtd_bot == "constant_altitude" and self.zbot is None:
            raise ValueError("zbot is required when genmtd_bot='constant_altitude'")

        if self.genmtd_lay in ("constant", "decay") and self.nlay is None:
            raise ValueError("nlay is required when genmtd_lay is 'constant' or 'decay'")
        if self.genmtd_lay == "decay" and self.lay_decay is None:
            raise ValueError("lay_decay is required when genmtd_lay='decay'")
        if self.genmtd_lay == "list":
            if self.lay_proportions is None:
                raise ValueError("lay_proportions is required when genmtd_lay='list'")
            if self.nlay is not None and self.nlay != len(self.lay_proportions):
                raise ValueError("nlay must match len(lay_proportions) when both are provided")
        return self

    @classmethod
    def from_mapping(cls, config_data: Mapping[str, Any]):
        """Validate and build from flat mapping or top-level ``sgrid`` mapping."""
        payload = dict(config_data.get("sgrid", config_data))
        return cls.model_validate(payload)

    @classmethod
    def from_toml(cls, config_path: str | Path):
        """Load TOML, resolve relative paths, then validate."""
        path = Path(config_path).expanduser().resolve()
        with path.open("rb") as stream:
            payload = tomllib.load(stream)

        if not isinstance(payload, Mapping) or "sgrid" not in payload:
            raise ValueError(f"Invalid sgrid configuration in {path}: missing [sgrid] section")

        cfg = dict(payload["sgrid"])
        base = path.parent
        cfg["top_path"] = _resolve_path(cfg["top_path"], base)
        if cfg.get("bot_path") is not None:
            cfg["bot_path"] = _resolve_path(cfg["bot_path"], base)
        return cls.model_validate(cfg)


def _resolve_path(path_value: str, base_dir: Path) -> str:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return str(path)


def validate_sgrid_config_data(config_data: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize SGrid configuration mapping."""
    if not isinstance(config_data, Mapping):
        raise ValueError("sgrid configuration must be a mapping")
    try:
        parsed = SGridConfig.from_mapping(config_data)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    return parsed.model_dump(mode="python", exclude_none=True)


def load_sgrid_toml(config_path: str | Path) -> dict[str, Any]:
    """Load and validate SGrid configuration from TOML."""
    try:
        parsed = SGridConfig.from_toml(config_path)
    except ValidationError as exc:
        path = Path(config_path).expanduser().resolve()
        raise ValueError(f"Invalid sgrid configuration in {path}: {exc}") from exc
    except ValueError as exc:
        path = Path(config_path).expanduser().resolve()
        raise ValueError(f"Invalid sgrid configuration in {path}: {exc}") from exc
    return parsed.model_dump(mode="python", exclude_none=True)
