"""The DEM grid and the catchment a model is built on, read once from the delineation.

A backend that builds its grid on the DEM (NWT) reads ``RasterGeometry``, and
MODFLOW 6 reads it too for the DEM its routing is conditioned on. The rasters
of the generated river network are chosen once, before the solve, and kept in
``ChannelRasters``. ``CatchmentGeometry`` says where the catchment closes. The
arrays and paths are those of the delineation, never copies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hydromodpy.catchment.preprocess.geographic_config import GeographicConfig


@dataclass(frozen=True, slots=True)
class ChannelRasters:
    """The rasters of the generated river network A that this run reads.

    ``enabled`` says whether the river network step ran for this run.
    ``link``, ``pointer`` and ``accumulation`` are the full-extent rasters in
    the corrected-flow folder, chosen by the rule of ``active_channel_raster``,
    and ``None`` when the run has no such folder. They may not exist on disk,
    and the reader checks. ``clipped`` lists the rasters cut to the watershed
    that exist, the stream-link raster first. The zonal top sampling reads
    them when the full-extent link raster is missing.
    """

    enabled: bool
    link: str | None
    pointer: str | None
    accumulation: str | None
    clipped: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, eq=False)
class RasterGeometry:
    """The DEM grid of the run and the settings its routing DEM is conditioned with.

    ``dem_data`` and ``dem_box_buff_data`` are the DEM on the watershed and on
    its buffered box, in metres. ``dem_res`` is the pixel size in metres and
    ``xmin``, ``ymax`` the upper-left corner in the project CRS
    ``crs_proj``. ``watershed_buff_dem`` and ``watershed_box_buff_dem`` are
    the paths of the same two rasters. ``dem_correc_type``, ``terrain_engine``
    and ``capped_breach`` condition the DEM a solver routes on, as the
    delineation did. ``channel`` is ``None`` when no raster of A applies.
    """

    dem_data: Any
    dem_box_buff_data: Any
    dem_res: float | None
    xmin: float | None
    ymax: float | None
    watershed_buff_dem: str | None
    watershed_box_buff_dem: str | None
    crs_proj: Any
    dem_correc_type: str
    terrain_engine: str | None
    capped_breach: Any
    channel: ChannelRasters | None = None

    @classmethod
    def from_geographic(
        cls, geographic: object, *, channel: ChannelRasters | None = None
    ) -> RasterGeometry:
        """Read the grid off a delineation, synthetic or real, by attribute name.

        A missing attribute reads ``None``. A missing ``dem_correc_type`` reads
        the default of ``[geographic]``, so a solver conditions the DEM as the
        configuration would.
        """
        default_correction = GeographicConfig.model_fields["dem_correc_type"].default
        return cls(
            dem_data=getattr(geographic, "dem_data", None),
            dem_box_buff_data=getattr(geographic, "dem_box_buff_data", None),
            dem_res=getattr(geographic, "dem_res", None),
            xmin=getattr(geographic, "xmin", None),
            ymax=getattr(geographic, "ymax", None),
            watershed_buff_dem=getattr(geographic, "watershed_buff_dem", None),
            watershed_box_buff_dem=getattr(geographic, "watershed_box_buff_dem", None),
            crs_proj=getattr(geographic, "crs_proj", None),
            dem_correc_type=str(getattr(geographic, "dem_correc_type", default_correction)),
            terrain_engine=getattr(geographic, "terrain_engine", None),
            capped_breach=getattr(geographic, "capped_breach", None),
            channel=channel,
        )


@dataclass(frozen=True, slots=True)
class CatchmentGeometry:
    """Where the catchment of the run closes.

    ``catch_def`` is ``synthetic`` for a synthetic geographic, which closes no
    catchment. ``watershed_shp`` is the delineated polygon file.
    ``domain_extent`` is ``watershed`` when the model domain is the catchment.
    The outlet is ``(x_outlet_snapped, y_outlet_snapped)`` when the
    delineation snapped it, else the declared ``(x_outlet, y_outlet)``, in the
    project CRS ``crs``. The attribute names are those of the delineation, so
    a reader of one reads the other.
    """

    catch_def: str | None
    watershed_shp: str | None
    domain_extent: str | None
    x_outlet: float | None
    y_outlet: float | None
    x_outlet_snapped: float | None
    y_outlet_snapped: float | None
    crs: Any

    @classmethod
    def from_geographic(cls, geographic: object, *, crs: Any) -> CatchmentGeometry:
        """Read the catchment off a delineation by attribute name; a missing one reads ``None``."""
        return cls(
            catch_def=getattr(geographic, "catch_def", None),
            watershed_shp=getattr(geographic, "watershed_shp", None),
            domain_extent=getattr(geographic, "domain_extent", None),
            x_outlet=getattr(geographic, "x_outlet", None),
            y_outlet=getattr(geographic, "y_outlet", None),
            x_outlet_snapped=getattr(geographic, "x_outlet_snapped", None),
            y_outlet_snapped=getattr(geographic, "y_outlet_snapped", None),
            crs=crs,
        )


__all__ = ["CatchmentGeometry", "ChannelRasters", "RasterGeometry"]
