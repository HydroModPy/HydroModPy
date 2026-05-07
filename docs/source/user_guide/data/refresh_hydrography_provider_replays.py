"""Refresh small hydrography provider replay artifacts.

This script is intentionally separate from ``render_data_communication_assets``:
it may call online providers, while the documentation renderer must remain a
stable replay-only step.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import geopandas as gpd

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[5]
DATA_DIR = REPO_ROOT / "examples" / "data" / "hydrography"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


DEFAULT_BBOXES: dict[str, tuple[float, float, float, float]] = {
    "couesnon": (-1.2451, 48.3618, -1.1072, 48.4651),
}


def _bbox_token(bbox: tuple[float, float, float, float]) -> str:
    return "_".join(f"{value:.4f}" for value in bbox)


def _sha256(path: Path) -> str:
    from hydromodpy.data.lockfile import sha256_of

    return sha256_of(path)


def _fetch_provider(provider: str, bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    from hydromodpy.data.variables.hydrography.config import HydrographySourceConfig

    cfg = HydrographySourceConfig(source=provider)
    fetchers: dict[str, Callable] = {}
    if provider == "bdtopage":
        from hydromodpy.data.variables.hydrography.apis.bdtopage import fetch

        fetchers[provider] = fetch
    elif provider == "osm":
        from hydromodpy.data.variables.hydrography.apis.osm import fetch

        fetchers[provider] = fetch
    elif provider == "euhydro":
        from hydromodpy.data.variables.hydrography.apis.euhydro import fetch

        fetchers[provider] = fetch
    else:
        raise ValueError(f"Unsupported provider: {provider!r}")
    return fetchers[provider](cfg, bbox)


def _length_km(gdf: gpd.GeoDataFrame) -> float:
    if gdf.empty:
        return 0.0
    projected = gdf.to_crs("EPSG:2154") if str(gdf.crs) != "EPSG:2154" else gdf
    return float(projected.geometry.length.sum() / 1000.0)


def _metadata(
    *,
    case_name: str,
    provider: str,
    bbox: tuple[float, float, float, float],
    path: Path,
    status: str,
) -> dict[str, object]:
    gdf = gpd.read_file(path)
    bounds = None if gdf.empty else [float(v) for v in gdf.to_crs("EPSG:4326").total_bounds]
    return {
        "case": case_name,
        "provider": provider,
        "bbox_wgs84": list(bbox),
        "file": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "status": status,
        "feature_count": int(len(gdf)),
        "total_length_km": round(_length_km(gdf), 3),
        "crs": str(gdf.crs),
        "bounds_wgs84": bounds,
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def refresh_case(
    *,
    case_name: str,
    bbox: tuple[float, float, float, float],
    providers: list[str],
    force: bool,
) -> list[dict[str, object]]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for provider in providers:
        path = DATA_DIR / f"{provider}_{_bbox_token(bbox)}.gpkg"
        status = "reused"
        if force or not path.exists():
            if path.exists():
                path.unlink()
            gdf = _fetch_provider(provider, bbox)
            if gdf.crs is None:
                gdf = gdf.set_crs("EPSG:4326")
            elif str(gdf.crs) != "EPSG:4326":
                gdf = gdf.to_crs("EPSG:4326")
            gdf.to_file(path, driver="GPKG")
            status = "fetched"
        rows.append(
            _metadata(
                case_name=case_name,
                provider=provider,
                bbox=bbox,
                path=path,
                status=status,
            )
        )
    return rows


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case",
        choices=sorted(DEFAULT_BBOXES),
        default="couesnon",
        help="Small replay bbox to refresh.",
    )
    parser.add_argument(
        "--providers",
        nargs="+",
        choices=["bdtopage", "osm", "euhydro"],
        default=["osm", "euhydro"],
        help="Providers to refresh. BD Topage is usually already committed.",
    )
    parser.add_argument(
        "--force", action="store_true", help="Fetch again even when a replay GPKG exists."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DATA_DIR / "provider_replay_manifest.json",
        help="Manifest path to write after the refresh.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    bbox = DEFAULT_BBOXES[args.case]
    rows = refresh_case(case_name=args.case, bbox=bbox, providers=args.providers, force=args.force)
    manifest = {
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "note": "Provider replay artifacts for documentation. Run intentionally; the renderer is replay-only.",
        "artifacts": rows,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
