"""Targeted tests for piezometry discovery delegation."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.data_managers.piezometry.discovery import normalize_piezometer_ids
from hydromodpy.data_managers.piezometry.piezometer_set import PiezometerSet


def test_normalize_piezometer_ids_rejects_empty_values() -> None:
    with pytest.raises(ValueError, match="cannot contain empty values"):
        normalize_piezometer_ids(["BSS0000001", ""])


def test_piezometer_set_discover_ids_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: dict[str, object] = {}

    def _fake_discover(**kwargs):
        recorded.update(kwargs)
        return ["BSS0000001"]

    monkeypatch.setattr(
        "hydromodpy.data_managers.piezometry.piezometer_set.discover_piezometer_ids_in_area",
        _fake_discover,
    )

    discovered = PiezometerSet.discover_piezometer_ids(mask_path="mask.shp", max_ids=1)

    assert discovered == ["BSS0000001"]
    assert recorded["mask_path"] == "mask.shp"
    assert recorded["max_ids"] == 1


def test_piezometer_set_mask_mode_delegates_to_discovery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pd.DataFrame(
        {
            "date_measure": ["2024-01-01", "2024-01-02"],
            "groundwater_level_m": [10.0, 11.0],
            "groundwater_depth_m": [2.0, 1.0],
        }
    ).to_csv(tmp_path / "BSS0000001.csv", index=False)

    def _fake_select(mask_path, *, source_mode, local_data_dir, fallback_search_radius_km=25.0):
        assert mask_path == "mask.shp"
        assert source_mode == "local"
        assert local_data_dir == tmp_path
        assert fallback_search_radius_km == 25.0
        return ["BSS0000001"]

    monkeypatch.setattr(
        "hydromodpy.data_managers.piezometry.piezometer_set.select_piezometer_ids_from_mask",
        _fake_select,
    )

    piezometer_set = PiezometerSet(
        measurement="both",
        mask="mask.shp",
        display=False,
        output=None,
        source_mode="local",
        local_data_dir=tmp_path,
    )

    assert piezometer_set.piezometer_id == ["BSS0000001"]
    assert sorted(piezometer_set.piezometers) == ["BSS0000001"]
