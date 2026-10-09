"""Load project.toml as a Python object, change K and Sy, run the modified
model and compare it with the reference model.

    python py2_edit_parameters.py
"""

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

import hydromodpy as hmp
from hydromodpy.config import HydroModPyConfig

HERE = Path(__file__).resolve().parent

# %% The reference

# The model as project.toml describes it (one minute). An unchanged file is
# not computed again: hmp.run returns the run of the last execution and logs a
# warning that names it. Pass force=True to compute it again. Once the file
# changes, if_exists = "replace" sends the previous run to the trash.
reference = hmp.run(HERE / "project.toml")

# %% The modified model

# from_toml follows the base_config chain and returns the object that
# `hmp run` validates: every key of the TOML becomes an attribute.
cfg = HydroModPyConfig.from_toml(HERE / "project.toml")
K = cfg.flow.param["K"].field
Sy = cfg.flow.param["Sy"].field
print(f"project.toml: K = {K.value} {K.unit}, Sy = {Sy.value}")

# Each assignment is validated. A unit other than the one of the field, or an
# unknown figure name, raises an error at once.
K.value = 2e-5
Sy.value = 0.02

# A trial needs neither every figure nor the exports. Replace the whole list:
# an append on the list would escape the validation.
cfg.display.figures = ["hydrograph_log_nse", "seepage_map"]
cfg.export = []

# The full config of the run is kept in runs/<run name>/config.toml.
variant = hmp.run(cfg, name="nancon_variant")
print(variant.name)

# %% Comparison

# Scores from the catalog, over the 36 months of the run.
scores = pd.concat(
    {
        run.name: run.metrics.query("station_id == 'NANCON'").set_index("metric_name")["value"]
        for run in (reference, variant)
    },
    axis=1,
)
print(scores.loc[["nse", "nse_log", "kge", "pbias"]].round(3))

months = reference.periods.edges[:-1]
q_obs = hmp.read(reference, "discharge_obs").resample("MS").mean().reindex(months)
in_catchment = reference.catchment_mask.ravel()
cell_km2 = reference.grid.cell_size**2 / 1e6

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True, constrained_layout=True)
ax1.plot(months, q_obs, color="k", lw=1, label="gauged")
for run, color in [(reference, "tab:blue"), (variant, "tab:red")]:
    label = f"{run.name} (K = {run.params['K']:.0e} m/s, Sy = {run.params['Sy']})"
    ax1.plot(months, hmp.read(run, "discharge").to_numpy(), color=color, label=label)
    seepage = hmp.read(run, "seepage_mask").to_numpy() > 0
    ax2.plot(months, (seepage & in_catchment).sum(axis=1) * cell_km2, color=color)
ax1.set_yscale("log")
ax1.set_yticks([0.2, 0.5, 1, 2], ["0.2", "0.5", "1", "2"])
ax1.minorticks_off()
ax1.set_ylabel("discharge (m³/s)")
ax1.legend(fontsize="small")
ax2.set_ylabel("seepage area (km²)")

# A figure that compares two runs belongs to neither of them: share/figures.
out = HERE / "share" / "figures" / "reference_vs_variant.png"
out.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(out, dpi=150)
print(out)
plt.show()
