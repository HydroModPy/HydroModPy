from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.solver.modflow6 import Modflow6, Modflow6Transport
from hydromodpy.solver.modflow_common.solver_mesh import SolverMesh
from hydromodpy.solver.modflow_nwt.modflow import ModflowPostprocessOptions
from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh
from hydromodpy.spatial.mesh.gmsh_grid.runtime_support import GmshSupportMetadata


class _DummyGeographic:
    def __init__(self, dem: np.ndarray):
        self.dem_res = 1.0
        self.xmin = 0.0
        self.ymax = float(dem.shape[0])
        self.dem_box_buff_data = np.asarray(dem, dtype=float)
        self.dem_data = np.asarray(dem, dtype=float)
        self.watershed_box_buff_dem = "dummy_box.tif"
        self.watershed_buff_dem = "dummy_buff.tif"


class _DummyHeadFile:
    def __init__(self, path: str):
        self.path = path

    def get_times(self) -> list[float]:
        return [1.0]

    def get_data(self, *, totim: float) -> np.ndarray:
        del totim
        return np.array([[[9.0, 8.5], [8.0, 7.5]]], dtype=float)


class _DummyHeadFileUnstructured:
    def __init__(self, path: str):
        self.path = path

    def get_times(self) -> list[float]:
        return [1.0]

    def get_data(self, *, totim: float) -> np.ndarray:
        del totim
        return np.array([[9.0, 8.5]], dtype=float)


class _DummyUcnFileUnstructured:
    def __init__(self, path: str):
        self.path = path

    def get_times(self) -> list[float]:
        return [1.0]

    def get_alldata(self, *, mflay=None) -> np.ndarray:
        del mflay
        return np.array([[[0.2, 0.4]]], dtype=float)


class _DummyBudgetFile:
    def __init__(self, path: str):
        self.path = path

    def get_data(self, *, kstpkper, text: str):
        del kstpkper, text
        raise ValueError("The specified text string is not in the budget file")


class _DummyBudgetFileWithDrn:
    def __init__(self, path: str):
        self.path = path

    def get_data(self, *, kstpkper, text: str):
        del kstpkper
        assert text == "DRN"
        return [np.array([[1.0, -2.5], [4.0, 1.0]], dtype=float)]


class _DummyBudgetFileWithDrnAndChd:
    def __init__(self, path: str):
        self.path = path

    def get_data(self, *, kstpkper, text: str):
        del kstpkper
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


class _DummyBudgetFileUnexpectedValueError:
    def __init__(self, path: str):
        self.path = path

    def get_data(self, *, kstpkper, text: str):
        del kstpkper, text
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
    monkeypatch.setattr("hydromodpy.solver.modflow6.modflow6.bf.HeadFile", _DummyHeadFile)
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.modflow6.bf.CellBudgetFile",
        budget_file_cls,
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.modflow6.pp.get_water_table",
        lambda head, nodata: np.asarray(head[0], dtype=float),
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.modflow6.export_tif",
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


def test_modflow6_post_processing_tolerates_missing_drn_budget(
    monkeypatch,
    tmp_path: Path,
) -> None:
    work_dir = _workspace_dir(tmp_path, "mf6_postprocess_missing_drn")
    model = _build_model(work_dir)
    _patch_postprocess_runtime(monkeypatch, _DummyBudgetFile)

    model.post_processing(ModflowPostprocessOptions(accumulation_flux=False))

    assert np.allclose(model.dict_outflow_drain[0], 0.0)
    assert np.allclose(model.dict_seepage_areas[0], 0.0)
    assert np.allclose(
        model.dict_watertable_elevation[0], np.array([[9.0, 8.5], [8.0, 7.5]], dtype=float)
    )


def test_modflow6_post_processing_reads_drn_budget_when_present(
    monkeypatch,
    tmp_path: Path,
) -> None:
    work_dir = _workspace_dir(tmp_path, "mf6_postprocess_with_drn")
    model = _build_model(work_dir)
    _patch_postprocess_runtime(monkeypatch, _DummyBudgetFileWithDrn)

    model.post_processing(ModflowPostprocessOptions(accumulation_flux=False))

    np.testing.assert_allclose(
        model.dict_outflow_drain[0],
        np.array([[2.5, 0.0], [0.0, 0.0]], dtype=float),
    )
    np.testing.assert_allclose(
        model.dict_seepage_areas[0],
        np.array([[1.0, 0.0], [0.0, 0.0]], dtype=float),
    )


def test_modflow6_post_processing_exports_east_side_chd_discharge(
    monkeypatch,
    tmp_path: Path,
) -> None:
    work_dir = _workspace_dir(tmp_path, "mf6_postprocess_with_chd")
    model = _build_model(work_dir)
    _patch_postprocess_runtime(monkeypatch, _DummyBudgetFileWithDrnAndChd)

    model.post_processing(
        ModflowPostprocessOptions(
            accumulation_flux=False,
            outlet_discharge_east_side_m3_s=True,
        )
    )

    np.testing.assert_allclose(
        model.dict_outlet_discharge_east_side_m3_s[0],
        np.array([6.0], dtype=float),
    )


def test_modflow6_post_processing_reraises_unexpected_budget_value_errors(
    monkeypatch,
    tmp_path: Path,
) -> None:
    work_dir = _workspace_dir(tmp_path, "mf6_postprocess_unexpected_value_error")
    model = _build_model(work_dir)
    _patch_postprocess_runtime(monkeypatch, _DummyBudgetFileUnexpectedValueError)

    with pytest.raises(ValueError, match="Corrupted DRN record payload"):
        model.post_processing(ModflowPostprocessOptions())


def test_modflow6_post_processing_routes_accumulation_flux_via_masstransfer(
    monkeypatch,
    tmp_path: Path,
) -> None:
    work_dir = _workspace_dir(tmp_path, "mf6_postprocess_accumulation_flux")
    model = _build_model(work_dir)
    _patch_postprocess_runtime(monkeypatch, _DummyBudgetFileWithDrn)

    exported_paths: list[Path] = []
    masstransfer_calls: list[dict[str, object]] = []
    accumulated = np.array([[5.0, 4.0], [3.0, -9999.0]], dtype=float)

    def _fake_export_tif(_template, _data, output_path, _nodata):
        exported_paths.append(Path(output_path))

    class _FakeMasstransfer:
        def __init__(
            self,
            geographic,
            raw_rast_name,
            trace_shp_name,
            mass_rast_name,
            *,
            extraction_folder,
            routing_fill_path,
            routing_direc_path,
        ) -> None:
            masstransfer_calls.append(
                {
                    "geographic": geographic,
                    "raw_rast_name": raw_rast_name,
                    "trace_shp_name": trace_shp_name,
                    "mass_rast_name": mass_rast_name,
                    "extraction_folder": extraction_folder,
                    "routing_fill_path": routing_fill_path,
                    "routing_direc_path": routing_direc_path,
                    "trace_cumulated_called": False,
                }
            )

        def trace_cumulated(self) -> None:
            masstransfer_calls[-1]["trace_cumulated_called"] = True

    class _FakeRasterReader:
        def __init__(self, path: str):
            self.path = path

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, band: int) -> np.ndarray:
            assert band == 1
            return accumulated

    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.modflow6.export_tif",
        _fake_export_tif,
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.modflow6.masstransfer.Masstransfer",
        _FakeMasstransfer,
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.modflow6.rasterio.open",
        lambda path: _FakeRasterReader(path),
    )
    monkeypatch.setattr(
        model,
        "_ensure_solver_routing_context",
        lambda: SimpleNamespace(correc_path="routing_fill.tif", direc_path="routing_direc.tif"),
    )

    model.post_processing(
        ModflowPostprocessOptions(
            outflow_drain=False,
            accumulation_flux=True,
            watertable_elevation=False,
            watertable_depth=False,
            seepage_areas=False,
            groundwater_flux=False,
            groundwater_storage=False,
        )
    )

    save_dir = Path(model.full_path) / "_postprocess"
    np.testing.assert_allclose(model.dict_accumulation_flux[0], accumulated)
    assert masstransfer_calls == [
        {
            "geographic": model.geographic,
            "raw_rast_name": "outflow_drain_t(0).tif",
            "trace_shp_name": "tracept_t(0).shp",
            "mass_rast_name": "accumulation_flux_t(0).tif",
            "extraction_folder": str(save_dir),
            "routing_fill_path": "routing_fill.tif",
            "routing_direc_path": "routing_direc.tif",
            "trace_cumulated_called": True,
        }
    ]
    assert exported_paths == [save_dir / "_rasters" / "outflow_drain_t(0).tif"]


def test_modflow6_post_processing_exports_native_unstructured_mesh_outputs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    work_dir = _workspace_dir(tmp_path, "mf6_postprocess_native_mesh")
    model = _build_unstructured_model(work_dir)
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.modflow6.bf.HeadFile", _DummyHeadFileUnstructured
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.modflow6.bf.CellBudgetFile",
        _DummyBudgetFile,
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.modflow6.pp.get_water_table",
        lambda head, nodata: np.asarray(head, dtype=float).reshape(-1),
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.modflow6.export_tif",
        lambda *args, **kwargs: None,
    )

    written_vtu: list[tuple[Path, object]] = []

    def _fake_write_vtu(path: str, hydro_mesh) -> Path:
        path_obj = Path(path)
        path_obj.write_text("dummy vtu", encoding="utf-8")
        written_vtu.append((path_obj, hydro_mesh))
        return path_obj

    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.io.write_vtu",
        _fake_write_vtu,
    )

    model.post_processing(
        ModflowPostprocessOptions(
            accumulation_flux=False,
            native_mesh_npz=True,
            native_mesh_csv=True,
            native_mesh_vtu=True,
            native_mesh_png=True,
        )
    )

    mesh_dir = Path(model.full_path) / "_postprocess" / "_mesh"
    figure_dir = Path(model.full_path) / "_postprocess" / "_figures" / "native_mesh"
    watertable_npz = np.load(mesh_dir / "flow_watertable_elevation.npz")
    assert watertable_npz["values"].shape == (1, 2)
    np.testing.assert_allclose(watertable_npz["values"][0], np.array([9.0, 8.5], dtype=float))
    np.testing.assert_allclose(watertable_npz["times"], np.array([1.0], dtype=float))

    csv_lines = (
        (mesh_dir / "flow_watertable_elevation.csv").read_text(encoding="utf-8").splitlines()
    )
    assert csv_lines[0] == "time_index,time,cell_id,value"
    assert csv_lines[1].startswith("0,1.0,0,9.0")

    assert len(written_vtu) == 1
    _, hydro_mesh = written_vtu[0]
    assert sorted(hydro_mesh.cell_data.keys()) == [
        "cell_id",
        "outflow_drain",
        "seepage_areas",
        "top_elevation",
        "watertable_depth",
        "watertable_elevation",
    ]
    assert (figure_dir / "flow_watertable_elevation_t(0).png").exists()


def test_modflow6_post_processing_accumulates_unstructured_flow_on_mesh(
    monkeypatch,
    tmp_path: Path,
) -> None:
    work_dir = _workspace_dir(tmp_path, "mf6_postprocess_unstructured_accumulation")
    model = _build_unstructured_model(work_dir, dem_values=np.asarray([10.0, 5.0], dtype=float))
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.modflow6.bf.HeadFile", _DummyHeadFileUnstructured
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.modflow6.bf.CellBudgetFile",
        _DummyBudgetFileWithDrn,
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.modflow6.pp.get_water_table",
        lambda head, nodata: np.asarray(head, dtype=float).reshape(-1),
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.modflow6.export_tif",
        lambda *args, **kwargs: None,
    )

    model.post_processing(
        ModflowPostprocessOptions(
            accumulation_flux=True,
            native_mesh_npz=False,
            native_mesh_csv=False,
            native_mesh_vtu=False,
            native_mesh_png=False,
        )
    )

    save_dir = Path(model.full_path) / "_postprocess"
    accumulation = np.load(save_dir / "accumulation_flux.npy", allow_pickle=True).item()
    np.testing.assert_allclose(
        accumulation[0],
        np.asarray([2.5, 2.5], dtype=float),
    )


def test_modflow6_transport_post_processing_exports_native_unstructured_mesh_outputs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    work_dir = _workspace_dir(tmp_path, "mf6_transport_postprocess_native_mesh")
    flow_model = _build_unstructured_model(work_dir)
    flow_model.last_postprocess_options = ModflowPostprocessOptions(
        accumulation_flux=False,
        native_mesh_npz=True,
        native_mesh_csv=True,
        native_mesh_vtu=True,
        native_mesh_png=True,
    )
    flow_model.dict_outflow_drain = {0: np.array([1.0, 2.0], dtype=float)}
    transport_model = _build_unstructured_transport_model(flow_model)

    save_dir = Path(flow_model.full_path) / "_postprocess"
    save_dir.mkdir(parents=True, exist_ok=True)

    written_vtu: list[tuple[Path, object]] = []

    def _fake_write_vtu(path: str, hydro_mesh) -> Path:
        path_obj = Path(path)
        path_obj.write_text("dummy vtu", encoding="utf-8")
        written_vtu.append((path_obj, hydro_mesh))
        return path_obj

    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.modflow6.bf.UcnFile",
        _DummyUcnFileUnstructured,
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.modflow6.export_tif",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.io.write_vtu",
        _fake_write_vtu,
    )

    transport_model.post_processing(
        transport_model,
        concentration_seepage=True,
        mass_seepage=True,
        mass_accumulated=False,
    )

    mesh_dir = save_dir / "_mesh"
    figure_dir = save_dir / "_figures" / "native_mesh"
    concentration_npz = np.load(mesh_dir / "transport_concentration_seepage.npz")
    np.testing.assert_allclose(
        concentration_npz["values"][0],
        np.array([0.2, 0.4], dtype=float),
    )
    np.testing.assert_allclose(concentration_npz["times"], np.array([1.0], dtype=float))

    csv_lines = (mesh_dir / "transport_mass_seepage.csv").read_text(encoding="utf-8").splitlines()
    assert csv_lines[0] == "time_index,time,cell_id,value"
    assert csv_lines[1].startswith("0,1.0,0,0.2")

    assert len(written_vtu) == 1
    _, hydro_mesh = written_vtu[0]
    assert sorted(hydro_mesh.cell_data.keys()) == [
        "cell_id",
        "concentration_seepage",
        "mass_seepage",
        "top_elevation",
    ]
    assert (figure_dir / "transport_concentration_seepage_t(0).png").exists()


def test_modflow6_transport_post_processing_accumulates_unstructured_mass(
    monkeypatch,
    tmp_path: Path,
) -> None:
    work_dir = _workspace_dir(tmp_path, "mf6_transport_postprocess_unstructured_accumulation")
    flow_model = _build_unstructured_model(
        work_dir, dem_values=np.asarray([10.0, 5.0], dtype=float)
    )
    flow_model.last_postprocess_options = ModflowPostprocessOptions(
        accumulation_flux=False,
        native_mesh_npz=False,
        native_mesh_csv=False,
        native_mesh_vtu=False,
        native_mesh_png=False,
    )
    flow_model.dict_outflow_drain = {0: np.array([1.0, 0.0], dtype=float)}
    transport_model = _build_unstructured_transport_model(flow_model)

    save_dir = Path(flow_model.full_path) / "_postprocess"
    save_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.modflow6.bf.UcnFile",
        _DummyUcnFileUnstructured,
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.modflow6.export_tif",
        lambda *args, **kwargs: None,
    )

    transport_model.post_processing(
        transport_model,
        concentration_seepage=False,
        mass_seepage=False,
        mass_accumulated=True,
    )

    mass_accumulated = np.load(save_dir / "mass_accumulated.npy", allow_pickle=True).item()
    np.testing.assert_allclose(
        mass_accumulated[0],
        np.asarray([0.2, 0.2], dtype=float),
    )


def test_modflow6_post_processing_tolerates_missing_meshio_for_vtu_export(
    monkeypatch,
    tmp_path: Path,
) -> None:
    work_dir = _workspace_dir(tmp_path, "mf6_postprocess_missing_meshio")
    model = _build_unstructured_model(work_dir)
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.modflow6.bf.HeadFile", _DummyHeadFileUnstructured
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.modflow6.bf.CellBudgetFile",
        _DummyBudgetFile,
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.modflow6.pp.get_water_table",
        lambda head, nodata: np.asarray(head, dtype=float).reshape(-1),
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.modflow6.export_tif",
        lambda *args, **kwargs: None,
    )

    def _raise_import_error(path: str, hydro_mesh) -> Path:
        del path, hydro_mesh
        raise ImportError("meshio is required for VTU I/O")

    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.io.write_vtu",
        _raise_import_error,
    )

    model.post_processing(
        ModflowPostprocessOptions(
            accumulation_flux=False,
            native_mesh_npz=False,
            native_mesh_csv=False,
            native_mesh_vtu=True,
            native_mesh_png=True,
        )
    )

    figure_dir = Path(model.full_path) / "_postprocess" / "_figures" / "native_mesh"
    assert (figure_dir / "flow_watertable_elevation_t(0).png").exists()


def test_modflow6_post_processing_exports_runtime_support_overview(
    monkeypatch,
    tmp_path: Path,
) -> None:
    work_dir = _workspace_dir(tmp_path, "mf6_postprocess_support_overview")
    model = _build_unstructured_model(work_dir)
    model.runtime_mesh_support = _build_unstructured_support_metadata()
    model.flow = SimpleNamespace(
        active_bc=["west_side", "stream"],
        active_sinks_sources=["wells"],
        boundary_conditions={
            "west_side": SimpleNamespace(value=1.0, units="m", support_label=None),
            "stream": SimpleNamespace(value=2.0, units="m", support_label=None),
        },
        sinks_sources={
            "wells": {
                "W1": SimpleNamespace(
                    location_mode="absolute_xy",
                    layer=0,
                    x=0.25,
                    y=0.25,
                    flux=-1.0,
                )
            }
        },
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.modflow6.bf.HeadFile", _DummyHeadFileUnstructured
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.modflow6.bf.CellBudgetFile",
        _DummyBudgetFile,
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.modflow6.pp.get_water_table",
        lambda head, nodata: np.asarray(head, dtype=float).reshape(-1),
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.modflow6.export_tif",
        lambda *args, **kwargs: None,
    )

    model.post_processing(
        ModflowPostprocessOptions(
            accumulation_flux=False,
            native_mesh_png=True,
        )
    )

    overview_path = (
        Path(model.full_path)
        / "_postprocess"
        / "_figures"
        / "native_mesh"
        / "flow_support_overview.png"
    )
    assert overview_path.exists()
