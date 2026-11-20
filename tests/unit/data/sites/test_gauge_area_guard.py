"""Hub'Eau area guard: it checks the gauge of the run (area in km2) and warns beyond 20 per cent."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from hydromodpy.core.io.fetch import HTTPClient
from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.data.sites.gauge import check_run_gauge_area
from hydromodpy.data.variables.hydrometry import catchment_area_check as mod

BOUNDS = Bounds()


def site(gauge: str | None = None):
    return SimpleNamespace(gauge=gauge)


def loaded(*ids: str):
    return SimpleNamespace(
        has_points=bool(ids), points=[SimpleNamespace(station_id=i) for i in ids]
    )


def warnings_of(caplog) -> list:
    return [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_fifteen_per_cent_does_not_warn(monkeypatch, caplog):
    monkeypatch.setattr(mod, "published_catchment_area_km2", lambda _sid, **_kw: 100.0)
    with caplog.at_level(logging.INFO):
        mod.compare_catchment_area("J001401001", 115.0, client=HTTPClient())
    assert not warnings_of(caplog)


def test_no_check_without_a_hubeau_gauge_and_an_area(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        mod, "published_catchment_area_km2", lambda sid, **_kw: calls.append(sid) or 10.0
    )
    assert mod.check_gauge_area(None, 50.0, client=HTTPClient()) is None
    assert mod.check_gauge_area("my_station", 50.0, client=HTTPClient()) is None
    assert mod.check_gauge_area("J001401001", None, client=HTTPClient()) is None
    assert mod.check_gauge_area("J001401001", 0.0, client=HTTPClient()) is None
    assert calls == []


def test_the_gauge_of_the_run_is_checked(monkeypatch, caplog):
    seen: list[str] = []
    monkeypatch.setattr(
        mod, "published_catchment_area_km2", lambda sid, **_kw: seen.append(sid) or 64.45
    )
    with caplog.at_level(logging.INFO):
        # Declared gauge among several stations.
        check_run_gauge_area(
            site("J001401001"), loaded("J001401001", "K123456701"), 96.5, bounds=BOUNDS
        )
        assert seen == ["J001401001"]
        assert warnings_of(caplog)
        # No declared gauge: the single loaded station.
        check_run_gauge_area(None, loaded("J001401001"), 96.5, bounds=BOUNDS)
        assert seen == ["J001401001", "J001401001"]
    # Several stations and no declared gauge: no gauge, no check.
    check_run_gauge_area(None, loaded("J001401001", "K123456701"), 96.5, bounds=BOUNDS)
    check_run_gauge_area(None, None, 96.5, bounds=BOUNDS)
    assert len(seen) == 2


def test_the_data_step_runs_the_guard(monkeypatch, caplog):
    from hydromodpy.workflow.steps import data as data_step

    monkeypatch.setattr(mod, "published_catchment_area_km2", lambda _sid, **_kw: 64.45)
    monkeypatch.setattr(data_step, "apply_structural_updates_from_data", lambda _state: None)
    monkeypatch.setattr(
        data_step,
        "_build_data_runtime_loader",
        lambda **_kw: SimpleNamespace(load_all=lambda _state: None),
    )
    run_state = SimpleNamespace(
        cfg=SimpleNamespace(site=site("J001401001")),
        setup=SimpleNamespace(geographic=SimpleNamespace(catch_area=96.5), soil_forcings=None),
        loaded_data=SimpleNamespace(hydrometry=None, loaded_plan_types=()),
        execution=SimpleNamespace(lightweight=False),
        config_path="c.toml",
        data_plan=SimpleNamespace(types=()),
        bounds=Bounds(),
    )
    with caplog.at_level(logging.INFO):
        data_step.step_data_loading(run_state)
    assert warnings_of(caplog)
