"""The top and the bottom of every cell, read once from the domain by the rule a backend declares.

Two cells side by side (x 0-50 m and 50-100 m) lie on a DEM ramp z = x with a notch of 0.5 m in cell 0, off its center. A river chain with a lateral offset marks cell 0 as a crossing cell.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.catchment.raster_support import RasterSupport
from hydromodpy.catchment.surface import Surface
from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.mesh.planar.planar_cell_mesh import CellChain, MeshIdentity, build_planar_cell_mesh
from hydromodpy.model.domain.cell_column import (
    centre_column,
    modflow_column,
    zonal_channel_mask,
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
