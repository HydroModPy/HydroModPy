#!/usr/bin/env python
"""Ex04 — Mixed sources: custom CSV + Hub'Eau API.

Realistic case: local constant station (boundary condition)
+ reference data from the Hub'Eau API.
Tests hydrometry, piezometry AND water_quality with mixed sources.

Requires internet connection for Hub'Eau sources.
API results are persisted in data/<variable>/ and registered in catalog.db.
"""

from __future__ import annotations

# %% Imports
import os
from datetime import datetime
from pathlib import Path

from hydromodpy.data.variables.hydrometry.config import HydrometryConfig, HydrometrySourceConfig
from hydromodpy.data.variables.piezometry.config import PiezometryConfig, PiezometrySourceConfig
from hydromodpy.data.variables.water_quality.config import WaterQualityConfig, WaterQualitySourceConfig
from hydromodpy.config.generate_toml import generate_toml_from_instances
from hydromodpy.data.store import DataStore

# %% Paths and geographic context
BV_DIR = Path(__file__).resolve().parent
WS_ROOT = BV_DIR.parent.parent
os.chdir(BV_DIR)
DATA_DIR = WS_ROOT / "data"

BBOX_RENNES = (-1.80, 48.05, -1.55, 48.25)
PERIOD = (datetime(2022, 1, 1), datetime(2022, 3, 31))

store = DataStore(
    workspace_root=WS_ROOT,
    project_extent=BBOX_RENNES,
    project_period=PERIOD,
)

# %% Build configs and export to TOML
cfg_hydro = HydrometryConfig(
    sources=[
        HydrometrySourceConfig(
            source="custom",
            path=DATA_DIR / "hydrometry",
            station_ids=["CONST01"],
        ),
        HydrometrySourceConfig(
            source="hubeau",
            product="QmnJ",
            station_ids=["J709063002"],
        ),
    ],
    date_start="2022-01-01",
    date_end="2022-03-31",
)
cfg_piezo = PiezometryConfig(
    sources=[
        PiezometrySourceConfig(
            source="custom",
            path=DATA_DIR / "piezometry",
            station_ids=["PIEZO_CONST"],
        ),
        PiezometrySourceConfig(
            source="hubeau",
            product="level",
            station_ids=["03175X0338/PZ"],
        ),
    ],
    date_start="2022-01-01",
    date_end="2022-03-31",
)
cfg_wq = WaterQualityConfig(
    sources=[
        WaterQualitySourceConfig(
            source="custom",
            path=DATA_DIR / "water_quality",
            station_ids=["WQ_CONST"],
        ),
        WaterQualitySourceConfig(
            source="hubeau",
            site_type="river",
            station_ids=["04204300"],
            parameters=["pH"],
        ),
    ],
)

generate_toml_from_instances(
    {"hydrometry": cfg_hydro, "piezometry": cfg_piezo, "water_quality": cfg_wq},
    output_path=BV_DIR / "ex04_mixed.toml",
    exclude_defaults=True, exclude_none=True,
    comment="Ex04 — Mixed sources: custom CSV + Hub'Eau API.\n"
            "Combines local data and API data.\n"
            "Requires internet connection for Hub'Eau sources.",
)

# %% Mixed hydrometry
print("=" * 60)
print("Ex04a — Mixed hydrometry: custom + Hub'Eau")
print("=" * 60)

print(f"\n  {len(cfg_hydro.sources)} hydro sources configured:")
for i, src in enumerate(cfg_hydro.sources):
    print(f"    Source {i + 1}: {src.source}"
          + (f" (station_ids={src.station_ids})" if src.station_ids else "")
          + (f" (product={src.product})" if src.product else ""))

try:
    records = store.load_hydrometry(cfg_hydro)
except Exception as exc:
    print(f"\n  API failure (normal if offline): {exc}")
    records = []

print(f"\n  {len(records)} hydro stations loaded:")
for r in records:
    origin = "CUSTOM" if r.source == "custom" else "API"
    print(f"    [{origin:6s}] {r.station_id:14s}: {r.n_records:5d} pts, "
          f"unit={r.unit}, constant={r.is_constant}")

# %% Mixed piezometry
print("\n" + "=" * 60)
print("Ex04b — Mixed piezometry: custom + Hub'Eau")
print("=" * 60)

print(f"\n  {len(cfg_piezo.sources)} piezo sources configured:")
for i, src in enumerate(cfg_piezo.sources):
    print(f"    Source {i + 1}: {src.source}"
          + (f" (station_ids={src.station_ids})" if src.station_ids else "")
          + (f" (product={src.product})" if src.product else ""))

try:
    records_piezo = store.load_piezometry(cfg_piezo)
except Exception as exc:
    print(f"\n  API failure (normal if offline): {exc}")
    records_piezo = []

print(f"\n  {len(records_piezo)} piezometers loaded:")
for r in records_piezo:
    origin = "CUSTOM" if r.source == "custom" else "API"
    print(f"    [{origin:6s}] {r.station_id:20s}: {r.n_records:5d} pts, "
          f"unit={r.unit}, constant={r.is_constant}")

# %% Mixed water quality
print("\n" + "=" * 60)
print("Ex04c — Mixed water quality: custom + Hub'Eau")
print("=" * 60)

print(f"\n  {len(cfg_wq.sources)} WQ sources configured:")
for i, src in enumerate(cfg_wq.sources):
    print(f"    Source {i + 1}: {src.source}"
          + (f" (station_ids={src.station_ids})" if src.station_ids else "")
          + (f" (parameters={src.parameters})" if src.parameters else ""))

try:
    records_wq = store.load_water_quality(cfg_wq)
except Exception as exc:
    print(f"\n  API failure (normal if offline): {exc}")
    records_wq = []

print(f"\n  {len(records_wq)} WQ records loaded:")
for r in records_wq:
    origin = "CUSTOM" if r.source == "custom" else "API"
    print(f"    [{origin:6s}] {r.station_id:14s} / {r.variable:20s}: "
          f"{r.n_records:5d} pts, unit={r.unit}")
