"""Internal BD ALTI 25 m archive index and extraction helpers.

This module is not a public DEM provider. It supports the Geoplateforme DEM
client when live resource discovery is incomplete and keeps extraction helpers
close to the only assembled raster product that still needs them.
"""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Sequence
from pathlib import Path

# Mapping of department code (BRGM 3-char) to archive name (without .7z).
# Mainland France uses LAMB93-IGN69, Corsica uses LAMB93-IGN78C,
# overseas territories use their respective local CRS.
BDALTI_25M_ASC_ARCHIVES: dict[str, str] = {
    # --- Mainland France (EPSG:2154 / Lambert-93, IGN69 altimetry) ---
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
    # --- Corsica (EPSG:2154 / Lambert-93, IGN78C altimetry) ---
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


def _request_hash_str(
    bbox: tuple,
    *,
    dept_codes: Sequence[str] | None = None,
) -> str:
    dept_part = "" if not dept_codes else "_" + "_".join(sorted(dept_codes))
    s = f"{bbox[0]:.2f}_{bbox[1]:.2f}_{bbox[2]:.2f}_{bbox[3]:.2f}{dept_part}"
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
            for item in z.files:
                target = output_dir / Path(item.filename)
                if item.is_directory:
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
            z.extractall(path=str(output_dir))
        return
    except ImportError:
        raise RuntimeError(
            "Cannot extract .7z archive. Install either:\n"
            "  - p7zip-full: sudo apt install p7zip-full\n"
            "  - py7zr: pip install py7zr"
        ) from None


def _find_asc_files(directory: Path) -> list[Path]:
    """Find all ASC files recursively in a directory."""
    return sorted(directory.rglob("*.asc"))


__all__ = [
    "BDALTI_25M_ASC_ARCHIVES",
    "_extract_7z",
    "_find_asc_files",
    "_request_hash_str",
]
