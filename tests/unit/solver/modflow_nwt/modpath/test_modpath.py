"""MODPATH reads heads that hold the ``hdry`` and ``hnoflo`` sentinels and writes a raster with ``-9999``.

The seepage raster of the flow run is derived from its heads. A head equal to ``hnoflo`` or ``hdry``
is not a water table: the water table stands in the highest layer with a finite head, and a column
with none seeps nowhere. The raster takes ``-9999`` as its own nodata.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import flopy
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from hydromodpy.solver.base.plan import RunSlot, SolverRun
from hydromodpy.solver.modflow_nwt.modpath import modpath

_HNOFLO = -9999.0
_HDRY = -1.0e30


def _write_dem(path: Path) -> None:
    profile = {
        "driver": "GTiff",
        "height": 1,
        "width": 1,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:2154",
        "transform": from_origin(0.0, 1.0, 1.0, 1.0),
        "nodata": -9999.0,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(np.array([[10.0]], dtype="float32"), 1)


def _seepage(monkeypatch, tmp_path: Path, heads: list[float], topography: float, band=0.0):
    class _Heads:
        def __init__(self, _path: str) -> None:
            pass

        def get_times(self) -> list[float]:
            return [1.0]

        def get_data(self, totim: float) -> np.ndarray:
            del totim
            return np.array(heads, dtype="float64").reshape(len(heads), 1, 1)

        def close(self) -> None:
            pass

    monkeypatch.setattr(flopy.utils.binaryfile, "HeadFile", _Heads)
    flow_dir = tmp_path / "flow"
    flow_dir.mkdir(parents=True)
    (flow_dir / "run.hds").write_bytes(b"")
    dem = tmp_path / "dem.tif"
    _write_dem(dem)
    flow = SimpleNamespace(
        full_path=str(flow_dir),
        model_name="run",
        dem_watershed_path=str(dem),
        bas_hnoflo=_HNOFLO,
        upw_hdry=_HDRY,
        top_elevation=np.array([topography]),
        nrow=1,
        ncol=1,
    )
    options = SimpleNamespace(drain_band_depth_m=band)
    run = SolverRun(
        slot=RunSlot(tmp_path, "run"),
        model=SimpleNamespace(options=options),
        options=None,
        solver_model=flow,
        output_dir=flow_dir,
        written=True,
        solved=True,
    )

    modpath._write_seepage_clip_raster(run)

    path = flow_dir / "_postprocess" / "_rasters" / "seepage_areas_t(0).tif"
    with rasterio.open(path) as src:
        assert src.nodata == -9999.0
        return float(src.read(1)[0, 0])


# One row per column of two layers: the heads of the top and the lower layer, the land surface and
# whether the cell seeps (the water table reaches the land surface, band zero).
_COLUMNS = [
    pytest.param([10.0, 5.0], 10.0, 1.0, id="water_table_at_the_surface"),
    pytest.param([12.0, 5.0], 10.0, 1.0, id="water_table_above_the_surface"),
    pytest.param([8.0, 5.0], 10.0, 0.0, id="water_table_below_the_surface"),
    pytest.param([_HNOFLO, 10.0], 10.0, 1.0, id="hnoflo_top_layer_is_skipped"),
    pytest.param([_HNOFLO, 5.0], 10.0, 0.0, id="hnoflo_then_a_low_head"),
    pytest.param([_HDRY, 9.0], 10.0, 0.0, id="hdry_top_layer_is_skipped"),
    pytest.param([_HNOFLO, _HDRY], 10.0, 0.0, id="no_finite_head_seeps_nowhere"),
    pytest.param([np.nan, 10.0], 10.0, 1.0, id="nan_top_layer_is_skipped"),
]


@pytest.mark.parametrize(("heads", "topography", "seeps"), _COLUMNS)
def test_a_sentinel_head_is_no_water_table(monkeypatch, tmp_path, heads, topography, seeps) -> None:
    assert _seepage(monkeypatch, tmp_path, heads, topography) == seeps


def test_a_drain_band_lets_the_water_table_seep_from_half_a_band_below_the_surface(
    monkeypatch, tmp_path
) -> None:
    assert _seepage(monkeypatch, tmp_path, [9.0, 5.0], 10.0, band=2.0) == 1.0
    assert _seepage(monkeypatch, tmp_path / "other", [8.9, 5.0], 10.0, band=2.0) == 0.0
