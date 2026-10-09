"""The smoothed saturated fraction of a drying cell, for the three solvers."""

import matplotlib.pyplot as plt
import numpy as np

from hydromodpy.solver.modflow_nwt.nwt.nwt_config import NwtSolverConfig


def smoothed(sigma, eps):
    """Piecewise quadratic of eq-smoothed-saturation; the plain clip at eps = 0."""
    sigma = np.asarray(sigma, dtype=float)
    if eps == 0.0:
        return np.clip(sigma, 0.0, 1.0)
    a = 1.0 / (1.0 - eps)
    out = np.where(sigma < eps, a * sigma**2 / (2.0 * eps), a * sigma + 0.5 * (1.0 - a))
    out = np.where(sigma >= 1.0 - eps, 1.0 - a * (1.0 - sigma) ** 2 / (2.0 * eps), out)
    out = np.where(sigma >= 1.0, 1.0, out)
    return np.where(sigma <= 0.0, 0.0, out)


# MODFLOW-NWT reads thickfact; MODFLOW 6 fixes satomega at 1e-6 under Newton.
curves = [
    (NwtSolverConfig.model_fields["thickfact"].default, "MODFLOW-NWT", "C0", "-"),
    (1e-6, "MODFLOW 6, Newton", "C1", "--"),
    (0.0, "MODFLOW 6 without Newton,\nBoussinesq", "C6", ":"),
]

fig, (full, zoom) = plt.subplots(1, 2, figsize=(6.4, 3.4))
sigma = np.linspace(-0.2, 1.2, 701)
for eps, label, color, style in curves:
    full.plot(sigma, smoothed(sigma, eps), color=color, ls=style, lw=1.6, label=label)
full.set_xlabel(r"saturated fraction $\sigma$")
full.set_ylabel(r"$\tilde\sigma(\sigma)$")
full.set_title("The whole range: one line", fontsize=10)

scale = 1e-5
sigma = np.linspace(-0.5, 3.0, 701) * scale
for eps, label, color, style in curves:
    zoom.plot(
        sigma / scale, smoothed(sigma, eps) / scale, color=color, ls=style, lw=1.6, label=label
    )
zoom.set_xlabel(r"$\sigma$ ($\times 10^{-5}$)")
zoom.set_ylabel(r"$\tilde\sigma$ ($\times 10^{-5}$)")
zoom.set_title(r"Near the bottom, $\sigma < 3 \times 10^{-5}$", fontsize=10)
zoom.set_xlim(-0.5, 3.0)
zoom.set_ylim(-0.2, 3.0)
fig.tight_layout(rect=(0, 0.1, 1, 1))
handles, labels = zoom.get_legend_handles_labels()
fig.legend(handles, labels, loc="lower center", ncol=3, fontsize=8, frameon=False)
