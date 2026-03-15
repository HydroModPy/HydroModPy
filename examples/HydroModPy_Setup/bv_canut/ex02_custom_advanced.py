#!/usr/bin/env python
"""Ex02 — Advanced custom: unit conversion + constant stations.

Demonstrates:
- Hydrometry : CANUT01 (m3/s), CANUT_LS (L/s -> m3/s), CONST01 (constant)
- Piezometry : PIEZO01 (m), PIEZO_CM (cm -> m), PIEZO_CONST (constant)
- Water quality : WQ_NO3 (mg/L), WQ_UGL (ug/L -> mg/L), WQ_CONST (constant)
"""

from __future__ import annotations

# %% Imports
import os
from datetime import datetime
from pathlib import Path

from hydromodpy.data_managers.variables.hydrometry.config import HydrometryConfig, HydrometrySourceConfig
from hydromodpy.data_managers.variables.piezometry.config import PiezometryConfig, PiezometrySourceConfig
from hydromodpy.data_managers.variables.water_quality.config import WaterQualityConfig, WaterQualitySourceConfig
from hydromodpy.config.generate_toml import generate_toml_from_instances
from hydromodpy.data_managers.store import DataStore

# %% Paths and geographic context
BV_DIR = Path(__file__).resolve().parent
WS_ROOT = BV_DIR.parent
os.chdir(BV_DIR)
DATA_DIR = WS_ROOT / "data"

BBOX_CANUT = (-1.70, 48.11, -1.66, 48.14)
PERIOD = (datetime(1990, 1, 1), datetime(1990, 12, 31))

store = DataStore(
    workspace_root=WS_ROOT,
    project_extent=BBOX_CANUT,
    project_period=PERIOD,
)

# %% Build configs and export to TOML
cfg_hydro = HydrometryConfig(
    sources=[HydrometrySourceConfig(
        source="custom",
        path=DATA_DIR / "hydrometry",
        station_ids=["CANUT01", "CANUT_LS", "CONST01"],
    )],
    date_start="1990-01-01",
    date_end="1990-12-31",
)
cfg_piezo = PiezometryConfig(
    sources=[PiezometrySourceConfig(
        source="custom",
        path=DATA_DIR / "piezometry",
        station_ids=["PIEZO01", "PIEZO_CM", "PIEZO_CONST"],
    )],
    date_start="1990-01-01",
    date_end="1990-12-31",
)
cfg_wq = WaterQualityConfig(
    sources=[WaterQualitySourceConfig(
        source="custom",
        path=DATA_DIR / "water_quality",
        station_ids=["WQ_NO3", "WQ_UGL", "WQ_CONST"],
    )],
)

generate_toml_from_instances(
    {"hydrometry": cfg_hydro, "piezometry": cfg_piezo, "water_quality": cfg_wq},
    output_path=BV_DIR / "ex02_custom_advanced.toml",
    exclude_defaults=True, exclude_none=True,
    comment="Ex02 — Advanced custom: unit conversion + constant stations.\n"
            "Hydrometry: CANUT01 (m3/s), CANUT_LS (L/s -> m3/s), CONST01 (constant)\n"
            "Piezometry: PIEZO01 (m), PIEZO_CM (cm -> m), PIEZO_CONST (constant)\n"
            "Water quality: WQ_NO3 (mg/L), WQ_UGL (ug/L -> mg/L), WQ_CONST (constant)",
)

# %% Hydrometry
print("=" * 60)
print("Ex02a — Unit conversion (hydrometry)")
print("=" * 60)

records = store.load_hydrometry(cfg_hydro)

print(f"\n  {len(records)} stations loaded:")
for r in records:
    val = r.data["value"].iloc[0]
    print(f"    {r.station_id:16s}: {r.n_records:5d} pts, "
          f"val[0]={val:.6f} {r.unit}, constant={r.is_constant}")

print("\n  --- Conversion check (hydro) ---")
for r in records:
    if r.station_id == "CANUT_LS":
        val = r.data["value"].iloc[0]
        print(f"  CANUT_LS: first value = {val:.6f} m3/s")
        print(f"  (source CSV in L/s: 55.0 L/s -> expected 0.055 m3/s)")
    if r.station_id == "CANUT01":
        val = r.data["value"].iloc[0]
        print(f"  CANUT01:  first value = {val:.6f} m3/s (already in m3/s)")
    if r.station_id == "CONST01":
        val = r.data["value"].iloc[0]
        print(f"  CONST01:  first value = {val:.6f} m3/s (constant, "
              f"{r.n_records} pts expanded)")

# %% Piezometry
print("\n" + "=" * 60)
print("Ex02b — Unit conversion (piezometry)")
print("=" * 60)

records_piezo = store.load_piezometry(cfg_piezo)

print(f"\n  {len(records_piezo)} piezometers loaded:")
for r in records_piezo:
    val = r.data["value"].iloc[0]
    print(f"    {r.station_id:16s}: {r.n_records:5d} pts, "
          f"val[0]={val:.4f} {r.unit}, constant={r.is_constant}")

print("\n  --- Conversion check (piezo) ---")
for r in records_piezo:
    if r.station_id == "PIEZO_CM":
        val = r.data["value"].iloc[0]
        print(f"  PIEZO_CM:    first value = {val:.4f} m")
        print(f"  (source CSV in cm -> expected ~42-45 m)")
    if r.station_id == "PIEZO01":
        val = r.data["value"].iloc[0]
        print(f"  PIEZO01:     first value = {val:.4f} m (already in m)")
    if r.station_id == "PIEZO_CONST":
        val = r.data["value"].iloc[0]
        print(f"  PIEZO_CONST: first value = {val:.4f} m (constant, "
              f"{r.n_records} pts expanded)")

# %% Water quality
print("\n" + "=" * 60)
print("Ex02c — Unit conversion (water quality)")
print("=" * 60)

records_wq = store.load_water_quality(cfg_wq)

print(f"\n  {len(records_wq)} WQ sites loaded:")
for r in records_wq:
    val = r.data["value"].iloc[0]
    print(f"    {r.station_id:16s}: {r.n_records:5d} pts, "
          f"val[0]={val:.2f} {r.unit}, constant={r.is_constant}")

print("\n  --- Conversion check (WQ) ---")
for r in records_wq:
    if r.station_id == "WQ_UGL":
        val = r.data["value"].iloc[0]
        print(f"  WQ_UGL:   first value = {val:.2f} mg/L")
        print(f"  (source CSV in ug/L -> expected ~25 mg/L)")
    if r.station_id == "WQ_NO3":
        val = r.data["value"].iloc[0]
        print(f"  WQ_NO3:   first value = {val:.2f} mg/L (already in mg/L)")
    if r.station_id == "WQ_CONST":
        val = r.data["value"].iloc[0]
        print(f"  WQ_CONST: first value = {val:.2f} mg/L (constant, "
              f"{r.n_records} pts expanded)")
