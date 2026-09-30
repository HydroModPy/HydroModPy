"""The soil water budget prints once per ``run_data``, never from the binder alone.

``run_data`` prints the block after the binder has run, through
``progress.after_phase`` so it lands after the phase's own checkmark. The
binder itself (``apply_structural_updates_from_data``) only computes and
stores ``setup.soil_forcings``; it never prints. A lightweight context (a
calibration trial replaying ``load_data``) stays silent either way.
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from hydromodpy.core.state.data import LoadedDataContext
from hydromodpy.core.state.execution import ExecutionRegistry
from hydromodpy.core.state.setup import SetupContext
from hydromodpy.core.time import ResolvedSimulationTimeWindow
from hydromodpy.physics.hydrology.soil_reservoir.config import SoilReservoirConfig
from hydromodpy.workflow.steps import data as data_step


def _window() -> ResolvedSimulationTimeWindow:
    return ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2015-01-01"),
        end=pd.Timestamp("2015-01-02"),
        step_value=1,
        step_unit="day",
        coverage_policy="ignore",
    )


def _soil_forcings() -> SimpleNamespace:
    return SimpleNamespace(
        recharge=object(),
        residual_etp=object(),
        runoff=object(),
        days=["2015-01-01", "2015-01-02"],
    )


def _run_state(*, lightweight: bool, with_soil: bool) -> SimpleNamespace:
    soil = SoilReservoirConfig(ru=150.0, spinup="none") if with_soil else None
    setup = SetupContext(
        flow=SimpleNamespace(active_bc=[], sinks_sources={}),
        domain=object(),
        geographic=SimpleNamespace(crs_proj="EPSG:2154", catch_area=10.0),
        time_grid=SimpleNamespace(window=_window()),
    )
    return SimpleNamespace(
        setup=setup,
        loaded_data=LoadedDataContext(hydrometry=None, precipitation=object(), etp=object()),
        cfg=SimpleNamespace(
            flow=SimpleNamespace(
                sinks_sources=SimpleNamespace(recharge=SimpleNamespace(soil=soil)),
                flow_regime="transient",
                first_period_steady=False,
                active_sinks_sources=["recharge", "etp"],
            )
        ),
        execution=ExecutionRegistry(lightweight=lightweight),
    )


def _patch_binder_internals(monkeypatch) -> None:
    monkeypatch.setattr(data_step, "compute_soil_forcings", lambda **kwargs: _soil_forcings())
    monkeypatch.setattr(data_step, "apply_recharge_load_result_to_flow", lambda **kwargs: False)
    monkeypatch.setattr(data_step, "apply_etp_load_result_to_flow", lambda **kwargs: False)
    monkeypatch.setattr(data_step, "apply_runoff_to_sfr_networks", lambda **kwargs: False)
    monkeypatch.setattr(data_step, "apply_lake_meteo_forcings_to_flow", lambda **kwargs: False)
    monkeypatch.setattr(data_step, "ru_ladder", lambda soil: ())
    monkeypatch.setattr(data_step, "gauged_discharge_line", lambda *args, **kwargs: "line")
    monkeypatch.setattr(data_step, "soil_budget_lines", lambda soil, **kwargs: ("line",))


def test_run_data_prints_the_soil_budget_exactly_once(monkeypatch) -> None:
    run_state = _run_state(lightweight=False, with_soil=True)
    _patch_binder_internals(monkeypatch)
    fake_loader = SimpleNamespace(load_all=lambda run_state: None)
    monkeypatch.setattr(data_step, "_build_data_runtime_loader", lambda **kwargs: fake_loader)
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(data_step, "_log_soil_budget", lambda lines: calls.append(lines))

    data_step.run_data("config.toml", SimpleNamespace(types=()), run_state)

    assert calls == [("line",)]


def test_the_binder_alone_never_prints_the_soil_budget(monkeypatch) -> None:
    run_state = _run_state(lightweight=False, with_soil=True)
    _patch_binder_internals(monkeypatch)
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(data_step, "_log_soil_budget", lambda lines: calls.append(lines))

    data_step.apply_structural_updates_from_data(run_state)

    assert calls == []
    assert run_state.setup.soil_forcings is not None


def test_a_lightweight_context_stays_silent(monkeypatch) -> None:
    run_state = _run_state(lightweight=True, with_soil=True)
    _patch_binder_internals(monkeypatch)
    fake_loader = SimpleNamespace(load_all=lambda run_state: None)
    monkeypatch.setattr(data_step, "_build_data_runtime_loader", lambda **kwargs: fake_loader)
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(data_step, "_log_soil_budget", lambda lines: calls.append(lines))

    data_step.run_data("config.toml", SimpleNamespace(types=()), run_state)

    assert calls == []
