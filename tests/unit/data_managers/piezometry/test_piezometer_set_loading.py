"""Golden non-regression tests for deterministic piezometry PiezometerSet loading."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.data_managers.piezometry.loaders_api import ApiLoadResult, ApiPiezometerLoader
from hydromodpy.data_managers.piezometry.piezometer import Piezometer
from hydromodpy.data_managers.piezometry.piezometer_set import PiezometerSet


GOLDEN_FILE = Path(__file__).resolve().parent / "golden" / "piezometer_set_loading_golden.json"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _as_date_str(value) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.strftime("%Y-%m-%d")


def _build_signature(piezometers: PiezometerSet) -> dict:
    ids = sorted(piezometers.piezometers.keys())
    missing_df = piezometers.missing_data_summary.copy()

    by_piezometer: dict[str, dict] = {}
    for piezometer_id in ids:
        piezometer = piezometers.piezometers[piezometer_id]
        data = piezometer.data.copy()
        n_rows = int(len(data))

        level = pd.to_numeric(data.get("groundwater_level_m"), errors="coerce")
        depth = pd.to_numeric(data.get("groundwater_depth_m"), errors="coerce")

        item = {
            "n_rows": n_rows,
            "sum_groundwater_level_m": round(float(level.sum()), 6) if n_rows > 0 else 0.0,
            "sum_groundwater_depth_m": round(float(depth.sum()), 6) if n_rows > 0 else 0.0,
            "first_date": _as_date_str(data["date_measure"].min()) if n_rows > 0 else None,
            "last_date": _as_date_str(data["date_measure"].max()) if n_rows > 0 else None,
        }

        row = missing_df[missing_df["piezometer_id"].astype(str) == piezometer_id]
        if not row.empty:
            first = row.iloc[0]
            item.update(
                {
                    "expected_days": int(first.get("expected_days", 0)),
                    "actual_days": int(first.get("actual_days", 0)),
                    "missing_days": int(first.get("missing_days", 0)),
                    "completeness_pct": round(float(first.get("completeness_pct", 0.0)), 6),
                }
            )
        else:
            item.update(
                {
                    "expected_days": 0,
                    "actual_days": 0,
                    "missing_days": 0,
                    "completeness_pct": 0.0,
                }
            )

        by_piezometer[piezometer_id] = item

    total_missing = 0
    if not missing_df.empty and "missing_days" in missing_df.columns:
        total_missing = int(missing_df["missing_days"].sum())

    return {
        "piezometer_ids": ids,
        "total_rows": int(len(piezometers.data)),
        "total_missing_days": total_missing,
        "piezometers": by_piezometer,
    }


def _create_local_fixture_data(local_dir: Path) -> list[str]:
    piezometer_ids = ["BSS0000001", "BSS0000002"]

    pd.DataFrame(
        {
            "date_measure": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "groundwater_level_m": [10.0, 11.0, 12.0],
            "groundwater_depth_m": [5.0, 4.0, 3.0],
        }
    ).to_csv(local_dir / "BSS0000001.csv", index=False)

    pd.DataFrame(
        {
            "date_measure": ["2024-01-01", "2024-01-03"],
            "groundwater_level_m": [20.0, 22.0],
            "groundwater_depth_m": [4.0, 6.0],
        }
    ).to_csv(local_dir / "BSS0000002.csv", index=False)

    return piezometer_ids


def _build_mocked_api_result(piezometer_ids: list[str]) -> ApiLoadResult:
    start_date = datetime(2024, 1, 1)
    end_date = datetime(2024, 1, 3)
    rows_by_piezometer = {
        "BSS0000001": pd.DataFrame(
            {
                "date_measure": ["2024-01-01", "2024-01-02", "2024-01-03"],
                "groundwater_level_m": [10.0, 11.0, 12.0],
                "groundwater_depth_m": [5.0, 4.0, 3.0],
            }
        ),
        "BSS0000002": pd.DataFrame(
            {
                "date_measure": ["2024-01-01", "2024-01-03"],
                "groundwater_level_m": [20.0, 22.0],
                "groundwater_depth_m": [4.0, 6.0],
            }
        ),
    }

    stations_info = []
    metadata = []
    all_data = []
    missing_summary = []
    piezometers: dict[str, Piezometer] = {}

    for piezometer_id in piezometer_ids:
        frame = rows_by_piezometer[piezometer_id].copy()
        frame["piezometer_id"] = piezometer_id

        piezometer_meta = {
            "piezometer_id": piezometer_id,
            "station_name": piezometer_id,
            "start_date": start_date,
            "end_date": end_date,
        }
        piezometer = Piezometer(
            piezometer_id=piezometer_id,
            measurement="both",
            data=frame,
            metadata=piezometer_meta,
        )
        piezometers[piezometer_id] = piezometer
        all_data.append(piezometer.data)
        missing_summary.append(
            piezometer.completeness(
                start_date=start_date,
                end_date=end_date,
                verbose=False,
            )
        )
        stations_info.append({"piezometer_id": piezometer_id, "code_bss": piezometer_id})
        metadata.append(piezometer_meta)

    return ApiLoadResult(
        stations_info=pd.DataFrame(stations_info),
        metadata=pd.DataFrame(metadata),
        data=pd.concat(all_data, ignore_index=True),
        missing_data_summary=pd.DataFrame(missing_summary),
        piezometers=piezometers,
    )


def test_piezometer_set_loading_golden(
    update_goldens: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validate local and mocked-api PiezometerSet loading against golden signatures."""
    local_dir = tmp_path / "local_piezometry"
    local_dir.mkdir(parents=True, exist_ok=True)
    local_piezometer_ids = _create_local_fixture_data(local_dir)

    local_piezometer_set = PiezometerSet(
        measurement="both",
        id=local_piezometer_ids,
        display=False,
        date_start="2024-01-01",
        date_end="2024-01-03",
        output=None,
        source_mode="local",
        local_data_dir=local_dir,
    )

    def _fake_api_load(self, *, piezometer_ids):
        return _build_mocked_api_result([str(pid) for pid in piezometer_ids])

    monkeypatch.setattr(ApiPiezometerLoader, "load", _fake_api_load)

    api_piezometer_set = PiezometerSet(
        measurement="both",
        id=["BSS0000001", "BSS0000002"],
        display=False,
        date_start="2024-01-01",
        date_end="2024-01-03",
        output=None,
        source_mode="api",
    )

    payload = {
        "local_basic": _build_signature(local_piezometer_set),
        "api_mocked_basic": _build_signature(api_piezometer_set),
    }

    if update_goldens:
        _write_json(GOLDEN_FILE, payload)
        return

    if not GOLDEN_FILE.exists():
        pytest.fail(
            f"Missing golden reference file: {GOLDEN_FILE}. "
            "Run tests with --update-goldens to generate it."
        )

    expected = _load_json(GOLDEN_FILE)
    assert payload == expected

