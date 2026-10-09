"""What the two-point flux drops on a skewed face, and what XT3D buys back.

The share comes from eq-xt3d-split; the trigger from resolve_xt3d_decision;
the errors are the golden reference of test_xt3d_irregular_tri_fast_regression.
"""

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from hydromodpy.solver.modflow6.builders.solver_options import _NONORTH_P95_TRIGGER_DEG

GOLDEN = Path(
    "tests/regression/reference/golden_references/fast/intercomparison/"
    "intercomparison_xt3d_irregular_tri_dupuit_uniform_recharge.json"
)
row = json.loads(GOLDEN.read_text())["intercomparison_expected"]["rows"][
    "dupuit_uniform_recharge_1d"
]

fig, (share, error) = plt.subplots(1, 2, figsize=(6.4, 3.4), gridspec_kw={"width_ratios": [1.4, 1]})
phi = np.linspace(0.0, 60.0, 241)
share.plot(phi, np.tan(np.deg2rad(phi)), color="C0", lw=2.0)
for angle in (15.0, 30.0, 45.0):
    value = np.tan(np.deg2rad(angle))
    share.plot(angle, value, "o", color="C0", ms=5)
    share.annotate(f"{value:.2f}", (angle, value), xytext=(-26, 4), textcoords="offset points")
share.axvline(_NONORTH_P95_TRIGGER_DEG, color="C1", lw=1.2, ls="--")
share.text(_NONORTH_P95_TRIGGER_DEG + 1, 1.5, "trigger\nangle", color="C1", fontsize=9)
share.set_xlabel(r"angle of the connection $\varphi_{nm}$ (degrees)")
share.set_ylabel(r"dropped share, $\tan\varphi_{nm}$")
share.set_title("Tangential gradient left out", fontsize=10)

labels = ["RMSE", "largest error"]
without = [row["rmse_without_xt3d"], row["max_error_without_xt3d"]]
with_xt3d = [row["rmse_with_xt3d"], row["max_error_with_xt3d"]]
x = np.arange(2)
error.bar(x - 0.18, without, width=0.34, color="C6", alpha=0.6, label="without XT3D")
error.bar(x + 0.18, with_xt3d, width=0.34, color="C1", label="with XT3D")
for xi, a, b in zip(x, without, with_xt3d, strict=True):
    error.text(xi - 0.18, a, f"{a:.3f}", ha="center", va="bottom", fontsize=8)
    error.text(xi + 0.18, b, f"{b:.3f}", ha="center", va="bottom", fontsize=8)
error.set_xticks(x, labels)
error.set_ylabel("head error (m)")
error.grid(axis="x", visible=False)
error.set_title("Irregular triangles, Dupuit case", fontsize=10)
error.set_ylim(0, 0.45)
error.legend(loc="upper left", fontsize=8, frameon=False)
fig.tight_layout()
