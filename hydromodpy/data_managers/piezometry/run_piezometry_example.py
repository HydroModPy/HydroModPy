"""Run an end-to-end piezometry station-set example.

This script demonstrates piezometer loading from a TOML configuration:
1. Load a ``PiezometerSet`` via ``from_toml``
2. Plot every discovered piezometer to an output directory
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


def _safe_id_token(value: str) -> str:
    """Return a filesystem-safe token for one piezometer id."""
    return safe_file_token(value)


def _fmt_date_or_none(value):
    """Return ``YYYY-MM-DD`` string or ``None``."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.strftime("%Y-%m-%d")


def main_piezometer_set() -> None:
    """Execute the piezometry discovery workflow from a TOML config."""
    manager_dir = Path(__file__).resolve().parent
    config_path = manager_dir / "piezometry_config.toml"
    outputs_dir = manager_dir / "outputs"
    outputs_dir.mkdir(exist_ok=True)

    print("=" * 70)
    print("PIEZOMETRY DISCOVERY EXAMPLE - MASK-BASED WORKFLOW")
    print("=" * 70)

    # Load piezometer set from config
    try:
        piezometers = PiezometerSet.from_toml(config_path)
    except Exception as exc:
        print(f"Error:  Failed to load config: {exc}")
        return

    # -- Display loaded configuration ----------------------------------------
    print(f"\n[Config] Measurement type : {piezometers.measurement}")
    if piezometers.date_start or piezometers.date_end:
        print(f"[Config] Date range       : {piezometers.date_start} -> {piezometers.date_end}")

    # -- Completeness report -------------------------------------------------
    piezometers.get_completeness_report()

    # -- List discovered piezometers -----------------------------------------
    if not piezometers.piezometers:
        print("\nNo loaded piezometric data available.")
        print("\nTips for new developers:")
        print("  - Check that the TOML config lists valid station IDs or a mask")
        print("  - Use PiezometerSet.discover_piezometer_ids() for geographic search")
        print("  - Use require_observations=True to filter by data availability")
        return

    piezometer_ids = sorted(piezometers.piezometers.keys())

    print("\n" + "=" * 70)
    print("DISCOVERED PIEZOMETERS")
    print("=" * 70)
    print(f"Total: {len(piezometer_ids)} piezometer(s)")
    for idx, pid in enumerate(piezometer_ids[:10], 1):
        print(f"  {idx}. {pid}")
    if len(piezometer_ids) > 10:
        print(f"  ... and {len(piezometer_ids) - 10} more")

    # -- Export one plot per piezometer --------------------------------------
    print("\n" + "=" * 70)
    print("EXPORTING PLOTS")
    print("=" * 70)
    for piezometer_id in piezometer_ids:
        output_path = outputs_dir / f"piezometer_plot_{_safe_id_token(piezometer_id)}.png"
        try:
            piezometers.plot_piezometer(
                piezometer_id=piezometer_id,
                output_path=output_path,
                show=True,
            )
            print(f"  ✓ Exported: {output_path.name}")
        except Exception as exc:
            print(f"  ✗ Failed to plot {piezometer_id}: {exc}")


def main_piezometer() -> None:
    """Test the Piezometer class with a single loaded piezometer."""
    manager_dir = Path(__file__).resolve().parent
    config_path = manager_dir / "piezometry_config.toml"
    outputs_dir = manager_dir / "outputs"
    outputs_dir.mkdir(exist_ok=True)

    print("=" * 70)
    print("PIEZOMETRY PIEZOMETER CLASS TEST")
    print("=" * 70)

    # Load config and get a piezometer
    try:
        config_data = load_piezometry_toml(config_path)
        selection_cfg = config_data.get("selection", {})
        selection_mode = selection_cfg.get("mode", "stations")
        mask_path = selection_cfg.get("mask_path")
        piezometry_cfg = config_data.get("piezometry", {})
        
        date_start = _fmt_date_or_none(piezometry_cfg.get("date_start"))
        date_end = _fmt_date_or_none(piezometry_cfg.get("date_end"))
    except Exception as exc:
        print(f"[Error] Failed to load config: {exc}")
        return

    # Discover and load piezometers
    print(f"\n[Loading] Loading piezometric data...")
    try:
        if selection_mode == "mask" and mask_path:
            discovered = PiezometerSet.discover_piezometer_ids(
                mask_path=mask_path,
                require_observations=False,
                date_start=date_start,
                date_end=date_end,
                max_ids=5,  # Limit to 5 for testing
                fallback_search_radius_km=20.0,
                timeout=60,
            )
        else:
            print("[Error] This test requires selection.mode='mask' in config")
            return

        if not discovered:
            print("[Error] No piezometers discovered")
            return

        # Create PiezometerSet to load data
        piezometers = PiezometerSet(
            measurement=piezometry_cfg.get("measurement", "level"),
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

    # Test Piezometer class with the first loaded piezometer
    if not piezometers.piezometers:
        print("[Error] No piezometers loaded")
        return

    piezometer_id = sorted(piezometers.piezometers.keys())[0]
    print(f"\n[Test] Testing Piezometer class with: {piezometer_id}")
    print("=" * 70)

    piezometer = piezometers.piezometers[piezometer_id]

    # 1️⃣ Display basic info
    print("\n1️⃣  PIEZOMETER BASIC INFO")
    print(f"   ID: {piezometer.piezometer_id}")
    print(f"   Measurement type: {piezometer.measurement}")
    print(f"   Label: {piezometer.build_label()}")

    # 2️⃣ Display metadata
    print("\n2️⃣  PIEZOMETER METADATA")
    if piezometer.metadata:
        for key, value in sorted(piezometer.metadata.items())[:5]:  # Show first 5
            print(f"   {key}: {value}")
        if len(piezometer.metadata) > 5:
            print(f"   ... and {len(piezometer.metadata) - 5} more keys")
    else:
        print("   No metadata available")

    # 3️⃣ Display spatial info
    print("\n3️⃣  SPATIAL INFORMATION")
    if piezometer.station_position:
        print(f"   Position: {piezometer.station_position}")
    else:
        print("   No position data")
    if piezometer.georeferencing:
        print(f"   Georeferencing: {piezometer.georeferencing}")

    # 4️⃣ Display data summary
    print("\n4️⃣  DATA SUMMARY")
    if not piezometer.data.empty:
        print(f"   Records: {len(piezometer.data)}")
        print(f"   Date range: {piezometer.data['date_measure'].min()} to {piezometer.data['date_measure'].max()}")
        print(f"   Columns: {', '.join(piezometer.data.columns.tolist())}")
    else:
        print("   No data loaded")

    # 5️⃣ Calculate and display completeness
    print("\n5️⃣  DATA COMPLETENESS")
    try:
        completeness = piezometer.completeness(verbose=False)
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
        plot_output = outputs_dir / f"piezometer_test_{piezometer_id}.png"
        piezometer.plot(output_path=plot_output, show=False)
        print(f"   ✓ Plot saved to: {plot_output.name}")
    except Exception as e:
        print(f"   ✗ Failed to generate plot: {e}")

    print("\n" + "=" * 70)
    print("[Success] Piezometer class test completed")


if __name__ == "__main__":
    # Run both discovery workflow and Piezometer class test
    main_piezometer_set()
    
    # Clear separator for readability
    print("\n\n")
    print("█" * 70)
    print("█" + " " * 68 + "█")
    print("█" + " TRANSITIONING TO PIEZOMETER CLASS TEST ".center(68) + "█")
    print("█" + " " * 68 + "█")
    print("█" * 70)
    print("\n")
    
    main_piezometer()
