"""In soil mode the binder feeds MODFLOW from the soil reservoir, not the loader.

``apply_structural_updates_from_data`` reads ``[flow.sinks_sources.recharge.soil]``
from ``run_state.cfg.flow``, calls ``compute_soil_forcings`` once, and sends its
outputs everywhere the loaded data would otherwise have gone: recharge, the ETP
the soil left unmet (marked ``from_soil_reservoir``), and the runoff (to both the
SFR binder and the lake meteo binder). The lake still receives the raw
precipitation and ETP for its own surface. Outside soil mode nothing changes and
``setup.soil_forcings`` stays ``None``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from hydromodpy.core.state.data import LoadedDataContext
from hydromodpy.core.state.setup import SetupContext
from hydromodpy.core.time import ResolvedSimulationTimeWindow
from hydromodpy.physics.hydrology.soil_reservoir.config import SoilReservoirConfig
from hydromodpy.workflow.steps.data import apply_structural_updates_from_data


def _window() -> ResolvedSimulationTimeWindow:
    return ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2015-01-01"),
        end=pd.Timestamp("2015-01-03"),
        step_value=1,
        step_unit="day",
        coverage_policy="ignore",
    )


_SOIL_RECHARGE = object()
_SOIL_RESIDUAL_ETP = object()
_SOIL_RUNOFF = object()


def _soil_forcings() -> SimpleNamespace:
    return SimpleNamespace(
        recharge=_SOIL_RECHARGE,
        residual_etp=_SOIL_RESIDUAL_ETP,
        runoff=_SOIL_RUNOFF,
    )


def _flow_cfg(*, with_soil: bool) -> SimpleNamespace:
    soil = SoilReservoirConfig(ru=150.0, spinup="none") if with_soil else None
    return SimpleNamespace(
        sinks_sources=SimpleNamespace(recharge=SimpleNamespace(soil=soil)),
        flow_regime="transient",
        first_period_steady=False,
    )


def _run_state(*, with_soil: bool) -> tuple[SimpleNamespace, dict[str, dict]]:
    calls: dict[str, dict] = {}
    setup = SetupContext(
        flow=SimpleNamespace(active_bc=[], sinks_sources={}),
        domain=object(),
        geographic=SimpleNamespace(crs_proj="EPSG:2154", catch_area=10.0),
        time_grid=SimpleNamespace(window=_window()),
    )
    loaded_data = LoadedDataContext(
        precipitation=object(),
        etp=object(),
        runoff=object(),
        recharge=object(),
    )
    run_state = SimpleNamespace(
        setup=setup,
        loaded_data=loaded_data,
        cfg=SimpleNamespace(flow=_flow_cfg(with_soil=with_soil)),
    )
    return run_state, calls


def _patch_capture(monkeypatch, calls: dict[str, dict]) -> None:
    def _capture(name):
        def _fn(**kwargs):
            calls[name] = kwargs
            return False

        return _fn

    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data.compute_soil_forcings",
        lambda **kwargs: _soil_forcings(),
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data.apply_recharge_load_result_to_flow",
        _capture("recharge"),
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data.apply_etp_load_result_to_flow",
        _capture("etp"),
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data.apply_runoff_to_sfr_networks",
        _capture("sfr_runoff"),
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data.apply_lake_meteo_forcings_to_flow",
        _capture("lake_meteo"),
    )


def test_the_binder_sends_the_soil_recharge_to_modflow(monkeypatch) -> None:
    run_state, calls = _run_state(with_soil=True)
    _patch_capture(monkeypatch, calls)

    apply_structural_updates_from_data(run_state)

    assert calls["recharge"]["recharge_result"] is _SOIL_RECHARGE


def test_the_binder_sends_the_soil_residual_etp_marked_from_soil_reservoir(
    monkeypatch,
) -> None:
    run_state, calls = _run_state(with_soil=True)
    _patch_capture(monkeypatch, calls)

    apply_structural_updates_from_data(run_state)

    assert calls["etp"]["etp_result"] is _SOIL_RESIDUAL_ETP
    assert calls["etp"]["from_soil_reservoir"] is True


def test_the_binder_sends_the_soil_runoff_to_the_sfr_network(monkeypatch) -> None:
    run_state, calls = _run_state(with_soil=True)
    _patch_capture(monkeypatch, calls)

    apply_structural_updates_from_data(run_state)

    assert calls["sfr_runoff"]["runoff"] is _SOIL_RUNOFF


def test_the_binder_sends_the_soil_runoff_to_the_lake_and_keeps_its_raw_meteo(
    monkeypatch,
) -> None:
    run_state, calls = _run_state(with_soil=True)
    _patch_capture(monkeypatch, calls)

    apply_structural_updates_from_data(run_state)

    assert calls["lake_meteo"]["runoff"] is _SOIL_RUNOFF
    assert calls["lake_meteo"]["precipitation"] is run_state.loaded_data.precipitation
    assert calls["lake_meteo"]["etp"] is run_state.loaded_data.etp


def test_the_binder_stores_the_soil_forcings_on_setup(monkeypatch) -> None:
    run_state, calls = _run_state(with_soil=True)
    _patch_capture(monkeypatch, calls)

    apply_structural_updates_from_data(run_state)

    assert run_state.setup.soil_forcings.recharge is _SOIL_RECHARGE


def test_the_binder_leaves_soil_forcings_none_without_a_soil_section(
    monkeypatch,
) -> None:
    run_state, calls = _run_state(with_soil=False)
    _patch_capture(monkeypatch, calls)

    apply_structural_updates_from_data(run_state)

    assert run_state.setup.soil_forcings is None
    assert calls["recharge"]["recharge_result"] is run_state.loaded_data.recharge
    assert calls["etp"]["etp_result"] is run_state.loaded_data.etp
    assert calls["etp"]["from_soil_reservoir"] is False
    assert calls["sfr_runoff"]["runoff"] is run_state.loaded_data.runoff


def test_the_binder_never_mutates_loaded_data(monkeypatch) -> None:
    run_state, calls = _run_state(with_soil=True)
    _patch_capture(monkeypatch, calls)
    loaded_data = run_state.loaded_data
    precipitation, etp, runoff, recharge = (
        loaded_data.precipitation,
        loaded_data.etp,
        loaded_data.runoff,
        loaded_data.recharge,
    )

    apply_structural_updates_from_data(run_state)

    assert run_state.loaded_data is loaded_data
    assert loaded_data.precipitation is precipitation
    assert loaded_data.etp is etp
    assert loaded_data.runoff is runoff
    assert loaded_data.recharge is recharge
