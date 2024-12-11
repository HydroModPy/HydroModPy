# -*- coding: utf-8 -*-
"""
Created on Wed Sep 18 11:47:05 2024

@author: ronan
"""

#%% MODEL CLEMENT

# Frame settings
box = True # or False
sink_fill = False # or True
sim_state = 'steady' # 'steady' or 'transient'
plot_cross = True

# Climatic settings
first_clim = 'mean' # or 'first or value
freq_time = 'M'

# Hydraulic settings
nlay = 25
lay_decay = 1.25 # 1 for no decay
bottom = 0 # elevation in meters, None for constant auifer thickness, or 2D matrix
thick = 30 # if bottom is None, aquifer thickness
cond_decay = 1/30 # exponential decay : 1/20 (half decrease at 20m)
verti_cond = None # or [ [1e-5, [0, 20]], [1e-6, [20,80]] ]
cond_drain = None # or value of conductance

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

# Import modules
BV.add_settings()
BV.add_climatic()
BV.add_geometric() # soon
BV.add_hydraulic()

# Frame settings
BV.settings.update_box_model(box)
BV.settings.update_sink_fill(sink_fill)
BV.settings.update_simulation_state(sim_state)
BV.settings.update_active_plot(plot_cross=plot_cross)

# Hydraulic settings
BV.hydraulic.update_nlay(nlay) # 1
BV.hydraulic.update_lay_decay(lay_decay) # 1
BV.hydraulic.update_bottom(bottom) # None
BV.hydraulic.update_thick(thick) # 30 / intervient pas si bottom != None
BV.hydraulic.update_cond_vertical(verti_cond)
BV.hydraulic.update_cond_drain(cond_drain)

# Boundary settings
BV.settings.update_bc_sides(bc_left, bc_right)
BV.add_oceanic(sea_level)
BV.settings.update_split_temporal(split_temp=False)

# Particle tracking settings
BV.settings.update_input_particules(zone_partic=zone_partic, path = tif_file, tracking_direction=tracking_dir)

koptim_val = 2.9e-6 * 24 * 3600
BV.hydraulic.update_hyd_cond(koptim_val)

poro_val = 1 / 100 # -
BV.hydraulic.update_porosity(poro_val)

Ss_formula = 1000*9.8*(1e-10+(poro_val*4.4e-10)) # rho*g*(alpha+nBeta)
BV.hydraulic.update_ss(Ss_formula)

decay_factor = 2
BV.hydraulic.update_cond_decay(cond_decay) # 0
BV.hydraulic.update_poro_decay(cond_decay/decay_factor)
BV.hydraulic.update_ss_decay(cond_decay/decay_factor)

list_of_R = np.arange(1000/100,1000*10, 10) / 365 / 1000
list_of_R = np.linspace(1000/100,1000*100, 10) / 365 / 1000
list_of_R = np.geomspace(10,10000, 20) / 365 / 1000
# list_of_R = np.array([10,100,1000,10000]) / 365 / 1000
# list_of_R = np.array([10,25,50,100,150,200,250,500,750,1000,1250,1500,2000,3000,4000,5000,6000,7000,8000,9000,10000])

model_names = []

for R in list_of_R:

    model_name = 'clement4_'+str(int(round(R*365*1000,0)))
    BV.climatic.update_recharge(R, sim_state=sim_state)
    BV.climatic.update_first_clim(first_clim)
    BV.settings.update_model_name(model_name)
    
    
    model_modflow = BV.preprocessing_modflow(for_calib=False)
    success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=True)
    
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
                                                      actual_date=True, 
                                                      subbasin_results=True,
                                                      freq_time=freq_time) # or None

    model_names.append(model_name)

#%% FIGURES CLEMENT

dem = rasterio.open('C:/Users/ronan/GitHub/Repository/HydroModPy-master/examples/results/Example_05bis_Lasset/results_stable/geographic/watershed_dem.tif')

for mn in model_names:
    
    im = rasterio.open('C:/Users/ronan/GitHub/Repository/HydroModPy-master/examples/results/Example_05bis_Lasset/results_simulations/'+mn+'/'+'_postprocess/_rasters/'+'seepage_areas_t(0).tif')

    # rasterio.plot.show(np.ma.masked_where(dem.read(1) < 0, dem.read(1)), 
    #                           ax=ax, transform=dem.transform,
    #                           cmap='Greys_r', alpha=1, zorder=-5)

    fig, ax = plt.subplots(1,1, dpi=600)

    cont = gpd.read_file('C:/Users/ronan/GitHub/Repository/HydroModPy-master/examples/results/Example_05bis_Lasset/results_stable/geographic/watershed.shp')
    rivers = gpd.read_file('C:/Users/ronan/OneDrive/UNINE/8_Modeling/Lasset/_data/_hydrography/_newhydro_v2/streams_peren_upv2.shp')
    wetlands = gpd.read_file('C:/Users/ronan/OneDrive/UNINE/8_Modeling/Lasset/_data/_hydrography/_newhydro_v2/wetlands_peren_upv2.shp')
    
    rivers = gpd.clip(rivers, cont)
    wetlands = gpd.clip(wetlands, cont)
    
    rasterio.plot.show(np.ma.masked_where(dem.read(1) < 0, dem.read(1)), 
                              ax=ax, transform=dem.transform,
                              cmap='Greys', alpha=0.30, zorder=-5)

    rivers.plot(ax=ax, lw=1, ec='blue', facecolor='None')
    wetlands.plot(ax=ax, lw=1, ec='blue', facecolor='blue')

    imm = np.ma.masked_where((dem.read(1) < 0) | (im.read(1) == 0), im.read(1))

    rasterio.plot.show(imm, 
                              ax=ax, transform=dem.transform,
                              cmap=mpl.colors.ListedColormap('darkorange'), alpha=1, zorder=10)
    
    mask = gpd.read_file('C:/Users/ronan/OneDrive/UNINE/8_Modeling/Lasset/_data/_mix/mask_catchment.shp')
    # mask.plot(ax=ax, lw=1, ec='k', facecolor='white')

    cont.plot(ax=ax, lw=1, ec='k', facecolor='None')
    
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    plt.axis('off')
    
    ax.set_title('K/R = '+str(round(koptim_val/(int(mn.split('_')[1])/365/1000),0)), fontsize=10)
    
    fig.savefig('C:/Users/ronan/Downloads/clement/'+mn+'.png', dpi=300, bbox_inches='tight')

import imageio
import glob
images = []
filenames = sorted(glob.glob('C:/Users/ronan/Downloads/clement/'+'*'), key=os.path.getmtime, reverse=True)
for filename in filenames:
    images.append(imageio.imread(filename))
imageio.mimsave('C:/Users/ronan/Downloads/clement_gif2.gif', images,
                loop=10, duration = len(model_names)*20)