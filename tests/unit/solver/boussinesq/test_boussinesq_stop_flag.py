"""The Boussinesq solver reads the stop flag of its slot between two stress periods."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.runtime.interrupts import StopRequested
from hydromodpy.core.state.layout import stop_flag_for
from hydromodpy.model.flow import Flow
from hydromodpy.model.flow_config import FlowConfig
from hydromodpy.solver.boussinesq.drivers import transient

from ._test_boussinesq_flow_adapter_builders import (
    AdapterCall,
    _write_minimal_bundle,
    adapter_call,
)

PERIODS = 3


def _call(tmp_path: Path, *, flag: Path | None) -> AdapterCall:
    call = adapter_call(
        tmp_path,
        flow=Flow(FlowConfig.model_validate({"ic": {"kind": "top"}, "first_period_steady": False})),
        exchange_mesh=_write_minimal_bundle(tmp_path / "bundle"),
        time_grid=SimpleNamespace(period_lengths_seconds=(3600.0,) * PERIODS),
    )
    return replace(call, slot=replace(call.slot, stop_flag=flag))


def _ask_for_a_stop(flag: Path) -> None:
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text('{"schema": "hydromodpy.stop.v1", "at": "2026-11-10T10:00:00+00:00"}')


def _count_periods(
    monkeypatch: pytest.MonkeyPatch, *, stop_after: int | None, flag: Path
) -> list[int]:
    """Count the periods the driver advances, and ask for a stop after ``stop_after`` of them."""
    advanced: list[int] = []
    real = transient._advance_period

    def advance(*args, **kwargs):
        advance_result = real(*args, **kwargs)
        advanced.append(len(advanced))
        if stop_after is not None and len(advanced) == stop_after:
            _ask_for_a_stop(flag)
        return advance_result

    monkeypatch.setattr(transient, "_advance_period", advance)
    return advanced


CASES = (
    ("no flag asked, a run that cannot be stopped", False, None, PERIODS),
    ("a flag that nobody wrote", True, None, PERIODS),
    ("a stop asked during the first period", True, 1, 1),
    ("a stop asked during the second period", True, 2, 2),
)


@pytest.mark.parametrize(
    ("case", "has_flag", "stop_after", "advanced"), CASES, ids=[c[0] for c in CASES]
)
def test_the_solver_stops_between_two_periods(
    case: str,
    has_flag: bool,
    stop_after: int | None,
    advanced: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del case
    flag = stop_flag_for(tmp_path / "run")
    periods = _count_periods(monkeypatch, stop_after=stop_after, flag=flag)
    call = _call(tmp_path, flag=flag if has_flag else None)

    if stop_after is None:
        result = call.solve()
        assert result.solved is True
    else:
        with pytest.raises(StopRequested, match="stop requested at 2026-11-10T10:00:00"):
            call.solve()

    assert len(periods) == advanced


def test_a_stop_asked_before_the_solve_runs_no_period(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    flag = stop_flag_for(tmp_path / "run")
    periods = _count_periods(monkeypatch, stop_after=None, flag=flag)
    _ask_for_a_stop(flag)

    with pytest.raises(StopRequested):
        _call(tmp_path, flag=flag).solve()

    assert periods == []


def test_a_stopped_solve_writes_no_state_for_the_extractor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    flag = stop_flag_for(tmp_path / "run")
    _count_periods(monkeypatch, stop_after=1, flag=flag)
    call = _call(tmp_path, flag=flag)

    with pytest.raises(StopRequested):
        call.solve()

    assert not (call.slot.directory / "_boussinesq_state_history.npz").exists()
