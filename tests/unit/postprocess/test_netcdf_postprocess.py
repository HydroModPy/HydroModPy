from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr
from shapely.geometry import Point

from hydromodpy.analysis.postprocess.netcdf import (
    FlowNetcdfPostprocess,
    TransportNetcdfPostprocess,
)
from hydromodpy.solver.modflow_common.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh


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


def test_flow_netcdf_exports_cell_based_outputs_for_unstructured_mesh(
    tmp_path: Path,
) -> None:
    solver_mesh = _build_unstructured_solver_mesh()
    save_dir = tmp_path / "models" / "flow_unstructured" / "_postprocess"
    save_dir.mkdir(parents=True, exist_ok=True)
    np.save(
        save_dir / "watertable_depth",
        {0: np.asarray([1.0, 4.0], dtype=float)},
    )

    geographic = SimpleNamespace(
        watershed_dem=str(tmp_path / "unused_base.tif"),
        crs_proj="EPSG:2154",
    )
    model_modflow = SimpleNamespace(
        model_name="flow_unstructured",
        model_folder=str(tmp_path / "models"),
        recharge=pd.Series([0.1], index=["2020-01-01"]),
        solver_mesh=solver_mesh,
        dem_watershed_path=str(tmp_path / "unused_base.tif"),
    )

    FlowNetcdfPostprocess(
        geographic=geographic,
        model_modflow=model_modflow,
        datetime_format=False,
    )

    out_path = save_dir / "_netcdf" / "watertable_depth.nc"
    with xr.open_dataset(out_path) as ds:
        assert ds["watertable_depth"].dims == ("time", "cell")
        np.testing.assert_allclose(
            ds["watertable_depth"].values,
            np.asarray([[1.0, 4.0]], dtype=float),
            atol=1.0e-4,
        )
        np.testing.assert_allclose(ds["cell_x"].values, np.asarray([0.5, 2.0], dtype=float))
        np.testing.assert_allclose(ds["cell_area"].values, np.asarray([1.0, 2.0], dtype=float))
        assert ds.attrs["crs"] == "EPSG:2154"


def test_transport_netcdf_exports_cell_based_residence_times_for_unstructured_mesh(
    tmp_path: Path,
    monkeypatch,
) -> None:
    solver_mesh = _build_unstructured_solver_mesh()
    save_dir = tmp_path / "models" / "flow_unstructured" / "_postprocess"
    particles_dir = save_dir / "_particles"
    particles_dir.mkdir(parents=True, exist_ok=True)
    particle_path = particles_dir / "ending.shp"
    particle_path.touch()

    class _Support:
        @staticmethod
        def locate_cell_index_for_point(x_m: float, y_m: float, *, allow_nearest: bool = True) -> int:
            del y_m, allow_nearest
            return 0 if x_m < 1.0 else 1

    geographic = SimpleNamespace(
        watershed_dem=str(tmp_path / "unused_base.tif"),
        crs_proj="EPSG:2154",
    )
    model_modflow = SimpleNamespace(
        model_name="flow_unstructured",
        model_folder=str(tmp_path / "models"),
        recharge=pd.Series([0.1], index=["2020-01-01"]),
        solver_mesh=solver_mesh,
        dem_watershed_path=str(tmp_path / "unused_base.tif"),
        runtime_mesh_support=_Support(),
    )
    model_modpath = SimpleNamespace(track_dir="forward")

    particles = gpd.GeoDataFrame(
        {
            "time": [5.0, 15.0],
            "geometry": [Point(0.25, 0.25), Point(2.5, 0.5)],
        },
        crs="EPSG:2154",
    )
    monkeypatch.setattr(
        "hydromodpy.analysis.postprocess.netcdf.transport_netcdf.gpd.read_file",
        lambda path: particles,
    )

    TransportNetcdfPostprocess(
        geographic=geographic,
        model_modflow=model_modflow,
        model_modpath=model_modpath,
        model_mt3dms=None,
        datetime_format=False,
        concentration_seepage=False,
        mass_accumulated=False,
        residence_times=True,
    )

    out_path = save_dir / "_netcdf" / "residence_times.nc"
    with xr.open_dataset(out_path) as ds:
        assert ds["residence_times"].dims == ("time", "cell")
        np.testing.assert_allclose(
            ds["residence_times"].values,
            np.asarray([[5.0, 15.0]], dtype=float),
            atol=1.0e-4,
        )
