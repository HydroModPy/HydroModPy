from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import rasterio
from rasterio.transform import from_origin

from hydromodpy.analysis.postprocess.timeseries.flow_timeseries import FlowTimeseriesPostprocess


def _write_raster(
    path: Path,
    data: np.ndarray,
    *,
    transform,
    nodata: float = -9999.0,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=int(data.shape[1]),
        height=int(data.shape[0]),
        count=1,
        dtype=str(data.dtype),
        transform=transform,
        crs="EPSG:2154",
        nodata=nodata,
    ) as dst:
        dst.write(data, 1)
    return path


class _RecorderTimeseries(FlowTimeseriesPostprocess):
    def __init__(self, *args, **kwargs) -> None:
        self.calls: list[dict[str, object]] = []
        super().__init__(*args, **kwargs)

    def extract_results(self, dem_clip, time, recharge, runoff, timeseries_file):
        self.calls.append(
            {
                "shape": tuple(np.asarray(dem_clip).shape),
                "cell": int(self.cell),
                "timeseries_file": str(timeseries_file),
            }
        )
        return None


def test_flow_timeseries_aligns_subbasin_masks_to_solver_grid(tmp_path: Path) -> None:
    nodata = -9999.0
    base_raster = _write_raster(
        tmp_path / "solver_template.tif",
        np.array([[10.0, 11.0], [12.0, 13.0]], dtype=np.float32),
        transform=from_origin(0.0, 2.0, 1.0, 1.0),
        nodata=nodata,
    )
    _write_raster(
        tmp_path / "stable" / "subbasin" / "zone_a" / "watershed_dem.tif",
        np.array([[10.0, nodata]], dtype=np.float32),
        transform=from_origin(0.0, 2.0, 1.0, 2.0),
        nodata=nodata,
    )

    geographic = SimpleNamespace(
        stable_folder=str(tmp_path / "stable"),
        simulations_folder=str(tmp_path / "simulations"),
        watershed_dem=str(base_raster),
        nodata=nodata,
    )
    model_modflow = SimpleNamespace(
        model_name="flow_main",
        model_folder=str(tmp_path / "models"),
        resolution=1.0,
        cell_area=1.0,
        dem_watershed_path=str(base_raster),
        recharge=1.0,
    )

    recorder = _RecorderTimeseries(
        geographic=geographic,
        model_modflow=model_modflow,
        subbasin_results=True,
    )

    assert recorder.calls[0]["shape"] == (2, 2)
    assert recorder.calls[0]["cell"] == 4
    assert recorder.calls[1]["shape"] == (2, 2)
    assert recorder.calls[1]["cell"] == 2


def test_flow_timeseries_accepts_missing_recharge() -> None:
    postprocess = object.__new__(FlowTimeseriesPostprocess)
    postprocess.recharge = None
    postprocess.runoff = None

    time, recharge, runoff = postprocess._normalize_forcing_series()

    assert time == [0]
    assert recharge is None
    assert np.isnan(runoff)
