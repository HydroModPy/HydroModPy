"""Minimal smoke tests for the Hub'Eau water‑quality APIs.

These tests are not meant to be exhaustive; they simply perform a real HTTP
query against the two endpoints and verify that the response can be parsed as
JSON and contains the expected structure.  Run them only when you have network
access; they are skipped if the requests library cannot reach the service.
"""

from __future__ import annotations

import requests
import pytest
from pathlib import Path


API_RIVER = "https://hubeau.eaufrance.fr/api/v2/qualite_rivieres/stations"
API_PZ = "https://hubeau.eaufrance.fr/api/v1/qualite_nappes/stations"

def _probe(url: str) -> dict:
    resp = requests.get(url, params={"size": 1, "format": "json"}, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    assert isinstance(payload, dict), "response is not a JSON object"
    assert "data" in payload, "missing 'data' key"
    assert isinstance(payload["data"], list), "'data' is not a list"
    return payload


@pytest.mark.integration
def test_river_quality_endpoint_returns_data():
    """Call the river quality station list and inspect its structure."""
    try:
        payload = _probe(API_RIVER)
    except requests.exceptions.HTTPError as exc:
        pytest.skip(f"river endpoint not available ({exc})")
    if not payload["data"]:
        pytest.skip("river endpoint returned no records")
    first = payload["data"][0]
    # print some information for manual inspection
    print("river sample keys:", list(first.keys()))
    assert isinstance(first, dict)


@pytest.mark.integration
def test_piezometer_quality_endpoint_returns_data():
    """Call the piezometer quality station list and inspect its structure."""
    payload = _probe(API_PZ)
    if not payload["data"]:
        pytest.skip("piezometer endpoint returned no records")
    first = payload["data"][0]
    print("piezometer sample keys:", list(first.keys()))
    assert isinstance(first, dict)

    # fetch a small chunk of quality data for this piezometer to inspect structure
    pz_id = first.get("code_bss") or first.get("id") or first.get("piezometer_id") or first.get("bss_id")
    if not pz_id:
        pytest.skip("no identifier found in station record")

    # the documentation indicates that the correct data service is
    # /v1/qualite_nappes/analyses.  we supply either bss_id (preferred) or
    # code_bss as query parameter.
    analyses_url = "https://hubeau.eaufrance.fr/api/v1/qualite_nappes/analyses"
    params = {"size": 5, "format": "json"}
    # try to use the short bss_id if available (strip slash part)
    if "/" in pz_id:
        params["code_bss"] = pz_id
    else:
        params["bss_id"] = pz_id

    try:
        resp = requests.get(analyses_url, params=params, timeout=30)
    except requests.exceptions.RequestException:
        pytest.skip("analyses endpoint request failed")

    if resp.status_code not in (200, 206):
        pytest.skip(f"analyses endpoint returned {resp.status_code}")

    try:
        data_payload = resp.json()
    except Exception:
        pytest.skip("analyses response not JSON")

    if not isinstance(data_payload, dict) or not data_payload.get("data"):
        pytest.skip("analyses endpoint returned no data")

    print(f"payload from analyses for {pz_id}:")
    print(data_payload)
    try:
        import pandas as pd
        df = pd.DataFrame(data_payload.get("data", []))
        print("dataframe columns:", df.columns.tolist())
        print(df.head())

        out_path = Path("outputs") / f"wq_sample_{pz_id}.csv"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_path, index=False)
        print(f"Saved sample CSV to: {out_path}")
    except ImportError:
        pass
