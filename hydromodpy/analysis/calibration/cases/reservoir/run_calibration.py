# -*- coding: utf-8 -*-
"""
End-to-end calibration example for one- and two-reservoir reference cases.

Run from repository root:
    python hydromodpy/analysis/calibration/cases/reservoir/run_calibration.py
    python hydromodpy/analysis/calibration/cases/reservoir/run_calibration.py --preset one_reservoir

Didactic workflow
-----------------
1) Read and validate TOML configuration.
2) Build one synthetic chronicle:
   - forcing (precipitation + optional losses),
   - "true" model response,
   - noisy observations used for calibration.
3) Run calibration with the selected method.
4) Print a compact numerical summary.
5) Save and optionally display the diagnostic figure.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

# Ensure repository root is importable when script is launched directly.
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.analysis.calibration.core.case_orchestrator import (
    run_calibration_case_from_toml,
)
from hydromodpy.analysis.calibration.cases.reservoir.case_implementation import (
    CASE_IMPLEMENTATION,
)
from hydromodpy.analysis.calibration.cases.reservoir.workflow import get_model_display_name
from hydromodpy.analysis.calibration.cases.reservoir.plotting import plot_calibration_result


DEFAULT_CONFIG_FILE = "config_calibration_two_reservoir.toml"
ONE_RESERVOIR_CONFIG_FILE = "config_calibration_one_reservoir.toml"
CONFIG_PRESETS = {
    "three_params": DEFAULT_CONFIG_FILE,
    "one_reservoir": ONE_RESERVOIR_CONFIG_FILE,
}


def _print_calibration_summary(calibration):
    """
    Print the key numbers needed to interpret one calibration run.

    The summary is intentionally short:
    - setup (model/metric/method),
    - computational effort (direct evaluations and elapsed time),
    - parameter recovery (true vs estimated),
    - hydrological scores.
    """
    model_name = calibration["model_name"]
    metrics = calibration["metrics"]
    result = calibration["result"]

    print("Calibration summary")
    print(f"  model            : {get_model_display_name(model_name)}")
    print(f"  objective metric : {calibration['objective_metric']}")
    print(f"  method           : {calibration['method']}")
    print(f"  n evaluations    : {int(result.n_evaluations)}")
    elapsed_seconds = result.metadata.get("calibration_time_seconds")
    if elapsed_seconds is not None:
        try:
            elapsed_seconds = float(elapsed_seconds)
        except (TypeError, ValueError):
            elapsed_seconds = None
    if elapsed_seconds is not None and elapsed_seconds >= 0.0:
        print(f"  calib time [s]   : {elapsed_seconds:.3f}")
    for name in calibration["parameter_names"]:
        true_value = calibration["params_true"][name]
        best_value = calibration["params_best"][name]
        print(f"  {name} true / hat     : {true_value:.6f} / {best_value:.6f}")
    print(f"  NSE              : {metrics['NSE']:.6f}")
    print(f"  NSElog           : {metrics['NSElog']:.6f}")
    print(f"  KGE              : {metrics['KGE']:.6f}")
    print(f"  r, alpha, beta   : {metrics['r']:.6f}, {metrics['alpha']:.6f}, {metrics['beta']:.6f}")


def _parse_args(argv=None):
    """
    Parse command-line options for calibration config selection.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Run reservoir calibration from TOML configuration. "
            "By default uses the 3-parameter two-reservoir preset."
        )
    )
    parser.add_argument(
        "--preset",
        choices=tuple(CONFIG_PRESETS.keys()),
        default="three_params",
        help=(
            "Named configuration preset. "
            "'three_params' (default) uses two_reservoir; "
            "'one_reservoir' uses one_reservoir + objective surface."
        ),
    )
    parser.add_argument(
        "--config-file",
        default=None,
        help=(
            "Optional explicit TOML filename or path. "
            "If provided, it overrides --preset."
        ),
    )
    return parser.parse_args(argv)


def _resolve_config_path(args):
    """
    Resolve selected TOML path from CLI arguments.
    """
    if args.config_file:
        raw = Path(str(args.config_file))
        if raw.is_absolute():
            return raw
        return (Path(__file__).resolve().parent / raw).resolve()
    return Path(__file__).with_name(CONFIG_PRESETS[args.preset])


def main(argv=None):
    """
    Run the complete TOML-driven reservoir calibration example.
    """
    # Step 1: run case calibration through the generic case orchestrator.
    args = _parse_args(argv)
    config_path = _resolve_config_path(args)
    print(f"Using config: {config_path}")
    calibration = run_calibration_case_from_toml(
        config_path=config_path,
        case_implementation=CASE_IMPLEMENTATION,
    )

    # Step 2: report scalar diagnostics in terminal.
    _print_calibration_summary(calibration)

    # Step 3: resolve output figure settings.
    output_cfg = calibration["config"].get("output", {})
    out_subdir = str(output_cfg.get("output_dir", "outputs"))
    show_plot = bool(output_cfg.get("show_plot", True))
    out_dir = Path(__file__).resolve().parent / out_subdir
    model_name = calibration["model_name"]
    default_name = (
        "reservoir_calibration_"
        f"{model_name}_{calibration['objective_metric']}_{calibration['method']}.png"
    )
    figure_name = str(output_cfg.get("figure_name", default_name))
    output_png = out_dir / figure_name

    # Step 4: render and save full diagnostic plot.
    plot_calibration_result(
        chronicle=calibration["chronicle"],
        calibration=calibration,
        output_png=output_png,
        show_plot=show_plot,
    )
    print(f"Saved figure: {output_png}")


if __name__ == "__main__":
    main()

