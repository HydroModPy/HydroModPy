from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.data.plan import DataLoadPlan
from hydromodpy.data.loader import DataManagersRuntimeLoader


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


def test_apply_station_time_window_requires_valid_window_when_enabled(
    tmp_path: Path,
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

    with pytest.raises(
        ValueError,
        match=r"data\.hydrometry\.use_simulation_time_window=true requires a valid \[simulation\.time\] section\.",
    ):
        loader._apply_simulation_window_to_station_section(
            result=result,
            payload=payload,
            root_key="hydrometry",
            manager_type="hydrometry",
        )

    assert payload["hydrometry"]["date_start"] == "2015-01-01"
    assert payload["hydrometry"]["date_end"] == "2015-12-31"


def test_require_simulation_time_window_dates_requires_valid_section(tmp_path: Path) -> None:
    loader = _build_loader(tmp_path)
    result = SimpleNamespace()
    loader._resolve_simulation_time_window_dates = lambda _result: None

    with pytest.raises(
        ValueError,
        match=r"data\.hydrometry\.use_simulation_time_window=true requires a valid \[simulation\.time\] section\.",
    ):
        loader._require_simulation_time_window_dates(
            result,
            option_name="data.hydrometry.use_simulation_time_window",
        )
