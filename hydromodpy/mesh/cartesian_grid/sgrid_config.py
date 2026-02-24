"""
Pydantic schema and TOML loader for SGrid_Generation configuration.
"""

from __future__ import annotations

from math import isclose
from pathlib import Path
import tomllib
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class SGridConfigSchema(BaseModel):
    """
    Schema for one spatial-grid configuration payload.

    This schema mirrors parameters exposed by ``SGrid_Generation``.
    """

    model_config = ConfigDict(extra="forbid")

    sgrid_type: Literal["structured", "unstructured", "vertex"] = "structured"
    lenuni: str = "m"
    genmtd_top: Literal["filepath"] = "filepath"
    top_path: str
    crs: str | None = None

    genmtd_bot: Literal["filepath", "constant_thickness", "constant_altitude"]
    bot_path: str | None = None
    thick: float | None = None
    zbot: float | None = None

    genmtd_lay: Literal["constant", "decay", "list"]
    nlay: int | None = Field(default=None, ge=1)
    lay_decay: float | None = Field(default=None, gt=1.0)
    lay_proportions: list[float] | None = None

    nodata: float = -9999.0

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

    @model_validator(mode="after")
    def _validate_cross_fields(self):
        if self.genmtd_bot == "filepath" and self.bot_path is None:
            raise ValueError("bot_path is required when genmtd_bot='filepath'")
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


class SGridTomlSchema(BaseModel):
    """
    Top-level schema for TOML files containing one `[sgrid]` section.
    """

    model_config = ConfigDict(extra="forbid")

    sgrid: SGridConfigSchema


def _resolve_path(path_value: str, base_dir: Path) -> str:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return str(path)


def validate_sgrid_config_data(config_data: Mapping[str, Any]) -> dict[str, Any]:
    """
    Validate and normalize SGrid configuration mapping.

    Accepted shapes:
    - flat dictionary containing SGrid keys
    - dictionary with top-level `"sgrid"` section
    """
    if not isinstance(config_data, Mapping):
        raise ValueError("sgrid configuration must be a mapping")

    payload = dict(config_data.get("sgrid", config_data))
    try:
        parsed = SGridConfigSchema.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    return parsed.model_dump(mode="python", exclude_none=True)


def load_sgrid_toml(config_path: str | Path) -> dict[str, Any]:
    """
    Load and validate SGrid configuration from TOML.

    Relative `top_path` and `bot_path` are resolved against TOML directory.
    """
    path = Path(config_path).expanduser().resolve()
    with path.open("rb") as stream:
        payload = tomllib.load(stream)

    try:
        parsed = SGridTomlSchema.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"Invalid sgrid configuration in {path}: {exc}") from exc

    cfg = parsed.sgrid.model_dump(mode="python", exclude_none=True)
    base = path.parent
    cfg["top_path"] = _resolve_path(cfg["top_path"], base)
    if cfg.get("bot_path") is not None:
        cfg["bot_path"] = _resolve_path(cfg["bot_path"], base)
    return cfg

