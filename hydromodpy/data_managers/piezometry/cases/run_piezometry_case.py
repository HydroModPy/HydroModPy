"""Run an end-to-end piezometry station-set case from TOML configuration."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

# Support direct execution from file path and ensure local package precedence.
repo_root = Path(__file__).resolve().parents[4]
if (repo_root / "hydromodpy").exists() and str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from hydromodpy.data_managers.common.utils import safe_file_token
from hydromodpy.data_managers.piezometry.piezometer_set import PiezometerSet
from hydromodpy.data_managers.piezometry.piezometry_config import load_piezometry_toml


def _safe_id_token(value: str) -> str:
    """Return a filesystem-safe token for one piezometer id."""
    return safe_file_token(value)


def _fmt_date_or_none(value):
    """Return YYYY-MM-DD string or None."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.strftime("%Y-%m-%d")


def _default_case_dir() -> Path:
    return Path(__file__).resolve().parent


def _resolve_case_paths(
    *,
    config_path: Path | None,
    outputs_dir: Path | None,
) -> tuple[Path, Path]:
    case_dir = _default_case_dir()
    resolved_config = (
        (case_dir / "run_piezometry_config.toml")
        if config_path is None
        else Path(config_path).expanduser().resolve()
    )
    resolved_outputs = (
        (case_dir / "outputs")
        if outputs_dir is None
        else Path(outputs_dir).expanduser().resolve()
    )
    resolved_outputs.mkdir(parents=True, exist_ok=True)
    return resolved_config, resolved_outputs


def main_piezometer_set(
    *,
    config_path: Path | None = None,
    outputs_dir: Path | None = None,
    show_plots: bool = False,
) -> None:
    """Execute the piezometry discovery workflow from a TOML config."""
    config_file, output_folder = _resolve_case_paths(
        config_path=config_path,
        outputs_dir=outputs_dir,
    )

    print("=" * 70)
    print("PIEZOMETRY CASE - MASK OR STATION WORKFLOW")
    print("=" * 70)

    try:
        piezometers = PiezometerSet.from_toml(config_file)
    except Exception as exc:
        print(f"Error: failed to load config: {exc}")
        return

    print(f"\n[Config] Measurement type : {piezometers.measurement}")
    if piezometers.date_start or piezometers.date_end:
        print(f"[Config] Date range       : {piezometers.date_start} -> {piezometers.date_end}")

    piezometers.get_completeness_report()

    if not piezometers.piezometers:
        print("\nNo loaded piezometric data available.")
        print("\nTips:")
        print("  - Check TOML station IDs or mask path.")
        print("  - Use PiezometerSet.discover_piezometer_ids() for geographic search.")
        print("  - Use require_observations=True to filter by data availability.")
        return

    piezometer_ids = sorted(piezometers.piezometers.keys())
    print("\n" + "=" * 70)
    print("DISCOVERED PIEZOMETERS")
    print("=" * 70)
    print(f"Total: {len(piezometer_ids)} piezometer(s)")
    for idx, piezometer_id in enumerate(piezometer_ids[:10], 1):
        print(f"  {idx}. {piezometer_id}")
    if len(piezometer_ids) > 10:
        print(f"  ... and {len(piezometer_ids) - 10} more")

    print("\n" + "=" * 70)
    print("EXPORTING PLOTS")
    print("=" * 70)
    for piezometer_id in piezometer_ids:
        output_path = output_folder / f"piezometer_plot_{_safe_id_token(piezometer_id)}.png"
        try:
            piezometers.plot_piezometer(
                piezometer_id=piezometer_id,
                output_path=output_path,
                show=bool(show_plots),
            )
            print(f"  OK exported: {output_path.name}")
        except Exception as exc:
            print(f"  FAIL plot {piezometer_id}: {exc}")


def main_piezometer(
    *,
    config_path: Path | None = None,
    outputs_dir: Path | None = None,
    show_plot: bool = False,
) -> None:
    """Exercise one loaded piezometer object for diagnostics."""
    config_file, output_folder = _resolve_case_paths(
        config_path=config_path,
        outputs_dir=outputs_dir,
    )

    print("=" * 70)
    print("PIEZOMETRY PIEZOMETER OBJECT CHECK")
    print("=" * 70)

    try:
        config_data = load_piezometry_toml(config_file)
        selection_cfg = config_data.get("selection", {})
        selection_mode = selection_cfg.get("mode", "stations")
        mask_path = selection_cfg.get("mask_path")
        piezometry_cfg = config_data.get("piezometry", {})

        date_start = _fmt_date_or_none(piezometry_cfg.get("date_start"))
        date_end = _fmt_date_or_none(piezometry_cfg.get("date_end"))
    except Exception as exc:
        print(f"[Error] Failed to load config: {exc}")
        return

    print("\n[Loading] Loading piezometric data...")
    try:
        if selection_mode == "mask" and mask_path:
            discovered = PiezometerSet.discover_piezometer_ids(
                mask_path=mask_path,
                require_observations=False,
                date_start=date_start,
                date_end=date_end,
                max_ids=5,
                fallback_search_radius_km=20.0,
                timeout=60,
            )
        else:
            print("[Error] This check requires selection.mode='mask' in config")
            return

        if not discovered:
            print("[Error] No piezometers discovered")
            return

        piezometers = PiezometerSet(
            measurement=piezometry_cfg.get("measurement", "level"),
            id=discovered,
            display=piezometry_cfg.get("display", False),
            date_start=date_start,
            date_end=date_end,
            output=None,
            source_mode="api",
        )
    except Exception as exc:
        print(f"[Error] Loading failed: {exc}")
        return

    if not piezometers.piezometers:
        print("[Error] No piezometers loaded")
        return

    piezometer_id = sorted(piezometers.piezometers.keys())[0]
    print(f"\n[Test] Piezometer object check for: {piezometer_id}")
    print("=" * 70)

    piezometer = piezometers.piezometers[piezometer_id]

    print("\n1) BASIC INFO")
    print(f"   ID: {piezometer.piezometer_id}")
    print(f"   Measurement type: {piezometer.measurement}")
    print(f"   Label: {piezometer.build_label()}")

    print("\n2) METADATA")
    if piezometer.metadata:
        for key, value in sorted(piezometer.metadata.items())[:5]:
            print(f"   {key}: {value}")
        if len(piezometer.metadata) > 5:
            print(f"   ... and {len(piezometer.metadata) - 5} more keys")
    else:
        print("   No metadata available")

    print("\n3) SPATIAL INFORMATION")
    if piezometer.station_position:
        print(f"   Position: {piezometer.station_position}")
    else:
        print("   No position data")
    if piezometer.georeferencing:
        print(f"   Georeferencing: {piezometer.georeferencing}")

    print("\n4) DATA SUMMARY")
    if not piezometer.data.empty:
        print(f"   Records: {len(piezometer.data)}")
        print(
            "   Date range: "
            f"{piezometer.data['date_measure'].min()} to {piezometer.data['date_measure'].max()}"
        )
        print(f"   Columns: {', '.join(piezometer.data.columns.tolist())}")
    else:
        print("   No data loaded")

    print("\n5) DATA COMPLETENESS")
    try:
        completeness = piezometer.completeness(verbose=False)
        print(f"   Total expected days: {completeness.get('expected_days', 0)}")
        print(f"   Actual days with data: {completeness.get('actual_days', 0)}")
        print(f"   Missing days: {completeness.get('missing_days', 0)}")
        print(f"   Completeness: {completeness.get('completeness_pct', 0.0):.1f}%")
        print(f"   Gaps detected: {completeness.get('gaps_detected', 0)}")
    except Exception as exc:
        print(f"   Error computing completeness: {exc}")

    print("\n6) PLOTTING")
    try:
        plot_output = output_folder / f"piezometer_test_{_safe_id_token(piezometer_id)}.png"
        piezometer.plot(output_path=plot_output, show=bool(show_plot))
        print(f"   OK plot saved to: {plot_output.name}")
    except Exception as exc:
        print(f"   FAIL plotting: {exc}")

    print("\n" + "=" * 70)
    print("[Success] Piezometer object check completed")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run piezometry case workflows from TOML configuration."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Optional path to piezometry TOML config (default: cases/run_piezometry_config.toml).",
    )
    parser.add_argument(
        "--outputs-dir",
        type=Path,
        default=None,
        help="Optional directory for generated figures (default: cases/outputs).",
    )
    parser.add_argument(
        "--mode",
        choices=("set", "piezometer", "both"),
        default="both",
        help="Run only set workflow, only piezometer check, or both.",
    )
    parser.add_argument(
        "--show-plots",
        action="store_true",
        help="Display interactive plots (disabled by default).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.mode in ("set", "both"):
        main_piezometer_set(
            config_path=args.config,
            outputs_dir=args.outputs_dir,
            show_plots=args.show_plots,
        )

    if args.mode == "both":
        print("\n" + "#" * 70 + "\n")

    if args.mode in ("piezometer", "both"):
        main_piezometer(
            config_path=args.config,
            outputs_dir=args.outputs_dir,
            show_plot=args.show_plots,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

