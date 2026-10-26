"""A comparison map takes its grid and its cells from the mesh the run stored.

The choice between an image and polygons reads ``structured_shape`` in the
``mesh/`` group of ``fields.zarr``, never the TOML of the run, and the image is
drawn with row 0 at the top (north first).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import matplotlib.pyplot as plt
import numpy as np
import pytest
import zarr

from hydromodpy.analysis.comparison import visuals_payloads
from hydromodpy.analysis.comparison.runtime import mesh as runtime_mesh
from hydromodpy.analysis.comparison.runtime.mesh import (
    cells_from_run_mesh,
    resolve_run_cells,
    resolve_summary_cells,
)
from hydromodpy.analysis.comparison.runtime.series import VariableSeries
from hydromodpy.analysis.comparison.visuals_render_maps import _render_map_subplot

NROW, NCOL = 3, 4
XMIN, YMAX, STEP = 100.0, 230.0, 10.0


class _Handle:
    def __init__(self, root) -> None:
        self.root = root

    def close(self) -> None:
        return None


class _Store:
    """The part of a RunSource the readers use: the run, ``open_zarr`` and ``close``."""

    sim_id = "sim"

    def __init__(self, path: Path) -> None:
        self._path = path
        self.run_dir = path.parent

    def open_zarr(self, sim_id: str | None = None) -> _Handle:
        return _Handle(zarr.open_group(str(self._path), mode="r"))

    def close(self) -> None:
        return None

    def __enter__(self) -> _Store:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _write_grid(path: Path, *, structured: bool) -> None:
    """A 3 x 4 grid of 10 m cells, row 0 at the north, as the regular engine writes it."""
    ys = YMAX - STEP * np.arange(NROW + 1)
    xs = XMIN + STEP * np.arange(NCOL + 1)
    vertices = np.array([[x, y, 0.0] for y in ys for x in xs])
    node = np.arange((NROW + 1) * (NCOL + 1)).reshape(NROW + 1, NCOL + 1)
    faces = np.array(
        [
            [node[i, j], node[i, j + 1], node[i + 1, j + 1], node[i + 1, j]]
            for i in range(NROW)
            for j in range(NCOL)
        ],
        dtype=np.int32,
    )
    root = zarr.open_group(str(path), mode="w")
    mesh = root.create_group("mesh")
    mesh.create_array("vertices", data=vertices)
    mesh.create_array("face_node_connectivity", data=faces)
    if structured:
        mesh.attrs["structured_shape"] = [NROW, NCOL]


def test_the_shape_comes_from_the_stored_mesh(tmp_path: Path) -> None:
    _write_grid(tmp_path / "fields.zarr", structured=True)
    cells = cells_from_run_mesh(_Store(tmp_path / "fields.zarr"), "sim")

    assert cells is not None
    assert cells.structured_shape == (NROW, NCOL)
    # Row 0 is the northern row.
    np.testing.assert_allclose(cells.y[:NCOL], YMAX - STEP / 2)
    np.testing.assert_allclose(cells.x[:NCOL], XMIN + STEP * (np.arange(NCOL) + 0.5))


def test_a_mesh_that_is_no_grid_has_no_shape(tmp_path: Path) -> None:
    _write_grid(tmp_path / "fields.zarr", structured=False)
    cells = cells_from_run_mesh(_Store(tmp_path / "fields.zarr"), "sim")

    assert cells is not None
    assert cells.structured_shape is None


def _stub_the_series(monkeypatch: pytest.MonkeyPatch, values: np.ndarray, store: _Store) -> None:
    monkeypatch.setattr(visuals_payloads, "open_run_source", lambda summary: store)
    monkeypatch.setattr(
        visuals_payloads,
        "load_variable_series",
        lambda **k: VariableSeries("head", Path("head"), ()),
    )
    monkeypatch.setattr(
        visuals_payloads, "mask_depth_series_from_head_nodata", lambda **k: k["series"]
    )
    monkeypatch.setattr(visuals_payloads, "_choose_map_slice", lambda **k: (values, "t0"))


def _map_payload(tmp_path: Path, values: np.ndarray):
    observable = SimpleNamespace(
        reducer=None, name="head_map", unit="m", variable="head", time_reducer=None
    )
    simulation = SimpleNamespace(id="a", label="A", solver="modflow6", mesh_mode="structured")
    return visuals_payloads._build_map_payload(
        cfg=SimpleNamespace(),
        simulation=simulation,
        summary={"run_folder": str(tmp_path / "run"), "run_dir": str(tmp_path / "run")},
        observable=observable,
        rows=[],
    )


def test_the_structured_branch_is_chosen_without_a_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_grid(tmp_path / "fields.zarr", structured=True)
    values = np.arange(NROW * NCOL, dtype=float)
    _stub_the_series(monkeypatch, values, _Store(tmp_path / "fields.zarr"))

    payload = _map_payload(tmp_path, values)

    assert payload is not None
    assert payload.geometry_kind == "structured"
    assert payload.structured_shape == (NROW, NCOL)
    assert payload.extent == (XMIN, XMIN + NCOL * STEP, YMAX - NROW * STEP, YMAX)


def test_a_mesh_without_a_shape_is_drawn_as_polygons(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_grid(tmp_path / "fields.zarr", structured=False)
    values = np.arange(NROW * NCOL, dtype=float)
    _stub_the_series(monkeypatch, values, _Store(tmp_path / "fields.zarr"))

    payload = _map_payload(tmp_path, values)

    assert payload is not None
    assert payload.geometry_kind == "scatter"


def test_the_stored_mesh_is_read_before_any_reconstruction(tmp_path: Path) -> None:
    _write_grid(tmp_path / "fields.zarr", structured=True)

    cells = resolve_run_cells(_Store(tmp_path / "fields.zarr"), "sim", expected_size=NROW * NCOL)

    assert cells is not None
    assert cells.structured_shape == (NROW, NCOL)


def test_the_map_has_north_at_the_top(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Row 0 holds the northernmost cells: the image must put it at the top."""
    _write_grid(tmp_path / "fields.zarr", structured=True)
    # A field that grows with the northing, so a flipped image cannot pass.
    values = np.repeat(np.arange(NROW)[::-1], NCOL).astype(float)
    _stub_the_series(monkeypatch, values, _Store(tmp_path / "fields.zarr"))
    payload = _map_payload(tmp_path, values)
    assert payload is not None

    figure, ax = plt.subplots()
    try:
        _render_map_subplot(ax, payload, cmap="viridis", vmin=0.0, vmax=float(NROW))
        image = ax.images[0]
        left, right, bottom, top = image.get_extent()
        assert image.origin == "upper"
        array = np.asarray(image.get_array())
        # The plotted y of the centre of image row i, as matplotlib places it.
        step = (top - bottom) / array.shape[0]
        plotted_y = top - step * (np.arange(array.shape[0]) + 0.5)
        stored_y = payload.y.reshape(payload.structured_shape)[:, 0]
        np.testing.assert_allclose(plotted_y, stored_y)
        # And the value shown at the top row is the one of the northernmost cells.
        assert array[0, 0] == values.max()
    finally:
        plt.close(figure)


def test_a_summary_finds_the_stored_mesh_of_its_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Areas and centres of a comparison come from the run directory the summary names."""
    _write_grid(tmp_path / "fields.zarr", structured=True)
    asked: list[object] = []

    def open_source(summary):
        asked.append(summary.get("run_dir"))
        return _Store(tmp_path / "fields.zarr")

    monkeypatch.setattr(runtime_mesh, "open_run_source", open_source)

    cells = resolve_summary_cells({"run_dir": str(tmp_path)})

    assert cells is not None
    assert asked == [str(tmp_path)]
    np.testing.assert_allclose(cells.area_m2, STEP * STEP)
