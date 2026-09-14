"""Cover ``BoussinesqFlowAdapter.extract_observables``.

The Boussinesq adapter reads the simulated observables from the
``_boussinesq_state_history.npz`` file written by ``post_processing``. These
tests exercise the contract directly against a synthetic state-history file:
they fix the schema (shape, sign convention, station cell mapping, units)
without depending on a full Boussinesq solve.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.contracts.observables import ObservableRequest
from hydromodpy.core.exceptions import ObservableNotAvailableError, SolverError
from hydromodpy.simulation.planning.plan import (
    ProcessRun,
    RunContext,
    SimulationPlan,
)
from hydromodpy.solver.boussinesq.adapters.flow import BoussinesqFlowAdapter


def _write_state_history(
    output_dir: Path,
    *,
    head_history: np.ndarray,
    drainage_history: np.ndarray | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, np.ndarray] = {
        "head_history_m": np.asarray(head_history, dtype=float),
    }
    if drainage_history is not None:
        payload["drainage_flux_history_m3_s"] = np.asarray(drainage_history, dtype=float)
    np.savez(output_dir / "_boussinesq_state_history.npz", **payload)


def _build_ctx(run_id: str, output_dir: Path) -> RunContext:
    run = ProcessRun(
        id=run_id,
        process_id="flow_main",
        process_type="flow",
        solver="boussinesq",
    )
    state = SimpleNamespace(
        setup=SimpleNamespace(),
        execution=SimpleNamespace(
            output_dirs_by_run_id={run.id: output_dir},
            models_by_run_id={},
        ),
    )
    return RunContext(
        plan=SimulationPlan(name="demo", description="demo", runs=(run,)),
        run=run,
        state=state,
    )


def _discharge_request() -> ObservableRequest:
    return ObservableRequest(id="q", name="discharge", support="domain")


def test_extract_discharge_returns_sum_per_timestep(tmp_path: Path) -> None:
    drainage = np.array(
        [
            [1.0, 2.0, 0.0],
            [0.5, 0.0, 1.5],
        ],
        dtype=float,
    )
    head = np.full((2, 3), 5.0, dtype=float)
    _write_state_history(tmp_path, head_history=head, drainage_history=drainage)
    ctx = _build_ctx("flow_main::boussinesq", tmp_path)

    served = BoussinesqFlowAdapter().extract_observables(ctx, None, [_discharge_request()])

    assert set(served) == {"q"}
    result = served["q"]
    assert result.request_id == "q"
    assert isinstance(result.values, np.ndarray)
    assert result.values.shape == (2,)
    np.testing.assert_array_equal(result.values, np.array([3.0, 2.0]))
    assert result.units == "m3 s-1"


def test_extract_discharge_ignores_negative_recharge_terms(tmp_path: Path) -> None:
    drainage = np.array([[1.0, -2.0, 3.0]], dtype=float)
    head = np.full((1, 3), 5.0, dtype=float)
    _write_state_history(tmp_path, head_history=head, drainage_history=drainage)
    ctx = _build_ctx("flow_main::boussinesq", tmp_path)

    served = BoussinesqFlowAdapter().extract_observables(ctx, None, [_discharge_request()])

    np.testing.assert_array_equal(served["q"].values, np.array([4.0]))


def test_extract_discharge_aligns_with_time_index(tmp_path: Path) -> None:
    drainage = np.array([[1.0], [2.0], [3.0]], dtype=float)
    head = np.full((3, 1), 5.0, dtype=float)
    _write_state_history(tmp_path, head_history=head, drainage_history=drainage)
    ctx = _build_ctx("flow_main::boussinesq", tmp_path)

    time_index = pd.DatetimeIndex(["2020-01-01", "2020-01-02", "2020-01-03"])
    served = BoussinesqFlowAdapter().extract_observables(
        ctx, None, [_discharge_request()], time_index=time_index
    )

    result = served["q"]
    assert isinstance(result.times, pd.DatetimeIndex)
    assert result.times.tolist() == time_index.tolist()
    assert result.values.size == len(time_index)


def test_extract_head_reads_history_at_cell(tmp_path: Path) -> None:
    head = np.array(
        [
            [10.0, 11.0, 12.0],
            [10.5, 11.5, 12.5],
        ],
        dtype=float,
    )
    _write_state_history(tmp_path, head_history=head)
    ctx = _build_ctx("flow_main::boussinesq", tmp_path)

    request = ObservableRequest(id="P1", name="head", support="cell", cell=(0, 0, 1))
    served = BoussinesqFlowAdapter().extract_observables(ctx, None, [request])

    result = served["P1"]
    assert result.request_id == "P1"
    np.testing.assert_array_equal(result.values, np.array([11.0, 11.5]))
    assert result.units == "m"


def test_head_request_on_cell_support_requires_a_cell() -> None:
    with pytest.raises(ValueError, match="needs a .* cell"):
        ObservableRequest(id="P1", name="head", support="cell")


def test_extract_head_rejects_non_zero_layer(tmp_path: Path) -> None:
    head = np.array([[1.0, 2.0]], dtype=float)
    _write_state_history(tmp_path, head_history=head)
    ctx = _build_ctx("flow_main::boussinesq", tmp_path)

    request = ObservableRequest(id="P1", name="head", support="cell", cell=(1, 0, 0))
    with pytest.raises(ValueError, match="cell_id"):
        BoussinesqFlowAdapter().extract_observables(ctx, None, [request])


def test_extract_head_serves_several_stations_in_one_call(tmp_path: Path) -> None:
    head = np.array(
        [
            [1.0, 2.0],
            [1.5, 2.5],
        ],
        dtype=float,
    )
    _write_state_history(tmp_path, head_history=head)
    ctx = _build_ctx("flow_main::boussinesq", tmp_path)

    requests = [
        ObservableRequest(id="P1", name="head", support="cell", cell=(0, 0, 0)),
        ObservableRequest(id="P2", name="head", support="cell", cell=(0, 0, 1)),
    ]
    served = BoussinesqFlowAdapter().extract_observables(ctx, None, requests)

    assert set(served) == {"P1", "P2"}
    assert served["P1"].request_id == "P1"
    assert served["P2"].request_id == "P2"
    np.testing.assert_array_equal(served["P1"].values, np.array([1.0, 1.5]))
    np.testing.assert_array_equal(served["P2"].values, np.array([2.0, 2.5]))
    assert served["P1"].units == "m"
    assert served["P2"].units == "m"


def test_extract_unknown_observable_raises_not_available(tmp_path: Path) -> None:
    head = np.array([[1.0, 2.0]], dtype=float)
    _write_state_history(tmp_path, head_history=head)
    ctx = _build_ctx("flow_main::boussinesq", tmp_path)

    request = ObservableRequest(id="c", name="concentration", support="domain")
    with pytest.raises(ObservableNotAvailableError, match="concentration"):
        BoussinesqFlowAdapter().extract_observables(ctx, None, [request])


def test_extract_raises_when_no_output_dir_recorded(tmp_path: Path) -> None:
    run = ProcessRun(
        id="flow_main::boussinesq",
        process_id="flow_main",
        process_type="flow",
        solver="boussinesq",
    )
    state = SimpleNamespace(
        setup=SimpleNamespace(),
        execution=SimpleNamespace(
            output_dirs_by_run_id={},
            models_by_run_id={},
        ),
    )
    ctx = RunContext(
        plan=SimulationPlan(name="demo", description="demo", runs=(run,)),
        run=run,
        state=state,
    )

    with pytest.raises(SolverError, match="No solver output recorded"):
        BoussinesqFlowAdapter().extract_observables(ctx, None, [_discharge_request()])
