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

import tomllib
import warnings
from collections.abc import Mapping
from math import isclose
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, ValidationError, field_validator, model_validator

from hydromodpy.master_config.base import HydroModelBase
from hydromodpy.master_config.path_helpers import resolve_path
from hydromodpy.master_config.profile import Profile


def _require_positive_int(value, *, name: str) -> int:
    """
    Validate and return one strictly positive integer.

    Floats representing exact integers (for example 5.0) are accepted.
    """
    if value is None:
        raise ValueError(f"{name} is required.")
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer >= 1, got bool.")
    if isinstance(value, int):
        out = value
    elif isinstance(value, float):
        if not float(value).is_integer():
            raise ValueError(f"{name} must be an integer value, got {value!r}.")
        out = int(value)
    else:
        raise ValueError(f"{name} must be an integer value, got {type(value)!r}.")
    if out < 1:
        raise ValueError(f"{name} must be >= 1.")
    return out


class VerticalGridConfig(HydroModelBase):
    """
    Single source of truth for vertical-grid validation.

    This model is used by surface-driven SGrid generation:
    - layering strategy (`genmtd_lay`),
    - layer count or proportions,
    - nodata masking metadata.

    All geometric quantities are interpreted in SI metres.
    """

    model_config = ConfigDict(extra="forbid")

    genmtd_lay: Annotated[Literal["constant", "decay", "list"], Profile.USER] = Field(
        default="constant",
        description="Vertical-layering strategy.",
    )
    nlay: Annotated[int | None, Profile.USER] = Field(
        default=1,
        description="Number of layers (required for constant/decay, ignored for list).",
    )
    lay_decay: Annotated[float | None, Profile.DEV] = Field(
        default=None,
        description="Decay exponent (>1) for decay layering.",
    )
    lay_proportions: Annotated[list[float] | None, Profile.DEV] = Field(
        default=None,
        description="Explicit layer fractions when genmtd_lay='list' (must sum to 1).",
    )
    nodata: Annotated[float, Profile.DEV] = Field(
        default=-9999.0,
        description="No-data sentinel value.",
    )

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
        if self.genmtd_lay in ("constant", "decay"):
            object.__setattr__(self, "nlay", _require_positive_int(self.nlay, name="nlay"))
        if self.genmtd_lay == "decay":
            if self.lay_decay is None:
                raise ValueError("lay_decay is required when genmtd_lay='decay'")
            object.__setattr__(self, "lay_decay", float(self.lay_decay))
            if self.lay_decay <= 1.0:
                raise ValueError("lay_decay must be > 1.0 when genmtd_lay='decay'")

        if self.genmtd_lay == "list":
            if self.lay_proportions is None:
                raise ValueError("lay_proportions is required when genmtd_lay='list'")
            if self.nlay is not None:
                warnings.warn(
                    "nlay must not be provided when genmtd_lay='list' "
                    "(it is derived from lay_proportions). "
                    "Provided nlay will be ignored.",
                    UserWarning,
                    stacklevel=2,
                )
            object.__setattr__(self, "nlay", None)
        return self

    @classmethod
    def from_mapping(cls, config_data: Mapping[str, Any]):
        payload = dict(config_data.get("sgrid", config_data))
        return cls.model_validate(payload)


class PlanarGridConfig(HydroModelBase):
    """Planar discretization contract for solver-facing grids."""

    model_config = ConfigDict(extra="forbid")

    mode: Annotated[Literal["keep_native", "resample_to_shape"], Profile.USER] = Field(
        default="keep_native",
        description=(
            "Planar solver-grid mode: keep the native domain support or "
            "resample to an explicit (ny, nx) target shape."
        ),
    )
    nx: Annotated[int | None, Profile.USER] = Field(
        default=None,
        ge=1,
        description="Target number of columns when planar mode is 'resample_to_shape'.",
    )
    ny: Annotated[int | None, Profile.USER] = Field(
        default=None,
        ge=1,
        description="Target number of rows when planar mode is 'resample_to_shape'.",
    )
    resampling: Annotated[Literal["bilinear", "average", "nearest"], Profile.DEV] = Field(
        default="bilinear",
        description="Resampling rule applied when planar mode is 'resample_to_shape'.",
    )

    @model_validator(mode="after")
    def _validate_cross_fields(self):
        if self.mode == "resample_to_shape":
            object.__setattr__(self, "nx", _require_positive_int(self.nx, name="nx"))
            object.__setattr__(self, "ny", _require_positive_int(self.ny, name="ny"))
        elif self.nx is not None or self.ny is not None:
            raise ValueError("nx and ny must be omitted when planar.mode='keep_native'")
        return self


class SolverSGridConfig(HydroModelBase):
    """Solver-facing grid configuration split into explicit planar and vertical parts."""

    model_config = ConfigDict(extra="forbid")

    planar: Annotated[PlanarGridConfig, Profile.USER] = Field(
        default_factory=PlanarGridConfig,
        description="Planar discretization of the solver grid.",
    )
    vertical: Annotated[VerticalGridConfig, Profile.USER] = Field(
        default_factory=VerticalGridConfig,
        description="Vertical layering of the solver grid.",
    )

    @classmethod
    def from_mapping(cls, config_data: Mapping[str, Any]):
        payload = dict(config_data.get("sgrid", config_data))
        return cls.model_validate(payload)


class SGridConfig(HydroModelBase):
    """
    Single source of truth for structured-grid configuration validation.

    Each field below maps one explicit model parameter with constrained type and
    semantic description. Cross-field dependencies are validated in
    ``_validate_cross_fields``.

    All geometric quantities are interpreted in SI metres.
    """

    model_config = ConfigDict(extra="forbid")

    sgrid_type: Annotated[Literal["structured"], Profile.USER] = Field(
        default="structured",
        description="Spatial grid family. Only 'structured' is supported.",
    )
    genmtd_top: Annotated[Literal["filepath"], Profile.USER] = Field(
        default="filepath",
        description="Method used to define top surface. Currently only raster filepath is supported.",
    )
    top_path: Annotated[str, Profile.USER] = Field(
        ...,
        description="Path to top DEM raster used as model top surface.",
    )
    crs: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Optional CRS identifier (for example 'EPSG:2154').",
    )
    plan_discretization_mode: Annotated[
        Literal["keep_native", "resample_to_shape"], Profile.USER
    ] = Field(
        default="keep_native",
        description=(
            "Planar discretization strategy: keep native support or "
            "resample to explicit (ny, nx) target shape."
        ),
    )
    nx: Annotated[int | None, Profile.USER] = Field(
        default=None,
        ge=1,
        description="Target number of columns when plan_discretization_mode='resample_to_shape'.",
    )
    ny: Annotated[int | None, Profile.USER] = Field(
        default=None,
        ge=1,
        description="Target number of rows when plan_discretization_mode='resample_to_shape'.",
    )

    genmtd_bot: Annotated[
        Literal["filepath", "raster", "constant_thickness", "constant_altitude"], Profile.USER
    ] = Field(
        ...,
        description="Bottom-surface generation method.",
    )
    bot_path: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Path to bottom raster when genmtd_bot='filepath'.",
    )
    bot_raster: Annotated[Any | None, Profile.USER] = Field(
        default=None,
        description="In-memory bottom raster array when genmtd_bot='raster'.",
    )
    thick: Annotated[float | None, Profile.USER] = Field(
        default=None,
        description="Domain thickness when genmtd_bot='constant_thickness'.",
    )
    zbot: Annotated[float | None, Profile.USER] = Field(
        default=None,
        description="Constant bottom elevation when genmtd_bot='constant_altitude'.",
    )

    genmtd_lay: Annotated[Literal["constant", "decay", "list"], Profile.USER] = Field(
        ...,
        description="Vertical-layering method.",
    )
    nlay: Annotated[int | None, Profile.USER] = Field(
        default=None,
        ge=1,
        description="Number of model layers for constant/decay layering.",
    )
    lay_decay: Annotated[float | None, Profile.DEV] = Field(
        default=None,
        gt=1.0,
        description="Decay exponent (>1) for progressively thicker layers with depth.",
    )
    lay_proportions: Annotated[list[float] | None, Profile.DEV] = Field(
        default=None,
        description="Per-layer thickness fractions when genmtd_lay='list' (must sum to 1).",
    )

    nodata: Annotated[float, Profile.DEV] = Field(
        default=-9999.0,
        description="No-data sentinel value used to mask invalid raster cells.",
    )

    @field_validator("top_path")
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
        if self.plan_discretization_mode == "resample_to_shape":
            if self.nx is None or self.ny is None:
                raise ValueError(
                    "nx and ny are required when plan_discretization_mode='resample_to_shape'"
                )
        if self.plan_discretization_mode == "keep_native":
            if self.nx is not None or self.ny is not None:
                raise ValueError(
                    "nx and ny must not be provided when plan_discretization_mode='keep_native'"
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
        cfg["top_path"] = resolve_path(cfg["top_path"], base)
        if cfg.get("bot_path") is not None:
            cfg["bot_path"] = resolve_path(cfg["bot_path"], base)
        return cls.model_validate(cfg)


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
