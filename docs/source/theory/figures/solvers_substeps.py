"""Head error against the number of steps in a period, on a confined column.

The column, its forcing and the error are those of the validation case
tests/validation/analytical/transient/test_stress_period_substepping.py. The
case is linear, so the backward Euler steps below are the discrete equations
MODFLOW 6 solves for it; no solver runs at build time.
"""

import matplotlib.pyplot as plt
import numpy as np
from scipy.linalg import solve_banded
from scipy.special import erfc

# The constants of the validation case.
NCOL, DX, K, THICKNESS, SS = 200, 5.0, 1.0e-6, 10.0, 1.0e-4
PERIOD, HEAD_STEP = 31.0 * 86400.0, 1.0
DIFFUSIVITY = K * THICKNESS / (SS * THICKNESS)
x = (np.arange(NCOL) + 0.5) * DX
exact = HEAD_STEP * erfc(x[1:] / (2.0 * np.sqrt(DIFFUSIVITY * PERIOD)))

conductance = K * THICKNESS * 1.0 / DX  # m2/s between two cells of width 1 m
storage = SS * THICKNESS * DX * 1.0  # m2 per cell


def end_of_period_rmse(nstp, tsmult=1.0):
    """Backward Euler over one period, head 1 m imposed in the first cell."""
    if tsmult == 1.0:
        steps = np.full(nstp, PERIOD / nstp)
    else:
        first = PERIOD * (tsmult - 1.0) / (tsmult**nstp - 1.0)
        steps = first * tsmult ** np.arange(nstp)
    head = np.zeros(NCOL)
    head[0] = HEAD_STEP
    for dt in steps:
        n = NCOL - 1  # unknowns: every cell but the imposed one
        diag = np.full(n, storage / dt + 2.0 * conductance)
        diag[-1] = storage / dt + conductance  # no flow past the last cell
        bands = np.zeros((3, n))
        bands[0, 1:] = -conductance
        bands[1] = diag
        bands[2, :-1] = -conductance
        rhs = storage / dt * head[1:]
        rhs[0] += conductance * HEAD_STEP
        head[1:] = solve_banded((1, 1), bands, rhs)
    return float(np.sqrt(np.mean((head[1:] - exact) ** 2)))


counts = np.array([1, 2, 3, 5, 10, 20, 30, 50])
rmse = np.array([end_of_period_rmse(int(n)) for n in counts])
growing = end_of_period_rmse(10, tsmult=2.0)
shrinking = end_of_period_rmse(10, tsmult=0.5)
space_only = end_of_period_rmse(1000)  # the time error is gone: what is left is the grid

fig, ax = plt.subplots(figsize=(6.4, 3.6))
ax.axhline(space_only, color="C6", lw=1.0, ls=":", label="error of the 5 m cells alone")
ax.loglog(counts, rmse, "o-", color="C0", label="equal steps")
ax.plot(10, growing, "^", color="C1", ms=9, label="10 steps growing by 2")
ax.plot(10, shrinking, "v", color="C2", ms=6, label="10 steps shrinking by 2")
ax.annotate(
    f"1 step: {rmse[0] / rmse[counts == 10][0]:.0f} times\nthe error of 10",
    (1, rmse[0]),
    xytext=(14, -8),
    textcoords="offset points",
    va="top",
)
ax.set_xlabel(r"steps per period $n_\mathrm{sub}$")
ax.set_ylabel("head RMSE at the end of the period (m)")
ax.set_xticks(counts, [str(n) for n in counts])
ax.legend(loc="upper right", frameon=False, fontsize=9)
fig.tight_layout()
