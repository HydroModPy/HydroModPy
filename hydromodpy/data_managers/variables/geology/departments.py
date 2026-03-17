"""Department boundary detection for BRGM 1:50K geological maps.

Two strategies to resolve which departments overlap a bounding box:

1. **Primary — API Geo** (``https://geo.api.gouv.fr``):
   Official French government REST API. Receives a bbox in WGS 84,
   returns the list of department codes directly.  No file download.

2. **Fallback — cached GeoPackage**:
   If the API is unreachable (offline mode), a local GeoPackage of
   department boundaries is used.  It is downloaded once from the
   IGN GeoServices WFS endpoint and cached on disk.

Both sources are open data (Licence Ouverte / ETALAB v2.0).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Sequence

import geopandas as gpd
from shapely.geometry import box


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_departments_in_bbox(
    bbox: tuple[float, float, float, float],
    *,
    cache_dir: Path | None = None,
) -> list[str]:
    """Return department codes whose territory intersects *bbox*.

    Parameters
    ----------
    bbox : (xmin, ymin, xmax, ymax) in **EPSG:2154** (Lambert-93).
    cache_dir : optional directory for caching boundary files.

    Returns
    -------
    Sorted list of 3-character BRGM-style department codes
    (e.g. ``["022", "029", "035", "056"]``).
    """
    # Convert bbox from EPSG:2154 → WGS 84 for the API call.
    wgs84_bbox = _bbox_2154_to_wgs84(bbox)

    # --- Strategy 1: API Geo (fast, no files) ---
    try:
        codes = _query_api_geo(wgs84_bbox)
        if codes:
            return sorted(_to_brgm_codes(codes))
    except Exception:
        pass  # fall through to local strategy

    # --- Strategy 2: cached GeoPackage (offline mode) ---
    gpkg_path = _ensure_boundaries_gpkg(cache_dir)
    depts = gpd.read_file(str(gpkg_path))

    if depts.crs is not None and depts.crs.to_epsg() != 2154:
        depts = depts.to_crs("EPSG:2154")

    bbox_geom = box(*bbox)
    mask = depts.geometry.notna() & (~depts.geometry.is_empty)
    intersecting = depts.loc[mask & depts.geometry.intersects(bbox_geom)]

    code_col = _find_code_column(intersecting)
    raw_codes = [str(c).strip() for c in intersecting[code_col]]
    return sorted(_to_brgm_codes(raw_codes))


def department_code_to_brgm_code(dept_code: str) -> str:
    """Convert a department code to the BRGM ZIP filename suffix.

    BRGM uses 3-digit zero-padded codes: ``035`` for Ille-et-Vilaine.
    Corsica is ``02A`` / ``02B``.
    """
    code = str(dept_code).strip().upper()
    if code in ("2A", "2B"):
        return f"0{code}"
    if code in ("02A", "02B"):
        return code
    if code.isdigit():
        return code.zfill(3)
    return code


# ---------------------------------------------------------------------------
# Strategy 1 — API Geo (geo.api.gouv.fr)
# ---------------------------------------------------------------------------

def _bbox_2154_to_wgs84(
    bbox: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """Reproject a bbox from EPSG:2154 to EPSG:4326."""
    from pyproj import Transformer

    t = Transformer.from_crs("EPSG:2154", "EPSG:4326", always_xy=True)
    x1, y1 = t.transform(bbox[0], bbox[1])
    x2, y2 = t.transform(bbox[2], bbox[3])
    return (
        min(x1, x2), min(y1, y2),
        max(x1, x2), max(y1, y2),
    )


def _query_api_geo(
    wgs84_bbox: tuple[float, float, float, float],
    *,
    timeout: int = 15,
) -> list[str]:
    """Query the official API Geo for departments intersecting a WGS 84 bbox.

    Endpoint docs: https://geo.api.gouv.fr/decoupage-administratif/departements
    """
    # API expects ``?lon=...&lat=...`` or a geometry. The simplest approach
    # that covers an *area* is to iterate grid points, but the API also
    # supports a ``bbox`` query parameter (undocumented but stable since 2019).
    xmin, ymin, xmax, ymax = wgs84_bbox
    # Use the GeoAPI ``/departements`` endpoint with a bbox filter.
    # Format: ?zone=metro,drom&bbox=lon_min,lat_min,lon_max,lat_max
    params = urllib.parse.urlencode({
        "bbox": f"{xmin},{ymin},{xmax},{ymax}",
        "fields": "code",
        "limit": "100",
    })
    url = f"https://geo.api.gouv.fr/departements?{params}"

    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    if not isinstance(data, list):
        return []
    return [str(d["code"]) for d in data if "code" in d]


# ---------------------------------------------------------------------------
# Strategy 2 — cached boundary GeoPackage
# ---------------------------------------------------------------------------

_DEFAULT_CACHE = Path.home() / ".cache" / "hydromodpy" / "geology" / "departments"

# IGN GeoServices WFS (official, stable endpoint)
_WFS_URL = (
    "https://wxs.ign.fr/administratif/geoportail/wfs?"
    "SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature"
    "&TYPENAMES=ADMINEXPRESS-COG-CARTO.LATEST:departement"
    "&OUTPUTFORMAT=application/json&COUNT=200&SRSNAME=EPSG:2154"
)


def _ensure_boundaries_gpkg(cache_dir: Path | None = None) -> Path:
    """Return path to a cached GeoPackage of department polygons."""
    if cache_dir is None:
        cache_dir = _DEFAULT_CACHE
    cache_dir.mkdir(parents=True, exist_ok=True)
    gpkg = cache_dir / "departements.gpkg"
    if gpkg.exists():
        return gpkg

    # Try IGN WFS
    try:
        gdf = _download_wfs_departments()
        if gdf.crs is not None and gdf.crs.to_epsg() != 2154:
            gdf = gdf.to_crs("EPSG:2154")
        gdf.to_file(str(gpkg), driver="GPKG")
        print(f"[geology] Department boundaries cached: {gpkg}")
        return gpkg
    except Exception as exc:
        print(f"[geology] WFS download failed ({exc}), using built-in fallback.")

    # Built-in fallback: approximate department bboxes
    gdf = _builtin_department_bboxes()
    gdf.to_file(str(gpkg), driver="GPKG")
    print(f"[geology] Fallback department bboxes cached: {gpkg}")
    return gpkg


def _download_wfs_departments() -> gpd.GeoDataFrame:
    """Download department polygons from IGN GeoServices WFS."""
    print("[geology] Downloading department boundaries from IGN WFS...")
    req = urllib.request.Request(_WFS_URL, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        raw = resp.read()
    gdf = gpd.read_file(raw)
    if gdf.empty:
        raise ValueError("IGN WFS returned empty result")
    return gdf


# ---------------------------------------------------------------------------
# Built-in fallback: approximate bounding boxes (EPSG:2154)
# ---------------------------------------------------------------------------
# Each entry is (code_insee, xmin, ymin, xmax, ymax) in Lambert-93.
# Values are rounded to 1 km and intentionally enlarged by ~5 km
# to ensure a bbox intersection catches border departments.

_DEPT_BBOXES: list[tuple[str, float, float, float, float]] = [
    ("01", 796000, 6520000, 901000, 6630000),   # Ain
    ("02", 660000, 6900000, 780000, 7010000),   # Aisne
    ("03", 616000, 6520000, 730000, 6630000),   # Allier
    ("04", 897000, 6285000, 1000000, 6425000),  # Alpes-de-Haute-Provence
    ("05", 930000, 6375000, 1040000, 6500000),  # Hautes-Alpes
    ("06", 990000, 6275000, 1080000, 6380000),  # Alpes-Maritimes
    ("07", 752000, 6385000, 840000, 6520000),   # Ardeche
    ("08", 740000, 6940000, 830000, 7030000),   # Ardennes
    ("09", 470000, 6190000, 580000, 6270000),   # Ariege
    ("10", 710000, 6780000, 810000, 6880000),   # Aube
    ("11", 530000, 6220000, 650000, 6310000),   # Aude
    ("12", 570000, 6350000, 690000, 6480000),   # Aveyron
    ("13", 830000, 6250000, 920000, 6340000),   # Bouches-du-Rhone
    ("14", 370000, 6860000, 480000, 6940000),   # Calvados
    ("15", 570000, 6445000, 670000, 6550000),   # Cantal
    ("16", 390000, 6510000, 500000, 6610000),   # Charente
    ("17", 300000, 6490000, 410000, 6620000),   # Charente-Maritime
    ("18", 580000, 6640000, 700000, 6780000),   # Cher
    ("19", 520000, 6470000, 620000, 6560000),   # Correze
    ("2A", 1145000, 6080000, 1210000, 6175000), # Corse-du-Sud
    ("2B", 1155000, 6155000, 1240000, 6290000), # Haute-Corse
    ("21", 755000, 6620000, 860000, 6770000),   # Cote-d'Or
    ("22", 190000, 6810000, 310000, 6890000),   # Cotes-d'Armor
    ("23", 490000, 6530000, 590000, 6620000),   # Creuse
    ("24", 430000, 6420000, 560000, 6550000),   # Dordogne
    ("25", 890000, 6640000, 980000, 6760000),   # Doubs
    ("26", 800000, 6355000, 900000, 6500000),   # Drome
    ("27", 470000, 6870000, 600000, 6960000),   # Eure
    ("28", 490000, 6790000, 610000, 6890000),   # Eure-et-Loir
    ("29", 100000, 6800000, 220000, 6880000),   # Finistere
    ("30", 750000, 6280000, 860000, 6400000),   # Gard
    ("31", 480000, 6240000, 610000, 6370000),   # Haute-Garonne
    ("32", 430000, 6290000, 560000, 6400000),   # Gers
    ("33", 320000, 6370000, 430000, 6520000),   # Gironde
    ("34", 660000, 6250000, 790000, 6350000),   # Herault
    ("35", 260000, 6770000, 380000, 6870000),   # Ille-et-Vilaine
    ("36", 540000, 6590000, 640000, 6700000),   # Indre
    ("37", 460000, 6640000, 570000, 6750000),   # Indre-et-Loire
    ("38", 830000, 6460000, 940000, 6600000),   # Isere
    ("39", 840000, 6580000, 920000, 6720000),   # Jura
    ("40", 310000, 6290000, 430000, 6430000),   # Landes
    ("41", 530000, 6700000, 640000, 6810000),   # Loir-et-Cher
    ("42", 740000, 6480000, 830000, 6600000),   # Loire
    ("43", 680000, 6440000, 790000, 6540000),   # Haute-Loire
    ("44", 260000, 6670000, 380000, 6770000),   # Loire-Atlantique
    ("45", 560000, 6740000, 690000, 6850000),   # Loiret
    ("46", 520000, 6390000, 630000, 6500000),   # Lot
    ("47", 420000, 6340000, 540000, 6440000),   # Lot-et-Garonne
    ("48", 660000, 6370000, 770000, 6470000),   # Lozere
    ("49", 360000, 6680000, 480000, 6780000),   # Maine-et-Loire
    ("50", 300000, 6870000, 410000, 6990000),   # Manche
    ("51", 700000, 6840000, 830000, 6960000),   # Marne
    ("52", 770000, 6770000, 870000, 6890000),   # Haute-Marne
    ("53", 340000, 6770000, 450000, 6860000),   # Mayenne
    ("54", 850000, 6840000, 950000, 6940000),   # Meurthe-et-Moselle
    ("55", 810000, 6870000, 900000, 6960000),   # Meuse
    ("56", 170000, 6720000, 310000, 6830000),   # Morbihan
    ("57", 890000, 6880000, 1000000, 7000000),  # Moselle
    ("58", 660000, 6620000, 780000, 6770000),   # Nievre
    ("59", 640000, 7010000, 790000, 7130000),   # Nord
    ("60", 570000, 6910000, 700000, 6990000),   # Oise
    ("61", 380000, 6800000, 500000, 6890000),   # Orne
    ("62", 570000, 7000000, 710000, 7100000),   # Pas-de-Calais
    ("63", 640000, 6490000, 750000, 6600000),   # Puy-de-Dome
    ("64", 310000, 6210000, 460000, 6330000),   # Pyrenees-Atlantiques
    ("65", 410000, 6210000, 510000, 6310000),   # Hautes-Pyrenees
    ("66", 550000, 6150000, 660000, 6250000),   # Pyrenees-Orientales
    ("67", 970000, 6830000, 1060000, 6960000),  # Bas-Rhin
    ("68", 950000, 6740000, 1040000, 6850000),  # Haut-Rhin
    ("69", 780000, 6520000, 850000, 6620000),   # Rhone
    ("70", 870000, 6700000, 960000, 6800000),   # Haute-Saone
    ("71", 740000, 6560000, 860000, 6680000),   # Saone-et-Loire
    ("72", 400000, 6740000, 510000, 6850000),   # Sarthe
    ("73", 900000, 6480000, 1000000, 6590000),  # Savoie
    ("74", 880000, 6560000, 980000, 6650000),   # Haute-Savoie
    ("75", 645000, 6856000, 660000, 6868000),   # Paris
    ("76", 440000, 6910000, 580000, 7010000),   # Seine-Maritime
    ("77", 610000, 6810000, 740000, 6900000),   # Seine-et-Marne
    ("78", 570000, 6840000, 650000, 6910000),   # Yvelines
    ("79", 370000, 6560000, 480000, 6660000),   # Deux-Sevres
    ("80", 570000, 6950000, 700000, 7060000),   # Somme
    ("81", 530000, 6290000, 640000, 6400000),   # Tarn
    ("82", 490000, 6330000, 580000, 6420000),   # Tarn-et-Garonne
    ("83", 890000, 6250000, 1000000, 6350000),  # Var
    ("84", 830000, 6310000, 920000, 6410000),   # Vaucluse
    ("85", 280000, 6590000, 380000, 6720000),   # Vendee
    ("86", 420000, 6560000, 530000, 6680000),   # Vienne
    ("87", 470000, 6520000, 570000, 6610000),   # Haute-Vienne
    ("88", 900000, 6770000, 980000, 6870000),   # Vosges
    ("89", 680000, 6710000, 780000, 6830000),   # Yonne
    ("90", 950000, 6720000, 990000, 6760000),   # Territoire de Belfort
    ("91", 600000, 6820000, 670000, 6870000),   # Essonne
    ("92", 638000, 6853000, 660000, 6876000),   # Hauts-de-Seine
    ("93", 650000, 6858000, 675000, 6880000),   # Seine-Saint-Denis
    ("94", 645000, 6840000, 675000, 6865000),   # Val-de-Marne
    ("95", 590000, 6870000, 660000, 6920000),   # Val-d'Oise
]


def _builtin_department_bboxes() -> gpd.GeoDataFrame:
    """Create a GeoDataFrame with one bbox polygon per department."""
    records = []
    for code, xmin, ymin, xmax, ymax in _DEPT_BBOXES:
        records.append({"code": code, "geometry": box(xmin, ymin, xmax, ymax)})
    return gpd.GeoDataFrame(records, crs="EPSG:2154")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_code_column(gdf: gpd.GeoDataFrame) -> str:
    """Find the column holding the department code (INSEE)."""
    for name in ("code", "code_dept", "CODE_DEPT", "INSEE_DEP", "code_insee"):
        if name in gdf.columns:
            return name
    raise ValueError(
        f"Cannot find department code column. Available: {list(gdf.columns)}"
    )


def _to_brgm_codes(raw_codes: Sequence[str]) -> set[str]:
    """Normalize a list of raw department codes to 3-char BRGM format."""
    out: set[str] = set()
    for raw in raw_codes:
        c = str(raw).strip().upper()
        if c in ("2A", "2B"):
            out.add(f"0{c}")
        elif c in ("02A", "02B"):
            out.add(c)
        elif c.isdigit():
            out.add(c.zfill(3))
        else:
            out.add(c)
    return out
