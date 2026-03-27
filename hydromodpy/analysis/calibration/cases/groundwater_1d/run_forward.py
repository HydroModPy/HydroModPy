"""
Forward-only script for the transient 1D groundwater case.

Run from repository root:
    python hydromodpy/analysis/calibration/cases/groundwater_1d/run_forward.py
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np

# Ensure repository root is importable when script is launched directly.
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.analysis.calibration.core.engine_config import load_calibration_toml
from hydromodpy.analysis.calibration.cases.groundwater_1d.workflow import (
    build_noisy_groundwater_chronicle,
)


DEFAULT_CONFIG_FILE = "config_calibration.toml"


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run forward simulation for groundwater_1d.")
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


def main(argv=None):
    args = _parse_args(argv)
    config_path = _resolve_config_path(args)
    cfg = load_calibration_toml(config_path)
    chronicle = build_noisy_groundwater_chronicle(cfg["chronicle"])

    t = np.asarray(chronicle["t"], dtype=float)
    x = np.asarray(chronicle["x"], dtype=float)
    h_true = np.asarray(chronicle["h_true"], dtype=float)
    recharge = np.asarray(chronicle["recharge_series"], dtype=float)

    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8), dpi=140)
    ax_ts, ax_profile = axes

    midpoint_nodes = np.asarray(chronicle["midpoint_node_indices"], dtype=int)
    midpoint_x = np.asarray(chronicle["midpoint_x_m"], dtype=float)
    colors = ("tab:blue", "tab:orange")
    labels = ("upstream midpoint", "downstream midpoint")
    for node, xj, color, label in zip(midpoint_nodes, midpoint_x, colors, labels):
        ax_ts.plot(t, h_true[:, int(node)], color=color, lw=2.0, label=f"Head ({label}, x={xj:.1f} m)")

    ax_ts.set_xlabel("Time [day]")
    ax_ts.set_ylabel("Head [m]")
    ax_ts.set_title("Heads at zone midpoints")
    ax_ts.grid(True, ls=":", alpha=0.45)

    ax_ts_right = ax_ts.twinx()
    ax_ts_right.plot(t, recharge, color="tab:green", lw=1.8, ls="--", label="Recharge R(t)")
    ax_ts_right.set_ylabel("Recharge [m/day]", color="tab:green")
    ax_ts_right.tick_params(axis="y", labelcolor="tab:green")

    handles_left, labels_left = ax_ts.get_legend_handles_labels()
    handles_right, labels_right = ax_ts_right.get_legend_handles_labels()
    ax_ts.legend(handles_left + handles_right, labels_left + labels_right, loc="best", fontsize=8)

    profile_times = np.linspace(0, t.size - 1, 5, dtype=int)
    profile_times = np.unique(profile_times)
    cmap = plt.get_cmap("plasma")
    for k, it in enumerate(profile_times):
        color = cmap(k / max(profile_times.size - 1, 1))
        ax_profile.plot(x, h_true[it], color=color, lw=2.0, label=f"t={t[it]:.0f} d")

    ax_profile.axvline(float(chronicle["true_params"]["xi"]), color="k", ls=":", lw=1.4, label="xi")
    ax_profile.set_xlabel("x [m]")
    ax_profile.set_ylabel("Head [m]")
    ax_profile.set_title("Profiles h(x) at several times")
    ax_profile.grid(True, ls=":", alpha=0.45)
    ax_profile.legend(loc="best", fontsize=8, ncol=2)

    fig.suptitle("Transient 1D unconfined-aquifer forward run")
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    plt.show()


if __name__ == "__main__":
    main()

