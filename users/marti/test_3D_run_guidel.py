# -*- coding: utf-8 -*-
"""
Created on Fri Jan  6 16:15:34 2023

@author: ronan
"""

#%% INFORMATION
"""
Example to test MODPATH: pathlines and residence times
- Study site in Guadeloupe with residence times measurement targets
- Estimate K in steady-state from a stream network layer: Kcalib
- Launch MODPATH from different complexity of hydraulic properties hetrogeneity 
  with a bottom flat aquifer:
    .K lower layer = K upper layer
    .K lower layer = K upper layer / 10
    .K lower layer = K upper layer * 10
        *where Kupper = Kcalib and the lower layer start from 50 m
- Option for modeling particles:
    . Forward from all cells at the surface of target
    . Backward from all cells at the surface of target
- Post-processing on the pathlines and strating/endpoint
    . Identified the pathlines passed through a geological formation or not
        *using the 'pthobj' MODLFOW
    . From indices obtained, apply mask on pathlines/starting/ending files
        *using the shapefiles created
"""
#%% LIBRAIRIES

import os
import sys
import numpy as np
import matplotlib.pyplot as plt
import glob
from os.path import dirname, abspath
import pandas as pd
import geopandas as gpd
import matplotlib as mpl
from mpl_toolkits.axes_grid1 import make_axes_locatable
from matplotlib.colors import Normalize
root_dir = dirname(dirname(dirname(abspath(__file__))))
sys.path.append(root_dir)
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = True
from datetime import datetime
import deepdish as dd
import imageio
import rasterio
import flopy
import pickle
import random
from matplotlib_scalebar.scalebar import ScaleBar
from rasterio.plot import show
import rioxarray as rxr
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.ticker import FormatStrFormatter
import xarray as xr

from watershed import watershed_root, watershed_display, forcing
from watershed.data import climatic
from calibration import calib_root, calib_analysis, calib_basis
from tools import toolbox, vtk
from groundwater_flow import visualization, modflow, modflow_display

#%% USERS

# user_path = "Martin"
user_path = "Etienne"
data_path = "D:/emarti/Britanny/data/"
out_path = "D:/emarti/Britanny/"
fig_path = "xxx"
  
print("Define a well-validated name of user")

#%% PATHS REGIO

# watershed_name = 'Tiretaine2'
# watershed_name = 'Frasne_coord'
watershed_name = 'Guidel'

library_path = data_path + 'watershed_library.csv' # each row is a study site with outlet coordinates

# dem_name = "Frasne_25m_BDALTIV2_0925_6650_MNT.tif"
dem_name = "BDALTI_bzh_25m_L2.tif"

from_shp = []
# from_shp = "D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/PROJECTS/PUYS/_data/BV Tiretaine.shp"
    
from_dem = False
cell_size = None

#from_xy = [162018.733,2322322.165,500,20] #From watershed_library
from_xy = [163915.094,2321962.143,500,20] #From gaunging station position
# from_xy = [948344.009,6647659.757,500,25] # coord large

    
climate_path =  None
dem_path = os.path.join(data_path ,dem_name)
# socle_path = "D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/PROJECTS/PUYS/_data/MNT_socle_5000r_25g_kriglin1.tif"
# bottom_path = socle_path
bottom_path = None

modflow_path =  "D:/emarti/Chile/data/MODFLOW/"

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
#%%

dem_data =  rxr.open_rasterio(dem_path, masked=True).squeeze()
dem_data.plot()

#%% WATERSHED

load = True
# load = True
# False to build and save python object4

BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path,
                              out_path=out_path,
                              modflow_path=modflow_path,
                              library_path=[],
                              load=load,
                              from_shp=from_shp,
                              from_dem=from_dem,
                              from_xy=from_xy,
                              cell_size=cell_size,
                              bottom_path=bottom_path)

BV.add_oceanic('None')
#%% DATA

types_obs = ['streams']
fields_obs = ['fid']

#BV.add_hydrology(hydrology_path, types_obs=types_obs, fields_obs=fields_obs)

BV.add_oceanic('None')
BV.add_hydrodynamic()
BV.add_forcing()
    
watershed_display.watershed_dem(BV)
watershed_display.watershed_local(dem_path, BV)
#em_data =  rxr.open_rasterio(BV.geographic.watershed_box_buff_dem, masked=True).squeeze()

#%%

dict_df={}
for filename in os.listdir(data_path+'geol_model/raw/'):
    print(filename)
    geol_df = pd.read_csv(data_path+'geol_model/raw/'+filename,sep=' ')
    dict_df[filename]=geol_df

model_geol=pd.concat(dict_df.values(), ignore_index=True)
model_geol.to_csv(data_path+'geol_model/geol_model_XYZ.txt',index=None, sep=' ')

#%% ---- MODELING

#%% CASES

######################
case = 't1'
typ = case
######################

BV.add_hydrodynamic()
BV.add_forcing()

# Import K calibrated
Koptim = 1E-5
print(Koptim)

# Discretization
nlay = 12 # vertical discrtization
# thick_exp = 1.2 # exponential decay of nlay with depth
thick_exp = 1 # exponential decay of nlay with depth

# Climate
recharge = 500 / 1000 / 365 # m/y to m/d

# Porosity
Sy = 0.1 # Charlotte ==> 10%

K = Koptim * 3600 * 24 # upper layer
cond_decay = 0 # exponential decay of K with depth : 0.02
verti_k = None # "k1", or None

# Aquifer
thick = 100
bottom = min(model_geol['Z'])
typ = case

#%% OPTIONS

# Option
sim_state = 'steady' # 'steady' or 'transient'
# modpath_sim = True # run modpath particle tracking if True
modpath_sim = False # run modpath particle tracking if True
modpath_sim = True # run modpath particle tracking if True

run = True

# Input recharge
time_step = 'D' # or 'D'
actual_date = False # False if date is conceptual

# Active of not modules
box = True
# zone_partic = 'watershed_box_buff' # watershed or watershed_buff
# zone_partic = 'watershed' # watershed or watershed_buff
zone_partic = 'domain' # watershed or watershed_buff
sink_fill = False # permit to fill sinks
verbose = True # add print of MODFLOW in console
post_process = False # necessary to decompose post process of process

# Recharge
init_rech = None
BV.forcing.update_recharge(recharge, sim_state=sim_state) #

xyz_3D=data_path+'geol_model/geol_model_XYZ.txt'
val_3D=data_path+'geol_model/hydro_parameters_guidel.txt'

#%% RUN

# Label
list_model_name = []
list_of_success = []
list_flow_model = []

# Update properties
compt = 1

BV.hydrodynamic.update_nlay(nlay) # 1
BV.hydrodynamic.update_bottom(bottom) # None
BV.hydrodynamic.update_thick_exp(thick_exp) # 1
BV.hydrodynamic.update_thickness(thick) # 30 / intervient pas si bottom != None

BV.hydrodynamic.update_porosity(Sy)
  
date_today = datetime.now().strftime("%d/%m/%Y %H:%M:%S") # just a string
date_today = date_today.replace('/','-')
date_today = date_today.replace(':','-')
date_today = date_today.replace(' ','_')
    
BV.hydrodynamic.update_hyd_cond(K)
compt=0
model_name = typ+'_'+str(compt)+'_'+\
                 str(Sy)+'-'+str(round(K,3))+'-'+str(thick)+'_'+str(nlay)
BV.hydrodynamic.update_cond_decay(cond_decay) # 0

print('SIM - ' + model_name)

success = True
  
success, flow_model = BV.run_modflow(ident=model_name,
                                     run=run,
                                     modpath_sim=modpath_sim,
                                     sink_fill=sink_fill,
                                     zone_partic=zone_partic,
                                     box=box,
                                     verbose=verbose,
                                     post_process=post_process, 
                                     init_rech=init_rech,
                                     verti_k=verti_k,
                                     from_3D=True,
                                     xyz_3D=xyz_3D,
                                     val_3D=val_3D,
                                     idx_3D=data_path,
                                     ext_3D=1,
                                     )
    
if success == True:
    print(     'Success')
else:
    print(     'Error')
# except:
#     pass
list_model_name.append(model_name)
list_of_success.append(success)
list_flow_model.append(flow_model)
compt+=1
        
print(list_of_success)

dictio = {}
dictio['list_model_name'] = list_model_name
dictio['list_of_success'] = list_of_success
dictio['list_flow_model'] = list_flow_model
h5file = simulations_folder+'/'+'list_'+typ

# dd.io.save(h5file, dictio)

#%% ---- POST-PROCESS

#%% LOAD MODELS

modpath_sim

h5file = simulations_folder+'/'+'list_'+typ
d = dd.io.load(h5file)
list_model_name = d['list_model_name'][:]
list_of_success = d['list_of_success'][:]
list_flow_model = d['list_flow_model'][:]

#%% EXTRACT RESULTS

cp = 0

for model_name, success, flow_model in zip(list_model_name, list_of_success, list_flow_model):
        
    if success==True:
            print(success)
            
            if modpath_sim == True:
                residence_times=True
            else:
                residence_times=False
            
            BV.matrix_modflow(success,
                              flow_model,
                              first_only = True,
                              watertable_elevation = True,
                              watertable_depth = True, 
                              seepage_areas = True,
                              outflow_drain = True,
                              groundwater_flux = False,
                              specific_discharge = False,
                              accumulation_flux = True,
                              perenn_intermit_shp = False,
                              groundwater_storage = True,
                              residence_times = residence_times,
                              verbose = True,
                              export_tif = True)
            
            # Necessary for results_modflow
            BV.forcing.update_recharge(flow_model.climatic,
                                       sim_state=sim_state)
            
            # # Extract results
            BV.results_modflow(ident=model_name,
                               actual_date=actual_date,
                               time_step=time_step)
            
            ## Plot maps
            # surf = modflow_display.SurfaceOutputs(flow_model.climatic, simulations_folder, stable_folder,
            #                                       model_name, types_obs,
            #                                       save_gif=False,
            #                                       first_only=True,
            #                                       sim_state=sim_state,
            #                                       outflow=False,
            #                                       accflux=True,
            #                                       intermittency=False,
            #                                       chronics=False)
            
            cp+=1

#%% 2D MAP VIEW
###Mapa de topografia con grilla MODFLOW 	
mf = flopy.modflow.Modflow.load(simulations_folder+model_name+'/'+model_name+'.nam')

#fname = simulations_folder+model_name+'/'+model_name+'.hds'
#gridname = simulations_folder+model_name+'/'+model_name+'.dis'
# grid_model = flopy.discretization.grid.Grid(mf)
grid_model = mf.modelgrid
hk_grid = mf.upw.hk
grid_geol = hk_grid.array
fig             = plt.figure(figsize=(16, 16))
modelmap = flopy.plot.PlotMapView(model= mf)
modelmap.plot_array(hk_grid.array)
#modelmap.plot_grid()
#modelmap.plot_ibound()
#plt.axhline(int(nrow/2)*resolution,c='r') #Lineas representando las posiciones de las secciones transversales
#plt.axvline(int(ncol/2)*resolution,c='r')
plt.show()

#%%

#unique_values = [2222, 3333, 4444, 5555, 6666, 7777]
unique_values = [1e-10, 1e-8, 1e-7, 1e-6, 1e-5, 1e-3]
#unique_colors = ['blue', 'royalblue', 'mediumspringgreen', 'greenyellow', 'orange', 'red']
unique_colors = [ 'mediumspringgreen','royalblue', 'orange',  'greenyellow', 'blue','red']
value_color_mapping = {value: color for value, color in zip(unique_values, unique_colors)}
cmap = LinearSegmentedColormap.from_list('custom_colormap', unique_colors, N=len(unique_values))



#%%
box = rxr.open_rasterio(BV.geographic.watershed_box_buff_dem, masked=True).squeeze()
extent = box.x.min(), box.x.max(), box.y.min(), box.y.max()
cuenca = gpd.read_file(BV.geographic.watershed_shp)

#%%

row_xc=72
col_xc=26
fig, axs = plt.subplots(1, 2, figsize=(24, 6))
# ax = fig.add_subplot(1, 1, 1)
axs = axs.ravel()
modelxsect = flopy.plot.PlotCrossSection(model=mf, line={'Row': row_xc})
linecollection = modelxsect.plot_grid()
modelxsect.plot_array(hk_grid.array, ax=axs[0],cmap=cmap,vmin=min(unique_values), vmax=max(unique_values),norm=matplotlib.colors.LogNorm())
# axs[0].set_xlim(2000, 18000)
axs[0].set_ylim(-500, 200)
axs[0].set_title('Y= '+str(int(extent[3]-(row_xc*BV.geographic.resolution)))+'  -  Facies')
modelxsect = flopy.plot.PlotCrossSection(model=mf, line={'Column': col_xc})
linecollection = modelxsect.plot_grid()
#hdobj = flopy.utils.HeadFile(fname)
#head_data = hdobj.get_data()
p = modelxsect.plot_array(hk_grid.array, ax=axs[1], cmap=cmap,vmin=min(unique_values), vmax=max(unique_values),norm=matplotlib.colors.LogNorm())
axs[1].set_ylim(-500, 200)
# axs[0].set_ylim(700, 1200)
axs[1].set_title('X= '+str(int(extent[0]+(col_xc*BV.geographic.resolution)))+'  -  Facies')
#%%

fig,ax=plt.subplots(figsize=(12,10))
im = plt.imshow(grid_geol[0,:-1,:-1],extent=extent, cmap=cmap,norm=matplotlib.colors.LogNorm(vmin=min(unique_values), vmax=max(unique_values)))
plt.axhline(extent[3]-(row_xc*BV.geographic.resolution),c='k') #Lineas representando las posiciones de las secciones transversales
plt.axvline(extent[0]+(col_xc*BV.geographic.resolution),c='k')
cuenca.plot(color='None', edgecolor='black',linewidths=3, ax=ax)
cbar = plt.colorbar(im, ax=ax, ticks=unique_values, label='Facies',shrink=0.7)
plt.gca().yaxis.set_major_formatter(FormatStrFormatter('%d'))
plt.gca().xaxis.set_major_formatter(FormatStrFormatter('%d'))

#%%

da = xr.DataArray(
        data = grid_geol[0,:,:],
        dims = ['Y','X'],
        coords = {'Y': box.y.values,'X': box.x.values}
      )

da.rio.set_spatial_dims('X','Y').rio.to_raster('D:/emarti/Britanny/Guidel_geol_lay0.tif')



# ds.rio.to_raster('D:/emarti/Britanny/Guidel_geol_lay0.tif')  

#%%
for model_name, success, flow_model in zip(list_model_name, list_of_success, list_flow_model):

    list_path = sorted(glob.glob(simulations_folder+typ+'*'),
                        key=os.path.getmtime, reverse=True)
    
    model_name = list_path[-1].split('\\')[-1]

    visu = visualization.Visualization(BV, model_name)
    
    visu.visual2D(object_list = ['map', 'grid', 'watertable', 'watertable_depth',
                                 'drain_flow', 'surface_flow'],
                  color_scale = [(None,None),(None,None),(None,None),(0,10),
                                  (None,None),(None,None)])

#%% CROSS SECTION

list_selects = list_model_name

fig_cross = True

for model_name, flow_model in zip(list_selects[:], list_flow_model[:]):
    print(model_name)
    # if model_name == 'egu1_0_500.0-0-0.0058-30.0':
    # try:
        
    id_model = int(model_name.split('_')[1])
            
    ### MODEL ###
    # list_path = sorted(glob.glob(simulations_folder+typ+'*'), key=os.path.getmtime, reverse=True)
    # model_name = list_path[-1].split('\\')[-1]
    mf = flopy.modflow.Modflow.load(simulations_folder+model_name+'/'+model_name+'.nam')
    
    fname = simulations_folder+model_name+'/'+model_name+'.hds'
    gridname = simulations_folder+model_name+'/'+model_name+'.dis'
    # grid_model = flopy.discretization.grid.Grid(mf)
    grid_model = mf.modelgrid
    hk_grid = mf.upw.hk
    # sy_grid = mf.upw.sy
    sy_grid = flow_model.ps
    # sr_model = flopy.utils.reference.SpatialReference()
    
    if fig_cross == True:
        
        fig, axs = plt.subplots(1, 2, figsize=(12, 3))
        # ax = fig.add_subplot(1, 1, 1)
        axs = axs.ravel()
        modelxsect = flopy.plot.PlotCrossSection(model=mf, line={'Row': 80})
        linecollection = modelxsect.plot_grid()
        hdobj = flopy.utils.HeadFile(fname)
        head_data = hdobj.get_data()
        modelxsect.plot_array(hk_grid.array, ax=axs[0], cmap='jet')
        # axs[0].set_xlim(2000, 18000)
        axs[0].set_ylim(-500, 200)
        axs[0].set_title('Row  -  Hydraulic conductivity')
        pc = modelxsect.plot_array(head_data, masked_values=[-9999], head=head_data,
                                    cmap='Blues', alpha=0.5, ax=axs[1])
        # axs[0].set_xlim(2000, 18000)
        axs[1].set_ylim(-500, 200)
        axs[1].set_title('Watertable and hydraulic gradient')
        fig.suptitle(model_name, y=1.05, fontsize=8)
        
        # bv_box = gpd.read_file(stable_folder+'geographic/'+'box_buff.shp')
        # ext_mod = bv_box.geometry.total_bounds
        
        # axs[0].set_ylim(150, 350)
        # axs[1].set_ylim(150, 350)
        
        # fig.savefig(fig_path+'cross_section_h_'+model_name+'.png', dpi=300, bbox_inches='tight')

        fig, axs = plt.subplots(1, 2, figsize=(12, 3))
        # ax = fig.add_subplot(1, 1, 1)
        axs = axs.ravel()
        modelxsect = flopy.plot.PlotCrossSection(model=mf, line={'Column': int((grid_model.shape[2])/2)})
        linecollection = modelxsect.plot_grid()
        hdobj = flopy.utils.HeadFile(fname)
        head_data = hdobj.get_data()
        modelxsect.plot_array(sy_grid, ax=axs[0], cmap='YlGn_r')
        # axs[0].set_xlim(2000, 18000)
        # axs[0].set_ylim(700, 1200)
        axs[0].set_title('Column  -  Porosity')
        pc = modelxsect.plot_array(head_data, masked_values=[-9999], head=head_data,
                                    cmap='Blues', alpha=0.5, ax=axs[1])
        
        # axs[1].set_xlim(2000, 18000)
        # axs[1].set_ylim(700, 1200)
        axs[1].set_title('Watertable and hydraulic gradient')
        fig.suptitle(model_name, y=1.05, fontsize=8)
        
        # bv_box = gpd.read_file(stable_folder+'geographic/'+'box_buff.shp')
        # ext_mod = bv_box.geometry.total_bounds
        
        # axs[0].set_ylim(150, 350)
        # axs[1].set_ylim(150, 350)
        
        # fig.savefig(fig_path+'cross_section_v_'+model_name+'.png', dpi=300, bbox_inches='tight') 

#%% ENDPOINT MODELS

list_selects = list_model_name

fig_cross = True

for model_name, flow_model in zip(list_selects[:], list_flow_model[:]):
    print(model_name)
    # if model_name == 'egu1_0_500.0-0-0.0058-30.0':
    # try:
        
    id_model = int(model_name.split('_')[1])
            
    ### MODEL ###
    # list_path = sorted(glob.glob(simulations_folder+typ+'*'), key=os.path.getmtime, reverse=True)
    # model_name = list_path[-1].split('\\')[-1]
    mf = flopy.modflow.Modflow.load(simulations_folder+model_name+'/'+model_name+'.nam')
    
    fname = simulations_folder+model_name+'/'+model_name+'.hds'
    gridname = simulations_folder+model_name+'/'+model_name+'.dis'
    # grid_model = flopy.discretization.grid.Grid(mf)
    grid_model = mf.modelgrid
    hk_grid = mf.upw.hk
    # sy_grid = mf.upw.sy
    sy_grid = flow_model.ps
    # sr_model = flopy.utils.reference.SpatialReference()
    
    crs_code = 2154

    """
    def reproj_approx_points(shp_name, crs_code):
        shp = gpd.read_file(simulations_folder+
                            model_name+'/'+'_pathlines/'+
                            shp_name+'.shp')
        ext_shp = shp.geometry.total_bounds
        shp.set_crs(epsg=crs_code, inplace=True, allow_override=True)
        # shp.to_crs(utm_crs)
        print(ext_shp)
        x = (shp.geometry.x) + ext_mod[0] # - ext_shp[0] # 6.39e5 
        y = (shp.geometry.y) + ext_mod[1] # - ext_shp[3] # 1.78e6 
        gdf = gpd.GeoDataFrame(shp, geometry=gpd.points_from_xy(x, y))
        gdf.to_file(simulations_folder+
                    model_name+'/'+'_pathlines/'+
                    shp_name+'.shp')
    """
    
    ### POINTS ###
    print('Create shapefile ending and starting points')
    endobj = flopy.utils.EndpointFile(simulations_folder+
                                      model_name+'/'+model_name+'.mpend')
    e = endobj.get_alldata()
    
    endobj.write_shapefile(endpoint_data=e,
                            shpname=simulations_folder+
                                    model_name+'/'+'_pathlines/'+
                                    'ending.shp',
                            direction='ending',
                            mg=grid_model, epsg=crs_code, sr=None)
    path_pathlines = simulations_folder+model_name+'/'+'_pathlines/'
    shp_sim = gpd.read_file(path_pathlines+'ending.shp')
    shp_sim.time = shp_sim.time / 365
    shp_sim.to_file(simulations_folder+
                         model_name+'/'+'_pathlines/'+
                         'ending_years.shp') # time in years !
    masked = shp_sim.copy()
    masked = masked[masked.time > 0.1] # ONLY SUP ONE MONTH APPROX
    masked = masked[masked.k == 1] # ONLY OUT FIRST CELL
    masked = masked[masked.zloc != 1] # NOT IN AND OUT SAME CELL
    if not masked[masked.time > 1000].empty:
        print('THERE IS CELL > 1000y')
        if len(masked[masked.time > 1000]) <= (len(masked)*0.05):
            print('DELETE > 1000y', str(len(masked[masked.time > 1000]))+'/'+
                                    str((len(masked))))
            # IF ONLY 5% CELL ARE HIGHER THAN 1000 YEARS : MASKED (OUTLIERS):
            masked = masked[masked.time <= 1000]
        else:
            print('NO CELL > 1000y')
    masked.to_file(simulations_folder+
                         model_name+'/'+'_pathlines/'+
                         'ending_years_masked.shp') # time in years !
    keep_particules = masked.particleid
    keep_particules = keep_particules.tolist()
    
    endobj.write_shapefile(endpoint_data=e,
                            shpname=simulations_folder+
                                    model_name+'/'+'_pathlines/'+
                                    'starting.shp',
                            direction='starting',
                            mg=grid_model, epsg=crs_code, sr=None)
    path_pathlines = simulations_folder+model_name+'/'+'_pathlines/'
    shp_sim = gpd.read_file(path_pathlines+'starting.shp')
    shp_sim.time = shp_sim.time / 365
    shp_sim.to_file(simulations_folder+
                         model_name+'/'+'_pathlines/'+
                         'starting_years.shp') # time in years !
    
    # reproj_approx_points('ending')
    # reproj_approx_points('starting')
    
    #### SELECT PARTICLUES ####
    if not os.path.exists(simulations_folder+'_id_particules_random.data'):
        id_particules_random = random.sample(keep_particules[:-1], 1000)
        with open(simulations_folder+'_id_particules_random.data', 'wb') as f:
            pickle.dump(id_particules_random, f)
    # else:
    #     with open(simulations_folder+'_id_particules_random.data', 'rb') as f:
    #         id_particules_random = pickle.load(f)

    #     print('VALID '+model_name)
    # except:
    #     print('ERROR '+model_name)
    #     pass

#%% PATHLINES MODELS

list_path = sorted(glob.glob(simulations_folder+typ+'*'), key=os.path.getmtime, reverse=True)
list_selects = list_model_name

for model_name in list_selects[:]:

    ### MODEL ###

    mf = flopy.modflow.Modflow.load(simulations_folder+model_name+'/'+model_name+'.nam')
    
    fname = simulations_folder+model_name+'/'+model_name+'.hds'
    gridname = simulations_folder+model_name+'/'+model_name+'.dis'
    # grid_model = flopy.discretization.grid.Grid(mf)
    grid_model = mf.modelgrid
    hk_grid = mf.upw.hk
    # sr_model = flopy.utils.reference.SpatialReference()

    bv_box = gpd.read_file(stable_folder+'geographic/'+'box_buff.shp')
    ext_mod = bv_box.geometry.total_bounds
    
    crs_code = 2154 # 32620 # 2154
    
    ### PATHLINES ###
    print('Create shapefile particules and pathlines')
    pthobj = flopy.utils.PathlineFile(simulations_folder+
                                      model_name+'/'+model_name+'.mppth')
    pth_data = pthobj.get_alldata()
    
    for k in range(len(pth_data)):
        pth_data[k].time = pth_data[k].time / 365
    # from operator import itemgetter
    # n = itemgetter(*keep_particules)(pth_data)
    
    with open(simulations_folder+'_id_particules_random.data', 'rb') as f:
        id_particules_random = pickle.load(f)
    
    # pth_data_rand = [pth_data[i] for i in id_particules_random[:-1]]

    # x= list(map(lambda i: pth_data[i], keep_particules))
    # x = pth_data[::2]
        
    # id_particules_random = random.sample(keep_particules[:-1], 1000)
    
    # random.sample(keep_particules[:-1], 1000)
    
    pth_data_save = []
    for o, i in enumerate(id_particules_random):
        print(o, i, len(id_particules_random))
        for j in pth_data:
            if i == j.particleid[0]:
                pth_data_save.append(j)
                    
    # pthobj.write_shapefile(pathline_data=pth_data,
    #                         shpname=simulations_folder+
    #                                 model_name+'/'+'_pathlines/'+
    #                                 'particlues.shp',
    #                         one_per_particle=False, 
    #                         direction='ending',
    #                         mg=grid_model, epsg=crs_code, sr=None)
        
    # pth_data_springs = []
    # for o, i in enumerate(sp_particules):
    #     print(o, i, len(sp_particules))
    #     for j in pth_data_save:
    #         if i == j.particleid[0]:
    #             pth_data_springs.append(j)
    
    """
    ### ALL PATHLINES
    print('ALL PATHLINES')
    pthobj.write_shapefile(pathline_data=pth_data,
                            shpname=simulations_folder+
                                    model_name+'/'+'_pathlines/'+
                                    'pathlines.shp',
                            one_per_particle=True, 
                            direction='ending',
                            mg=grid_model, epsg=crs_code, sr=None)
    
    ### ALL PARTICULES
    print('ALL PARTICULES')
    pthobj.write_shapefile(pathline_data=pth_data,
                            shpname=simulations_folder+
                                    model_name+'/'+'_pathlines/'+
                                    'particules.shp',
                            one_per_particle=False, 
                            direction='ending',
                            mg=grid_model, epsg=crs_code, sr=None)
    """
    
    ### 1000 pathlines
    print('1000 pathlines')
    pthobj.write_shapefile(pathline_data=pth_data_save,
                            shpname=simulations_folder+
                                    model_name+'/'+'_pathlines/'+
                                    'pathlines_1000.shp',
                            one_per_particle=True, 
                            direction='ending',
                            mg=grid_model, epsg=crs_code, sr=None)
    
    ### 1000 particules
    print('1000 particules')
    pthobj.write_shapefile(pathline_data=pth_data_save,
                            shpname=simulations_folder+
                                    model_name+'/'+'_pathlines/'+
                                    'particules_1000.shp',
                            one_per_particle=False,
                            direction='ending',
                            mg=grid_model, epsg=crs_code, sr=None)

#%% ---- NOTES

