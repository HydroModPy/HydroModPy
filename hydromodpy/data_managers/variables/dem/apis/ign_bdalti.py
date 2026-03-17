"""Download and cache IGN BD ALTI® 25 m MNT.

Source: https://geoservices.ign.fr/bdalti (GéoPlateforme)
License: Licence Ouverte / Open Licence (Etalab v2.0)

Workflow:
1. Detect which departments overlap the requested bbox
2. Download .7z archive for each department
3. Extract ASC tiles
4. Merge all tiles and crop to the requested bbox
5. Save as GeoTIFF
"""

from __future__ import annotations

import hashlib
import subprocess
import urllib.request
from pathlib import Path

# Base URL for BD ALTI downloads on GéoPlateforme.
_BASE_URL = "https://data.geopf.fr/telechargement/download/BDALTI"

# Mapping of department code (BRGM 3-char) → archive name (without .7z).
# Mainland France uses LAMB93-IGN69, Corsica uses LAMB93-IGN78C,
# overseas territories use their respective local CRS.
_BDALTI_ARCHIVES: dict[str, str] = {
    # --- Métropole (EPSG:2154 / Lambert-93, altimétrie IGN69) ---
    "001": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D001_2023-08-08",
    "002": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D002_2020-09-04",
    "003": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D003_2023-08-10",
    "004": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D004_2023-08-08",
    "005": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D005_2021-08-04",
    "006": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D006_2023-08-08",
    "007": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D007_2022-12-16",
    "008": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D008_2019-10-14",
    "009": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D009_2023-10-04",
    "010": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D010_2021-11-04",
    "011": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D011_2023-10-04",
    "012": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D012_2022-09-29",
    "013": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D013_2022-12-16",
    "014": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D014_2022-12-21",
    "015": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D015_2022-09-29",
    "016": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D016_2023-07-28",
    "017": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D017_2023-07-28",
    "018": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D018_2023-01-03",
    "019": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D019_2019-12-10",
    "021": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D021_2023-01-03",
    "022": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D022_2022-10-14",
    "023": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D023_2019-11-20",
    "024": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D024_2019-10-17",
    "025": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D025_2021-01-13",
    "026": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D026_2022-12-16",
    "027": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D027_2022-12-21",
    "028": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D028_2020-01-22",
    "029": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D029_2022-10-14",
    "030": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D030_2022-12-16",
    "031": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D031_2021-05-12",
    "032": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D032_2021-02-11",
    "033": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D033_2021-05-11",
    "034": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D034_2022-12-16",
    "035": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D035_2022-12-15",
    "036": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D036_2022-09-28",
    "037": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D037_2023-07-20",
    "038": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D038_2020-11-13",
    "039": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D039_2023-08-08",
    "040": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D040_2021-04-19",
    "041": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D041_2020-01-22",
    "042": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D042_2023-08-10",
    "043": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D043_2022-10-03",
    "044": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D044_2022-12-20",
    "045": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D045_2023-01-03",
    "046": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D046_2019-12-10",
    "047": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D047_2019-11-21",
    "048": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D048_2022-12-16",
    "049": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D049_2023-07-20",
    "050": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D050_2022-12-21",
    "051": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D051_2020-09-04",
    "052": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D052_2021-01-13",
    "053": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D053_2023-01-12",
    "054": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D054_2021-11-02",
    "055": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D055_2019-10-17",
    "056": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D056_2022-12-15",
    "057": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D057_2021-11-02",
    "058": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D058_2023-08-10",
    "059": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D059_2021-09-20",
    "060": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D060_2020-09-04",
    "061": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D061_2023-01-12",
    "062": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D062_2021-09-20",
    "063": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D063_2021-01-22",
    "064": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D064_2021-04-19",
    "065": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D065_2020-02-11",
    "066": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D066_2023-10-04",
    "067": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D067_2021-11-02",
    "068": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D068_2021-11-02",
    "069": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D069_2023-08-10",
    "070": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D070_2021-01-13",
    "071": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D071_2023-01-03",
    "072": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D072_2023-01-12",
    "073": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D073_2020-10-15",
    "074": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D074_2020-10-15",
    "075": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D075_2020-07-30",
    "076": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D076_2020-10-20",
    "077": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D077_2021-03-03",
    "078": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D078_2020-07-30",
    "079": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D079_2023-07-20",
    "080": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D080_2020-09-04",
    "081": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D081_2022-07-29",
    "082": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D082_2021-02-11",
    "083": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D083_2022-12-05",
    "084": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D084_2022-12-16",
    "085": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D085_2023-08-11",
    "086": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D086_2023-07-20",
    "087": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D087_2021-10-26",
    "088": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D088_2021-11-02",
    "089": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D089_2023-01-03",
    "090": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D090_2021-01-13",
    "091": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D091_2021-03-03",
    "092": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D092_2021-03-03",
    "093": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D093_2020-07-30",
    "094": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D094_2021-03-03",
    "095": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D095_2020-07-30",
    # --- Corse (EPSG:2154 / Lambert-93, altimétrie IGN78C) ---
    "02A": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN78C_D02A_2020-04-16",
    "02B": "BDALTIV2_2-0_25M_ASC_LAMB93-IGN78C_D02B_2020-04-16",
    # --- Outre-mer (CRS locaux) ---
    "971": "BDALTIV2_2-0_25M_ASC_WGS84UTM20-GUAD88_D971_2014-01-15",
    "972": "BDALTIV2_2-0_25M_ASC_WGS84UTM20-MART87_D972_2015-10-21",
    "973": "BDALTIV2_2-0_25M_ASC_RGFG95UTM22-GUYA77_D973_2023-08-02",
    "974": "BDALTIV2_2-0_25M_ASC_RGR92UTM40S-REUN89_D974_2023-09-05",
    "975": "BDALTIV2_2-0_25M_ASC_RGSPM06U21-STPM50_D975_2017-03-27",
    "976": "BDALTIV2_2-0_25M_ASC_RGM04UTM38S-MAYO53_D976_2013-12-19",
    "977": "BDALTIV2_2-0_25M_ASC_WGS84UTM20-GUAD88SB_D977_2019-11-25",
    "978": "BDALTIV2_2-0_25M_ASC_WGS84UTM20-GUAD88SM_D978_2019-11-20",
}


def _bbox_hash_str(bbox: tuple) -> str:
    s = f"{bbox[0]:.2f}_{bbox[1]:.2f}_{bbox[2]:.2f}_{bbox[3]:.2f}"
    return hashlib.md5(s.encode()).hexdigest()[:8]


def _extract_7z(archive_path: Path, output_dir: Path) -> None:
    """Extract a .7z archive using system ``7z`` or ``py7zr``."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Try system 7z command first (p7zip-full).
    try:
        subprocess.run(
            ["7z", "x", str(archive_path), f"-o{output_dir}", "-y"],
            check=True,
            capture_output=True,
        )
        return
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    # Fallback to py7zr Python package.
    try:
        import py7zr
        with py7zr.SevenZipFile(str(archive_path), mode="r") as z:
            z.extractall(path=str(output_dir))
        return
    except ImportError:
        raise RuntimeError(
            "Cannot extract .7z archive. Install either:\n"
            "  - p7zip-full: sudo apt install p7zip-full\n"
            "  - py7zr: pip install py7zr"
        )


def _download_department(
    dept_code: str,
    *,
    cache_dir: Path,
) -> Path | None:
    """Download and extract one department's BD ALTI .7z archive.

    Returns path to the extracted directory containing ASC files,
    or ``None`` if the department is unavailable.
    """
    archive_name = _BDALTI_ARCHIVES.get(dept_code)
    if archive_name is None:
        print(f"[dem] Warning: no BD ALTI archive for department {dept_code}")
        return None

    url = f"{_BASE_URL}/{archive_name}/{archive_name}.7z"

    dept_dir = cache_dir / archive_name
    marker = dept_dir / ".extracted"

    if marker.exists():
        return dept_dir

    archive_path = cache_dir / f"{archive_name}.7z"

    if not archive_path.exists():
        print(f"[dem] Downloading BD ALTI 25 m for department {dept_code}...")
        try:
            urllib.request.urlretrieve(url, str(archive_path))
        except Exception as exc:
            print(f"[dem] Warning: failed to download department {dept_code}: {exc}")
            return None

    print(f"[dem] Extracting {archive_name}...")
    try:
        _extract_7z(archive_path, dept_dir)
        marker.touch()
    except Exception as exc:
        print(f"[dem] Warning: failed to extract department {dept_code}: {exc}")
        return None

    return dept_dir


def _find_asc_files(directory: Path) -> list[Path]:
    """Find all ASC files recursively in a directory."""
    return sorted(directory.rglob("*.asc"))


def fetch_bdalti(
    *,
    output_dir: Path,
    bbox: tuple[float, float, float, float],
) -> Path:
    """Download, merge, and crop BD ALTI 25 m for the given bbox.

    Parameters
    ----------
    output_dir : cache directory
    bbox : (xmin, ymin, xmax, ymax) in EPSG:2154

    Returns
    -------
    Path to the merged and cropped GeoTIFF.
    """
    from hydromodpy.data_managers.common.administrative.france import (
        find_departments_in_bbox,
    )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    bbox_h = _bbox_hash_str(bbox)
    merged_tif = output_dir / f"dem_bdalti_25m_{bbox_h}.tif"

    if merged_tif.exists():
        return merged_tif

    # Step 1: find overlapping departments (returns BRGM 3-char codes).
    dept_codes = find_departments_in_bbox(bbox)
    if not dept_codes:
        raise ValueError(
            f"No department found overlapping bbox {bbox}. "
            "Ensure the bbox is in EPSG:2154 (Lambert-93)."
        )
    print(f"[dem] Departments overlapping bbox: {dept_codes}")

    # Step 2: download each department.
    dept_cache = output_dir / "departments_bdalti"
    dept_cache.mkdir(parents=True, exist_ok=True)

    import rasterio
    from rasterio.merge import merge

    all_asc_files: list[Path] = []
    for code in sorted(dept_codes):
        dept_dir = _download_department(code, cache_dir=dept_cache)
        if dept_dir is not None:
            asc_files = _find_asc_files(dept_dir)
            all_asc_files.extend(asc_files)

    if not all_asc_files:
        raise ValueError(
            f"No ASC files found for departments: {list(dept_codes)}"
        )

    print(f"[dem] Merging {len(all_asc_files)} ASC tiles...")

    # Step 3: open all datasets and merge with bbox crop.
    datasets = []
    try:
        for asc_path in all_asc_files:
            ds = rasterio.open(str(asc_path))
            datasets.append(ds)

        mosaic, mosaic_transform = merge(datasets, bounds=bbox)
    finally:
        for ds in datasets:
            ds.close()

    # Step 4: write merged GeoTIFF.
    profile = {
        "driver": "GTiff",
        "height": mosaic.shape[1],
        "width": mosaic.shape[2],
        "count": mosaic.shape[0],
        "transform": mosaic_transform,
        "crs": "EPSG:2154",
        "dtype": mosaic.dtype,
        "compress": "deflate",
        "nodata": -9999,
    }

    with rasterio.open(str(merged_tif), "w", **profile) as dst:
        dst.write(mosaic)

    print(f"[dem] Merged BD ALTI MNT: {merged_tif}")
    return merged_tif
