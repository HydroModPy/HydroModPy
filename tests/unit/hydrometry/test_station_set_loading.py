"""Unit tests for station set loading in local and API modes."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from hydromodpy.data_managers.hydrometry.station_set import StationSet
from hydromodpy.data_managers.hydrometry import loaders_api as loaders_api_module

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
STATION_SET_LOADING_GOLDEN_FILE = GOLDEN_DIR / "station_set_loading_golden.json"


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


def _write_station_csv(path: Path, rows: list[tuple[str, float]]) -> None:
    """Write one station csv with standard station-series columns."""
    frame = pd.DataFrame(
        {
            "date_obs_elab": [d for d, _ in rows],
            "resultat_obs_elab": [v for _, v in rows],
            "grandeur_hydro_elab": ["QmnJ"] * len(rows),
            "libelle_qualification": ["Good"] * len(rows),
        }
    )
    frame.to_csv(path, index=False)


def _load_local_station_set(tmp_path: Path) -> StationSet:
    """Build a local-mode station set with deterministic test data."""
    sid1 = "J111111101"
    sid2 = "J222222201"
    local_dir = tmp_path / "exports"
    local_dir.mkdir()

    _write_station_csv(
        local_dir / f"{sid1}_Station_One.csv",
        [("2024-01-01", 10.0), ("2024-01-02", 11.0), ("2024-01-03", 12.0)],
    )
    _write_station_csv(
        local_dir / f"{sid2}.csv",
        [("2024-01-01", 20.0), ("2024-01-03", 22.0)],
    )

    pd.DataFrame(
        [
            {"station_id": sid1, "station_name": "Station One"},
            {"station_id": sid2, "station_name": "Station Two"},
        ]
    ).to_csv(local_dir / "metadata.csv", index=False)
    pd.DataFrame(
        [
            {
                "station_id": sid1,
                "longitude_station": -2.0,
                "latitude_station": 48.0,
                "coordonnee_x_station": 300000.0,
                "coordonnee_y_station": 6800000.0,
            },
            {
                "station_id": sid2,
                "longitude_station": -1.9,
                "latitude_station": 48.1,
                "coordonnee_x_station": 350000.0,
                "coordonnee_y_station": 6810000.0,
            },
        ]
    ).to_csv(local_dir / "stations_info.csv", index=False)
    pd.DataFrame(
        [
            {"site_id": sid1[:8], "station_id": sid1},
            {"site_id": sid2[:8], "station_id": sid2},
        ]
    ).to_csv(local_dir / "sites_info.csv", index=False)

    return StationSet(
        variable="QmnJ",
        id=[sid1, sid2],
        source_mode="local",
        local_data_dir=local_dir,
        date_start="2024-01-01",
        date_end="2024-01-03",
        output=None,
    )


def _load_api_station_set(monkeypatch: pytest.MonkeyPatch) -> StationSet:
    """Build an api-mode station set with fully mocked HTTP requests."""
    sid1 = "J736422001"
    sid2 = "J751301001"
    site1 = sid1[:8]
    site2 = sid2[:8]

    station_rows = {
        sid1: {
            "code_station": sid1,
            "libelle_site": "Site One",
            "libelle_station": "Station One",
            "coordonnee_x_station": 300000.0,
            "coordonnee_y_station": 6800000.0,
            "longitude_station": -2.0,
            "latitude_station": 48.0,
            "libelle_commune": "Town One",
            "libelle_departement": "Dept",
            "libelle_region": "Region",
            "date_ouverture_station": "2010-01-01T00:00:00Z",
            "date_fermeture_station": None,
            "altitude_ref_alti_station": 100.0,
        },
        sid2: {
            "code_station": sid2,
            "libelle_site": "Site Two",
            "libelle_station": "Station Two",
            "coordonnee_x_station": 310000.0,
            "coordonnee_y_station": 6810000.0,
            "longitude_station": -1.9,
            "latitude_station": 48.1,
            "libelle_commune": "Town Two",
            "libelle_departement": "Dept",
            "libelle_region": "Region",
            "date_ouverture_station": "2010-01-01T00:00:00Z",
            "date_fermeture_station": None,
            "altitude_ref_alti_station": 90.0,
        },
    }
    site_rows = {
        site1: {"code_site": site1, "surface_bv": 100.0, "influence_generale_site": "N"},
        site2: {"code_site": site2, "surface_bv": 50.0, "influence_generale_site": "N"},
    }
    obs_rows = {
        sid1: [
            {
                "date_obs_elab": "2024-01-01",
                "resultat_obs_elab": 1000.0,
                "grandeur_hydro_elab": "QmnJ",
                "libelle_qualification": "Good",
            },
            {
                "date_obs_elab": "2024-01-02",
                "resultat_obs_elab": 1100.0,
                "grandeur_hydro_elab": "QmnJ",
                "libelle_qualification": "Good",
            },
            {
                "date_obs_elab": "2024-01-03",
                "resultat_obs_elab": 1200.0,
                "grandeur_hydro_elab": "QmnJ",
                "libelle_qualification": "Good",
            },
        ],
        sid2: [
            {
                "date_obs_elab": "2024-01-01",
                "resultat_obs_elab": 2000.0,
                "grandeur_hydro_elab": "QmnJ",
                "libelle_qualification": "Good",
            },
            {
                "date_obs_elab": "2024-01-03",
                "resultat_obs_elab": 2200.0,
                "grandeur_hydro_elab": "QmnJ",
                "libelle_qualification": "Good",
            },
        ],
    }

    def fake_get(url, params=None, timeout=None, **kwargs):  # noqa: ARG001
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        params = params or {}

        if parsed.path.endswith("/hydrometrie/referentiel/stations"):
            code = params.get("code_station") or query.get("code_station", [None])[0]
            if code is not None:
                row = station_rows.get(str(code))
                data = [row] if row is not None else []
                return _DummyResponse({"count": len(data), "data": data})
            data = list(station_rows.values())
            return _DummyResponse({"count": len(data), "data": data})

        if parsed.path.endswith("/hydrometrie/referentiel/sites"):
            code = params.get("code_site") or query.get("code_site", [None])[0]
            if code is not None:
                row = site_rows.get(str(code))
                data = [row] if row is not None else []
                return _DummyResponse({"count": len(data), "data": data})
            data = list(site_rows.values())
            return _DummyResponse({"count": len(data), "data": data})

        if parsed.path.endswith("/hydrometrie/obs_elab"):
            code = query.get("code_entite", [None])[0]
            data = list(obs_rows.get(str(code), []))
            return _DummyResponse({"count": len(data), "data": data})

        return _DummyResponse({"count": 0, "data": []}, status_code=404)

    monkeypatch.setattr(loaders_api_module.requests, "get", fake_get)

    return StationSet(
        variable="QmnJ",
        id=[sid1, sid2],
        source_mode="api",
        date_start="2024-01-01",
        date_end="2024-01-03",
        output=None,
        display=False,
    )


def _station_set_signature(stations: StationSet) -> dict:
    """Build a deterministic signature used in golden non-regression checks."""
    summary_df = stations.missing_data_summary.copy()
    summary_by_station = {}
    if not summary_df.empty and "station_id" in summary_df.columns:
        for _, row in summary_df.iterrows():
            sid = str(row["station_id"])
            summary_by_station[sid] = {
                "expected_days": int(row["expected_days"]),
                "actual_days": int(row["actual_days"]),
                "missing_days": int(row["missing_days"]),
                "completeness_pct": round(float(row["completeness_pct"]), 6),
            }

    station_payload = {}
    for sid in sorted(stations.stations.keys()):
        sdf = stations.stations[sid].data.copy()
        sdf["date_obs_elab"] = pd.to_datetime(sdf["date_obs_elab"], errors="coerce")
        values = pd.to_numeric(sdf["resultat_obs_elab"], errors="coerce")
        dates = sdf["date_obs_elab"].dropna()
        payload = {
            "n_rows": int(len(sdf)),
            "sum_resultat_obs_elab": round(float(values.fillna(0.0).sum()), 8),
            "first_date": None if dates.empty else dates.min().strftime("%Y-%m-%d"),
            "last_date": None if dates.empty else dates.max().strftime("%Y-%m-%d"),
        }
        if "specific_discharge" in sdf.columns:
            sd = pd.to_numeric(sdf["specific_discharge"], errors="coerce")
            payload["sum_specific_discharge"] = round(float(sd.fillna(0.0).sum()), 8)
        payload.update(summary_by_station.get(sid, {}))
        station_payload[sid] = payload

    total_missing_days = 0
    if not summary_df.empty and "missing_days" in summary_df.columns:
        total_missing_days = int(summary_df["missing_days"].sum())

    return {
        "station_ids": sorted(stations.stations.keys()),
        "total_rows": int(len(stations.data)),
        "total_missing_days": total_missing_days,
        "stations": station_payload,
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


def test_station_set_local_loading_from_exported_files(tmp_path: Path):
    """Load two local station files and compute completeness summary."""
    sid1 = "J111111101"
    sid2 = "J222222201"
    stations = _load_local_station_set(tmp_path)

    assert set(stations.stations.keys()) == {sid1, sid2}
    assert len(stations.data) == 5
    assert set(stations.metadata["station_id"].astype(str)) == {sid1, sid2}
    assert set(stations.stations_info["station_id"].astype(str)) == {sid1, sid2}

    summary = stations.missing_data_summary.set_index("station_id")
    assert int(summary.loc[sid1, "missing_days"]) == 0
    assert int(summary.loc[sid2, "missing_days"]) == 1

    station_two = stations.get_station(sid2)
    assert station_two.georeferencing["is_georeferenced"] is True
    assert station_two.station_position["wgs84"]["x"] == pytest.approx(-1.9)
    assert station_two.station_position["l93"]["x"] == pytest.approx(350000.0)


def test_station_set_api_loading_with_mocked_requests(monkeypatch: pytest.MonkeyPatch):
    """Load two stations in API mode with mocked HTTP responses."""
    sid1 = "J736422001"
    sid2 = "J751301001"
    stations = _load_api_station_set(monkeypatch)

    assert set(stations.stations.keys()) == {sid1, sid2}
    assert len(stations.data) == 5
    assert set(stations.data["station_id"].astype(str).unique()) == {sid1, sid2}

    sid1_data = stations.data[stations.data["station_id"] == sid1].sort_values("date_obs_elab")
    assert float(sid1_data.iloc[0]["resultat_obs_elab"]) == pytest.approx(1.0)
    assert "specific_discharge" in stations.data.columns

    summary = stations.missing_data_summary.set_index("station_id")
    assert int(summary.loc[sid1, "missing_days"]) == 0
    assert int(summary.loc[sid2, "expected_days"]) == 3
    assert int(summary.loc[sid2, "actual_days"]) == 2
    assert int(summary.loc[sid2, "missing_days"]) == 1


def test_station_set_loading_golden_non_regression(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    update_goldens: bool,
):
    """Non-regression check on deterministic local/api loading signatures."""
    local_stations = _load_local_station_set(tmp_path)
    api_stations = _load_api_station_set(monkeypatch)

    actual = {
        "local_basic": _station_set_signature(local_stations),
        "api_mocked_basic": _station_set_signature(api_stations),
    }

    if update_goldens:
        _write_json(STATION_SET_LOADING_GOLDEN_FILE, actual)
        return

    if not STATION_SET_LOADING_GOLDEN_FILE.exists():
        pytest.fail(
            f"Missing golden reference file: {STATION_SET_LOADING_GOLDEN_FILE}. "
            "Run tests with --update-goldens to generate it."
        )

    expected = _load_json(STATION_SET_LOADING_GOLDEN_FILE)
    assert expected == actual
