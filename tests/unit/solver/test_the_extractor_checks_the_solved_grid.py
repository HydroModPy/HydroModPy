"""The extractors check the grid the solver used against the mesh the run stored.

The mesh is written once, before the run. After the solve, the MODFLOW 6 grid
file (or the NWT DIS grid) must be that same mesh: otherwise heads sealed into
the store would sit on the wrong cells. Rounding by flopy and the clockwise
DISV ring order are the only accepted differences.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core.exceptions import IncompatibleMeshError, MeshError
from hydromodpy.results.zarr_store import SimulationZarr
from hydromodpy.solver.modflow6.extractors.grid_check import (
    grb_rings,
    verify_disv_grid,
    verify_grid_against_store,
)
from hydromodpy.solver.modflow6.support.computational_top import GROUND_SIDECAR_SUFFIX
from hydromodpy.solver.modflow6.support.written_grid import reoriented_rows, written_step
from hydromodpy.solver.modflow_nwt.extractors.flow import verify_dis_grid
from tests._helpers.ugrid_meshes import quad_mesh

NROW, NCOL = 3, 4
N_CELLS = NROW * NCOL


def _flopy_round(values: np.ndarray) -> np.ndarray:
    """The text round trip flopy 3.10 applies to a coordinate it writes."""
    out = np.empty_like(values, dtype=np.float64)
    flat = values.ravel()
    for i, v in enumerate(flat):
        scaled = (abs(v) > 1e5 or abs(v) < 1e-3) and v != 0
        out.reshape(-1)[i] = float(f"{v:.8E}") if scaled else float(f"{v:15.8f}")
    return out


def _grb(vertices_xy: np.ndarray, rings: np.ndarray, centers: np.ndarray | None = None):
    """A stand-in for ``MfGrdFile``: closed rings in ``iavert``/``javert``, zero based."""
    closed = [[*row[row >= 0], row[0]] for row in rings]
    lengths = np.array([len(r) for r in closed])
    return SimpleNamespace(
        verts=vertices_xy,
        iavert=np.concatenate([[0], np.cumsum(lengths)]),
        javert=np.concatenate(closed),
        cellcenters=centers,
        grid_type="DISV",
    )


def _stored(origin=(0.0, 0.0)) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    vertices, rings = quad_mesh(NROW, NCOL, cell_size=75.0)
    vertices[:, 0] += origin[0]
    vertices[:, 1] += origin[1]
    centers = vertices[rings][:, :, :2].mean(axis=1)
    return vertices, rings.astype(np.int32), centers


def test_a_grid_that_is_the_stored_mesh_passes_with_the_rings_walked_the_other_way() -> None:
    vertices, rings, centers = _stored()
    solved = _grb(vertices[:, :2], reoriented_rows(rings), centers)

    check = verify_disv_grid(solved, vertices=vertices, connectivity=rings, centers=centers)

    assert check.n_reversed_cells == N_CELLS
    assert check.max_vertex_shift_m == 0.0
    assert check.max_center_shift_m == 0.0


def test_the_flopy_rounding_of_lambert_coordinates_is_not_a_difference() -> None:
    rng = np.random.default_rng(3)
    vertices, rings, centers = _stored(origin=(351234.56789123, 6801234.98765432))
    vertices[:, :2] += rng.uniform(-3.0, 3.0, size=(vertices.shape[0], 2))
    centers = vertices[rings][:, :, :2].mean(axis=1)
    solved = _grb(_flopy_round(vertices[:, :2]), rings, _flopy_round(centers))

    check = verify_disv_grid(solved, vertices=vertices, connectivity=rings, centers=centers)

    assert 0.0 < check.max_vertex_shift_m <= 0.505 * 1e-2
    assert check.n_reversed_cells == 0


def test_the_written_step_follows_the_flopy_rule() -> None:
    step = written_step(np.array([0.0, 12.5, 351234.5, 6801234.9, 5e-4, -2e5]))

    np.testing.assert_allclose(step, [1e-8, 1e-8, 1e-3, 1e-2, 1e-12, 1e-3])


def test_a_vertex_one_centimetre_off_in_x_names_the_vertex_and_a_cell() -> None:
    vertices, rings, centers = _stored(origin=(351234.0, 6801234.0))
    moved = vertices[:, :2].copy()
    moved[7, 0] += 0.01
    solved = _grb(moved, rings, centers)

    with pytest.raises(IncompatibleMeshError, match=r"vertex 7 .* first cell using it: \d+"):
        verify_disv_grid(solved, vertices=vertices, connectivity=rings, centers=centers)


def test_two_swapped_cells_name_the_first_cell_that_differs() -> None:
    vertices, rings, centers = _stored()
    swapped = rings.copy()
    swapped[[2, 5]] = swapped[[5, 2]]
    solved = _grb(vertices[:, :2], swapped, centers)

    with pytest.raises(IncompatibleMeshError, match=r"cell 2 is .*\(2 cells differ\)"):
        verify_disv_grid(solved, vertices=vertices, connectivity=rings, centers=centers)


def test_a_north_south_mirror_is_refused() -> None:
    vertices, rings, centers = _stored()
    mirrored = vertices[:, :2].copy()
    mirrored[:, 1] = mirrored[:, 1].max() - mirrored[:, 1]
    solved = _grb(mirrored, rings, centers)

    with pytest.raises(IncompatibleMeshError, match="off along y"):
        verify_disv_grid(solved, vertices=vertices, connectivity=rings, centers=centers)


def test_a_centre_that_moved_is_refused() -> None:
    vertices, rings, centers = _stored()
    shifted = centers.copy()
    shifted[4, 1] += 0.5
    solved = _grb(vertices[:, :2], rings, shifted)

    with pytest.raises(IncompatibleMeshError, match="centre of cell 4"):
        verify_disv_grid(solved, vertices=vertices, connectivity=rings, centers=centers)


def test_centres_are_left_unchecked_when_the_store_holds_none() -> None:
    vertices, rings, centers = _stored()
    solved = _grb(vertices[:, :2], rings, centers + 5.0)

    check = verify_disv_grid(solved, vertices=vertices, connectivity=rings)

    assert check.max_center_shift_m is None


def test_the_counts_are_compared_first() -> None:
    vertices, rings, _ = _stored()
    with pytest.raises(IncompatibleMeshError, match="21 vertices"):
        verify_disv_grid(
            _grb(np.vstack([vertices[:, :2], [[0.0, 0.0]]]), rings),
            vertices=vertices,
            connectivity=rings,
        )
    with pytest.raises(IncompatibleMeshError, match="11 cells"):
        verify_disv_grid(_grb(vertices[:, :2], rings[:-1]), vertices=vertices, connectivity=rings)


def test_rings_of_mixed_sizes_are_padded_and_lose_their_closing_node() -> None:
    rings = np.array([[0, 1, 2, -1], [2, 3, 4, 5]], dtype=np.int32)

    np.testing.assert_array_equal(grb_rings(_grb(np.zeros((6, 2)), rings)), rings)


def test_a_grid_file_without_vertices_is_refused_not_guessed() -> None:
    structured = SimpleNamespace(verts=None, iavert=None, javert=None)

    with pytest.raises(MeshError, match="only DISV"):
        grb_rings(structured)


def _store_with_mesh(path: Path, *, with_mesh: bool = True) -> SimulationZarr:
    handle = SimulationZarr.create(path, n_cells=N_CELLS, n_layers=1)
    if with_mesh:
        vertices, rings = quad_mesh(NROW, NCOL)
        handle.write_mesh(
            vertices,
            rings,
            np.tile([[10.0], [0.0]], (1, N_CELLS)),
            structured_shape=(NROW, NCOL),
        )
    return handle


def test_a_store_without_geometry_warns_and_gets_no_vertex(tmp_path, caplog) -> None:
    store = _store_with_mesh(tmp_path / "run.zarr", with_mesh=False)
    vertices, rings, _ = _stored()
    try:
        with caplog.at_level(logging.WARNING):
            check = verify_grid_against_store(
                _grb(vertices[:, :2], rings), store.root, sim_id="old"
            )

        assert check is None
        assert any("stores no mesh geometry" in r.getMessage() for r in caplog.records)
        assert "vertices" not in store.root.get("mesh", {})
    finally:
        store.close()


class _Handle:
    """Hands out ``store`` to an extractor that closes what it opens."""

    def __init__(self, store: SimulationZarr) -> None:
        self._store = store

    def __getattr__(self, name: str):
        return getattr(self._store, name)

    def close(self) -> None:
        return None


def _mf6_extract_surface(monkeypatch, tmp_path: Path, store, grb) -> None:
    import flopy.mf6.utils

    from hydromodpy.solver.modflow6.extractors.flow import Modflow6OutputAdapter

    ground = np.linspace(5.0, 6.0, N_CELLS)
    grb.top1d = ground
    grb.bot1d = ground - 10.0
    grb.idomain = np.ones(N_CELLS, dtype=int)
    monkeypatch.setattr(flopy.mf6.utils, "MfGrdFile", lambda path: grb)
    (tmp_path / "m.disv.grb").write_bytes(b"")
    np.savez(tmp_path / f"m{GROUND_SIDECAR_SUFFIX}", ground=ground)
    Modflow6OutputAdapter()._write_surface_elevation(
        "sim",
        SimpleNamespace(open_zarr=lambda sim_id: _Handle(store)),
        tmp_path,
        "m",
        1,
        N_CELLS,
    )


def test_the_mf6_extractor_adds_the_vertical_part_and_leaves_the_vertices_alone(
    monkeypatch, tmp_path
) -> None:
    store = _store_with_mesh(tmp_path / "run.zarr")
    vertices, rings = quad_mesh(NROW, NCOL)
    before = store.root["mesh"]["vertices"][:].copy()
    try:
        _mf6_extract_surface(monkeypatch, tmp_path, store, _grb(vertices[:, :2], rings))

        mesh = store.root["mesh"]
        np.testing.assert_array_equal(mesh["vertices"][:], before)
        np.testing.assert_array_equal(mesh["face_node_connectivity"][:], rings)
        np.testing.assert_allclose(mesh["topography"][:], np.linspace(5.0, 6.0, N_CELLS))
        assert mesh["layer_thickness"].shape == (1, N_CELLS)
        assert mesh.attrs["grid_type"] == "disv"
        assert tuple(mesh.attrs["structured_shape"]) == (NROW, NCOL)
    finally:
        store.close()


def test_the_mf6_extractor_stops_when_the_solved_grid_is_another_mesh(
    monkeypatch, tmp_path, caplog
) -> None:
    store = _store_with_mesh(tmp_path / "run.zarr")
    vertices, rings = quad_mesh(NROW, NCOL)
    moved = vertices[:, :2].copy()
    moved[3, 0] += 0.01
    try:
        with (
            caplog.at_level(logging.WARNING),
            pytest.raises(IncompatibleMeshError, match="vertex 3"),
        ):
            _mf6_extract_surface(monkeypatch, tmp_path, store, _grb(moved, rings))

        assert "topography" not in store.root["mesh"]
    finally:
        store.close()


@pytest.fixture
def regular_store(tmp_path: Path):
    handle = _store_with_mesh(tmp_path / "run.zarr")
    yield handle
    handle.close()


def _dis_grid(nrow: int = NROW, ncol: int = NCOL, *, shift: float = 0.0) -> SimpleNamespace:
    xx, yy = np.meshgrid(np.arange(ncol + 1.0), np.arange(nrow + 1.0))
    xx = xx.copy()
    xx[1, 1] += shift
    return SimpleNamespace(xvertices=xx, yvertices=yy)


def test_the_nwt_grid_of_the_stored_mesh_passes(regular_store) -> None:
    shift = verify_dis_grid(
        _dis_grid(shift=1e-9), regular_store.root, nrow=NROW, ncol=NCOL, sim_id="s"
    )

    assert shift == pytest.approx(1e-9)


def test_the_nwt_grid_is_refused_on_a_shape_a_ring_or_a_vertex(regular_store) -> None:
    with pytest.raises(IncompatibleMeshError, match="4 x 3 cells"):
        verify_dis_grid(_dis_grid(4, 3), regular_store.root, nrow=4, ncol=3, sim_id="s")
    with pytest.raises(IncompatibleMeshError, match=r"vertex 6 .* from the stored mesh"):
        verify_dis_grid(_dis_grid(shift=0.01), regular_store.root, nrow=NROW, ncol=NCOL, sim_id="s")

    rings = regular_store.root["mesh"]["face_node_connectivity"]
    swapped = rings[:]
    swapped[[0, 1]] = swapped[[1, 0]]
    rings[:] = swapped
    with pytest.raises(IncompatibleMeshError, match="not those of a regular"):
        verify_dis_grid(_dis_grid(), regular_store.root, nrow=NROW, ncol=NCOL, sim_id="s")


def test_the_nwt_grid_of_a_store_without_geometry_warns(tmp_path, caplog) -> None:
    store = _store_with_mesh(tmp_path / "run.zarr", with_mesh=False)
    try:
        with caplog.at_level(logging.WARNING):
            assert (
                verify_dis_grid(_dis_grid(), store.root, nrow=NROW, ncol=NCOL, sim_id="s") is None
            )
        assert any("stores no mesh geometry" in r.getMessage() for r in caplog.records)
    finally:
        store.close()


def test_a_cell_count_that_is_not_the_stored_one_is_refused_after_a_run(regular_store) -> None:
    with pytest.raises(IncompatibleMeshError, match="13 cells"):
        regular_store.write_topography(np.zeros(13), n_cells=13)

    regular_store.write_topography(np.zeros(N_CELLS), n_cells=N_CELLS)


def _mf6_binary() -> Path | None:
    from hydromodpy.solver.modflow_common.binaries import locate_solver_binary, managed_bin_dir

    found = shutil.which("mf6")
    if found:
        return Path(found)
    return locate_solver_binary(managed_bin_dir(), "mf6")


def test_a_real_disv_grid_file_round_trips_through_the_check(tmp_path) -> None:
    flopy = pytest.importorskip("flopy")
    from flopy.mf6.utils import MfGrdFile

    exe = _mf6_binary()
    if exe is None:
        pytest.skip("mf6 is not installed")
    rng = np.random.default_rng(3)
    nx, ny, d = 6, 5, 75.0
    xs = 351234.56789123 + d * np.arange(nx + 1) + rng.uniform(-3, 3, nx + 1)
    ys = 6801234.98765432 - d * np.arange(ny + 1) + rng.uniform(-3, 3, ny + 1)
    gx, gy = np.meshgrid(xs, ys)
    vertices = np.column_stack([gx.ravel(), gy.ravel(), np.zeros(gx.size)])
    first = (np.arange(ny)[:, None] * (nx + 1) + np.arange(nx)[None, :]).ravel()
    rings = np.column_stack([first, first + 1, first + nx + 2, first + nx + 1]).astype(np.int32)
    centers = vertices[rings][:, :, :2].mean(axis=1) + rng.uniform(-1, 1, (nx * ny, 2))
    cell2d = [[i, *centers[i], 4, *rings[i]] for i in range(nx * ny)]
    sim = flopy.mf6.MFSimulation(sim_ws=str(tmp_path), exe_name=str(exe), verbosity_level=0)
    flopy.mf6.ModflowTdis(sim)
    flopy.mf6.ModflowIms(sim)
    gwf = flopy.mf6.ModflowGwf(sim, modelname="m")
    flopy.mf6.ModflowGwfdisv(
        gwf,
        nlay=1,
        ncpl=nx * ny,
        nvert=len(vertices),
        top=10.0,
        botm=[0.0],
        vertices=[[i, float(x), float(y)] for i, (x, y, _) in enumerate(vertices)],
        cell2d=cell2d,
    )
    flopy.mf6.ModflowGwfnpf(gwf)
    flopy.mf6.ModflowGwfic(gwf, strt=5.0)
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data=[[(0, 0), 5.0]])
    sim.write_simulation(silent=True)
    ok, _ = sim.run_simulation(silent=True)
    assert ok
    grd = MfGrdFile(str(tmp_path / "m.disv.grb"))

    check = verify_disv_grid(grd, vertices=vertices, connectivity=rings, centers=centers)

    assert 0.0 < check.max_vertex_shift_m <= 0.505e-2
    assert check.n_reversed_cells == 0
    moved = vertices.copy()
    moved[0, 0] += 0.01
    with pytest.raises(IncompatibleMeshError, match="vertex 0"):
        verify_disv_grid(grd, vertices=moved, connectivity=rings, centers=centers)


def _boussinesq_surface(store, tmp_path: Path, n_cells: int) -> None:
    from hydromodpy.solver.boussinesq.extractors.flow import BoussinesqOutputAdapter

    BoussinesqOutputAdapter()._write_surface_elevation(
        "sim",
        SimpleNamespace(open_zarr=lambda sim_id: _Handle(store)),
        tmp_path,
        n_cells,
        z_top_m=np.linspace(5.0, 6.0, n_cells),
        z_bottom_m=np.zeros(n_cells),
    )


def test_boussinesq_checks_its_cell_count_against_the_stored_mesh(regular_store, tmp_path) -> None:
    with pytest.raises(IncompatibleMeshError, match="13 cells"):
        _boussinesq_surface(regular_store, tmp_path, 13)

    _boussinesq_surface(regular_store, tmp_path, N_CELLS)

    mesh = regular_store.root["mesh"]
    np.testing.assert_allclose(mesh["topography"][:], np.linspace(5.0, 6.0, N_CELLS))
    assert mesh.attrs["n_cells"] == N_CELLS
