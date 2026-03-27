#!/usr/bin/env python
"""Ex03 — Hub'Eau API: discharge, piezometric levels, water quality.

Demonstrates:
- Hydrometry : loading by station code + bbox discovery
- Piezometry : loading by BSS code + bbox discovery + nearest
- Water quality : loading by station code + nearest

Requires internet connection.
API results are persisted in data/<variable>/ and registered in catalog.db.
"""

from __future__ import annotations

# %% Imports
import os
from datetime import datetime
from pathlib import Path

from hydromodpy.data.variables.hydrometry.config import (
    HydrometryConfig,
    HydrometrySourceConfig,
)
from hydromodpy.data.variables.piezometry.config import (
    PiezometryConfig,
    PiezometrySourceConfig,
)
from hydromodpy.data.variables.water_quality.config import (
    WaterQualityConfig,
    WaterQualitySourceConfig,
)
from hydromodpy.config.generate_toml import generate_toml_from_instances
from hydromodpy.data.store import DataStore

# %% Paths and geographic context
BV_DIR = Path(__file__).resolve().parent
WS_ROOT = BV_DIR.parent.parent
os.chdir(BV_DIR)
DATA_DIR = WS_ROOT / "data"

# Extended bbox around Rennes to find Hub'Eau stations
BBOX_RENNES = (-1.80, 48.05, -1.55, 48.25)
PERIOD = (datetime(2022, 1, 1), datetime(2022, 3, 31))

store = DataStore(
    workspace_root=WS_ROOT,
    project_extent=BBOX_RENNES,
    project_period=PERIOD,
)

# %% Build configs and export to TOML
cfg_hydro = HydrometryConfig(
    sources=[HydrometrySourceConfig(
        source="hubeau",
        product="QmnJ",
        station_ids=["J709063002"],
    )],
    date_start="2022-01-01",
    date_end="2022-03-31",
)
cfg_piezo = PiezometryConfig(
    sources=[PiezometrySourceConfig(
        source="hubeau",
        product="level",
        station_ids=["03175X0338/PZ"],
    )],
    date_start="2022-01-01",
    date_end="2022-03-31",
)
cfg_wq = WaterQualityConfig(
    sources=[WaterQualitySourceConfig(
        source="hubeau",
        site_type="river",
        station_ids=["04204300"],
        parameters=["pH", "Nitrates"],
    )],
)

generate_toml_from_instances(
    {"hydrometry": cfg_hydro, "piezometry": cfg_piezo, "water_quality": cfg_wq},
    output_path=BV_DIR / "ex03_api.toml",
    exclude_defaults=True, exclude_none=True,
    comment="Ex03 — Hub'Eau API: discharge, piezometric levels, water quality.\n"
            "Requires internet connection.\n"
            "\n"
            "Hydrometry : J709063002 = Vilaine at Cesson-Sevigne\n"
            "Piezometry : 03175X0338/PZ = Saint-Jacques-de-la-Lande (Rennes aquifer)\n"
            "Water quality : 04204300 = Rennes area river station",
)

# =====================================================================
# HYDROMETRY
# =====================================================================

# %% Ex03a — Hydro by station code (from config)
print("=" * 60)
print("Ex03a — Hub'Eau hydro by station code")
print("=" * 60)

try:
    records = store.load_hydrometry(cfg_hydro)
    print(f"\n  {len(records)} stations loaded:")
    for r in records:
        print(f"    {r.station_id}: {r.n_records} pts, unit={r.unit}")
        if r.location:
            print(f"      -> ({r.location.x:.4f}, {r.location.y:.4f}) "
                  f"{r.location.crs}")
except Exception as exc:
    print(f"\n  API failure (normal if offline): {exc}")

# %% Ex03b — Hydro by bbox (automatic discovery)
print("\n" + "=" * 60)
print("Ex03b — Hub'Eau hydro by geographic extent (bbox)")
print("=" * 60)

cfg_bbox = HydrometryConfig(
    sources=[
        HydrometrySourceConfig(
            source="hubeau",
            product="QmnJ",
            extent="watershed",
        )
    ],
    date_start="2022-01-01",
    date_end="2022-03-31",
)

try:
    records_bbox = store.load_hydrometry(cfg_bbox)
    print(f"\n  {len(records_bbox)} stations discovered in bbox:")
    for r in records_bbox:
        loc = f"({r.location.x:.4f}, {r.location.y:.4f})" if r.location else "?"
        print(f"    {r.station_id}: {r.n_records} pts  {loc}")
except Exception as exc:
    print(f"\n  API failure (normal if offline): {exc}")

# =====================================================================
# PIEZOMETRY
# =====================================================================

# %% Ex03c — Piezo by BSS code (from config)
print("\n" + "=" * 60)
print("Ex03c — Hub'Eau piezo by BSS code")
print("=" * 60)

try:
    records_piezo = store.load_piezometry(cfg_piezo)
    print(f"\n  {len(records_piezo)} piezometers loaded:")
    for r in records_piezo:
        print(f"    {r.station_id}: {r.n_records} pts, unit={r.unit}, var={r.variable}")
        if r.location:
            print(f"      -> ({r.location.x:.4f}, {r.location.y:.4f}) "
                  f"{r.location.crs}")
except Exception as exc:
    print(f"\n  API failure (normal if offline): {exc}")

# %% Ex03d — Piezo by bbox (automatic discovery)
print("\n" + "=" * 60)
print("Ex03d — Hub'Eau piezo by geographic extent (bbox)")
print("=" * 60)

cfg_piezo_bbox = PiezometryConfig(
    sources=[
        PiezometrySourceConfig(
            source="hubeau",
            product="level",
            extent="watershed",
        )
    ],
    date_start="2022-01-01",
    date_end="2022-03-31",
)

try:
    records_piezo_bbox = store.load_piezometry(cfg_piezo_bbox)
    print(f"\n  {len(records_piezo_bbox)} piezometers discovered in bbox:")
    for r in records_piezo_bbox:
        loc = f"({r.location.x:.4f}, {r.location.y:.4f})" if r.location else "?"
        print(f"    {r.station_id}: {r.n_records} pts  {loc}")
except Exception as exc:
    print(f"\n  API failure (normal if offline): {exc}")

# %% Ex03e — Piezo by bbox + nearest (closest piezometer to centroid)
print("\n" + "=" * 60)
print("Ex03e — Hub'Eau piezo: nearest (closest to centroid)")
print("=" * 60)

cfg_piezo_nearest = PiezometryConfig(
    sources=[
        PiezometrySourceConfig(
            source="hubeau",
            product="level",
            extent="watershed",
            nearest=True,
        )
    ],
    date_start="2022-01-01",
    date_end="2022-03-31",
)

try:
    records_nearest = store.load_piezometry(cfg_piezo_nearest)
    print(f"\n  {len(records_nearest)} piezometer(s) (nearest):")
    for r in records_nearest:
        loc = f"({r.location.x:.4f}, {r.location.y:.4f})" if r.location else "?"
        print(f"    {r.station_id}: {r.n_records} pts  {loc}")
except Exception as exc:
    print(f"\n  API failure (normal if offline): {exc}")

# =====================================================================
# WATER QUALITY
# =====================================================================

# %% Ex03f — WQ by station code (from config)
print("\n" + "=" * 60)
print("Ex03f — Hub'Eau water quality by station code")
print("=" * 60)

try:
    records_wq = store.load_water_quality(cfg_wq)
    print(f"\n  {len(records_wq)} WQ records loaded (1 per station x parameter):")
    for r in records_wq:
        print(f"    {r.station_id} / {r.variable}: {r.n_records} pts, unit={r.unit}")
except Exception as exc:
    print(f"\n  API failure (normal if offline): {exc}")

# %% Ex03g — WQ by bbox + nearest (closest station to centroid)
print("\n" + "=" * 60)
print("Ex03g — Hub'Eau WQ: nearest (closest to centroid)")
print("=" * 60)

cfg_wq_nearest = WaterQualityConfig(
    sources=[
        WaterQualitySourceConfig(
            source="hubeau",
            site_type="river",
            extent="watershed",
            nearest=True,
            parameters=["pH"],
        )
    ],
)

try:
    records_wq_nearest = store.load_water_quality(cfg_wq_nearest)
    print(f"\n  {len(records_wq_nearest)} WQ record(s) (nearest):")
    for r in records_wq_nearest:
        loc = f"({r.location.x:.4f}, {r.location.y:.4f})" if r.location else "?"
        print(f"    {r.station_id} / {r.variable}: {r.n_records} pts  {loc}")
except Exception as exc:
    print(f"\n  API failure (normal if offline): {exc}")

# %% Catalog contents after API loading
print("\n" + "=" * 60)
print("Ex03h — Catalog after API loading")
print("=" * 60)

for var in ("hydrometry", "piezometry", "water_quality"):
    info = store.cache_info(variable=var)
    print(f"\n  {len(info)} {var} entries in catalog.")

# %%
