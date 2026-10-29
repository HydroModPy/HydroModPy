"""Shared builders for the site selection tests."""

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.spatial.geographic.core.catchment_from_point import CatchmentFromPointProducts
from hydromodpy.spatial.geographic.core.flow_products import FlowProducts
from hydromodpy.spatial.site_selection.config.site_selection_config import SiteSelectionConfig
from tests._helpers.geotiffs import write_geotiff
from tests._helpers.terrain_doubles import fake_flow_products


def write_feature_collection_geojson(
    path: Path, *, geometry: dict[str, Any], properties: dict[str, Any] | None = None
) -> Path:
    feature = {"type": "Feature", "geometry": geometry, "properties": properties or {}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [feature]}), "utf-8")
    return path


def write_point_geojson(
    path: Path, *, coordinates: list[float], properties: dict[str, Any] | None = None
) -> Path:
    geometry = {"type": "Point", "coordinates": coordinates}
    return write_feature_collection_geojson(path, geometry=geometry, properties=properties)


def write_polygon_geojson(
    path: Path, *, coordinates: list[list[float]], properties: dict[str, Any] | None = None
) -> Path:
    geometry = {"type": "Polygon", "coordinates": [coordinates]}
    return write_feature_collection_geojson(path, geometry=geometry, properties=properties)


def write_square_geojson(
    path: Path,
    *,
    size: float = 10.0,
    x0: float = 0.0,
    y0: float = 0.0,
    properties: dict[str, Any] | None = None,
) -> Path:
    x1, y1 = x0 + size, y0 + size
    corners = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
    return write_polygon_geojson(path, coordinates=corners, properties=properties)


def make_point_record(
    station_id: str = "J123456701",
    *,
    x: float = 0.0,
    y: float = 0.0,
    crs: str = "EPSG:2154",
    metadata: dict[str, object] | None = None,
    n_values: int = 1,
    source: str = "hubeau",
    with_location: bool = True,
) -> PointRecord:
    start = datetime(2020, 1, 1)
    days = [start + timedelta(days=day) for day in range(n_values)]
    values = [float(day + 1) for day in range(n_values)]
    station_metadata = {"station_name": f"Station {station_id}", **(metadata or {})}
    location = StationLocation(id=station_id, x=x, y=y, crs=crs, metadata=station_metadata)
    return PointRecord(
        station_id=station_id,
        variable="discharge",
        source=source,
        unit="m3/s",
        frequency="D",
        data=pd.DataFrame({"datetime": days, "value": values}),
        date_start=start,
        date_end=start + timedelta(days=max(n_values, 1) - 1),
        location=location if with_location else None,
    )


def make_record(station_id: str, *, x: float = 350000.0, y: float = 6810000.0):
    return make_point_record(station_id, x=x, y=y, n_values=2)


def make_wgs84_hubeau_record(station_id: str):
    metadata = {"x_l93": "352000.0", "y_l93": "6812000.0"}
    return make_point_record(
        station_id, x=-1.65, y=48.12, crs="EPSG:4326", n_values=2, metadata=metadata
    )


def make_config(tmp_path: Path) -> SiteSelectionConfig:
    strategy = {"principle": "observation_led", "profile": "gauged_downstream_station"}
    payload = {
        "selection_id": "observed_demo",
        "output_root": tmp_path / "out",
        "strategy": {**strategy, "primary_observation_type": "flow_station"},
        "territory": {"mode": "admin_regions", "country": "FR", "regions": ["Bretagne"]},
        "dem": {"source": "custom", "path": tmp_path / "dem.tif"},
        "outlets": {"candidate_mode": "station_outlets", "snap_dist_m": 150},
    }
    return SiteSelectionConfig.model_validate(payload)


def write_accumulation_raster(path: Path, values: np.ndarray, *, cell_size: float = 10.0) -> Path:
    return write_geotiff(path, values, cell=cell_size, nodata=-9999.0, dtype="float64")


# site selection: config, candidates, hydrology, runner

BRETAGNE = {"mode": "admin_regions", "country": "FR", "regions": ["Bretagne"]}
SELECTION_PROFILES: dict[str, dict[str, Any]] = {
    "area_only": {
        "strategy": {"principle": "criteria_crossing", "profile": "area_only", "primary_axes": ["area"]},
        "criteria": {"area": {"mode": "hard_reject", "hard_min_area_km2": 75.0, "hard_max_area_km2": 125.0}},
    },
    "gauged": {
        "strategy": {"principle": "observation_led", "profile": "gauged_downstream_station",
                     "primary_observation_type": "flow_station"},
        "outlets": {"candidate_mode": "station_outlets"},
    },
    "custom": {},
}  # fmt: skip


def selection_section(profile: str = "area_only", **tables: Any) -> dict[str, Any]:
    """A ``[site_selection]`` table: a profile, Bretagne, then the given tables.

    A dict value is merged into the table of the same name, any other value
    replaces the key.
    """
    section: dict[str, Any] = {"selection_id": "demo", "output_root": "out", "territory": BRETAGNE}
    for name, table in SELECTION_PROFILES[profile].items():
        section[name] = dict(table)
    for name, value in tables.items():
        if isinstance(value, dict) and isinstance(section.get(name), dict):
            section[name] = {**section[name], **value}
        else:
            section[name] = value
    return section


def write_selection_toml(folder: Path, section: dict[str, Any], **top: Any) -> Path:
    """Write ``selection.toml`` with ``[site_selection]`` and other top sections."""
    import tomlkit

    def plain(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: plain(item) for key, item in value.items() if item is not None}
        if isinstance(value, list | tuple):
            return [plain(item) for item in value]
        return str(value) if isinstance(value, Path) else value

    path = folder / "selection.toml"
    path.write_text(tomlkit.dumps(plain({"site_selection": section, **top})), encoding="utf-8")
    return path


def flow_spy(calls: dict[str, Any] | None = None, **paths: Any) -> Callable[..., FlowProducts]:
    """Flow products builder that records its arguments and names *paths*."""

    def build(**kwargs: Any) -> FlowProducts:
        if calls is not None:
            calls.update(kwargs)
        return fake_flow_products(**paths)

    return build


def delineation_spy(
    calls: list[dict[str, Any]] | None = None, *, size: float | None = None
) -> Callable[..., CatchmentFromPointProducts]:
    """Delineation builder that records each call.

    With *size* it writes a square watershed of that side, else it only names one.
    """

    def build(**kwargs: Any) -> CatchmentFromPointProducts:
        if calls is not None:
            calls.append(kwargs)
        out = Path(kwargs["output_dir"])
        watershed = out / ("watershed.geojson" if size else "watershed.shp")
        if size:
            write_square_geojson(watershed, size=size)
        return CatchmentFromPointProducts(
            outlet_shp=str(out / "outlet.shp"),
            outlet_snap_shp=str(out / "outlet_snap.shp"),
            watershed_tif=str(out / "watershed.tif"),
            watershed_shp=str(watershed),
        )

    return build


def site_flow_products(acc: Path | str, *, threshold_km2: float = 0.0001):
    """Site-selection flow products whose accumulation raster is *acc*."""
    from hydromodpy.spatial.site_selection.hydrology.flow_products import (
        SiteSelectionFlowProducts,
    )

    return SiteSelectionFlowProducts(
        products=fake_flow_products(acc=str(acc)),
        method="dem_only",
        flow_algorithm="d8",
        dem_correction_type="fill",
        network_threshold_area_km2=threshold_km2,
        compute_strahler=True,
    )


def dem_loader_spy(dem: Path, calls: list[dict[str, Any]] | None = None) -> Callable[..., list]:
    """DEM loader that records its arguments and returns *dem* as the one field."""
    from hydromodpy.data.contracts.spatial_field import FieldRecord

    def load(**kwargs: Any) -> list[FieldRecord]:
        if calls is not None:
            calls.append(kwargs)
        return [
            FieldRecord(
                variable="dem",
                source="custom",
                unit="m",
                data=dem,
                bbox=kwargs["project_extent"],
                crs="EPSG:2154",
            )
        ]

    return load


# site selection: evaluation, evidence, decisions, outputs

L93 = "EPSG:2154"


def make_catchment(
    site_id: str = "site_001",
    *,
    x: float = 0.0,
    y: float = 0.0,
    area_km2: float | None = 100.0,
    priority: float = 0.0,
    attributes: dict[str, Any] | None = None,
    source: str = "test",
    crs: str = L93,
    **fields: Any,
):
    """A delineated catchment whose outlet carries the site id as candidate id."""
    from hydromodpy.spatial.site_selection.domain.candidate_outlet import CandidateOutlet
    from hydromodpy.spatial.site_selection.domain.delineated_catchment import DelineatedCatchment

    outlet = CandidateOutlet(
        site_id, x, y, crs, source, priority=priority, attributes=dict(attributes or {})
    )
    return DelineatedCatchment(site_id=site_id, outlet=outlet, area_km2=area_km2, **fields)


def make_selection(selected=(), rejected=(), decisions=(), components=()):
    """A selection result built from plain sequences."""
    from hydromodpy.spatial.site_selection.evaluation.selection import SelectionResult

    return SelectionResult(list(selected), list(rejected), list(decisions), list(components))


def write_vector_layer(path: Path, geometries: list[Any], *, crs: str | None = L93, **columns):
    """Write shapely geometries and their columns as a vector file, driver from the suffix."""
    import geopandas as gpd

    path.parent.mkdir(parents=True, exist_ok=True)
    gpd.GeoDataFrame(columns or None, geometry=list(geometries), crs=crs).to_file(path)
    return path


X93, Y93 = 350_000.0, 6_810_000.0
"""A Lambert-93 point in Brittany: the south-west corner of the test basin."""


def to_wgs84(geometry: Any) -> Any:
    """The Lambert-93 *geometry* in WGS 84."""
    from pyproj import Transformer
    from shapely.ops import transform

    return transform(Transformer.from_crs(L93, "EPSG:4326", always_xy=True).transform, geometry)


def write_basin(directory: Path, kind: str = "l93") -> str | None:
    """The 100 m square basin at (X93, Y93), stored as *kind* says, or None for "none".

    "empty" holds one empty polygon, "no_rows" no feature at all.
    """
    from shapely.geometry import Polygon, box

    if kind == "none":
        return None
    square = box(X93, Y93, X93 + 100.0, Y93 + 100.0)
    geometries, crs = {
        "l93": ([square], L93),
        "wgs84": ([to_wgs84(square)], "EPSG:4326"),
        "no_crs": ([square], None),
        "empty": ([Polygon()], L93),
        "no_rows": ([], L93),
    }[kind]
    return str(write_vector_layer(directory / f"basin_{kind}.gpkg", geometries, crs=crs))


def make_basin_catchment(directory: Path, kind: str = "l93", **fields: Any):
    """A catchment of the test basin, its outlet 10 m inside the south-west corner."""
    return make_catchment(
        x=X93 + 10.0,
        y=Y93 + 10.0,
        area_km2=0.01,
        watershed_shp=write_basin(directory, kind),
        **fields,
    )


def run_selection(catchments, criteria: dict[str, Any], principle="criteria_crossing", **kwargs):
    """Select *catchments* under the *criteria* table; ``spatial`` holds the spatial table."""
    from hydromodpy.spatial.site_selection.config.criteria_config import CriteriaConfig
    from hydromodpy.spatial.site_selection.config.outlets_config import SpatialSelectionConfig
    from hydromodpy.spatial.site_selection.evaluation.selection import select_delineated_catchments

    return select_delineated_catchments(
        catchments,
        criteria=CriteriaConfig.model_validate(criteria),
        spatial_selection=SpatialSelectionConfig(**kwargs.pop("spatial", {})),
        selection_principle=principle,
        **kwargs,
    )


def component_of(result, criterion_id: str, site_id: str | None = None):
    """The first criteria component of *criterion_id* in *result*, for *site_id* if given."""
    return next(
        one
        for one in result.criteria_components
        if one.criterion_id == criterion_id and site_id in (None, one.site_id)
    )
