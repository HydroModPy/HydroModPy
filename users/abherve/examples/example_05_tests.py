# -*- coding: utf-8 -*-
"""

Created on 2023.

@author: Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy

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
from osgeo import gdal

import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = True

#%% ROOT

from os.path import dirname, abspath
root_dir = dirname(dirname(dirname(dirname(abspath(__file__)))))
sys.path.append(root_dir)

cwd = os.getcwd()
if not cwd == root_dir:
    os.chdir(root_dir)
    # print("Root path directory is: {0}".format(cwd))

#%% HYDROMODPY

import src
import importlib
importlib.reload(src)

# Import HydroModPy modules
from src import watershed_root
from src.display import visualization_results, export_vtuvtk
from src.tools import toolbox, folder_root

fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

def select_period(df, first, last):
    df = df[(df.index.year>=first) & (df.index.year<=last)]
    return df

#%% ---- PATHS

#%% PERSONAL

example_path = root_dir + "/examples/05_particle tracking for residence times/"
data_path = os.path.join(example_path, "data") + '/'
# To get or initialize the folder path:
# out_path = folder_root.root_folder_results()
# To change the folder path: out_path = folder_root.update_root_folder_results()
# out_path = '/home/agauvain/Documents/HydroModPy/'
out_path = 'E:/_RONAN/_E_SIMULATIONS/HYDROMODPY/'

#%% ---- WATERSHED

#%% OPTIONS

# case = 'Lasset'
# case = 'Hillslope_2D'
case = 'Hillslope_1D'

if case == 'Hillslope_1D':
    dem_path_ref = data_path + 'hillslope_1D.tif'
    
    resamp_res = 20
    dem_path_res = data_path + 'hillslope_1D_resampled'+str(resamp_res)+'.tif'
    
    if not os.path.exists(dem_path_res):
        # open reference file and get resolution
        x_res = resamp_res
        y_res = resamp_res  # make sure this value is positive
        # specify input and output filenames
        inputFile = dem_path_ref
        outputFile = dem_path_res
        # call gdal Warp
        kwargs = {"format": "GTiff", "xRes": x_res, "yRes": y_res}
        ds = gdal.Warp(outputFile, inputFile, **kwargs)
        del(ds)
    # wbt.verbose = True
    # wbt.resample(
    #     dem_path_ref, 
    #     dem_path_res, 
    #     cell_size=100, 
    #     base=None, 
    #     method="cc")
    
    x = imageio.imread(dem_path_res)
    x = (x*0)+100
    # x[1,:] = -99999
    toolbox.export_tif(dem_path_res, x, -99999, data_path + 'hillslope_1D_userdefined.tif')
    dem_path = data_path + 'hillslope_1D_userdefined.tif'
    
    load = False
    watershed_name = case
    from_lib = None # os.path.join(root_dir,'watershed_library.csv')
    from_dem = [dem_path, 10] # [path, cell size]
    from_shp = None # [path, buffer size]
    from_xyv = None # [x, y, snap distance, buffer size]
    bottom_path = None # path
    modflow_path = os.path.join(root_dir,'bin/')
    save_object = True
    
if case == 'Hillslope_2D':
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

if case == 'Lasset':
    dem_path = data_path + 'regional dem.tif'
    load = False
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
# fig, ax = plt.subplots(1,1, figsize=(6,3))
# R = BV.climatic.recharge
# r = R * 0.1
# ax.plot(R, label='recharge_manual', c='dodgerblue', lw=2)
# ax.plot(r, label='runoff_manual', c='navy', lw=2)
# ax.set_xlabel('Months')
# ax.set_ylabel('[mm/month]')
# ax.legend()

x = pd.read_csv(data_path+'/'+'_REC_D.csv', sep=';', parse_dates=True, index_col=0)
x = x.sort_index()
x = select_period(x, 2001, 2003)
x = x['REA_historic'] / 1000
Rd = x.copy()
Rw = x.resample('W').mean()
Rm = x.resample('M').mean()
y = pd.read_csv(data_path+'/'+'_RUN_D.csv', sep=';', parse_dates=True, index_col=0)
y = y.sort_index()
y = select_period(y, 2001, 2003)
y = y['REA_historic'] / 1000
rd = y.copy()
rw = y.resample('M').mean()
rm = y.resample('M').mean()
# plt.plot(x)
# plt.plot(y)
# BV.climatic.update_recharge(x / 1000, sim_state='transient') # from mm to m
# BV.climatic.update_runoff(y / 1000, sim_state='transient') # from mm to m
# R = BV.climatic.recharge
# r = BV.climatic.runoff
plt.plot(Rm)
plt.plot(Rw)
plt.plot(Rd)
plt.yscale('log')

#%% ---- PARAMETRIZATION

#%% DEFINE

# Frame settings
model_name = 'default_Rm_md_split'
# model_name = 'default_m-month'
box = True # or False
sink_fill = False # or True
sim_state = 'transient' # 'steady' or 'transient'
plot_cross = False

plot = False


# split_temp = 30
# split_temp = True
split_temp = False

# Climatic settings
# recharge = pd.Series([10,20,30,40,50,60,60,50,40,30,20,10])/30/1000/10
# recharge = 100 / 365 / 1000
# recharge = pd.Series([0]*30) / 365 / 1000
# recharge = Rd.copy()
# kr = 10
hyd_cond = 10 #e-5 * 24 * 3600
# recharge = Rw.copy()
# rval = hyd_cond / kr
# rval = 1
rval = 1
# recharge = pd.Series([rval,rval,rval,rval,rval,rval,rval,rval,rval,rval,
#                       0,0,0,0,0,0,0,0,0,0,
#                       0,0,0,0,0,0,0,0,0,0,
#                       0,0,0,0,0,0,0,0,0,0,])#/30/1000 #* 30
recharge = np.ones(1000)*0
recharge[:30] = rval
recharge = pd.Series(recharge)
first_clim = 'mean' # or 'first or value
# first_clim = 100 / 365 / 1000 # or 'first or value
freq_time = 'M'

# Hydraulic settings
nlay = 10
lay_decay = 1 # 1 for no decay
bottom = 0 # elevation in meters, None for constant auifer thickness, or 2D matrix
thick = 30 # if bottom is None, aquifer thickness
# if watershed_name == 'Lasset':
#     hyd_cond = 1e-8 * 24 * 3600 # m/day
# else:
# hyd_cond = 1e-4 * 24 * 3600 #* 30 # m/day

cond_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
verti_cond = None # or [ [1e-5, [0, 20]], [1e-6, [20,80]] ]
cond_drain = None # or value of conductance
porosity = 10 / 100 # -
poro_decay = 0 # exponential decay : 1/20 (half decrease at 20m)

# Boundary settings
bc_left = 0 # or value
bc_right = None # or value
sea_level = 'None' # or value based on specific data : BV.oceanic.MSL

# Particle tracking settings
zone_partic = 'watershed' # domain or watershed or path
tif_file = '/home/agauvain/Documents/HydroModPy/Lasset/results_simulations/default/_postprocess/_rasters/seepage_areas_t(0).tif'
tracking_dir = 'forward' # backward or forward

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

# Ss_formula = 1000*9.8*(1e-10+(porosity*4.4e-10)) # rho*g*(alpha+nBeta)
# print(Ss_formula)
# BV.hydraulic.update_ss(Ss_formula)
BV.hydraulic.update_ss(1e-15)

# Boundary settings
BV.settings.update_bc_sides(bc_left, bc_right)
BV.add_oceanic(sea_level)
BV.settings.update_split_temporal(split_temp)

# Particle tracking settings
BV.settings.update_input_particules(zone_partic=zone_partic, path=tif_file, tracking_direction=tracking_dir)

#%% ---- MODELING

#%% MODFLOW

model_modflow = BV.preprocessing_modflow(for_calib=False)
success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=True)
"""
if success_modflow == True:
    BV.postprocessing_modflow(model_modflow,
                              watertable_elevation = True,
                              watertable_depth= True, 
                              seepage_areas = True,
                              outflow_drain = True,
                              groundwater_flux = True,
                              groundwater_storage = True,
                              accumulation_flux = True,
                              persistency_index=True,
                              intermittency_monthly=False,
                              intermittency_daily=False,
                              export_all_tif = True)
"""
#%% MODPATH
"""
if sim_state == 'steady':
    if success_modflow == True:
        model_modpath = BV.preprocessing_modpath(model_modflow)
        success_modpath = BV.processing_modpath(model_modpath, write_model=True, run_model=True)
    if success_modpath == True:
        BV.postprocessing_modpath(model_modpath,
                                  ending_point=True,
                                  starting_point=True,
                                  pathlines_shp=True,
                                  particules_shp=True,
                                  random_id=None) # None
"""
#%% TIMESERIES
"""
if sim_state == 'steady':
    timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                      model_modpath=model_modpath,
                                                      actual_date=True, 
                                                      subbasin_results=True,
                                                      freq_time=freq_time) # or None
else:
    timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                      model_modpath=False,
                                                      actual_date=True, 
                                                      subbasin_results=True,
                                                      freq_time=freq_time) # or None
"""
#%% ---- PLOT
"""
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

fig.savefig(os.path.join(simulations_folder, model_name,
                            '_postprocess', '_figures', 'RAW_'+model_name+'.png'))

#%% RAW MAP 2

shp_pathlines = gpd.read_file(simulations_folder+model_name+'/_postprocess/_particules/pathlines.shp')
shp_endpoints = gpd.read_file(simulations_folder+model_name+'/_postprocess/_particules/ending.shp')

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
shp_pathlines.plot(ax=ax, column='time', cmap=mpl.colors.ListedColormap(['k']), lw=0.5,
                  norm=mpl.colors.LogNorm(vmin=1, vmax=10000),
                  zorder=1)

shp_endpoints['time'] = shp_endpoints['time'] / 365
shp_endpoints.plot(ax=ax, column='time', cmap='jet', lw=0, markersize=5,
                 norm=mpl.colors.LogNorm(vmin=1, vmax=10000), legend=True,
                 zorder=2)

try:
    line.plot(ax=ax, color='k', lw=3)
except:
    pass

ax.set_title('Ending residence times [y]')

ax.get_xaxis().set_visible(False)
ax.get_yaxis().set_visible(False)  

fig.tight_layout()

fig.savefig(os.path.join(simulations_folder, model_name,
                            '_postprocess', '_figures', 'RTD_'+model_name+'.png'))
"""
#%% CROSS

# if case != 'Lasset':

plot = True
if plot == True:

    import flopy.utils.binaryfile as fpu
    
    # Load model
    fname = simulations_folder+model_name+'/'+model_name
    ml = flopy.modflow.Modflow.load(fname+'.nam')
    hdobj = flopy.utils.HeadFile(fname + '.hds')
    times = hdobj.get_times()
    print('LOAD')
    

    for i, t in enumerate([times[0],times[-1]]):
        i = int(i)
        head = hdobj.get_data(totim=t)
        
        # Figure
        fig = plt.figure(figsize=(10, 4), dpi=300)
        ax = fig.add_subplot(1, 1, 1)
        ax.set_title('Cross-section : '+str(i))
        ax.set_xlabel('x [m]')
        ax.set_ylabel('z [m]')
        
        xsect = flopy.plot.PlotCrossSection(model=ml, line={'Row': 0})
        # Head color
        pc = xsect.plot_array(head, masked_values=[999.], head=head, cmap='Blues_r',
                                vmin=0, vmax=100,
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
        Qx = cbb.get_data(text='FLOW RIGHT FACE', kstpkper=kstpkper, totim=t)[0]
        Qy = np.ones(shape=(10,1,100))
        Qz = cbb.get_data(text='FLOW LOWER FACE', kstpkper=kstpkper, totim=t)[0]
        drain = cbb.get_data(text='DRAINS', kstpkper=kstpkper, totim=t)[0]
        Qc = cbb.get_data(text='CONSTANT HEAD', kstpkper=kstpkper, totim=t)[0]
        Q = np.sqrt(Qx**2 + Qz**2) # ???
        Q_print = Q[0,0,0] # m/m
        
        if sim_state == 'steady':
    
            # Particules plot
            end = gpd.read_file(simulations_folder+model_name+'/_postprocess/_particules/ending.shp')
            end_fil = end[end['zone']==1]
            list_particules = end_fil['particleid'].unique()
            shp = gpd.read_file(simulations_folder+model_name+'/_postprocess/_particules/particules.shp')
            shp['time'] = shp['time'] / 365
            # shp_fil = shp[shp['time']>1]
            shp_fil = shp.copy()
            shp_fil = shp_fil[shp_fil['particleid'].isin(list_particules)]
            shp_fil = shp_fil[shp_fil['particleid']==80]
            sc = ax.scatter(shp_fil['x'], shp_fil['z'], c=shp_fil['time'],
                       s=20, cmap='plasma_r', linewidths=0)
            cbsc = plt.colorbar(sc, shrink=0.75)
            cbsc.set_label('Residence times [y]', labelpad=+10)
        
        # ax.set_ylim(70,200)
        ax.set_ylim(0,100)

        
        # fig.savefig(os.path.join(simulations_folder, model_name,
        #                             '_postprocess', '_figures', 'CROSS_'+model_name+'.png'))

#%% RECESSION

fname = simulations_folder+model_name+'/'+model_name

import flopy.utils.binaryfile as fpu
import flopy.utils.binaryfile as bf

# cbb = bf.CellBudgetFile('mymodel.cbb')
# cbb = fpu.CellBudgetFile('E:/_RONAN/_E_SIMULATIONS/HYDROMODPY/Canut_trans/results_simulations/explor_KR_sumunsplit_0_1/explor_KR_sumunsplit_0_1.cbc')
cbb = fpu.CellBudgetFile(fname + '.cbc')
# cbb.list_records()
kstpkper = cbb.get_kstpkper()
# drain = cbb.get_data(text='DRAINS', kstpkper=kstpkper[0])
list_D = []
list_CH = []
list_R = []
list_S = []
for i in range(len(kstpkper)):   
    st = cbb.get_data(text='STORAGE', kstpkper=(0,i))
    ch = cbb.get_data(text='CONSTANT HEAD', kstpkper=(0,i))
    drain = cbb.get_data(text='DRAINS', kstpkper=(0,i))
    rec = cbb.get_data(text='RECHARGE', kstpkper=(0,i))
    # print(drain[0][-1][-1])
    # list_D.append(drain[0][-1][0])
    list_D.append(drain[0]['q'].sum())
    list_CH.append(ch[0]['q'].sum())
    list_R.append(rec[0][-1][0].sum())
    
    Qx = cbb.get_data(text='FLOW RIGHT FACE', kstpkper=(0,i))
    Qy = np.ones(shape=(10,1,100))
    Qz = cbb.get_data(text='FLOW LOWER FACE', kstpkper=(0,i))
    # Q = np.sqrt(Qx**2 + Qz**2) # ???
    # Q_print = Q[0,0,0] # m/m


fac = 1

fig, ax = plt.subplots(figsize=(5, 5), dpi=300)
# ax.plot(abs(pd.Series(list_CH)))
ax.plot(abs(pd.Series(list_R))/fac, marker='o', ms=1, c='b')
ax.plot(abs(pd.Series(list_CH))/fac, c='red')
ax.set_xlabel('time')
ax.set_ylabel('discharge, rehcarge')
# plt.yscale('log')

df = pd.DataFrame()
df = abs(pd.Series(list_CH).to_frame())
df.columns = ['Q']
df['Q'] = 2*df['Q']/resamp_res
df['R'] = pd.Series(list_R)
df = df[30:]
df['t'] = np.arange(1,len(df)+1,1)
df['dQ'] = df['Q'].diff()
df['dt'] = df['t'].diff()
df['dQ/dt'] = abs(df['dQ'] / df['dt'])
df['a'] = ( 4.804*(hyd_cond**0.5)*1 ) / ( porosity*((2*1000)**1.5) )
df['B'] = df['a'] * (df['Q']**1.5)
df['a6'] = (3.14**2 * 1 * hyd_cond * 100 * 1 ) / ( porosity*((2*1000)**2) )
df['B6'] = df['a6'] * (df['Q']**1)

fig, ax = plt.subplots(figsize=(5, 5), dpi=300)
# ax.set_title('K/R = '+str(kr))
ax.plot(np.log10(df['Q']), np.log10(df['dQ/dt']), c='r', label='simulated')
ax.plot(np.log10(df['Q']), np.log10(df['B']), c='k', label='analytic')
# ax.plot(np.log10(df['Q']), np.log10(df['B6']), c='grey', label='analytic lin')

ax.set_xlabel('log(Q)')
ax.set_ylabel('log(-dQ/dt)')
# ax.set_yscale('log')
# ax.set_xscale('log')

fig, ax = plt.subplots(figsize=(5, 5), dpi=300)
ax.plot(np.log10(df['Q']), np.log10(df['dQ/dt']) - np.log10(df['B']))


fig, ax = plt.subplots(figsize=(5, 5), dpi=300)
# ax.plot(pd.Series(list_R), abs(pd.Series(list_CH)))
ax.plot(abs(pd.Series(list_R))/fac, abs(pd.Series(list_CH))/fac, marker='o', lw=1)
print(abs(pd.Series(list_CH)/fac).sum() / abs(pd.Series(list_R)/fac).sum())
ax.set_xlabel('recharge')
ax.set_ylabel('discharge')
# plt.yscale('log')
# plt.xscale('log')

#%% SMOD
"""
Smod = pd.read_csv(simulations_folder+model_name+'/'+'_postprocess/_timeseries/_simulated_timeseries.csv', sep=';', index_col=0, parse_dates=True)

fig, ax = plt.subplots(figsize=(5, 5), dpi=300)
# ax.plot(pd.Series(list_R), abs(pd.Series(list_CH)))
ax.plot((Smod['recharge']/fac)*1000, Smod['total_areas'], marker='o')
ax.set_xlabel('recharge')
ax.set_ylabel('seepage')
from matplotlib.ticker import FormatStrFormatter
ax.yaxis.set_major_formatter(FormatStrFormatter('%.1f'))

mf_list = flopy.utils.MfListBudget(simulations_folder+model_name+'/'+model_name+".list")
incremental, cumulative = mf_list.get_budget()
"""
#%% ---- NOTES

os.chdir(root_dir)

# the = pd.read_csv('H:/STORE_SIMULATIONS/Lasset/v7_e14/e14_model6_30.0-0-1.86e-06_2_60.0-1.0/_postprocess/_timeseries/_simulated_timeseries.csv',
#                   sep=';', index_col=0, parse_dates=True)
# the2 = pd.read_csv('D:/Users/abherve/ONEDRIVE_UNINECHYN/OneDrive - unine.ch/SIMULATIONS/Lasset/results_simulations/p2_model4_20.0-0-3.38e-06_40.0-0.9-1.02e-06_ALL-RCP85-1975-2099/_postprocess/_timeseries/_simulated_timeseries_bis.csv',
#                   sep=';', index_col=0, parse_dates=True)
# the2 = pd.read_csv('D:/Users/abherve/ONEDRIVE_UNINECHYN/OneDrive - unine.ch/SIMULATIONS/Lasset/results_simulations/p2_model4_20.0-0-3.38e-06_40.0-0.9-1.02e-06_ALL-RCP85-1975-2099/_postprocess/_timeseries/_simulated_timeseries_bis.csv',
#                   sep=';', index_col=0, parse_dates=True)
# theh = select_period(the2, 1980,2010)
# the2 = select_period(the2, 2070,2100)
# fig, ax = plt.subplots(figsize=(5, 5), dpi=300)
# # plt.plot(the['recharge'], the['watertable_elevation'])
# plt.plot(theh['recharge']*1000*30, theh['total_areas'], c='k')
# plt.plot(the2['recharge']*1000*30, the2['total_areas'])

# ax.set_xscale('log')
# # ax.plot(the2['recharge']*1000*30, the2['outflow_drain']*1000*30)
# from matplotlib.ticker import FormatStrFormatter
# # ax.yaxis.set_major_formatter(FormatStrFormatter('%.1f'))
