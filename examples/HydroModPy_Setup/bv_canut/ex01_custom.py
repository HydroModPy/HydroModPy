#!/usr/bin/env python
"""Ex01 — Basic custom loading from CSV files.

Loads chronicles from data/{hydrometry,piezometry,water_quality}/:
- All stations (6 hydro + 6 piezo + 6 WQ in LOC files)
- Constant stations, gaps, unit conversions
- Filtering by station_ids (programmatic)
- Completeness report
"""
# %%
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from hydromodpy.data_managers.hydrometry.config import (
    HydrometryConfig,
    HydrometrySourceConfig,
)
from hydromodpy.data_managers.piezometry.config import (
    PiezometryConfig,
    PiezometrySourceConfig,
)
from hydromodpy.data_managers.water_quality.config import (
    WaterQualityConfig,
    WaterQualitySourceConfig,
)
from hydromodpy.config.generate_toml import generate_toml_from_instances
from hydromodpy.data_managers.store import DataStore

# %% Paths and geographic context
BV_DIR = Path(__file__).resolve().parent
WS_ROOT = BV_DIR.parent
os.chdir(BV_DIR)
DATA_DIR = WS_ROOT / "data"

BBOX_CANUT = (-1.70, 48.11, -1.66, 48.14)
PERIOD = (datetime(1990, 1, 1), datetime(1992, 12, 31))

store = DataStore(
    workspace_root=WS_ROOT,
    project_extent=BBOX_CANUT,
    project_period=PERIOD,
)

# %% Build configs and export to TOML
cfg_hydro = HydrometryConfig(
    sources=[HydrometrySourceConfig(source="custom", path=DATA_DIR / "hydrometry")],
    date_start="1990-01-01",
    date_end="1992-12-31",
)
cfg_piezo = PiezometryConfig(
    sources=[PiezometrySourceConfig(source="custom", path=DATA_DIR / "piezometry")],
    date_start="1990-01-01",
    date_end="1992-12-31",
)
cfg_wq = WaterQualityConfig(
    sources=[WaterQualitySourceConfig(source="custom", path=DATA_DIR / "water_quality")],
)

generate_toml_from_instances(
    {"hydrometry": cfg_hydro, "piezometry": cfg_piezo, "water_quality": cfg_wq},
    output_path=BV_DIR / "ex01_custom.toml",
    exclude_defaults=True, exclude_none=True,
    comment="Ex01 — Basic custom loading from CSV files.\n"
            "Loads all stations from the custom data directories.\n"
            "Unit of each station is defined in the LOC file (column 'unit').",
)

# %% Load hydrometry — all stations
print("=" * 60)
print("Ex01a — All custom stations (hydrometry)")
print("=" * 60)

records = store.load_hydrometry(cfg_hydro)

print(f"\n  {len(records)} stations loaded:")
for r in records:
    info = f"    {r.station_id:12s}: {r.n_records:5d} pts, unit={r.unit}"
    if r.is_constant:
        info += f", CONSTANT (val={r.data['value'].iloc[0]:.4f})"
    if r.location:
        info += f"  ({r.location.x}, {r.location.y})"
    print(info)

# %% Load piezometry — all stations
print("\n" + "=" * 60)
print("Ex01b — All custom stations (piezometry)")
print("=" * 60)

records_piezo = store.load_piezometry(cfg_piezo)

print(f"\n  {len(records_piezo)} piezometers loaded:")
for r in records_piezo:
    info = f"    {r.station_id:12s}: {r.n_records:5d} pts, unit={r.unit}"
    if r.is_constant:
        info += f", CONSTANT (val={r.data['value'].iloc[0]:.2f})"
    if r.location:
        info += f"  ({r.location.x}, {r.location.y})"
    print(info)

# %% Load water_quality — all stations
print("\n" + "=" * 60)
print("Ex01c — All custom stations (water_quality)")
print("=" * 60)

records_wq = store.load_water_quality(cfg_wq)

print(f"\n  {len(records_wq)} WQ sites loaded:")
for r in records_wq:
    info = f"    {r.station_id:12s}: {r.n_records:5d} pts, unit={r.unit}"
    if r.is_constant:
        info += f", CONSTANT (val={r.data['value'].iloc[0]:.1f})"
    if r.location:
        info += f"  ({r.location.x}, {r.location.y})"
    print(info)

# %% Filtering by station_ids (programmatic, no TOML change needed)
print("\n" + "=" * 60)
print("Ex01d — Filtering by station_ids")
print("=" * 60)

cfg_filter = HydrometryConfig(sources=[
    HydrometrySourceConfig(
        source="custom",
        path=DATA_DIR / "hydrometry",
        station_ids=["CANUT01", "CANUT02", "RENNES01"],
    )
])
# %%
records_filter = store.load_hydrometry(cfg_filter)

print(f"\n  Hydro: {len(records_filter)} stations (filter CANUT01 + CANUT02 + RENNES01):")
for r in records_filter:
    print(f"    {r.station_id}: {r.n_records} pts")

cfg_piezo_filter = PiezometryConfig(sources=[
    PiezometrySourceConfig(
        source="custom",
        path=DATA_DIR / "piezometry",
        station_ids=["PIEZO01", "PIEZO02"],
    )
])
records_piezo_filter = store.load_piezometry(cfg_piezo_filter)

print(f"\n  Piezo: {len(records_piezo_filter)} stations (filter PIEZO01 + PIEZO02):")
for r in records_piezo_filter:
    print(f"    {r.station_id}: {r.n_records} pts")

cfg_wq_filter = WaterQualityConfig(sources=[
    WaterQualitySourceConfig(
        source="custom",
        path=DATA_DIR / "water_quality",
        station_ids=["WQ_NO3", "WQ_NO3B"],
    )
])
records_wq_filter = store.load_water_quality(cfg_wq_filter)

print(f"\n  WQ: {len(records_wq_filter)} stations (filter WQ_NO3 + WQ_NO3B):")
for r in records_wq_filter:
    print(f"    {r.station_id}: {r.n_records} pts")

# %% Completeness report
print("\n" + "=" * 60)
print("Ex01e — Completeness report")
print("=" * 60)

all_records = records + records_piezo + records_wq
report = store.get_completeness_report(all_records)
print()
print(report.to_string(index=False))

# %% Catalog contents
print("\n" + "=" * 60)
print("Ex01f — Catalog contents (catalog.db)")
print("=" * 60)

info = store.cache_info()
print(f"\n  {len(info)} entries registered in catalog.")
if not info.empty:
    print(info[["variable", "source", "station_id", "date_start", "date_end"]].to_string(index=False))

# %%
