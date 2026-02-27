"""Run an end-to-end piezometry station-set example.

This script demonstrates piezometer discovery and loading with automatic fallback:
1. Load from piezometry_config.toml (mask-based discovery)
2. Use automatic fallback when mask is empty
3. Optional: Sort by distance to mask centroid or center_point
"""

from pathlib import Path
import sys

_MANAGER_ROOT = Path(__file__).resolve().parents[1]
_THIS_DIR = Path(__file__).resolve().parent
for _path in (str(_MANAGER_ROOT), str(_THIS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

try:
    from ..common.utils import safe_file_token
    from .piezometer_set import PiezometerSet
    from .piezometry_config import load_piezometry_toml
except ImportError:
    from common.utils import safe_file_token
    from piezometer_set import PiezometerSet
    from piezometry_config import load_piezometry_toml


def _fmt_date_or_none(value):
    """Return ``YYYY-MM-DD`` string or ``None``."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.strftime("%Y-%m-%d")


def _safe_id_token(value: str) -> str:
    """Return a filesystem-safe token for one piezometer id."""
    return safe_file_token(value)


def main() -> None:
    """Execute the piezometry mask-based discovery workflow with automatic fallback."""
    manager_dir = Path(__file__).resolve().parent
    config_path = manager_dir / "piezometry_config.toml"
    outputs_dir = manager_dir / "outputs"
    outputs_dir.mkdir(exist_ok=True)

    print("=" * 70)
    print("PIEZOMETRY DISCOVERY EXAMPLE - MASK-BASED WORKFLOW")
    print("=" * 70)

    # Load config
    try:
        config_data = load_piezometry_toml(config_path)
        selection_cfg = config_data.get("selection", {})
        selection_mode = selection_cfg.get("mode", "stations")
        mask_path = selection_cfg.get("mask_path")
        piezometry_cfg = config_data.get("piezometry", {})
        output_cfg = config_data.get("output", {})
    except Exception as exc:
        print(f"[Error] Failed to load config: {exc}")
        return

    # Display config
    print(f"\n[Config] Selection mode: {selection_mode}")
    if mask_path:
        print(f"[Config] Mask path: {mask_path}")
    date_start = _fmt_date_or_none(piezometry_cfg.get("date_start"))
    date_end = _fmt_date_or_none(piezometry_cfg.get("date_end"))
    if date_start or date_end:
        print(f"[Config] Date range: {date_start} to {date_end}")

    # Discover piezometers
    print(f"\n[Loading] Starting piezometric discovery and loading...")
    try:
        if selection_mode == "mask" and mask_path:
            # Mask-based discovery with automatic 25 km fallback
            print(f"Loading geographic mask from: {mask_path}")
            discovered = PiezometerSet.discover_piezometer_ids(
                mask_path=mask_path,
                require_observations=False,
                date_start=date_start,
                date_end=date_end,
                max_ids=None,  # Get all discovered piezometers
                fallback_search_radius_km=25.0,  # Adjustable fallback radius
                timeout=60,
            )
        else:
            print("[Error] This example requires selection.mode='mask' in config")
            return

        if not discovered:
            print("[Error] No piezometers discovered")
            return

        print(f"\n[Discovery] Found {len(discovered)} piezometers")

        # Create PiezometerSet
        piezometers = PiezometerSet(
            measurement=piezometry_cfg.get("measurement", "both"),
            id=discovered,
            display=piezometry_cfg.get("display", False),
            date_start=date_start,
            date_end=date_end,
            output=output_cfg.get("path") if output_cfg.get("enabled") else None,
            source_mode="api",
        )
    except Exception as exc:
        print(f"[Error] Discovery/loading failed: {exc}")
        import traceback
        traceback.print_exc()
        return

    # Report
    print("\n" + "=" * 70)
    piezometers.get_completeness_report()

    # Show discovered piezometers
    if piezometers.piezometers:
        print("\n" + "=" * 70)
        print("DISCOVERED PIEZOMETERS")
        print("=" * 70)
        piezometer_ids = sorted(piezometers.piezometers.keys())
        print(f"Total: {len(piezometer_ids)} piezometers")
        for idx, pid in enumerate(piezometer_ids[:10], 1):  # Show first 10
            piezometer_obj = piezometers.piezometers[pid]
            piezometer_name = pid
            # Try to get piezometer name from metadata if available
            try:
                if hasattr(piezometer_obj, 'metadata'):
                    meta = piezometer_obj.metadata
                    if isinstance(meta, dict) and meta:
                        piezometer_name = meta.get("station_name", pid)
                    elif hasattr(meta, 'get'):
                        piezometer_name = meta.get("station_name", pid)
            except Exception:
                pass
            print(f"  {idx}. {pid} - {piezometer_name}")
        if len(piezometer_ids) > 10:
            print(f"  ... and {len(piezometer_ids) - 10} more")

        # Export plots
        print("\n" + "=" * 70)
        print("EXPORTING PLOTS")
        print("=" * 70)
        # Plot first 3 piezometers as example
        for piezometer_id in piezometer_ids[:3]:
            output_path = outputs_dir / f"piezometer_plot_{_safe_id_token(piezometer_id)}.png"
            try:
                piezometers.plot_piezometer(
                    piezometer_id=piezometer_id,
                    output_path=output_path,
                    show=False,
                )
                print(f"  ✓ Exported: {output_path.name}")
            except Exception as e:
                print(f"  ✗ Failed to plot {piezometer_id}: {e}")
    else:
        print("\n✗ No loaded piezometric data available.")
        print("\nTips for manual discovery:")
        print("  • Use bbox for geographic area: bbox=(minx, miny, maxx, maxy)")
        print("  • Use center_point for distance-based sorting: center_point=(lon, lat)")
        print("  • Use mask_path='file.shp' for shapefile-based discovery")
        print("  • Use max_ids=N to limit results (or max_ids=None for all)")
        print("  • Use fallback_search_radius_km=25 to adjust search radius")
        print("  • Use require_observations=True to filter by data availability")


if __name__ == "__main__":
    main()
