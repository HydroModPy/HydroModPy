"""Unit tests for piezometer set loading in local and API modes."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from hydromodpy.data_managers.piezometry.piezometer_set import PiezometerSet
from hydromodpy.data_managers.piezometry import loaders_api as loaders_api_module

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
PIEZOMETER_SET_LOADING_GOLDEN_FILE = GOLDEN_DIR / "piezometer_set_loading_golden.json"


class _DummyResponse:
    """Small response stub compatible with requests.Response usage in loaders."""

    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = int(status_code)

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise loaders_api_module.requests.exceptions.HTTPError(f"HTTP {self.status_code}")


def _safe_id_token(value: str) -> str:
    """Normalize values used in local piezometer export filenames."""
    return "".join(c if c.isalnum() else "_" for c in str(value))


def _write_piezometer_csv(path: Path, rows: list[tuple[str, float, float]]) -> None:
    """Write one piezometer csv with standard piezometry columns."""
    frame = pd.DataFrame(
        {
            "date_measure": [d for d, _, _ in rows],
            "groundwater_level_m": [v for _, v, _ in rows],
            "groundwater_depth_m": [v for _, _, v in rows],
            "qualification": ["Good"] * len(rows),
        }
    )
    frame.to_csv(path, index=False)


def _load_local_piezometer_set(tmp_path: Path) -> PiezometerSet:
    """Build a local-mode piezometer set with deterministic test data."""
    pid1 = "BSS0000001"
    pid2 = "BSS0000002"
    local_dir = tmp_path / "exports"
    local_dir.mkdir()

    _write_piezometer_csv(
        local_dir / f"{_safe_id_token(pid1)}_Station_One.csv",
        [
            ("2024-01-01", 10.0, 5.0),
            ("2024-01-02", 11.0, 4.0),
            ("2024-01-03", 12.0, 3.0),
        ],
    )
    _write_piezometer_csv(
        local_dir / f"{_safe_id_token(pid2)}.csv",
        [("2024-01-01", 20.0, 6.0), ("2024-01-03", 22.0, 4.0)],
    )

    pd.DataFrame(
        [
            {"piezometer_id": pid1, "station_name": "Station One"},
            {"piezometer_id": pid2, "station_name": "Station Two"},
        ]
    ).to_csv(local_dir / "metadata.csv", index=False)
    pd.DataFrame(
        [
            {
                "piezometer_id": pid1,
                "longitude_station": -2.0,
                "latitude_station": 48.0,
            },
            {
                "piezometer_id": pid2,
                "longitude_station": -1.9,
                "latitude_station": 48.1,
            },
        ]
    ).to_csv(local_dir / "stations_info.csv", index=False)

    return PiezometerSet(
        measurement="both",
        id=[pid1, pid2],
        source_mode="local",
        local_data_dir=local_dir,
        date_start="2024-01-01",
        date_end="2024-01-03",
        output=None,
    )


def _load_api_piezometer_set(monkeypatch: pytest.MonkeyPatch) -> PiezometerSet:
    """Build an api-mode piezometer set with fully mocked HTTP requests."""
    pid1 = "BSS0000001"
    pid2 = "BSS0000002"

    station_rows = {
        pid1: {
            "code_bss": pid1,
            "libelle_station": "Station One",
            "profondeur_investigation": 40.0,
            "altitude_station": 100.0,
            "date_debut_mesure": "2024-01-01",
            "date_fin_mesure": "2024-01-03",
            "geometry": {"type": "Point", "coordinates": [-2.0, 48.0]},
        },
        pid2: {
            "code_bss": pid2,
            "libelle_station": "Station Two",
            "profondeur_investigation": 50.0,
            "altitude_station": 90.0,
            "date_debut_mesure": "2024-01-01",
            "date_fin_mesure": "2024-01-03",
            "geometry": {"type": "Point", "coordinates": [-1.9, 48.1]},
        },
    }
    obs_rows = {
        pid1: [
            {
                "date_mesure": "2024-01-01",
                "niveau_nappe_eau": 10.0,
                "profondeur_nappe": 5.0,
                "libelle_qualification": "Good",
            },
            {
                "date_mesure": "2024-01-02",
                "niveau_nappe_eau": 11.0,
                "profondeur_nappe": 4.0,
                "libelle_qualification": "Good",
            },
            {
                "date_mesure": "2024-01-03",
                "niveau_nappe_eau": 12.0,
                "profondeur_nappe": 3.0,
                "libelle_qualification": "Good",
            },
        ],
        pid2: [
            {
                "date_mesure": "2024-01-01",
                "niveau_nappe_eau": 20.0,
                "profondeur_nappe": 6.0,
                "libelle_qualification": "Good",
            },
            {
                "date_mesure": "2024-01-03",
                "niveau_nappe_eau": 22.0,
                "profondeur_nappe": 4.0,
                "libelle_qualification": "Good",
            },
        ],
    }

    def fake_get(url, params=None, timeout=None, **kwargs):  # noqa: ARG001
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        params = params or {}

        if parsed.path.endswith("/niveaux_nappes/stations"):
            code = params.get("code_bss") or query.get("code_bss", [None])[0]
            if code is not None:
                row = station_rows.get(str(code))
                data = [row] if row is not None else []
                return _DummyResponse({"count": len(data), "data": data})
            data = list(station_rows.values())
            return _DummyResponse({"count": len(data), "data": data})

        if parsed.path.endswith("/niveaux_nappes/chroniques"):
            code = params.get("code_bss") or query.get("code_bss", [None])[0]
            data = list(obs_rows.get(str(code), []))
            return _DummyResponse({"count": len(data), "data": data})

        return _DummyResponse({"count": 0, "data": []}, status_code=404)

    monkeypatch.setattr(loaders_api_module.requests, "get", fake_get)

    return PiezometerSet(
        measurement="both",
        id=[pid1, pid2],
        source_mode="api",
        date_start="2024-01-01",
        date_end="2024-01-03",
        output=None,
        display=False,
    )


def _piezometer_set_signature(piezometers: PiezometerSet) -> dict:
    """Build a deterministic signature used in golden non-regression checks."""
    summary_df = piezometers.missing_data_summary.copy()
    summary_by_station = {}
    if not summary_df.empty and "piezometer_id" in summary_df.columns:
        for _, row in summary_df.iterrows():
            pid = str(row["piezometer_id"])
            summary_by_station[pid] = {
                "expected_days": int(row["expected_days"]),
                "actual_days": int(row["actual_days"]),
                "missing_days": int(row["missing_days"]),
                "completeness_pct": round(float(row["completeness_pct"]), 6),
            }

    station_payload = {}
    for pid in sorted(piezometers.piezometers.keys()):
        sdf = piezometers.piezometers[pid].data.copy()
        sdf["date_measure"] = pd.to_datetime(sdf["date_measure"], errors="coerce")
        levels = pd.to_numeric(sdf.get("groundwater_level_m"), errors="coerce")
        depths = pd.to_numeric(sdf.get("groundwater_depth_m"), errors="coerce")
        dates = sdf["date_measure"].dropna()
        payload = {
            "n_rows": int(len(sdf)),
            "sum_groundwater_level_m": round(float(levels.fillna(0.0).sum()), 8),
            "sum_groundwater_depth_m": round(float(depths.fillna(0.0).sum()), 8),
            "first_date": None if dates.empty else dates.min().strftime("%Y-%m-%d"),
            "last_date": None if dates.empty else dates.max().strftime("%Y-%m-%d"),
        }
        payload.update(summary_by_station.get(pid, {}))
        station_payload[pid] = payload

    total_missing_days = 0
    if not summary_df.empty and "missing_days" in summary_df.columns:
        total_missing_days = int(summary_df["missing_days"].sum())

    return {
        "piezometer_ids": sorted(piezometers.piezometers.keys()),
        "total_rows": int(len(piezometers.data)),
        "total_missing_days": total_missing_days,
        "piezometers": station_payload,
    }


def _write_json(path: Path, payload: dict) -> None:
    """Write json golden payload with stable formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2)
        stream.write("\n")


def _load_json(path: Path) -> dict:
    """Load one json golden payload."""
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def test_piezometer_set_local_loading_from_exported_files(tmp_path: Path):
    """Load two local piezometer files and compute completeness summary."""
    pid1 = "BSS0000001"
    pid2 = "BSS0000002"
    piezometers = _load_local_piezometer_set(tmp_path)

    assert set(piezometers.piezometers.keys()) == {pid1, pid2}
    assert len(piezometers.data) == 5
    assert set(piezometers.metadata["piezometer_id"].astype(str)) == {pid1, pid2}
    assert set(piezometers.stations_info["piezometer_id"].astype(str)) == {pid1, pid2}

    summary = piezometers.missing_data_summary.set_index("piezometer_id")
    assert int(summary.loc[pid1, "missing_days"]) == 0
    assert int(summary.loc[pid2, "missing_days"]) == 1

    station_two = piezometers.get_piezometer(pid2)
    assert station_two.georeferencing["is_georeferenced"] is True
    assert station_two.station_position["wgs84"]["x"] == pytest.approx(-1.9)


def test_piezometer_set_api_loading_with_mocked_requests(monkeypatch: pytest.MonkeyPatch):
    """Load two piezometers in API mode with mocked HTTP responses."""
    pid1 = "BSS0000001"
    pid2 = "BSS0000002"
    piezometers = _load_api_piezometer_set(monkeypatch)

    assert set(piezometers.piezometers.keys()) == {pid1, pid2}
    assert len(piezometers.data) == 5
    assert set(piezometers.data["piezometer_id"].astype(str).unique()) == {pid1, pid2}

    pid1_data = piezometers.data[piezometers.data["piezometer_id"] == pid1].sort_values("date_measure")
    assert float(pid1_data.iloc[0]["groundwater_level_m"]) == pytest.approx(10.0)

    summary = piezometers.missing_data_summary.set_index("piezometer_id")
    assert int(summary.loc[pid1, "missing_days"]) == 0
    assert int(summary.loc[pid2, "expected_days"]) == 3
    assert int(summary.loc[pid2, "actual_days"]) == 2
    assert int(summary.loc[pid2, "missing_days"]) == 1


def test_discover_piezometer_ids_with_observation_filter(monkeypatch: pytest.MonkeyPatch):
    """Discover valid code_bss from bbox and keep only stations with data."""
    station_rows = [
        {"code_bss": "BSS_A", "longitude_station": -1.80, "latitude_station": 48.10},
        {"code_bss": "BSS_B", "longitude_station": -1.82, "latitude_station": 48.11},
        {"code_bss": "BSS_C", "longitude_station": -1.84, "latitude_station": 48.12},
    ]
    chrono_counts = {"BSS_A": 3, "BSS_B": 0, "BSS_C": 1}

    def fake_get(url, params=None, timeout=None, **kwargs):  # noqa: ARG001
        parsed = urlparse(url)
        params = params or {}

        if parsed.path.endswith("/niveaux_nappes/stations"):
            return _DummyResponse({"count": len(station_rows), "data": station_rows})

        if parsed.path.endswith("/niveaux_nappes/chroniques"):
            sid = str(params.get("code_bss"))
            count = int(chrono_counts.get(sid, 0))
            return _DummyResponse({"count": count, "data": ([{"x": 1}] if count > 0 else [])})

        return _DummyResponse({"count": 0, "data": []}, status_code=404)

    monkeypatch.setattr(loaders_api_module.requests, "get", fake_get)

    discovered = PiezometerSet.discover_piezometer_ids(
        bbox=(-1.9, 48.0, -1.7, 48.2),
        require_observations=True,
        date_start="2024-01-01",
        date_end="2024-12-31",
        max_ids=10,
    )
    assert discovered == ["BSS_A", "BSS_C"]


def test_piezometer_set_loading_golden_non_regression(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    update_goldens: bool,
):
    """Non-regression check on deterministic local/api loading signatures."""
    local_piezometers = _load_local_piezometer_set(tmp_path)
    api_piezometers = _load_api_piezometer_set(monkeypatch)

    actual = {
        "local_basic": _piezometer_set_signature(local_piezometers),
        "api_mocked_basic": _piezometer_set_signature(api_piezometers),
    }

    if update_goldens:
        _write_json(PIEZOMETER_SET_LOADING_GOLDEN_FILE, actual)
        return

    if not PIEZOMETER_SET_LOADING_GOLDEN_FILE.exists():
        pytest.fail(
            f"Missing golden reference file: {PIEZOMETER_SET_LOADING_GOLDEN_FILE}. "
            "Run tests with --update-goldens to generate it."
        )

    expected = _load_json(PIEZOMETER_SET_LOADING_GOLDEN_FILE)
    assert expected == actual
