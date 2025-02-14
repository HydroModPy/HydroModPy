# -*- coding: utf-8 -*-
"""
Created on Tue Jan 28 18:30:00 2025

@author: figueroar
"""

import pandas as pd
import pyvista as pv
import geopandas as gpd
from shapely.geometry import Point
import numpy as np

# Leer el archivo CSV
csv_path = "D:/Dropbox/1_CHYN_Neuchatel/1PhD_Project/Poschiavo_HMP_model/Geomechanic_model/Models/Ursa_rot0/Ursa_rot0_data_stage4_nodeMaterial.csv"
df = pd.read_csv(csv_path)

shapefile = gpd.read_file('D:/Hydromodpy/Geomechanic/Urse_StreamNetwork_withRS3/results_stable/geographic/watershed.shp')

# Asegurarse de que las columnas se llamen 'x', 'y', 'z' y 'value'
# Si los nombres son diferentes, renombrar las columnas correspondientes
df = df.rename(columns={'X': 'x', 'Y': 'y', 'Z': 'z', 'Volumetric Strain ': 'value'})
df['phi'] = 0.0
df['K'] = 0.0
phi0 = 0.01
K0 = 0.1
n = 15
df['phi'] = 1 - (1-phi0)*np.exp(df['value'])

df.phi[df['phi']<=4e-3] = 4e-3
df['K'] = K0*(df['phi']/phi0)**n
# Definir el valor máximo de z
z0 = 1000

# Filtrar el DataFrame
df= df[df['z'] >= z0]



geometry = [Point(xy) for xy in zip(df['x'], df['y'])]
gdf = gpd.GeoDataFrame(df, geometry=geometry)
gdf.set_crs(shapefile.crs, inplace=True)
df = gpd.clip(gdf, shapefile)


# Crear un objeto PolyData a partir de las coordenadas
points = df[['x', 'y', 'z']].values
point_cloud = pv.PolyData(points)

# Añadir los valores como una propiedad de los puntos
point_cloud['K'] = df['K'].values

# Definir los límites para la barra de colores
vmin = 1e-7
vmax = 1e-1

# Crear una trama interactiva
plotter = pv.Plotter()
plotter.add_mesh(point_cloud, point_size=5, render_points_as_spheres=True,
                 scalars='K', cmap='jet_r', clim=[vmin, vmax], log_scale=True)
plotter.camera.view_angle = 30
plotter.show()

