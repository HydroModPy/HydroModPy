"""Pydantic configuration of the solver top sampling, the ``sgrid`` table of a MODFLOW backend.

The planar grid is the mesh of ``[mesh]`` and the layering is ``[domain.layers]``. The
``sgrid`` table only says how the top of the solver grid is sampled from the DEM.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import PositiveInt


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
        json_schema_extra=field_metadata(unit="pixel"),
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
        json_schema_extra=field_metadata(unit="-"),
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
    "vertical": (
        "[domain.layers]: the layering describes the aquifer, so one table serves every "
        "solver. Move the table there, or run hmp doctor --fix-config"
    ),
}


class SolverSGridConfig(HydroModelBase):
    """Solver-facing grid configuration: how the top of the grid is sampled.

    The planar grid is the mesh of ``[mesh]`` and the layering is ``[domain.layers]``,
    neither a key of this table.
    """

    top_sampling: Annotated[TopSamplingConfig, Profile.USER] = Field(
        default_factory=TopSamplingConfig,
        description="How the top of the solver grid is sampled from the DEM.",
    )

    @model_validator(mode="before")
    @classmethod
    def _name_the_mesh_section_of_a_retired_key(cls, data: Any) -> Any:
        """Refuse ``planar``, ``grid_dual`` and ``vertical`` and name the table that replaces them."""
        if isinstance(data, Mapping):
            for key, replacement in _RETIRED_SGRID_KEYS.items():
                if key in data:
                    raise ValueError(f"sgrid.{key} is replaced by {replacement}.")
        return data

    @classmethod
    def from_mapping(cls, config_data: Mapping[str, Any]):
        payload = dict(config_data.get("sgrid", config_data))
        return cls.model_validate(payload)
