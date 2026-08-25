from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np

from hydromodpy.solver.modflow_nwt.nwt import ModflowPostprocessOptions

from ._test_modflow6_postprocessing_builders import (
    _build_unstructured_model,
    _build_unstructured_support_metadata,
    _DummyBudgetFile,
    _DummyBudgetFileWithDrn,
    _DummyHeadFileUnstructured,
    _path_exists,
    _workspace_dir,
)


def test_modflow6_post_processing_exports_native_unstructured_mesh_outputs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    work_dir = _workspace_dir(tmp_path, "mf6_postprocess_native_mesh")
    model = _build_unstructured_model(work_dir)
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.postprocess.pipeline.bf.HeadFile", _DummyHeadFileUnstructured
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.postprocess.pipeline.bf.CellBudgetFile",
        _DummyBudgetFile,
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.postprocess.pipeline.raster_io.export_tif",
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
    assert _path_exists(figure_dir / "flow_watertable_elevation_t(0).png")


def test_modflow6_post_processing_accumulates_unstructured_flow_on_mesh(
    monkeypatch,
    tmp_path: Path,
) -> None:
    work_dir = _workspace_dir(tmp_path, "mf6_postprocess_unstructured_accumulation")
    model = _build_unstructured_model(work_dir, dem_values=np.asarray([10.0, 5.0], dtype=float))
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.postprocess.pipeline.bf.HeadFile", _DummyHeadFileUnstructured
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.postprocess.pipeline.bf.CellBudgetFile",
        _DummyBudgetFileWithDrn,
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.postprocess.pipeline.raster_io.export_tif",
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


def test_modflow6_post_processing_tolerates_missing_meshio_for_vtu_export(
    monkeypatch,
    tmp_path: Path,
) -> None:
    work_dir = _workspace_dir(tmp_path, "mf6_postprocess_missing_meshio")
    model = _build_unstructured_model(work_dir)
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.postprocess.pipeline.bf.HeadFile", _DummyHeadFileUnstructured
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.postprocess.pipeline.bf.CellBudgetFile",
        _DummyBudgetFile,
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.postprocess.pipeline.raster_io.export_tif",
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
    assert _path_exists(figure_dir / "flow_watertable_elevation_t(0).png")


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
                    location=SimpleNamespace(
                        kind="absolute_xy",
                        layer=0,
                        x=0.25,
                        y=0.25,
                    ),
                    flux=-1.0,
                )
            }
        },
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.postprocess.pipeline.bf.HeadFile", _DummyHeadFileUnstructured
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.postprocess.pipeline.bf.CellBudgetFile",
        _DummyBudgetFile,
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.postprocess.pipeline.raster_io.export_tif",
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
    assert _path_exists(overview_path)
