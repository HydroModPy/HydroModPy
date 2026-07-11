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

import warnings
from collections.abc import Mapping
from math import isclose
from pathlib import Path
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import Field, ValidationError, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import NonEmptyStr, PositiveInt
from hydromodpy.core.toml_io.paths import resolve_path


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

    @model_validator(mode="before")
    @classmethod
    def _normalize_payload(cls, value):
        if not isinstance(value, Mapping):
            return value
        payload = dict(value)
        genmtd_lay = str(payload.get("genmtd_lay", "constant")).strip().lower()
        if genmtd_lay in {"constant", "decay"} and payload.get("nlay") is not None:
            payload["nlay"] = _require_positive_int(payload.get("nlay"), name="nlay")
        if genmtd_lay == "decay" and payload.get("lay_decay") is not None:
            payload["lay_decay"] = float(payload["lay_decay"])
        if genmtd_lay == "list":
            if "nlay" in payload and payload.get("nlay") is not None:
                warnings.warn(
                    "nlay must not be provided when genmtd_lay='list' "
                    "(it is derived from lay_proportions). "
                    "Provided nlay will be ignored.",
                    UserWarning,
                    stacklevel=2,
                )
            payload["nlay"] = None
        return payload

    @model_validator(mode="after")
    def _validate_cross_fields(self):
        if self.genmtd_lay in ("constant", "decay"):
            _require_positive_int(self.nlay, name="nlay")
        if self.genmtd_lay == "decay":
            if self.lay_decay is None:
                raise ValueError("lay_decay is required when genmtd_lay='decay'")
            if self.lay_decay <= 1.0:
                raise ValueError("lay_decay must be > 1.0 when genmtd_lay='decay'")

        if self.genmtd_lay == "list":
            if self.lay_proportions is None:
                raise ValueError("lay_proportions is required when genmtd_lay='list'")
        return self

    @classmethod
    def from_mapping(cls, config_data: Mapping[str, Any]):
        payload = dict(config_data.get("sgrid", config_data))
        return cls.model_validate(payload)


class PlanarGridConfig(HydroModelBase):
    """Planar discretization contract for solver-facing grids."""

    mode: Annotated[Literal["keep_native", "resample_to_shape"], Profile.USER] = Field(
        default="keep_native",
        description=(
            "Planar solver-grid mode: keep the native domain support or "
            "resample to an explicit (ny, nx) target shape."
        ),
    )
    nx: Annotated[PositiveInt | None, Profile.USER] = Field(
        default=None,
        description="Target number of columns when planar mode is 'resample_to_shape'.",
    )
    ny: Annotated[PositiveInt | None, Profile.USER] = Field(
        default=None,
        description="Target number of rows when planar mode is 'resample_to_shape'.",
    )
    resampling: Annotated[Literal["bilinear", "average", "nearest"], Profile.DEV] = Field(
        default="bilinear",
        description="Resampling rule applied when planar mode is 'resample_to_shape'.",
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_payload(cls, value):
        if not isinstance(value, Mapping):
            return value
        payload = dict(value)
        mode = str(payload.get("mode", "keep_native")).strip().lower()
        if mode == "resample_to_shape":
            if payload.get("nx") is not None:
                payload["nx"] = _require_positive_int(payload.get("nx"), name="nx")
            if payload.get("ny") is not None:
                payload["ny"] = _require_positive_int(payload.get("ny"), name="ny")
        return payload

    @model_validator(mode="after")
    def _validate_cross_fields(self):
        if self.mode == "resample_to_shape":
            _require_positive_int(self.nx, name="nx")
            _require_positive_int(self.ny, name="ny")
        elif self.nx is not None or self.ny is not None:
            raise ValueError("nx and ny must be omitted when planar.mode='keep_native'")
        return self


class TopSamplingConfig(HydroModelBase):
    """How the DISV mesh top is sampled from the DEM before conditioning.

    MODFLOW 6 runtime-mesh only. The default 'centroid' mode samples the DEM at
    each Voronoi generator, which under-represents narrow incised channels that
    fall between generators (the generator lands on a bank, not the thalweg). The
    'zonal' mode reduces every DEM pixel inside a cell with a per-class statistic
    (a thalweg-preserving stat on channel pixels, an area stat on hillslope
    pixels), so channel cells keep their incised low. Ignored for structured
    grids, MODFLOW-NWT and Boussinesq. Every non-default value changes the
    calibration params_hash (config-scoped); when the sampling CODE changes, bump
    the version so the code-blind cache re-solves.
    """

    mode: Annotated[Literal["centroid", "zonal"], Profile.USER] = Field(
        default="centroid",
        description=(
            "Top-sampling strategy. 'centroid' samples the DEM at each cell "
            "generator (fast, the current behaviour, byte-identical default). "
            "'zonal' reduces every DEM pixel inside a cell with per-class stats."
        ),
    )
    hillslope_stat: Annotated[
        Literal["mean", "median", "min", "max", "p10", "p25"], Profile.USER
    ] = Field(
        default="median",
        description="Zonal statistic over non-channel (hillslope) pixels inside a cell.",
    )
    channel_stat: Annotated[Literal["min", "p10", "p25", "median", "mean"], Profile.USER] = Field(
        default="min",
        description=(
            "Zonal statistic over channel pixels inside a cell (thalweg-preserving; "
            "'min' keeps the incised low)."
        ),
    )
    channel_source: Annotated[Literal["none", "streams_raster"], Profile.USER] = Field(
        default="streams_raster",
        description=(
            "Where channel pixels come from when mode='zonal'. 'streams_raster' uses "
            "the delineated river-network raster reprojected onto the DEM grid; 'none' "
            "disables the channel class (every pixel is hillslope)."
        ),
    )
    channel_buffer_px: Annotated[int, Profile.DEV] = Field(
        default=0,
        ge=0,
        description=(
            "Dilate the channel pixel mask by this many pixels before reducing, to "
            "capture a channel that grazes a cell without a pixel centre on it."
        ),
    )
    spike_guard_tol_m: Annotated[float, Profile.DEV] = Field(
        default=2.0,
        ge=0.0,
        description=(
            "Revert a hillslope cell's zonal value to the centroid sample when it "
            "deviates more than this many metres (guards nodata/edge spikes); channel "
            "cells are exempt since they are lowered on purpose. 0 disables the guard."
        ),
    )
    min_pixels: Annotated[PositiveInt, Profile.DEV] = Field(
        default=3,
        description=(
            "Minimum DEM pixels inside a cell to trust a hillslope zonal statistic; "
            "below this the cell falls back to the centroid sample. A channel cell "
            "uses its channel stat from a single thalweg pixel."
        ),
    )
    min_thickness_m: Annotated[float, Profile.DEV] = Field(
        default=0.1,
        ge=0.0,
        description=(
            "Minimum layer-0 thickness (m) kept after zonal top lowering, so a carved "
            "channel top never collides with the aquifer bottom."
        ),
    )
    network_safety_net: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Before the priority-flood fill, carve the channel cells into a monotone "
            "descending thalweg (lower-only) and pin them so the fill never raises "
            "them. Fixes the fill re-raising a zonal-lowered channel; needs a channel "
            "source (mode='zonal' with channel_source!='none'). Off by default."
        ),
    )
    max_channel_lowering_m: Annotated[float, Profile.DEV] = Field(
        default=5.0,
        ge=0.0,
        description=(
            "Cap (m) on how far the network safety net may carve a single channel "
            "cell below its sampled top."
        ),
    )


class SolverSGridConfig(HydroModelBase):
    """Solver-facing grid configuration split into explicit planar and vertical parts."""

    planar: Annotated[PlanarGridConfig, Profile.USER] = Field(
        default_factory=PlanarGridConfig,
        description="Planar discretization of the solver grid.",
    )
    vertical: Annotated[VerticalGridConfig, Profile.USER] = Field(
        default_factory=VerticalGridConfig,
        description="Vertical layering of the solver grid.",
    )
    grid_dual: Annotated[Literal["voronoi", "triangle"], Profile.USER] = Field(
        default="voronoi",
        description=(
            "Applies only to a MODFLOW 6 run on a runtime gmsh mesh; ignored for "
            "structured grids, MODFLOW-NWT and Boussinesq (which keeps its own "
            "triangulation). 'voronoi' uses the PEBI dual (exact CVFD "
            "orthogonality, ~half the cells) and is the default; 'triangle' keeps "
            "the triangulation cells as the DISV grid for simplex comparison runs."
        ),
    )
    condition_top: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "MODFLOW 6 runtime-mesh only. Hydro-condition the DISV mesh top so it "
            "holds no closed depression. Sampling the DEM at irregular Voronoi cell "
            "centroids reintroduces local minima (pits) the raster fill removed. "
            "When true, a priority-flood epsilon fill on the mesh face graph raises "
            "only pit cells to their spill level, giving every active non-lake cell "
            "a strictly descending path to the domain boundary. Lake and boundary "
            "cells are fixed base levels; the aquifer bottom is untouched. Default "
            "false keeps the raw projected top."
        ),
    )
    condition_top_epsilon: Annotated[float, Profile.USER] = Field(
        default=1e-3,
        ge=0.0,
        description=(
            "Minimal downhill increment (m) added along each filled path so "
            "conditioned cells strictly descend instead of forming flats. Only "
            "used when condition_top is true."
        ),
    )
    top_sampling: Annotated[TopSamplingConfig, Profile.USER] = Field(
        default_factory=TopSamplingConfig,
        description="How the runtime-mesh top is sampled from the DEM before conditioning.",
    )

    @classmethod
    def from_mapping(cls, config_data: Mapping[str, Any]):
        payload = dict(config_data.get("sgrid", config_data))
        return cls.model_validate(payload)


class BottomFromFilepath(HydroModelBase):
    """Bottom surface read from a raster file."""

    kind: Annotated[Literal["filepath"], Profile.USER] = "filepath"
    path: Annotated[NonEmptyStr, Profile.USER] = Field(
        ...,
        description="Path to bottom raster used as model bottom surface.",
    )

    @field_validator("path")
    @classmethod
    def _expand_user(cls, value):
        return str(Path(value).expanduser())

    @model_validator(mode="after")
    def _check_exists(self):
        if not Path(self.path).exists():
            raise ValueError(f"File does not exist: {self.path}")
        return self


class BottomFromRaster(HydroModelBase):
    """Bottom surface provided as in-memory raster array."""

    kind: Annotated[Literal["raster"], Profile.USER] = "raster"
    raster: Annotated[Any, Profile.USER] = Field(
        ...,
        description="In-memory bottom raster array.",
    )

    @field_validator("raster")
    @classmethod
    def _check_not_none(cls, value):
        if value is None:
            raise ValueError("bottom.raster must not be None when kind='raster'")
        return value


class BottomConstantThickness(HydroModelBase):
    """Bottom surface defined by a constant thickness below top."""

    kind: Annotated[Literal["constant_thickness"], Profile.USER] = "constant_thickness"
    thick: Annotated[float, Profile.USER] = Field(
        ...,
        description="Domain thickness (top minus bottom, in metres).",
    )


class BottomConstantAltitude(HydroModelBase):
    """Bottom surface defined by a constant absolute altitude."""

    kind: Annotated[Literal["constant_altitude"], Profile.USER] = "constant_altitude"
    zbot: Annotated[float, Profile.USER] = Field(
        ...,
        description="Constant bottom elevation (metres).",
    )


BottomConfig: TypeAlias = Annotated[
    BottomFromFilepath | BottomFromRaster | BottomConstantThickness | BottomConstantAltitude,
    Field(discriminator="kind", description="Bottom-surface kind discriminator."),
]
"""Discriminated union of bottom-surface generation methods."""


class LayeringConstant(HydroModelBase):
    """Uniform layer thickness across the vertical extent."""

    kind: Annotated[Literal["constant"], Profile.USER] = "constant"
    nlay: Annotated[PositiveInt, Profile.USER] = Field(
        ...,
        description="Number of model layers.",
    )


class LayeringDecay(HydroModelBase):
    """Layers thicker with depth following a geometric decay."""

    kind: Annotated[Literal["decay"], Profile.USER] = "decay"
    nlay: Annotated[PositiveInt, Profile.USER] = Field(
        ...,
        description="Number of model layers.",
    )
    lay_decay: Annotated[float, Profile.DEV] = Field(
        ...,
        gt=1.0,
        description="Decay exponent (>1) for progressively thicker layers with depth.",
    )


class LayeringList(HydroModelBase):
    """Explicit per-layer thickness fractions."""

    kind: Annotated[Literal["list"], Profile.USER] = "list"
    lay_proportions: Annotated[list[float], Profile.DEV] = Field(
        ...,
        description="Per-layer thickness fractions (must sum to 1).",
    )

    @field_validator("lay_proportions")
    @classmethod
    def _validate_lay_proportions(cls, value):
        arr = [float(v) for v in list(value)]
        if len(arr) == 0:
            raise ValueError("lay_proportions cannot be empty")
        if any(v <= 0 for v in arr):
            raise ValueError("lay_proportions values must be strictly positive")
        if not isclose(sum(arr), 1.0, rel_tol=0.0, abs_tol=1e-6):
            raise ValueError("lay_proportions must sum to 1.0")
        return arr


LayeringConfig: TypeAlias = Annotated[
    LayeringConstant | LayeringDecay | LayeringList,
    Field(discriminator="kind", description="Layering kind discriminator."),
]
"""Discriminated union of vertical-layering methods."""


class SGridConfig(HydroModelBase):
    """
    Single source of truth for structured-grid configuration validation.

    Each field below maps one explicit model parameter with constrained type and
    semantic description. Cross-field dependencies are validated in
    ``_validate_cross_fields``.

    All geometric quantities are interpreted in SI metres.
    """

    sgrid_type: Annotated[Literal["structured"], Profile.USER] = Field(
        default="structured",
        description="Spatial grid family. Only 'structured' is supported.",
    )
    genmtd_top: Annotated[Literal["filepath"], Profile.USER] = Field(
        default="filepath",
        description="Method used to define top surface. Currently only raster filepath is supported.",
    )
    top_path: Annotated[NonEmptyStr, Profile.USER] = Field(
        ...,
        description="Path to top DEM raster used as model top surface.",
    )
    crs: Annotated[NonEmptyStr | None, Profile.USER] = Field(
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
    nx: Annotated[PositiveInt | None, Profile.USER] = Field(
        default=None,
        description="Target number of columns when plan_discretization_mode='resample_to_shape'.",
    )
    ny: Annotated[PositiveInt | None, Profile.USER] = Field(
        default=None,
        description="Target number of rows when plan_discretization_mode='resample_to_shape'.",
    )

    bottom: Annotated[BottomConfig, Profile.USER] = Field(
        ...,
        description="Bottom-surface generation method (discriminated by 'kind').",
    )
    layering: Annotated[LayeringConfig, Profile.USER] = Field(
        ...,
        description="Vertical-layering method (discriminated by 'kind').",
    )

    nodata: Annotated[float, Profile.DEV] = Field(
        default=-9999.0,
        description="No-data sentinel value used to mask invalid raster cells.",
    )

    @field_validator("top_path")
    @classmethod
    def _expand_user_in_paths(cls, value):
        if value is None:
            return None
        return str(Path(value).expanduser())

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

        top = Path(self.top_path)
        if not top.exists():
            raise ValueError(f"File does not exist: {top}")

        return self

    @classmethod
    def from_mapping(cls, config_data: Mapping[str, Any]):
        """Validate and build from a mapping or top-level ``sgrid`` mapping."""
        payload = dict(config_data.get("sgrid", config_data))
        return cls.model_validate(payload)

    @classmethod
    def from_toml(cls, config_path: str | Path):
        """Load TOML, resolve relative paths, then validate."""
        from hydromodpy.core.toml_io.loader import load_toml_with_base_config

        path = Path(config_path).expanduser().resolve()
        payload = load_toml_with_base_config(path)

        if not isinstance(payload, Mapping) or "sgrid" not in payload:
            raise ValueError(f"Invalid sgrid configuration in {path}: missing [sgrid] section")

        cfg = dict(payload["sgrid"])
        base = path.parent
        cfg["top_path"] = resolve_path(cfg["top_path"], base)
        bottom_section = cfg.get("bottom")
        if isinstance(bottom_section, Mapping) and bottom_section.get("path") is not None:
            bottom_data = dict(bottom_section)
            bottom_data["path"] = resolve_path(bottom_data["path"], base)
            cfg["bottom"] = bottom_data
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
