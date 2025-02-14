# -*- coding: utf-8 -*-
"""
 * Copyright (c) 2023 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
 *
 * This program and the accompanying materials are made available under the
 * terms of the Eclipse Public License 2.0 which is available at
 * http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
 * which is available at https://www.apache.org/licenses/LICENSE-2.0.
 *
 * SPDX-License-Identifier: EPL-2.0 OR Apache-2.0
"""

#%% ---- LIBRAIRIES

#%% PYTHON

# Filter warnings (before imports)
import warnings
warnings.filterwarnings('ignore', category=DeprecationWarning)

import pkg_resources # Must be placed after DeprecationWarning as it is itself deprecated
warnings.filterwarnings('ignore', message='.*pkg_resources.*')
warnings.filterwarnings('ignore', message='.*declare_namespace.*')

# Libraries installed by default
import sys
import os

# Libraries need to be installed if not
import numpy as np
import pandas as pd

import matplotlib as mpl
import matplotlib.pyplot as plt
from IPython import get_ipython
get_ipython().run_line_magic('matplotlib', 'inline')

# # Libraries added from 'pip install' procedure
import deepdish as dd
import imageio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = True

#%% ROOT

# Import HydroModPy modules
from os.path import dirname, abspath
DIR = dirname(dirname(dirname(dirname(abspath(__file__)))))
sys.path.append(DIR)


# from os.path import dirname, abspath
# root_dir = dirname(dirname(dirname(abspath(__file__))))
# sys.path.append(root_dir)
print("Root path directory is: {0}".format(DIR.upper()))

#%% HYDROMODPY

import src
import importlib
importlib.reload(src)

# Import HydroModPy modules
from src import watershed_root
from src.watershed import climatic, geographic, geology, hydraulic, hydrography, hydrometry, intermittency, oceanic, piezometry, subbasin
from src.modeling import downslope, modflow, modpath, timeseries
from src.display import visualization_watershed, visualization_results, export_vtuvtk
from src.tools import toolbox, folder_root

fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large


#%% Functions
from scipy import interpolate
from scipy.interpolate import griddata
def K_stress(mf1,svol,  K0, n0, phi0, plotit = False):
        
    x_orig = svol["X"]
    y_orig = svol["Y"]
    z_orig = svol["Z"]
    values_orig = svol["Volumetric Strain "]
    
    xc = mf1.modelgrid.xcellcenters
    yc = mf1.modelgrid.ycellcenters
    zaux = mf1.modelgrid.zcellcenters  # Centros de celda en Z
    zc = zaux
    zc[:,-1,:] = zaux[:,-2,:]
    zc[:,:,-1] = zaux[:,:,-2]
    
    n, m = xc.shape  # Dimensiones del grid 2D
    l = zc.shape[0]  # Número de capas en z

    XC_3D = np.zeros([l,n,m])
    XC_3D[:,:,:] = xc
    YC_3D = np.zeros([l,n,m])
    YC_3D[:,:,:] = yc
    
    # Coordenadas destino 3D (zc ya está 3D)
    XC_flat = XC_3D.ravel()
    YC_flat = YC_3D.ravel()
    ZC_flat = zc.ravel()
    
    # Crear un array 2D con las coordenadas del grid destino
    points_dest = np.vstack((XC_flat, YC_flat, ZC_flat)).T
    
    # Interpolación usando griddata
    values_interpolated = griddata(
        (x_orig, y_orig, z_orig),  # Puntos de entrada
        values_orig,              # Valores asociados
        points_dest,              # Puntos de destino
        method='nearest'            # Método de interpolación
    )
    
    # Reshape 
    svol_grid_f = values_interpolated.reshape((l, n, m))

    phi = (1-(1-phi0)*np.exp((svol_grid_f)))
    phi[phi<=4e-3] = 4.e-3
        

    K_S =  K0*(phi/phi0)**n0
    
    return(K_S, phi, svol_grid_f,)


#%% ---- PATHS

#%% PERSONAL

data_path = 'D:/Dropbox/1_CHYN_Neuchatel/1PhD_Project/Poschiavo_HMP_model/Data_temporal/Hydromodpy/'
gis_path = 'D:/Dropbox/1_CHYN_Neuchatel/1PhD_Project/Poschiavo_HMP_model/GIS/Raster/'

# The folder out_path is created in the example_path root directory:

# Or define it manually
out_path = 'D:/Hydromodpy/Geomechanic/'

print('The results of the example will be saved here :', out_path)

#%% ---- WATERSHED

#%% OPTIONS

dem_path = os.path.join(gis_path, 'eu_dem_clipp_ursa_v2.tif')
# dem_path = 'C:/Users/ronan/OneDrive/UNINE/12_Data/_GIS/dem/BDALTI_fr_75m.tif'
load = False
watershed_name = 'Urse_StreamNetwork_withRS3'
# watershed_name ='Strengbach'
from_lib = None # os.path.join(root_dir,'watershed_library.csv')
from_dem = None # [path, cell size]
from_shp = ['D:/Hydromodpy/examples/valdUrsa_v2/Poschiavino/results_stable/geographic/watershed.shp', 10]
from_xyv = [327816.965, 6777886.670, 150, 10 , 'EPSG:2154'] # [x, y, snap distance, buffer size, crs proj]
bottom_path = None # path
save_object = True

#%% GEOGRAPHIC

print('##### '+watershed_name.upper()+' #####')

load = True
BV = watershed_root.Watershed(dem_path=dem_path,
                              out_path=out_path,
                              load=load,
                              watershed_name=watershed_name,
                              from_lib=from_lib, # os.path.join(root_dir,'watershed_library.csv')
                              from_dem=from_dem, # [path, cell size]
                              from_shp=from_shp, # [path, buffer size]
                              from_xyv=from_xyv, # [x, y, snap distance, buffer size]
                              bottom_path=bottom_path, # path 
                              save_object=save_object)

# Paths generated automatically but necessary for plots
stable_folder = os.path.join(out_path, watershed_name, 'results_stable')
simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')

#%% DATA
KB4_loc = [2796960.102,1133328.361]
visualization_watershed.watershed_dem(BV)
                

#%% ---- PARAMETRIZATION

#%% DEFINE

# Frame settings
box = True # or False
sink_fill = False # or True
# sim_state = 'transient' # 'steady' or 'transient'
sim_state = 'steady' # 'steady' or 'transient'
plot_cross = False
check_grid = False
dis_perlen=False

# Climatic settings
# recharge = pd.Series([10,20,30,40,50,60,60,50,40,30,20,10])/30/1000
recharge = 1/365
first_clim = 'mean' # or 'first or value
freq_time = 'M'

# Hydraulic settings
nlay = 20
lay_decay = 1.5 # 1 for nodecay
bottom = 1500 # elevation in meters, None for constant auifer thickness, or 2D matrix
thick = 50 # if bottom is None, aquifer thickness
cond_drain = None # or value of conductance
sy = 1 / 100 # -

########## LOOP ##########
list_hyd_cond = np.array([4e-1, 8e-1]) # m/day
list_hyd_cond = np.geomspace(1e-3,1e1,10)

# Boundary settings
bc_left = None # or value
bc_right = None # or value
sea_level = 'None' # or value based on specific data : BV.oceanic.MSL

# Particle tracking settings
zone_partic = 'domain' # or watershed

#%% UPDATE

# Import modules
BV.add_settings()
BV.add_climatic()
BV.add_hydraulic()

# Frame settings
BV.settings.update_box_model(box)
BV.settings.update_sink_fill(sink_fill)
BV.settings.update_simulation_state(sim_state)
BV.settings.update_check_model(plot_cross=plot_cross, check_grid=check_grid)

# Climatic settings
BV.climatic.update_recharge(recharge, sim_state=sim_state)
BV.climatic.update_first_clim(first_clim)

# Hydraulic settings
BV.hydraulic.update_nlay(nlay) # 1
BV.hydraulic.update_bottom(bottom) # None
BV.hydraulic.update_thick(thick) # 30 / intervient pas si bottom != None
BV.hydraulic.update_sy(sy)
BV.hydraulic.update_cond_drain(cond_drain)
BV.hydraulic.update_lay_decay(lay_decay)

# Boundary settings
BV.settings.update_bc_sides(bc_left, bc_right)
BV.add_oceanic(sea_level)
BV.settings.update_dis_perlen(dis_perlen=dis_perlen)

# Particle tracking settings
BV.settings.update_input_particles(zone_partic=BV.geographic.watershed_box_buff_dem) # or 'seepage_path'

#%% ---- MODELING
#%% MODFLOW - preliminar
model_name = 'mod0'
BV.settings.update_model_name(model_name)
print(model_name)
BV.hydraulic.update_hk(1e0)
model_modflow = BV.preprocessing_modflow(for_calib=False)
success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=False)
#%% Read roscience file
import pandas as pd
geom_stage = 'stage1'               #Choose geomechanical model stage 1,2,3,4

csv_path = "D:/Dropbox/1_CHYN_Neuchatel/1PhD_Project/Poschiavo_HMP_model/Geomechanic_model/Models/Ursa_rot0/Ursa_rot0_data_"+geom_stage+"_nodeMaterial.csv"
gmc = pd.read_csv(csv_path)
K0 = 1
phi0 = 0.01
n = 15

[KS, phiS, vS,] = K_stress(model_modflow.mf, gmc, K0, n, phi0,  plotit=False)


#%% Replace hk in new model
model_name = 'mod1'
BV.settings.update_model_name(model_name)
print(model_name)
BV.hydraulic.update_hk(KS)
model_modflow = BV.preprocessing_modflow(for_calib=False)
success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=False)


#%% Plot map view and cross sections
# %matplotlib qt
import flopy
import flopy.utils.binaryfile as bf
import matplotlib.colors as colors
import geopandas as gpd

v_min = 1e-7
v_max = 1e-1
to_plot = KS

WC0 = os.path.join(stable_folder, 'geographic', 'watershed.shp')
WC_shp = gpd.read_file(WC0)

fig = plt.figure()
ax = fig.add_subplot(111, aspect="equal")
pmv = flopy.plot.PlotMapView(model=model_modflow.mf, layer=0, ax=ax)
norm = colors.LogNorm(vmin=v_min, vmax=v_max)
pa = pmv.plot_array(to_plot, norm=norm, cmap='jet_r',alpha=0.5,)
# pa = pmv.plot_array(KS, norm=colors.LogNorm(), vmin = v_min, vmax = v_max)
cb = plt.colorbar(pa, shrink=0.75)
WC_shp.boundary.plot(ax=ax, color='m', linewidth=1.5)
ax.plot(KB4_loc[0],KB4_loc[1], 'r*')
plt.axis('off')


fig2 = plt.figure(figsize=(10, 12))
ax = fig2.add_subplot(211)
xsect = flopy.plot.PlotCrossSection(model=model_modflow.mf, line={'Column': int(model_modflow.mf.dis.ncol/2)}, ax=ax)
pc = xsect.plot_array(to_plot, norm=colors.LogNorm(), vmin = v_min,vmax = v_max,  alpha=0.75,cmap='jet_r', lw = 0)    
ax.set_ylim(1500,3000)


bx = fig2.add_subplot(212)
xsect = flopy.plot.PlotCrossSection(model=model_modflow.mf, line={'Row': int(model_modflow.mf.dis.nrow/2)}, ax=bx)
pc = xsect.plot_array(to_plot, norm=colors.LogNorm(), vmin = v_min,vmax = v_max,  alpha=0.75,cmap='jet_r', lw = 0)    
bx.set_ylim(1500,3000)
cb = plt.colorbar(pc, shrink=0.75, orientation='horizontal')

# sys.exit(1)

#%% PLot pyvista
import numpy as np
import pyvista as pv
from shapely.geometry import Polygon, LineString
import rasterio
gdf = WC_shp
# Suponiendo que model_modflow.mf es tu modelo cargado con flopy
nlay = model_modflow.mf.dis.nlay
nrow = model_modflow.mf.dis.nrow
ncol = model_modflow.mf.dis.ncol

# Obtener los centros de las celdas
x = model_modflow.mf.modelgrid.xcellcenters
y = model_modflow.mf.modelgrid.ycellcenters
zz = model_modflow.mf.modelgrid.zcellcenters
z = zz
z[:,-1,:] = zz[:,-2,:]
z[:,:,-1] = zz[:,:,-2]
# Asegurarse de que x, y, z y KS tengan las mismas dimensiones
assert x.shape == (nrow, ncol)
assert y.shape == (nrow, ncol)
assert z.shape == (nlay, nrow, ncol)
assert KS.shape == (nlay, nrow, ncol)

# Repetir x e y a lo largo de la dimensión de capas (nlay)
x = np.repeat(x[np.newaxis, :, :], nlay, axis=0)
y = np.repeat(y[np.newaxis, :, :], nlay, axis=0)

# Aplanar las matrices 3D en 1D
x_flat = x.ravel()
y_flat = y.ravel()
z_flat = z.ravel()
KS_flat = KS.ravel()

# Crear la matriz de puntos de forma (n_points, 3)
points = np.vstack((x_flat, y_flat, z_flat)).T

# Crear el StructuredGrid
grid = pv.StructuredGrid()
grid.points = points

# Establecer las dimensiones de la cuadrícula
grid.dimensions = (ncol, nrow, nlay)

# Asignar los valores de conductividad al grid
grid['Conductividad'] = KS_flat


archivo_csv = 'D:/Dropbox/1_CHYN_Neuchatel/1PhD_Project/Poschiavo_HMP_model/Geomechanic_model/Surfaces_DTMs/Catchment_border.csv'
df = pd.read_csv(archivo_csv)
df['z'] = df['z']+10.0
# Extraer las coordenadas
puntos = df[['x', 'y', 'z']].values

# Paso 2: Crear una malla de línea en PyVista
# Crear una lista que define la conectividad de los puntos
n_puntos = len(puntos)
linea = np.zeros((n_puntos + 1,), dtype=np.int_)
linea[0] = n_puntos  # Número de puntos en la línea
linea[1:] = np.arange(n_puntos)  # Índices de los puntos

# Crear la malla PolyData con los puntos y la línea
malla = pv.PolyData(puntos, lines=linea)


# Visualizar
# plotter = pv.Plotter(off_screen=True)
plotter = pv.Plotter()
plotter.add_mesh(grid, scalars='Conductividad', cmap='jet_r', show_edges=False, log_scale=True, clim=[v_min, v_max], )
plotter.remove_scalar_bar()
plotter.add_mesh(malla, color='m', line_width=2)
plotter.camera_position = [0.75,-1,0.75]
# plotter.camera_direction = [-0.7797689156897312, -0.5596313273339267, 0.2806656651436511]
# plotter.camera.view_angle = 60
# for geom in geometries:
#     plotter.add_mesh(geom, color='m', line_width=2)
# plotter.add_scalar_bar(title='K [m/d]', )
# _ = plotter.add_background_image(examples.mapfile)
# plotter.Plotter(off_screen=True)
# plotter.screenshot("D:/"+geom_stage+".png")
# plotter.show()
# sys.exit(1)
#%% MODFLOW

iD_set_simulations = geom_stage

list_model_name = []
list_success_modflow = []
list_model_modflow = []

for hyd_cond in list_hyd_cond:
    BV.hydraulic.update_hk(hyd_cond*KS)
    BV.hydraulic.update_cond_drain(1)
    model_name = iD_set_simulations+'_'+str(round(hyd_cond,3))
    BV.settings.update_model_name(model_name)
    print(model_name)
    
    model_modflow = BV.preprocessing_modflow(for_calib=False)
    success_modflow = BV.processing_modflow(model_modflow, write_model=False, run_model=False)
    
    list_model_name.append(model_name)
    list_success_modflow.append(success_modflow)
    list_model_modflow.append(model_modflow)

dictio = {}
dictio['list_model_name'] = list_model_name
dictio['list_success_modflow'] = list_success_modflow
dictio['list_model_modflow'] = list_model_modflow
h5file = os.path.join(simulations_folder,'results_listing_'+iD_set_simulations)
    
dd.io.save(h5file, dictio)

#%% RELOAD

h5file = os.path.join(simulations_folder,'results_listing_'+iD_set_simulations)
d = dd.io.load(h5file)
list_model_name = d['list_model_name'][:]
list_success_modflow = d['list_success_modflow'][:]
list_model_modflow = d['list_model_modflow'][:]

#%% POSTPROCESSING

for model_name, success_modflow, model_modflow in zip(list_model_name,
                                                      list_success_modflow,
                                                      list_model_modflow):
    if success_modflow == True:
        BV.postprocessing_modflow(model_modflow,
                                  watertable_elevation = True,
                                  watertable_depth= True, 
                                  seepage_areas = True,
                                  outflow_drain = True,
                                  groundwater_flux = True,
                                  groundwater_storage = True,
                                  accumulation_flux = True,
                                  persistency_index=False,
                                  intermittency_monthly=False,
                                  intermittency_daily=False,
                                  export_all_tif = False)

        timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                          model_modpath=None,
                                                          datetime_format=False, 
                                                          subbasin_results=True) # or None
        
        netcdf_results = BV.postprocessing_netcdf(model_modflow,
                                                  datetime_format=False)

#%% ---- PLOT

#%% CROSS

compt = 1

for model_name, success_modflow, model_modflow in zip(list_model_name,
                                                      list_success_modflow,
                                                      list_model_modflow):

    
    fig, ax = plt.subplots(1, 1, figsize=(5,3), dpi=300)

    stable_folder = os.path.join(out_path, watershed_name, 'results_stable') # necessary for plots
    simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')

    dem_data = imageio.imread(BV.geographic.watershed_dem)
    dem_data = np.ma.masked_where(dem_data < 0, dem_data)
    
    wt_data = imageio.imread(os.path.join(simulations_folder, model_name, 
                                          r'_postprocess/_rasters/watertable_elevation_t(0).tif'))
    wt_data = np.ma.masked_where(wt_data < 0, wt_data)
    
    # river_data = imageio.imread(os.path.join(stable_folder, 'hydrography', 
    #                                          'regional stream network.tif'))

    xvalues = np.linspace(-1,1,dem_data.shape[1])
    yvalues = np.linspace(-1,1,dem_data.shape[0])
    xx, yy = np.meshgrid(xvalues,yvalues)
    
    cur_x = dem_data.shape[1] /2
    # cur_y = dem_data.shape[0] /2
    
    dem_prof = dem_data.astype(float)
    dem_prof[dem_prof<0] = np.nan
    dem_v_plot = dem_prof[:,int(cur_x)]
    dem_v_plot[dem_v_plot == 0] = np.nan

    wt_prof = wt_data.astype(float)
    wt_prof[wt_prof<0] = np.nan
    wt_v_plot = wt_prof[:,int(cur_x)]
    wt_v_plot[wt_v_plot == 0] = np.nan

    # wt_prof_min = wt_data.astype(float)
    # wt_prof_min[wt_prof_min<0] = np.nan
    # wt_v_plot_min = wt_prof_min[:,int(cur_x)]
    # wt_v_plot_min[wt_v_plot_min == 0] = np.nan
    
    # Facecolor watertable
    wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75,
                                dem_v_plot-30, wt_v_plot,
                                color='dodgerblue', alpha=0.5, lw=0)
    # Line watertable
    w_prof = ax.plot(np.arange(xx.shape[0])*75, wt_v_plot, color='navy', lw=1)
    
    # Facecolor unsaturated
    wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75, 
                                wt_v_plot, dem_v_plot,
                                color='saddlebrown', alpha=0.5, lw=0)
    
    # Line unsaturated
    d_prof = ax.plot(np.arange(xx.shape[0])*75, dem_v_plot, 'saddlebrown', lw=1.5)
    
    # Facecolor noflow
    ax.fill_between(np.arange(xx.shape[0])*75,
                    0, dem_v_plot-30,
                    color='lightgrey', alpha=1, lw=0, zorder=10)
    # Line noflow
    ax.plot(np.arange(xx.shape[0])*75, dem_v_plot-30, color='dimgray', lw=1.5)
    
    # Settings
    # ax.set_xlim(1000, 4000)
    ax.set_ylim(2000, 3000)
    # ax.set_yticks([90,100,110,120,130])
    ax.set_xlabel('Distance [m]')
    ax.set_ylabel('Elevation [m]')
    ax.set_title('K = '+'{:.2e}'.format(model_modflow.hk.mean()/24/3600)+' m/s')
    
    compt += 1
    
    # fig.tight_layout
    
    # fig.savefig(os.path.join(model_modflow.figure_file,
    #             'CROSS_'+model_name+'_'+str(compt)+'.png'),
    #             bbox_inches='tight')
        
    # fig.savefig(os.path.join(model_modflow.save_fig,
    #             'CROSS_'+model_name+'_'+str(compt)+'.png'),
    #             bbox_inches='tight')

 
#%% MAP seepage
import rasterio
from rasterio.plot import show
import geopandas as gpd
from rasterio.features import geometry_mask
compt = 0
stream_obs=gpd.read_file('D:/Dropbox/1_CHYN_Neuchatel/1PhD_Project/Poschiavo_HMP_model/GIS/Shapes/stream_network_perenial.shp')

   
stable_folder = os.path.join(out_path, watershed_name, 'results_stable') # necessary for plots
simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')

lin0 = os.path.join(stable_folder, 'geographic', 'watershed_contour.tif')
mask0 = os.path.join(stable_folder, 'geographic', 'watershed_dem.tif')
WC0 = os.path.join(stable_folder, 'geographic', 'watershed.shp')

WC_shp = gpd.read_file(WC0)
stream_obs_clip = gpd.clip(stream_obs, WC_shp)

with rasterio.open(mask0) as src:
    # Leer el raster y obtener las coordenadas
    data = src.read(1)  # Leer la primera banda
    bounds = src.bounds  # Coordenadas de los bordes
    transform = src.transform  # Transformación para georreferenciar
    extent2 = (bounds.left, bounds.right, bounds.bottom, bounds.top)

with rasterio.open(lin0) as src:
    # Leer el raster y obtener las coordenadas
    data = src.read(1)  # Leer la primera banda
    bounds = src.bounds  # Coordenadas de los bordes
    transform = src.transform  # Transformación para georreferenciar
    extent1 = (bounds.left, bounds.right, bounds.bottom, bounds.top)

line = imageio.imread(os.path.join(stable_folder, 'geographic', 'watershed_contour.tif'))
line = np.ma.masked_where(line <= 0, line)

mask = imageio.imread(os.path.join(stable_folder, 'geographic', 'watershed_dem.tif'))
for model_name, success_modflow, model_modflow in zip(list_model_name,
                                                      list_success_modflow,
                                                      list_model_modflow):

    fig, ax = plt.subplots(1, 1, figsize=(5,3), dpi=300)

    stable_folder = os.path.join(out_path, watershed_name, 'results_stable') # necessary for plots
    simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')
    
    stream_obs_clip.plot(ax=ax, edgecolor="cyan",linewidth=0.5)
    # ax.set_title(str(year)[0:10] + '   ' + '$A_{sat}$ = ' + str(val.round(1)) + ' [%]',
    #              pad=10, fontsize=10)
    ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys', alpha=0.5, zorder=0, extent=extent2)

    # dem_data = imageio.imread(BV.geographic.watershed_box_buff_dem)
    # dem_data = np.ma.masked_where(dem_data < 0, dem_data)
    
    # contour = imageio.imread(BV.geographic.watershed_contour_tif)
    # contour = np.ma.masked_where(contour < 0, contour)
    
    # obs_river_data = imageio.imread(os.path.join(stable_folder, 'hydrography',
    #                                              'regional stream network.tif'))
    # obs_river_data = np.ma.masked_where(obs_river_data < 0, obs_river_data)
    
    seep_river_data = imageio.imread(os.path.join(simulations_folder, model_name,
                                                  r'_postprocess/_rasters/seepage_areas_t(0).tif'))
    seep_river_data = np.ma.masked_where((seep_river_data <= 0) | (mask <0), seep_river_data)
    # seep_river_data = rasterio.mask(seep_river_data, WC0)
    
    
    sim_river_data = imageio.imread(os.path.join(simulations_folder, model_name,
                                                 r'_postprocess/_rasters/accumulation_flux_t(0).tif'))
    sim_river_data = np.ma.masked_where((sim_river_data <= 0) | (mask <0), sim_river_data)
    
    
    # im_dem = ax.imshow(dem_data, alpha=0.5, cmap='Greys')
    # im_cont = ax.imshow(contour, alpha=1, cmap=mpl.colors.ListedColormap('k'))
    # im_obs = ax.imshow(obs_river_data, alpha=1, cmap=mpl.colors.ListedColormap('navy'))
    im_sim = ax.imshow(sim_river_data, cmap=mpl.colors.ListedColormap('red'), alpha=0.7, extent=extent2)
    im_seep = ax.imshow(seep_river_data, cmap=mpl.colors.ListedColormap('darkorange'), alpha=0.7, extent=extent2)

    # ax.set_xlabel('X [pixels]')
    # ax.set_ylabel('Y [pixels]')
    # ax.set_title('K = '+'{:.2e}'.format(model_modflow.hk.mean()/24/3600)+' m/s')
    ax.set_title('K = '+'{:.1e}'.format(model_modflow.hk.mean())+' m/d')
    ax.imshow(line, cmap=mpl.colors.ListedColormap('k'), extent=extent1)
    ax.plot(KB4_loc[0],KB4_loc[1], 'r*')
    plt.axis('off')
    compt += 1
    
    fig.tight_layout()

    # fig.savefig(os.path.join(model_modflow.figure_file,
    #             'MAP_'+model_name+'_'+str(compt)+'.png'),
    #             bbox_inches='tight')
    
    # fig.savefig(os.path.join(model_modflow.save_fig,
    #             'MAP_'+model_name+'_'+str(compt)+'.png'),
    #             bbox_inches='tight')

#%% MAP flow outlet
import rasterio
from rasterio.plot import show
import geopandas as gpd
from rasterio.features import geometry_mask
compt = 0
stream_obs=gpd.read_file('D:/Dropbox/1_CHYN_Neuchatel/1PhD_Project/Poschiavo_HMP_model/GIS/Shapes/stream_network_perenial.shp')
zz = []
   
stable_folder = os.path.join(out_path, watershed_name, 'results_stable') # necessary for plots
simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')

lin0 = os.path.join(stable_folder, 'geographic', 'watershed_contour.tif')
mask0 = os.path.join(stable_folder, 'geographic', 'watershed_dem.tif')
WC0 = os.path.join(stable_folder, 'geographic', 'watershed.shp')

WC_shp = gpd.read_file(WC0)
stream_obs_clip = gpd.clip(stream_obs, WC_shp)

with rasterio.open(mask0) as src:
    # Leer el raster y obtener las coordenadas
    data = src.read(1)  # Leer la primera banda
    bounds = src.bounds  # Coordenadas de los bordes
    transform = src.transform  # Transformación para georreferenciar
    extent2 = (bounds.left, bounds.right, bounds.bottom, bounds.top)

with rasterio.open(lin0) as src:
    # Leer el raster y obtener las coordenadas
    data = src.read(1)  # Leer la primera banda
    bounds = src.bounds  # Coordenadas de los bordes
    transform = src.transform  # Transformación para georreferenciar
    extent1 = (bounds.left, bounds.right, bounds.bottom, bounds.top)

line = imageio.imread(os.path.join(stable_folder, 'geographic', 'watershed_contour.tif'))
line = np.ma.masked_where(line <= 0, line)

mask = imageio.imread(os.path.join(stable_folder, 'geographic', 'watershed_dem.tif'))
for model_name, success_modflow, model_modflow in zip(list_model_name,
                                                      list_success_modflow,
                                                      list_model_modflow):

    fig, ax = plt.subplots(1, 1, figsize=(5,3), dpi=300)

    stable_folder = os.path.join(out_path, watershed_name, 'results_stable') # necessary for plots
    simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')
    
    stream_obs_clip.plot(ax=ax, edgecolor="cyan",linewidth=0.5)
    # ax.set_title(str(year)[0:10] + '   ' + '$A_{sat}$ = ' + str(val.round(1)) + ' [%]',
    #              pad=10, fontsize=10)
    ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys', alpha=0.5, zorder=0, extent=extent2)

    # dem_data = imageio.imread(BV.geographic.watershed_box_buff_dem)
    # dem_data = np.ma.masked_where(dem_data < 0, dem_data)
    
    # contour = imageio.imread(BV.geographic.watershed_contour_tif)
    # contour = np.ma.masked_where(contour < 0, contour)
    
    # obs_river_data = imageio.imread(os.path.join(stable_folder, 'hydrography',
    #                                              'regional stream network.tif'))
    # obs_river_data = np.ma.masked_where(obs_river_data < 0, obs_river_data)
    
    seep_river_data = imageio.imread(os.path.join(simulations_folder, model_name,
                                                  r'_postprocess/_rasters/groundwater_flux_t(0).tif'))
    seep_river_data = np.ma.masked_where((seep_river_data <= 0) | (mask <0), seep_river_data)
    seep_river_data = np.ma.masked_where(seep_river_data <= 1.72, seep_river_data)
    # seep_river_data = rasterio.mask(seep_river_data, WC0)
    
    zz.append(seep_river_data)
    sim_river_data = imageio.imread(os.path.join(simulations_folder, model_name,
                                                 r'_postprocess/_rasters/accumulation_flux_t(0).tif'))
    sim_river_data = np.ma.masked_where((sim_river_data <= 0) | (mask <0), sim_river_data)
    
    
    # im_dem = ax.imshow(dem_data, alpha=0.5, cmap='Greys')
    # im_cont = ax.imshow(contour, alpha=1, cmap=mpl.colors.ListedColormap('k'))
    # im_obs = ax.imshow(obs_river_data, alpha=1, cmap=mpl.colors.ListedColormap('navy'))
    # im_sim = ax.imshow(sim_river_data, cmap=mpl.colors.ListedColormap('red'), alpha=0.7, extent=extent2)
    im_seep = ax.imshow(seep_river_data, norm=colors.LogNorm(vmin=10, vmax=100), alpha=0.7, extent=extent2)

    # ax.set_xlabel('X [pixels]')
    # ax.set_ylabel('Y [pixels]')
    # ax.set_title('K = '+'{:.2e}'.format(model_modflow.hk.mean()/24/3600)+' m/s')
    ax.set_title('K = '+'{:.1e}'.format(model_modflow.hk.mean())+' m/d')
    ax.imshow(line, cmap=mpl.colors.ListedColormap('k'), extent=extent1)
    ax.plot(KB4_loc[0],KB4_loc[1], 'r*')
    plt.axis('off')
    compt += 1
    
    fig.tight_layout()

    # fig.savefig(os.path.join(model_modflow.figure_file,
    #             'MAP_'+model_name+'_'+str(compt)+'.png'),
    #             bbox_inches='tight')
    
    # fig.savefig(os.path.join(model_modflow.save_fig,
    #             'MAP_'+model_name+'_'+str(compt)+'.png'),
    #             bbox_inches='tight')

    
#%% GRAPH

fig, ax = plt.subplots(1, 1, figsize=(5,4), dpi=300)

for model_name, success_modflow, model_modflow in zip(list_model_name,
                                                      list_success_modflow,
                                                      list_model_modflow):
    
    simulations_folder = os.path.join(out_path, watershed_name, 
                                      'results_simulations')
    
    simul_csv = pd.read_csv(os.path.join(simulations_folder, model_name,
                            r'_postprocess/_timeseries/', '_simulated_timeseries.csv'),
                            sep=';')
    

    ax.plot(model_modflow.hk.mean()/24/3600,
            simul_csv['seepage_areas'],
            marker='o', ms=8, lw=0, color='k')
    
    ax.set_xscale('log')
    ax.set_xlabel('K [m/s]')
    ax.set_ylabel('Drainage density [%]')
    
    # fig.tight_layout()
    
    # fig.savefig(os.path.join(model_modflow.save_fig,
    #             'GRAPH_sat_'+iD_set_simulations+'.png'),
    #             bbox_inches='tight')
#%%
# export_vtuvtk.VTK(BV, model_name)
# visu = visualization_results.Visualization(BV, model_name)
# visu.visual3D(interactive=True, object_list=[
#                                              'grid',
#                                              'watertable',
#                                              'watertable_depth',
#                                              'surface_flow',
#                                              'drain_flow',
#                                              'pathlines'
#                                              ],
#                                                view='south-west',
#                                               # view='north',
#                                               lines=None,
#                                               cloc=(0.7,0.1),
#                                               z_scale=10)
# dem_data = imageio.imread(os.path.join(stable_folder,'geographic','watershed_box_buff_dem.tif')) # dem data
# stream_data = imageio.imread(os.path.join(stable_folder,'hydrography','regional stream network.tif')) # river data
# watertable_data = imageio.imread(os.path.join(simulations_folder,model_name,'_postprocess/_rasters/','watertable_elevation_t(0).tif')) # watertable data
# interactive = True
# visu = visualization_results.Visualization(BV, model_name)
# visu.interactive_cross_section(dem_data, watertable_data, stream_data, interactive)


#%% ---- NOTES

os.chdir(DIR)
