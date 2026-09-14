"""Cyclic spin-up: convergence readers, delta metric, and the loop control flow.

The loop test drives ``run_spinup`` against a stub Project whose ``simulate``
hands back pre-written synthetic Zarr stores, so the real driver logic (restart
injection, delta computation, convergence stop) runs without a solver.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.physics.flow.initial_conditions import FlowInitialConditions
from hydromodpy.project.spinup import cycle_delta, run_spinup
from hydromodpy.simulation.spinup_config import SpinupConfig
from hydromodpy.solver.modflow6.builders.initial_conditions import read_final_head


def _write_cycle_zarr(path: Path, head: list, stages: dict[str, float] | None = None) -> str:
    """Write a synthetic run Zarr with a head field and optional lake stages."""
    import zarr

    root = zarr.open(str(path), mode="w")
    arr = np.asarray(head, dtype=float)
    root["head"] = arr.reshape(1, *arr.shape)  # (ntime=1, nlay, ncpl)
    if stages:
        grp = root.require_group("lake_state_final")
        lake_ids = list(stages)
        grp["stage"] = np.array([stages[k] for k in lake_ids], dtype="float64")
        grp.attrs["lake_ids"] = lake_ids
    return str(path)


def test_read_final_head_returns_last_step_with_nan_inactive(tmp_path: Path) -> None:
    path = _write_cycle_zarr(tmp_path / "c.zarr", [[1.0, 2.0, 1e30]])
    head = read_final_head(path)
    assert head.shape == (1, 3)
    assert np.array_equal(head[0, :2], [1.0, 2.0])
    assert np.isnan(head[0, 2])  # large sentinel -> NaN, ignored by the delta


def test_cycle_delta_reports_linf_head_and_stage(tmp_path: Path) -> None:
    prev = _write_cycle_zarr(tmp_path / "p.zarr", [[10.0, 10.0, 10.0]], {"lac0": 86.0})
    curr = _write_cycle_zarr(tmp_path / "q.zarr", [[10.2, 10.0, 10.0]], {"lac0": 86.05})
    d_head, d_stage = cycle_delta(prev, curr)
    assert d_head == pytest.approx(0.2)
    assert d_stage == pytest.approx(0.05)


def test_cycle_delta_zero_when_identical(tmp_path: Path) -> None:
    a = _write_cycle_zarr(tmp_path / "a.zarr", [[5.0, 6.0]], {"lac0": 80.0})
    b = _write_cycle_zarr(tmp_path / "b.zarr", [[5.0, 6.0]], {"lac0": 80.0})
    assert cycle_delta(a, b) == (0.0, 0.0)


def test_cycle_delta_rejects_shape_change(tmp_path: Path) -> None:
    a = _write_cycle_zarr(tmp_path / "a.zarr", [[5.0, 6.0, 7.0]])
    b = _write_cycle_zarr(tmp_path / "b.zarr", [[5.0, 6.0]])
    with pytest.raises(ValueError, match="mesh is not stable"):
        cycle_delta(a, b)


class _StubProject:
    """Minimal Project stand-in: simulate() returns a pre-written cycle Zarr."""

    def __init__(self, cfg, cycle_zarrs: list[str]) -> None:
        self.config = cfg
        self._cycle_zarrs = cycle_zarrs
        self._i = 0
        self._by_sid: dict[str, str] = {}
        self.tags: list[tuple[str, str]] = []
        self._catalog = SimpleNamespace(
            store=SimpleNamespace(
                fields_path_for=lambda sid: self._by_sid[sid],
                add_tag=lambda sid, tag: self.tags.append((str(sid), tag)),
            )
        )
        self.simulated_restart_from: list[str | None] = []
        self.simulated_ic_type: list[str] = []

    def prepare(self):
        return self

    def simulate(self, *, name: str):
        # Record the restart_from and IC type the driver set for this cycle.
        self.simulated_restart_from.append(self.config.flow.restart_from)
        self.simulated_ic_type.append(self.config.flow.ic.h.type)
        path = self._cycle_zarrs[self._i]
        self._i += 1
        sid = f"sid::{name}"
        self._by_sid[sid] = path
        return SimpleNamespace(sim_id=sid)


def _stub_config() -> SimpleNamespace:
    return SimpleNamespace(
        flow=FlowConfig(),  # real flow config so ic.h.type / restart_from behave
        simulation=SimpleNamespace(time=SimpleNamespace(start_datetime=None, end_datetime=None)),
        mesh_catchment=None,
        spinup=None,
    )


def test_run_spinup_converges_and_stops_early(tmp_path: Path) -> None:
    # cycle 0 -> 1 is a big jump; 1 -> 2 is below tol, so the loop stops at cycle 2.
    zarrs = [
        _write_cycle_zarr(tmp_path / "c0.zarr", [[0.0, 0.0, 0.0]], {"lac0": 80.0}),
        _write_cycle_zarr(tmp_path / "c1.zarr", [[5.0, 5.0, 5.0]], {"lac0": 86.0}),
        _write_cycle_zarr(tmp_path / "c2.zarr", [[5.001, 5.0, 5.0]], {"lac0": 86.002}),
        _write_cycle_zarr(tmp_path / "c3.zarr", [[9.0, 9.0, 9.0]], {"lac0": 99.0}),
    ]
    project = _StubProject(_stub_config(), zarrs)
    result = run_spinup(project, spinup=SpinupConfig(max_cycles=5, tol_head=0.01, tol_stage=0.01))

    assert result.converged is True
    assert result.n_cycles == 3  # stopped after cycle 2, never ran cycle 3
    assert result.restart_from == zarrs[2]
    # Cycle 0 ran with no restart; cycles >= 1 restarted from the prior cycle Zarr.
    assert project.simulated_restart_from == [None, zarrs[0], zarrs[1]]


def test_run_spinup_stops_at_max_cycles_without_converging(tmp_path: Path) -> None:
    # Each cycle keeps moving by more than tol, so it never converges.
    zarrs = [
        _write_cycle_zarr(tmp_path / f"c{i}.zarr", [[float(i), 0.0]], {"lac0": 80.0 + i})
        for i in range(3)
    ]
    project = _StubProject(_stub_config(), zarrs)
    result = run_spinup(project, spinup=SpinupConfig(max_cycles=3, tol_head=0.01, tol_stage=0.01))

    assert result.converged is False
    assert result.n_cycles == 3
    assert result.restart_from == zarrs[2]


def test_run_spinup_switches_steady_ic_to_top_on_restart(tmp_path: Path) -> None:
    """Cycles >= 1 flip a steady_state IC to top so the steady pre-solve cannot
    clobber the restarted heads; cycle 0 keeps the original steady IC."""
    zarrs = [
        _write_cycle_zarr(tmp_path / "c0.zarr", [[0.0, 0.0]], {"lac0": 80.0}),
        _write_cycle_zarr(tmp_path / "c1.zarr", [[5.0, 5.0]], {"lac0": 86.0}),
        _write_cycle_zarr(tmp_path / "c2.zarr", [[5.0, 5.0]], {"lac0": 86.0}),
    ]
    cfg = _stub_config()
    cfg.flow.ic = FlowInitialConditions.model_validate({"type": "steady_state"})
    project = _StubProject(cfg, zarrs)

    run_spinup(project, spinup=SpinupConfig(max_cycles=3, tol_head=0.01, tol_stage=0.01))

    # Cycle 0 ran with the original steady IC; every restarted cycle used top.
    assert project.simulated_ic_type[0] == "steady_state"
    assert project.simulated_ic_type[1:] == ["top", "top"]
    # And each restarted cycle carried the prior cycle's Zarr as restart_from.
    assert project.simulated_restart_from == [None, zarrs[0], zarrs[1]]


def test_run_spinup_tags_intermediate_and_converged(tmp_path: Path) -> None:
    """Every cycle is tagged; the final one is the reusable converged antecedent."""
    zarrs = [
        _write_cycle_zarr(tmp_path / "c0.zarr", [[0.0, 0.0]], {"lac0": 80.0}),
        _write_cycle_zarr(tmp_path / "c1.zarr", [[5.0, 5.0]], {"lac0": 86.0}),
        _write_cycle_zarr(tmp_path / "c2.zarr", [[5.0, 5.0]], {"lac0": 86.0}),
    ]
    project = _StubProject(_stub_config(), zarrs)
    result = run_spinup(project, spinup=SpinupConfig(max_cycles=5, tol_head=0.01, tol_stage=0.01))

    tag_by_sid = dict(project.tags)
    assert tag_by_sid[result.cycles[-1].sim_id] == "spinup-converged"
    assert all(tag_by_sid[c.sim_id] == "spinup-intermediate" for c in result.cycles[:-1])
