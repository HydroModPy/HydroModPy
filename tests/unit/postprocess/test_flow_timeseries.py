from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin

from hydromodpy.analysis.postprocess.timeseries.flow_timeseries import FlowTimeseriesPostprocess
from hydromodpy.solver.modflow_common.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh


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
        out_dir_path=str(tmp_path / "stable"),
        stable_folder=str(tmp_path / "stable"),
        simulations_folder=str(tmp_path / "models"),
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


def _build_unstructured_solver_mesh() -> SolverMesh:
    planar_mesh = HydroMesh(
        vertices=np.asarray(
            [
                [0.0, 0.0],
                [1.0, 0.0],
                [1.0, 1.0],
                [0.0, 1.0],
                [3.0, 0.0],
                [3.0, 1.0],
            ],
            dtype=float,
        ),
        cell_blocks=(
            CellBlock(
                CellType.QUADRILATERAL,
                np.asarray(
                    [
                        [0, 1, 2, 3],
                        [1, 4, 5, 2],
                    ],
                    dtype=int,
                ),
            ),
        ),
    )
    return SolverMesh(
        planar_mesh=planar_mesh,
        top=np.asarray([10.0, 10.0], dtype=float),
        botm=np.asarray([[1.0, 1.0]], dtype=float),
        inactive_mask=np.zeros((1, 2), dtype=bool),
    )


class _FakeFieldStore:
    """Minimal store mock that serves pre-loaded spatial fields."""

    def __init__(self, fields: dict[str, dict[int, np.ndarray]]) -> None:
        self._fields = fields

    def list_simulations(self, sim_id: str | None = None) -> pd.DataFrame:
        return pd.DataFrame({"sim_id": ["fake"], "n_timesteps": [1]})

    def query_field(self, sim_id: str, variable: str, timestep: int) -> np.ndarray:
        if variable in self._fields and timestep in self._fields[variable]:
            return self._fields[variable][timestep]
        raise KeyError(f"{variable} t={timestep}")


def test_flow_timeseries_exports_unstructured_weighted_outputs(tmp_path: Path) -> None:
    nodata = -9999.0
    solver_mesh = _build_unstructured_solver_mesh()

    fields = {
        "watertable_depth": {0: np.asarray([1.0, 4.0], dtype=float)},
        "seepage_areas": {0: np.asarray([1.0, 0.0], dtype=float)},
    }
    store = _FakeFieldStore(fields)

    _write_raster(
        tmp_path / "stable" / "subbasin" / "zone_a" / "watershed_dem.tif",
        np.array([[nodata, 1.0, 1.0]], dtype=np.float32),
        transform=from_origin(0.0, 1.0, 1.0, 1.0),
        nodata=nodata,
    )

    geographic = SimpleNamespace(
        out_dir_path=str(tmp_path / "stable"),
        stable_folder=str(tmp_path / "stable"),
        simulations_folder=str(tmp_path / "simulations"),
        watershed_dem=str(tmp_path / "unused_base.tif"),
        nodata=nodata,
    )
    model_modflow = SimpleNamespace(
        model_name="flow_unstructured",
        model_folder=str(tmp_path / "models"),
        resolution=1.0,
        cell_area=1.0,
        dem_watershed_path=str(tmp_path / "unused_base.tif"),
        recharge=pd.Series([0.1], index=["2020-01-01"]),
        solver_mesh=solver_mesh,
        dem=np.asarray([10.0, 10.0], dtype=float),
        dem_mask=np.asarray([False, False], dtype=bool),
    )

    FlowTimeseriesPostprocess(
        geographic=geographic,
        model_modflow=model_modflow,
        subbasin_results=True,
        store=store,
        sim_id="fake",
    )

    catchment_csv = (
        tmp_path
        / "models"
        / "flow_unstructured"
        / "_postprocess"
        / "_timeseries"
        / "_simulated_timeseries.csv"
    )
    subbasin_csv = (
        tmp_path
        / "models"
        / "flow_unstructured"
        / "_subbasins"
        / "zone_a"
        / "_simulated_timeseries.csv"
    )

    catchment = pd.read_csv(catchment_csv, sep=";")
    subbasin = pd.read_csv(subbasin_csv, sep=";")

    assert catchment.loc[0, "date"] == "2020-01-01"
    assert catchment.loc[0, "watertable_depth"] == pytest.approx(3.0)
    assert catchment.loc[0, "seepage_areas"] == pytest.approx((1.0 / 3.0) * 100.0)
    assert subbasin.loc[0, "watertable_depth"] == pytest.approx(4.0)
    assert subbasin.loc[0, "seepage_areas"] == pytest.approx(0.0)
