from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from hydromodpy.data_managers.plan import DataLoadPlan
from hydromodpy.data_managers.runtime_loader import DataManagersRuntimeLoader


def _build_loader(tmp_path: Path) -> DataManagersRuntimeLoader:
    return DataManagersRuntimeLoader(
        config_path=tmp_path / "launcher.toml",
        data_plan=DataLoadPlan(),
    )


def test_apply_station_time_window_overrides_dates_when_enabled(tmp_path: Path) -> None:
    loader = _build_loader(tmp_path)
    payload = {
        "hydrometry": {
            "use_simulation_time_window": True,
            "date_start": "1990-01-01",
            "date_end": "1990-12-31",
        }
    }
    result = SimpleNamespace()
    loader._resolve_simulation_time_window_dates = lambda _result: ("2020-01-01", "2020-01-31")

    loader._apply_simulation_window_to_station_section(
        result=result,
        payload=payload,
        root_key="hydrometry",
        manager_type="hydrometry",
    )

    assert payload["hydrometry"]["date_start"] == "2020-01-01"
    assert payload["hydrometry"]["date_end"] == "2020-01-31"


def test_apply_station_time_window_keeps_explicit_dates_when_disabled(tmp_path: Path) -> None:
    loader = _build_loader(tmp_path)
    payload = {
        "piezometry": {
            "use_simulation_time_window": False,
            "date_start": "2010-01-01",
            "date_end": "2010-12-31",
        }
    }
    result = SimpleNamespace()
    loader._resolve_simulation_time_window_dates = lambda _result: ("2020-01-01", "2020-01-31")

    loader._apply_simulation_window_to_station_section(
        result=result,
        payload=payload,
        root_key="piezometry",
        manager_type="piezometry",
    )

    assert payload["piezometry"]["date_start"] == "2010-01-01"
    assert payload["piezometry"]["date_end"] == "2010-12-31"


def test_apply_station_time_window_warns_and_falls_back_when_window_missing(
    tmp_path: Path,
    capsys,
) -> None:
    loader = _build_loader(tmp_path)
    payload = {
        "hydrometry": {
            "use_simulation_time_window": "true",
            "date_start": "2015-01-01",
            "date_end": "2015-12-31",
        }
    }
    result = SimpleNamespace()
    loader._resolve_simulation_time_window_dates = lambda _result: None

    loader._apply_simulation_window_to_station_section(
        result=result,
        payload=payload,
        root_key="hydrometry",
        manager_type="hydrometry",
    )

    captured = capsys.readouterr()
    assert "use_simulation_time_window=true" in captured.out
    assert payload["hydrometry"]["date_start"] == "2015-01-01"
    assert payload["hydrometry"]["date_end"] == "2015-12-31"
