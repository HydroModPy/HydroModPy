"""Une figure tirée des seuls fichiers exportés, sans importer HydroModPy :
pandas, geopandas, rasterio et xarray suffisent. C'est ce que peut faire un
collègue à qui l'on envoie le dossier share/<run>/.

Il faut d'abord les exports de l'étape 5 :

    hmp run step5_export.toml
    python py3_read_exports.py                    # le dernier share/nancon_step5_export*
    python py3_read_exports.py chemin/vers/share/<run>
"""

import sys
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
import shapely
import xarray as xr
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from rasterio.features import geometry_mask

HERE = Path(__file__).resolve().parent

if len(sys.argv) > 1:
    folder = Path(sys.argv[1])
else:
    # Chaque relance de l'étape 5 écrit dans un nouveau dossier (.v2, .v3...).
    folder = max((HERE / "share").glob("nancon_step5_export*"), key=lambda p: p.stat().st_mtime)
print(folder)

# %% Lecture

# Le bassin, le réseau cartographié, et les cellules du réseau actif simulé en
# octobre 2002, le mois le plus sec de la chronique.
watershed = gpd.read_file(folder / "watershed.gpkg")
basin = watershed.geometry.iloc[0]
network = gpd.read_file(folder / "hydrographic_network_reference.gpkg")
active = gpd.read_file(folder / "simulated_active_network_2002-10-15.gpkg")
active = active[active.centroid.within(basin)]

# La profondeur de la nappe ce même mois. Le raster couvre tout le domaine du
# modèle, on masque ce qui sort du bassin.
with rasterio.open(folder / "watertable_depth_2002-10-15.tif") as src:
    depth = src.read(1, masked=True)
    outside = geometry_mask([basin], out_shape=depth.shape, transform=src.transform)
    extent = (src.bounds.left, src.bounds.right, src.bounds.bottom, src.bounds.top)
depth = np.ma.masked_where(outside, depth)

# Débits jaugé et simulé : un CSV long, une ligne par date et par série. Le
# simulé est daté à la fin de son mois (2001-02-01 pour janvier 2001), on le
# recale au premier jour pour le comparer aux moyennes mensuelles de la jauge.
# L'étape 5 n'exporte que 2001-2002, l'année 2000 servant de mise en route.
series = pd.read_csv(next(folder.glob("*_series*.csv")), parse_dates=["datetime"])
q_obs = series.query("variable == 'discharge_obs'").set_index("datetime")["value"]
q_sim = series.query("variable == 'discharge'").set_index("datetime")["value"]
q_sim.index = q_sim.index - pd.offsets.MonthBegin(1)
q_obs = q_obs.resample("MS").mean().reindex(q_sim.index)

# La chronique de la nappe : une valeur par cellule et par mois, les centres
# des cellules dans face_x et face_y. Même décalage d'un mois que le CSV.
ds = xr.open_dataset(folder / "watertable_2000_2002.nc")
in_basin = shapely.contains_xy(basin, ds["face_x"].to_numpy(), ds["face_y"].to_numpy())
depth_cells = ds["watertable_depth"].to_numpy()[:, in_basin]
shallow = pd.Series(
    (depth_cells < 1.0).mean(axis=1) * 100,
    index=ds["time"].to_index() - pd.offsets.MonthBegin(1),
).loc[q_sim.index]

# Bilan du bassin en mm par an. Les flux sont des débits moyens par période
# (m3/s) : on les multiplie par la durée de la période. Recharge positive,
# drains négatifs, stockage positif quand la nappe se vide.
budget = pd.read_csv(
    folder / "budget.csv", parse_dates=["period_start", "period_end"], dtype={"zone_id": str}
)
budget = budget[budget["zone_id"] == "catchment"]
seconds = (budget["period_end"] - budget["period_start"]).dt.total_seconds()
budget["mm"] = (budget["flux_in"] - budget["flux_out"]) * seconds / basin.area * 1000
year = budget["period_start"].dt.year.rename("année")
print(budget.pivot_table(index=year, columns="component", values="mm", aggfunc="sum").round())

# %% La figure

fig, axes = plt.subplot_mosaic(
    [["map", "q"], ["map", "shallow"]],
    figsize=(13, 6),
    width_ratios=[1, 1.3],
    constrained_layout=True,
)

ax = axes["map"]
im = ax.imshow(depth, extent=extent, cmap="YlGnBu_r", vmin=0, vmax=10)
active.plot(ax=ax, color="tab:red", alpha=0.7)
network.plot(ax=ax, color="navy", lw=0.7)
watershed.boundary.plot(ax=ax, color="k", lw=1)
xmin, ymin, xmax, ymax = basin.bounds
ax.set_xlim(xmin - 300, xmax + 300)
ax.set_ylim(ymin - 300, ymax + 300)
ax.set_axis_off()
ax.set_title("octobre 2002")
ax.legend(
    handles=[
        Line2D([], [], color="navy", lw=0.7, label="réseau cartographié"),
        Patch(color="tab:red", alpha=0.7, label="réseau actif simulé"),
    ],
    loc="upper left",
)
fig.colorbar(im, ax=ax, label="profondeur de la nappe (m)", shrink=0.7, extend="max")

ax = axes["q"]
ax.plot(q_obs, color="k", lw=1, label="jaugé")
ax.plot(q_sim, color="tab:blue", label="simulé")
ax.set_yscale("log")
ax.set_yticks([0.3, 0.5, 1, 2], ["0.3", "0.5", "1", "2"])
ax.minorticks_off()
ax.set_ylabel("débit mensuel (m³/s)")
ax.tick_params(labelbottom=False)
ax.legend()

ax = axes["shallow"]
ax.plot(shallow, color="tab:green")
ax.set_ylabel("bassin avec nappe à moins de 1 m (%)")
ax.sharex(axes["q"])

out = HERE / "share" / "figures" / f"{folder.name}_overview.png"
out.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(out, dpi=150)
print(out)
plt.show()
