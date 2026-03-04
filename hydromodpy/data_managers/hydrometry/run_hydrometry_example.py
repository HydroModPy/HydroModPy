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


def main_station_set() -> None:
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


def main_station() -> None:
    """Test the Station class with a single loaded station."""
    manager_dir = Path(__file__).resolve().parent
    config_path = manager_dir / "hydrometry_config.toml"
    outputs_dir = manager_dir / "outputs"
    outputs_dir.mkdir(exist_ok=True)

    print("=" * 70)
    print("HYDROMETRY STATION CLASS TEST")
    print("=" * 70)

    # Load config and get a station
    try:
        config_data = load_hydrometry_toml(config_path)
        selection_cfg = config_data.get("selection", {})
        selection_mode = selection_cfg.get("mode", "stations")
        mask_path = selection_cfg.get("mask_path")
        piezometry_cfg = config_data.get("hydrometry", {})
        
        date_start = _fmt_date_or_none(piezometry_cfg.get("date_start"))
        date_end = _fmt_date_or_none(piezometry_cfg.get("date_end"))
    except Exception as exc:
        print(f"[Error] Failed to load config: {exc}")
        return

    # Discover and load stations
    print(f"\n[Loading] Loading hydrometric stations...")
    try:
        if selection_mode == "mask" and mask_path:
            discovered = StationSet.discover_station_ids(
                mask_path=mask_path,
                require_observations=False,
                date_start=date_start,
                date_end=date_end,
                max_ids=5,  # Limit to 5 for testing
                fallback_search_radius_km=10.0,
                timeout=60,
            )
        else:
            print("[Error] This test requires selection.mode='mask' in config")
            return

        if not discovered:
            print("[Error] No stations discovered")
            return

        # Create StationSet to load data
        stations = StationSet(
            variable=piezometry_cfg.get("variable", "QmnJ"),
            id=discovered,
            display=piezometry_cfg.get("display", False),
            date_start=date_start,
            date_end=date_end,
            output=None,  # Don't export here
            source_mode="api",
        )
    except Exception as exc:
        print(f"[Error] Loading failed: {exc}")
        import traceback
        traceback.print_exc()
        return

    # Test Station class with the first loaded station
    if not stations.stations:
        print("[Error] No stations loaded")
        return

    station_id = sorted(stations.stations.keys())[0]
    print(f"\n[Test] Testing Station class with: {station_id}")
    print("=" * 70)

    station = stations.stations[station_id]

    # 1️⃣ Display basic info
    print("\n1️⃣  STATION BASIC INFO")
    print(f"   ID: {station.station_id}")
    print(f"   Variable: {station.variable}")
    print(f"   Label: {station.build_label()}")

    # 2️⃣ Display metadata
    print("\n2️⃣  STATION METADATA")
    if station.metadata:
        for key, value in sorted(station.metadata.items())[:5]:  # Show first 5
            print(f"   {key}: {value}")
        if len(station.metadata) > 5:
            print(f"   ... and {len(station.metadata) - 5} more keys")
    else:
        print("   No metadata available")

    # 3️⃣ Display spatial info
    print("\n3️⃣  SPATIAL INFORMATION")
    if station.station_position:
        print(f"   Position: {station.station_position}")
    else:
        print("   No position data")
    if station.georeferencing:
        print(f"   Georeferencing: {station.georeferencing}")

    # 4️⃣ Display data summary
    print("\n4️⃣  DATA SUMMARY")
    if not station.data.empty:
        print(f"   Records: {len(station.data)}")
        print(f"   Date range: {station.data['date_obs_elab'].min()} to {station.data['date_obs_elab'].max()}")
        print(f"   Columns: {', '.join(station.data.columns.tolist())}")
    else:
        print("   No data loaded")

    # 5️⃣ Calculate and display completeness
    print("\n5️⃣  DATA COMPLETENESS")
    try:
        completeness = station.completeness(verbose=False)
        print(f"   Total expected days: {completeness.get('expected_days', 0)}")
        print(f"   Actual days with data: {completeness.get('actual_days', 0)}")
        print(f"   Missing days: {completeness.get('missing_days', 0)}")
        print(f"   Completeness: {completeness.get('completeness_pct', 0.0):.1f}%")
        print(f"   Gaps detected: {completeness.get('gaps_detected', 0)}")
    except Exception as e:
        print(f"   Error computing completeness: {e}")

    # 6️⃣ Generate plot
    print("\n6️⃣  PLOTTING")
    try:
        plot_output = outputs_dir / f"station_test_{station_id}.png"
        station.plot(output_path=plot_output, show=False)
        print(f"   ✓ Plot saved to: {plot_output.name}")
    except Exception as e:
        print(f"   ✗ Failed to generate plot: {e}")

    print("\n" + "=" * 70)
    print("[Success] Station class test completed")


if __name__ == "__main__":
    # Run both discovery workflow and Station class test
    main_station_set()
    
    # Clear separator for readability
    print("\n\n")
    print("█" * 70)
    print("█" + " " * 68 + "█")
    print("█" + " TRANSITIONING TO STATION CLASS TEST ".center(68) + "█")
    print("█" + " " * 68 + "█")
    print("█" * 70)
    print("\n")
    
    main_station()
