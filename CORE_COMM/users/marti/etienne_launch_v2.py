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
import rioxarray as rxr
import matplotlib as mpl
from mpl_toolkits.axes_grid1 import make_axes_locatable
from matplotlib.colors import Normalize
root_dir = dirname(dirname(dirname(abspath(__file__))))
sys.path.append(root_dir)
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False
from datetime import datetime
import deepdish as dd
import imageio
import rasterio
import flopy
import pickle
import random
from matplotlib_scalebar.scalebar import ScaleBar
from rasterio.plot import show

from watershed import watershed_root, watershed_display, forcing
from watershed.data import climatic
from calibration import calib_root, calib_analysis, calib_basis
from tools import toolbox, vtk
from groundwater_flow import visualization, modflow_display

#%% USERS
user_path = "Etienne"
data_path = "D:/emarti/Tarapaca/data/"
out_path = "D:/emarti/Tarapaca/out/final"
fig_path = "D:/emarti/Tarapaca/figures"
  
print("Define a well-validated name of user")


#%%Read larger DEM file once 
north_chile_dem=rxr.open_rasterio(data_path+'DEM/study_area_DEM_UTM.tif', masked=True).squeeze()
#%% PATHS

watershed_name = 'Tarapaca'
#watershed_name = '6080791570'
#watershed_name = '6080714050'
#watershed_name = '6080811470'

library_path = data_path + 'watershed_library.csv' # each row is a study site with outlet coordinates

if watershed_name == 'Tarapaca':
    from_xy = [470009,7807292,500,20]
    depth = 20 ###20m depth from pozo DGA (Pozo Enpachica)
    from_shp = None
    dem_path = data_path + "/DEM/" + "SRTM_90M_Tarapaca_UTM.tif"
else:
    if watershed_name == '6080791570':
        #from_xy = []
        depth= 60  ### 60m nivel estatico
        from_shp = [data_path+'shapefiles_BV/6080791570.shp',20]
        gdf = gpd.read_file(from_shp[0])
        
        
    if watershed_name == '6080714050' :
        from_xy = []
        depth= 35 ###35,5m nivel estatico y pozo DGA (El Carmelo 2) 33m
        from_shp = data_path+'shapefiles_BV/6080714050.shp'
        gdf = gpd.read_file(from_shp)
        
    if watershed_name == '6080811470' :
        from_xy = []
        depth = 37 ##37.5m nivel estatico
        from_shp = data_path+'shapefiles_BV/6080811470.shp'
        gdf = gpd.read_file(from_shp)
    
    
    gdf_buffer = gdf.buffer(35000)
    regional_dem = north_chile_dem.rio.clip(gdf_buffer, drop=True)
    regional_dem.rio.to_raster(raster_path=data_path+'DEM/'+str(watershed_name)+'.tif')
    dem_name = 'DEM/'+str(watershed_name)+'.tif'
    dem_path = os.path.join(data_path,dem_name)
    
    #from_shp = None
    from_dem = False
    cell_size = None
        


climate_path =  None


x=imageio.imread(dem_path)
plt.imshow(x)

geology_path = None
hydrology_path = os.path.join(data_path)
hydrometry_path = 'None' # add hydrometry data for automatic download
intermittency_path = 'None' # add intermittency data for automatic download
modflow_path = os.path.join(data_path,'modflow')
oceanic_path = None
piezometry_path = True # add piezometry data for automatic download
subbasin_path = True # generate subbasins from stations or manual points

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots

#%% WATERSHED

load = True
# False to build and save python object4

BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              modflow_path=modflow_path,
                              library_path=library_path,
                              load=load,
                              from_shp=from_shp,
                              from_dem=from_dem,
                              from_xy=from_xy,
                              cell_size=cell_size)

BV.add_hydrometry(hydrometry_path)
BV.add_intermittency(intermittency_path)
BV.add_subbasin()

#%% DATA

types_obs = ['streams']
fields_obs = ['fid']

BV.add_hydrology(hydrology_path, types_obs=types_obs, fields_obs=fields_obs)

BV.add_oceanic('None')
BV.add_hydrodynamic()
BV.add_forcing()
    
watershed_display.watershed_dem(BV)
watershed_display.watershed_local(dem_path, BV)
dem_data =  rxr.open_rasterio(BV.geographic.watershed_box_buff_dem, masked=True).squeeze()
#%%
# Plot dem
fig , ax2 = plt.subplots(figsize=(16,9))

extent = dem_data.x.min(), dem_data.x.max(), dem_data.y.min(), dem_data.y.max()
cuenca = gpd.read_file(BV.geographic.watershed_shp)
#dem_data[dem_data<0] = np.nan
x = plt.imshow(dem_data, extent=extent)
cuenca.plot(color='None', edgecolor='red',linewidths=1.5, ax=ax2)
#ax2.scatter(454643, 7803303, color='r', s=25)


#%% ---- MODELING

#%% CASES

defKR = np.logspace(-2,2,25)



# Aquifer
thick = 0 # m
bottom = -1000 # aquifer flat or not

# Discretization
nlay = 10 # vertical discrtization
thick_exp = 1.2 # exponential decay of nlay with depth

# Climate

#recharge = 40 / 1000 / 365 # m/y to m/d

# Porosity
#Sy = [0.01, 0.1] # Charlotte ==> 10%

#Boundary condition
#bc_left = float(min(dem_data[:,0])-depth)

######################
case = 's1'
#case = 's2'
######################

if case == 's1':
    cond_decay = 0 # exponential decay of K with depth : 0.02
    k= 1e-7 * 86400 # m/s en m/j
    verti_k = None
    #Boundary condition
    #bc_left = float(min(dem_data[:,0])-depth)
    # Name
    typ = 's1'
if case == 's2':
    cond_decay = 0 # exponential decay of K with depth : 0.02
    k= 1e-7 * 86400 # m/s en m/j
    verti_k = None
    # Name
    typ = 's2'
    
#%% OPTIONS

# Option
sim_state = 'steady' # 'steady' or 'transient'
modpath_sim = False # run modpath particle tracking if True
# modpath_sim = False # run modpath particle tracking if True

run = True

# Input recharge
time_step = 'D' # or 'D'
actual_date = False # False if date is conceptual

# Active of not modules
box=True
# zone_partic = 'watershed_box_buff' # watershed or watershed_buff
# zone_partic = 'watershed' # watershed or watershed_buff
zone_partic = 'domain' # watershed or watershed_buff
sink_fill = False # permit to fill sinks
verbose = True # add print of MODFLOW in console
post_process = False # necessary to decompose post process of process

# Recharge
init_rech = None
#BV.forcing.update_recharge(recharge, sim_state=sim_state) #

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
BV.hydrodynamic.update_hyd_cond(k)
  
date_today = datetime.now().strftime("%d/%m/%Y %H:%M:%S") # just a string
date_today = date_today.replace('/','-')
date_today = date_today.replace(':','-')
date_today = date_today.replace(' ','_')

for i, KR in enumerate(defKR):
    
    KR_name = round(KR, 3)
    

    #model_name = "KR_"+str(KR_name)+"_layers_nb_"+str(nlay)+"_bchead_"+str(bc_left)+"m_bottom_"+str(bottom)
    model_name = 'KR_'+str(KR_name)+'_layers_nb_'+str(nlay)+'_bottom_'+str(bottom)+'_no_flow_box' # if no BC
    recharge = round(k / KR_name, 7)
    BV.forcing.update_recharge(recharge, sim_state=sim_state)
    print(i, KR, recharge)
    if run == True:
        # try:
        print('SIM - ' + model_name)

        success, flow_model = BV.run_modflow(ident=model_name,
                                             run=run,
                                             modpath_sim=modpath_sim,
                                             sink_fill=sink_fill,
                                             zone_partic=zone_partic,
                                             box=box,
                                             verbose=verbose,
                                             post_process=post_process, 
                                             init_rech=init_rech,
                                             verti_k=verti_k)#, bc_left=bc_left)
                
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

dd.io.save(h5file, dictio)

#%% ---- POST-PROCESS

#%% LOAD MODELS
#watershed_name = '6080714050'
#simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

h5file = simulations_folder+'/'+'list_'+typ
d = dd.io.load(h5file)
list_model_name = d['list_model_name'][:]
list_of_success = d['list_of_success'][:]
list_flow_model = d['list_flow_model'][:]

#%% EXTRACT RESULTS

data_explo = pd.DataFrame(columns=['k0','k1','k0k1','obs','sim','ind']) 

cp = 0

residence_times = False

for model_name, success, flow_model in zip(list_model_name, list_of_success, list_flow_model):
        
    if success==True:
            print(success)
            
            # if modpath_sim == True:
            #     residence_times=True
            # else:
            #     residence_times=False
            
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
            
            # # Necessary for results_modflow
            # BV.forcing.update_recharge(flow_model.climatic,
            #                            sim_state=sim_state)
            
            # # # Extract results
            # BV.results_modflow(ident=model_name,
            #                    actual_date=actual_date,
            #                    time_step=time_step)
            
            # ## Plot maps
            # surf = modflow_display.SurfaceOutputs(flow_model.climatic, simulations_folder, stable_folder,
            #                                       model_name, types_obs,
            #                                       save_gif=False,
            #                                       first_only=True,
            #                                       sim_state=sim_state,
            #                                       outflow=False,
            #                                       accflux=True,
            #                                       intermittency=False,
            #                                       chronics=False)

#%% ---- MODPATH FILES NEW

#%% ENDPOINT MODELS

fig_cross = True

list_path = sorted(glob.glob(simulations_folder+typ+'*'), key=os.path.getmtime, reverse=True)
list_selects = list_model_name

for model_name in list_selects[:]:
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
    # sr_model = flopy.utils.reference.SpatialReference()
    
    if fig_cross == True:
        
        fig, axs = plt.subplots(1, 2, figsize=(12, 3))
        # ax = fig.add_subplot(1, 1, 1)
        axs = axs.ravel()
        modelxsect = flopy.plot.PlotCrossSection(model=mf, line={'Row': int((grid_model.shape[1])/2)})
        linecollection = modelxsect.plot_grid()
        hdobj = flopy.utils.HeadFile(fname)
        head_data = hdobj.get_data()
        modelxsect.plot_array(hk_grid.array, ax=axs[0], cmap='YlOrRd_r')
        pc = modelxsect.plot_array(head_data, masked_values=[-9999], head=head_data,
                                    cmap='Blues', alpha=0.5, ax=axs[1])
        axs[0].set_title('Hydraulic conductivity')
        axs[1].set_title('Watertable and hydraulic gradient')
        fig.suptitle(model_name, y=1.05)
        
        bv_box = gpd.read_file(stable_folder+'geographic/'+'box_buff.shp')
        ext_mod = bv_box.geometry.total_bounds
        
        axs[0].set_ylim(150, 350)
        axs[1].set_ylim(150, 350)
        
        fig.savefig(fig_path+'cross_section_h_'+model_name+'.png', dpi=300, bbox_inches='tight')
        
        fig, axs = plt.subplots(1, 2, figsize=(12, 3))
        # ax = fig.add_subplot(1, 1, 1)
        axs = axs.ravel()
        modelxsect = flopy.plot.PlotCrossSection(model=mf, line={'Column': int((grid_model.shape[0])/2)})
        linecollection = modelxsect.plot_grid()
        hdobj = flopy.utils.HeadFile(fname)
        head_data = hdobj.get_data()
        modelxsect.plot_array(hk_grid.array, ax=axs[0], cmap='YlOrRd_r')
        pc = modelxsect.plot_array(head_data, masked_values=[-9999], head=head_data,
                                    cmap='Blues', alpha=0.5, ax=axs[1])
        axs[0].set_title('Hydraulic conductivity')
        axs[1].set_title('Watertable and hydraulic gradient')
        fig.suptitle(model_name, y=1.05)
        
        bv_box = gpd.read_file(stable_folder+'geographic/'+'box_buff.shp')
        ext_mod = bv_box.geometry.total_bounds
        
        axs[0].set_ylim(150, 350)
        axs[1].set_ylim(150, 350)
        
        fig.savefig(fig_path+'cross_section_v_'+model_name+'.png', dpi=300, bbox_inches='tight')
        
    crs_code = 32620 # 2154

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

# VALID egu1_4_20.0-0.0-0.1359-0.8

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
    
    crs_code = 32620 # 2154
    
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
    
    ### FOR SPRINGS
    path_pathlines = simulations_folder+model_name+'/'+'_pathlines/'
    
    path_obs = data_path+'targets_pathlines_points.shp'
    shp_obs = gpd.read_file(path_obs)
    shp_obs['geometry'] = shp_obs.geometry.buffer(75)
    shp_obs.to_file(simulations_folder+
                    model_name+'/'+'_pathlines/'+
                    'targets_pathlines_points.shp', encoding='utf-8')
    
    masked = gpd.read_file(simulations_folder+
                         model_name+'/'+'_pathlines/'+
                         'ending_years_masked.shp') # time in years !
    intersect = gpd.overlay(masked, shp_obs, how='intersection')
    
    sp_particules = intersect.particleid
    sp_particules = sp_particules.tolist()
    
    # pth_data_springs = [pth_data[i] for i in sp_particules[:]]
    
    shp_all_pathlines = gpd.read_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'pathlines_1000.shp')
    keep = np.isin(shp_all_pathlines, sp_particules)
    shp_springs = shp_all_pathlines[keep]
    shp_springs.to_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'pathlines_1000_springs.shp')

#%% SEPRATE BY LAYERS

list_path = sorted(glob.glob(simulations_folder+typ+'*'), key=os.path.getmtime, reverse=True)
list_selects = list_model_name[:]

for model_name in list_selects[:1]:

    shp_starting = gpd.read_file(simulations_folder+
                        model_name+'/'+'_pathlines/'+
                        'starting_years.shp')
    
    shp_ending = gpd.read_file(simulations_folder+
                        model_name+'/'+'_pathlines/'+
                        'ending_years.shp')
    
    shp_pathlines = gpd.read_file(simulations_folder+
                        model_name+'/'+'_pathlines/'+
                        'pathlines_1000.shp')
    
    shp_particules = gpd.read_file(simulations_folder+
                        model_name+'/'+'_pathlines/'+
                        'particules_1000.shp')
    
    ###### METHOD 1 : PARTIAL
    particleid = shp_particules['particleid'].unique()
    shalid = []
    # bothid = []
    deepid = []
    
    for pid in particleid :
        print(pid, len(particleid))
        mask = shp_particules.loc[shp_particules['particleid']==pid]
        if all(x < 40 for x in mask.k):
            shalid.append(pid)
        if any(x >= 40 for x in mask.k):
            deepid.append(pid)
            
    indices_layers_rdm = [random.sample(shalid, len(shalid)),
                          random.sample(deepid, len(deepid))]    
    
    ###### METHOD 2 : TOTAL
    pthobj = flopy.utils.PathlineFile(simulations_folder+
                                      model_name+'/'+model_name+'.mppth')
    pth_data = pthobj.get_alldata()
    
    cond_lay = 38 # ==> approx. 40 meters
    compt = 0
    indices_layers = []
    superf_p = []
    superf_id = []
    profon_p = []
    profon_id = []
    for idx, pline in enumerate(pth_data):
        if all(x < cond_lay for x in pline.k):
            compt += 1
            # print(compt)
            superf_p.append(pline)
            superf_id.append(pline['particleid'][0])
        else:
            profon_p.append(pline)
            profon_id.append(pline['particleid'][0])     

    indices_layers = [profon_id, superf_id]
    
    # if not os.path.exists(simulations_folder+
    #                       model_name+'/'+'_id_profon_superf.data'):
    with open(simulations_folder+
                      model_name+'/'+'_id_profon_superf.data', 'wb') as f:
        pickle.dump(indices_layers, f)
            
    shp_starting_shal = shp_starting[np.isin(shp_starting.particleid, superf_id)]
    shp_starting_shal.to_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_starting_shal.shp') # time in years !
    shp_starting_deep = shp_starting[np.isin(shp_starting.particleid, profon_id)]
    shp_starting_deep.to_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_starting_deep.shp') # time in years !
    
    shp_ending_shal = shp_ending[np.isin(shp_ending.particleid, superf_id)]
    shp_ending_shal.to_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_ending_shal.shp') # time in years !
    shp_ending_deep = shp_ending[np.isin(shp_ending.particleid, profon_id)]
    shp_ending_deep.to_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_ending_deep.shp') # time in years !
    
    shp_pathlines_shal = shp_pathlines[np.isin(shp_pathlines.particleid, shalid)]
    shp_pathlines_shal.to_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_pathlines_shal.shp') # time in years !
    shp_pathlines_deep = shp_pathlines[np.isin(shp_pathlines.particleid, deepid)]
    shp_pathlines_deep.to_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_pathlines_deep.shp') # time in years !
    
    shp_particules_shal = shp_particules[np.isin(shp_particules.particleid, shalid)]
    shp_particules_shal.to_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_particules_shal.shp') # time in years !
    shp_particules_deep = shp_particules[np.isin(shp_particules.particleid, deepid)]
    shp_particules_deep.to_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_particules_deep.shp') # time in years !

    """
    if not os.path.exists(simulations_folder+'id_layers_random.data'):
        id_layers_random = [random.sample(shalid, 500),
                            random.sample(deepid, 500)]
        with open(simulations_folder+'id_layers_random.data', 'wb') as f:
            pickle.dump(id_layers_random, f)
    else:
        with open(simulations_folder+'id_layers_random.data', 'rb') as f:
            id_layers_random = pickle.load(f)
    
    shp_starting['time_year'] = shp_starting['time']
    shp_ending['time_year'] = shp_ending['time']
    shp_particules['time_year'] = shp_particules['time']
    shp_pathlines['time_year'] = shp_pathlines['time']
    
    particleid = shp_particules['particleid'].unique()
    
    for pid in particleid[:] :
        mask = shp_particules.loc[shp_particules['particleid']==pid, shp_particules.columns]
        print(pid, len(particleid), len(mask))
        shp_particules.loc[shp_particules['particleid']==pid, 'd'] = ((mask.x.diff())**2 +
                                                                      (mask.y.diff())**2 +
                                                                      (mask.z.diff())**2)**(1/2)
        shp_particules.loc[shp_particules['particleid']==pid, 'dt'] = mask.time_year.diff()
        # mask['d'] = ((mask.x.diff())**2 + (mask.y.diff())**2 + (mask.z.diff())**2)**(1/2)
        # pd.concat([shp_particules, mask])
    
    shp_particules['V'] = shp_particules['d'] / shp_particules['dt']
    
    shp_particules_shal = shp_particules[np.isin(shp_particules.particleid, id_layers_random[0])]
    shp_particules_deep = shp_particules[np.isin(shp_particules.particleid, id_layers_random[1])]
    """

#%% DECREASE NUMBER PATHLINES

list_path = sorted(glob.glob(simulations_folder+typ+'*'), key=os.path.getmtime, reverse=True)
list_selects = list_model_name[:]

for model_name in list_selects[:]:

    shp_1000_particules = gpd.read_file(simulations_folder+
                        model_name+'/'+'_pathlines/'+
                        'particules_1000.shp')
    
    shp_100_particules = shp_1000_particules[np.isin(shp_1000_particules.particleid, np.random.choice(shp_1000_particules.particleid, 10))]
    shp_100_particules.to_file(simulations_folder+
                        model_name+'/'+'_pathlines/'+
                        'particules_10.shp')
    
    shp_particules_shal = gpd.read_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_particules_shal.shp') # time in years !
    shp_x_particules_shal = shp_particules_shal[np.isin(shp_particules_shal.particleid, np.random.choice(shp_particules_shal.particleid, 50))]
    shp_x_particules_shal.to_file(simulations_folder+
                        model_name+'/'+'_pathlines/'+
                        'shp_x_particules_shal.shp')
    shp_particules_deep = gpd.read_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_particules_deep.shp') # time in years !
    shp_x_particules_deep = shp_particules_deep[np.isin(shp_particules_deep.particleid, np.random.choice(shp_particules_deep.particleid, 25))]
    shp_x_particules_deep.to_file(simulations_folder+
                            model_name+'/'+'_pathlines/'+
                            'shp_x_particules_deep.shp')

#%% NOTES 


