# -*- coding: utf-8 -*-
"""
Minimal example for the linear reservoir model.

Run from repository root:
    python hydromodpy/calibration2/cases/reservoir/run_linear_smoke.py
"""

from __future__ import annotations

from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np

# Ensure repository root is importable when script is launched directly.
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.calibration2.cases.reservoir.models.one_reservoir import ReservoirModel


def qin_sine(t):
    """Example inflow signal Qin(t) [mm/day]."""
    return 2.0 + np.sin(t)


def main():
    # Reservoir parameters.
    capacity_mm = 4.5  # C [mm]
    k_per_day = 0.5  # Qout = k * S [1/day]
    s0_mm = 4.0  # initial storage [mm]

    model = ReservoirModel(capacity=capacity_mm, k=k_per_day)

    t_eval = np.linspace(0.0, 20.0, 1000)
    t, storage_mm, qout_mm_day = model.simulate(
        qin_func=qin_sine,
        s0=s0_mm,
        t_span=(0.0, 20.0),
        t_eval=t_eval,
    )
    qin_values = np.array([qin_sine(ti) for ti in t], dtype=float)

    fig, axes = plt.subplots(2, 1, figsize=(9, 6), sharex=True, dpi=130)

    ax0 = axes[0]
    ax0.plot(t, qin_values, label="Qin(t)", color="tab:blue", lw=2.0)
    ax0.plot(t, qout_mm_day, label="Qout(t)", color="tab:orange", lw=2.0)
    ax0.set_ylabel("Flow [mm/day]")
    ax0.set_title("Linear reservoir (lame d'eau): inflow vs outflow")
    ax0.grid(True, ls=":", alpha=0.5)
    ax0.legend(loc="best")

    ax1 = axes[1]
    ax1.plot(t, storage_mm, label="S(t)", color="tab:green", lw=2.0)
    ax1.axhline(capacity_mm, color="0.4", ls="--", lw=1.2, label="Capacity C")
    ax1.set_xlabel("Time")
    ax1.set_ylabel("Storage [mm]")
    ax1.grid(True, ls=":", alpha=0.5)
    ax1.legend(loc="best")

    fig.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
