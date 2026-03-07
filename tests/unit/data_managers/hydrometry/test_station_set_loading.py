"""Golden non-regression tests for deterministic hydrometry StationSet loading."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.data_managers.hydrometry.loaders_api import ApiLoadResult, ApiStationLoader
from hydromodpy.data_managers.hydrometry.station import Station
from hydromodpy.data_managers.hydrometry.station_set import StationSet


GOLDEN_FILE = Path(__file__).resolve().parent / "golden" / "station_set_loading_golden.json"


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


def _build_signature(stations: StationSet) -> dict:
    ids = sorted(stations.stations.keys())
    missing_df = stations.missing_data_summary.copy()

    by_station: dict[str, dict] = {}
    for station_id in ids:
        station = stations.stations[station_id]
        data = station.data.copy()
        n_rows = int(len(data))
        values = pd.to_numeric(data.get("resultat_obs_elab"), errors="coerce")
        sum_values = float(values.sum()) if n_rows > 0 else 0.0

        item = {
            "n_rows": n_rows,
            "sum_resultat_obs_elab": round(sum_values, 6),
            "first_date": _as_date_str(data["date_obs_elab"].min()) if n_rows > 0 else None,
            "last_date": _as_date_str(data["date_obs_elab"].max()) if n_rows > 0 else None,
        }

        if "specific_discharge" in data.columns:
            specific = pd.to_numeric(data["specific_discharge"], errors="coerce")
            item["sum_specific_discharge"] = round(float(specific.sum()), 6)

        row = missing_df[missing_df["station_id"].astype(str) == station_id]
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

        by_station[station_id] = item

    total_missing = 0
    if not missing_df.empty and "missing_days" in missing_df.columns:
        total_missing = int(missing_df["missing_days"].sum())

    return {
        "station_ids": ids,
        "total_rows": int(len(stations.data)),
        "total_missing_days": total_missing,
        "stations": by_station,
    }


def _create_local_fixture_data(local_dir: Path) -> list[str]:
    station_ids = ["J111111101", "J222222201"]

    pd.DataFrame(
        {
            "date_obs_elab": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "resultat_obs_elab": [10.0, 11.0, 12.0],
        }
    ).to_csv(local_dir / "J111111101.csv", index=False)

    pd.DataFrame(
        {
            "date_obs_elab": ["2024-01-01", "2024-01-03"],
            "resultat_obs_elab": [20.0, 22.0],
        }
    ).to_csv(local_dir / "J222222201.csv", index=False)

    return station_ids


def _build_mocked_api_result(station_ids: list[str]) -> ApiLoadResult:
    start_date = datetime(2024, 1, 1)
    end_date = datetime(2024, 1, 3)
    rows_by_station = {
        "J736422001": pd.DataFrame(
            {
                "date_obs_elab": ["2024-01-01", "2024-01-02", "2024-01-03"],
                "resultat_obs_elab": [1.0, 1.1, 1.2],
                "specific_discharge": [0.01, 0.011, 0.012],
            }
        ),
        "J751301001": pd.DataFrame(
            {
                "date_obs_elab": ["2024-01-01", "2024-01-03"],
                "resultat_obs_elab": [2.0, 2.2],
                "specific_discharge": [0.04, 0.044],
            }
        ),
    }

    stations_info = []
    sites_info = []
    metadata = []
    all_data = []
    missing_summary = []
    stations: dict[str, Station] = {}

    for station_id in station_ids:
        frame = rows_by_station[station_id].copy()
        frame["station_id"] = station_id

        station_meta = {
            "station_id": station_id,
            "station_name": station_id,
            "start_date": start_date,
            "end_date": end_date,
        }
        station = Station(
            station_id=station_id,
            variable="QmnJ",
            data=frame,
            metadata=station_meta,
        )
        stations[station_id] = station
        all_data.append(station.data)
        missing_summary.append(
            station.completeness(
                start_date=start_date,
                end_date=end_date,
                verbose=False,
            )
        )
        stations_info.append({"station_id": station_id, "code_station": station_id})
        sites_info.append({"site_id": station_id[:8], "station_id": station_id})
        metadata.append(station_meta)

    return ApiLoadResult(
        stations_info=pd.DataFrame(stations_info),
        sites_info=pd.DataFrame(sites_info),
        metadata=pd.DataFrame(metadata),
        data=pd.concat(all_data, ignore_index=True),
        missing_data_summary=pd.DataFrame(missing_summary),
        stations=stations,
    )


def test_station_set_loading_golden(
    update_goldens: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validate local and mocked-api StationSet loading against golden signatures."""
    local_dir = tmp_path / "local_hydrometry"
    local_dir.mkdir(parents=True, exist_ok=True)
    local_station_ids = _create_local_fixture_data(local_dir)

    local_station_set = StationSet(
        variable="QmnJ",
        id=local_station_ids,
        display=False,
        date_start="2024-01-01",
        date_end="2024-01-03",
        output=None,
        source_mode="local",
        local_data_dir=local_dir,
    )

    def _fake_api_load(self, *, station_ids, site_ids):  # noqa: ARG001
        return _build_mocked_api_result([str(sid) for sid in station_ids])

    monkeypatch.setattr(ApiStationLoader, "load", _fake_api_load)

    api_station_set = StationSet(
        variable="QmnJ",
        id=["J736422001", "J751301001"],
        display=False,
        date_start="2024-01-01",
        date_end="2024-01-03",
        output=None,
        source_mode="api",
    )

    payload = {
        "local_basic": _build_signature(local_station_set),
        "api_mocked_basic": _build_signature(api_station_set),
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

