"""CLI helper to download French IGN DEM archives by department."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.data.variables.dem.apis.geoplateforme_download import (  # noqa: E402
    RateLimiter,
    download_file,
    fetch_atom_entries,
    find_resources,
    list_files,
    list_subresources,
)
from hydromodpy.data.variables.dem.apis.ign_dem_fr import (  # noqa: E402
    discover_ign_dem_files,
    download_ign_dem_departments,
    normalize_department_code,
)


def default_output_dir() -> Path:
    """Return the default raw DEM cache outside the source repository."""

    workspace = os.environ.get("HYDROMODPY_WORKSPACE")
    root = Path(workspace).expanduser() if workspace else Path.home() / "hydromodpy"
    return root / "data" / "dem" / "raw_ign"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download IGN BD ALTI/RGE ALTI archives by French department.",
    )
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument(
        "--departements",
        nargs="+",
        help="French department codes, e.g. 29 35 D075 971.",
    )
    selector.add_argument(
        "--regions",
        nargs="+",
        help="French administrative region names, e.g. Bretagne or Auvergne-Rhone-Alpes.",
    )
    parser.add_argument(
        "--dataset",
        choices=("rge-alti", "bd-alti"),
        required=True,
        help="DEM dataset to download.",
    )
    parser.add_argument(
        "--resolution",
        type=float,
        default=None,
        help="Requested raster resolution in metres, e.g. 25 for BD ALTI.",
    )
    parser.add_argument(
        "--format",
        dest="file_format",
        default="ASC",
        help="Requested source file format, default: ASC.",
    )
    parser.add_argument(
        "--crs",
        default=None,
        help="Optional CRS filter when exposed by Geoplateforme.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(default_output_dir()),
        help=(
            "Output directory, default: HYDROMODPY_WORKSPACE/data/dem/raw_ign "
            "or ~/hydromodpy/data/dem/raw_ign."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List matching target files without downloading.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Optional maximum number of files to list/download.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=8.0,
        help="Maximum request rate per second. Keep below 10.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-download files even when a non-empty local file exists.",
    )
    parser.add_argument(
        "--include-md5",
        action="store_true",
        help="Include provider checksum metadata in dry-run output when available.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    departments = _resolve_departments(args.departements, args.regions)
    if args.dry_run:
        files = discover_ign_dem_files(
            departments=departments,
            dataset=args.dataset,
            resolution_m=args.resolution,
            file_format=args.file_format,
            crs=args.crs,
            timeout=args.timeout,
            rate_limiter=RateLimiter(args.rate_limit),
        )
        if args.max_files is not None:
            files = files[: args.max_files]
        print(f"Found {len(files)} file(s).")
        for file in files:
            suffix = f" md5={file.checksum}" if args.include_md5 and file.checksum else ""
            print(f"{file.department or 'D???'} {file.file_name} {file.url}{suffix}")
        return 0

    paths = download_ign_dem_departments(
        output_dir=Path(args.output_dir),
        departments=departments,
        dataset=args.dataset,
        resolution_m=args.resolution,
        file_format=args.file_format,
        crs=args.crs,
        dry_run=False,
        max_files=args.max_files,
        timeout=args.timeout,
        requests_per_second=args.rate_limit,
        overwrite=args.overwrite,
    )
    print(f"Downloaded or reused {len(paths)} file(s).")
    for path in paths:
        print(path)
    return 0


def _resolve_departments(
    departments: Sequence[str] | None,
    regions: Sequence[str] | None,
) -> list[str]:
    if departments:
        return [normalize_department_code(value) for value in departments]
    if regions:
        from hydromodpy.data.common.administrative.france import find_departments_in_regions

        return [normalize_department_code(value) for value in find_departments_in_regions(regions)]
    raise ValueError("Either departments or regions must be provided.")


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "download_file",
    "fetch_atom_entries",
    "find_resources",
    "list_files",
    "list_subresources",
    "default_output_dir",
    "main",
    "normalize_department_code",
]
