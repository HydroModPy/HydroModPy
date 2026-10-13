from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.solver.modflow6.postprocess import (
    build_unstructured_cell_adjacency,
    east_side_cell_ids,
)
from hydromodpy.solver.modflow6.support.diagnostics import (
    build_support_overlay_specs,
    build_well_overlay_specs,
    cell_outlines,
    export_runtime_support_overview,
    family_edge_segments,
    mesh_edge_segments,
)
from hydromodpy.solver.modflow_nwt.nwt import ModflowPostprocessOptions

from ._test_modflow6_boundary_conditions_builders import (
    _build_unstructured_runtime,
    regular_solver_mesh,
)
from ._test_modflow6_postprocessing_builders import (
    _build_model,
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


def test_the_east_side_cells_come_from_the_cell_mesh(tmp_path: Path) -> None:
    structured = _build_model(_workspace_dir(tmp_path, "east_grid"))
    unstructured = _build_unstructured_model(_workspace_dir(tmp_path, "east_triangles"))

    # 2 x 2 grid: the east column is cells 1 and 3. Triangles: the east edge is cell 0's.
    assert east_side_cell_ids(structured) == {1, 3}
    assert east_side_cell_ids(unstructured) == {0}


def test_the_adjacency_of_the_unstructured_accumulation_is_the_one_of_the_cell_mesh(
    tmp_path: Path,
) -> None:
    model = _build_unstructured_model(_workspace_dir(tmp_path, "adjacency"))

    assert build_unstructured_cell_adjacency(model) == [{1}, {0}]


def test_the_overview_segments_are_read_from_the_edges_and_families_of_the_cell_mesh() -> None:
    solver_mesh, _ = _build_unstructured_runtime(river_internal_edge=True)
    cell_mesh = solver_mesh.cell_mesh

    edges = mesh_edge_segments(cell_mesh)
    river = family_edge_segments(cell_mesh, "rivers")

    assert edges.shape == (5, 2, 2)
    assert sorted(map(tuple, river[0].tolist())) == [(0.0, 0.0), (1.0, 1.0)]
    assert family_edge_segments(cell_mesh, "no_such_family").shape == (0, 2, 2)
    west = family_edge_segments(cell_mesh, "boundary:west")
    assert np.allclose(west[:, :, 0], 0.0)


def test_the_cell_outlines_follow_the_vertices_of_the_cells() -> None:
    solver_mesh, _ = _build_unstructured_runtime()

    outlines = cell_outlines(solver_mesh.cell_mesh, np.asarray([1, 1, 0, 7, -1]))

    assert [outline.tolist() for outline in outlines] == [
        [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]],
        [[0.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
    ]


def test_the_overlays_name_the_cells_of_each_active_boundary(tmp_path: Path) -> None:
    model = _build_unstructured_model(_workspace_dir(tmp_path, "overlays"))
    model.flow = SimpleNamespace(
        active_bc=["west_side", "stream"],
        boundary_conditions={
            "west_side": SimpleNamespace(value=1.0, units="m", support_label=None),
            "stream": SimpleNamespace(value=2.0, units="m", support_label=None),
        },
    )

    overlays = {label: cells.tolist() for label, cells, _ in build_support_overlay_specs(model)}

    assert overlays == {"west_side": [1], "stream": [0, 1]}


def test_a_well_overlay_sits_at_the_centre_of_its_cell(tmp_path: Path) -> None:
    model = _build_unstructured_model(_workspace_dir(tmp_path, "well_overlay"))
    model.flow = SimpleNamespace(
        active_sinks_sources=["wells"],
        sinks_sources={
            "wells": {
                "W1": SimpleNamespace(
                    location=SimpleNamespace(kind="absolute_xy", layer=0, x=0.9, y=0.2),
                    flux=-1.0,
                )
            }
        },
    )

    (item,) = build_well_overlay_specs(model)

    assert item["cell_id"] == 0
    assert (item["x_m"], item["y_m"]) == (pytest.approx(2.0 / 3.0), pytest.approx(1.0 / 3.0))


def test_the_overview_of_a_regular_grid_is_drawn_too(tmp_path: Path) -> None:
    model = _build_model(_workspace_dir(tmp_path, "overview_grid"))
    model.solver_mesh = regular_solver_mesh(2, 2)
    model.save_file = str(tmp_path / "overview_grid" / "save")
    model.flow = None

    export_runtime_support_overview(model, options=ModflowPostprocessOptions(native_mesh_png=True))

    assert _path_exists(
        Path(model.save_file) / "_figures" / "native_mesh" / "flow_support_overview.png"
    )
