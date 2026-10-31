"""Shared cases of the geographic tests.

Each section belongs to the tests of one part of ``spatial/geographic``. A
section only adds to what is written here.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd

from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from tests._helpers import ground_bench as bench

# geographic core

LAMBERT = "EPSG:2154"


def write_features(
    path: Path | str, geometries: list, *, crs: str | None = LAMBERT, **columns: list
) -> Path:
    """Write *geometries* as a vector file (driver from the suffix) and return its path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = gpd.GeoDataFrame(
        {"id": list(range(1, len(geometries) + 1)), **columns}, geometry=geometries, crs=crs
    )
    frame.to_file(path, driver="GPKG" if path.suffix == ".gpkg" else None)
    return path


def outlet_config(
    dem: Path | str = "dem.tif",
    *,
    x: float,
    y: float,
    crs: str = LAMBERT,
    catchment: dict | None = None,
    **sections: object,
) -> GeographicConfig:
    """A validated outlet configuration on *dem*, with extra catchment keys and sections."""
    return GeographicConfig.model_validate(
        {
            "catchment": {
                "catch_def": "from_outlet_coord",
                "dem_init_path": dem,
                "x_outlet": x,
                "y_outlet": y,
                "buff_area": "10%",
                "snap_dist": "150 m",
                **(catchment or {}),
            },
            "crs_project": crs,
            **sections,
        }
    )


def bench_project(
    tmp_path: Path,
    crossings: gpd.GeoDataFrame | None,
    *,
    embankment_rows: tuple[int, ...] = (10,),
    height: float = 2.5,
    prune: bool = False,
    lakes: Path | None = None,
) -> SimpleNamespace:
    """The ground bench written as a project: rasters, network, crossings, config and setup.

    The config and setup are the duck-typed objects the ground files read. The
    stream raster sits where the river network writes its full-extent copy.
    """
    from hydromodpy.spatial.geographic.core.ground_corrections import FirstPassChannel

    valley = bench.build(embankment_rows=embankment_rows, height=height)
    work = tmp_path / "work"
    work.mkdir(parents=True, exist_ok=True)
    dem = tmp_path / "data" / "dem" / "dem.tif"
    dem.parent.mkdir(parents=True)
    bench.write_raster(dem, valley.dem)
    name = "dem_streams_pruned_full.tif" if prune else "dem_streams_full.tif"
    streams = bench.write_raster(work / name, valley.streams.astype("float32"))
    d8 = bench.write_raster(tmp_path / "d8.tif", valley.d8, dtype="int32")
    acc = bench.write_raster(tmp_path / "acc.tif", valley.acc)
    network = tmp_path / "network.shp"
    valley.network.to_file(network)
    path = None
    if crossings is not None:
        path = tmp_path / "crossings.gpkg"
        crossings.to_file(path, driver="GPKG")
    config = SimpleNamespace(
        crossings=SimpleNamespace(
            enabled=True,
            path=path,
            kinds=["road", "railway", "bridge"],
            notch_width=10.0,
            bed_reach=30.0,
            max_depth=3.0,
            snap_radius=30.0,
        ),
        enforce_lakes=SimpleNamespace(enabled=lakes is not None, lake_geometry_path=lakes),
        river_network=SimpleNamespace(prune_short_streams=prune),
        bed_regularization=SimpleNamespace(enabled=True, min_slope=1.0e-4),
    )
    setup = SimpleNamespace(
        dem_init_path=str(dem),
        crs_project=bench.CRS,
        paths=SimpleNamespace(
            correcflow_path=work, watershed_shp=None, box_buff=None, geographic_path=None
        ),
    )
    channel = FirstPassChannel(str(streams), str(d8), str(acc), str(network), 1.0)
    return SimpleNamespace(config=config, setup=setup, channel=channel, valley=valley, d8=d8)


# geographic pipeline

import json  # noqa: E402

import numpy as np  # noqa: E402
import rasterio  # noqa: E402
from shapely.geometry import box  # noqa: E402

from hydromodpy.core.state.paths import preprocessing_dir  # noqa: E402
from tests._helpers.geotiffs import write_geotiff  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCH_RIVER = {"enabled": True, "threshold_mode": "cells", "threshold_cells": 50}
"""A river network on the bench valley, its channel holds 21 cells."""
BENCH_CLIP_ORIGIN = (bench.RES, (bench.N - 1) * bench.RES)
"""West and north edges of the clips: the bench grid cropped by one pixel."""
BENCH_BLANK_COLS = 3
"""The watershed clip holds nodata on its first columns, off the channel."""


def read_band(path: Path | str) -> np.ndarray:
    """Return the first band of a raster."""
    with rasterio.open(path) as src:
        return src.read(1)


def bench_config(root: Path, *, dem: np.ndarray | None = None, **sections) -> GeographicConfig:
    """An outlet near the foot of the bench valley, the DEM written under *root*."""
    root.mkdir(parents=True, exist_ok=True)
    raw = bench.valley() if dem is None else dem
    path = bench.write_raster(root / "dem.tif", raw, dtype=str(raw.dtype))
    return GeographicConfig.from_outlet(
        x=bench.x_of(bench.AXIS),
        y=bench.y_of(bench.N - 2),
        dem=path,
        snap_dist="50 m",
        buff_area="10%",
        crs_project=bench.CRS,
        **sections,
    )


def bench_clip(source: Path | str, out: Path | str, *, blank_cols: int = 0) -> str:
    """The ground cropped by one pixel on each side, a window of the DEM grid."""
    data = read_band(source)[1:-1, 1:-1].astype("float32")
    data[:, :blank_cols] = -9999.0
    write_geotiff(out, data, origin=BENCH_CLIP_ORIGIN, cell=bench.RES, nodata=-9999.0)
    return str(out)


class BenchTerrain:
    """Recorders standing for the flow products, the catchment, the network and the clips.

    They write the rasters of the bench valley. ``routing`` lists the DEM each
    flow pass was given, ``top`` the DEM each clip was cut from. The catchment
    is a square whose side is read from *sides*, one per delineation, and its
    snapped outlet sits at ``(side, 30)``.
    """

    def __init__(self, *, sides: tuple[float, ...] = (180.0,)) -> None:
        self.routing: list[str] = []
        self.top: list[str] = []
        self.sides = sides
        self.catchments = 0
        self.context = None

    def flow(self, **kwargs):
        from tests._helpers.terrain_doubles import fake_flow_products

        self.routing.append(str(kwargs["dem_init_path"]))
        out = Path(kwargs["dem_out_dir_path"])
        out.mkdir(parents=True, exist_ok=True)
        valley = bench.build()
        direc = bench.write_raster(out / "dem_direc.tif", valley.d8, dtype="int32")
        acc = bench.write_raster(out / "dem_acc.tif", valley.acc)
        return fake_flow_products(correc=out / "dem_fill.tif", direc=direc, acc=acc)

    def catchment(self, **kwargs) -> SimpleNamespace:
        side = self.sides[min(self.catchments, len(self.sides) - 1)]
        self.catchments += 1
        frame = gpd.GeoDataFrame(geometry=[box(30.0, 30.0, side, side)], crs=bench.CRS)
        frame.to_file(kwargs["paths"].watershed_shp)
        return SimpleNamespace(x_outlet_snapped=side, y_outlet_snapped=30.0, snap_distance_m=side)

    def network(self, **kwargs):
        from hydromodpy.spatial.geographic.core.river_network import RiverNetworkProducts

        correcflow = Path(kwargs["correcflow_dir"])
        valley = bench.build()
        streams = correcflow / "dem_streams_full.tif"
        bench.write_raster(streams, valley.streams.astype("float32"))
        valley.network.to_file(kwargs["network_shp_path"])
        return RiverNetworkProducts(
            enabled=True,
            hydrographic_network_generated_shp=str(kwargs["network_shp_path"]),
            streams_tif=str(streams),
            network_crs=bench.CRS,
        )

    def domain_rasters(self, **kwargs):
        from hydromodpy.spatial.geographic.domain_rasters import DomainRasterProducts

        self.top.append(str(kwargs["dem_init_path"]))
        paths, source = kwargs["paths"], kwargs["dem_init_path"]
        unused = [
            f"watershed{z}_{k}" for z in ("_box_buff", "_buff", "") for k in ("fill", "direc")
        ]
        return DomainRasterProducts(
            watershed_box_buff_dem=bench_clip(source, paths.watershed_box_buff_dem),
            watershed_buff_dem=bench_clip(source, paths.watershed_buff_dem),
            watershed_dem=bench_clip(source, paths.watershed_dem, blank_cols=BENCH_BLANK_COLS),
            **dict.fromkeys([*unused, "watershed_contour_tif"], "unused.tif"),
        )


def patch_pipeline(monkeypatch, *, flow, catchment, network=None, domain_rasters=None) -> None:
    """Replace the terrain steps of the geographic pipeline by *flow*, *catchment*, ..."""
    from hydromodpy.spatial.geographic import geographic_cache, pipeline

    tool = SimpleNamespace(delineation=SimpleNamespace(polygons_to_lines=lambda *a, **k: None))
    monkeypatch.setattr(pipeline, "resolve_delineation_backend", lambda backend: tool)
    monkeypatch.setattr(pipeline, "build_regional_flow_products", flow)
    monkeypatch.setattr(pipeline, "build_standard_catchment", catchment)
    if network is not None:
        monkeypatch.setattr(pipeline, "build_river_network_products", network)
    if domain_rasters is not None:
        monkeypatch.setattr(pipeline, "build_domain_rasters", domain_rasters)
        monkeypatch.setattr(geographic_cache, "build_domain_rasters", domain_rasters)
    monkeypatch.setattr(
        pipeline, "read_dem_metadata", lambda **_: SimpleNamespace(runtime_attributes=dict)
    )


def run_bench_pipeline(root: Path, monkeypatch, config, *, terrain=None, **kwargs):
    """Build the runtime context of *config* on the bench recorders, under ``root/results``."""
    from hydromodpy.spatial.geographic import pipeline

    terrain = terrain or BenchTerrain()
    patch_pipeline(
        monkeypatch,
        flow=terrain.flow,
        catchment=terrain.catchment,
        network=terrain.network,
        domain_rasters=terrain.domain_rasters,
    )
    terrain.context = pipeline.build_geographic_runtime_context(
        config=config, out_dir_path=root / "results", **kwargs
    )
    return terrain, terrain.context


def correcflow_dir(root: Path) -> Path:
    """The flow products folder of a pipeline run under ``root/results``."""
    return preprocessing_dir(root / "results") / "demcorrecflow"


def geographic_dir(root: Path) -> Path:
    """The geographic folder of a pipeline run under ``root/results``."""
    return preprocessing_dir(root / "results") / "geographic"


def touch_artifact(path: Path | str) -> None:
    """Write one cache artefact: a 1-pixel GeoTIFF, the four files of a shapefile or a file.

    Rasters are real: a cache hit describes the flow stack by reading its CRS
    and nodata, so it has to survive being read.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    if suffix == ".tif":
        write_geotiff(path, np.zeros((1, 1), dtype="float32"), nodata=-9999.0)
    elif suffix == ".shp":
        for sidecar in (".shp", ".shx", ".dbf", ".prj"):
            path.with_suffix(sidecar).write_text("", encoding="utf-8")
    else:
        path.write_text("{}" if suffix == ".json" else "", encoding="utf-8")


def cached_tree(root: Path, *, flow_products=None, domain: dict | None = None, **sections):
    """A complete geographic cache under ``root/project`` and the config it was written for."""
    from hydromodpy.spatial.geographic.core.catchment_domain import CatchmentDomainProducts
    from hydromodpy.spatial.geographic.geographic_cache import (
        required_geographic_cache_artifacts,
        write_geographic_cache_manifest,
    )
    from hydromodpy.spatial.geographic.geographic_paths import build_geographic_paths

    dem = root / "dem.tif"
    touch_artifact(dem)
    config = GeographicConfig.model_validate(
        {
            "catchment": {
                "catch_def": "from_outlet_coord",
                "dem_init_path": dem,
                "x_outlet": 1.0,
                "y_outlet": 2.0,
                "snap_dist": 10.0,
                "buff_area": 10.0,
            },
            "reuse_existing_outputs": True,
            **sections,
        }
    )
    paths = build_geographic_paths(root / "project")
    for artifact in required_geographic_cache_artifacts(config=config, paths=paths):
        touch_artifact(artifact)
    domain_products = CatchmentDomainProducts(
        **{
            "catchment_area_km2": 12.0,
            "buffer_distance_m": 300.0,
            "watershed_buff_shp": str(Path(paths.geographic_path) / "watershed_buff.shp"),
            "watershed_box_shp": paths.watershed_box_shp,
            "watershed_box_buff_shp": paths.box_buff,
            **(domain or {}),
        }
    )
    write_geographic_cache_manifest(
        config=config,
        paths=paths,
        domain_products=domain_products,
        catchment_area_km2=12.0,
        catchment_products=None,
        flow_products=flow_products,
    )
    return config, paths


def load_cached(config, paths):
    """The products a cache hit rebuilds, or None on a miss."""
    from hydromodpy.spatial.geographic.geographic_cache import load_cached_geographic_products

    return load_cached_geographic_products(config=config, paths=paths, crs_project=LAMBERT)


OUTLET_CATCHMENT = {
    "catch_def": "from_outlet_coord",
    "x_outlet": 450.0,
    "y_outlet": 450.0,
    "snap_dist": 100,
    "buff_area": 20.0,
}
"""An outlet in the middle of the 10 x 10 ramp of :func:`delineate_on_fake_backend`."""


def polygon_catchment(root: Path) -> dict:
    """A 600 m square catchment shapefile on the ramp, as a catchment table."""
    path = write_features(root / "inputs" / "catchment.shp", [box(100.0, 100.0, 700.0, 700.0)])
    return {"catch_def": "from_polyg_shp", "polyg_shp_path": path, "buff_area": 20.0}


def delineate_on_fake_backend(root: Path, monkeypatch, catchment: dict, **config):
    """A ``CatchmentDelineation`` on a 10 x 10 ramp of 100 m cells, on the Whitebox double."""
    from hydromodpy.spatial.geographic import catchment_delineation
    from tests._helpers.whitebox_double import FakeWhiteboxBackend

    backend = FakeWhiteboxBackend()
    monkeypatch.setattr(
        catchment_delineation, "resolve_delineation_backend", lambda b=None: backend
    )
    ramp = np.arange(100, dtype="float32").reshape(10, 10)
    dem = write_geotiff(
        root / "inputs" / "dem.tif", ramp, origin=(0.0, 1000.0), cell=100.0, nodata=-9999.0
    )
    cfg = GeographicConfig(
        catchment={"dem_init_path": dem, **catchment},
        crs_project=LAMBERT,
        dem_correc_type="breach",
        **config,
    )
    return catchment_delineation.CatchmentDelineation(
        config=cfg, initializing=SimpleNamespace(project_root=str(root / "run"))
    )


def write_json(path: Path, payload: dict) -> None:
    """Write a golden reference as the regeneration writes it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def golden_reference(golden: Path, actual: dict, update_goldens: bool) -> dict | None:
    """Rewrite *golden* under ``--update-goldens`` and return None, else read it back."""
    import pytest

    if update_goldens:
        write_json(golden, actual)
        return None
    if not golden.exists():
        pytest.fail(f"Missing golden {golden}. Run tests with --update-goldens to generate it.")
    return json.loads(golden.read_text(encoding="utf-8"))


def within(expected: dict, tolerances: dict[str, float]) -> dict:
    """*expected* with each key of *tolerances* matched to that absolute tolerance."""
    import pytest

    return {
        key: pytest.approx(value, abs=tolerances[key], rel=0.0) if key in tolerances else value
        for key, value in expected.items()
    }


def outlet_document(**sections) -> GeographicConfig:
    """An outlet document on a DEM that is never read, with extra sections."""
    return GeographicConfig.from_outlet(x=1.0, y=2.0, dem="dem.tif", **sections)


def capped_breach_report():
    """What a capped breach of 0.5 m and 200 m did, as the engine reports it."""
    from hydromodpy.spatial.terrain import CappedBreachReport

    return CappedBreachReport(
        cells_lowered=4,
        cells_raised=12,
        max_lowering_m=0.56,
        max_raise_m=0.2,
        max_dist_cells=8,
        max_cost_m=0.5,
        move_threshold_m=0.01,
    )


def capped_breach_flow_products():
    """Flow products of a capped breach whose conditioned DEM carries its report."""
    from dataclasses import replace

    from hydromodpy.spatial.terrain import CappedBreach
    from tests._helpers.terrain_doubles import fake_flow_products

    flow_products = fake_flow_products(method=CappedBreach(0.5, 200.0))
    directions = flow_products.accumulation.directions
    conditioned = replace(directions.conditioned_dem, breach_report=capped_breach_report())
    directions = replace(directions, conditioned_dem=conditioned)
    return type(flow_products)(
        accumulation=replace(flow_products.accumulation, directions=directions)
    )


CASE_RIVER_NETWORK = dict(
    enabled=True, threshold_mode="area_km2", threshold_area_km2=0.5, prune_short_streams=False,
    min_stream_length_m=0.0, compute_strahler_order=True, compute_stream_links=True,
    all_vertices=False,
)  # fmt: skip
NAIZIN = {"site": "naizin", "dem": "regional_dem_naizin.tif", "x": 265611.933, "y": 6784182.776}
NANCON = {"site": "nancon", "dem": "DEM_armorican_massif.tif", "x": 389285.910, "y": 6816518.749}


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f'"{value}"'
    return repr(value)


def outlet_case_toml(
    path: Path,
    case: dict,
    *,
    root: Path,
    dem_correc_type: str = "breach",
    river_network: dict | None = None,
) -> Path:
    """Write the project TOML of an outlet case on an example DEM, and return its path."""
    dem = (REPO_ROOT / "examples" / "data" / "dem" / case["dem"]).as_posix()
    lines = [
        '[workflow]\nmode = "simulation"',
        f'[site]\nname = "{case["site"]}"',
        f'[workspace]\nroot = "{root.as_posix()}"',
        f'[geographic]\ncrs_project = "{LAMBERT}"\ndem_correc_type = "{dem_correc_type}"',
        "[geographic.catchment]",
        f'catch_def = "from_outlet_coord"\ndem_init_path = "{dem}"',
        f"x_outlet = {case['x']}\ny_outlet = {case['y']}\nsnap_dist = 50\nbuff_area = 20.0",
    ]
    if river_network is not None:
        lines.append("[geographic.river_network]")
        lines += [f"{key} = {_toml_value(value)}" for key, value in river_network.items()]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


GOLDEN_FLOAT_KEYS = (
    "catch_area_km2", "dx", "dy", "xmin", "xmax", "ymin", "ymax",
    "mean_box_buff", "mean_core", "top_left_box_buff", "center_core",
)  # fmt: skip


def delineation_signature(geo) -> dict:
    """The numbers a delineation on the ramp is frozen by."""
    finite_box = np.isfinite(geo.dem_box_buff_data) & (geo.dem_box_buff_data != geo.nodata)
    finite_core = np.isfinite(geo.dem_data) & (geo.dem_data != geo.nodata)
    return {
        "catch_area_km2": float(geo.catch_area),
        "crs_proj": str(geo.crs_proj),
        "shape_box_buff": [int(v) for v in geo.dem_box_buff_data.shape],
        "shape_buff": [int(v) for v in geo.dem_buff_data.shape],
        "shape_core": [int(v) for v in geo.dem_data.shape],
        "dx": float(geo.dx),
        "dy": float(geo.dy),
        "xmin": float(geo.xmin),
        "xmax": float(geo.xmax),
        "ymin": float(geo.ymin),
        "ymax": float(geo.ymax),
        "mean_box_buff": float(np.nanmean(np.where(finite_box, geo.dem_box_buff_data, np.nan))),
        "mean_core": float(np.nanmean(np.where(finite_core, geo.dem_data, np.nan))),
        "top_left_box_buff": float(geo.dem_box_buff_data[0, 0]),
        "center_core": float(geo.dem_data[5, 5]),
    }


def assert_delineation_golden(actual: dict, golden: Path, update_goldens: bool) -> None:
    """Rewrite *golden* under ``--update-goldens``, else compare *actual* to it."""
    import pytest

    expected = golden_reference(golden, actual, update_goldens)
    if expected is None:
        return
    for key in ("shape_box_buff", "shape_buff", "shape_core", "crs_proj"):
        assert actual[key] == expected[key], key
    for key in GOLDEN_FLOAT_KEYS:
        assert actual[key] == pytest.approx(expected[key], rel=0.0, abs=1e-9), key


def river_network_summary_signature(summary: dict) -> dict:
    """The numbers of a river network summary a golden is frozen by."""
    strahler = summary["max_strahler_order"]
    return {
        "enabled": bool(summary["enabled"]),
        "threshold_mode": str(summary["threshold_mode"]),
        "threshold_value": float(summary["threshold_value"]),
        "threshold_cells": float(summary["threshold_cells"]),
        "stream_pixel_count": int(summary["stream_pixel_count"]),
        "segment_count": int(summary["segment_count"]),
        "network_total_length_m": float(summary["network_total_length_m"]),
        "max_strahler_order": None if strahler is None else float(strahler),
        "catchment_area_km2": float(summary["catchment_area_km2"]),
        "drainage_density_km_per_km2": float(summary["drainage_density_km_per_km2"]),
    }


# geo-core


def write_lines(path: Path | str, n: int = 1, **columns: list) -> Path:
    """Write *n* west-east lines of 1 km, 100 m apart, as a vector file."""
    from shapely.geometry import LineString

    lines = [LineString([(0.0, 100.0 * i), (1000.0, 100.0 * i)]) for i in range(n)]
    return write_features(path, lines, **columns)


def hydrography_load_result(array=((0.0, 0.0), (0.0, 0.0)), **metadata):
    """The load result of the hydrography loader: one stream raster, paths as metadata."""
    import xarray as xr

    from hydromodpy.data.contracts.load_result import LoadResult
    from hydromodpy.data.contracts.spatial_field import FieldRecord
    from hydromodpy.spatial.geographic.core.hydrographic_network import (
        HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME as field,
    )

    metadata = {key: None if value is None else str(value) for key, value in metadata.items()}
    data = xr.Dataset({field: (("y", "x"), np.asarray(array, dtype=float))})
    record = FieldRecord(
        variable=field,
        source="hydrography",
        unit="",
        data=data,
        bbox=(0.0, 0.0, 2.0, 2.0),
        crs=LAMBERT,
        metadata={"array_name": field, **metadata},
    )
    return LoadResult(fields=[record])
