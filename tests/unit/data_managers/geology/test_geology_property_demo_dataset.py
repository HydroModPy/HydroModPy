from __future__ import annotations

import csv
from pathlib import Path

import geopandas as gpd


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "hydromodpy").is_dir():
            return parent
    raise RuntimeError("Cannot locate repository root from test path")


def test_demo_conductivity_csv_covers_bundled_geo1m_codes() -> None:
    repo_root = _repo_root()
    geology_dir = repo_root / "examples" / "data" / "geology"
    shp_path = geology_dir / "GEO1M.shp"
    csv_path = geology_dir / "geology_K_dummy_demo.csv"

    gdf = gpd.read_file(shp_path, columns=["CODE_LEG"])
    shp_keys = {str(value).strip() for value in gdf["CODE_LEG"].astype(str) if str(value).strip()}

    with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        csv_keys = {str(row["zone_key"]).strip() for row in reader if str(row["zone_key"]).strip()}

    missing = sorted(shp_keys - csv_keys)
    assert missing == []
    assert {"1321", "2041", "421", "SEA"}.issubset(csv_keys)
