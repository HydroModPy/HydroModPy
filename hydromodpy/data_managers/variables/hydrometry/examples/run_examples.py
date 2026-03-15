#!/usr/bin/env python
"""Hydrometry use-case examples — run standalone to test each scenario.

Usage::

    python -m hydromodpy.data_managers.variables.hydrometry.run_examples

Each function is an independent example that can be called directly.
"""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd


def example_custom_csv():
    """Load hydrometry from custom CSV files (location CSV + chronicles)."""
    print("\n=== Example: Custom CSV ===")
    from hydromodpy.data_managers.variables.hydrometry.config import HydrometrySourceConfig, HydrometryConfig
    from hydromodpy.data_managers.variables.hydrometry.manager import HydrometryManager
    from hydromodpy.data_managers.registry.catalog import DataCatalog

    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)

        # Create location file (unit column required)
        loc_df = pd.DataFrame({
            "id": ["ST001", "ST002"],
            "x": [-1.5, -1.6],
            "y": [48.1, 48.2],
            "crs": ["EPSG:4326", "EPSG:4326"],
            "name": ["Station Amont", "Station Aval"],
            "unit": ["m3/s", "m3/s"],
        })
        loc_df.to_csv(data_dir / "hydrometry_custom_LOC.csv", index=False)

        # Create chronicle files
        dates = pd.date_range("2020-01-01", "2020-12-31", freq="D")
        for sid, base_val in [("ST001", 2.5), ("ST002", 5.0)]:
            df = pd.DataFrame({
                "datetime": dates,
                "value": [base_val + i * 0.01 for i in range(len(dates))],
                "quality": "good",
            })
            df.to_csv(data_dir / f"hydrometry_custom_{sid}_20200101_20201231_D.csv", index=False)

        # Configure and load
        cfg = HydrometryConfig(sources=[
            HydrometrySourceConfig(
                source="custom",
                path=data_dir,
            )
        ])
        catalog = DataCatalog()  # in-memory
        mgr = HydrometryManager(
            config=cfg,
            catalog=catalog,
            project_period=(datetime(2020, 1, 1), datetime(2020, 12, 31)),
        )
        records = mgr.load()

        print(f"  Loaded {len(records)} records")
        for r in records:
            print(f"    {r.station_id}: {r.n_records} points, unit={r.unit}, "
                  f"[{r.date_start:%Y-%m-%d} → {r.date_end:%Y-%m-%d}]")
            if r.location:
                print(f"      Location: ({r.location.x}, {r.location.y}) {r.location.crs}")


def example_custom_csv_one_line():
    """Load hydrometry with a single-line CSV (constant value in file)."""
    print("\n=== Example: Custom CSV Single Line (Constant) ===")
    from hydromodpy.data_managers.variables.hydrometry.config import HydrometrySourceConfig, HydrometryConfig
    from hydromodpy.data_managers.variables.hydrometry.manager import HydrometryManager
    from hydromodpy.data_managers.registry.catalog import DataCatalog

    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)

        # Location (unit column required)
        pd.DataFrame({
            "id": ["CONST01"],
            "x": [-1.5],
            "y": [48.1],
            "crs": ["EPSG:4326"],
            "unit": ["m3/s"],
        }).to_csv(data_dir / "hydrometry_custom_LOC.csv", index=False)

        # Single-line chronicle → treated as constant
        pd.DataFrame({
            "datetime": ["2020-01-01"],
            "value": [4.2],
        }).to_csv(data_dir / "hydrometry_custom_CONST01_20200101_20201231_D.csv", index=False)

        cfg = HydrometryConfig(sources=[
            HydrometrySourceConfig(source="custom", path=data_dir)
        ])
        catalog = DataCatalog()
        mgr = HydrometryManager(
            config=cfg,
            catalog=catalog,
            project_period=(datetime(2020, 1, 1), datetime(2020, 12, 31)),
        )
        records = mgr.load()

        print(f"  Loaded {len(records)} records")
        for r in records:
            print(f"    {r.station_id}: {r.n_records} points, is_constant={r.is_constant}")


def example_custom_unit_conversion():
    """Load hydrometry with unit conversion (L/s → m³/s)."""
    print("\n=== Example: Custom with Unit Conversion ===")
    from hydromodpy.data_managers.variables.hydrometry.config import HydrometrySourceConfig, HydrometryConfig
    from hydromodpy.data_managers.variables.hydrometry.manager import HydrometryManager
    from hydromodpy.data_managers.registry.catalog import DataCatalog

    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)

        pd.DataFrame({
            "id": ["ST_LS"],
            "x": [-1.5],
            "y": [48.1],
            "crs": ["EPSG:4326"],
            "unit": ["L/s"],
        }).to_csv(data_dir / "hydrometry_custom_LOC.csv", index=False)

        # Value in L/s
        dates = pd.date_range("2020-01-01", "2020-01-10", freq="D")
        pd.DataFrame({
            "datetime": dates,
            "value": [1500.0] * len(dates),  # 1500 L/s = 1.5 m³/s
        }).to_csv(data_dir / "hydrometry_custom_ST_LS_20200101_20200110_D.csv", index=False)

        cfg = HydrometryConfig(sources=[
            HydrometrySourceConfig(
                source="custom",
                path=data_dir,
            )
        ])
        catalog = DataCatalog()
        mgr = HydrometryManager(
            config=cfg,
            catalog=catalog,
            project_period=(datetime(2020, 1, 1), datetime(2020, 1, 10)),
        )
        records = mgr.load()

        for r in records:
            val = r.data["value"].iloc[0]
            print(f"    {r.station_id}: value={val} {r.unit} (expected 1.5 m3/s)")


def example_hubeau_api():
    """Load hydrometry from Hub'Eau API (requires internet).

    Uses station J709063002 (Vilaine at Cesson-Sévigné) as a known example.
    """
    print("\n=== Example: Hub'Eau API ===")
    print("  (requires internet connection)")
    from hydromodpy.data_managers.variables.hydrometry.config import HydrometrySourceConfig, HydrometryConfig
    from hydromodpy.data_managers.variables.hydrometry.manager import HydrometryManager
    from hydromodpy.data_managers.registry.catalog import DataCatalog

    cfg = HydrometryConfig(sources=[
        HydrometrySourceConfig(
            source="hubeau",
            product="QmnJ",
            station_ids=["J709063002"],
        )
    ])
    catalog = DataCatalog()
    mgr = HydrometryManager(
        config=cfg,
        catalog=catalog,
        project_period=(datetime(2022, 1, 1), datetime(2022, 3, 31)),
    )

    try:
        records = mgr.load()
        print(f"  Loaded {len(records)} records")
        for r in records:
            print(f"    {r.station_id}: {r.n_records} points, unit={r.unit}")
            if r.location:
                print(f"      Location: ({r.location.x:.4f}, {r.location.y:.4f})")
    except Exception as exc:
        print(f"  API call failed (expected if offline): {exc}")


if __name__ == "__main__":
    example_custom_csv()
    example_custom_csv_one_line()
    example_custom_unit_conversion()
    example_hubeau_api()
    print("\n=== All examples done ===")
