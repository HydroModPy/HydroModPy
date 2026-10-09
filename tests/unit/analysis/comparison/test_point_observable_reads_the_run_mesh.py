"""A point observable located by x/y finds its cell on the mesh the run stored."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import zarr

from hydromodpy.analysis.comparison.runtime.mesh import (
    cells_from_run_mesh,
    resolve_bundle_cells,
)


class _Handle:
    def __init__(self, root) -> None:
        self.root = root

    def close(self) -> None:
        return None


class _Store:
    """The part of a Catalog the lookup uses: ``open_zarr``."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def open_zarr(self, sim_id: str) -> _Handle:
        return _Handle(zarr.open_group(str(self._path), mode="r"))


def _write_grid(path: Path) -> None:
    # Two cells side by side: [0, 10] x [0, 10] and [10, 30] x [0, 10].
    root = zarr.open_group(str(path), mode="w")
    mesh = root.create_group("mesh")
    vertices = np.array(
        [[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0], [30, 0, 0], [30, 10, 0]],
        dtype=float,
    )
    faces = np.array([[0, 1, 2, 3], [1, 4, 5, 2]], dtype=np.int32)
    mesh.create_array("vertices", data=vertices)
    mesh.create_array("face_node_connectivity", data=faces)


def test_cells_come_from_the_stored_mesh(tmp_path: Path) -> None:
    _write_grid(tmp_path / "fields.zarr")
    cells = cells_from_run_mesh(_Store(tmp_path / "fields.zarr"), "sim")

    assert cells is not None
    np.testing.assert_allclose(cells.x, [5.0, 20.0])
    np.testing.assert_allclose(cells.y, [5.0, 5.0])
    np.testing.assert_allclose(cells.area_m2, [100.0, 200.0])
    assert cells.nearest_cell_id(x=24.0, y=2.0) == 1


def test_resolver_reads_the_store_when_the_run_has_no_bundle(tmp_path: Path) -> None:
    _write_grid(tmp_path / "fields.zarr")
    run_folder = tmp_path / "run"
    run_folder.mkdir()

    assert resolve_bundle_cells(run_folder) is None
    cells = resolve_bundle_cells(
        run_folder,
        expected_size=2,
        store=_Store(tmp_path / "fields.zarr"),
        sim_id="sim",
    )
    assert cells is not None
    assert cells.nearest_cell_id(x=1.0, y=9.0) == 0


def test_a_size_mismatch_is_not_taken(tmp_path: Path) -> None:
    _write_grid(tmp_path / "fields.zarr")
    run_folder = tmp_path / "run"
    run_folder.mkdir()
    cells = resolve_bundle_cells(
        run_folder,
        expected_size=5,
        store=_Store(tmp_path / "fields.zarr"),
        sim_id="sim",
    )
    assert cells is None


def test_a_run_without_fields_gives_none() -> None:
    class _Empty:
        def open_zarr(self, sim_id: str):
            raise KeyError(sim_id)

    assert cells_from_run_mesh(_Empty(), "missing") is None
