"""Runtime object exposing a synthetic geographic contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_origin
from pyproj import Transformer
from shapely.geometry import box

from hydromodpy.spatial.raster_support import RasterSupport
from hydromodpy.spatial.surface import Surface
from hydromodpy.spatial.geographic.core.derived_features import (
    GeographicBoundaryFeatures,
    GeographicDerivedFeatures,
)
from hydromodpy.spatial.geographic.core.domain_geographic_pipeline import DomainGeographicContext
from hydromodpy.spatial.geographic.core.river_network import RiverNetworkProducts
from hydromodpy.spatial.geographic.synthetic.config import SyntheticGeographicConfig
from hydromodpy.spatial.geographic.synthetic.topography import build_topography_values


@dataclass(frozen=True)
class SyntheticGeographicPaths:
    """Canonical artefact paths written for one synthetic geographic context."""

    root_dir: Path
    watershed_shp: Path
    watershed_buff_shp: Path
    watershed_box_shp: Path
    watershed_box_buff_shp: Path
    watershed_contour_shp: Path
    watershed_dem: Path
    watershed_buff_dem: Path
    watershed_box_buff_dem: Path
    watershed_contour_tif: Path


def _build_paths(root_dir: Path) -> SyntheticGeographicPaths:
    """Return canonical output paths used by the synthetic context."""
    return SyntheticGeographicPaths(
        root_dir=root_dir,
        watershed_shp=root_dir / "watershed.shp",
        watershed_buff_shp=root_dir / "watershed_buff.shp",
        watershed_box_shp=root_dir / "watershed_box.shp",
        watershed_box_buff_shp=root_dir / "watershed_box_buff.shp",
        watershed_contour_shp=root_dir / "watershed_contour.shp",
        watershed_dem=root_dir / "watershed_dem.tif",
        watershed_buff_dem=root_dir / "watershed_buff_dem.tif",
        watershed_box_buff_dem=root_dir / "watershed_box_buff_dem.tif",
        watershed_contour_tif=root_dir / "watershed_contour.tif",
    )


def _remove_existing_shapefile(path: Path) -> None:
    """Delete all companion files of a shapefile before rewriting it."""
    for suffix in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
        candidate = path.with_suffix(suffix)
        if candidate.exists():
            candidate.unlink()


def _resolve_lon_lat_metadata(
    *,
    crs_project: str,
    xmin: float,
    xmax: float,
    ymin: float,
    ymax: float,
    centroid: list[float],
) -> dict[str, object]:
    """Project synthetic bounds/centroid to WGS84 for legacy data-managers."""
    transformer = Transformer.from_crs(crs_project, "EPSG:4326", always_xy=True)

    centroid_lon, centroid_lat = transformer.transform(centroid[0], centroid[1])
    ur_lon, ur_lat = transformer.transform(xmax, ymax)
    ul_lon, ul_lat = transformer.transform(xmin, ymax)
    lr_lon, lr_lat = transformer.transform(xmax, ymin)
    ll_lon, ll_lat = transformer.transform(xmin, ymin)

    centroid_long_lat = (centroid_lon, centroid_lat)
    centroid_long_lat_greenwich = [centroid_lon, centroid_lat]
    if centroid_long_lat_greenwich[1] < 0.0:
        centroid_long_lat_greenwich[1] += 360.0

    return {
        "centroid_long_lat": centroid_long_lat,
        "ur_long_lat": (ur_lon, ur_lat),
        "ul_long_lat": (ul_lon, ul_lat),
        "lr_long_lat": (lr_lon, lr_lat),
        "ll_long_lat": (ll_lon, ll_lat),
        "centroid_long_lat_Greenwich": centroid_long_lat_greenwich,
    }


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
        workspace: object | None = None,
    ) -> None:
        if not isinstance(config, SyntheticGeographicConfig):
            raise TypeError("config must be a SyntheticGeographicConfig instance")

        self.config = config
        self.output_dir = Path(output_dir).resolve()
        self.workspace = workspace
        self.paths = _build_paths(self.output_dir)

        self.catch_def = "synthetic"
        self.zone_kind = "uniform"
        self.x_outlet = None
        self.y_outlet = None
        self.crs_proj = str(config.grid.crs)
        self.dep_code = None

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
        self.dem_buff_data = values.copy()
        self.dem_data = values.copy()
        self.depressions_data = np.zeros_like(values, dtype=float)

        self.dem_res = float(grid.dx)
        self.dx = float(grid.dx)
        self.dy = float(grid.dy)
        self.resolution = float(grid.dx)
        self.resolution_x = float(grid.dx)
        self.resolution_y = float(grid.dy)
        self.xmin = float(grid.xmin)
        self.xmax = float(grid.xmax)
        self.ymin = float(grid.ymin)
        self.ymax = float(grid.ymax)
        self.nodata = float(grid.nodata)
        self.catch_area = float(values.size * grid.dx * grid.dy / 1_000_000.0)
        self.x_pixel = int(values.shape[1])
        self.y_pixel = int(values.shape[0])

        transform = from_origin(self.xmin, self.ymax, self.dem_res, self.dem_res)
        self.geodata = transform.to_gdal()
        self.x_coord = np.linspace(1, self.x_pixel, self.x_pixel) * self.dem_res + self.xmin
        self.y_coord = self.ymax - (np.linspace(1, self.y_pixel, self.y_pixel) * self.dem_res)
        self.centroid = [
            self.xmin + (self.x_pixel * self.dem_res / 2.0),
            self.ymax - (self.y_pixel * self.dem_res / 2.0),
        ]
        lon_lat_metadata = _resolve_lon_lat_metadata(
            crs_project=self.crs_proj,
            xmin=self.xmin,
            xmax=self.xmax,
            ymin=self.ymin,
            ymax=self.ymax,
            centroid=self.centroid,
        )
        self.centroid_long_lat = lon_lat_metadata["centroid_long_lat"]
        self.ur_long_lat = lon_lat_metadata["ur_long_lat"]
        self.ul_long_lat = lon_lat_metadata["ul_long_lat"]
        self.lr_long_lat = lon_lat_metadata["lr_long_lat"]
        self.ll_long_lat = lon_lat_metadata["ll_long_lat"]
        self.centroid_long_lat_Greenwich = lon_lat_metadata["centroid_long_lat_Greenwich"]

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._hydrate_workspace_paths()
        self._write_rasters(values, transform=transform)
        self._write_polygons_and_contour(transform=transform)

        self.watershed_shp = str(self.paths.watershed_shp)
        self.watershed_buff_shp = str(self.paths.watershed_buff_shp)
        self.watershed_box_shp = str(self.paths.watershed_box_shp)
        self.watershed_contour_shp = str(self.paths.watershed_contour_shp)
        self.box_buff = str(self.paths.watershed_box_buff_shp)
        self.box_buff_shp = str(self.paths.watershed_box_buff_shp)
        self.watershed_dem = str(self.paths.watershed_dem)
        self.watershed_buff_dem = str(self.paths.watershed_buff_dem)
        self.watershed_box_buff_dem = str(self.paths.watershed_box_buff_dem)
        self.watershed_contour_tif = str(self.paths.watershed_contour_tif)
        self._river_network_products = RiverNetworkProducts(enabled=False)
        self.river_mesh_trace = None

    def _hydrate_workspace_paths(self) -> None:
        """Expose legacy workspace-derived paths expected by post-processors."""
        catch_folder = Path(getattr(self.workspace, "project_root", self.output_dir.parent))

        self.out_dir_path = str(catch_folder)
        self.add_data_folder = str(catch_folder / "add_data")
        self.figure_folder = str(getattr(self.workspace, "figure_folder", catch_folder / "figures"))
        self.geographic_path = str(self.output_dir)

    def _write_rasters(self, values: np.ndarray, *, transform) -> None:
        """Write the synthetic DEM to the canonical raster locations."""
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

    def _write_polygons_and_contour(self, *, transform) -> None:
        """Write the rectangular polygons and their boundary to canonical files."""
        polygon = box(self.xmin, self.ymin, self.xmax, self.ymax)
        frame = gpd.GeoDataFrame(
            data={"id": [1]},
            geometry=[polygon],
            crs=self.crs_proj,
        )
        for shp_path in (
            self.paths.watershed_shp,
            self.paths.watershed_buff_shp,
            self.paths.watershed_box_shp,
            self.paths.watershed_box_buff_shp,
        ):
            _remove_existing_shapefile(shp_path)
            frame.to_file(shp_path)

        contour = gpd.GeoDataFrame(
            data={"id": [1]},
            geometry=frame.boundary,
            crs=self.crs_proj,
        )
        _remove_existing_shapefile(self.paths.watershed_contour_shp)
        contour.to_file(self.paths.watershed_contour_shp)

        contour_values = rasterize(
            [(geometry, 1.0) for geometry in contour.geometry],
            out_shape=(self.y_pixel, self.x_pixel),
            transform=transform,
            fill=0.0,
            dtype="float32",
        )
        profile = {
            "driver": "GTiff",
            "height": self.y_pixel,
            "width": self.x_pixel,
            "count": 1,
            "dtype": "float32",
            "crs": self.crs_proj,
            "transform": transform,
            "nodata": 0.0,
        }
        with rasterio.open(str(self.paths.watershed_contour_tif), "w", **profile) as dst:
            dst.write(contour_values, 1)

    def build_georeferencing(self) -> dict[str, object]:
        """Expose historical georeferencing metadata used by older consumers."""
        support = self.surface_topo.support
        if support is None:
            return {}
        return support.as_georeferencing_dict()

    def get_domain_surface_topo(self) -> Surface:
        """Return the synthetic topographic surface used to build the domain."""
        return self.surface_topo

    def get_geographic_derived_features(self) -> GeographicDerivedFeatures:
        """Return the canonical bundle of derived geographic artifacts."""
        return GeographicDerivedFeatures(
            surface_topo=self.get_domain_surface_topo(),
            boundaries=GeographicBoundaryFeatures(
                watershed_shp=str(self.paths.watershed_shp),
                watershed_box_shp=str(self.paths.watershed_box_shp),
                box_buff_shp=str(self.paths.watershed_box_buff_shp),
            ),
            rivers=self._river_network_products,
            catchment_area_km2=float(self.catch_area),
            catch_def=str(self.catch_def),
            x_outlet=None,
            y_outlet=None,
            zone_kind=str(self.zone_kind),
            watershed_box_buff_dem=str(self.paths.watershed_box_buff_dem),
            regional_dem_path=str(self.paths.watershed_box_buff_dem),
        )

    def get_domain_geographic_context(self) -> DomainGeographicContext:
        """Return the narrow V2 context consumed by ``Domain`` binders."""
        return self.get_geographic_derived_features().to_domain_geographic_context()


def build_synthetic_geographic(
    *,
    config: SyntheticGeographicConfig,
    output_dir: str | Path,
    workspace: object | None = None,
) -> SyntheticGeographic:
    """Build one synthetic geographic runtime object."""
    return SyntheticGeographic(config=config, output_dir=output_dir, workspace=workspace)
