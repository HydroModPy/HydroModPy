"""Cyclic spin-up: convergence readers, delta metric, and the loop control flow.

The loop test drives ``run_spinup`` against a stub Project whose ``simulate``
hands back pre-written synthetic Zarr stores, so the real driver logic (restart
injection, delta computation, convergence stop) runs without a solver.

The convergence of a spinup is measured on heads and on lake stages, and its result
says what a non-converged antecedent is.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.model.flow_config import FlowConfig
from hydromodpy.model.initial_config import FlowInitialConditions, SpinupConfig
from hydromodpy.project.spinup import cycle_delta, lake_stage_delta, run_spinup
from hydromodpy.results.storage.final_state import FinalState, write_final_state


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


def test_cycle_delta_reports_linf_head_and_stage(tmp_path: Path) -> None:
    prev = _write_cycle_zarr(tmp_path / "p.zarr", [[10.0, 10.0, 10.0]], {"lac0": 86.0})
    curr = _write_cycle_zarr(tmp_path / "q.zarr", [[10.2, 10.0, 10.0]], {"lac0": 86.05})
    d_head, d_stage = cycle_delta(prev, curr)
    assert d_head == pytest.approx(0.2)
    assert d_stage == pytest.approx(0.05)


def test_cycle_delta_rejects_shape_change(tmp_path: Path) -> None:
    a = _write_cycle_zarr(tmp_path / "a.zarr", [[5.0, 6.0, 7.0]])
    b = _write_cycle_zarr(tmp_path / "b.zarr", [[5.0, 6.0]])
    with pytest.raises(ValueError, match="mesh is not stable"):
        cycle_delta(a, b)


def _run_with_final_state(folder: Path, stored: list, exact: list, stage: float) -> str:
    """A run folder whose field store holds ``stored`` and whose ``final_state/`` holds ``exact``."""
    folder.mkdir()
    store = _write_cycle_zarr(folder / "fields.zarr", stored, {"lac0": stage + 1.0})
    write_final_state(
        folder,
        FinalState(
            head=np.asarray(exact, dtype=float),
            lake_stages={"lac0": stage},
            at=pd.Timestamp("2020-12-31"),
        ),
    )
    return store


def test_a_run_of_2_0_without_a_final_state_is_compared_on_its_field_store(tmp_path: Path) -> None:
    prev = _write_cycle_zarr(tmp_path / "old0.zarr", [[10.0, 10.0]], {"lac0": 86.0})
    curr = _run_with_final_state(tmp_path / "c1", [[10.5, 10.0]], [[10.75, 10.0]], 86.25)
    # The first cycle has no final_state/, the second has: each is read as it is stored.
    d_head, d_stage = cycle_delta(prev, curr)
    assert (d_head, d_stage) == (0.75, 0.25)


class _StubProject:
    """Minimal Project stand-in: simulate() returns a pre-written cycle Zarr."""

    def __init__(self, cfg, cycle_zarrs: list[str]) -> None:
        self.config = self._cfg = cfg
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
        self.simulated_ic_type.append(self.config.flow.ic.h.kind)
        path = self._cycle_zarrs[self._i]
        self._i += 1
        sid = f"sid::{name}"
        self._by_sid[sid] = path
        return SimpleNamespace(sim_id=sid)


def _stub_config() -> SimpleNamespace:
    return SimpleNamespace(
        flow=FlowConfig(),  # real flow config so ic.h.kind / restart_from behave
        simulation=SimpleNamespace(time=SimpleNamespace(start_datetime=None, end_datetime=None)),
        spinup=None,
    )


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
    cfg.flow.ic = FlowInitialConditions.model_validate({"kind": "steady_state"})
    project = _StubProject(cfg, zarrs)

    run_spinup(project, spinup=SpinupConfig(max_cycles=3, tol_head=0.01, tol_stage=0.01))

    # Cycle 0 ran with the original steady IC; every restarted cycle used top.
    assert project.simulated_ic_type[0] == "steady_state"
    assert project.simulated_ic_type[1:] == ["top", "top"]
    # And each restarted cycle carried the prior cycle's Zarr as restart_from.
    assert project.simulated_restart_from == [None, zarrs[0], zarrs[1]]


def test_the_cycles_store_exact_heads_and_the_project_gets_its_precision_back(
    tmp_path: Path,
) -> None:
    zarrs = [
        _write_cycle_zarr(tmp_path / "c0.zarr", [[0.0, 0.0, 0.0]], {"lac0": 80.0}),
        _write_cycle_zarr(tmp_path / "c1.zarr", [[0.0, 0.0, 0.0]], {"lac0": 80.0}),
    ]
    cfg = _stub_config()
    cfg.simulation.results = SimpleNamespace(persistence=SimpleNamespace(field_precision="compact"))
    seen: list[str] = []
    project = _StubProject(cfg, zarrs)
    simulate = project.simulate

    def _record(*, name: str):
        seen.append(cfg.simulation.results.persistence.field_precision)
        return simulate(name=name)

    project.simulate = _record
    run_spinup(project, spinup=SpinupConfig(max_cycles=2, tol_head=0.01, tol_stage=0.01))

    assert seen == ["exact", "exact"]
    assert cfg.simulation.results.persistence.field_precision == "compact"


def test_spinup_refuses_a_sites_project(tmp_path: Path) -> None:
    from hydromodpy.core.exceptions import ConfigError
    from hydromodpy.project import api

    project = tmp_path / "project.toml"
    project.write_text('[sites]\ntable = "sites.csv"\n\n[sites.recipes]\nbase = "base.toml"\n')

    with pytest.raises(ConfigError, match=r"declares \[sites\]"):
        api.spinup(project)


@pytest.mark.parametrize(
    ("before", "after", "delta"),
    [
        pytest.param({}, {}, 0.0, id="no-lake-at-all-is-a-change-of-zero"),
        pytest.param(
            {"cheze": 1.0},
            {"cheze": 1.25},
            pytest.approx(0.25),
            id="a-shared-lake-gives-its-largest-change",
        ),
        pytest.param(
            {"a": 1.0, "b": 5.0},
            {"a": 1.1, "b": 5.9},
            pytest.approx(0.9),
            id="several-lakes-give-the-largest-of-them",
        ),
        pytest.param(
            {"cheze": 1.0}, {}, None, id="a-lake-gone-in-the-second-cycle-is-no-comparison"
        ),
        pytest.param(
            {}, {"cheze": 1.0}, None, id="a-lake-new-in-the-second-cycle-is-no-comparison"
        ),
        pytest.param({"a": 1.0}, {"b": 1.0}, None, id="two-cycles-naming-different-lakes"),
    ],
)
def test_the_lake_stage_delta_is_the_largest_change_of_the_lakes_both_cycles_name(
    before: dict[str, float], after: dict[str, float], delta: object
) -> None:
    assert lake_stage_delta(before, after) == delta


def test_the_result_says_what_a_non_converged_antecedent_is(tmp_path) -> None:
    """`--then-run` seeds production from the last cycle whether it settled or not."""
    from hydromodpy.project.spinup import SpinupCycle, SpinupResult

    result = SpinupResult(
        converged=False,
        cycles=[SpinupCycle(0, "a", "a.zarr", None, None)],
        restart_from="a.zarr",
    )

    assert result.antecedent_warning() is not None
    assert "did not converge" in result.antecedent_warning()


@pytest.mark.parametrize("converged", [True, False])
def test_the_result_gives_its_json_form_with_the_warning_a_cli_prints(converged: bool) -> None:
    import json

    from hydromodpy.project.spinup import SpinupCycle, SpinupResult

    result = SpinupResult(
        converged=converged,
        cycles=[SpinupCycle(0, "a", "a.zarr", None, None), SpinupCycle(1, "b", "b.zarr", 0.5, 0.0)],
        restart_from="b.zarr",
        production_sim_id="p1",
    )
    document = json.loads(json.dumps(result.to_dict()))
    assert document["cycles"] == [
        {"index": 0, "d_head": None, "d_stage": None},
        {"index": 1, "d_head": 0.5, "d_stage": 0.0},
    ]
    assert document["warning"] == result.antecedent_warning()
    assert {key: document[key] for key in ("converged", "n_cycles", "restart_from")} == {
        "converged": converged,
        "n_cycles": 2,
        "restart_from": "b.zarr",
    }
    assert document["production_sim_id"] == "p1"
