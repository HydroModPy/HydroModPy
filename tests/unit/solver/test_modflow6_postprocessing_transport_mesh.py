from __future__ import annotations

from pathlib import Path

import numpy as np

from hydromodpy.solver.modflow_nwt.nwt import ModflowPostprocessOptions

from ._test_modflow6_postprocessing_builders import (
    _build_unstructured_model,
    _build_unstructured_transport_model,
    _DummyUcnFileUnstructured,
    _path_exists,
    _workspace_dir,
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
        "hydromodpy.solver.modflow6.postprocess.bf.UcnFile",
        _DummyUcnFileUnstructured,
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.postprocess.raster_io.export_tif",
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
    assert _path_exists(figure_dir / "transport_concentration_seepage_t(0).png")


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
        "hydromodpy.solver.modflow6.postprocess.bf.UcnFile",
        _DummyUcnFileUnstructured,
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.postprocess.raster_io.export_tif",
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
