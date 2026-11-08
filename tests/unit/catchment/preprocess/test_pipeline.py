"""The geographic pipeline: which DEM each step reads, and what the corrections leave.

The terrain steps are the recorders of ``BenchTerrain`` on the bench valley, where
every cell flows south and the mapped channel follows column 10.
"""

import json
import logging
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.catchment.algorithms.ground_bed import (
    GROUND_BED_FILENAME,
    GROUND_BED_REPORT_FILENAME,
    bed_dem_path,
)
from hydromodpy.catchment.algorithms.ground_corrections import (
    CROSSINGS_REPORT_FILENAME,
    GROUND_FILENAME,
)
from hydromodpy.catchment.algorithms.stream_dem_agreement import report_network_dem_agreement
from hydromodpy.catchment.preprocess import pipeline as runtime_pipeline
from hydromodpy.catchment.preprocess.catchment_delineation import CatchmentDelineation
from hydromodpy.catchment.preprocess.geographic_cache import (
    DESCRIPTION_FILENAME,
    required_geographic_cache_artifacts,
)
from hydromodpy.catchment.preprocess.geographic_config import GeographicConfig
from hydromodpy.catchment.surface import Surface
from hydromodpy.catchment.terrain.port import CappedBreach
from hydromodpy.core.exceptions import EmptyCatchmentError
from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.model.domain.domain import Domain
from hydromodpy.model.domain.domain_config import DomainConfig
from hydromodpy.model.domain.layers_config import VerticalGridConfig
from hydromodpy.solver.modflow_grid import build_spatial_discretization
from hydromodpy.solver.modflow_grid.sgrid_config import SolverSGridConfig
from tests._helpers import ground_bench as bench
from tests._helpers.cell_meshes import cell_mesh_of
from tests._helpers.geographic_cases import (
    BENCH_BLANK_COLS,
    BENCH_CLIP_ORIGIN,
    BENCH_RIVER,
    OUTLET_CATCHMENT,
    BenchTerrain,
    bench_config,
    correcflow_dir,
    delineate_on_fake_backend,
    geographic_dir,
    patch_pipeline,
    read_band,
    run_bench_pipeline,
    touch_artifact,
)
from tests._helpers.terrain_doubles import fake_flow_products

BUMP_ROW = 5
BUMP = 1.5
ROAD_ROW = 10
EMBANKMENT = 2.5
WEIR_ROW = 16
FIRST_AREA_KM2 = 0.0225
"""The first catchment of the recorders, a 150 m square."""
SECOND_AREA_KM2 = 0.0196
"""The catchment delineated again on the notched ground, a 140 m square."""
CHANNEL = LineString(
    [(bench.x_of(bench.AXIS), bench.N * bench.RES - 1.0), (bench.x_of(bench.AXIS), 1.0)]
)
OFF_CATCHMENT = LineString([(50_000.0, 50_000.0), (50_100.0, 50_100.0)])
ALPHA_SKIPPED = "stream/DEM agreement (alpha) was skipped"
SNAP_KEYS = ("x_outlet_snapped", "y_outlet_snapped", "outlet_snap_distance_m")


def _crossings(root: Path, *rows: tuple[str, object]) -> dict:
    """A crossings file, a road across the embankment row unless *rows* says otherwise."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / "crossings.gpkg"
    bench.structures(*(rows or (("road", bench.road_along(ROAD_ROW)),))).to_file(
        path, driver="GPKG"
    )
    return {"crossings": {"enabled": True, "path": path}}


def _logged(caplog, words: str) -> list[str]:
    return [r.getMessage() for r in caplog.records if words in r.getMessage()]


def _embanked() -> np.ndarray:
    return bench.build(embankment_rows=(ROAD_ROW,), height=EMBANKMENT).dem


def _report(root: Path, name: str = CROSSINGS_REPORT_FILENAME) -> dict:
    return json.loads((correcflow_dir(root) / name).read_text())


def _ground_run(root: Path, monkeypatch, raw: np.ndarray, **sections):
    config = bench_config(root, dem=raw, river_network=BENCH_RIVER, **sections)
    terrain, context = run_bench_pipeline(
        root, monkeypatch, config, terrain=BenchTerrain(sides=(180.0, 170.0))
    )
    return config, terrain, context


def test_a_declared_crossing_is_notched_delineated_again_and_reported(
    tmp_path, monkeypatch, caplog
) -> None:
    raw = _embanked()
    with caplog.at_level("INFO"):
        config, terrain, context = _ground_run(tmp_path, monkeypatch, raw, **_crossings(tmp_path))
    ground = str(correcflow_dir(tmp_path) / GROUND_FILENAME)
    assert terrain.routing == [str(config.dem_init_path), ground]
    assert terrain.top == [ground]
    assert context.top_dem_path == ground
    notched = read_band(ground)
    assert notched[ROAD_ROW, bench.AXIS] == pytest.approx(bench.bed(ROAD_ROW))
    assert np.argwhere(notched != raw).tolist() == [[ROAD_ROW, bench.AXIS]]
    report = _report(tmp_path)
    assert (report["crossing_points"], report["notched"]) == ({"road": 1}, {"road": 1})
    areas = (report["catchment_area_km2_before"], report["catchment_area_km2_after"])
    assert (report["pixels_lowered"], report["max_lowering_m"], *areas) == pytest.approx(
        (1, EMBANKMENT, FIRST_AREA_KM2, SECOND_AREA_KM2)
    )
    lines = _logged(caplog, "Crossing notch")
    assert len(lines) == 1
    assert "1 notched" in lines[0]
    # The outlet snapped on the notched ground, in the context and in the cache description.
    manifest = json.loads((geographic_dir(tmp_path) / DESCRIPTION_FILENAME).read_text())
    second = (170.0, 30.0, 170.0)
    assert (
        context.x_outlet_snapped,
        context.y_outlet_snapped,
        context.outlet_snap_distance_m,
    ) == second
    assert tuple(manifest[k] for k in SNAP_KEYS) == second


def test_a_notch_that_lowers_nothing_does_not_delineate_again_and_logs_once(
    tmp_path, monkeypatch, caplog
) -> None:
    with caplog.at_level("INFO"):
        config, terrain, _ = _ground_run(
            tmp_path, monkeypatch, bench.valley(), **_crossings(tmp_path)
        )
    ground = str(correcflow_dir(tmp_path) / GROUND_FILENAME)
    assert terrain.routing == [str(config.dem_init_path)]
    assert terrain.top == [ground]
    assert (read_band(ground) == bench.valley()).all()
    report = _report(tmp_path)
    assert report["pixels_lowered"] == 0
    assert report["catchment_area_km2_after"] == pytest.approx(FIRST_AREA_KM2)
    assert len(_logged(caplog, "Crossing notch")) == 1


def test_a_dem_domain_covers_the_valid_pixels_of_the_dem(tmp_path, monkeypatch) -> None:
    raw = bench.valley()
    raw[:3, :3] = -9999.0
    tmp_path.mkdir(exist_ok=True)
    dem = bench.write_raster(tmp_path / "dem.tif", raw)
    config = GeographicConfig.from_dem(dem, crs_project=bench.CRS)
    _, context = run_bench_pipeline(tmp_path, monkeypatch, config)
    valid_km2 = (bench.N * bench.N - 9) * bench.RES**2 / 1e6
    assert context.catchment_area_km2 == pytest.approx(valid_km2)
    box = gpd.read_file(context.runtime_attributes()["box_buff"])
    assert float(box.area.sum()) / 1e6 >= context.catchment_area_km2


@pytest.mark.parametrize(
    ("method", "limits"),
    [("breach", None), ("capped_breach", CappedBreach(max_depth_m=0.8, max_distance_m=100.0))],
)
def test_the_flow_step_gets_the_limits_and_an_empty_catchment_is_not_retried_with_a_fill(
    method, limits, tmp_path, monkeypatch
) -> None:
    sections = (
        {} if limits is None else {"capped_breach": {"max_depth": 0.8, "max_distance": 100.0}}
    )
    config = bench_config(tmp_path, dem_correc_type=method, **sections)
    calls: list[dict] = []

    def flow(**kwargs):
        calls.append(kwargs)
        return fake_flow_products(method=str(kwargs["dem_correc_type"]))

    def empty_catchment(**kwargs):
        raise EmptyCatchmentError("Outlet 'outlet' delineated an empty catchment.")

    patch_pipeline(monkeypatch, flow=flow, catchment=empty_catchment)
    with pytest.raises(EmptyCatchmentError):
        runtime_pipeline.build_geographic_runtime_context(
            config=config, out_dir_path=tmp_path / "results"
        )
    assert [call["dem_correc_type"] for call in calls] == [method]
    assert calls[0]["capped_breach"] == limits


def test_one_build_delineates_the_catchment_once(tmp_path, monkeypatch) -> None:
    delineations: list[object] = []
    delineate = runtime_pipeline.build_standard_catchment

    def counted(**kwargs):
        delineations.append(kwargs["paths"].watershed_shp)
        return delineate(**kwargs)

    monkeypatch.setattr(runtime_pipeline, "build_standard_catchment", counted)
    geographic = delineate_on_fake_backend(tmp_path, monkeypatch, OUTLET_CATCHMENT)
    geographic.get_domain_geographic_context()
    assert len(delineations) == 1
    assert float(geographic.catch_area) > 0.0


def _journal(root: Path) -> Path:
    return geographic_dir(root) / "stream_dem_agreement.json"


def _plant(path: Path, line: LineString, *, crs: str | None = bench.CRS) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    gpd.GeoDataFrame(geometry=[line], crs=crs).to_file(path)
    return path


def _unmeasurable_map(case: str, root: Path) -> Path:
    if case == "outside":
        return _plant(root / "map.gpkg", OFF_CATCHMENT)
    if case == "no_crs":
        return _plant(root / "map.shp", CHANNEL, crs=None)
    return root / "absent.gpkg"


@pytest.mark.parametrize("case", ["outside", "no_crs", "missing"])
def test_a_map_that_cannot_be_measured_is_a_warning_and_does_not_stop_the_geographic_step(
    case, tmp_path, monkeypatch, caplog
) -> None:
    watershed = tmp_path / "watershed.shp"
    gpd.GeoDataFrame(geometry=[LineString([(0, 0), (1, 1)]).buffer(1000.0)], crs=bench.CRS).to_file(
        watershed
    )
    paths = SimpleNamespace(watershed_shp=str(watershed), geographic_path=str(tmp_path / "geo"))
    d8 = bench.write_raster(tmp_path / "direc.tif", bench.build().d8, dtype="int32")
    journal = Path(paths.geographic_path) / "stream_dem_agreement.json"
    journal.parent.mkdir(parents=True)
    journal.write_text("{}")
    map_path = _unmeasurable_map(case, tmp_path)
    with caplog.at_level(logging.WARNING):
        result = report_network_dem_agreement(
            SimpleNamespace(crs_project=bench.CRS, paths=paths),
            network_map_path=map_path,
            d8_pointer_path=d8,
        )
    assert result is None
    assert ALPHA_SKIPPED in caplog.text
    assert "map" in caplog.text and "could not be measured" in caplog.text
    assert not journal.exists()
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        config = bench_config(tmp_path, river_network=BENCH_RIVER)
        _, context = run_bench_pipeline(tmp_path, monkeypatch, config, network_map_path=map_path)
    assert context.catchment_area_km2 > 0.0
    assert ALPHA_SKIPPED in caplog.text
    assert not _journal(tmp_path).exists()


def test_a_missing_custom_file_is_a_warning_in_the_resolver(tmp_path, caplog) -> None:
    from hydromodpy.data.variables.hydrography.resolver import resolve_network_map_path

    source = SimpleNamespace(source="custom", path="absent.gpkg")
    cfg = SimpleNamespace(data=SimpleNamespace(hydrography=SimpleNamespace(sources=[source])))
    with caplog.at_level(logging.WARNING):
        resolved = resolve_network_map_path(cfg, config_path=tmp_path / "project.toml")
    assert resolved is None
    assert "path not found" in caplog.text


def test_the_journal_follows_the_map_on_a_rebuild_and_on_a_cache_hit(tmp_path, monkeypatch) -> None:
    channel = _plant(tmp_path / "channel.gpkg", CHANNEL)
    config = bench_config(tmp_path, river_network=BENCH_RIVER)
    run = partial(run_bench_pipeline, tmp_path, monkeypatch, config, reuse_existing_outputs=True)
    paths = run(network_map_path=channel)[1].paths
    first = json.loads(_journal(tmp_path).read_text())
    assert first["alpha"] == pytest.approx(1.0)
    # The recorders write part of the tree. Completed, it is read back, never rebuilt.
    for artifact in required_geographic_cache_artifacts(config=config, paths=paths):
        Path(artifact).exists() or touch_artifact(artifact)
    monkeypatch.setattr(runtime_pipeline, "_build_geographic_products", lambda **_: pytest.fail())
    # Cache hit, another map: the journal describes this one.
    x = bench.x_of(bench.AXIS)
    run(network_map_path=_plant(tmp_path / "half.gpkg", LineString([(x, 100.0), (x, 40.0)])))
    second = json.loads(_journal(tmp_path).read_text())
    assert second["n_network_cells"] < first["n_network_cells"]
    # Cache hit, no map: the stale journal is removed.
    run(network_map_path=None)
    assert not _journal(tmp_path).exists()
    # Cache hit, a map where there was none: the journal appears.
    run(network_map_path=channel)
    assert json.loads(_journal(tmp_path).read_text()) == first


def _bumped(*, embankment: bool) -> np.ndarray:
    raw = bench.build(embankment_rows=(ROAD_ROW,) if embankment else (), height=EMBANKMENT).dem
    raw[BUMP_ROW, bench.AXIS] += BUMP
    return raw


def _bed_config(root: Path, *, regularize: bool, dem=None, **sections) -> GeographicConfig:
    raw = _bumped(embankment="crossings" in sections) if dem is None else dem
    sections |= {"river_network": BENCH_RIVER, "bed_regularization": {"enabled": regularize}}
    return bench_config(root, dem=raw, **sections)


def _bed_run(root: Path, monkeypatch, config: GeographicConfig):
    """Run the pipeline and return the recorders, the model top path and its values."""
    terrain, context = run_bench_pipeline(root, monkeypatch, config)
    top = context.runtime_attributes()["watershed_box_buff_dem"]
    return terrain, top, read_band(top)


def _clip_path(root: Path) -> Path:
    return geographic_dir(root) / "watershed_box_buff_dem.tif"


def test_on_the_top_reads_the_regularised_copy_and_off_the_clip_of_the_ground(
    tmp_path, monkeypatch, caplog
) -> None:
    off_root, on_root = tmp_path / "off", tmp_path / "on"
    off_config = _bed_config(off_root, regularize=False)
    off, off_path, off_top = _bed_run(off_root, monkeypatch, off_config)
    with caplog.at_level("INFO"):
        on, top_path, top = _bed_run(on_root, monkeypatch, _bed_config(on_root, regularize=True))
    # Without a correction the raw DEM is routed and clipped untouched.
    raw = str(off_config.dem_init_path)
    assert (off.routing, off.top) == ([raw], [raw])
    assert not list(correcflow_dir(off_root).glob("dem_ground*"))
    assert Path(off_path) == _clip_path(off_root)
    assert (off_top == read_band(_clip_path(off_root))).all()
    assert not list(geographic_dir(off_root).glob("*_bed*"))
    assert not list(correcflow_dir(off_root).glob("*_bed*"))
    clip = _clip_path(on_root)
    assert Path(top_path) == bed_dem_path(clip)
    # The clip of the ground itself is the one a run without the option reads.
    assert clip.read_bytes() == _clip_path(off_root).read_bytes()
    ground = read_band(clip)
    moved = np.argwhere(top != ground)
    channel_col = bench.AXIS - 1  # one column cropped by the clip
    assert moved.size
    assert set(moved[:, 1].tolist()) == {channel_col}
    bed = top[:, channel_col].astype(float)
    assert (np.diff(bed) < 0).all()
    assert abs(float(np.mean(bed - ground[:, channel_col]))) < 0.01
    # The routing, the channel tree and the polygons of the mesh do not move.
    assert [Path(p).name for p in on.routing] == [Path(p).name for p in off.routing]
    for name in ("watershed.shp", "watershed_box_buff.shp", "river_network.shp"):
        before = gpd.read_file(next(geographic_dir(off_root).rglob(name)))
        after = gpd.read_file(next(geographic_dir(on_root).rglob(name)))
        assert after.geometry.geom_equals(before.geometry).all(), name
    # Without a crossings file the fit has no cut, and says so once.
    assert len(_logged(caplog, "no crossings file")) == 1
    assert _report(on_root, GROUND_BED_REPORT_FILENAME)["cut_pixels"] == 0


def test_the_notch_footprint_is_a_gap_the_weir_a_cut_and_both_are_reported(
    tmp_path, monkeypatch, caplog
) -> None:
    structures = _crossings(
        tmp_path,
        ("road", bench.road_along(ROAD_ROW)),
        ("weir", bench.bridge_at(bench.AXIS, WEIR_ROW)),
    )
    config = _bed_config(tmp_path, regularize=True, **structures)
    with caplog.at_level("INFO"):
        _bed_run(tmp_path, monkeypatch, config)
    report = _report(tmp_path, GROUND_BED_REPORT_FILENAME)
    assert (report["gap_pixels"], report["cut_pixels"], report["rises_after_fit"]) == (1, 1, 0)
    assert report["cuts"][0]["kind"] == "weir"
    assert report["violations_before"] >= 1
    assert report["parameters"]["notch_footprint"] is True
    lines = _logged(caplog, "Bed regularisation")
    assert len(lines) == 1
    assert "1 gap(s), 1 cut(s)" in lines[0]


def test_every_extent_of_the_top_the_sfr_bed_and_a_triangle_mesh_read_one_regularised_ground(
    tmp_path, monkeypatch
) -> None:
    config = _bed_config(tmp_path, regularize=True)
    terrain, _, top = _bed_run(tmp_path, monkeypatch, config)
    cached = runtime_pipeline.build_geographic_runtime_context(
        config=config, out_dir_path=tmp_path / "results", reuse_existing_outputs=True
    )
    attributes = cached.runtime_attributes()
    names = ("watershed_box_buff_dem", "watershed_buff_dem", "watershed_dem")
    beds = {name: read_band(attributes[name]) for name in names}
    for name in names:
        assert Path(attributes[name]) == bed_dem_path(geographic_dir(tmp_path) / f"{name}.tif")
    watershed = read_band(geographic_dir(tmp_path) / "watershed_dem.tif")
    blank = BENCH_BLANK_COLS
    assert (beds["watershed_buff_dem"] == beds["watershed_box_buff_dem"]).all()
    assert (beds["watershed_dem"][:, :blank] == -9999.0).all()
    assert (beds["watershed_dem"][:, blank:] == beds["watershed_box_buff_dem"][:, blank:]).all()
    assert (beds["watershed_dem"] != watershed).any()
    # The SFR bed and the model top read the same regularized ground.
    ground_bed = correcflow_dir(tmp_path) / GROUND_BED_FILENAME
    for context in (terrain.context, cached):
        assert Path(context.runtime_attributes()["_top_dem_path"]) == ground_bed
    ground = read_band(tmp_path / "dem.tif")
    full_bed = read_band(ground_bed)
    assert (full_bed != ground).any()
    assert not ((full_bed != ground) & ~bench.build().streams).any()
    assert (top == read_band(ground_bed)[1:-1, 1:-1]).all()
    # A triangle mesh takes its MODFLOW 6 top from the regularized clip.
    ground_top = read_band(_clip_path(tmp_path))
    geographic = object.__new__(CatchmentDelineation)
    geographic._config = config
    for name, value in terrain.context.runtime_attributes().items():
        setattr(geographic, name, value)
    surface = geographic.get_domain_surface_topo()
    domain = Domain(config=DomainConfig(), surface_topo=surface)
    domain.substratum = Surface(
        name="substratum", values=np.asarray(surface.as_array()) - 50.0, support=surface.support
    )
    # One triangle on the moved channel pixel, one on the hillslope, each centered on it.
    row, col = BUMP_ROW - 1, bench.AXIS - 1  # on the clip grid
    west, north = BENCH_CLIP_ORIGIN
    vertices: list[list[float]] = []
    cells: list[list[int]] = []
    for c in (col, col - 4):
        x, y = west + (c + 0.5) * bench.RES, north - (row + 0.5) * bench.RES
        start = len(vertices)
        vertices += [[x - 3.0, y - 2.0], [x + 3.0, y - 2.0], [x, y + 4.0]]
        cells.append([start, start + 1, start + 2])
    mesh = HydroMesh(
        vertices=np.asarray(vertices, dtype=float),
        cell_blocks=(CellBlock(CellType.TRIANGLE, np.asarray(cells, dtype=int)),),
    )
    grid = build_spatial_discretization(
        domain=domain,
        vertical_config=VerticalGridConfig(genmtd_lay="constant", nlay=1, nodata=-9999.0),
        sgrid_config=SolverSGridConfig(),
        cell_mesh=cell_mesh_of(mesh),
    )
    mesh_top = grid.solver_mesh.top.reshape(-1)
    assert top[row, col] != pytest.approx(ground_top[row, col], abs=0.1)
    np.testing.assert_allclose(mesh_top, [top[row, col], top[row, col - 4]], atol=1e-4)


def test_a_float64_ground_above_2048_m_with_nothing_notched_has_no_gap(
    tmp_path, monkeypatch
) -> None:
    # float32 rounds a level above 2048 m by more than 1e-4 m, so a footprint read
    # off the difference of the two grounds would flag pixels the notch never moved.
    fraction = np.linspace(0.0, 1.0e-3, bench.N * bench.N).reshape(bench.N, bench.N)
    dem = _bumped(embankment=False).astype("float64") + 2500.0 + fraction
    off_channel = LineString([(0.0, bench.y_of(ROAD_ROW)), (bench.x_of(bench.AXIS - 4), 1.0)])
    sections = _crossings(tmp_path, ("road", off_channel))
    config = _bed_config(tmp_path, regularize=True, dem=dem, **sections)
    _bed_run(tmp_path, monkeypatch, config)
    report = _report(tmp_path, GROUND_BED_REPORT_FILENAME)
    assert report["parameters"]["notch_footprint"] is True
    assert report["gap_pixels"] == 0
    assert _report(tmp_path)["pixels_lowered"] == 0
