# -*- coding: utf-8 -*-
"""
 * Author: T. Babey
 * Guidel field site simulation
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
import datetime
import dateutil

# Libraries need to be installed if not
import numpy as np
import pandas as pd
import scipy

# Libraries added from 'conda install' procedure
import geopandas as gpd
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib_scalebar.scalebar import ScaleBar
from mpl_toolkits.axes_grid1 import make_axes_locatable
import rasterio
from IPython import get_ipython
get_ipython().run_line_magic('matplotlib', 'inline')
import flopy
import imageio

import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

#%% HYDROMODPY

import src
import importlib
importlib.reload(src)

# Import HydroModPy modules
from src import watershed_root
from src.display import visualization_watershed, visualization_results, export_vtuvtk
from watershed import residencetimes
from watershed import streams
from modeling import radon_groundwater, radon_stream

# from os.path import dirname, abspath
# root_dir = dirname(dirname(dirname(dirname(dirname(abspath(__file__))))))
# print("Root path directory is: {0}".format(root_dir.upper()))
from src.tools import toolbox
root_dir = toolbox.hydromodpy_root(print_option=True)
sys.path.append(root_dir)

modflow_path = os.path.join(root_dir,'bin/')

# fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% ---- PATHS

#%% PERSONAL

from os.path import dirname, abspath
csim_path = root_dir = dirname(abspath(__file__))
# data_path = os.path.join(csim_path,'data/')
data_path = os.path.join(csim_path,'data')
out_path = os.path.join(csim_path,'results')


#%% ---- WATERSHED

#%% OPTIONS

dem_path = os.path.join(data_path,'dem_guidel_25m.tif')
# dem_path = 'C:/Users/trist/Documents/SSH/HydroModPy/src/geomodeller/data/dem_brittany/BDALTI_bzh_75m.tif'
# load = True
load = False
watershed_name = 'Guidel_Upstream-Lannenec_v3'
from_lib = None # os.path.join(root_dir,'watershed_library.csv')
from_dem = None # [path, cell size]
from_shp = None # [path, buffer size]
from_xyv = [214866, 6758551 , 200 , 100 , 'EPSG:2154'] # [x, y, snap distance, buffer size]
bottom_path = None # path
save_object = True

#%% GEOGRAPHIC

BV = watershed_root.Watershed(dem_path=dem_path,
                              out_path=out_path,
                              load=load,
                              watershed_name=watershed_name,
                              from_lib=from_lib, # os.path.join(root_dir,'watershed_library.csv')
                              from_dem=from_dem, # [path, cell size]
                              from_shp=from_shp, # [path, buffer size]
                              from_xyv=from_xyv, # [x, y, snap distance, buffer size]
                              # nlay=10,
                              # lay_thickness=20,
                              bottom_path=bottom_path, # path 
                              save_object=save_object)

# Paths generated automatically but necessary for plots
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'


#%% DEFINE

# Frame settings
model_name = 'default'
box = True # or False
sink_fill = False # or True
sim_state = 'steady' # 'steady' or 'transient'
plot_cross = True
dis_perlen = False

# Import modules
BV.add_settings()

# Frame settings
BV.settings.update_model_name(model_name)
BV.settings.update_box_model(box)
BV.settings.update_sink_fill(sink_fill)
BV.settings.update_simulation_state(sim_state)
BV.settings.update_check_model(plot_cross=plot_cross)

BV.settings.update_dis_perlen(dis_perlen=dis_perlen)


#%% OBJECTIVE FUNCTION

def func_objguidel_full(x,args):
    
    K1111  = x[0]
    K1111  = np.power(10,K1111)
    
    K2222  = x[1]
    K2222  = np.power(10,K2222)
    
    K6666  = x[2]
    K6666  = np.power(10,K6666)
    
    # vkaval = x[1]
    # vkaval = np.power(10,vkaval)
    BV = args

    shrenv={}
    
    # Modflow5
    from src.modeling import Modflow5
    mf5 = Modflow5('modflow5')
    mf5.set_iptpar(model_folder = BV.simulations_folder,  
                   model_name   = BV.settings.model_name)
    
    # spatial discretization
    from src.discretization import SDis
    sdis = SDis('sdis')
    sdis.set_iptpar(genmtd_surf   = 'from_demtif',
                    demtif_path   = BV.geographic.watershed_box_buff_dem,
                    genmtd_vert   = 'homogeneous',
                    crs           = 'EPSG:2154',
                    lenuni        = 'm',    
                    nlay          = 19,
                    lay_thickness = [20,15,15,15,15,15,15,25,25,25,25,25,25,35,35,35,35,35,35])
                    # nlay          = 10,
                    # lay_thickness = [20,30,30,30,50,50,50,70,70,70])
    mf5.add_module(sdis)
    
    # time discretization
    from src.discretization import TDis
    tdis = TDis('tdis')
    tdis.set_iptpar(sim_state = 'steady',
                    nper      = 1,
                    itmuni    = 'd')
    mf5.add_module(tdis)
    
    # hydraulic conductivity
    from parameters import HydraulicConductivity
    hhc = HydraulicConductivity('hhc')
    hhc.set_iptpar(genmtd_sdis      = 'map_csv',
                    fpath_map_pos    = 'C:/Users/trist/Documents/SSH/HydroModPy/users/tbabey/guidel/calibration_mean_water_levels/data/geol_model_XYZ_epsg2154_no_1st_layer.csv',
                    crs_map_pos      = 'EPSG:2154',
                    idheader_map_pos = 'facies',
                    map_param_source = 'from_shrenv',
                    set_first_layer_as_facies = '1111.0',
                    fpath_map_par    = 'C:/Users/trist/Documents/SSH/HydroModPy/users/tbabey/guidel/calibration_mean_water_levels/data/hydro_parameters_guidel.csv',
                    idheader_value   = 'hk_ms',
                    lenuni           = 'm',
                    itmuni           = 's')
    mf5.add_module(hhc)
    # hhc.set_iptpar(genmtd_sdis = 'homogeneous',
    #                 # value       = 5.0e-6,
    #                 value       = 3e-6,
    #                 lenuni      = 'm',
    #                 itmuni      = 's',
    #                 sgrid       = 'from_shrenv',
    #                 tgrid       = 'from_shrenv')
    # mf5.add_module(hhc)
    
    # Specific yield
    from parameters import SpecificYield
    sy = SpecificYield('sy')
    sy.set_iptpar(genmtd_sdis = 'homogeneous',
                  value       = 0.05)
    mf5.add_module(sy)
    
    # Specific storage
    from parameters import SpecificStorage
    ss = SpecificStorage('ss')
    ss.set_iptpar(genmtd_sdis = 'homogeneous',
                  value       = 1e-10)
    mf5.add_module(ss)
    
    # Vertical anistropy K
    from parameters import VerticalAnisotropyK
    vka = VerticalAnisotropyK('vka')
    vka.set_iptpar(genmtd_sdis = 'homogeneous',
                   value       = 1)
                   # value       = vkaval)
    mf5.add_module(vka)
    
    # recharge
    from parameters import Recharge
    rec = Recharge('rec')
    rec.set_iptpar(genmtd_sdis = 'homogeneous',
                   genmtd_tdis = 'constant',
                   value = 246,
                   lenuni = 'mm',
                   itmuni = 'Y')
    mf5.add_module(rec)
    
    # initial boundary conditions
    from parameters import InitialBoundaryCondition
    ibound = InitialBoundaryCondition('ibnd')
    ibound.set_iptpar(genmtd_sdis = 'all_active')
    mf5.add_module(ibound)
    
    # initial heads
    from parameters import InitialHead
    strh = InitialHead('strh')
    strh.set_iptpar(genmtd_sdis = 'vertical_hydrostatic_equilibrium',
                    genmtd_ihd  = 'dem')
    mf5.add_module(strh)
    
    # # sea level
    # from parameters import SeaLevel
    # slvl = SeaLevel('sealvl')
    # slvl.set_iptpar(genmtd_tdis = 'constant',
    #                 value = 0,
    #                 lenuni = 'm',
    #                 sgrid = 'from_shrenv',
    #                 tgrid = 'from_shrenv')
    # mf5.add_module(slvl)
    
    # drains
    from parameters import Drain
    drn = Drain('drn')
    drn.set_iptpar(genmtd_sdis  = 'surface_no_constanthead',
                   genmtd_value = 'conductance',
                   thickness    = 1,
                   lenuni       = 'm')
    mf5.add_module(drn)
    
    # # wells 
    # from parameters import Well
    # wel = Well('well')
    # wel.set_iptpar(genmtd_pos       = 'map_csv',
    #                fpath_map_pos    = 'C:/Users/trist/Documents/SSH/HydroModPy/users/tbabey/guidel/calibration_mean_water_levels/data/pumping_wells_pos_epsg2154.csv',
    #                crs_map_pos      = 'EPSG:2154',
    #                idheader_map_pos = 'wells',
    #                genmtd_total_flux = 'chronicles_csv',
    #                fpath_chron       = 'C:/Users/trist/Documents/SSH/HydroModPy/users/tbabey/guidel/calibration_mean_water_levels/data/pumping_wells_chronicles_m3d.csv',
    #                dateheader_chron  = 'date',
    #                dateformat_chron  = '%d/%m/%Y',
    #                lenuni            = 'm',
    #                itmuni            = 'd',
    #                genmtd_zdstr_flux = 'proportional_transmissivity',
    #                opposite_flux_sign_option = True)
    # mf5.add_module(wel)
    
    # plot data options (hk...)
    # TODO@TB: rewrite
    mf5.set_advpar(plot_cross = False, 
                   cross_ylim = [-500,50])
    
    # Check grid option (flow connectivity) 
    mf5.set_advpar(check_grid_flow_connectivity = False,
                   pc_verbose = True)
    
    #%% GEOLOGY
    geol_map_param = pd.read_csv('C:/Users/trist/Documents/SSH/HydroModPy/users/tbabey/guidel/calibration_mean_water_levels/data/hydro_parameters_guidel.csv', sep = '\t', index_col=0)
    for facies in geol_map_param.columns.values:
        if facies == '1111.0':
            geol_map_param.at['hk_ms',facies] = K1111
        elif facies == '2222.0' or facies == '7777.0':
            geol_map_param.at['hk_ms',facies] = K2222
        elif facies == '6666.0':
            geol_map_param.at['hk_ms',facies] = K6666
        elif facies == '4444.0':
            geol_map_param.at['hk_ms',facies] = 1e-11
    
    shrenv.update({'geol_map_param':geol_map_param})
    
    #%% PROCESSING MODFLOW
    shrenv = mf5.processing_modules(shrenv) 
    mf5.preprocessing(shrenv)
    shrenv,success_modflow = mf5.processing(shrenv)
    
    #%% WTH result extraction
    from postprocessing.modflow import ObservationWellsWTHead
    obsWTH = ObservationWellsWTHead()
    obsWTH.set_iptpar(genmtd_sdis      = 'map_csv',
                      fpath_wellpos    = 'C:/Users/trist/Documents/SSH/HydroModPy/users/tbabey/guidel/calibration_mean_water_levels/data/guidel_wells_pos_epsg2154.csv',
                      crs_map_pos      = 'EPSG:2154',
                      idheader_map_pos = 'wells',
                      wt_head          = 'mf_res',
                      folderpath_mfres = os.path.join(mf5.full_path, mf5.model_name),
                      drycellval       = mf5.get_advpar['upw_hdry'])
    obsWTH.preprocessing(shrenv)
    shrenv = obsWTH.processing(shrenv)
    
    #%% WTH comparison with reference data
    fpath_wellref = 'C:/Users/trist/Documents/SSH/HydroModPy/users/tbabey/guidel/calibration_mean_water_levels/data/Guidel_wlevels_mNGF_meanstd_only_best.csv'
    wellref = pd.read_csv(fpath_wellref, sep = '\t')
    
    wellid = 'wells'
    meanwlid = 'mean_wl_masl'
    stdwlid = 'std_wl_masl'
    
    wellref = wellref.set_index(wellid)
    
    res = shrenv['mfpp_obs_wells'].copy()
    res = res[res.columns.intersection(wellref.index)]
    
    comparedf = res.copy()
    
    for i in list(range(len(comparedf.index))):
        for j in list(range(len(comparedf.columns))):
            well = comparedf.columns.values[j]
            meanref = wellref[meanwlid][wellref.index==well].to_numpy()
            stdref = wellref[stdwlid][wellref.index==well].to_numpy()
            comparedf.iloc[i,j] = (comparedf.iloc[i,j]-meanref)/stdref
            # comparedf.iloc[i,j] = comparedf.iloc[i,j]-meanref
    
    return res, wellref, comparedf, shrenv

def func_objguidel(x,args):
    
    K1111  = x[0]
    K1111  = np.power(10,K1111)
    
    K2222  = x[1]
    K2222  = np.power(10,K2222)
    
    K6666  = x[2]
    K6666  = np.power(10,K6666)
    
    # vkaval = x[1]
    # vkaval = np.power(10,vkaval)
    
    res, wellref, comparedf, shrenv = func_objguidel_full(x,args)
    
    nrmse = np.sum(np.power(comparedf.iloc[:,:].to_numpy(),2)) 
    nrmse = np.power(nrmse,0.5) / comparedf.iloc[:,:].size
    
    print('nRMSE for K_alt='+str(K1111)
          +'m/s, K_faults='+str(K2222)
          +'m/s, K_mx='+str(K6666)
          +'m/s, rMSE='+str(nrmse)+'.')

    return nrmse


# %% OPTIMIZATION

# logK1111min = -7
# logK1111max = -5
# K1111 = np.logspace(logK1111min,logK1111max,num=10)
# logK1111 = np.log10(K1111)

# logK2222min = -7
# logK2222max = -4
# K2222 = np.logspace(logK2222min,logK2222max,num=15)
# logK2222 = np.log10(K2222)

# logK6666min = -8
# logK6666max = -6
# K6666 = np.logspace(logK6666min,logK6666max,num=10)
# logK6666 = np.log10(K6666)

# # vkamin = 1
# # vkamax = 10
# # vka = np.linspace(vkamin,vkamax,num=10)
# # logvka = np.log10(vka)

# res = np.zeros((len(logK1111),len(logK2222),len(logK6666)))

# for i in list(range(len(K1111))):
#     for j in list(range(len(K2222))):
#         for k in list(range(len(K6666))):
#             res[i,j,k] = func_objguidel((logK1111[i],logK2222[j],logK6666[k]),BV)
        
    
# %% PLOT

# fpath = 'C:/Users/trist/Documents/research/Guidel/calibration/results_heterogeneous_2layers.csv'
# res = pd.read_csv(fpath, sep = '\t', index_col ='K_ms')

# logK1111min = np.log10(np.min(res.index.values))
# logK1111max = np.log10(np.max(res.index.values))

# logK2222min = np.log10(np.min(res.columns.values.astype(float)))
# logK2222max = np.log10(np.max(res.columns.values.astype(float)))

logK1111min = -7
logK1111max = -5
K1111 = np.logspace(logK1111min,logK1111max,num=10)
logK1111 = np.log10(K1111)

logK2222min = -7
logK2222max = -4
K2222 = np.logspace(logK2222min,logK2222max,num=15)
logK2222 = np.log10(K2222)

logK6666min = -8
logK6666max = -6
K6666 = np.logspace(logK6666min,logK6666max,num=10)
logK6666 = np.log10(K6666)

# # 2D Heatmap nRMSE homogeneous anisotropic model
# plt.imshow(res.iloc[:,:], 
#             interpolation='none',
#             aspect = 'auto',
#             extent=[logK2222min,logK2222max,logK1111max,logK1111min])
# plt.xlabel("log(Kh) Deep Aquifer [m/s]")
# plt.ylabel("log(Kh) Alterites [m/s]")
# plt.title("Heterogeneous 2 layers model")
# plt.colorbar(label='nRMSE [-]')
# plt.savefig('C:/Users/trist/Documents/research/Guidel/calibration/results_heterogeneous_2layers.jpg',
#             bbox_inches='tight')
# plt.show()

# # nRMSE vs log K homogeneous anisotropic model
# plt.plot(res.index.values,res.iloc[:,0],'r')
# plt.plot(res.index.values,res.iloc[:,-1],'b')
# plt.xlabel("Kh Alterites [m/s]")
# plt.xscale('log')
# plt.ylabel("nRMSE [-]")
# plt.legend(['Kh Deep Aquifer = 1e-8 m/s', 'Kh Deep Aquifer = 1e-6 m/s'])
# plt.title("Heterogeneous 2 layers model")
# plt.savefig('C:/Users/trist/Documents/research/Guidel/calibration/results_heterogeneous_2layers_-8-6.jpg',
#             bbox_inches='tight')
# plt.show()

#%% Model results vs data for best case scenarios:simulations
# temp = res.stack().index[np.argmin(res.values)]

# bestK1111 = K1111[5]
# bestK2222 = K2222[9]
# bestK6666 = K6666[9]

bestK1111 = 1.3e-6
bestK2222 = 8.5e-6
bestK6666 = 1.3e-7

# bestK1111 = 1e-6
# bestK2222 = 1e-5
# bestK6666 = 1e-8


res1, wellref, comparedf, shrenv = func_objguidel_full((np.log10(bestK1111),np.log10(bestK2222),np.log10(bestK6666)),BV)

#%% Plot domain
from postprocessing.modflow import DisplayCrossSections
dispSC = DisplayCrossSections()
dispSC.set_iptpar(cross_layer       = 1,
                  dataname          = 'Kh',
                  unit_display      = 'm/d',
                  colorscale_linlog = 'log')
dispSC.set_shrpar(data = 'hk')
dispSC.preprocessing(shrenv)
dispSC.processing(shrenv)

#%% Model results vs data for best case scenarios:plot
plt.errorbar(wellref.index, wellref['mean_wl_masl'], yerr=wellref['std_wl_masl'],fmt='.k')  
plt.plot(wellref.index,res1[wellref.index].iloc[0,:],'r')
plt.ylabel('Water table elevation [masl]')
plt.title('Full geolgical model - K_mx=1.3e-7m/s')
plt.legend(['Best calibrated model', 'Observations'])
plt.savefig('C:/Users/trist/Documents/research/Guidel/calibration/results_heterofull-piezos.jpg',
            bbox_inches='tight')
plt.show()



#%% OPTIMIZATION

# res = scipy.optimize.dual_annealing(func_objguidel,((Kmin,Kmax),),args=(BV,))


# if success_modflow is True:
#     mf5.dem_watershed_path = BV.geographic.watershed_box_buff_dem  #TODO@TB
#     mf5.geographic = BV.geographic  #TODO@TB
#     mf5.postprocessing(shrenv)

# model_modflow = mf5

# visu = visualization_results.Visualization(BV, model_name)
# visu.visual2D(object_list = ['map','grid',
#                               'watertable', 'watertable_depth',
#                               'drain_flow','surface_flow'
#                               ],
#               color_scale = [(None,None),(None,None),
#                               (None,None),(0,10),
#                               (None,None),(None,None),
#                               ], 
#               lines=500)


#%% NOTES