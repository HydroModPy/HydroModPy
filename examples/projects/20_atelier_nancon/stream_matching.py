# Scorer la correspondance entre le reseau de drainage simule et le
# reseau hydrographique observe.
#
# Prototype de recherche : HydroModPy possede la metrique de matching de
# reseau (utilisee en interne pour le calage naturel) mais ne l'expose pas
# encore comme workflow CLI. Le script cable un run persiste a la metrique
# a la main.
#
# Lancer d'abord une simulation permanente :
#   hmp run sim_steady_nwt.toml
#   python stream_matching.py

from pathlib import Path

import geopandas as gpd
import numpy as np

import hydromodpy as hmp
from hydromodpy.calibration.observations.natural_observations import natural_network_cost

here = Path(__file__).resolve().parent
catalog = hmp.open(here)
run = list(catalog.find(name="sim_steady_nwt"))[0]

# Reseau simule : debit positif de la nappe vers les drains, par maille.
# Les mailles a debit > 0 sont la ou la nappe atteint la surface.
sim_outflow = run.field("outflow_drain", timestep=-1).ravel()
n_cells = sim_outflow.size

# Centroides et surface des mailles depuis la grille structuree.
xs, ys = run.grid.cell_centers_xy()
centroids = np.column_stack([xs.ravel(), ys.ravel()])
cell_size = float(run.grid.cell_size)
cell_area = np.full(n_cells, cell_size * cell_size)

# Reseau observe : le reseau hydrographique de reference (lignes BD TOPAGE).
network = run.geographic("hydrographic_network_reference")
merged = network.geometry.union_all()

# Distance de chaque centroide de maille au reseau observe, en metres.
points = gpd.GeoSeries(gpd.points_from_xy(centroids[:, 0], centroids[:, 1]), crs=network.crs)
distance = points.distance(merged).to_numpy()

# Masque du reseau observe : mailles traversees par un cours d'eau (a
# moins d'une demi-maille).
observed_mask = distance <= (cell_size / 2.0)
print("mailles actives simulees :", int((sim_outflow > 0).sum()))
print("mailles du reseau observe :", int(observed_mask.sum()))

# Score : ratio de distance entre le drainage simule et le reseau observe.
score = natural_network_cost(
    sim_outflow,
    observed_mask,
    distance,
    centroids,
    cell_area,
    d_tol=cell_size,
    threshold=0.0,
    eta_dist=1.0,
)
print("\ncout de matching reseau :", round(score.total, 4))
print("  D_sim_to_obs (m) :", round(score.components["D_sim_to_obs"], 1))
print("  D_obs_to_obs (m) :", round(score.components["D_obs_to_obs"], 1))
print("  ratio de distance :", round(score.components["distance_ratio"], 3))
print("  mailles actives sim :", int(score.components["n_sim_active"]))
print("  mailles actives obs :", int(score.components["n_obs_active"]))
