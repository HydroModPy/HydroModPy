"""Pydantic configuration of the solver grid: vertical layering and top sampling.

The planar grid is the mesh of ``[mesh]``. This module only holds the ``sgrid`` table of a
MODFLOW backend.
"""

from __future__ import annotations

import warnings
from collections.abc import Mapping
from math import isclose
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import PositiveInt
from hydromodpy.core.config_kit.visible_when import VisibleWhen


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
        description=(
            "How the aquifer thickness is split into layers: equal layers, layers that "
            "thicken with depth, or the fractions you list."
        ),
        json_schema_extra={
            "value_docs": {
                "constant": (
                    "Splits local thickness into nlay equal-fraction layers at every cell."
                ),
                "decay": (
                    "Grows layer thickness geometrically with depth when lay_decay is above one."
                ),
                "list": (
                    "Uses the explicit per-layer thickness fractions given in lay_proportions."
                ),
            }
        },
    )
    nlay: Annotated[int | None, Profile.USER] = Field(
        default=1,
        description=(
            "Number of layers for 'constant' and 'decay'. With 'list', the number of "
            "fractions sets it."
        ),
        json_schema_extra={"unit": "-"},
    )
    lay_decay: Annotated[float | None, Profile.USER, VisibleWhen("genmtd_lay", "decay")] = Field(
        default=None,
        description=(
            "Ratio of each layer's thickness to the thickness of the layer above it, "
            "above 1. With 2, each layer is twice as thick as the one above."
        ),
        examples=[2.0],
        json_schema_extra={"unit": "-"},
    )
    lay_proportions: Annotated[
        list[float] | None, Profile.USER, VisibleWhen("genmtd_lay", "list")
    ] = Field(
        default=None,
        description=(
            "Share of the thickness each layer takes, from the top. The shares must sum to 1."
        ),
        examples=[[0.2, 0.3, 0.5]],
        json_schema_extra={"unit": "-"},
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


class TopSamplingConfig(HydroModelBase):
    """How the top of the solver grid is sampled from the DEM.

    Applies to the MODFLOW 6 runtime mesh and to a structured grid coarser than
    its DEM (``[mesh] cell_size`` or ``[mesh.regular] shape``). The default 'centroid' mode
    samples the DEM at each Voronoi generator, or resamples it to the grid, which
    under-represents narrow incised channels (the sample lands on a bank, not the
    thalweg). The 'zonal' mode reduces every DEM pixel inside a cell with a
    per-class statistic (a thalweg-preserving stat on channel pixels, an area stat
    on hillslope pixels), so channel cells keep their incised low. A structured
    grid whose cells are the DEM pixels already holds the pixel
    values and is unchanged. Only the top is zonal; the bottom keeps its rule. On
    a structured grid the idomain does not move, and zonal applies only when a cell
    covers at least two DEM pixels. MODFLOW-NWT builds no channel mask, so a zonal
    top there needs ``channel_source = "none"`` (median only), and the config load
    refuses the other value. Boussinesq ignores it. Every
    non-default value changes the calibration params_hash (config-scoped); when
    the sampling CODE changes, bump the version so the code-blind cache re-solves.
    """

    mode: Annotated[Literal["centroid", "zonal"], Profile.USER] = Field(
        default="centroid",
        description=(
            "Top-sampling strategy. 'centroid' samples the DEM at each cell "
            "generator, or resamples it to a structured grid (fast, the default). "
            "On a mesh that publishes a lateral offset for a river cell (the "
            "river runs through the cell but beside its centre, as where a "
            "contact line crosses it or two thalwegs share it), that cell takes "
            "the lowest DEM pixel it covers. 'zonal' reduces every DEM pixel "
            "inside a cell with per-class stats."
        ),
    )
    hillslope_stat: Annotated[
        Literal["mean", "median", "min", "max", "p10", "p25"], Profile.USER
    ] = Field(
        default="median",
        description="Zonal statistic over non-channel (hillslope) pixels inside a cell.",
        json_schema_extra={
            "value_docs": {
                "mean": "Averages every hillslope pixel in the cell to set its top elevation.",
                "median": "Uses the median hillslope pixel elevation, robust to outlier pixels.",
                "min": "Uses the lowest hillslope pixel elevation found inside the cell.",
                "max": "Uses the highest hillslope pixel elevation found inside the cell.",
                "p10": "Uses the 10th percentile of hillslope pixel elevations inside the cell.",
                "p25": "Uses the 25th percentile of hillslope pixel elevations inside the cell.",
            }
        },
    )
    channel_stat: Annotated[Literal["min", "p10", "p25", "median", "mean"], Profile.USER] = Field(
        default="min",
        description=(
            "Zonal statistic over channel pixels inside a cell (thalweg-preserving; "
            "'min' keeps the incised low)."
        ),
        json_schema_extra={
            "value_docs": {
                "min": "Uses the lowest channel pixel elevation, keeping the incised thalweg low.",
                "p10": (
                    "Uses the 10th percentile of channel pixel elevations, near the thalweg low."
                ),
                "p25": (
                    "Uses the 25th percentile of channel pixel elevations, above the thalweg low."
                ),
                "median": (
                    "Uses the median channel pixel elevation, less aggressive than the thalweg low."
                ),
                "mean": "Averages channel pixel elevations, smoothing over the incised thalweg.",
            }
        },
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
            "Minimum column thickness (m) kept under a zonal top lowered by a channel "
            "or a crossing. On a mesh of polygons the bottom of a cell whose lowered top "
            "leaves less than this, or less than a tenth of the column its centre sample "
            "gave, moves down with it and keeps the thickness of the cell-centre sample; "
            "on a regular grid the top is raised back instead."
        ),
    )


_RETIRED_SGRID_KEYS = {
    "planar": (
        "[mesh]: write cell_size for a regular grid coarser than the DEM pixel, "
        "or [mesh.regular] shape = [nrow, ncol] for a fixed shape, and remove the key "
        "to keep the DEM pixels"
    ),
    "grid_dual": (
        '[mesh] engine: write engine = "voronoi" for the dual cells or '
        'engine = "triangle" for the triangulation cells'
    ),
}


class SolverSGridConfig(HydroModelBase):
    """Solver-facing grid configuration: vertical layering and top sampling.

    The planar grid is the mesh of ``[mesh]``, not a key of this table.
    """

    vertical: Annotated[VerticalGridConfig, Profile.USER] = Field(
        default_factory=VerticalGridConfig,
        description="Vertical layering of the solver grid.",
    )
    top_sampling: Annotated[TopSamplingConfig, Profile.USER] = Field(
        default_factory=TopSamplingConfig,
        description="How the top of the solver grid is sampled from the DEM.",
    )

    @model_validator(mode="before")
    @classmethod
    def _name_the_mesh_section_of_a_retired_key(cls, data: Any) -> Any:
        """Refuse ``planar`` and ``grid_dual`` and name the ``[mesh]`` key that replaces them."""
        if isinstance(data, Mapping):
            for key, replacement in _RETIRED_SGRID_KEYS.items():
                if key in data:
                    raise ValueError(f"sgrid.{key} is replaced by {replacement}.")
        return data

    @classmethod
    def from_mapping(cls, config_data: Mapping[str, Any]):
        payload = dict(config_data.get("sgrid", config_data))
        return cls.model_validate(payload)
