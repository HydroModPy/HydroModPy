"""Manual test examples for water quality data manager.

Run with: python -m hydromodpy.data.variables.water_quality.run_examples
"""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd


def example_custom_csv():
    """Load water quality data from custom CSV files."""
    from hydromodpy.data.variables.water_quality.config import WaterQualitySourceConfig
    from hydromodpy.data.variables.water_quality.custom import load_custom

    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)

        # Location file (unit column required)
        pd.DataFrame(
            {
                "id": ["SITE01", "SITE02"],
                "x": [2.35, 2.40],
                "y": [48.85, 48.90],
                "crs": ["EPSG:4326", "EPSG:4326"],
                "unit": ["mg/L", "mg/L"],
            }
        ).to_csv(d / "waterquality_custom_LOC.csv", index=False)

        # Chronicle files
        dates = pd.date_range("2020-01-01", "2020-06-30", freq="W")
        for sid, val in [("SITE01", 7.2), ("SITE02", 6.8)]:
            pd.DataFrame(
                {
                    "datetime": dates,
                    "value": val,
                }
            ).to_csv(d / f"waterquality_custom_{sid}_20200101_20200630_W.csv", index=False)

        cfg = WaterQualitySourceConfig(source="custom", path=d)
        period = (datetime(2020, 1, 1), datetime(2020, 6, 30))
        records = load_custom(cfg, project_period=period)

        print(f"\n--- Custom CSV: {len(records)} records ---")
        for r in records:
            print(f"  {r.station_id}: {len(r.data)} rows, unit={r.unit}")


def example_custom_constant():
    """Load water quality with a single-line CSV (constant value)."""
    from hydromodpy.data.variables.water_quality.config import WaterQualitySourceConfig
    from hydromodpy.data.variables.water_quality.custom import load_custom

    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)

        pd.DataFrame(
            {
                "id": ["SITE01"],
                "x": [2.35],
                "y": [48.85],
                "crs": ["EPSG:4326"],
                "unit": ["mg/L"],
            }
        ).to_csv(d / "waterquality_custom_LOC.csv", index=False)

        pd.DataFrame({"datetime": ["2020-01-01"], "value": [7.0]}).to_csv(
            d / "waterquality_custom_SITE01_20200101_20201231_D.csv", index=False
        )

        cfg = WaterQualitySourceConfig(source="custom", path=d)
        period = (datetime(2020, 1, 1), datetime(2020, 12, 31))
        records = load_custom(cfg, project_period=period)

        print(f"\n--- Constant: {len(records)} records ---")
        for r in records:
            print(f"  {r.station_id}: constant={r.is_constant}, rows={len(r.data)}")


def example_hubeau_river_api():
    """Fetch river water quality data from Hub'Eau API."""
    from hydromodpy.data.variables.water_quality.apis.hubeau import fetch

    records = fetch(
        site_type="river",
        station_ids=["05047200"],
        date_start=datetime(2020, 1, 1),
        date_end=datetime(2020, 3, 31),
    )

    print(f"\n--- Hub'Eau River: {len(records)} records ---")
    for r in records:
        print(f"  {r.station_id} / {r.variable}: {len(r.data)} rows, unit={r.unit}")


if __name__ == "__main__":
    print("=" * 60)
    print("Water Quality Examples")
    print("=" * 60)

    example_custom_csv()
    example_custom_constant()

    try:
        example_hubeau_river_api()
    except Exception as exc:
        print(f"\n--- Hub'Eau API failed (need network): {exc} ---")
