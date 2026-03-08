"""Targeted tests for hydrometry discovery delegation."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.data_managers.hydrometry.discovery import normalize_station_ids
from hydromodpy.data_managers.hydrometry.station_set import StationSet


def test_normalize_station_ids_supports_site_and_station_ids() -> None:
    station_ids, site_ids = normalize_station_ids(["J1234567", "J765432101"])

    assert station_ids == ["J123456701", "J765432101"]
    assert site_ids == ["J1234567", "J7654321"]


def test_station_set_discover_station_ids_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: dict[str, object] = {}

    def _fake_discover(**kwargs):
        recorded.update(kwargs)
        return ["J000000001"]

    monkeypatch.setattr(
        "hydromodpy.data_managers.hydrometry.station_set.discover_station_ids_in_area",
        _fake_discover,
    )

    discovered = StationSet.discover_station_ids(mask_path="mask.shp", max_ids=1)

    assert discovered == ["J000000001"]
    assert recorded["mask_path"] == "mask.shp"
    assert recorded["max_ids"] == 1


def test_station_set_mask_mode_delegates_to_discovery(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pd.DataFrame(
        {
            "date_obs_elab": ["2024-01-01", "2024-01-02"],
            "resultat_obs_elab": [1.0, 2.0],
        }
    ).to_csv(tmp_path / "J111111101.csv", index=False)

    def _fake_select(mask_path, *, source_mode, local_data_dir, fallback_search_radius_m=10000.0):
        assert mask_path == "mask.shp"
        assert source_mode == "local"
        assert local_data_dir == tmp_path
        assert fallback_search_radius_m == 10000.0
        return ["J111111101"], ["J11111110"]

    monkeypatch.setattr(
        "hydromodpy.data_managers.hydrometry.station_set.select_station_ids_from_mask",
        _fake_select,
    )

    station_set = StationSet(
        variable="QmnJ",
        mask="mask.shp",
        display=False,
        output=None,
        source_mode="local",
        local_data_dir=tmp_path,
    )

    assert station_set.station_id == ["J111111101"]
    assert station_set.site_id == ["J11111110"]
    assert sorted(station_set.stations) == ["J111111101"]
