"""The top and the bottom of every cell, read once from the domain by the rule a backend declares.

Two cells side by side (x 0-50 m and 50-100 m) lie on a DEM ramp z = x with a notch of 0.5 m in cell 0, off its center. A river chain with a lateral offset marks cell 0 as a crossing cell.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.catchment.raster_support import RasterSupport
from hydromodpy.catchment.surface import Surface
from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.mesh.planar.planar_cell_mesh import CellChain, MeshIdentity, build_planar_cell_mesh
from hydromodpy.model.domain.cell_column import (
    cells_cover_pixels,
    centre_column,
    modflow_column,
    zonal_channel_mask,
    zonal_top_flat,
)
from hydromodpy.model.domain.domain import Domain
from hydromodpy.model.domain.domain_config import DomainConfig
from hydromodpy.model.domain.top_sampling_config import TopSamplingConfig
from tests._helpers.cell_meshes import TEST_CRS_WKT

N, PIXEL_M, NOTCH_M = 40, 2.5, 0.5
X_M = (np.arange(N) + 0.5) * PIXEL_M


def surface(values: np.ndarray, name: str) -> Surface:
    support = RasterSupport(
        crs="EPSG:2154", dx=PIXEL_M, dy=PIXEL_M, xmin=0.0, xmax=100.0, ymin=0.0, ymax=100.0,
        nrows=N, ncols=N, nodata=-9999.0,
    )  # fmt: skip
    return Surface(name=name, values=values, support=support)


def domain_on_ramp(notch: bool = True) -> Domain:
    dem = np.tile(X_M, (N, 1))
    if notch:
        dem[:, (X_M >= 10.0) & (X_M <= 15.0)] = NOTCH_M
    domain = Domain(config=DomainConfig(), surface_topo=surface(dem, "surface_topo"))
    domain.substratum = surface(np.full((N, N), -10.0), "substratum")
    return domain


def two_cells(offset: float | None):
    hydro = HydroMesh(
        vertices=np.array([[0, 0], [50, 0], [100, 0], [0, 100], [50, 100], [100, 100]], float),
        cell_blocks=(CellBlock(CellType.QUADRILATERAL, np.array([[0, 1, 4, 3], [1, 2, 5, 4]])),),
    )
    chains = ()
    if offset is not None:
        chains = (CellChain("rivers", 0, np.array([0, 1]), np.array([offset, 0.0])),)
    return build_planar_cell_mesh(
        hydro,
        np.column_stack(hydro.cell_centroids()),
        center_kind="vertex_mean",
        crs_wkt=TEST_CRS_WKT,
        identity=MeshIdentity("test", "0", "", None),
        declarations={"graded": False, "exact_faces": False, "deterministic": True, "needs_cache": False},
        cell_chains=chains,
    )  # fmt: skip


def columns(offset: float | None):
    keywords = {"cell_mesh": two_cells(offset), "domain": domain_on_ramp(), "top_sampling": None}
    return modflow_column(channel_mask=None, **keywords), centre_column(
        channel_mask=None, **keywords
    )


def test_rules_agree_on_a_mesh_without_a_crossing_cell():
    modflow, centre = columns(None)

    np.testing.assert_array_equal(modflow.top, centre.top)
    np.testing.assert_array_equal(modflow.bottom, centre.bottom)


def test_rules_differ_on_the_cell_a_river_crosses_off_its_center():
    modflow, centre = columns(8.0)

    assert modflow.top[0] == pytest.approx(NOTCH_M, abs=1e-6)
    assert centre.top[0] == pytest.approx(25.0, abs=1.0)
    assert modflow.top[1] == centre.top[1]


NO_MASK = [
    pytest.param(None, id="no top sampling"),
    pytest.param(TopSamplingConfig(), id="centroid mode"),
    pytest.param(TopSamplingConfig(mode="zonal", channel_source="none"), id="no channel source"),
    pytest.param(TopSamplingConfig(mode="zonal"), id="no stream raster"),
]


@pytest.mark.parametrize("top_sampling", NO_MASK)
def test_no_channel_mask_unless_zonal_has_a_stream_raster(top_sampling):
    mask = zonal_channel_mask(
        raster=None, surface=domain_on_ramp().surface_topo, top_sampling=top_sampling
    )

    assert mask is None


def _channel_tif(path, *, crs, nodata=None, bounds=(0.0, 0.0, 100.0, 100.0)):
    """Write a 4 x 4 stream raster whose pixel (1, 2) is a channel with link id 7."""
    import rasterio
    from rasterio.transform import from_bounds

    data = np.zeros((4, 4), dtype=np.float32)
    data[1, 2] = 7.0
    with rasterio.open(
        path, "w", driver="GTiff", height=4, width=4, count=1, dtype="float32",
        crs=crs, transform=from_bounds(*bounds, 4, 4), nodata=nodata,
    ) as dst:  # fmt: skip
        dst.write(data, 1)
    return str(path)


def _surface_4x4(**change) -> Surface:
    support = RasterSupport(
        crs="EPSG:2154", dx=25.0, dy=25.0, xmin=0.0, xmax=100.0, ymin=0.0, ymax=100.0,
        nrows=4, ncols=4, nodata=-9999.0,
    )  # fmt: skip
    for name, value in change.items():
        object.__setattr__(support, name, value)
    return Surface(name="surface_topo", values=np.zeros((4, 4)), support=support)


def _raster(link=None, clipped=()):
    return SimpleNamespace(channel=SimpleNamespace(link=link, clipped=tuple(clipped)))


ZONAL = TopSamplingConfig(mode="zonal")


def _mask(raster, surface=None, top_sampling=ZONAL):
    return zonal_channel_mask(
        raster=raster, surface=surface or _surface_4x4(), top_sampling=top_sampling
    )


@pytest.mark.parametrize(
    ("crs", "nodata", "buffer_px", "expected"),
    [
        pytest.param("EPSG:2154", None, 0, [(1, 2)], id="plain"),
        pytest.param(None, None, 0, [(1, 2)], id="no crs is the model space"),
        pytest.param("EPSG:2154", 7.0, 0, [], id="positive nodata is dropped"),
        pytest.param("EPSG:2154", None, 1, [(0, 2), (1, 1), (1, 2), (1, 3), (2, 2)], id="buffered"),
    ],
)  # fmt: skip
def test_the_channel_mask_marks_the_positive_pixels_of_the_stream_raster(
    tmp_path, crs, nodata, buffer_px, expected
):
    link = _channel_tif(tmp_path / "link.tif", crs=crs, nodata=nodata)
    top_sampling = TopSamplingConfig(mode="zonal", channel_buffer_px=buffer_px)

    mask = _mask(_raster(link=link), top_sampling=top_sampling)

    assert sorted(zip(*np.nonzero(mask), strict=True)) == expected


def test_the_channel_mask_falls_back_to_the_first_clipped_raster_that_exists(tmp_path):
    clipped = _channel_tif(tmp_path / "clipped.tif", crs="EPSG:2154")

    mask = _mask(
        _raster(link=str(tmp_path / "gone.tif"), clipped=[str(tmp_path / "no.tif"), clipped])
    )

    assert mask.sum() == 1


def test_the_channel_mask_is_disabled_when_no_stream_raster_exists(tmp_path, caplog):
    with caplog.at_level("WARNING"):
        mask = _mask(_raster(clipped=[str(tmp_path / "missing.tif")]))

    assert mask is None
    assert "no stream raster found" in caplog.text


def test_the_channel_mask_is_disabled_on_a_surface_without_georeferencing(tmp_path, caplog):
    link = _channel_tif(tmp_path / "link.tif", crs="EPSG:2154")

    with caplog.at_level("WARNING"):
        mask = _mask(_raster(link=link), surface=_surface_4x4(xmin=None))

    assert mask is None
    assert "needs a georeferenced surface" in caplog.text


def test_the_channel_mask_is_disabled_when_the_reprojection_fails(tmp_path, caplog):
    link = _channel_tif(tmp_path / "link.tif", crs="EPSG:2154")

    with caplog.at_level("WARNING"):
        mask = _mask(_raster(link=link), surface=_surface_4x4(crs="not a crs"))

    assert mask is None
    assert "reprojection failed" in caplog.text


def _zonal_inputs(surface: Surface) -> dict:
    return {
        "top_surface": surface, "centroid_top": np.full(16, 3.0), "bottom_flat": np.zeros(16),
        "nodata": -9999.0, "top_sampling": ZONAL, "channel_mask": None,
    }  # fmt: skip


@pytest.mark.parametrize(
    ("surface", "message"),
    [
        pytest.param(Surface(name="s", values=np.zeros((4, 4))), "needs a georeferenced surface", id="no support"),
        pytest.param(
            Surface(name="s", values=np.zeros((3, 3)), support=_surface_4x4().support),
            "does not match its support", id="shape differs",
        ),
    ],
)  # fmt: skip
def test_zonal_top_keeps_the_centroid_sample_when_it_cannot_reduce_the_dem(
    surface, message, caplog
):
    with caplog.at_level("WARNING"):
        top = zonal_top_flat(**_zonal_inputs(surface))

    np.testing.assert_array_equal(top, np.full(16, 3.0))
    assert message in caplog.text


@pytest.mark.parametrize(
    ("native", "grid", "expected"),
    [
        pytest.param({}, {"nrows": 2, "ncols": 2}, True, id="a cell spans four pixels"),
        pytest.param({}, {}, False, id="a cell spans one pixel"),
        pytest.param({"nrows": None}, {}, True, id="no georeferencing keeps the zonal step"),
    ],
)  # fmt: skip
def test_cells_cover_pixels_reads_the_areas_of_both_grids(native, grid, expected):
    assert cells_cover_pixels(_surface_4x4(**native), _surface_4x4(**grid)) is expected
