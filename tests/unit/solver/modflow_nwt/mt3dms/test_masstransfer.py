"""The mass routed downslope reads a seepage raster whose negative cells are no mass.

A seepage raster carries ``-9999`` where the cell has no seepage or no data. The loading
raster clamps every negative cell to zero, so the sentinel never travels as a mass, and the
helper rasters carry their own ``-99999`` nodata.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from hydromodpy.solver.modflow_nwt.mt3dms.masstransfer import Masstransfer


def _write(path: Path, data: np.ndarray, *, nodata: float) -> None:
    profile = {
        "driver": "GTiff",
        "height": data.shape[0],
        "width": data.shape[1],
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:2154",
        "transform": from_origin(0.0, float(data.shape[0]), 1.0, 1.0),
        "nodata": nodata,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data.astype("float32"), 1)


def _read(path: Path) -> np.ndarray:
    with rasterio.open(path) as src:
        return src.read(1)


def _trace(tmp_path: Path, raw: np.ndarray, surface_flow: np.ndarray) -> tuple[Path, dict]:
    calls: dict[str, tuple] = {}

    class _Flow:
        def d8_mass_flux(self, *paths: str) -> None:
            calls["d8_mass_flux"] = paths

    mass = Masstransfer.__new__(Masstransfer)
    mass.raw_rast_path = str(tmp_path / "raw.tif")
    mass.watershed_buff_fill_surflow = str(tmp_path / "surflow.tif")
    mass.load_rast_path = str(tmp_path / "load.tif")
    mass.eff_rast_path = str(tmp_path / "eff.tif")
    mass.abs_rast_path = str(tmp_path / "abs.tif")
    mass.mass_rast_path = str(tmp_path / "mass.tif")
    mass._backend = SimpleNamespace(flow=_Flow())
    _write(Path(mass.raw_rast_path), raw, nodata=-9999.0)
    _write(Path(mass.watershed_buff_fill_surflow), surface_flow, nodata=-99999.0)
    mass.trace_cumulated()
    return tmp_path, calls


# One row per seepage cell: its value in the raster and the load it gives. The sentinel
# -9999 and every other negative cell load nothing.
_LOADS = [
    pytest.param(5.0, 5.0, id="a_mass_is_kept"),
    pytest.param(0.0, 0.0, id="no_mass"),
    pytest.param(-9999.0, 0.0, id="the_sentinel_is_no_mass"),
    pytest.param(-1.0e-3, 0.0, id="a_small_negative_is_no_mass"),
]


@pytest.mark.parametrize(("seepage", "load"), _LOADS)
def test_a_negative_seepage_cell_loads_no_mass(tmp_path, seepage, load) -> None:
    raw = np.array([[seepage, 1.0], [1.0, 1.0]])
    surface_flow = np.full((2, 2), 3.0)

    folder, calls = _trace(tmp_path, raw, surface_flow)

    loaded = _read(folder / "load.tif")
    assert loaded[0, 0] == pytest.approx(load)
    assert loaded[0, 1] == 1.0
    assert calls["d8_mass_flux"][-1] == str(folder / "mass.tif")


@pytest.mark.parametrize(
    ("surface_flow", "efficiency", "adsorption"),
    [
        pytest.param(3.0, 1.0, 0.0, id="a_routed_cell_passes_everything_on"),
        pytest.param(0.0, 1.0, 0.0, id="zero_is_still_on_the_grid"),
        pytest.param(-99999.0, -99999.0, -99999.0, id="the_nodata_of_the_grid_is_kept"),
    ],
)
def test_a_cell_off_the_routing_grid_keeps_the_helper_nodata(
    tmp_path, surface_flow, efficiency, adsorption
) -> None:
    raw = np.ones((2, 2))
    routing = np.full((2, 2), 3.0)
    routing[0, 0] = surface_flow

    folder, _ = _trace(tmp_path, raw, routing)

    assert _read(folder / "eff.tif")[0, 0] == efficiency
    assert _read(folder / "abs.tif")[0, 0] == adsorption
    with rasterio.open(folder / "eff.tif") as src:
        assert src.nodata == -99999.0
