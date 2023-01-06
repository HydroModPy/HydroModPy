# -*- coding: utf-8 -*-
"""

"""

#%% LIBRAIRIES

import os
import sys
import numpy as np
import matplotlib.pyplot as plt
import glob
from os.path import dirname, abspath
import pandas as pd
import matplotlib as mpl
from mpl_toolkits.axes_grid1 import make_axes_locatable
from matplotlib.colors import Normalize
root_dir = dirname(dirname(dirname(abspath(__file__))))
sys.path.append(root_dir)

from watershed import watershed_root, watershed_display
from calibration import calib_root, calib_analysis, calib_basis

#%% USERS

# user_path = "Martin"
user_path = "Ronan"

if user_path=="Alexandre":
    data_path= "C:/Users/alexa/Dropbox/HydroModPy/_data/"
    out_path = 'C:/Users/alexa/Dropbox/HydroModPy/'
    
elif user_path=="Jean-Raynald":
    data_path= "D:/codes-data/HydroModPy_Data/"
    out_path = "D:/results/HydroModPy/"
    
elif user_path=="Ronan":
    data_path= "D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/HYDRODATAPY/HydroDataPy/CALIB/"
    out_path = "D:/Users/abherve/EXAMPLES/"
  
elif user_path=="Martin":
    data_path= "C:/Users/Martin Le Mesnil/Travail/data/CALIB/"
    out_path = "C:/Users/Martin Le Mesnil/Travail/HydroModPy/output2/"

else:
    print("Define a well-validated name of user")

#%% ASSIGNED PATHS

watershed_name = 'Agon-Coutainville'
watershed_name = 'Paimpont'

library_path = data_path + 'watershed_library.csv' # each row is a study site with outlet coordinates

if watershed_name == 'Agon-Coutainville':
    dem_name = "BDALTI_norm-manch_75m.tif"
    from_shp = os.path.join(data_path,'bounds','bounds_agon.shp')
    from_shp = None
    types_obs = ['streams']
    fields_obs = ['fid']
if watershed_name == 'Paimpont':
    dem_name = 'BDALTI_bzh_75m.tif'
    from_shp = None
    types_obs = ['streams', 'sections']
    fields_obs = ['fid', 'Persistanc']

from_dem = False
cell_size = None
    
climate_path =  os.path.join(data_path,'climate')
dem_path = os.path.join(data_path,"dem",dem_name)
geology_path = os.path.join(data_path,'geology')
hydrology_path = os.path.join(data_path,'hydrology')
hydrometry_path = data_path + 'hydrometry/' # add hydrometry data for automatic download
intermittency_path = data_path + 'intermittency/' # add intermittency data for automatic download
modflow_path = os.path.join(data_path,'modflow')
oceanic_path = os.path.join(data_path,'oceanic')
piezometry_path = True # add piezometry data for automatic download
subbasin_path = True # generate subbasins from stations or manual points

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots

#%% LOAD WATERSHED

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
                              cell_size=cell_size)

#%% ADD DATA IN THE WATERSHED

if not os.path.exists(os.path.join(stable_folder, 'climatic', 'REA.h5')):
    BV.add_surfex(climate_path) 
BV.add_geology(geology_path)
# if not os.path.exists(os.path.join(stable_folder, 'hydrology', 'streams.shp')):
BV.add_hydrology(hydrology_path, types_obs=types_obs, fields_obs=fields_obs)
BV.add_oceanic(oceanic_path)
BV.add_hydrometry(hydrometry_path)
BV.add_intermittency(intermittency_path)
if piezometry_path == True:
    BV.add_piezometry()
    # shapefiles folder
        # BSS.shp : wells available at the department scale
        # point_eau_piezo.shp : continue piezometers at the France scale
        # piezos.shp : continue piezometers at the catchment scale
        # piezos_discrete.shp : discrete piezometers at the catchment scale
if subbasin_path == True:
    BV.add_subbasin()
    
watershed_display.watershed_dem(BV)
watershed_display.watershed_local(dem_path, BV)

#%% MODEL PARAMETERS

# By dDefault and change forward

BV.add_hydrodynamic()
BV.hydrodynamic.update_thickness(30) # m
BV.hydrodynamic.update_porosity(0.1) # -
BV.hydrodynamic.update_hyd_cond(0.864) # m/j

BV.add_forcing()
BV.forcing.update_recharge_surfex(clim_mod='REA', clim_sce='historic', 
                                  first_year=2017, last_year=2018,
                                  time_step='D', sim_state='transient')
plt.plot(BV.forcing.recharge)

#%% CALIB CHOICE

# .csv in the results_calibration folder

#### Possibilities
params_files = [
                "calib_dicot_hom_1v_k1",      # dichotomy on streams, homogeneous, for k1
                "calib_explo_hom_1v_k1",      # exploration on streams or piezometers or hydrometry, homogeneous, for k1
                "calib_explo_hom_2v_k1-n1",   # exploration on streams or piezometers or hydrometry, homogeneous, for k1 and n1
                "calib_explo_het_1v_k1-k2",   # exploration on piezometers, heterogeneous, for k1 and k2
                "calib_explo_hom_1v_n1"
                ]

#%% CALIB : STREAMS - 1 VARIABLE - HOMOGENEOUS - DICHOTOMY - STEADY

if watershed_name == 'Agon-Coutainville':
    
    params_file = "calib_dicot_hom_1v_k1_stead" # dichotomy on streams, homogeneous, for k1
    sim_state = 'steady'
    data_calib = ['streams']
    
    # Pre-processing
    BV.forcing.update_recharge_surfex(clim_mod='REA', clim_sce='historic', 
                                      first_year=2017, last_year=2019,
                                      time_step='D', sim_state=sim_state)
    calib = calib_root.Calibration(params_file, BV, observations = data_calib)
    
    # Processing
    # calib.dichotomy(gap=1)
    
    # Post-processing
    label_calib = data_calib[0] + '_calibration'
    list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, label_calib, '*.calib')), key=os.path.getmtime)
    name_file = list_path[-1].split('\\')[-1] # the last calibration
    calib_file = os.path.join(BV.calibration_folder, params_file, label_calib, name_file)
    analy = calib_analysis.CalibAnalysis(calib_file)
    analy.display_objective_function(save=None)

#%% CALIB : STREAMS - 1 VARIABLE - HOMOGENEOUS - EXPLORATION - STEADY

if watershed_name == 'Agon-Coutainville':

    params_file = "calib_explo_hom_1v_k1_stead" # exploration on streams or piezometers or hydrometry, homogeneous, for k1
    sim_state = 'steady'
    data_calib = ['streams']
    
    # Pre-processing
    BV.forcing.update_recharge_surfex(clim_mod='REA', clim_sce='historic', 
                                      first_year=2017, last_year=2019,
                                      time_step='D', sim_state=sim_state)
    calib = calib_root.Calibration(params_file, BV, observations = data_calib)
    
    # Processing
    # calib.exploration(resolution=10)
    
    # Pre-processing
    label_calib = data_calib[0] + '_calibration'
    list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, label_calib, '*.calib')),
    key=os.path.getmtime, reverse=True)
    name_file = list_path[0].split('\\')[-1]
    calib_file = os.path.join(BV.calibration_folder, params_file, label_calib, name_file)
    analy = calib_analysis.CalibAnalysis(calib_file)
    analy.display_objective_function(save=None, vmax=None)

#%% CALIB : PIEZOMETRY - 1 VARIABLE - HOMOGENEOUS - EXPLORATION - STEADY

if watershed_name == 'Agon-Coutainville':

    params_file = "calib_explo_hom_1v_k1_stead" # exploration on streams or piezometers or hydrometry, homogeneous, for k1
    sim_state = 'steady'
    data_calib = ['piezometry']
    
    # Pre-processing
    BV.forcing.update_recharge_surfex(clim_mod='REA', clim_sce='historic', 
                                      first_year=2017, last_year=2019,
                                      time_step='D', sim_state=sim_state)
    calib = calib_root.Calibration(params_file, BV, observations = data_calib)
    
    # Processing
    # calib.exploration(resolution=10)
    
    # Pre-processing
    label_calib = data_calib[0] + '_calibration'
    list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, label_calib, '*.calib')),
    key=os.path.getmtime, reverse=True)
    name_file = list_path[0].split('\\')[-1]
    calib_file = os.path.join(BV.calibration_folder, params_file, label_calib, name_file)
    analy = calib_analysis.CalibAnalysis(calib_file)
    analy.display_objective_function(save=None, vmax=None)

#%% CALIB : PIEZOMETRY - 1 VARIABLE - HOMOGENEOUS - EXPLORATION - TRANSIENT

if watershed_name == 'Agon-Coutainville':
    
    params_file = "calib_explo_hom_1v_k1_trans" # exploration on streams or piezometers or hydrometry, homogeneous, for k1
    sim_state = 'transient'
    data_calib = ['piezometry']
    
    # Pre-processing
    BV.forcing.update_recharge_surfex(clim_mod='REA', clim_sce='historic', 
                                      first_year=2017, last_year=2019,
                                      time_step='D', sim_state=sim_state)
    calib = calib_root.Calibration(params_file, BV, observations = data_calib)
    
    # Processing
    # calib.exploration(resolution=2)
    
    # Pre-processing
    label_calib = data_calib[0] + '_calibration'
    list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, label_calib, '*.calib')),
    key=os.path.getmtime, reverse=True)
    name_file = list_path[0].split('\\')[-1]
    calib_file = os.path.join(BV.calibration_folder, params_file, label_calib, name_file)
    analy = calib_analysis.CalibAnalysis(calib_file)
    analy.display_objective_function(save=None, vmax=None)

#%% CALIB : PIEZOMETRY - 2 VARIABLES - HOMOGENEOUS - EXPLORATION - STEADY

if watershed_name == 'Agon-Coutainville':

    params_file = "calib_explo_hom_2v_k1-n1_stead" # exploration on streams or piezometers or hydrometry, homogeneous, for k1 and n1
    sim_state = 'steady'
    data_calib = ['piezometry']

    # Pre-processing
    BV.forcing.update_recharge_surfex(clim_mod='REA', clim_sce='historic', 
                                      first_year=2017, last_year=2019,
                                      time_step='D', sim_state=sim_state)
    calib = calib_root.Calibration(params_file, BV, observations = data_calib)
    
    # Processing
    # calib.exploration(resolution=10)
    
    # Pre-processing
    label_calib = data_calib[0] + '_calibration'
    list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, label_calib, '*.calib')),
    key=os.path.getmtime, reverse=True)
    name_file = list_path[0].split('\\')[-1]
    calib_file = os.path.join(BV.calibration_folder, params_file, label_calib, name_file)
    analy = calib_analysis.CalibAnalysis(calib_file)
    analy.display_objective_function(save=None, vmax=None)

#%% CALIB : HYDROMETRY - 2 VARIABLES - HOMOGENEOUS - EXPLORATION - TRANSIENT

# Observed streamflow data :
# Named for example : 
# Hydrometric_J0014010_Le Nançon à Lécousse [Pont aux Anes (actuel)]_338251-2381078_67_105_1982-2021.csv
#     ==> type_code_label_xcoord-ycoord_area_?_open-close.csv
#     .csv with two columns ==> date;discharge
#     |;Q              |
#     |1982-02-01;1.275|
#     |1982-02-02;1.258|
#     |1982-02-03;1.223|

if watershed_name == 'Paimpont':
    
    params_file = "calib_explo_hom_2v_k1-n1_trans" # exploration on streams or piezometers or hydrometry, homogeneous, for k1
    sim_state = 'transient'
    data_calib = ['hydrometry']

    # Pre-processing
    BV.forcing.update_recharge_surfex(clim_mod='REA', clim_sce='historic', 
                                      first_year=1990, last_year=1990,
                                      time_step='M', sim_state=sim_state)
    BV.forcing.update_runoff_surfex(clim_mod='REA', clim_sce='historic', 
                                      first_year=1990, last_year=1990,
                                      time_step='M', sim_state=sim_state)
    calib = calib_root.Calibration(params_file, BV, observations = data_calib)
    
    # Processing
    # calib.exploration(resolution=2)
    
    # Post-processing
    label_calib = data_calib[0] + '_calibration'
    list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, label_calib, '*.calib')),
                       key=os.path.getmtime, reverse=True)
    name_file = list_path[0].split('\\')[-1]
    calib_file = os.path.join(BV.calibration_folder, params_file, label_calib, name_file)
    analy = calib_analysis.CalibAnalysis(calib_file)
    
    from calibration import calib_root, calib_analysis

    # analy.display_objective_function(save=None, vmax=None)

    min_nse = 50
    mean_meansat = 3 # sup
    min_maxsat = 8
    max_maxsat = 25

    sim_res = analy.sim_results
    test = analy
    
    sat_typ = 'seepage_areas'
    typ_calib = label_calib
    typ_name = typ_calib.split('_')[0]
    
    obs = test.data_obs
    sim = test.data_sim
    ind = test.data_ind
    obj = test.calib['objective_function']
    xyz = test.params_xyz
    
    synt = test.params_synt
        
    p1 = []
    for p in synt:
        p1.append(p.split(';')[0])
    p2 = []
    for p in synt:
        p2.append(p.split(';')[1])
    rout = []
    for r in sim[typ_name]:
        rout.append((r*1000*30).mean()[0])
    rsat = []
    
    try:
        for t in range(len(synt)):     
            sat = test.sim_results[synt[t]][sat_typ]
            sat = pd.to_numeric(sat, errors='coerce').isnull()
            rsat.append(sat.mean())
    except:
        pass
    
    nse_good = []
    sat_good = []
    
    numb = 0
    for i in range(len(obs[typ_name])):
        o = obs[typ_name][i] * 1000 * 30 # m/j to mm/month
        s = sim[typ_name][i] * 1000 * 30 # m/j to mm/month
        nd = ind[typ_name][i]
        try:
            sat = test.sim_results[synt[i]][sat_typ]
            sat = pd.to_numeric(sat)
        except:
            pass
        k = '{:.1e}'.format(float(synt[i].split(';')[0])/24/3600)
        sy = float(synt[i].split(';')[1]) * 100
        title = 'Discharge [mm/month]'
        nselog = round(((nd[0]))*100,1)
        label = 'K = '+k+' m/s'+' ; '+'ɸ = '+str(round(sy,1))+'% ; '+\
                '$NSE_{log}$ = '+str(nselog)+'%'
        nse_good.append(str(k)+'_'+str(sy)+'_'+str(nselog))
        if nselog > min_nse:
            # if all(i <= 50 for i in sat):
            try:
                if sat.max() < max_maxsat:
                    if sat.max() > min_maxsat:
                        numb += 1
            except:
                pass
                # c = []
                # for h in range(len(ind[typ_name])):
                #     d = ind[typ_name][h][0]
                #     c.append(d)
        
        c = np.linspace(0,1,len(obs[typ_name]))

        # cmap = mpl.cm.get_cmap('viridis_r')
        # color_gradients = cmap(c)
        # vmin = min(c)
        # vmax = max(c)
        # norm = mpl.colors.Normalize(vmin=vmin, vmax=vmax)

    fig, ax = plt.subplots(1,1, figsize=(3.8,3.5))
    ax.set_aspect('auto')
    ax.axes.tick_params(which='both', direction='out', zorder=10)
    X,Y = np.meshgrid(test.params_values[0], test.params_values[1])
    Z = test.obj_function.copy()
    # Z[Z<0] = 0
    # from numpy import inf
    # Z[Z == inf] = 0
    bounds = np.arange(0,1.1,0.1)
    norm = mpl.colors.Normalize(vmin=-1, vmax=1.0)
    # pc = ax.pcolormesh(X,Y,Z, cmap='jet', shading='gouraud', vmin=0, vmax=1) #figadd.cmap_white_jet()
    pc = ax.contourf(X/3600/24, Y*100, Z, 
                     # levels=np.arange(0,1.1,0.1),
                     alpha=0.6, 
                     # ec='none'
                     )    

    ax.set_xscale('log')
    ax.set_ylabel('Φ [%]')
    ax.set_xlabel('K [m/s]')
    # ax.set_yticks(np.arange(0,11,2))
    # ax.set_yticklabels(np.arange(0,11,2))
    # ax.tick_params(direction='in')
    ax.tick_params(top=True,
               bottom=True,
               left=True,
               right=False,
               labelleft=True,
               labelbottom=True)
    
    # divider = make_axes_locatable(ax)
    # cax = divider.append_axes('right', size='5%', pad=0.05)

    position=fig.add_axes([1.05,0.33,0.03,0.5])  ##
    cb = fig.colorbar(pc, cax=position, orientation='vertical')
    # cb.set_ticks(np.arange(0,1.1,0.2))
    # cb.set_ticklabels(np.arange(0,101,20)) 
    cb.set_label('$NSE_{log}$', rotation=270, labelpad=40)
    cb.ax.tick_params(top=True,
                bottom=True,
                left=False,
                right=False,
                labelleft=False,
                labelbottom=True)
    
    plt.tight_layout()

    X,Y = np.meshgrid(test.params_values[0], test.params_values[1])
    Z = np.empty((3,3,))
    Z[:] = np.nan
    p1 = test.params_values[0]
    p2= test.params_values[1]
    sim_sat = np.zeros((len(p1),len(p2)))
    
    compt=0
    for i in range(len(p1)):
        for j in range(len(p2)):
            temp = [p1[i],p2[j]]
            string = str(p1[i])+';'+str(+p2[j])
            try:
                sim_sat[j][i] = pd.to_numeric(sim_res[string][sat_typ]).min()
            except:
                sim_sat[j][i] = np.nan
                pass
            compt += 1
    Zmin = sim_sat
    
    compt=0
    for i in range(len(p1)):
        for j in range(len(p2)):
            temp = [p1[i],p2[j]]
            string = str(p1[i])+';'+str(+p2[j])
            try:
                sim_sat[j][i] = pd.to_numeric(sim_res[string][sat_typ]).mean()
            except:
                sim_sat[j][i] = np.nan
                pass 
            compt += 1
    Zmean = sim_sat
    
    compt=0
    for i in range(len(p1)):
        for j in range(len(p2)):
            temp = [p1[i],p2[j]]
            string = str(p1[i])+';'+str(+p2[j])
            try:
                sim_sat[j][i] = pd.to_numeric(sim_res[string][sat_typ]).median()
            except:
                sim_sat[j][i] = np.nan
                pass 
            compt += 1
    Zmed = sim_sat
    
    compt=0
    for i in range(len(p1)):
        for j in range(len(p2)):
            temp = [p1[i],p2[j]]
            string = str(p1[i])+';'+str(+p2[j])
            try:
                sim_sat[j][i] = pd.to_numeric(sim_res[string][sat_typ]).max()
            except:
                sim_sat[j][i] = np.nan
                pass
            compt += 1
    Zmax = sim_sat
    
    Z = Zmax.copy()
    Z[Zmax<min_maxsat] = np.nan
    Z[Zmax>max_maxsat] = np.nan
    Z[Zmean<mean_meansat] = np.nan
    
    Xclip = np.ma.masked_array(X, mask=np.isnan(Z)) /3600/24 # y = y.compress() # y without nan where x has nan's
    Yclip = np.ma.masked_array(Y, mask=np.isnan(Z)) *100
    
    ax.scatter(Xclip, Yclip, c=Z, s=20, marker='s', edgecolor='k',
                cmap=mpl.colors.ListedColormap('white'))
    
    ax.set_title(watershed_name, pad=10)
    plt.tight_layout()

#%% CALIB : PIEZOMETRY - 1 VARIABLE - HETEROGENEOUS - EXPLORATION - STEADY

if watershed_name == 'Agon-Coutainville':
    
    zones = np.ones(np.shape(BV.geology.geology_array))
    
    zones[BV.geology.geology_array>40] = int(2) # Crystalline rocks
    zones[BV.geology.geology_array<40] = int(1) # Sands
    zones[BV.geology.geology_array == 175] = int(1)
    zones[BV.geology.geology_array == 178] = int(1)
    zones[BV.geology.geology_array == 4] = int(2)
    zones[BV.geology.geology_array == 29] = int(2)
    zones[BV.geology.geology_array == 35] = int(2)
    
    plt.imshow(zones)

    BV.hydrodynamic.update_calib_zones(zones)

    params_file = "calib_explo_het_1v_k1-k2_stead" # exploration on piezometers, heterogeneous, for k1 and k2
    sim_state = 'steady'
    data_calib = ['piezometry']
    
    # Pre-processing
    BV.forcing.update_recharge_surfex(clim_mod='REA', clim_sce='historic', 
                                      first_year=2017, last_year=2019,
                                      time_step='D', sim_state=sim_state)
    calib = calib_root.Calibration(params_file, BV, observations = data_calib)
    
    # Processing
    # calib.exploration(resolution=10)
    
    # Pre-processing
    label_calib = data_calib[0] + '_calibration'
    list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, label_calib, '*.calib')),
    key=os.path.getmtime, reverse=True)
    name_file = list_path[0].split('\\')[-1]
    calib_file = os.path.join(BV.calibration_folder, params_file, label_calib, name_file)
    analy = calib_analysis.CalibAnalysis(calib_file)
    analy.display_objective_function(save=None, vmax=None)

#%% CALIB : INTERMITTENCY - 1 VARIABLE - HOMOGENEOUS - EXPLORATION - TRANSIENT

if watershed_name == 'Paimpont':
    
    params_file = "calib_explo_hom_1v_n1_trans" # exploration on streams or piezometers or hydrometry, homogeneous, for k1
    sim_state = 'transient'
    data_calib = ['intermittency']
    
    # Pre-processing
    BV.forcing.update_recharge_surfex(clim_mod='REA', clim_sce='historic', 
                                      first_year=2018, last_year=2019,
                                      time_step='M', sim_state=sim_state)
    calib = calib_root.Calibration(params_file, BV, observations = data_calib)
    
    # Processing
    calib.exploration(resolution=1)
    
    # Pre-processing
    label_calib = data_calib[0] + '_calibration'
    list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, label_calib, '*.calib')),
    key=os.path.getmtime, reverse=True)
    name_file = list_path[0].split('\\')[-1]
    calib_file = os.path.join(BV.calibration_folder, params_file, label_calib, name_file)
    analy = calib_analysis.CalibAnalysis(calib_file)
    analy.display_objective_function(save=None, vmax=None)

#%% CALIB : SIMPLEX

# Coming soon !

#%% DISPLAYS EXEMPLE

# To correct

typ_calib = ['streams_calibration','piezometry_calibration']
vmax = [100,10]
vmin =[0.01,2]
plt.rcParams.update({
  "text.usetex": True,
  "font.family": "Helvetica"
})

fig, ax = plt.subplots(1,2,figsize=(12,5))
for i in range(len(typ_calib)):
    list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, typ_calib[i], '*.calib')),
                       key=os.path.getmtime, reverse=True)
    name_file = list_path[0].split('\\')[-1]
    calib_file = os.path.join(BV.calibration_folder, params_file, typ_calib[i], name_file)
    test = calib_analysis.CalibAnalysis(calib_file)
    print(typ_calib[i],test.p)
    X,Y = np.meshgrid(test.params_values[0], test.params_values[1])
    Z=test.obj_function
    #plt.pcolor(X,Y,Z,cmap='jet')#figadd.cmap_white_jet()
    #plt.pcolor(X,Y,Z,cmap='jet')#figadd.cmap_white_jet()
    ax[i].plot(test.p[0],test.p[1],'ow',markersize=10)
    levels = 1000
    #plt.contourf(X, Y, Z,levels,cmap='jet', shading='auto',vmax=vmax, vmin=vmin)
            
    for j in range(0,len(test.names)):
        
        if test.names[i][0] == 'k':
            if j == 0:
                ax[i].set_xscale("log")
                ax[i].set_xlabel(r'$K$'+str(test.names[j][1])+' $[m.j^{-1}]$')
            if j == 1:
                ax[i].set_yscale("log")
                ax[i].set_ylabel(r'$K$'+str(test.names[j][1])+' $[m.j^{-1}]$')
        if test.names[j][0] == 'n':
            if j == 0:
                if test.names[j][1]=='0':
                    ax[i].set_xlabel(r'$n$ $[-]$')
                else:
                    ax[i].set_xlabel(r'$n$'+str(test.names[j][1])+' $[-]$')
            if j== 1:
                if test.names[j][1] == '0':
                    ax[i].set_ylabel(r'$n$ $[-]$')
                else:
                    ax[i].set_ylabel(r'$n$'+str(test.names[j][1])+' $[-]$')
    
    ax[i].plot([0.01,100],[0.01,100],'k--',lw=2)
    ax[i].set_xlim((0.01,100))
    ax[i].set_ylim((0.01,100))      
    if test.observations == ['piezometry']:
        cmap=ax[i].pcolor(X, Y, Z,cmap='jet', shading='auto',vmax=vmax[i], vmin=vmin[i])
        plt.colorbar(cmap,label=r'$RMSE$',ax=ax[i])
    if test.observations == ['streams']:
        cmap=ax[i].pcolor(X, Y, Z,cmap='jet', shading='auto',vmax=vmax[i], vmin=vmin[i])
        plt.colorbar(cmap,label=r'$log(D_{SO}/D_{OS})^{2}$',ax=ax[i])

plt.tight_layout()
save='.../Figure/2param_K.png'
#plt.savefig(save,dpi=300, bbox_inches = "tight")

#%% NOTES

#### MULTIPLE CALIBRATION ! ####
# calib = calib_root.Calibration(params_file, BV, observations = ['streams','piezometry'])

#### DISPLAYS BULK ####

# pc = ax.pcolormesh(X/3600/24, Y*100, Z,
#                  cmap = mpl.colors.ListedColormap('Grey'),
#                  alpha=0.5, linewidths=1)
# pc = ax.contour(X/3600/24, Y*100, Z, levels=np.arange(0,100,5),
#                  cmap =  mpl.colors.ListedColormap('Grey'),
#                  alpha=0.75, linewidths=1)

# fig2, ax = plt.subplots(1,1, figsize=(3.8,3.5))
# pc = ax.contourf(X/3600/24, Y*100, Zmax, cmap='seismic',
#                   levels=np.arange(0,100,5), alpha=0.75) # mpl.colors.ListedColormap('Grey')
# ax.set_xscale('log')
# ax.set_ylabel('Φ [%]')
# ax.set_xlabel('K [m/s]')
# ax.tick_params(top=True,
#            bottom=True,
#            left=True,
#            right=False,
#            labelleft=True,
#            labelbottom=True)
# # ax.tick_params(direction='out', axis='both', which='both')
# # position=fig2.add_axes([1.05,0.2,0.02,0.7])  ## the parameters are the specified position you set 
# # fig2.colorbar(pc,cax=position)

# ax.axvline(df.perennial[0], color='k', lw=2)
# ax.axvline(df.complete[0], color='k', lw=2, ls='--')


