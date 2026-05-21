"""Cover ``BoussinesqFlowAdapter.extract_calibration_series``.

The Boussinesq adapter reads the simulated calibration series from the
``_boussinesq_state_history.npz`` file written by ``post_processing``. These
tests exercise the contract directly against a synthetic state-history file:
they fix the schema (shape, sign convention, station cell mapping) without
depending on a full Boussinesq solve.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.exceptions import ConfigError, SolverError
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

    series = BoussinesqFlowAdapter().extract_calibration_series(
        ctx, store=None, variable="discharge"
    )

    assert isinstance(series, pd.Series)
    assert series.name == "discharge"
    assert series.shape == (2,)
    assert series.to_numpy().tolist() == [3.0, 2.0]


def test_extract_discharge_ignores_negative_recharge_terms(tmp_path: Path) -> None:
    drainage = np.array([[1.0, -2.0, 3.0]], dtype=float)
    head = np.full((1, 3), 5.0, dtype=float)
    _write_state_history(tmp_path, head_history=head, drainage_history=drainage)
    ctx = _build_ctx("flow_main::boussinesq", tmp_path)

    series = BoussinesqFlowAdapter().extract_calibration_series(
        ctx, store=None, variable="discharge"
    )

    assert series.to_numpy().tolist() == [4.0]


def test_extract_discharge_aligns_with_time_index(tmp_path: Path) -> None:
    drainage = np.array([[1.0], [2.0], [3.0]], dtype=float)
    head = np.full((3, 1), 5.0, dtype=float)
    _write_state_history(tmp_path, head_history=head, drainage_history=drainage)
    ctx = _build_ctx("flow_main::boussinesq", tmp_path)

    time_index = pd.DatetimeIndex(["2020-01-01", "2020-01-02", "2020-01-03"])
    series = BoussinesqFlowAdapter().extract_calibration_series(
        ctx, store=None, variable="discharge", time_index=time_index
    )

    assert isinstance(series.index, pd.DatetimeIndex)
    assert series.index.tolist() == time_index.tolist()


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

    series = BoussinesqFlowAdapter().extract_calibration_series(
        ctx,
        store=None,
        variable="head",
        station_cells={"P1": (0, 0, 1)},
    )

    assert series.name == "head@P1"
    assert series.to_numpy().tolist() == [11.0, 11.5]


def test_extract_head_requires_station_cells(tmp_path: Path) -> None:
    head = np.array([[1.0, 2.0]], dtype=float)
    _write_state_history(tmp_path, head_history=head)
    ctx = _build_ctx("flow_main::boussinesq", tmp_path)

    with pytest.raises(ConfigError, match="head calibration requires station_cells"):
        BoussinesqFlowAdapter().extract_calibration_series(ctx, store=None, variable="head")


def test_extract_head_rejects_non_zero_layer(tmp_path: Path) -> None:
    head = np.array([[1.0, 2.0]], dtype=float)
    _write_state_history(tmp_path, head_history=head)
    ctx = _build_ctx("flow_main::boussinesq", tmp_path)

    with pytest.raises(ValueError, match="cell_id"):
        BoussinesqFlowAdapter().extract_calibration_series(
            ctx,
            store=None,
            variable="head",
            station_cells={"P1": (1, 0, 0)},
        )


def test_extract_head_rejects_multiple_stations(tmp_path: Path) -> None:
    head = np.array([[1.0, 2.0]], dtype=float)
    _write_state_history(tmp_path, head_history=head)
    ctx = _build_ctx("flow_main::boussinesq", tmp_path)

    with pytest.raises(ConfigError, match="single entry"):
        BoussinesqFlowAdapter().extract_calibration_series(
            ctx,
            store=None,
            variable="head",
            station_cells={"P1": (0, 0, 0), "P2": (0, 0, 1)},
        )


def test_extract_unknown_variable_raises_not_implemented(tmp_path: Path) -> None:
    head = np.array([[1.0, 2.0]], dtype=float)
    _write_state_history(tmp_path, head_history=head)
    ctx = _build_ctx("flow_main::boussinesq", tmp_path)

    with pytest.raises(NotImplementedError, match="concentration"):
        BoussinesqFlowAdapter().extract_calibration_series(
            ctx, store=None, variable="concentration"
        )


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
        BoussinesqFlowAdapter().extract_calibration_series(ctx, store=None, variable="discharge")
