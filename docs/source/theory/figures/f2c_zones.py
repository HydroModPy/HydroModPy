"""A zone map sampled by the cells, and the mean that FieldParam.to_mesh_field takes."""

import matplotlib.pyplot as plt
import numpy as np

from hydromodpy.data.variables.geology.config import GeologyConfig
from hydromodpy.spatial.field.cases.square.field_mesh_square import FieldMeshSquare
from hydromodpy.spatial.field.cases.square.field_spatial_square import FieldSquare
from hydromodpy.spatial.field.core.cell_sampling import sample_points_in_cell
from hydromodpy.spatial.field.core.field_param import FieldParam

V_A, V_B = 1e-5, 1e-7
N_S = GeologyConfig.model_fields["cell_samples_per_axis"].default
mesh = FieldMeshSquare.from_unit_square(target_n_cells=9, mesh_kind="structured")
zones = FieldSquare(line="axis_vertical", zone1_side="negative", zone1_name="A", zone2_name="B")
support = zones.on_mesh(mesh, cell_samples_per_axis=N_S)
K = FieldParam(
    identifier="K",
    kind="heterogeneous",
    values_by_key={"A": V_A, "B": V_B},
    field_spatial_id=zones.identifier,
)
u_c = np.asarray(K.to_mesh_field(support).cell_values, dtype=float).ravel()
F_A = np.asarray(support.fractions_by_zone["A"], dtype=float).ravel()

fig, (plan, means) = plt.subplots(1, 2, figsize=(6.4, 3.3), gridspec_kw={"width_ratios": [1, 1.25]})
plan.fill([0, 0.5, 0.5, 0], [0, 0, 1, 1], fc=("C5", 0.3), lw=0)
plan.fill([0.5, 1, 1, 0.5], [0, 0, 1, 1], fc=("C4", 0.3), lw=0)
for cell in mesh.cells:
    plan.fill(*np.asarray(cell.vertices).T, fc="none", ec="C6", lw=1.0)
    x, y = sample_points_in_cell(cell, n_sub_per_axis=N_S)
    in_a = zones.zone_id(x, y) == "A"
    plan.plot(x[in_a], y[in_a], ".", color="C0", ms=2)
    plan.plot(x[~in_a], y[~in_a], ".", color="C1", ms=2)
for cell, share in zip(mesh.cells, F_A, strict=True):
    if cell.vertices[0][1] == 0.0:
        cx = float(np.mean(np.asarray(cell.vertices)[:, 0]))
        plan.text(cx, -0.1, f"{share:g}", ha="center", va="top", fontsize=9)
plan.text(-0.02, -0.1, r"$F_{c,A}$:", ha="right", va="top", fontsize=9)
plan.plot([0.5, 0.5], [0.0, 1.0], color="C6", lw=2.0)
plan.text(0.25, 1.04, "zone A", ha="center", fontsize=9)
plan.text(0.75, 1.04, "zone B", ha="center", fontsize=9)
plan.set_xlim(-0.2, 1.02)
plan.set_ylim(-0.25, 1.12)
plan.set_aspect("equal")
plan.axis("off")

share = np.linspace(0.0, 1.0, 201)
means.semilogy(
    share, share * V_A + (1 - share) * V_B, color="C0", lw=2.0, label="arithmetic, the code"
)
means.semilogy(
    share,
    1.0 / (share / V_A + (1 - share) / V_B),
    color="C6",
    lw=1.2,
    ls="--",
    label="harmonic, flow across",
)
means.plot(F_A, u_c, "o", color="C0", ms=6, label=r"$u_c$ of the nine cells")
middle = float(u_c[np.argmin(np.abs(F_A - 0.5))])
harmonic = 1.0 / (0.5 / V_A + 0.5 / V_B)
means.plot(0.5, harmonic, "o", mfc="white", mec="C6", ms=6)
means.annotate(
    f"{middle:.3g} m/s", (0.5, middle), xytext=(6, -14), textcoords="offset points", fontsize=9
)
means.annotate(
    f"{harmonic:.3g} m/s", (0.5, harmonic), xytext=(8, -12), textcoords="offset points", fontsize=9
)
means.set_xlabel(r"share of zone A in the cell, $F_{c,A}$")
means.set_ylabel(r"$K$ of the cell (m/s)")
means.legend(loc="center right", fontsize=8, frameon=False)
fig.tight_layout()
