"""
Forcing-only viewer for the transient 1D groundwater case.

Run from repository root:
    python hydromodpy/calibration/cases/groundwater_1d/run_forcing.py
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

# Ensure repository root is importable when script is launched directly.
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.calibration.core.engine_config import load_calibration_toml
from hydromodpy.calibration.cases.groundwater_1d.plotting import (
    plot_forcing_chronicle,
)
from hydromodpy.calibration.cases.groundwater_1d.workflow import (
    build_noisy_groundwater_chronicle,
)


DEFAULT_CONFIG_FILE = "config_calibration.toml"
DEFAULT_FIGURE_NAME = "groundwater_1d_forcing.png"


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Visualize only the forcing chronicle used by groundwater_1d."
    )
    parser.add_argument(
        "--config-file",
        default=None,
        help="Optional explicit TOML filename/path. Defaults to config_calibration.toml.",
    )
    parser.add_argument(
        "--output-file",
        default=None,
        help="Optional explicit PNG filename/path. Defaults to outputs/groundwater_1d_forcing.png.",
    )
    return parser.parse_args(argv)


def _resolve_config_path(args):
    if args.config_file:
        raw = Path(str(args.config_file))
        if raw.is_absolute():
            return raw
        return (Path(__file__).resolve().parent / raw).resolve()
    return Path(__file__).with_name(DEFAULT_CONFIG_FILE)


def _resolve_output_path(args, output_cfg):
    if args.output_file:
        raw = Path(str(args.output_file))
        if raw.is_absolute():
            return raw
        return raw.resolve()

    out_subdir = str(output_cfg.get("output_dir", "outputs"))
    out_dir = Path(__file__).resolve().parent / out_subdir
    return out_dir / DEFAULT_FIGURE_NAME


def main(argv=None):
    args = _parse_args(argv)
    config_path = _resolve_config_path(args)
    cfg = load_calibration_toml(config_path)
    chronicle = build_noisy_groundwater_chronicle(cfg["chronicle"])

    output_cfg = cfg.get("output", {})
    output_png = _resolve_output_path(args, output_cfg)
    show_plot = bool(output_cfg.get("show_plot", True))

    mode = str(chronicle["forcing_metadata"].get("recharge_mode", "unknown"))
    print(f"Using config: {config_path}")
    print(f"Forcing mode: {mode}")

    plot_forcing_chronicle(
        chronicle=chronicle,
        output_png=output_png,
        show_plot=show_plot,
    )
    print(f"Saved figure: {output_png}")


if __name__ == "__main__":
    main()
