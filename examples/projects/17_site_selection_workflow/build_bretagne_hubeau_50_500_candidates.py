"""Build Hub'Eau hydrometry candidates for the Bretagne 50-500 km2 example.

The script queries Hub'Eau reference endpoints, applies the same upstream
screening assumptions as the example, and writes two CSV files:

- an inventory of all matching Bretagne hydrometric sites;
- the full candidate table used by the DEM delineation example.
"""

from __future__ import annotations

import csv
import math
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pyproj import Transformer

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.data.common.administrative.france import bbox_for_regions
from hydromodpy.data.common.api_client import get_json

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"
INVENTORY_CSV = FIXTURES / "bretagne_hubeau_50_500_station_inventory.csv"
CANDIDATES_CSV = FIXTURES / "bretagne_hubeau_50_500_candidates.csv"

DEPARTMENT_CODES = {"22", "29", "35", "56"}
REGION_CODE = "53"
SURFACE_MIN_KM2 = 50.0
SURFACE_MAX_KM2 = 500.0
MIN_RECORD_YEARS = 5.0
MAX_STATION_TO_OUTLET_DISTANCE_KM = 1.0
REFERENCE_DATE = datetime(2025, 1, 1)

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
    "flow_station_id",
    "flow_station_label",
    "flow_station_source",
    "flow_station_x",
    "flow_station_y",
    "flow_station_crs",
    "flow_station_record_years",
    "station_to_outlet_distance_km",
    "station_inside_or_at_outlet",
    "major_dam_upstream",
    "major_withdrawal_upstream",
    "major_regulated_reach",
    "geology_class",
    "piezometer_id",
    "piezometer_label",
    "piezometer_source",
    "piezometer_x",
    "piezometer_y",
    "piezometer_crs",
    "piezometer_record_years",
    "piezometer_distance_km",
    "piezometer_inside_basin",
]

INVENTORY_COLUMNS = [
    "code_site",
    "code_station",
    "surface_bv_km2",
    "record_years",
    "x_l93",
    "y_l93",
    "station_to_outlet_distance_km",
    "influence_generale_site",
    "libelle_site",
]


@dataclass(frozen=True)
class HubeauCandidate:
    code_site: str
    code_station: str
    label: str
    x: float
    y: float
    station_x: float
    station_y: float
    surface_km2: float
    record_years: float
    station_distance_km: float
    influence_generale_site: object

    def to_selection_row(self) -> dict[str, object]:
        site_id = f"hubeau_{self.code_site}"
        return {
            "site_id": site_id,
            "candidate_id": self.code_station,
            "x": self.x,
            "y": self.y,
            "outlet_crs": "EPSG:2154",
            "area_km2": self.surface_km2,
            "status": "delineated",
            "site_label": _ascii(self.label),
            "source": "hubeau_hydrometrie",
            "source_feature_id": self.code_station,
            "flow_station_id": self.code_station,
            "flow_station_label": _ascii(self.label),
            "flow_station_source": "hubeau",
            "flow_station_x": self.station_x,
            "flow_station_y": self.station_y,
            "flow_station_crs": "EPSG:2154",
            "flow_station_record_years": round(self.record_years, 1),
            "station_to_outlet_distance_km": round(self.station_distance_km, 3),
            "station_inside_or_at_outlet": "true",
            "major_dam_upstream": "false",
            "major_withdrawal_upstream": "false",
            "major_regulated_reach": "false",
            "geology_class": "unknown",
        }

    def to_inventory_row(self) -> dict[str, object]:
        return {
            "code_site": self.code_site,
            "code_station": self.code_station,
            "surface_bv_km2": self.surface_km2,
            "record_years": round(self.record_years, 1),
            "x_l93": self.x,
            "y_l93": self.y,
            "station_to_outlet_distance_km": round(self.station_distance_km, 3),
            "influence_generale_site": self.influence_generale_site,
            "libelle_site": _ascii(self.label),
        }


def main() -> None:
    candidates = discover_candidates()
    _write_csv(INVENTORY_CSV, INVENTORY_COLUMNS, [item.to_inventory_row() for item in candidates])
    _write_csv(CANDIDATES_CSV, OUTPUT_COLUMNS, [item.to_selection_row() for item in candidates])
    print(f"Wrote {len(candidates)} inventory candidates to {INVENTORY_CSV}")
    print(f"Wrote {len(candidates)} selection candidates to {CANDIDATES_CSV}")


def discover_candidates() -> list[HubeauCandidate]:
    bbox = _bretagne_bbox_wgs84()
    payload = get_json(
        "https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/sites",
        params={"bbox": _bbox_param(bbox), "size": 10_000, "format": "json"},
    )
    candidates: list[HubeauCandidate] = []
    for site in payload.get("data", []):
        if not _site_passes_metadata_prefilter(site):
            continue
        station = _active_station_for_site(str(site["code_site"]))
        if station is None:
            continue
        candidate = _candidate_from_site_and_station(site, station)
        if candidate is not None:
            candidates.append(candidate)
    return sorted(candidates, key=lambda item: (item.x, item.y, item.code_site))


def _site_passes_metadata_prefilter(site: dict[str, Any]) -> bool:
    departments = {str(value) for value in site.get("code_departement") or []}
    regions = {str(value) for value in site.get("code_region") or []}
    if REGION_CODE not in regions or not (departments & DEPARTMENT_CODES):
        return False
    if site.get("grandeur_hydro") != "Q":
        return False
    surface = _float_or_none(site.get("surface_bv"))
    if surface is None or not (SURFACE_MIN_KM2 <= surface <= SURFACE_MAX_KM2):
        return False
    if site.get("influence_generale_site") not in {0, 1, None}:
        return False
    comment = " ".join(
        str(site.get(key) or "")
        for key in ("commentaire_influence_generale_site", "commentaire_site", "libelle_site")
    ).lower()
    return not any(token in comment for token in ("barrage", "edf", "retenue", "ecluse", "canal"))


def _active_station_for_site(code_site: str) -> dict[str, Any] | None:
    payload = get_json(
        "https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations",
        params={"code_site": code_site, "size": 20, "format": "json"},
    )
    active = [
        station
        for station in payload.get("data", [])
        if station.get("code_station") and station.get("en_service")
    ]
    if not active:
        return None
    return sorted(active, key=lambda station: str(station.get("code_station")))[0]


def _candidate_from_site_and_station(
    site: dict[str, Any],
    station: dict[str, Any],
) -> HubeauCandidate | None:
    site_x = _float_or_none(site.get("coordonnee_x_site"))
    site_y = _float_or_none(site.get("coordonnee_y_site"))
    station_x = _float_or_none(station.get("coordonnee_x_station"))
    station_y = _float_or_none(station.get("coordonnee_y_station"))
    surface = _float_or_none(site.get("surface_bv"))
    opened = _date_or_none(station.get("date_ouverture_station"))
    if None in {site_x, site_y, station_x, station_y, surface} or opened is None:
        return None
    record_years = (REFERENCE_DATE - opened).days / 365.25
    if record_years < MIN_RECORD_YEARS:
        return None
    distance_km = math.hypot(float(station_x) - float(site_x), float(station_y) - float(site_y)) / 1000
    if distance_km > MAX_STATION_TO_OUTLET_DISTANCE_KM:
        return None
    return HubeauCandidate(
        code_site=str(site["code_site"]),
        code_station=str(station["code_station"]),
        label=str(site.get("libelle_site") or station.get("libelle_station") or site["code_site"]),
        x=float(site_x),
        y=float(site_y),
        station_x=float(station_x),
        station_y=float(station_y),
        surface_km2=float(surface),
        record_years=float(record_years),
        station_distance_km=float(distance_km),
        influence_generale_site=site.get("influence_generale_site"),
    )


def _bretagne_bbox_wgs84() -> tuple[float, float, float, float]:
    bbox_2154 = bbox_for_regions(["Bretagne"], margin_m=0)
    transformer = Transformer.from_crs("EPSG:2154", "EPSG:4326", always_xy=True)
    points = [
        transformer.transform(x, y)
        for x, y in (
            (bbox_2154[0], bbox_2154[1]),
            (bbox_2154[0], bbox_2154[3]),
            (bbox_2154[2], bbox_2154[1]),
            (bbox_2154[2], bbox_2154[3]),
        )
    ]
    return (
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    )


def _bbox_param(bbox: tuple[float, float, float, float]) -> str:
    return ",".join(f"{value:.9f}" for value in bbox)


def _float_or_none(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _date_or_none(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        return datetime.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _write_csv(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _ascii(value: str) -> str:
    return (
        unicodedata.normalize("NFKD", value)
        .encode("ascii", "ignore")
        .decode("ascii")
        .replace("\u2019", "'")
    )


if __name__ == "__main__":
    main()
