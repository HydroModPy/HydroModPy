"""Unit tests for :mod:`hydromodpy.workflow.internals.derived`.

Covers the registry API (register / get / list / ordered_names / apply),
the canonical default derivations (watertable_elevation, watertable_depth,
seepage_mask, fluxes_from_budget) against a tiny in-memory Zarr store, and
the DeriveStep wiring through a minimal stub context.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.results.zarr_store import SimulationZarr
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
):
    path = tmp_path / "sim.zarr"
    sz = SimulationZarr.create(path, n_cells=n_cells, n_layers=1)

    # surface_top
    mesh = sz.root["mesh"]
    mesh.create_array(
        "surface_top",
        data=np.full(n_cells, float(top_value), dtype="float64"),
        overwrite=True,
    )
    if cell_area is not None:
        mesh.create_array(
            "cell_area",
            data=np.asarray(cell_area, dtype="float64"),
            overwrite=True,
        )

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
        budget = sz.root["budget"]
        budget.create_array(
            "drn",
            shape=(n_timesteps, n_cells),
            chunks=(1, n_cells),
            dtype="float64",
            overwrite=True,
        )
        for t in range(n_timesteps):
            budget["drn"][t, :] = drn[t]

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


class _CtxStub:
    def __init__(self, store, sim_id: str = "stub") -> None:
        self.store = store
        self.sim_id = sim_id


def test_derive_step_runs_registry(tmp_path):
    sz = _make_zarr(
        tmp_path,
        head_values=np.array([[5.0, 11.0, 9.0, 12.0], [6.0, 7.0, 8.0, 9.0]]),
        cell_area=[10.0, 10.0, 10.0, 10.0],
        drn=np.array([[100.0, 0.0, -50.0, 20.0], [10.0, 20.0, 30.0, 40.0]]),
    )
    ctx = _CtxStub(_StoreStub(sz))
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


def test_derive_step_without_store_is_noop():
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
