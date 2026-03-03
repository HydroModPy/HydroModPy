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
except ImportError:
    from common.utils import safe_file_token
    from piezometer_set import PiezometerSet


def _safe_id_token(value: str) -> str:
    """Return a filesystem-safe token for one piezometer id."""
    return safe_file_token(value)


def main() -> None:
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
            print(f"  Exported: {output_path.name}")
        except Exception as exc:
            print(f"  Failed to plot {piezometer_id}: {exc}")


if __name__ == "__main__":
    main()
