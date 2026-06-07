"""Integration tests for the water quality Hub'Eau API (real HTTP requests).

Network-gated: opt in with ``HMP_RUN_HUBEAU_NETWORK_TESTS=1``.
"""

from __future__ import annotations

import os
from datetime import datetime

import pytest

from hydromodpy.data.variables.water_quality.apis.hubeau import fetch

pytestmark = [
    pytest.mark.network,
    pytest.mark.slow,
    pytest.mark.skipif(
        os.getenv("HMP_RUN_HUBEAU_NETWORK_TESTS") != "1",
        reason="Set HMP_RUN_HUBEAU_NETWORK_TESTS=1 to run Hub'Eau network tests.",
    ),
]


def test_river_quality_real_api():
    """Fetch real river quality data from Hub'Eau."""
    records = fetch(
        site_type="river",
        station_ids=["05047200"],
        date_start=datetime(2020, 1, 1),
        date_end=datetime(2020, 3, 31),
    )
    if not records:
        pytest.skip("No data returned for the requested river station/period.")
    for r in records:
        assert r.source == "hubeau"
        assert r.station_id == "05047200"
        assert r.has_data


def test_piezometer_quality_real_api():
    """Fetch real piezometer quality data from Hub'Eau."""
    records = fetch(
        site_type="piezometer",
        station_ids=["07285X0037/F"],
        date_start=datetime(2001, 1, 1),
        date_end=datetime(2001, 3, 31),
    )
    if not records:
        pytest.skip("No data returned for the requested piezometer station/period.")
    for r in records:
        assert r.source == "hubeau"
