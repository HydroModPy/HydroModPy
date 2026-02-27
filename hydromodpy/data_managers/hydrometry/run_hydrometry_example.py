"""Run an end-to-end hydrometry station-set example.

This script demonstrates multiple ways to discover and load hydrometric data:
1. Load from hydrometry_config.toml with explicit station IDs
2. Load from hydrometry_config.toml with geographic mask (automatic fallback if empty)
3. Use manual discovery with discover_station_ids() for fine-grained control
"""

from pathlib import Path
import sys

_MANAGER_ROOT = Path(__file__).resolve().parents[1]
_THIS_DIR = Path(__file__).resolve().parent
for _path in (str(_MANAGER_ROOT), str(_THIS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

try:
    from .station_set import StationSet
    from .hydrometry_config import load_hydrometry_toml
except ImportError:
    from station_set import StationSet
    from hydrometry_config import load_hydrometry_toml


def _fmt_date_or_none(value):
    """Return ``YYYY-MM-DD`` string or ``None``."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.strftime("%Y-%m-%d")


def main() -> None:
    """Execute the hydrometry example workflow with mask-based discovery."""
    manager_dir = Path(__file__).resolve().parent
    config_path = manager_dir / "hydrometry_config.toml"
    outputs_dir = manager_dir / "outputs"

    print("=" * 70)
    print("HYDROMETRY DISCOVERY EXAMPLE - MASK-BASED WORKFLOW")
    print("=" * 70)

    # Load config to check selection mode
    try:
        config_data = load_hydrometry_toml(config_path)
        selection_cfg = config_data.get("selection", {})
        selection_mode = selection_cfg.get("mode", "stations")
        mask_path = selection_cfg.get("mask_path")
    except Exception as exc:
        print(f"Error loading config: {exc}")
        return

    print(f"\n[Config] Selection mode: {selection_mode}")
    if selection_mode == "mask" and mask_path:
        print(f"[Config] Mask path: {mask_path}")
        print(f"[Config] Date range: {config_data.get('hydrometry', {}).get('date_start')} to {config_data.get('hydrometry', {}).get('date_end')}")

    # Try to load from config
    try:
        print("\n[Loading] Starting hydrometric station discovery and loading...")
        stations = StationSet.from_toml(config_path)
        print(f"\n[Success] Loaded {len(stations.stations)} stations")

    except ValueError as exc:
        print(f"\n[Error] {exc}")
        print("\nNote: If mask was empty, the automatic 50 km fallback should have triggered.")
        return
    except Exception as exc:
        print(f"\n[Unexpected Error] {exc}")
        return

    # Print completeness report
    print("\n" + "=" * 70)
    stations.get_completeness_report()

    # Show discovered stations
    if stations.stations:
        print("\n" + "=" * 70)
        print("DISCOVERED STATIONS")
        print("=" * 70)
        station_ids = sorted(stations.stations.keys())
        print(f"Total: {len(station_ids)} stations")
        for idx, sid in enumerate(station_ids[:10], 1):  # Show first 10
            station_obj = stations.stations[sid]
            station_name = sid
            # Try to get station name from metadata if available
            try:
                if hasattr(station_obj, 'metadata'):
                    meta = station_obj.metadata
                    if isinstance(meta, dict) and meta:
                        station_name = meta.get("station_name", sid)
                    elif hasattr(meta, 'get'):  # pandas Series or similar
                        station_name = meta.get("station_name", sid)
            except Exception:
                pass
            print(f"  {idx}. {sid} - {station_name}")
        if len(station_ids) > 10:
            print(f"  ... and {len(station_ids) - 10} more")

        # Export plots
        print("\n" + "=" * 70)
        print("EXPORTING PLOTS")
        print("=" * 70)
        # Plot first 3 stations as example
        for station_id in station_ids[:3]:
            output_path = outputs_dir / f"station_plot_{station_id}.png"
            try:
                stations.plot_station(
                    station_id=station_id,
                    output_path=output_path,
                    show=False,  # Set to True if you want to display
                )
                print(f"  ✓ Exported: {output_path.name}")
            except Exception as e:
                print(f"  ✗ Failed to plot {station_id}: {e}")
    else:
        print("\n✗ No loaded hydrometric data available.")
        print("\nTips for manual discovery:")
        print("  • Use bbox for geographic area: bbox=(minx, miny, maxx, maxy)")
        print("  • Use center_point for distance-based sorting: center_point=(lon, lat)")
        print("  • Use mask_path='file.shp' for shapefile-based discovery")
        print("  • Use max_ids=N to limit results (or max_ids=None for all)")
        print("  • Use fallback_search_radius_km=50 to adjust search radius")
        print("  • Use require_observations=True to filter by data availability")


if __name__ == "__main__":
    main()
