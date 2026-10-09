"""The lower obstacle on the one cell of its validation test.

The cell, the well and the step are those of
test_single_cell_pumping_activates_lower_obstacle; the residual comes from the
assembly of the code. q_dry = 0.008 m/s is the value the test asserts, since
the PETSc solve does not run at build time.
"""

from types import SimpleNamespace

import matplotlib.pyplot as plt
import numpy as np

from hydromodpy.solver.boussinesq.assembly import (
    assemble_transient_residual_with_saturation_excess,
)
from hydromodpy.solver.boussinesq.runtimes.petsc_mixed import _assembly_with_dry_deficit

none_int, none_float = np.asarray([], dtype=int), np.asarray([], dtype=float)
cell = SimpleNamespace(
    n_cells=1,
    n_edges=0,
    cell_area_m2=np.array([1.0]),
    z_top_m=np.array([2.0]),
    z_bottom_m=np.array([0.0]),
    hydraulic_conductivity_m_s=np.array([1.0]),
    storage_coefficient=np.array([0.2]),
    edge_ids=none_int,
    edge_cell_a=none_int,
    edge_cell_b=none_int,
    edge_length_m=none_float,
    edge_distance_m=none_float,
    edge_midpoint_distance_to_cell_a_m=none_float,
    edge_midpoint_distance_to_cell_b_m=none_float,
)
H_OLD, DT, WELL, Q_DRY = 0.1, 10.0, -0.01, 0.008


def residual(h, q_dry=0.0):
    """Residual of the cell at head h, in m3/s, positive when it loses water."""
    assembly = assemble_transient_residual_with_saturation_excess(
        cell,
        head_m=np.array([h]),
        head_prev_m=np.array([H_OLD]),
        dt_seconds=DT,
        recharge_rate_m_s=0.0,
        well_flux_m3_s=np.array([WELL]),
        saturation_excess_rate_m_s=np.array([0.0]),
    )
    if q_dry:
        assembly = _assembly_with_dry_deficit(
            cell, assembly, np.array([q_dry]), prescribed_mask=np.array([False])
        )
    return float(assembly.residual_m3_s[0])


h = np.linspace(-0.6, 0.4, 201)
fig, (balance, budget) = plt.subplots(
    1, 2, figsize=(6.4, 3.4), gridspec_kw={"width_ratios": [2.2, 1]}
)
balance.axvspan(-0.6, 0.0, color="C6", alpha=0.08, lw=0)
balance.axhline(0.0, color="C6", lw=0.8)
slope = 0.2 / DT
balance.plot(
    h, slope * (h - H_OLD) - WELL, color="C6", ls=":", lw=1.2, label="storage without a floor"
)
balance.plot(h, [residual(v) for v in h], color="C0", lw=2.0, label=r"$R(h)$, the code")
admissible = h[h >= 0.0]
balance.plot(
    admissible,
    [residual(v, Q_DRY) for v in admissible],
    color="C1",
    lw=1.6,
    ls="--",
    label=r"$R - a\,q^\mathrm{dry}$",
)
balance.plot([H_OLD + WELL / slope], [0.0], "x", color="C6", ms=8)
balance.plot([0.0], [0.0], "o", color="C1", ms=6)
balance.annotate(
    "", (0.0, 0.0), (0.0, residual(0.0)), arrowprops={"arrowstyle": "<->", "color": "C1"}
)
balance.text(0.02, 0.5 * residual(0.0), r"$a\,q^\mathrm{dry}$", color="C1", va="center")
balance.text(-0.58, 0.0135, "below the bottom", fontsize=8)
balance.set_xlabel(r"head $h$ (m), bottom at 0")
balance.set_ylabel(r"residual (m$^3$/s)")
balance.set_ylim(-0.006, 0.016)
balance.legend(loc="upper left", bbox_to_anchor=(0.0, 0.9), fontsize=8, frameon=False)
balance.set_title("The balance has no admissible root", fontsize=10)

storage = residual(0.0) + WELL  # what the empty cell releases, negative
parts = [(-storage, "from storage", "C5"), (Q_DRY * 1.0, r"unmet: $a\,q^\mathrm{dry}$", "C1")]
bottom = 0.0
for value, label, color in parts:
    budget.bar(0, value, bottom=bottom, color=color, width=0.6)
    budget.text(
        0,
        bottom + 0.5 * value,
        f"{label}\n{value:.3f}",
        ha="center",
        va="center",
        fontsize=8,
    )
    bottom += value
budget.set_xticks([0], [f"well, {-WELL:g}"])
budget.set_xlim(-0.6, 0.6)
budget.set_ylabel(r"pumped rate (m$^3$/s)")
budget.grid(axis="x", visible=False)
budget.set_title("Where the well\nwater comes from", fontsize=10)
fig.tight_layout()
