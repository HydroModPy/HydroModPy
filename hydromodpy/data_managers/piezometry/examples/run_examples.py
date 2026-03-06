#!/usr/bin/env python
"""Piezometry use-case examples — run standalone to test each scenario.

Usage::

    python -m hydromodpy.data_managers.piezometry.run_examples
"""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd


def example_custom_csv():
    """Load piezometry from custom CSV files."""
    print("\n=== Example: Piezometry Custom CSV ===")
    from hydromodpy.data_managers.piezometry.config import PiezometrySourceConfig, PiezometryConfig
    from hydromodpy.data_managers.piezometry.manager import PiezometryManager
    from hydromodpy.data_managers.registry.catalog import DataCatalog

    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)

        # Location file
        pd.DataFrame({
            "id": ["BSS001", "BSS002"],
            "x": [-1.5, -1.6],
            "y": [48.1, 48.2],
            "crs": ["EPSG:4326", "EPSG:4326"],
            "name": ["Piézo Nord", "Piézo Sud"],
        }).to_csv(data_dir / "piezometry_custom_LOC.csv", index=False)

        # Chronicle files
        dates = pd.date_range("2020-01-01", "2020-12-31", freq="D")
        for sid, base_val in [("BSS001", 15.0), ("BSS002", 22.5)]:
            df = pd.DataFrame({
                "datetime": dates,
                "value": [base_val - i * 0.002 for i in range(len(dates))],
            })
            df.to_csv(data_dir / f"piezometry_custom_{sid}_20200101_20201231_D.csv", index=False)

        cfg = PiezometryConfig(sources=[
            PiezometrySourceConfig(source="custom", path=data_dir)
        ])
        catalog = DataCatalog()
        mgr = PiezometryManager(
            config=cfg,
            catalog=catalog,
            project_period=(datetime(2020, 1, 1), datetime(2020, 12, 31)),
        )
        records = mgr.load()

        print(f"  Loaded {len(records)} records")
        for r in records:
            print(f"    {r.station_id}: {r.n_records} points, variable={r.variable}")


def example_custom_constant():
    """Load piezometry with constant values."""
    print("\n=== Example: Piezometry Constant ===")
    from hydromodpy.data_managers.piezometry.config import PiezometrySourceConfig, PiezometryConfig
    from hydromodpy.data_managers.piezometry.manager import PiezometryManager
    from hydromodpy.data_managers.registry.catalog import DataCatalog

    cfg = PiezometryConfig(sources=[
        PiezometrySourceConfig(
            source="custom",
            fixed_values={"PZ_A": 18.0, "PZ_B": 25.0},
        )
    ])
    catalog = DataCatalog()
    mgr = PiezometryManager(
        config=cfg,
        catalog=catalog,
        project_period=(datetime(2020, 1, 1), datetime(2020, 3, 31)),
    )
    records = mgr.load()

    for r in records:
        print(f"    {r.station_id}: value={r.data['value'].iloc[0]} {r.unit}, is_constant={r.is_constant}")


def example_hubeau_api():
    """Load piezometry from Hub'Eau API (requires internet).

    Uses BSS code 07548X0009/F as a known example.
    """
    print("\n=== Example: Piezometry Hub'Eau API ===")
    print("  (requires internet connection)")
    from hydromodpy.data_managers.piezometry.config import PiezometrySourceConfig, PiezometryConfig
    from hydromodpy.data_managers.piezometry.manager import PiezometryManager
    from hydromodpy.data_managers.registry.catalog import DataCatalog

    cfg = PiezometryConfig(sources=[
        PiezometrySourceConfig(
            source="hubeau",
            product="level",
            station_ids=["07548X0009/F"],
        )
    ])
    catalog = DataCatalog()
    mgr = PiezometryManager(
        config=cfg,
        catalog=catalog,
        project_period=(datetime(2022, 1, 1), datetime(2022, 3, 31)),
    )

    try:
        records = mgr.load()
        print(f"  Loaded {len(records)} records")
        for r in records:
            print(f"    {r.station_id}: {r.n_records} points, variable={r.variable}")
    except Exception as exc:
        print(f"  API call failed (expected if offline): {exc}")


if __name__ == "__main__":
    example_custom_csv()
    example_custom_constant()
    example_hubeau_api()
    print("\n=== All examples done ===")
