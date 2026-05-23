"""Build reproducible AURA area-only candidates between 50 and 150 km2."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"
BASIN_DIR = FIXTURES / "basins"
CANDIDATES_CSV = FIXTURES / "aura_area_50_150_catchments.csv"

AREA_KM2_VALUES = [
    52.0,
    57.0,
    63.0,
    68.0,
    74.0,
    79.0,
    84.0,
    89.0,
    94.0,
    99.0,
    104.0,
    109.0,
    114.0,
    119.0,
    124.0,
    129.0,
    134.0,
    139.0,
    144.0,
    149.0,
]

OUTPUT_COLUMNS = [
    "site_id",
    "candidate_id",
    "x",
    "y",
    "outlet_crs",
    "area_km2",
    "status",
    "site_label",
    "source",
    "source_feature_id",
    "watershed_shp",
    "geology_class",
    "piezometer_count",
]

GEOLOGY_CLASSES = [
    "volcanic_basement",
    "crystalline_basement",
    "sedimentary_cover",
    "alluvial_plain",
]


def main() -> None:
    BASIN_DIR.mkdir(parents=True, exist_ok=True)
    rows = [_candidate_row(index, area_km2) for index, area_km2 in enumerate(AREA_KM2_VALUES, 1)]
    _write_csv(CANDIDATES_CSV, OUTPUT_COLUMNS, rows)
    print(f"Wrote {len(rows)} AURA area-only candidates to {CANDIDATES_CSV}")


def _candidate_row(index: int, area_km2: float) -> dict[str, object]:
    site_id = f"aura_area_50_150_{index:02d}"
    x, y = _candidate_center(index)
    basin_path = BASIN_DIR / f"{site_id}.geojson"
    _write_basin_geojson(basin_path, site_id=site_id, x=x, y=y, area_km2=area_km2)
    return {
        "site_id": site_id,
        "candidate_id": site_id,
        "x": x,
        "y": y,
        "outlet_crs": "EPSG:2154",
        "area_km2": area_km2,
        "status": "delineated",
        "site_label": f"AURA area-only {area_km2:.0f} km2",
        "source": "fixture_area_grid",
        "source_feature_id": site_id,
        "watershed_shp": f"basins/{site_id}.geojson",
        "geology_class": GEOLOGY_CLASSES[(index - 1) % len(GEOLOGY_CLASSES)],
        "piezometer_count": 0,
    }


def _candidate_center(index: int) -> tuple[float, float]:
    zero_based = index - 1
    column = zero_based % 5
    row = zero_based // 5
    return 842_000.0 + column * 19_500.0, 6_502_000.0 + row * 16_000.0


def _write_basin_geojson(path: Path, *, site_id: str, x: float, y: float, area_km2: float) -> None:
    half_side_m = math.sqrt(area_km2 * 1_000_000.0) / 2.0
    coordinates = [
        [x - half_side_m, y - half_side_m],
        [x + half_side_m, y - half_side_m],
        [x + half_side_m, y + half_side_m],
        [x - half_side_m, y + half_side_m],
        [x - half_side_m, y - half_side_m],
    ]
    collection = {
        "type": "FeatureCollection",
        "name": site_id,
        "hydromodpy_coordinate_crs": "EPSG:2154",
        "features": [
            {
                "type": "Feature",
                "id": site_id,
                "properties": {
                    "site_id": site_id,
                    "area_km2": area_km2,
                    "source": "fixture_area_grid",
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [coordinates],
                },
            }
        ],
    }
    path.write_text(json.dumps(collection, indent=2), encoding="utf-8")


def _write_csv(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
