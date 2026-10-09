"""When a cyclic spin-up stops, decided by cycles_have_settled."""

from types import SimpleNamespace

import matplotlib.pyplot as plt
import numpy as np

from hydromodpy.physics.flow.initial_conditions import FlowInitialConditions
from hydromodpy.solver.steady_initial_conditions import (
    cycles_have_settled,
    cyclic_spinup_strategy,
)

flow = SimpleNamespace(
    initial_conditions=FlowInitialConditions.model_validate({"h": {"type": "spinup_cyclic"}})
)
strategy = cyclic_spinup_strategy(flow)

# Heads at the end of each cycle, for 200 cells that drift towards their settled
# state. Most cells settle fast; a compartment of 10 cells drifts slowly.
cycles = np.arange(1, 13)
rate = np.full(200, 0.15)
rate[:10] = 0.55
gap = np.full(200, 2.0)
gap[:10] = 1.5
ends = [100.0 + gap * rate ** (c - 1) for c in cycles]

largest = [np.nan] + [np.max(np.abs(b - a)) for a, b in zip(ends, ends[1:], strict=False)]
mean = [np.nan] + [np.mean(np.abs(b - a)) for a, b in zip(ends, ends[1:], strict=False)]
settled = next(
    c
    for c, a, b in zip(cycles[1:], ends, ends[1:], strict=False)
    if cycles_have_settled(a, b, tol_head_m=strategy.tol_head_m)
)

fig, ax = plt.subplots(figsize=(6.4, 3.6))
ax.semilogy(cycles, largest, "o-", color="C1", label="largest change, the test")
ax.semilogy(cycles, mean, "s--", color="C0", ms=4, label="mean change, not the test")
ax.axhline(strategy.tol_head_m, color="C6", lw=1.0)
ax.text(
    1.1,
    strategy.tol_head_m * 1.3,
    rf"$\varepsilon_h$ = {strategy.tol_head_m * 100:g} cm",
    va="bottom",
)
ax.axvline(strategy.max_cycles, color="C6", lw=1.0, ls=":")
ax.text(
    strategy.max_cycles,
    3.0,
    f" default max_cycles = {strategy.max_cycles}",
    va="center",
    fontsize=8,
)
ax.annotate(
    f"settled after cycle {settled}",
    (settled, largest[settled - 1]),
    xytext=(-20, -40),
    textcoords="offset points",
    arrowprops={"arrowstyle": "->", "color": "C6"},
)
ax.set_xlabel("cycle $c$")
ax.set_ylabel(r"$|h^{(c)}_\mathrm{end} - h^{(c-1)}_\mathrm{end}|$ (m)")
ax.set_xticks(cycles)
ax.set_ylim(1e-5, 6)
ax.legend(loc="lower left", frameon=False)
fig.tight_layout()
