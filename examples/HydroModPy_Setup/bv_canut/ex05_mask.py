#!/usr/bin/env python
"""Ex05 — Spatial filtering with GeoJSON mask.

The hydrometry LOC contains 6 stations (5 in Canut + RENNES01 outside extent).
The piezometry LOC contains 6 piezometers (5 in Canut + RENNES_P01 outside).
The water_quality LOC contains 6 sites (5 in Canut + RENNES_WQ outside).

The GeoJSON mask filters and keeps only stations inside the extent.
"""

from __future__ import annotations

# %% Imports
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
MASK_PATH = DATA_DIR / "masks" / "canut_bbox.geojson"

BBOX_CANUT = (-1.70, 48.11, -1.66, 48.14)
PERIOD = (datetime(1990, 1, 1), datetime(1992, 12, 31))

store = DataStore(
    workspace_root=WS_ROOT,
    project_extent=BBOX_CANUT,
    project_period=PERIOD,
)

# %% Build configs — without mask (all stations)
cfg_hydro_all = HydrometryConfig(
    sources=[HydrometrySourceConfig(source="custom", path=DATA_DIR / "hydrometry")],
    date_start="1990-01-01",
    date_end="1992-12-31",
)
cfg_piezo_all = PiezometryConfig(
    sources=[PiezometrySourceConfig(source="custom", path=DATA_DIR / "piezometry")],
    date_start="1990-01-01",
    date_end="1992-12-31",
)
cfg_wq_all = WaterQualityConfig(
    sources=[WaterQualitySourceConfig(source="custom", path=DATA_DIR / "water_quality")],
)

# %% Build configs — with mask (spatial filtering)
cfg_hydro_mask = HydrometryConfig(
    sources=[HydrometrySourceConfig(
        source="custom",
        path=DATA_DIR / "hydrometry",
        mask_path=MASK_PATH,
    )],
    date_start="1990-01-01",
    date_end="1992-12-31",
)
cfg_piezo_mask = PiezometryConfig(
    sources=[PiezometrySourceConfig(
        source="custom",
        path=DATA_DIR / "piezometry",
        mask_path=MASK_PATH,
    )],
    date_start="1990-01-01",
    date_end="1992-12-31",
)
cfg_wq_mask = WaterQualityConfig(
    sources=[WaterQualitySourceConfig(
        source="custom",
        path=DATA_DIR / "water_quality",
        mask_path=MASK_PATH,
    )],
)

# Export the mask config to TOML
generate_toml_from_instances(
    {"hydrometry": cfg_hydro_mask, "piezometry": cfg_piezo_mask, "water_quality": cfg_wq_mask},
    output_path=BV_DIR / "ex05_mask.toml",
    exclude_defaults=True, exclude_none=True,
    comment="Ex05 — Spatial filtering with GeoJSON mask.\n"
            "Loads all stations, then filters by geographic extent.\n"
            "RENNES01 / RENNES_P01 / RENNES_WQ are outside the mask -> excluded.",
)

# =====================================================================
# HYDROMETRY
# =====================================================================

# %% Ex05a — Hydro without mask
print("=" * 60)
print("Ex05a — Hydro without mask (all stations)")
print("=" * 60)

records_all = store.load_hydrometry(cfg_hydro_all)

print(f"\n  {len(records_all)} stations (no mask):")
for r in records_all:
    loc = f"({r.location.x}, {r.location.y})" if r.location else "?"
    print(f"    {r.station_id:12s}  {loc}")

# %% Ex05b — Hydro with GeoJSON mask
print("\n" + "=" * 60)
print("Ex05b — Hydro with GeoJSON mask")
print("=" * 60)

try:
    records_mask = store.load_hydrometry(cfg_hydro_mask)
    print(f"\n  {len(records_mask)} stations (with mask):")
    for r in records_mask:
        loc = f"({r.location.x}, {r.location.y})" if r.location else "?"
        print(f"    {r.station_id:12s}  {loc}")

    excluded = set(r.station_id for r in records_all) - set(r.station_id for r in records_mask)
    if excluded:
        print(f"\n  Hydro stations excluded by mask: {excluded}")
except ImportError:
    print("\n  geopandas required for spatial filtering.")
    print("  pip install geopandas")

# =====================================================================
# PIEZOMETRY
# =====================================================================

# %% Ex05c — Piezo without mask
print("\n" + "=" * 60)
print("Ex05c — Piezo without mask (all piezometers)")
print("=" * 60)

records_piezo_all = store.load_piezometry(cfg_piezo_all)

print(f"\n  {len(records_piezo_all)} piezometers (no mask):")
for r in records_piezo_all:
    loc = f"({r.location.x}, {r.location.y})" if r.location else "?"
    print(f"    {r.station_id:12s}  {loc}")

# %% Ex05d — Piezo with GeoJSON mask
print("\n" + "=" * 60)
print("Ex05d — Piezo with GeoJSON mask")
print("=" * 60)

try:
    records_piezo_mask = store.load_piezometry(cfg_piezo_mask)
    print(f"\n  {len(records_piezo_mask)} piezometers (with mask):")
    for r in records_piezo_mask:
        loc = f"({r.location.x}, {r.location.y})" if r.location else "?"
        print(f"    {r.station_id:12s}  {loc}")

    excluded_piezo = set(r.station_id for r in records_piezo_all) - set(r.station_id for r in records_piezo_mask)
    if excluded_piezo:
        print(f"\n  Piezometers excluded by mask: {excluded_piezo}")
except ImportError:
    print("\n  geopandas required for spatial filtering.")
    print("  pip install geopandas")

# =====================================================================
# WATER QUALITY
# =====================================================================

# %% Ex05e — WQ without mask
print("\n" + "=" * 60)
print("Ex05e — WQ without mask (all sites)")
print("=" * 60)

records_wq_all = store.load_water_quality(cfg_wq_all)

print(f"\n  {len(records_wq_all)} WQ sites (no mask):")
for r in records_wq_all:
    loc = f"({r.location.x}, {r.location.y})" if r.location else "?"
    print(f"    {r.station_id:12s}  {loc}")

# %% Ex05f — WQ with GeoJSON mask
print("\n" + "=" * 60)
print("Ex05f — WQ with GeoJSON mask")
print("=" * 60)

try:
    records_wq_mask = store.load_water_quality(cfg_wq_mask)
    print(f"\n  {len(records_wq_mask)} WQ sites (with mask):")
    for r in records_wq_mask:
        loc = f"({r.location.x}, {r.location.y})" if r.location else "?"
        print(f"    {r.station_id:12s}  {loc}")

    excluded_wq = set(r.station_id for r in records_wq_all) - set(r.station_id for r in records_wq_mask)
    if excluded_wq:
        print(f"\n  WQ sites excluded by mask: {excluded_wq}")
except ImportError:
    print("\n  geopandas required for spatial filtering.")
    print("  pip install geopandas")
