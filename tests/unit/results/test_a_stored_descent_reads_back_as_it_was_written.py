"""D lives under ``fields.zarr/mesh/`` and ``run.descent`` reads it back.

Seven static arrays, never rounded, plus the build report on the receiver array
and, when the build kept one, the basin of D with its outlet.
The layout is additive: ``zarr_schema_version`` stays where it was, and a run
sealed before D was stored gets one rebuilt from its stored top, announced once.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core.descent import Descent, descent_from_stored_mesh
from hydromodpy.core.field_routing import accumulate_on_downhill_graph
from hydromodpy.results.run.contracts import Mesh
from hydromodpy.results.run.descent import RunDescent, load_descent, read_basin
from hydromodpy.results.zarr_store import SimulationZarr
from hydromodpy.results.zarr_store.constants import ZARR_SCHEMA_VERSION
from tests._helpers.ugrid_meshes import quad_mesh
from tests.unit.core._descent_meshes import grid_descent

NROW = NCOL = 4
N_CELLS = NROW * NCOL
TOP = np.array(
    [
        [9.0, 8.0, 7.0, 8.0],
        [8.0, 5.0, 4.0, 7.0],
        [7.0, 4.0, 1.0, 6.0],
        [6.0, 5.0, 4.0, 5.0],
    ]
)

PIT = 10


def _built_descent() -> Descent:
    """D as a build makes it, with a constant head in the pit: no rebuild from the top can."""
    base_level = np.zeros(N_CELLS, dtype=bool)
    base_level[PIT] = True
    return grid_descent(TOP, base_level=base_level)


def _attrs(descent: Descent) -> dict[str, object]:
    return {
        "adjacency": "shared_nodes",
        "epsilon": 1.0e-4,
        "n_raised": descent.n_raised,
        "max_raise_m": descent.max_raise_m,
        "n_lake_flooded": descent.n_lake_flooded,
        "max_lake_flood_m": descent.max_lake_flood_m,
        "n_pinned_raised": descent.n_pinned_raised,
        "max_pinned_raise_m": descent.max_pinned_raise_m,
    }


def _write(store: SimulationZarr, descent: Descent) -> None:
    store.write_descent(
        receiver=descent.receiver,
        surface=descent.surface,
        base_level=descent.base_level,
        constant_head=descent.constant_head,
        raised=descent.raised,
        channel=descent.channel,
        pinned=descent.pinned,
        attrs=_attrs(descent),
    )


def _write_mesh(store: SimulationZarr) -> tuple[np.ndarray, np.ndarray]:
    vertices, connectivity = quad_mesh(NROW, NCOL)
    store.write_mesh(vertices, connectivity, np.array([10.0, 0.0]), topography=TOP.ravel())
    return vertices, connectivity


@pytest.fixture
def store(tmp_path: Path):
    handle = SimulationZarr.create(tmp_path / "run.zarr", n_cells=N_CELLS, n_layers=1)
    yield handle
    handle.close()


def _run_over(store: SimulationZarr, vertices: np.ndarray, connectivity: np.ndarray):
    """A run whose catalog hands out ``store`` and whose mesh is the one written."""
    handle = SimpleNamespace(root=store.root, close=lambda: None)
    return SimpleNamespace(
        sim_id="sim-descent",
        _sim_id="sim-descent",
        _catalog=SimpleNamespace(open_zarr=lambda sim_id: handle),
        mesh=Mesh(
            vertices=vertices,
            face_node_connectivity=connectivity,
            z_interfaces=np.array([10.0, 0.0]),
            topography=TOP.ravel(),
        ),
    )


def test_the_seven_arrays_are_written_under_mesh_with_the_report_on_the_receiver(store) -> None:
    descent = _built_descent()
    _write_mesh(store)

    _write(store, descent)

    mesh = store.root["mesh"]
    expected = {
        "descent_receiver": np.int64,
        "descent_surface": np.float64,
        "descent_base_level": np.bool_,
        "descent_constant_head": np.bool_,
        "descent_raised": np.bool_,
        "descent_channel": np.bool_,
        "descent_pinned": np.bool_,
    }
    for name, dtype in expected.items():
        assert mesh[name].dtype == dtype, name
        assert mesh[name].shape == (N_CELLS,), name
    attrs = dict(mesh["descent_receiver"].attrs)
    assert attrs["adjacency"] == "shared_nodes"
    assert attrs["n_raised"] == descent.n_raised
    assert attrs["max_raise_m"] == pytest.approx(descent.max_raise_m)


def test_the_filled_surface_is_never_rounded_in_a_compact_store(store) -> None:
    descent = _built_descent()
    _write_mesh(store)

    _write(store, descent)

    np.testing.assert_array_equal(store.root["mesh"]["descent_surface"][:], descent.surface)


def test_storing_the_descent_moves_neither_the_schema_version_nor_the_mesh(store) -> None:
    vertices, _ = _write_mesh(store)
    before = dict(store.root.attrs)["zarr_schema_version"]

    _write(store, _built_descent())

    assert dict(store.root.attrs)["zarr_schema_version"] == before == ZARR_SCHEMA_VERSION
    np.testing.assert_array_equal(store.root["mesh"]["vertices"][:], vertices)
    np.testing.assert_array_equal(store.root["mesh"]["topography"][:], TOP.ravel())


def test_a_descent_whose_arrays_disagree_on_the_cell_count_is_refused(store) -> None:
    descent = _built_descent()
    _write_mesh(store)

    with pytest.raises(ValueError, match="share one size"):
        store.write_descent(
            receiver=descent.receiver[:-1],
            surface=descent.surface,
            base_level=descent.base_level,
            constant_head=descent.constant_head,
            raised=descent.raised,
            channel=descent.channel,
            pinned=descent.pinned,
            attrs={},
        )


def test_a_stored_descent_reads_back_and_routes_like_the_one_written(store) -> None:
    descent = _built_descent()
    vertices, connectivity = _write_mesh(store)
    _write(store, descent)

    view = load_descent(_run_over(store, vertices, connectivity))

    assert not view.rebuilt
    assert view.adjacency == "shared_nodes"
    assert view.diagonal_neighbors
    assert view.epsilon == pytest.approx(1.0e-4)
    assert view.report["n_raised"] == descent.n_raised
    np.testing.assert_array_equal(view.receiver, descent.receiver)
    np.testing.assert_array_equal(view.surface, descent.surface)
    np.testing.assert_array_equal(view.base_level, descent.base_level)
    np.testing.assert_array_equal(view.constant_head, descent.constant_head)
    np.testing.assert_array_equal(view.raised, descent.raised)
    assert view.constant_head[PIT] and view.receiver[PIT] == -1
    flux = np.arange(1.0, N_CELLS + 1.0)
    np.testing.assert_array_equal(
        accumulate_on_downhill_graph(view.graph, flux),
        accumulate_on_downhill_graph(descent.metric.graph, flux),
    )


def test_the_arrays_of_the_view_are_read_only(store) -> None:
    vertices, connectivity = _write_mesh(store)
    _write(store, _built_descent())

    view = load_descent(_run_over(store, vertices, connectivity))

    for name in (
        "receiver",
        "surface",
        "base_level",
        "constant_head",
        "raised",
        "channel",
        "pinned",
    ):
        assert not getattr(view, name).flags.writeable, name


def test_a_run_sealed_before_the_descent_rebuilds_it_from_its_top(store) -> None:
    vertices, connectivity = _write_mesh(store)

    view = load_descent(_run_over(store, vertices, connectivity))

    rebuilt = descent_from_stored_mesh(TOP.ravel(), connectivity, vertices)
    assert view.rebuilt
    assert not view.channel.any()
    assert not view.pinned.any()
    np.testing.assert_array_equal(view.receiver, rebuilt.receiver)
    np.testing.assert_array_equal(view.surface, rebuilt.surface)


def test_an_old_run_says_once_that_it_rebuilt_its_descent(store, caplog) -> None:
    vertices, connectivity = _write_mesh(store)
    holder = RunDescent.of_run(_run_over(store, vertices, connectivity))

    with caplog.at_level(logging.INFO):
        for name in ("receiver", "surface", "graph"):
            assert getattr(holder, name) is not None

    lines = [r for r in caplog.records if "predates the stored descent" in r.getMessage()]
    assert len(lines) == 1
    assert lines[0].levelno == logging.INFO


def test_a_stored_descent_is_loaded_lazily_and_once(store) -> None:
    descent = _built_descent()
    vertices, connectivity = _write_mesh(store)
    _write(store, descent)
    opened: list[str] = []
    run = _run_over(store, vertices, connectivity)
    handle = run._catalog.open_zarr("x")
    run._catalog.open_zarr = lambda sim_id: opened.append(sim_id) or handle
    holder = RunDescent.of_run(run)
    assert opened == []

    for name in ("receiver", "graph"):
        assert getattr(holder, name) is not None

    assert opened == ["sim-descent"]


def test_an_attribute_the_view_does_not_have_is_an_attribute_error() -> None:
    holder = RunDescent(lambda: pytest.fail("loading must not happen for an unknown name"))

    with pytest.raises(AttributeError):
        getattr(holder, "nothing_of_the_kind")  # noqa: B009


BASIN_CELLS = [5, 6, 9, 10]
BASIN_OUTLET = PIT


def _basin_mask() -> np.ndarray:
    mask = np.zeros(N_CELLS, dtype=bool)
    mask[BASIN_CELLS] = True
    return mask


def _basin_attrs(**changes: object) -> dict[str, object]:
    attrs: dict[str, object] = {
        "descent_outlet": BASIN_OUTLET,
        "basin_rule": "within_polygon",
        "basin_area_m2": 4.0,
        "basin_seeded_at_outlet": True,
        "basin_version": 1,
    }
    return {**attrs, **changes}


def _write_with_basin(store: SimulationZarr, mask: np.ndarray, attrs: dict[str, object]) -> None:
    descent = _built_descent()
    store.write_descent(
        receiver=descent.receiver,
        surface=descent.surface,
        base_level=descent.base_level,
        constant_head=descent.constant_head,
        raised=descent.raised,
        channel=descent.channel,
        pinned=descent.pinned,
        attrs=_attrs(descent),
        basin=mask,
        basin_attrs=attrs,
    )


def test_the_basin_is_a_bool_array_per_face_with_its_outlet_on_it(store) -> None:
    _write_mesh(store)

    _write_with_basin(store, _basin_mask(), _basin_attrs())

    array = store.root["mesh"]["descent_basin"]
    assert array.dtype == np.bool_
    assert array.shape == (N_CELLS,)
    assert np.flatnonzero(array[:]).tolist() == BASIN_CELLS
    attrs = dict(array.attrs)
    assert attrs["descent_outlet"] == BASIN_OUTLET
    assert attrs["basin_rule"] == "within_polygon"
    assert attrs["basin_area_m2"] == pytest.approx(4.0)
    assert attrs["basin_seeded_at_outlet"] is True
    assert attrs["basin_version"] == 1


def test_a_stored_basin_reads_back_read_only_with_its_attributes(store) -> None:
    vertices, connectivity = _write_mesh(store)
    _write_with_basin(store, _basin_mask(), _basin_attrs())

    view = load_descent(_run_over(store, vertices, connectivity))

    assert not view.rebuilt
    np.testing.assert_array_equal(view.basin, _basin_mask())
    assert not view.basin.flags.writeable
    assert view.basin_attrs == _basin_attrs()


def test_the_basin_is_read_alone_without_loading_or_rebuilding_d(store, monkeypatch) -> None:
    vertices, connectivity = _write_mesh(store)
    _write_with_basin(store, _basin_mask(), _basin_attrs())
    from hydromodpy.results.run import descent as module

    def refuse(*args, **kwargs):
        raise AssertionError("D must be neither loaded nor rebuilt to read the basin")

    for name in ("load_descent", "_rebuild", "_read_stored"):
        monkeypatch.setattr(module, name, refuse)

    mask, attrs = read_basin(_run_over(store, vertices, connectivity))

    np.testing.assert_array_equal(mask, _basin_mask())
    assert not mask.flags.writeable
    assert attrs["descent_outlet"] == BASIN_OUTLET


def test_the_holder_reads_the_basin_alone_and_a_run_without_one_is_not_rebuilt(
    store, monkeypatch
) -> None:
    vertices, connectivity = _write_mesh(store)
    run = _run_over(store, vertices, connectivity)
    from hydromodpy.results.run import descent as module

    def refuse(*args, **kwargs):
        raise AssertionError("D must be neither loaded nor rebuilt to read the basin")

    for name in ("load_descent", "_rebuild", "_read_stored"):
        monkeypatch.setattr(module, name, refuse)
    holder = RunDescent.of_run(run)

    assert holder.stored_basin() is None

    _write_with_basin(store, _basin_mask(), _basin_attrs())
    holder = RunDescent.of_run(run)
    mask, attrs = holder.stored_basin()
    np.testing.assert_array_equal(mask, _basin_mask())
    assert attrs["descent_outlet"] == BASIN_OUTLET


def test_a_descent_stored_before_the_basin_reads_back_without_one(store) -> None:
    vertices, connectivity = _write_mesh(store)
    _write(store, _built_descent())
    run = _run_over(store, vertices, connectivity)

    view = load_descent(run)

    assert not view.rebuilt
    assert view.basin is None
    assert view.basin_attrs == {}
    assert read_basin(run) is None


def test_a_rebuilt_descent_has_no_basin(store) -> None:
    vertices, connectivity = _write_mesh(store)

    view = load_descent(_run_over(store, vertices, connectivity))

    assert view.rebuilt
    assert view.basin is None


@pytest.mark.parametrize(
    ("mask", "attrs", "message"),
    [
        (_basin_mask()[:-1], _basin_attrs(), "one value per cell"),
        (_basin_mask(), {}, "descent_outlet"),
        (_basin_mask(), _basin_attrs(descent_outlet=0), "not a cell of the basin"),
        (_basin_mask(), _basin_attrs(descent_outlet=N_CELLS), "not a cell of the basin"),
    ],
    ids=["wrong size", "no outlet", "outlet off the basin", "outlet off the mesh"],
)
def test_a_basin_that_does_not_fit_d_is_refused(store, mask, attrs, message) -> None:
    _write_mesh(store)

    with pytest.raises(ValueError, match=message):
        _write_with_basin(store, mask, attrs)

    assert "descent_basin" not in store.root["mesh"]


def test_attributes_without_a_basin_are_refused(store) -> None:
    descent = _built_descent()

    with pytest.raises(ValueError, match="without a basin"):
        store.write_descent(
            receiver=descent.receiver,
            surface=descent.surface,
            base_level=descent.base_level,
            constant_head=descent.constant_head,
            raised=descent.raised,
            channel=descent.channel,
            pinned=descent.pinned,
            attrs={},
            basin_attrs=_basin_attrs(),
        )


def test_storing_the_basin_moves_neither_the_schema_version_nor_the_other_arrays(store) -> None:
    _write_mesh(store)
    before = dict(store.root.attrs)["zarr_schema_version"]

    _write_with_basin(store, _basin_mask(), _basin_attrs())

    assert dict(store.root.attrs)["zarr_schema_version"] == before == ZARR_SCHEMA_VERSION
    np.testing.assert_array_equal(
        store.root["mesh"]["descent_receiver"][:], _built_descent().receiver
    )
