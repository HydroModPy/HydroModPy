from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from hydromodpy.solver.modflow6 import Modflow6, Modflow6Transport
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh
from hydromodpy.spatial.mesh.gmsh_grid.runtime_support import GmshSupportMetadata


def _path_exists(path: Path) -> bool:
    if path.exists():
        return True
    if os.name != "nt":
        return False
    absolute = str(path.absolute())
    if absolute.startswith("\\\\?\\"):
        return Path(absolute).exists()
    if absolute.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + absolute.lstrip("\\")).exists()
    return Path("\\\\?\\" + absolute).exists()


class _DummyGeographic:
    def __init__(self, dem: np.ndarray):
        self.dem_res = 1.0
        self.xmin = 0.0
        self.ymax = float(dem.shape[0])
        self.dem_box_buff_data = np.asarray(dem, dtype=float)
        self.dem_data = np.asarray(dem, dtype=float)
        self.watershed_box_buff_dem = "dummy_box.tif"
        self.watershed_buff_dem = "dummy_buff.tif"


class _ClosableReader:
    """Test double for a flopy binary reader; supports close() like the real one."""

    def close(self) -> None:
        return None


class _DummyHeadFile(_ClosableReader):
    def __init__(self, path: str):
        self.path = path

    def get_times(self) -> list[float]:
        return [1.0]

    def get_kstpkper(self) -> list[tuple[int, int]]:
        return [(0, 0)]

    def get_data(self, *, totim: float) -> np.ndarray:
        del totim
        return np.array([[[9.0, 8.5], [8.0, 7.5]]], dtype=float)


class _DummyHeadFileUnstructured(_ClosableReader):
    def __init__(self, path: str):
        self.path = path

    def get_times(self) -> list[float]:
        return [1.0]

    def get_kstpkper(self) -> list[tuple[int, int]]:
        return [(0, 0)]

    def get_data(self, *, totim: float) -> np.ndarray:
        del totim
        return np.array([[9.0, 8.5]], dtype=float)


class _DummyUcnFileUnstructured(_ClosableReader):
    def __init__(self, path: str):
        self.path = path

    def get_times(self) -> list[float]:
        return [1.0]

    def get_alldata(self, *, mflay=None) -> np.ndarray:
        del mflay
        return np.array([[[0.2, 0.4]]], dtype=float)


class _DummyBudgetFile(_ClosableReader):
    def __init__(self, path: str):
        self.path = path

    def get_data(self, *, kstpkper, text: str, totim=None):
        del kstpkper, text, totim
        raise ValueError("The specified text string is not in the budget file")


class _DummyBudgetFileWithDrn(_ClosableReader):
    def __init__(self, path: str):
        self.path = path

    def get_data(self, *, kstpkper, text: str, totim=None):
        del kstpkper, totim
        assert text == "DRN"
        return [np.array([[1.0, -2.5], [4.0, 1.0]], dtype=float)]


class _DummyBudgetFileWithDrnAndChd(_ClosableReader):
    def __init__(self, path: str):
        self.path = path

    def get_data(self, *, kstpkper, text: str, totim=None):
        del kstpkper, totim
        if text == "DRN":
            return [np.array([[1.0, -2.5], [4.0, 1.0]], dtype=float)]
        if text == "CHD":
            dtype = np.dtype([("node", "<i4"), ("node2", "<i4"), ("q", "<f8")])
            return [
                np.array(
                    [
                        (1, 0, 1.5),
                        (2, 0, -2.5),
                        (3, 0, 0.5),
                        (4, 0, -3.5),
                    ],
                    dtype=dtype,
                )
            ]
        raise ValueError("The specified text string is not in the budget file")


class _DummyBudgetFileUnexpectedValueError(_ClosableReader):
    def __init__(self, path: str):
        self.path = path

    def get_data(self, *, kstpkper, text: str, totim=None):
        del kstpkper, text, totim
        raise ValueError("Corrupted DRN record payload")


def _workspace_dir(tmp_path: Path, case_name: str) -> Path:
    work_dir = tmp_path / case_name
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def _build_model(work_dir: Path) -> Modflow6:
    dem = np.array([[10.0, 10.0], [10.0, 10.0]], dtype=float)
    geo = _DummyGeographic(dem)
    model = Modflow6(geographic=geo, model_folder=str(work_dir), model_name="Demo")
    model.full_path = str(work_dir / "Demo")
    model.dem = dem.ravel()  # flat (ncpl,)
    model.dem_mask = np.zeros(4, dtype=bool)  # flat (ncpl,)
    model.dem_watershed_path = str(work_dir / "grid.tif")
    model.nrow = 2
    model.ncol = 2
    model.ncpl = 4
    model.nlay = 1
    model.solver_mesh = SimpleNamespace(
        is_structured=True,
        nrow=2,
        ncol=2,
        reshape_to_grid=lambda arr: np.asarray(arr, dtype=float).reshape(2, 2),
    )
    return model


def _patch_postprocess_runtime(monkeypatch, budget_file_cls: type[object]) -> None:
    monkeypatch.setattr("hydromodpy.solver.modflow6.postprocess.bf.HeadFile", _DummyHeadFile)
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.postprocess.bf.CellBudgetFile",
        budget_file_cls,
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.postprocess.raster_io.export_tif",
        lambda *args, **kwargs: None,
    )


def _build_unstructured_model(
    work_dir: Path,
    *,
    dem_values: np.ndarray | None = None,
) -> Modflow6:
    dem = np.array([[10.0, 10.0]], dtype=float)
    geo = _DummyGeographic(dem)
    model = Modflow6(geographic=geo, model_folder=str(work_dir), model_name="DemoUnstructured")
    model.full_path = str(work_dir / "DemoUnstructured")
    vertices = np.asarray(
        [
            [0.0, 0.0],
            [1.0, 0.0],
            [1.0, 1.0],
            [0.0, 1.0],
        ],
        dtype=float,
    )
    planar_mesh = HydroMesh(
        vertices=vertices,
        cell_blocks=(CellBlock(CellType.TRIANGLE, np.asarray([[0, 1, 2], [0, 2, 3]], dtype=int)),),
    )
    model.solver_mesh = SolverMesh(
        planar_mesh=planar_mesh,
        top=np.asarray([10.0, 10.0], dtype=float),
        botm=np.asarray([[1.0, 1.0]], dtype=float),
        inactive_mask=np.zeros((1, 2), dtype=bool),
    )
    model.dem = np.asarray(
        [10.0, 10.0] if dem_values is None else dem_values,
        dtype=float,
    ).reshape(-1)
    model.dem_mask = np.zeros(2, dtype=bool)
    model.dem_watershed_path = ""
    model.ncpl = 2
    model.nlay = 1
    model.nper = 1
    return model


def _build_unstructured_transport_model(model_modflow: Modflow6) -> Modflow6Transport:
    transport_model = object.__new__(Modflow6Transport)
    transport_model.model_modflow = model_modflow
    transport_model.full_path = model_modflow.full_path
    transport_model.model_name_mt = f"{model_modflow.model_name}_gwt"
    return transport_model


def _build_unstructured_support_metadata() -> GmshSupportMetadata:
    return GmshSupportMetadata(
        cell_ids=np.asarray([0, 1], dtype=int),
        node_ids=np.asarray([0, 1, 2, 3], dtype=int),
        node_x_m=np.asarray([0.0, 1.0, 1.0, 0.0], dtype=float),
        node_y_m=np.asarray([0.0, 0.0, 1.0, 1.0], dtype=float),
        cell_node_indices=((0, 1, 2), (0, 2, 3)),
        cell_centroid_x_m=np.asarray([2.0 / 3.0, 1.0 / 3.0], dtype=float),
        cell_centroid_y_m=np.asarray([1.0 / 3.0, 2.0 / 3.0], dtype=float),
        edge_ids=np.asarray([0, 1, 2, 3, 4], dtype=int),
        edge_node_a_index=np.asarray([0, 1, 2, 3, 0], dtype=int),
        edge_node_b_index=np.asarray([1, 2, 3, 0, 2], dtype=int),
        edge_cell_a=np.asarray([0, 0, 1, 1, 0], dtype=int),
        edge_cell_b=np.asarray([-1, -1, -1, -1, 1], dtype=int),
        edge_midpoint_x_m=np.asarray([0.5, 1.0, 0.5, 0.0, 0.5], dtype=float),
        edge_midpoint_y_m=np.asarray([0.0, 0.5, 1.0, 0.5, 0.5], dtype=float),
        edge_kind=("boundary", "boundary", "boundary", "boundary", "internal"),
        edge_is_river=np.asarray([False, False, False, False, True], dtype=bool),
        geology_a_key=("", "", "", "", ""),
        geology_b_key=("", "", "", "", ""),
        boundary_labels_by_edge_id={
            0: "south_side",
            1: "east_side",
            2: "north_side",
            3: "west_side",
        },
    )
