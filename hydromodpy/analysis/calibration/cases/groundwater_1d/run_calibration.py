"""
End-to-end calibration script for the transient 1D groundwater case.

Run from repository root:
    python hydromodpy/analysis/calibration/cases/groundwater_1d/run_calibration.py
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import numpy as np

# Ensure repository root is importable when script is launched directly.
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.analysis.calibration.core.case_orchestrator import (
    run_calibration_case_from_toml,
)
from hydromodpy.analysis.calibration.cases.groundwater_1d.case_implementation import (
    CASE_IMPLEMENTATION,
)
from hydromodpy.analysis.calibration.cases.groundwater_1d.plotting import (
    plot_calibration_result,
)


DEFAULT_CONFIG_FILE = "config_calibration.toml"


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Run transient 1D groundwater calibration from TOML configuration."
    )
    parser.add_argument(
        "--config-file",
        default=None,
        help="Optional explicit TOML filename/path. Defaults to config_calibration.toml.",
    )
    return parser.parse_args(argv)


def _resolve_config_path(args):
    if args.config_file:
        raw = Path(str(args.config_file))
        if raw.is_absolute():
            return raw
        return (Path(__file__).resolve().parent / raw).resolve()
    return Path(__file__).with_name(DEFAULT_CONFIG_FILE)


def _print_summary(calibration):
    result = calibration["result"]
    metrics = calibration["metrics"]

    print("Calibration summary")
    print(f"  case             : groundwater_1d")
    print(f"  objective metric : {calibration['objective_metric']}")
    print(f"  method           : {calibration['method']}")
    print(f"  n evaluations    : {int(result.n_evaluations)}")

    elapsed = result.metadata.get("calibration_time_seconds")
    if elapsed is not None:
        try:
            elapsed = float(elapsed)
        except (TypeError, ValueError):
            elapsed = None
    if elapsed is not None and np.isfinite(elapsed) and elapsed >= 0.0:
        print(f"  calib time [s]   : {elapsed:.3f}")

    for name in calibration["parameter_names"]:
        true_value = calibration["params_true"][name]
        best_value = calibration["params_best"][name]
        print(f"  {name} true / hat: {true_value:.6f} / {best_value:.6f}")

    print(f"  NSE              : {metrics['NSE']:.6f}")
    print(f"  NSElog           : {metrics['NSElog']:.6f}")
    print(f"  KGE              : {metrics['KGE']:.6f}")
    print(f"  r, alpha, beta   : {metrics['r']:.6f}, {metrics['alpha']:.6f}, {metrics['beta']:.6f}")


def main(argv=None):
    args = _parse_args(argv)
    config_path = _resolve_config_path(args)
    print(f"Using config: {config_path}")

    calibration = run_calibration_case_from_toml(
        config_path=config_path,
        case_implementation=CASE_IMPLEMENTATION,
    )
    _print_summary(calibration)

    output_cfg = calibration["config"].get("output", {})
    out_subdir = str(output_cfg.get("output_dir", "outputs"))
    show_plot = bool(output_cfg.get("show_plot", True))
    out_dir = Path(__file__).resolve().parent / out_subdir

    default_name = (
        "groundwater_1d_calibration_"
        f"{calibration['objective_metric']}_{calibration['method']}.png"
    )
    figure_name = str(output_cfg.get("figure_name", default_name))
    output_png = out_dir / figure_name

    plot_calibration_result(
        chronicle=calibration["chronicle"],
        calibration=calibration,
        output_png=output_png,
        show_plot=show_plot,
    )
    print(f"Saved figure: {output_png}")


if __name__ == "__main__":
    main()


