"""Runtime object exposing a synthetic geographic contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from hydromodpy.domain.raster_support import RasterSupport
from hydromodpy.domain.surface import Surface
from hydromodpy.geographic.core.domain_geographic_pipeline import DomainGeographicContext
from hydromodpy.geographic_synthethic.config import SyntheticGeographicConfig
from hydromodpy.geographic_synthethic.topography import build_topography_values


@dataclass(frozen=True)
class SyntheticGeographicPaths:
    """Canonical artefact paths written for one synthetic geographic context."""

    root_dir: Path
    watershed_shp: Path
    watershed_buff_shp: Path
    watershed_box_buff_shp: Path
    watershed_dem: Path
    watershed_buff_dem: Path
    watershed_box_buff_dem: Path


def _build_paths(root_dir: Path) -> SyntheticGeographicPaths:
    """Return canonical output paths used by the synthetic context."""
    return SyntheticGeographicPaths(
        root_dir=root_dir,
        watershed_shp=root_dir / "watershed.shp",
        watershed_buff_shp=root_dir / "watershed_buff.shp",
        watershed_box_buff_shp=root_dir / "watershed_box_buff.shp",
        watershed_dem=root_dir / "watershed_dem.tif",
        watershed_buff_dem=root_dir / "watershed_buff_dem.tif",
        watershed_box_buff_dem=root_dir / "watershed_box_buff_dem.tif",
    )


def _remove_existing_shapefile(path: Path) -> None:
    """Delete all companion files of a shapefile before rewriting it."""
    for suffix in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
        candidate = path.with_suffix(suffix)
        if candidate.exists():
            candidate.unlink()


class SyntheticGeographic:
    """Synthetic replacement for the historical geographic runtime object.

    The object intentionally exposes the subset of attributes still read by
    launchers, domain binders, and legacy flow solvers.
    """

    def __init__(
        self,
        *,
        config: SyntheticGeographicConfig,
        output_dir: str | Path,
    ) -> None:
        if not isinstance(config, SyntheticGeographicConfig):
            raise TypeError("config must be a SyntheticGeographicConfig instance")

        self.config = config
        self.output_dir = Path(output_dir).resolve()
        self.paths = _build_paths(self.output_dir)

        self.catch_def = "synthetic"
        self.zone_kind = "uniform"
        self.x_outlet = None
        self.y_outlet = None
        self.crs_proj = str(config.grid.crs)

        self._build()

    def _build(self) -> None:
        """Materialize the synthetic DEM support and its on-disk artefacts."""
        grid = self.config.grid
        values = build_topography_values(
            topography=self.config.topography,
            grid=grid,
        )

        support = RasterSupport(
            crs=str(grid.crs),
            dx=float(grid.dx),
            dy=float(grid.dy),
            xmin=float(grid.xmin),
            xmax=float(grid.xmax),
            ymin=float(grid.ymin),
            ymax=float(grid.ymax),
            nrows=int(grid.nrow),
            ncols=int(grid.ncol),
            nodata=float(grid.nodata),
        )

        self.surface_topo = Surface.from_geographic_dem(
            values,
            support=support,
            name="surface_topo",
        )

        self.dem_box_buff_data = values.copy()
        self.dem_data = values.copy()
        self.depressions_data = np.zeros_like(values, dtype=float)

        self.dem_res = float(grid.dx)
        self.xmin = float(grid.xmin)
        self.xmax = float(grid.xmax)
        self.ymin = float(grid.ymin)
        self.ymax = float(grid.ymax)
        self.catch_area = float(values.size * grid.dx * grid.dy / 1_000_000.0)

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._write_rasters(values)
        self._write_polygons()

        self.watershed_shp = str(self.paths.watershed_shp)
        self.watershed_buff_shp = str(self.paths.watershed_buff_shp)
        self.box_buff_shp = str(self.paths.watershed_box_buff_shp)
        self.watershed_dem = str(self.paths.watershed_dem)
        self.watershed_buff_dem = str(self.paths.watershed_buff_dem)
        self.watershed_box_buff_dem = str(self.paths.watershed_box_buff_dem)

    def _write_rasters(self, values: np.ndarray) -> None:
        """Write the synthetic DEM to the canonical raster locations."""
        transform = from_origin(self.xmin, self.ymax, self.dem_res, self.dem_res)
        profile = {
            "driver": "GTiff",
            "height": int(values.shape[0]),
            "width": int(values.shape[1]),
            "count": 1,
            "dtype": "float32",
            "crs": self.crs_proj,
            "transform": transform,
            "nodata": float(self.config.grid.nodata),
        }
        for raster_path in (
            self.paths.watershed_dem,
            self.paths.watershed_buff_dem,
            self.paths.watershed_box_buff_dem,
        ):
            with rasterio.open(str(raster_path), "w", **profile) as dst:
                dst.write(np.asarray(values, dtype=np.float32), 1)

    def _write_polygons(self) -> None:
        """Write one rectangular polygon to the canonical vector locations."""
        polygon = box(self.xmin, self.ymin, self.xmax, self.ymax)
        frame = gpd.GeoDataFrame(
            data={"id": [1]},
            geometry=[polygon],
            crs=self.crs_proj,
        )
        for shp_path in (
            self.paths.watershed_shp,
            self.paths.watershed_buff_shp,
            self.paths.watershed_box_buff_shp,
        ):
            _remove_existing_shapefile(shp_path)
            frame.to_file(shp_path)

    def build_georeferencing(self) -> dict[str, object]:
        """Expose historical georeferencing metadata used by older consumers."""
        support = self.surface_topo.support
        if support is None:
            return {}
        return support.as_georeferencing_dict()

    def get_domain_surface_topo(self) -> Surface:
        """Return the synthetic topographic surface used to build the domain."""
        return self.surface_topo

    def get_domain_geographic_context(self) -> DomainGeographicContext:
        """Return the narrow V2 context consumed by ``Domain`` binders."""
        return DomainGeographicContext(
            surface_topo=self.get_domain_surface_topo(),
            watershed_shp=str(self.paths.watershed_shp),
            catchment_area_km2=float(self.catch_area),
            catch_def=str(self.catch_def),
            x_outlet=None,
            y_outlet=None,
            watershed_box_buff_dem=str(self.paths.watershed_box_buff_dem),
            box_buff_shp=str(self.paths.watershed_box_buff_shp),
            zone_kind=str(self.zone_kind),
        )


def build_synthetic_geographic(
    *,
    config: SyntheticGeographicConfig,
    output_dir: str | Path,
) -> SyntheticGeographic:
    """Build one synthetic geographic runtime object."""
    return SyntheticGeographic(config=config, output_dir=output_dir)
