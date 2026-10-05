"""Both geographic entry points sample the model top from the regularised bed, and only it.

The terrain engine, the network extraction and the clips are replaced by
recorders that write the rasters of the bench valley, with a 1.5 m bump on the
bed. What is under test is which file the model top and the SFR bed read, what
the regularisation writes, and that the routing products, the channel tree and
the polygons the mesh is built on do not move. A mesh read from a file takes
its MODFLOW 6 top from the regularised clip too.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString, box

from hydromodpy.core.state.paths import preprocessing_dir
from hydromodpy.solver.modflow_grid import build_spatial_discretization
from hydromodpy.spatial import Surface
from hydromodpy.spatial.domain import Domain, DomainConfig
from hydromodpy.spatial.geographic import pipeline as runtime_pipeline
from hydromodpy.spatial.geographic.catchment_delineation import CatchmentDelineation
from hydromodpy.spatial.geographic.core import domain_geographic_pipeline as domain_pipeline
from hydromodpy.spatial.geographic.core.bed_regularization_raster import (
    GROUND_BED_FILENAME,
    GROUND_BED_REPORT_FILENAME,
    bed_dem_path,
)
from hydromodpy.spatial.geographic.core.river_network import RiverNetworkProducts
from hydromodpy.spatial.geographic.domain_rasters import DomainRasterProducts
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh
from hydromodpy.spatial.mesh.cartesian_grid.sgrid_config import (
    SolverSGridConfig,
    VerticalGridConfig,
)
from hydromodpy.spatial.mesh.gmsh_grid.gmsh_planar_mesh import GmshPlanarMesh2D
from hydromodpy.workflow.steps.mesh import run_mesh_input_phase
from tests._helpers import ground_bench as bench
from tests._helpers.terrain_doubles import fake_flow_products

BUMP_ROW = 5
BUMP = 1.5
ROAD_ROW = 10
EMBANKMENT = 2.5
WEIR_ROW = 16
_RIVER = {"enabled": True, "threshold_mode": "cells", "threshold_cells": 50}
_CLIP_TRANSFORM = from_origin(bench.RES, (bench.N - 1) * bench.RES, bench.RES, bench.RES)
_WATERSHED_COLS = 3
"""The watershed clip holds nodata on its first columns, off the channel."""


def _clip(source: str | Path, out: str | Path, *, blank_cols: int = 0) -> None:
    """The ground cropped by one pixel on each side, a window of the DEM grid."""
    with rasterio.open(source) as src:
        data = src.read(1)[1:-1, 1:-1].copy()
    data[:, :blank_cols] = -9999.0
    profile = {
        "driver": "GTiff",
        "height": data.shape[0],
        "width": data.shape[1],
        "count": 1,
        "dtype": "float32",
        "crs": bench.CRS,
        "transform": _CLIP_TRANSFORM,
        "nodata": -9999.0,
    }
    with rasterio.open(out, "w", **profile) as dst:
        dst.write(data.astype("float32"), 1)


class _Terrain:
    """Recorders standing for the flow products, the catchment, the network and the clips."""

    def __init__(self) -> None:
        self.routing: list[str] = []

    def flow(self, **kwargs):
        self.routing.append(str(kwargs["dem_init_path"]))
        out = Path(kwargs["dem_out_dir_path"])
        out.mkdir(parents=True, exist_ok=True)
        valley = bench.build()
        direc = bench.write_raster(out / "dem_direc.tif", valley.d8, dtype="int32")
        acc = bench.write_raster(out / "dem_acc.tif", valley.acc)
        return fake_flow_products(correc=out / "dem_fill.tif", direc=direc, acc=acc)

    def catchment(self, **kwargs):
        frame = gpd.GeoDataFrame(geometry=[box(30.0, 30.0, 180.0, 180.0)], crs=bench.CRS)
        frame.to_file(kwargs["paths"].watershed_shp)

    def network(self, **kwargs):
        correcflow = Path(kwargs["correcflow_dir"])
        valley = bench.build()
        bench.write_raster(correcflow / "dem_streams_full.tif", valley.streams.astype("float32"))
        valley.network.to_file(kwargs["network_shp_path"])
        return RiverNetworkProducts(
            enabled=True,
            hydrographic_network_generated_shp=str(kwargs["network_shp_path"]),
            streams_tif=str(correcflow / "dem_streams_full.tif"),
            network_crs=bench.CRS,
        )

    def clip(self, **kwargs):
        _clip(kwargs["dem_init_path"], kwargs["output_dem_path"])
        return str(kwargs["output_dem_path"])

    def domain_rasters(self, **kwargs):
        paths = kwargs["paths"]
        _clip(kwargs["dem_init_path"], paths.watershed_box_buff_dem)
        _clip(kwargs["dem_init_path"], paths.watershed_buff_dem)
        _clip(kwargs["dem_init_path"], paths.watershed_dem, blank_cols=_WATERSHED_COLS)
        return DomainRasterProducts(
            watershed_box_buff_dem=paths.watershed_box_buff_dem,
            watershed_box_buff_fill="unused.tif",
            watershed_box_buff_direc="unused.tif",
            watershed_buff_dem=paths.watershed_buff_dem,
            watershed_buff_fill="unused.tif",
            watershed_buff_direc="unused.tif",
            watershed_dem=paths.watershed_dem,
            watershed_fill="unused.tif",
            watershed_direc="unused.tif",
            watershed_contour_tif="unused.tif",
        )


def _bumped(*, embankment: bool) -> np.ndarray:
    raw = bench.build(embankment_rows=(ROAD_ROW,) if embankment else (), height=EMBANKMENT).dem
    raw[BUMP_ROW, bench.AXIS] += BUMP
    return raw


def _config(
    root: Path, *, regularize: bool, dem: np.ndarray | None = None, **sections
) -> GeographicConfig:
    root.mkdir(parents=True, exist_ok=True)
    if dem is None:
        dem_path = bench.write_raster(root / "dem.tif", _bumped(embankment="crossings" in sections))
    else:
        dem_path = bench.write_raster(root / "dem.tif", dem, dtype=str(dem.dtype))
    return GeographicConfig.from_outlet(
        x=bench.x_of(bench.AXIS),
        y=bench.y_of(bench.N - 2),
        dem=dem_path,
        snap_dist="50 m",
        buff_area="10%",
        crs_project=bench.CRS,
        river_network=_RIVER,
        bed_regularization={"enabled": regularize},
        **sections,
    )


def _structures(root: Path) -> dict:
    path = root / "crossings.gpkg"
    bench.structures(
        ("road", bench.road_along(ROAD_ROW)),
        ("weir", bench.bridge_at(bench.AXIS, WEIR_ROW)),
    ).to_file(path, driver="GPKG")
    return {"crossings": {"enabled": True, "path": path}}


def _domain(root: Path, monkeypatch, config: GeographicConfig):
    terrain = _Terrain()
    monkeypatch.setattr(domain_pipeline, "build_regional_flow_products", terrain.flow)
    monkeypatch.setattr(domain_pipeline, "build_standard_catchment", terrain.catchment)
    monkeypatch.setattr(domain_pipeline, "build_river_network_products", terrain.network)
    monkeypatch.setattr(domain_pipeline, "clip_dem_to_box_buffer", terrain.clip)
    workspace = SimpleNamespace(project_root=root / "results")
    features = domain_pipeline.build_geographic_derived_features(config=config, workspace=workspace)
    context = features.to_domain_geographic_context()
    return terrain, context.watershed_box_buff_dem, context.surface_topo.as_array()


def _runtime(root: Path, monkeypatch, config: GeographicConfig):
    terrain = _Terrain()
    tool = SimpleNamespace(delineation=SimpleNamespace(polygons_to_lines=lambda *a, **k: None))
    monkeypatch.setattr(runtime_pipeline, "resolve_delineation_backend", lambda backend: tool)
    monkeypatch.setattr(runtime_pipeline, "build_regional_flow_products", terrain.flow)
    monkeypatch.setattr(runtime_pipeline, "build_standard_catchment", terrain.catchment)
    monkeypatch.setattr(runtime_pipeline, "build_river_network_products", terrain.network)
    monkeypatch.setattr(runtime_pipeline, "build_domain_rasters", terrain.domain_rasters)
    monkeypatch.setattr(
        runtime_pipeline,
        "read_dem_metadata",
        lambda **kwargs: SimpleNamespace(runtime_attributes=lambda: {}),
    )
    context = runtime_pipeline.build_geographic_runtime_context(
        config=config, out_dir_path=root / "results"
    )
    terrain.context = context
    top = context.runtime_attributes()["watershed_box_buff_dem"]
    return terrain, top, _read(top)


ENTRY_POINTS = pytest.mark.parametrize("run", [_domain, _runtime], ids=["domain", "runtime"])


def _geographic(root: Path) -> Path:
    return preprocessing_dir(root / "results") / "geographic"


def _clip_path(root: Path) -> Path:
    return _geographic(root) / "watershed_box_buff_dem.tif"


def _correcflow(root: Path) -> Path:
    return preprocessing_dir(root / "results") / "demcorrecflow"


def _report(root: Path) -> dict:
    return json.loads((_correcflow(root) / GROUND_BED_REPORT_FILENAME).read_text())


def _read(path: str | Path) -> np.ndarray:
    with rasterio.open(path) as src:
        return src.read(1)


@ENTRY_POINTS
def test_off_the_top_reads_the_clip_of_the_ground_and_nothing_is_written(
    run, tmp_path, monkeypatch
) -> None:
    config = _config(tmp_path, regularize=False)

    _, top_path, top = run(tmp_path, monkeypatch, config)

    assert Path(top_path) == _clip_path(tmp_path)
    assert (top == _read(_clip_path(tmp_path))).all()
    assert not list(_geographic(tmp_path).glob("*_bed*"))
    assert not list(_correcflow(tmp_path).glob("*_bed*"))


@ENTRY_POINTS
def test_on_the_top_reads_the_regularised_copy(run, tmp_path, monkeypatch) -> None:
    off_root, on_root = tmp_path / "off", tmp_path / "on"
    run(off_root, monkeypatch, _config(off_root, regularize=False))

    _, top_path, top = run(on_root, monkeypatch, _config(on_root, regularize=True))

    clip = _clip_path(on_root)
    assert Path(top_path) == bed_dem_path(clip)
    # The clip of the ground itself is the one a run without the option reads.
    assert clip.read_bytes() == _clip_path(off_root).read_bytes()
    ground = _read(clip)
    moved = np.argwhere(top != ground)
    channel_col = bench.AXIS - 1  # one column cropped by the clip
    assert moved.size
    assert set(moved[:, 1].tolist()) == {channel_col}
    bed = top[:, channel_col].astype(float)
    assert (np.diff(bed) < 0).all()
    assert abs(float(np.mean(bed - ground[:, channel_col]))) < 0.01


@ENTRY_POINTS
def test_the_routing_the_channel_tree_and_the_mesh_polygons_do_not_move(
    run, tmp_path, monkeypatch
) -> None:
    off_root, on_root = tmp_path / "off", tmp_path / "on"
    off, _, _ = run(off_root, monkeypatch, _config(off_root, regularize=False))
    on, _, _ = run(on_root, monkeypatch, _config(on_root, regularize=True))

    assert [Path(p).name for p in on.routing] == [Path(p).name for p in off.routing]
    for name in ("watershed.shp", "watershed_box_buff.shp"):
        before = gpd.read_file(next(_geographic(off_root).rglob(name)))
        after = gpd.read_file(next(_geographic(on_root).rglob(name)))
        assert after.geometry.geom_equals(before.geometry).all(), name
    networks = [
        gpd.read_file(next(_geographic(root).rglob("river_network.shp")))
        for root in (off_root, on_root)
    ]
    assert networks[1].geometry.geom_equals(networks[0].geometry).all()


@ENTRY_POINTS
def test_the_notch_footprint_is_a_gap_the_weir_a_cut_and_both_are_reported(
    run, tmp_path, monkeypatch, caplog
) -> None:
    config = _config(tmp_path, regularize=True, **_structures(tmp_path))

    with caplog.at_level("INFO"):
        run(tmp_path, monkeypatch, config)

    report = _report(tmp_path)
    assert report["gap_pixels"] == 1
    assert report["cut_pixels"] == 1
    assert report["cuts"][0]["kind"] == "weir"
    assert report["violations_before"] >= 1
    assert report["rises_after_fit"] == 0
    assert report["parameters"]["notch_footprint"] is True
    lines = [
        r.getMessage() for r in caplog.records if r.getMessage().startswith("Bed regularisation")
    ]
    assert len(lines) == 1
    assert "1 gap(s), 1 cut(s)" in lines[0]


def test_every_extent_of_the_runtime_top_reads_its_regularised_copy(tmp_path, monkeypatch) -> None:
    config = _config(tmp_path, regularize=True)

    _runtime(tmp_path, monkeypatch, config)
    cached = runtime_pipeline.build_geographic_runtime_context(
        config=config, out_dir_path=tmp_path / "results", reuse_existing_outputs=True
    )
    attributes = cached.runtime_attributes()

    names = ("watershed_box_buff_dem", "watershed_buff_dem", "watershed_dem")
    beds = {name: _read(attributes[name]) for name in names}
    for name in names:
        assert Path(attributes[name]) == bed_dem_path(_geographic(tmp_path) / f"{name}.tif")
    watershed = _read(_geographic(tmp_path) / "watershed_dem.tif")
    assert (beds["watershed_buff_dem"] == beds["watershed_box_buff_dem"]).all()
    assert (beds["watershed_dem"][:, :_WATERSHED_COLS] == -9999.0).all()
    assert (
        beds["watershed_dem"][:, _WATERSHED_COLS:]
        == beds["watershed_box_buff_dem"][:, _WATERSHED_COLS:]
    ).all()
    assert (beds["watershed_dem"] != watershed).any()


def _window(path: Path) -> np.ndarray:
    """The pixels of a full-extent raster the clips hold."""
    return _read(path)[1:-1, 1:-1]


def test_the_sfr_bed_and_the_model_top_read_one_regularised_ground(tmp_path, monkeypatch) -> None:
    config = _config(tmp_path, regularize=True)

    terrain, _, top = _runtime(tmp_path, monkeypatch, config)
    cached = runtime_pipeline.build_geographic_runtime_context(
        config=config, out_dir_path=tmp_path / "results", reuse_existing_outputs=True
    )

    ground_bed = _correcflow(tmp_path) / GROUND_BED_FILENAME
    for context in (terrain.context, cached):
        assert Path(context.runtime_attributes()["_top_dem_path"]) == ground_bed
    ground = _read(tmp_path / "dem.tif")
    full_bed = _read(ground_bed)
    assert (full_bed != ground).any()
    assert not ((full_bed != ground) & ~bench.build().streams).any()
    # The clip the model top reads is the clip of the regularised ground.
    assert (top == _window(ground_bed)).all()


def test_a_float64_ground_above_2048_m_with_nothing_notched_has_no_gap(
    tmp_path, monkeypatch
) -> None:
    # float32 rounds a level above 2048 m by more than 1e-4 m, so a footprint read
    # off the difference of the two grounds would flag pixels the notch never moved.
    fraction = np.linspace(0.0, 1.0e-3, bench.N * bench.N).reshape(bench.N, bench.N)
    dem = (_bumped(embankment=False).astype("float64") + 2500.0 + fraction).astype("float64")
    path = tmp_path / "crossings.gpkg"
    off_channel = LineString([(0.0, bench.y_of(ROAD_ROW)), (bench.x_of(bench.AXIS - 4), 1.0)])
    bench.structures(("road", off_channel)).to_file(path, driver="GPKG")
    config = _config(tmp_path, regularize=True, dem=dem, crossings={"enabled": True, "path": path})

    _runtime(tmp_path, monkeypatch, config)

    report = _report(tmp_path)
    assert report["parameters"]["notch_footprint"] is True
    assert report["gap_pixels"] == 0
    notch = json.loads((_correcflow(tmp_path) / "dem_ground_crossings.json").read_text())
    assert notch["pixels_lowered"] == 0


def _triangle_at(x: float, y: float, start: int) -> tuple[list[list[float]], list[int]]:
    """A small triangle whose centroid is (x, y)."""
    return [[x - 3.0, y - 2.0], [x + 3.0, y - 2.0], [x, y + 4.0]], [start, start + 1, start + 2]


def test_a_mesh_read_from_a_file_takes_its_modflow6_top_from_the_regularised_clip(
    tmp_path, monkeypatch
) -> None:
    config = _config(tmp_path, regularize=True)
    terrain, _, bed_top = _runtime(tmp_path, monkeypatch, config)
    ground_top = _read(_clip_path(tmp_path))
    geographic = object.__new__(CatchmentDelineation)
    geographic._config = config
    for name, value in terrain.context.runtime_attributes().items():
        setattr(geographic, name, value)
    surface = geographic.get_domain_surface_topo()
    domain = Domain(config=DomainConfig(), surface_topo=surface)
    domain.substratum = Surface(
        name="substratum", values=np.asarray(surface.as_array()) - 50.0, support=surface.support
    )

    # A mesh written to a file and read back the way [mesh_input] reads it: one
    # cell on the moved channel pixel, one on the hillslope.
    row, col = BUMP_ROW - 1, bench.AXIS - 1  # on the clip grid
    centres = [
        (_CLIP_TRANSFORM.c + (c + 0.5) * bench.RES, _CLIP_TRANSFORM.f - (row + 0.5) * bench.RES)
        for c in (col, col - 4)
    ]
    vertices, cells = [], []
    for x, y in centres:
        corners, nodes = _triangle_at(x, y, len(vertices))
        vertices += corners
        cells.append(nodes)
    mesh = HydroMesh(
        vertices=np.asarray(vertices, dtype=float),
        cell_blocks=(CellBlock(CellType.TRIANGLE, np.asarray(cells, dtype=int)),),
    )
    msh = GmshPlanarMesh2D.from_hydro_mesh(mesh).to_file(tmp_path / "mesh.msh")
    run_state = SimpleNamespace(
        setup=SimpleNamespace(
            mesh_summary=None, mesh_bundle=None, mesh_planar=None, mesh_support=None
        )
    )
    run_mesh_input_phase(run_state, {"mesh_path": str(msh), "bundle_dir": ""})

    grid = build_spatial_discretization(
        domain=domain,
        sgrid_config=SolverSGridConfig(
            grid_dual="triangle",
            vertical=VerticalGridConfig(genmtd_lay="constant", nlay=1, nodata=-9999.0),
        ),
        runtime_planar_mesh=run_state.setup.mesh_planar,
    )

    top = grid.solver_mesh.top.reshape(-1)
    assert bed_top[row, col] != pytest.approx(ground_top[row, col], abs=0.1)
    np.testing.assert_allclose(top, [bed_top[row, col], bed_top[row, col - 4]], atol=1e-4)


@ENTRY_POINTS
def test_without_a_crossings_file_the_fit_has_no_cut_and_says_so(
    run, tmp_path, monkeypatch, caplog
) -> None:
    with caplog.at_level("INFO"):
        run(tmp_path, monkeypatch, _config(tmp_path, regularize=True))

    lines = [r.getMessage() for r in caplog.records if "no crossings file" in r.getMessage()]
    assert len(lines) == 1
    assert _report(tmp_path)["cut_pixels"] == 0
