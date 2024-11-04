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

# Libraries installed by default
import sys
import os
import warnings
warnings.filterwarnings("ignore", message=".*An exception was ignored while fetching the attribute.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*`np.object` is a deprecated alias for the builtin `object`.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated. Use tobytes().*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated since Matplotlib 3.*", category=DeprecationWarning)
warnings.filterwarnings("ignore")

# Libraries need to be installed if not
import numpy as np
import pandas as pd

# Libraries added from 'conda install' procedure
import geopandas as gpd
import matplotlib as mpl
import matplotlib.pyplot as plt
import rasterio
from IPython import get_ipython
get_ipython().run_line_magic('matplotlib', 'inline')
import flopy
import imageio

import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

#%% ROOT

from os.path import dirname, abspath
root_dir = dirname(dirname(dirname(abspath(__file__))))
sys.path.append(root_dir)
print("Root path directory is: {0}".format(root_dir.upper()))

#%% HYDROMODPY

import src
import importlib
importlib.reload(src)

# Import HydroModPy modules
from src import watershed_root
from src.display import visualization_results, export_vtuvtk
from src.tools import toolbox, folder_root

fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% ---- PATHS

#%% PERSONAL

example_path = root_dir + "/examples/05_particle tracking for residence times/"
data_path = os.path.join(example_path, "data") + '/'
# To automatically retrieve/initialize the HydroModPy results path:
# out_path = folder_root.root_folder_results()
# When it needs modifying: out_path = folder_root.update_root_folder_results()
# Otherwise, to inform a results path specific to this script:
out_path = 'C:/Users/ronan/Simulations/HydroModPy/' # for example

#%% ---- WATERSHED

#%% OPTIONS

case = 'Example_05_Lasset'
# case = 'Example_05_Hillslope_1D'
# case = 'Example_05_Hillslope_2D'

if case == 'Example_05_Hillslope_1D':
    dem_path = data_path + 'hillslope_1D.tif'
    load = False
    watershed_name = case
    from_lib = None # os.path.join(root_dir,'watershed_library.csv')
    from_dem = [dem_path, 10] # [path, cell size]
    from_shp = None # [path, buffer size]
    from_xyv = None # [x, y, snap distance, buffer size]
    bottom_path = None # path
    modflow_path = os.path.join(root_dir,'bin/')
    save_object = True
    
if case == 'Example_05_Hillslope_2D':
    dem_path = data_path + 'hillslope_2D.tif'
    load = False
    watershed_name = case
    from_lib = None # os.path.join(root_dir,'watershed_library.csv')
    from_dem = [dem_path, 10] # [path, cell size]
    from_shp = None # [path, buffer size]
    from_xyv = None # [x, y, snap distance, buffer size]
    bottom_path = None # path
    modflow_path = os.path.join(root_dir,'bin/')
    save_object = True

if case == 'Example_05_Lasset':
    dem_path = data_path + 'regional dem.tif'
    load = True
    watershed_name = case
    from_lib = None # os.path.join(root_dir,'watershed_library.csv')
    from_dem = None # [path, cell size]
    from_shp = None # [path, buffer size]
    from_xyv = [601020,6193860,200,50,'EPSG:2154'] # [x, y, snap distance, buffer size]
    bottom_path = None # path
    modflow_path = os.path.join(root_dir,'bin/')
    save_object = True

#%% GEOGRAPHIC

print('##### '+watershed_name.upper()+' #####')

# load = True
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
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

#%% ---- RECHARGE

#%% CASES

# # Necessary to set model parameters
BV.add_climatic()

# Different cases of recharge implementation
time_series = pd.Series([10,20,30,40,50,60,60,50,40,30,20,10])
BV.climatic.update_recharge(time_series, sim_state='transient')
fig, ax = plt.subplots(1,1, figsize=(6,3))
R = BV.climatic.recharge
r = R * 0.1
ax.plot(R, label='recharge_manual', c='dodgerblue', lw=2)
ax.plot(r, label='runoff_manual', c='navy', lw=2)
ax.set_xlabel('Months')
ax.set_ylabel('[mm/month]')
ax.legend()

#%% ---- PARAMETRIZATION

#%% DEFINE

# Frame settings
model_name = 'default'
box = True # or False
sink_fill = False # or True
sim_state = 'steady' # 'steady' or 'transient'
plot_cross = True

# Climatic settings
recharge = pd.Series([10,20,30,40,50,60,60,50,40,30,20,10])/30/1000
first_clim = 'mean' # or 'first or value
freq_time = 'M'

# Hydraulic settings
nlay = 50
lay_decay = 1.25 # 1 for no decay
bottom = -1 # elevation in meters, None for constant auifer thickness, or 2D matrix
thick = 100 # if bottom is None, aquifer thickness
if watershed_name == 'Example_05_Lasset':
    hyd_cond = 1e-8 * 24 * 3600 # m/day
else:
    hyd_cond = 5e-7 * 24 * 3600 # m/day
cond_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
verti_cond = None # or [ [1e-5, [0, 20]], [1e-6, [20,80]] ]
cond_drain = None # or value of conductance
porosity = 1 / 100 # -
poro_decay = 0 # exponential decay : 1/20 (half decrease at 20m)

# Boundary settings
bc_left = None # or value
bc_right = None # or value
sea_level = 'None' # or value based on specific data : BV.oceanic.MSL

# Particle tracking settings
zone_partic = 'domain'
tif_file = 'None'
tracking_dir = 'forward'

# If you want to test the backward settings
# zone_partic = 'path' # domain or watershed or path
# tif_file = 'xxx/results_simulations/default/_postprocess/_rasters/seepage_areas_t(0).tif'
# tracking_dir = 'backward' # backward or forward

#%% UPDATE

# Import modules
BV.add_settings()
BV.add_climatic()
BV.add_geometric() # soon
BV.add_hydraulic()

# Frame settings
BV.settings.update_model_name(model_name)
BV.settings.update_box_model(box)
BV.settings.update_sink_fill(sink_fill)
BV.settings.update_simulation_state(sim_state)
BV.settings.update_active_plot(plot_cross=plot_cross)

# Climatic settings
BV.climatic.update_recharge(recharge, sim_state=sim_state)
BV.climatic.update_first_clim(first_clim)

# Hydraulic settings
BV.hydraulic.update_nlay(nlay) # 1
BV.hydraulic.update_lay_decay(lay_decay) # 1
BV.hydraulic.update_bottom(bottom) # None
BV.hydraulic.update_thick(thick) # 30 / intervient pas si bottom != None
BV.hydraulic.update_hyd_cond(hyd_cond)
BV.hydraulic.update_porosity(porosity)
BV.hydraulic.update_cond_vertical(verti_cond)
BV.hydraulic.update_cond_drain(cond_drain)
BV.hydraulic.update_lay_decay(poro_decay)

# Boundary settings
BV.settings.update_bc_sides(bc_left, bc_right)
BV.add_oceanic(sea_level)
BV.settings.update_split_temporal(split_temp=False)

#%% ---- MODELING

#%% MODFLOW

model_modflow = BV.preprocessing_modflow(for_calib=False)
success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=True)
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

#%% MODPATH

# Particle tracking settings
tif_file = BV.simulations_folder + '/' + model_name + '/_postprocess/_rasters/seepage_areas_t(0).tif'
tif_file_clip = BV.simulations_folder + '/' + model_name + '/_postprocess/_rasters/seepage_areas_t(0)_clip.tif'
wbt.clip_raster_to_polygon(
    tif_file, 
    BV.stable_folder + '/geographic/watershed.shp', 
    tif_file_clip, 
    maintain_dimensions=True)
        
seep = imageio.imread(BV.geographic.watershed_box_buff_dem)
seep = seep*0
# seep[30,25] = 1
# seep[25,30] = 1
seep[40,48] = 1
# seep[60,20] = 1
# seep[50,25] = 1
plt.imshow(seep)
particles_folder = os.path.join(BV.simulations_folder + '/' + model_name, '_postprocess', '_particles')
toolbox.create_folder(particles_folder)
toolbox.export_tif(BV.geographic.watershed_box_buff_dem,
                   seep,
                   BV.geographic.simulations_folder+'/'+model_name+'/'+'_postprocess/_particles/'+'synthetic_boreholes.tif',
                   0)
tif_bore = BV.geographic.simulations_folder+'/'+model_name+'/'+'_postprocess/_particles/'+'synthetic_boreholes.tif'

BV.settings.update_input_particles(
                                    # zone_partic = BV.geographic.watershed_box_buff_dem,
                                    zone_partic = tif_file_clip,
                                    cell_div = 1, # 1
                                    zloc_div = False,  # or False, add cells at cell bottom
                                    bore_depth = None, # '[0,5,10] for 3 particles or None
                                    track_dir = 'backward',
                                    # track_dir = 'forward', # backward
                                    sel_random = None, # or int
                                    sel_slice = None, # or int
                                    )

if sim_state == 'steady':
    if success_modflow == True:
        model_modpath = BV.preprocessing_modpath(model_modflow)
        success_modpath = BV.processing_modpath(model_modpath, write_model=True, run_model=True)
    if success_modpath == True:
        BV.postprocessing_modpath(model_modpath,
                                  ending_point=True,
                                  starting_point=True,
                                  pathlines_shp=True,
                                  particles_shp=False,
                                  random_id=None, # select randomly to save (for pathlines and particles)
                                  ) # None
        
        BV.filtprocessing_modpath(model_modpath,
                                  norm_flux=True, # for forward only
                                  filt_time=True, # delete particles with time at 0, add a column with time divided by 365 (considering recharge in days)
                                  filt_seep=True, # only forward, keep only particles finishing in zone1 (seepage), keep only particles finishing in k1 (first layer)
                                  filt_inout=True, # delete particles in and out in the same cell (first layer)
                                  calc_rtd=True, # compute residence time distribution
                                  random_id=None, # select randomly to keep
                                  ) # None

#%% TIMESERIES

timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                  model_modpath=model_modpath,
                                                  actual_date=True, 
                                                  subbasin_results=True,
                                                  freq_time=freq_time) # or None

#%% ---- PLOT

#%% 2D

# if sim_state == 'steady':
visu = visualization_results.Visualization(BV, model_name)
visu.visual2D(object_list = ['map','grid',
                             'watertable', 'watertable_depth',
                             'drain_flow','surface_flow',
                             'pathlines', 'residence_times'
                             ],
              color_scale = [(None,None),(None,None),
                             (None,None),(0,10),
                             (None,None),(None,None),
                             (0,100),(None,None),
                             ], 
              lines=500)

#%% RAW MAP 1

lead_numb = '0'
outflow = imageio.imread(simulations_folder+model_name+'/_postprocess/_rasters/accumulation_flux_t(0).tif')
demData = imageio.imread(BV.geographic.watershed_dem)
demData = np.ma.masked_array(demData, mask=demData<0)
res = BV.geographic.resolution

msk_outflow = (outflow<0)
outflow = np.ma.masked_array(outflow, mask=msk_outflow)
outflow = ( np.ma.masked_where(outflow==0, outflow) / (res**2) )
outflow = outflow * 1000 * 365 # mm/year
outflow = np.log10(outflow)

from matplotlib.colors import LightSource
ls = LightSource(azdeg=45, altdeg=45)
cmap = plt.cm.Greys
rgb = ls.shade(demData, cmap=cmap, blend_mode='soft', vert_exag=2, dx=res, dy=res)

fig, ax = plt.subplots(1, 1, figsize=(8,8))
ax.get_xaxis().set_visible(False)
ax.get_yaxis().set_visible(False)
im = ax.imshow(demData, alpha=0.8, cmap=cmap)
im = ax.imshow(rgb, alpha=0.8, cmap=cmap)
cf=ax.imshow(outflow, cmap='YlGnBu', alpha=1, vmin=outflow.min(), vmax=outflow.max())

name_fig = 'map_discharge_' + str(lead_numb) + '.png'
plt.tight_layout()

# fig.savefig(os.path.join(simulations_folder, model_name,
#                             '_postprocess', '_figures', 'RAW_'+model_name+'.png'))

#%% RAW MAP 2

shp_pathlines = gpd.read_file(simulations_folder+model_name+'/_postprocess/_particles/pathlines.shp')
# shp_endpoints = gpd.read_file(simulations_folder+model_name+'/_postprocess/_particles/ending.shp')
shp_endpoints = gpd.read_file(simulations_folder+model_name+'/_postprocess/_particles/starting.shp')

try:
    line = gpd.read_file(stable_folder+'geographic/'+'watershed_contour.shp')
except:
    pass

dem_rio = rasterio.open(BV.geographic.watershed_box_buff_dem)
dem_data = dem_rio.read(1)
dem_data = np.ma.masked_where(dem_data < 0, dem_data)

fig, ax = plt.subplots(1,1, figsize=(7,5))

rasterio.plot.show(dem_data, ax=ax, transform=dem_rio.transform, 
                    cmap='Greys', alpha=0.7, zorder=0, aspect="auto")

shp_pathlines['time'] = shp_pathlines['time'] / 365
shp_pathlines.plot(ax=ax, column='time', cmap=mpl.colors.ListedColormap(['k']), lw=0.1,
                  norm=mpl.colors.LogNorm(vmin=1, vmax=10000),
                  zorder=1)

shp_endpoints['time'] = shp_endpoints['time'] / 365
shp_endpoints.plot(ax=ax, column='time', cmap='jet', lw=0, markersize=10,
                 norm=mpl.colors.LogNorm(vmin=0.1, vmax=10000), legend=True,
                 zorder=2)

try:
    line.plot(ax=ax, color='k', lw=3)
except:
    pass

ax.set_title('Ending residence times [y]')

ax.get_xaxis().set_visible(False)
ax.get_yaxis().set_visible(False)  

fig.tight_layout()

# fig.savefig(os.path.join(simulations_folder, model_name,
#                             '_postprocess', '_figures', 'RTD_'+model_name+'.png'))

#%% CROSS

if case != 'Example_05_Lasset':

    import flopy.utils.binaryfile as fpu
    
    # Load model
    fname = simulations_folder+model_name+'/'+model_name
    ml = flopy.modflow.Modflow.load(fname+'.nam')
    hdobj = flopy.utils.HeadFile(fname + '.hds')
    times = hdobj.get_times()
    head = hdobj.get_data(totim=times[0])
    
    # Figure
    fig = plt.figure(figsize=(10, 4))
    ax = fig.add_subplot(1, 1, 1)
    ax.set_title('Cross-section : steady-state') 
    ax.set_xlabel('x [m]')
    ax.set_ylabel('z [m]')
    
    # Head color
    xsect = flopy.plot.PlotCrossSection(model=ml, line={'Row': 0})
    pc = xsect.plot_array(head, masked_values=[999.], head=head, cmap='Blues_r',
                          vmin=0, vmax=200,
                          alpha=0.8)
    cb = plt.colorbar(pc, shrink=0.75)
    cb.set_label('Head [m]', labelpad=+10)
    wt = xsect.plot_surface(head, masked_values=[999.], color='b', lw=1)
    
    # Boundary
    patches = xsect.plot_ibound(head=head)
    
    # Grid
    linecollection = xsect.plot_grid(alpha=0.75, zorder=0)
    
    # General fluxes
    cbb = fpu.CellBudgetFile(fname + '.cbc')
    kstpkper = (0, 0)
    Qx = cbb.get_data(text='FLOW RIGHT FACE', kstpkper=kstpkper, totim=times[0])[0]
    Qy = np.ones(shape=(10,1,100))
    Qz = cbb.get_data(text='FLOW LOWER FACE', kstpkper=kstpkper, totim=times[0])[0]
    drain = cbb.get_data(text='DRAINS', kstpkper=kstpkper, totim=times[0])[0]
    Q = np.sqrt(Qx**2 + Qz**2) # ???
    Q_print = Q[0,0,0] # m/m
    
    # Particules plot
    shp = gpd.read_file(simulations_folder+model_name+'/_postprocess/_particles/particles.shp')
    # list_particules = shp['particleid'].unique()
    shp['time'] = shp['time'] / 365
    shp_fil = shp[shp['time']>1]
    sc = ax.scatter(shp_fil['x'], shp_fil['z'], c=shp_fil['time'],
               s=20, cmap='plasma_r', linewidths=0)
    cbsc = plt.colorbar(sc, shrink=0.75)
    cbsc.set_label('Residence times [y]', labelpad=+10)
    
    # fig.savefig(os.path.join(simulations_folder, model_name,
    #                             '_postprocess', '_figures', 'CROSS_'+model_name+'.png'))

#%% ---- NOTES

os.chdir(root_dir)

# wbt.geomorphons(
#     'xxx/watershed_box_buff_dem.tif', 
#     'xxx/watershed_box_geomorphons.tif', 
#     search=5, # in cell
#     threshold=0, # angle in degree
#     fdist=0, # in cell  
#     skip=0, # in cell
#     forms=True, 
#     residuals=False, 
# )


