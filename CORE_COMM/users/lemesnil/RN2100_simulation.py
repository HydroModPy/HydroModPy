# -*- coding: utf-8 -*-
"""
Created on Fri May 20 10:55:31 2022

@author: Martin
"""

#%% LIBRARIES

# General
import os
import sys
from os.path import dirname, abspath
DIR = dirname(dirname(dirname(abspath(__file__))))
sys.path.append(DIR)
sys.path.append(os.path.join(DIR, 'users', 'lemesnil'))

# Gis
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

# Warnings
import warnings
warnings.filterwarnings("ignore", message=".*An exception was ignored while fetching the attribute.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*`np.object` is a deprecated alias for the builtin `object`.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated. Use tobytes().*", category=DeprecationWarning)
warnings.filterwarnings("ignore")
# warnings.warn("You won't see this warning")
                 
# HydroModPy + personal functions
from watershed import watershed_root, watershed_display
from wtd_spat_indic import wtd_spat_indic

# %% PATHS + watershed options

watershed_name = 'Saint-Germain-sur-Ay'
# Caen-la-Mer Baie-du-Cotentin Barneville-Carteret Agon-Coutainville Saint-Germain-sur-Ay
dem_name = "BDALTI_norm-manch_75m.tif"

if DIR[0] == 'd': #server
    shp_file = r'D:\mlemesnil\Data\BV_RN2100\SGA\SGA_2_sea.shp'
    # Path to the git repositoty home page
    git_path = r"D:\mlemesnil\HydroModPy\HydroModPy\CORE_COMM/"
    # Path to the data folder
    data_path = r"D:\mlemesnil\Data\HydroModPy/"
    # Path where the results will be stored
    out_path = r'D:\mlemesnil\HydroModPy\Output/'
    modflow_path = r'D:\mlemesnil\HydroModPy\Modflow' # add bin/ folder with necessary .exe
    ESPERE_recharge_path = r'D:\mlemesnil\Data\estim_ET\SGA\aut_2022\rech_SGA_aut2022.csv'
    shape_calib_zones_path = r'D:\mlemesnil\Data\HydroModPy\calib_zones\SGA\shape_calib_zones_SGA.shp'
elif DIR[0] == 'c': #local
    shp_file = r'C:/Users/Martin Le Mesnil/Travail/SIG/BV_RN2100/Baie-du-cotentin/Carentan_2_sea.shp'
    # C:\Users\Martin Le Mesnil\Travail\SIG\BV_RN2100\Agon-Coutainville\Agon_2_sea_extended.shp
    # 'C:\Users\Martin Le Mesnil\Travail\SIG\BV_RN2100\Barneville-Carteret\Barneville_2_sea_extended.shp'
    # 'C:/Users/Martin Le Mesnil/Travail/SIG/BV_RN2100/Caen/Caen_2_sea.shp'
    # 'C:/Users/Martin Le Mesnil/Travail/SIG/BV_RN2100/Baie-du-Cotentin/watershed_clip_carentan.shp'
    # 'C:/Users/Martin Le Mesnil/Travail/SIG/BV_RN2100/Saint-Germain-sur-Ay/SGA_2_sea.shp'
    git_path = r"C:/Users/Martin Le Mesnil/Travail/HydroModPy/HydroModPy/CORE_COMM/"
    data_path = r"C:/Users/Martin Le Mesnil/Travail/data/data_test_ronan/"
    out_path = r'C:/Users/Martin Le Mesnil/Travail/HydroModPy/output2/'
    modflow_path = r'C:/Users/Martin Le Mesnil/Travail/HydroModPy/Modflow' # add bin/ folder with necessary .exe
    ESPERE_recharge_path = r'C:\Users\Martin Le Mesnil\Travail\data\estim_ET\LC\rech_LC_aut2022.csv'
    #r'C:\Users\Martin Le Mesnil\Travail\data\estim_ET\SGA\aut_2022\rech_SGA_aut2022.csv'
    # C:\Users\Martin Le Mesnil\Travail\data\estim_ET\rech_CLM_aut2022.csv
    #r'C:\Users\Martin Le Mesnil\Travail\data\estim_ET\rech_CLM_2022.csv'
    shape_calib_zones_path = r'C:\Users\Martin Le Mesnil\Travail\SIG\zones_calib\shape_calib_zones_BDC_3.shp'
    # 'C:\Users\Martin Le Mesnil\Travail\SIG\zones_calib\shape_calib_zones_LC.shp'
    # r'C:\Users\Martin Le Mesnil\Travail\SIG\zones_calib\shape_calib_zones_SGA.shp'
    # C:\Users\Martin Le Mesnil\Travail\SIG\zones_calib\shape_calib_zones_CLM.shp
    # C:\Users\Martin Le Mesnil\Travail\SIG\zones_calib\shape_calib_zones_CMB.shp
    # C:\Users\Martin Le Mesnil\Travail\SIG\zones_calib\shape_calib_zones_BDC_3.shp
    
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
surfex_path =  data_path # add surfex models in .h5 format (France scale, else, specify None)
geology_path = data_path + 'geology/' # add geologic layers
oceanic_path = data_path + 'OCEAN/' # add specific sea level files
hydrology_path = data_path + 'hydro/' # add hydrographic shapefiles
# hydrometry_path = data_path + 'hydrometry/' # add hydrometry data for automatic download
# intermittency_path = data_path + 'intermittency/' # add intermittency data for automatic download
piezometry_path = True # add piezometry data for automatic download
subbasin_path = True # generate subbasins from stations or manual points
drias_path = data_path + "CLIMAT/Normandie/"
library_path = git_path + 'watershed/watershed_library.csv' # each row is a study site with outlet coordinates
dems_path = data_path # reginal DEM or conceptual DEM
dem_path = dems_path + dem_name
cell_size = None # specify new resolution from a given DEM or None

site_dict = {'Saint-Germain-sur-Ay' : 'SGA',
             'Agon-Coutainville' : 'AGC',
             'Barneville-Carteret' : 'BNV',
             'Baie-du-Cotentin' : 'BDC',
             'Caen-la-Mer' : 'CLM'}

#%% Watershed generation

BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              modflow_path=modflow_path,
                              library_path=library_path,
                              load=False,
                              from_shp=shp_file,
                              from_dem=False,
                              cell_size=cell_size)


# BV.add_drias(drias_path)
# BV.add_surfex(surfex_path) 
BV.add_hydrodynamic()
BV.add_oceanic(oceanic_path)

# BV.add_geology(geology_path)

watershed_display.watershed_dem(BV)
watershed_display.watershed_local(dem_path, BV)


#%% Load BV object
    
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              modflow_path=modflow_path,
                              library_path=library_path,
                              load=True,
                              from_shp=shp_file,
                              from_dem=None,
                              cell_size=cell_size)

BV.load_object()
BV.add_hydrodynamic()
BV.add_oceanic(oceanic_path)
# BV.add_piezometry()

watershed_display.watershed_dem(BV)
watershed_display.watershed_local(dem_path, BV)

#%% Model Parameters and options

hetero = 1
t = 29 # m

# Strcture of the model
lay_number = 1 # vertical discrtization
bottom = None # aquifer flat or not
thick_exp = 1 # exponential decay of K with nlay
cond_decay = 0 # exponential decay of K with depth

# Activation of modules
first_only = False # if True generate results only for the first time_step
box = False # if True generate a rectangular model
sink_fill = False # permit to fill sinks
modpath_sim = False # run modpath particle tracking if True
verbose = True # add print of MODFLOW in console

# Update properties
if hetero == 0:
    n = 0.005 # nondim
    K = 0.207 # m/j
    BV.hydrodynamic.update_hyd_cond(K)
    BV.hydrodynamic.update_porosity(n)
elif hetero == 1:
    print('heterogeneous model')
    K1 = 0.21
    K2 = 2.3
    n1 = 0.01
    n2 = 0.015
    shape = BV.hydrodynamic.update_calib_zones_from_shp(shape_calib_zones_path)
    BV.hydrodynamic.update_hyd_cond_from_calib_zones(num_zone = 1, hyd_cond_value = K1)
    BV.hydrodynamic.update_hyd_cond_from_calib_zones(num_zone = 2, hyd_cond_value = K2)
    BV.hydrodynamic.update_porosity_from_calib_zones(num_zone = 1, porosity_value = n1)
    BV.hydrodynamic.update_porosity_from_calib_zones(num_zone = 2, porosity_value = n2)

BV.hydrodynamic.update_thickness(t)
BV.hydrodynamic.update_nlay(lay_number)
BV.hydrodynamic.update_bottom(bottom)
BV.hydrodynamic.update_thick_exp(thick_exp)
BV.hydrodynamic.update_cond_decay(cond_decay)

#%% Launch simulations and save results
from datetime import datetime

# /!\ Activate to save results on external disk
disk_save = True

# /!\ Activate to save rasters of watertable depth threshold frequency
edit_raster = True

first_yr = 2061
last_yr = 2100

BV.add_forcing()
RMSL_85 = BV.oceanic.RMSL["RCP8.5"]
md_rmsl_85 = RMSL_85.iloc[:,0]
RMSL_26 = BV.oceanic.RMSL["RCP2.6"]
md_rmsl_26 = RMSL_26.iloc[:,0]
# md_rmsl_85_cut = ...

DRIAS_model_list = ['MPI-CCL'] #['MPI-R09', 'HAD-REG', 'CNR-ALA', 'NOR-R15', 'CNR-RAC', 'ECE-RAC', 'ECE-RCA', 'MPI-CCL']
sce_list = ['RCP8.5']

sim_name_list = []
for DRIAS_model in DRIAS_model_list:
    for scenario in sce_list:
    
        gcm = DRIAS_model[:3] #'MPI'
        rcm = DRIAS_model[-3:] #'CCL'
        sce = scenario #'RCP8.5'
        BV.forcing.update_recharge_drias(gcm_mod = gcm, rcm_mod = rcm, sce_mod = sce,
                                          first_year = first_yr, last_year = last_yr,
                                          sim_state = 'transient')
        # BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce = 'historic',
        #                                       first_year = 1965, last_year = 2014, 
        #                                       time_step = 'D', sim_state = 'transient')
        if scenario == 'RCP2.6':
            BV.oceanic.update_MSL(md_rmsl_26)
        elif scenario == 'RCP8.5':
            BV.oceanic.update_MSL(md_rmsl_85)
        
        now = datetime.now()
        now_str = now.strftime("%d%m%Y%H%M%S")
        sim_name = str(first_yr)+str(last_yr) + '_' + gcm+rcm+ sce.replace('.', '') + '_' + now_str
        # # sim_name = str(first_yr)+str(last_yr) + '_REA_' + now_str
        print(sim_name)
        sim_name_list.append(sim_name)
    
        if disk_save:
            simulation_results_new_path_dir = os.path.join(r'E:\PostDoc\Modélisation', site_dict[watershed_name], r'Heterogeneous\simulation_results')
            BV.simulations_folder = simulation_results_new_path_dir
            
        success, flow_model = BV.run_modflow(ident=sim_name,
                        modpath_sim=modpath_sim,
                        first_only=first_only,
                        sink_fill=sink_fill,
                        box=box,
                        lay_number=lay_number,
                        bottom=bottom,
                        thick_exp=thick_exp,
                        cond_decay=cond_decay,
                        verbose=verbose)
        
        # Save recharge time series
        rech = BV.forcing.recharge
        rech_path = os.path.join(BV.simulations_folder, sim_name, 'recharge.csv')
        if not os.path.exists(dirname(rech_path)):
            os.makedirs(dirname(rech_path))
        rech.to_csv(rech_path, sep = ';', index_label = 'Date',)
        
        if success == True:
            BV.matrix_modflow(success,
                              flow_model,
                              first_only = True,
                              watertable_elevation = True,
                              watertable_depth = True, 
                              seepage_areas = True,
                              outflow_drain = False,
                              groundwater_flux = False,
                              specific_discharge = False,
                              accumulation_flux = False,
                              perenn_intermit_shp = False,
                              groundwater_storage = False,
                              residence_times = False,
                              verbose = True,
                              export_tif = True)
            
            # Extract results
            BV.results_modflow(ident = sim_name,
                                recharge = BV.forcing.recharge,
                                runoff = BV.forcing.recharge, # warning: runoff is set at recharge value to debug
                                actual_date = True,
                                time_step = 'D')
                        
            
#%% raster

disk_save = True
if disk_save:
    simulation_results_new_path_dir = os.path.join(r'E:\PostDoc\Modélisation', site_dict[watershed_name], r'Heterogeneous\simulation_results')
    BV.simulations_folder = simulation_results_new_path_dir

sim_name_list = ['20202100_MPICCLRCP85_26012023235924']
# Edit raster for GIS
for sim_name in sim_name_list:
    rast_path = os.path.join(dirname(BV.simulations_folder), 'rasters_wtd', sim_name)  
    os.makedirs(rast_path, exist_ok = True)
    wtd_spat_indic(BV, sim_name, 2020, 2024, [2.5, 1, .5, .3, .03, -1], figures = 'save', save_rast = rast_path)
    # wtd_spat_indic(BV, sim_name, 2027, 2033, [2.5, 1, .5, .3, .03, -1], figures = 'save', save_rast = rast_path)
    # wtd_spat_indic(BV, sim_name, 2047, 2053, [2.5, 1, .5, .3, .03, -1], figures = 'save', save_rast = rast_path)
    # wtd_spat_indic(BV, sim_name, 2094, 2099, [2.5, 1, .5, .3, .03, -1], figures = 'save', save_rast = rast_path)


