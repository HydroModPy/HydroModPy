"""Unit tests for :mod:`hydromodpy.workflow.internals.derived`.

Covers the registry API (register / get / list / ordered_names / apply),
the canonical default derivations (watertable_elevation, watertable_depth,
seepage_mask, fluxes_from_budget) against a tiny in-memory Zarr store, and
the DeriveStep wiring through a minimal stub context.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.results.zarr_store import SimulationZarr
from hydromodpy.simulation.planning.results_config import ResultsConfig
from hydromodpy.solver.base.solver_config import SolverConfig
from hydromodpy.workflow.internals.derived import (
    DerivedComputation,
    DerivedRegistry,
    DerivedResult,
    registry,
)
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.steps.derive import DeriveStep

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_zarr(
    tmp_path,
    *,
    n_timesteps=2,
    n_cells=4,
    top_value=10.0,
    head_values=None,
    cell_area=None,
    drn=None,
    surface_excess=None,
    seepage_rate=None,
):
    path = tmp_path / "sim.zarr"
    sz = SimulationZarr.create(path, n_cells=n_cells, n_layers=1)

    # topography
    mesh = sz.root["mesh"]
    mesh.create_array(
        "topography",
        data=np.full(n_cells, float(top_value), dtype="float64"),
        overwrite=True,
    )
    if cell_area is not None:
        # The geometry, not an area array: nothing in the package has ever
        # written mesh/cell_area, so a fixture that wrote one made the
        # derivation look alive while it skipped on every real run. One row of
        # unit-height rectangles whose width is the area gives back `cell_area`
        # exactly, for any area vector.
        widths = np.asarray(cell_area, dtype="float64")
        x = np.concatenate([[0.0], np.cumsum(widths)])
        n_x = x.size
        vertices = np.array(
            [[float(xi), 0.0, 0.0] for xi in x] + [[float(xi), 1.0, 0.0] for xi in x],
            dtype="float64",
        )
        connectivity = np.array(
            [[i, i + 1, n_x + i + 1, n_x + i] for i in range(n_cells)], dtype="int32"
        )
        mesh.create_array("vertices", data=vertices, overwrite=True)
        mesh.create_array("face_node_connectivity", data=connectivity, overwrite=True)

    # head
    if head_values is None:
        head_values = np.tile(np.array([5.0, 11.0, 9.0, 12.0]), (n_timesteps, 1))
    for t in range(n_timesteps):
        sz.write_field(
            "head",
            t,
            np.asarray(head_values[t], dtype="float64"),
            n_timesteps=n_timesteps if t == 0 else None,
        )

    # budget/drn
    if drn is not None:
        budget = sz.root.require_group("budget")
        budget.create_array(
            "drain",
            shape=(n_timesteps, n_cells),
            chunks=(1, n_cells),
            dtype="float64",
            overwrite=True,
        )
        for t in range(n_timesteps):
            budget["drain"][t, :] = drn[t]

    if surface_excess is not None:
        budget = sz.root.require_group("budget")
        budget.create_array(
            "surface_excess",
            shape=(n_timesteps, n_cells),
            chunks=(1, n_cells),
            dtype="float64",
            overwrite=True,
        )
        for t in range(n_timesteps):
            budget["surface_excess"][t, :] = surface_excess[t]

    if seepage_rate is not None:
        derived = sz.root.require_group("derived")
        derived.create_array(
            "seepage_rate",
            shape=(n_timesteps, n_cells),
            chunks=(1, n_cells),
            dtype="float64",
            overwrite=True,
        )
        for t in range(n_timesteps):
            derived["seepage_rate"][t, :] = seepage_rate[t]

    return sz


# ---------------------------------------------------------------------------
# Registry API
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Fake:
    name: str
    required_inputs: tuple[str, ...] = ()
    required_derived: tuple[str, ...] = ()
    description: str = ""

    def compute(self, sim_zarr, **ctx):
        return DerivedResult(name=self.name, status="computed")


def test_default_registry_has_canonical_entries():
    assert set(registry.list()) == {
        "watertable_elevation",
        "watertable_depth",
        "seepage_mask",
        "fluxes_from_budget",
    }
    # Protocol compliance
    for name in registry.list():
        assert isinstance(registry.get(name), DerivedComputation)


def test_registry_register_duplicate_raises():
    reg = DerivedRegistry()
    reg.register(_Fake("a"))
    with pytest.raises(ConfigError):
        reg.register(_Fake("a"))
    reg.register(_Fake("a"), overwrite=True)  # allowed


def test_registry_topological_order():
    reg = DerivedRegistry()
    reg.register(_Fake("c", required_derived=("b",)))
    reg.register(_Fake("b", required_derived=("a",)))
    reg.register(_Fake("a"))
    order = reg.ordered_names()
    assert order.index("a") < order.index("b") < order.index("c")


def test_registry_cycle_raises():
    reg = DerivedRegistry()
    reg.register(_Fake("a", required_derived=("b",)))
    reg.register(_Fake("b", required_derived=("a",)))
    with pytest.raises(ConfigError, match="Cycle"):
        reg.ordered_names()


def test_registry_apply_unknown_name_raises(tmp_path):
    reg = DerivedRegistry()
    reg.register(_Fake("a"))
    sz = _make_zarr(tmp_path)
    with pytest.raises(KeyError):
        reg.apply(sz, names=["missing"])


def test_registry_skips_missing_inputs(tmp_path):
    reg = DerivedRegistry()
    reg.register(_Fake("needs_foo", required_inputs=("foo",)))
    sz = _make_zarr(tmp_path)
    results = reg.apply(sz)
    assert len(results) == 1
    assert results[0].status == "skipped"
    assert "foo" in results[0].reason


# ---------------------------------------------------------------------------
# Canonical derivations against a real SimulationZarr
# ---------------------------------------------------------------------------


def test_watertable_elevation_writes_uppermost_saturated_head(tmp_path):
    sz = _make_zarr(
        tmp_path,
        head_values=np.array([[5.0, 11.0, 9.0, 12.0], [6.0, 7.0, 8.0, 9.0]]),
    )
    results = registry.apply(sz, names=["watertable_elevation"])
    assert [r.status for r in results] == ["computed"]
    wt = np.asarray(sz.root["derived"]["watertable_elevation"][:])
    # Head returned as-is; seepage above the surface is flagged separately.
    np.testing.assert_array_equal(wt[0], [5.0, 11.0, 9.0, 12.0])
    np.testing.assert_array_equal(wt[1], [6.0, 7.0, 8.0, 9.0])


def test_watertable_depth_requires_elevation(tmp_path):
    sz = _make_zarr(tmp_path)
    # Without computing elevation first, depth must be skipped.
    results = registry.apply(sz, names=["watertable_depth"])
    assert results[0].status == "skipped"


def test_watertable_depth_after_elevation(tmp_path):
    sz = _make_zarr(
        tmp_path,
        head_values=np.array([[5.0, 11.0, 9.0, 12.0], [6.0, 7.0, 8.0, 9.0]]),
    )
    # Apply in registered topological order: elevation then depth.
    registry.apply(sz, names=["watertable_elevation", "watertable_depth"])
    depth = np.asarray(sz.root["derived"]["watertable_depth"][:])
    assert (depth >= 0).all()
    np.testing.assert_array_equal(depth[0], [5.0, 0.0, 1.0, 0.0])
    np.testing.assert_array_equal(depth[1], [4.0, 3.0, 2.0, 1.0])


def test_seepage_mask_flags_overflowing_cells(tmp_path):
    sz = _make_zarr(
        tmp_path,
        head_values=np.array([[5.0, 10.0, 11.0, 9.0], [9.9, 10.0, 10.5, 10.0]]),
    )
    registry.apply(
        sz,
        names=["watertable_elevation", "seepage_mask"],
    )
    mask = np.asarray(sz.root["derived"]["seepage_mask"][:])
    assert set(np.unique(mask)).issubset({0.0, 1.0})
    # Expect 1 where wt_elev >= top (10.0), 0 otherwise.
    np.testing.assert_array_equal(mask[0], [0.0, 1.0, 1.0, 0.0])
    np.testing.assert_array_equal(mask[1], [0.0, 1.0, 1.0, 1.0])


def test_seepage_mask_prefers_solver_surface_excess_rate(tmp_path):
    sz = _make_zarr(
        tmp_path,
        head_values=np.array([[11.0, 11.0, 11.0, 11.0], [11.0, 11.0, 11.0, 11.0]]),
        seepage_rate=np.array([[0.0, 1.0e-8, 0.0, 0.0], [0.0, 0.0, 2.0e-8, 0.0]]),
    )
    registry.apply(
        sz,
        names=["watertable_elevation", "seepage_mask"],
    )

    mask = np.asarray(sz.root["derived"]["seepage_mask"][:])

    np.testing.assert_array_equal(mask[0], [0.0, 1.0, 0.0, 0.0])
    np.testing.assert_array_equal(mask[1], [0.0, 0.0, 1.0, 0.0])


def test_seepage_mask_prefers_solver_surface_excess_budget(tmp_path):
    sz = _make_zarr(
        tmp_path,
        head_values=np.array([[11.0, 11.0, 11.0, 11.0], [11.0, 11.0, 11.0, 11.0]]),
        surface_excess=np.array([[0.0, 0.0, 1.0e-5, 0.0], [0.0, 3.0e-5, 0.0, 0.0]]),
    )
    registry.apply(
        sz,
        names=["watertable_elevation", "seepage_mask"],
    )

    mask = np.asarray(sz.root["derived"]["seepage_mask"][:])

    np.testing.assert_array_equal(mask[0], [0.0, 0.0, 1.0, 0.0])
    np.testing.assert_array_equal(mask[1], [0.0, 1.0, 0.0, 0.0])


def test_fluxes_from_budget_divides_by_cell_area(tmp_path):
    sz = _make_zarr(
        tmp_path,
        cell_area=[10.0, 10.0, 10.0, 10.0],
        drn=np.array([[100.0, 0.0, -50.0, 20.0], [10.0, 20.0, 30.0, 40.0]]),
    )
    results = registry.apply(sz, names=["fluxes_from_budget"])
    assert [r.status for r in results] == ["computed"]
    flux = np.asarray(sz.root["derived"]["fluxes_from_budget"][:])
    np.testing.assert_array_almost_equal(flux[0], [10.0, 0.0, -5.0, 2.0])
    np.testing.assert_array_almost_equal(flux[1], [1.0, 2.0, 3.0, 4.0])


def test_fluxes_from_budget_skipped_without_budget(tmp_path):
    sz = _make_zarr(tmp_path, cell_area=[10.0, 10.0, 10.0, 10.0])
    results = registry.apply(sz, names=["fluxes_from_budget"])
    assert results[0].status == "skipped"
    assert "budget" in results[0].reason.lower()


def test_fluxes_from_budget_skipped_without_cell_area(tmp_path):
    sz = _make_zarr(
        tmp_path,
        drn=np.array([[100.0, 0.0, -50.0, 20.0], [10.0, 20.0, 30.0, 40.0]]),
    )
    results = registry.apply(sz, names=["fluxes_from_budget"])
    assert results[0].status == "skipped"


# ---------------------------------------------------------------------------
# DeriveStep wiring
# ---------------------------------------------------------------------------


class _StoreStub:
    def __init__(self, sz: SimulationZarr) -> None:
        self._sz = sz

    def open_zarr(self, sim_id):
        return self._sz


@pytest.fixture(autouse=True)
def _catalog_scope_yields_the_stub(monkeypatch):
    """The step opens the index itself; hand it the stub the context holds."""
    from contextlib import contextmanager

    import hydromodpy.workflow.steps.derive as derive_module

    @contextmanager
    def _fake_scope(ctx):
        yield ctx.store

    monkeypatch.setattr(derive_module, "run_catalog", _fake_scope)


class _CtxStub:
    def __init__(self, store, sim_id: str = "stub") -> None:

        from hydromodpy.core.state.execution import ExecutionRegistry

        self.store = store
        self.sim_id = sim_id
        self.cfg = SimpleNamespace(
            simulation=SimpleNamespace(
                results=ResultsConfig.model_validate(
                    {"persistence": {"save_catalog": store is not None}}
                )
            ),
            solver=SolverConfig(),
        )
        self.setup = SimpleNamespace(workspace=None if store is None else object())
        # Use the real ExecutionRegistry so the stub honours the same contract as
        # WorkflowContext.execution (notably models_by_run_id, which DeriveStep
        # clears); a bare SimpleNamespace was missing that attribute. The run is
        # catalogued: the step opens the index for its own span and the stub
        # hands it this store.
        self.execution = ExecutionRegistry(simulation_plan=None, lightweight=False)


def test_derive_step_runs_registry(tmp_path):
    sz = _make_zarr(
        tmp_path,
        head_values=np.array([[5.0, 11.0, 9.0, 12.0], [6.0, 7.0, 8.0, 9.0]]),
        cell_area=[10.0, 10.0, 10.0, 10.0],
        drn=np.array([[100.0, 0.0, -50.0, 20.0], [10.0, 20.0, 30.0, 40.0]]),
    )
    ctx = _CtxStub(_StoreStub(sz))
    # Registry persistence is opt-in: enable every field this test asserts.
    ctx.effective_results_config = ResultsConfig.model_validate(
        {
            "derived": {
                "watertable_elevation": True,
                "watertable_depth": True,
                "seepage_areas": True,
            },
            "budget": {"spatial_fields": True},
        }
    )
    state = PipelineState(run_id="r", data={"ctx": ctx})
    out = DeriveStep().run(state)
    assert out.step_name == "derive"
    # All four derivations must have produced outputs.
    derived = sz.root["derived"]
    for name in (
        "watertable_elevation",
        "watertable_depth",
        "seepage_mask",
        "fluxes_from_budget",
    ):
        assert name in derived, f"{name} not written"


def test_derive_step_without_ctx_raises():
    state = PipelineState(run_id="r", data={})
    with pytest.raises(ConfigError, match="'ctx'"):
        DeriveStep().run(state)


def test_derive_step_without_an_index_is_noop():
    ctx = _CtxStub(store=None)
    state = PipelineState(run_id="r", data={"ctx": ctx})
    out = DeriveStep().run(state)
    assert out.step_name == "derive"


def test_derive_step_without_head_is_noop(tmp_path):
    path = tmp_path / "sim.zarr"
    sz = SimulationZarr.create(path, n_cells=2, n_layers=1)
    ctx = _CtxStub(_StoreStub(sz))
    state = PipelineState(run_id="r", data={"ctx": ctx})
    out = DeriveStep().run(state)
    assert out.step_name == "derive"
    # No head → derived group must remain empty of our canonical names.
    derived = sz.root.get("derived")
    if derived is not None:
        for name in (
            "watertable_elevation",
            "watertable_depth",
            "seepage_mask",
            "fluxes_from_budget",
        ):
            assert name not in derived


def test_registry_accessible_via_public_api():
    from hydromodpy.workflow.internals import derived as derived_pkg

    assert "watertable_elevation" in derived_pkg.registry.list()


def test_fluxes_from_budget_needs_the_mesh_geometry_and_says_so(tmp_path):
    # No vertices, no connectivity: the areas cannot be rebuilt and the
    # derivation has to skip with a sentence rather than divide by nothing.
    sz = _make_zarr(tmp_path, drn=np.array([[100.0, 0.0, -50.0, 20.0], [10.0, 20.0, 30.0, 40.0]]))
    results = registry.apply(sz, names=["fluxes_from_budget"])

    assert results[0].status == "skipped"
    assert "cell area" in str(results[0].reason).lower()


def test_the_areas_come_from_the_geometry_and_not_from_a_stored_array(tmp_path):
    # Uneven cells, so an implementation reading a constant or a mean is caught.
    sz = _make_zarr(
        tmp_path,
        cell_area=[10.0, 20.0, 40.0, 80.0],
        drn=np.array([[100.0, 100.0, 100.0, 100.0], [10.0, 20.0, 30.0, 40.0]]),
    )
    results = registry.apply(sz, names=["fluxes_from_budget"])

    assert [r.status for r in results] == ["computed"]
    flux = np.asarray(sz.root["derived"]["fluxes_from_budget"][:])
    np.testing.assert_array_almost_equal(flux[0], [10.0, 5.0, 2.5, 1.25])
