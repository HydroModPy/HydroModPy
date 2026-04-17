"""Integration tests for water quality Hub'Eau API (real HTTP requests).

Run with: pytest -m integration -s tests/unit/data_managers/water_quality/
"""

from __future__ import annotations

from datetime import datetime

import pytest

from hydromodpy.data.variables.water_quality.apis.hubeau import fetch


pytestmark = [pytest.mark.integration, pytest.mark.slow]


def test_river_quality_real_api():
    """Fetch real river quality data from Hub'Eau."""
    try:
        records = fetch(
            site_type="river",
            station_ids=["05047200"],
            date_start=datetime(2020, 1, 1),
            date_end=datetime(2020, 3, 31),
        )
    except Exception as exc:
        pytest.skip(f"API call failed: {exc}")

    if not records:
        pytest.skip("No data returned")

    for r in records:
        assert r.source == "hubeau"
        assert r.station_id == "05047200"
        assert r.has_data
    print(f"River: {len(records)} parameter records")


def test_piezometer_quality_real_api():
    """Fetch real piezometer quality data from Hub'Eau."""
    try:
        records = fetch(
            site_type="piezometer",
            station_ids=["07285X0037/F"],
            date_start=datetime(2001, 1, 1),
            date_end=datetime(2001, 3, 31),
        )
    except Exception as exc:
        pytest.skip(f"API call failed: {exc}")

    if not records:
        pytest.skip("No data returned")

    for r in records:
        assert r.source == "hubeau"
    print(f"Piezometer: {len(records)} parameter records")
