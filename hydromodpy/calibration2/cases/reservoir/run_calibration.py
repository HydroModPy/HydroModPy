# -*- coding: utf-8 -*-
"""
End-to-end calibration example for one- and two-reservoir reference cases.

Run from repository root:
    python hydromodpy/calibration2/cases/reservoir/run_calibration.py
"""

from __future__ import annotations

from pathlib import Path
import sys

# Ensure repository root is importable when script is launched directly.
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.calibration2.core.config import load_calibration_toml
from hydromodpy.calibration2.cases.reservoir.workflow import (
    calibrate_reservoir_model,
    get_model_display_name,
    resolve_model_name,
)
from hydromodpy.calibration2.cases.reservoir.plotting import plot_calibration_result
from hydromodpy.calibration2.cases.reservoir.synthetic_data import build_noisy_reservoir_chronicle


DEFAULT_CONFIG_FILE = "config_calibration.toml"


def _print_calibration_summary(calibration):
    """Print compact calibration summary to stdout."""
    model_name = calibration["model_name"]
    metrics = calibration["metrics"]

    print("Calibration summary")
    print(f"  model            : {get_model_display_name(model_name)}")
    print(f"  objective metric : {calibration['objective_metric']}")
    print(f"  method           : {calibration['method']}")
    for name in calibration["parameter_names"]:
        true_value = calibration["params_true"][name]
        best_value = calibration["params_best"][name]
        print(f"  {name} true / hat     : {true_value:.6f} / {best_value:.6f}")
    print(f"  NSE              : {metrics['NSE']:.6f}")
    print(f"  NSElog           : {metrics['NSElog']:.6f}")
    print(f"  KGE              : {metrics['KGE']:.6f}")
    print(f"  r, alpha, beta   : {metrics['r']:.6f}, {metrics['alpha']:.6f}, {metrics['beta']:.6f}")


def main():
    """Run the complete reservoir calibration workflow."""
    config_path = Path(__file__).with_name(DEFAULT_CONFIG_FILE)
    config = load_calibration_toml(config_path)
    model_name = resolve_model_name(config)

    chronicle = build_noisy_reservoir_chronicle(config["chronicle"], model_name=model_name)
    calibration = calibrate_reservoir_model(chronicle, config, model_name=model_name)

    _print_calibration_summary(calibration)

    output_cfg = config.get("output", {})
    out_subdir = str(output_cfg.get("output_dir", "outputs"))
    show_plot = bool(output_cfg.get("show_plot", True))
    out_dir = Path(__file__).resolve().parent / out_subdir
    default_name = (
        "reservoir_calibration_"
        f"{model_name}_{calibration['objective_metric']}_{calibration['method']}.png"
    )
    figure_name = str(output_cfg.get("figure_name", default_name))
    output_png = out_dir / figure_name

    plot_calibration_result(
        chronicle=chronicle,
        calibration=calibration,
        output_png=output_png,
        show_plot=show_plot,
    )
    print(f"Saved figure: {output_png}")


if __name__ == "__main__":
    main()
