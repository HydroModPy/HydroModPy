# -*- coding: utf-8 -*-
"""
Created on Mon Dec 20 08:05:41 2021

@author: Clement Roques
"""

#TO BE DONE

#filter by goodness of fit


#%% GENERAL LIBRARIES

# General
import sys
from os.path import dirname, abspath
DIR = dirname(dirname(dirname(abspath(__file__))))
sys.path.append(DIR)
import numpy as np
import pandas as pd
from osgeo import gdal, osr
import matplotlib.pyplot as plt
import time
import os
import os.path
from os import path

# Gis
import imageio
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

# for extraction ERA5
import geopandas as gpd
import xarray as xr 
import rioxarray

                 
#%% HYDROMODPY MODULES
                    
from watershed import watershed_root, watershed_display
from tools import toolbox, vtk
from groundwater_flow import visualization, modflow_display
from calibration import calib_root
from tools import vtk
from groundwater_flow import visualization
from tools import toolbox

#%% close windows explorer
import psutil
from subprocess import PIPE

#%% LAYOUT PLOT

#fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% PERSONAL PATHS

# Path to the git repositoty home page
git_path = "C:/Users/LocalAdmin/Documents/GitHub/HydroModPy/CORE_COMM/"
# Path to the data folder
data_path = "D:/GoogleDrive/1.TRAVAIL/PYTHON/project/alps_pyr/_data/"
# Path where the results will be stored
out_path = "D:/GoogleDrive/1.TRAVAIL/PYTHON/project/alps_pyr/_out/"


#%% FOLDER DATA PATHS

# Specify path or boolean to active/enable modules
dems_path = data_path + 'dem/' # reginal DEM or conceptual DEM
shp_path = data_path + 'shp/' # if you want run a model from a shapefile
modflow_path = data_path + 'modflow/' # add bin/ folder with necessary .exe

surfex_path =  data_path + 'surfex/' # add surfex models in .h5 format (France scale, else, specify None)
geology_path = data_path + 'geology/' # add geologic layers
oceanic_path = data_path + 'oceanic/' # add specific sea level files
hydrology_path = data_path + 'hydrology/' # add hydrographic shapefiles
hydrometry_path = data_path + 'hydrometry/' # add hydrometry data for automatic download
intermittency_path = data_path + 'intermittency/' # add intermittency data for automatic download
piezometry_path = True # add piezometry data for automatic download
subbasin_path = True # generate subbasins from stations or manual points

library_path = data_path + 'watershed_library_GRDC_alps_pyr.csv' # each row is a study site with outlet coordinates
dem_name = "eu_dem_v11_E30-40N20_clip_alps_polyg_EPSG3035.tif" # name of dem
dem_path = dems_path + dem_name

ERA5_folder = data_path + 'climate/era5/'
ERA5_filename = 'adaptor.mars.internal-1646855474.1913588-16842-3-5ad8a136-1ff8-433e-a89f-a0c064ce1122.nc'

#find 
path_points = data_path + 'hydrology/GRDC_stations_EU_mars2022_EPSG3035_alps.shp'
points = gpd.read_file(path_points)

if path.exists(out_path + 'results.shp')==False:
    results = points
    em = np.empty(len(results))
    em[:]=np.nan
    
    results.loc[:,'t2m_me'] = em
    results.loc[:,'t2m_std'] = em        
    results.loc[:,'tp_me'] = em
    results.loc[:,'tp_std'] = em
    results.loc[:,'sde_me'] = em
    results.loc[:,'sde_std'] = em
    results.loc[:,'snowc_me'] = em
    results.loc[:,'snowc_std'] = em
    results.loc[:,'e_me'] = em
    results.loc[:,'e_std'] = em
    results.loc[:,'ep_me'] = em
    results.loc[:,'ep_std'] = em
    
    results.loc[:,'area_comp'] = em
    results.loc[:,'slope_me'] = em
    results.loc[:,'slope_std'] = em
    results.loc[:,'rug_me'] = em
    results.loc[:,'rug_std'] = em
    results.loc[:,'wti_me'] = em
    results.loc[:,'wti_std'] = em
    
    results.loc[:,'dams_num'] = em
    results.loc[:,'stream_length'] = em
    results.loc[:,'stream_length_db'] = em
    results.loc[:,'dist_to_stream_me'] = em
    
    results.loc[:,'bdticm_me'] = em
    results.loc[:,'bdticm_std'] = em
    
    results.loc[:,'glh_n_me'] = em
    results.loc[:,'glh_n_std'] = em
    results.loc[:,'glh_k_me'] = em
    results.loc[:,'glh_k_std'] = em
    results.loc[:,'glh_kstd_me'] = em
    results.loc[:,'glh_kstd_std'] = em
    
    results.loc[:,'su'] = em
    results.loc[:,'ss'] = em
    results.loc[:,'ev'] = em
    results.loc[:,'sc'] = em
    results.loc[:,'sm'] = em
    results.loc[:,'mt'] = em
    results.loc[:,'ig'] = em
    results.loc[:,'nd'] = em
    results.loc[:,'wb'] = em
    results.loc[:,'pa'] = em
    results.loc[:,'pb'] = em
    results.loc[:,'pi'] = em
    results.loc[:,'py'] = em
    results.loc[:,'va'] = em
    results.loc[:,'vb'] = em
    results.loc[:,'vi'] = em
    
    results.loc[:,'RA_ts_me'] = em
    results.loc[:,'RA_ts_std'] = em
    results.loc[:,'RA_ts_n'] = em
    results.loc[:,'RA_bL_me'] = em
    results.loc[:,'RA_bL_std'] = em
    results.loc[:,'RA_bL_n'] = em
    results.loc[:,'RA_bH_me'] = em
    results.loc[:,'RA_bH_std'] = em
    results.loc[:,'RA_bH_n'] = em
    results.loc[:,'RA_rsH_me'] = em
    results.loc[:,'RA_rsL_me'] = em
    
else:
    results = gpd.read_file(out_path + 'results.shp')


#%% 
#watershed_names = ['AP_6948360', 'AP_6948120']
for i, j in points.iterrows():
    if i>=0:
        
        watershed_name = str(points.loc[i,'grdc_no'])
        print('working on catchment #' + str(i) + ', id=' + watershed_name)
        x = points.loc[i,'X']
        y = points.loc[i,'Y']
        
        t = time.time()
        stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
        simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
        
        types_obs = ['EcrRiv_c_tr_alps_pyr'] # list of shapefile name layers for clip hydrology
        fields_obs = ['STRAHLER'] # list of shapefile name columns to translate as a tif
        
        #############################
        ######## GENERATING WATERSHED
        load = True
        BV = watershed_root.Watershed(watershed_name=watershed_name,
                                      dem_path=dem_path, 
                                      out_path=out_path,
                                      modflow_path=modflow_path,
                                      library_path=library_path,
                                      load=load,
                                      regio_out=True, from_xy=[x,y,250,1])
        
        BV.add_hydrology(hydrology_path, types_obs=types_obs, fields_obs=fields_obs)
        # watershed_display.watershed_dem(BV)
        # watershed_display.watershed_local(dem_path, BV)
    
        #############################
        ######## CLIMATE 
        print('##')
        print('I analyse the climate data')
        #% Extract climate data from ERA5 netcdf file
        # inspired from http://www.matteodefelice.name/post/aggregating-gridded-data/
        # for names of variables https://collections.eurodatacube.com/reanalysis-era5-land-monthly-means/readme.html
        
        # read the shapefile
        bnd = gpd.read_file(BV.geographic.watershed_contour_shp)#reading basin shapefile with geopandas
        bnd = bnd.set_crs('epsg:3035')
        bnd = bnd.to_crs(epsg = 4326)
        bnd.head()
        
        # Read NetCDF
        d = xr.open_dataset(ERA5_folder + ERA5_filename, chunks = {'time': 10})
        d = d.assign_coords(longitude=(((d.longitude + 180) % 360) - 180)).sortby('longitude')
        
        array_to_clip = d.rio.write_grid_mapping(inplace=True)
        array_to_clip = array_to_clip.rio.write_crs("epsg:4326", inplace=True)
        d_clipped = array_to_clip.rio.clip(bnd.geometry)
        
        d_mean = xr.DataArray.mean(d_clipped, dim={'latitude', 'longitude'}) #Mean calculation for all the variables of db over the basin
        
        # plt.figure(figsize=(12,8))
        # ax = plt.axes()
        # d_mean.t2m.plot(ax = ax)
        
        t2m = d_mean.t2m - 273.15 #2m temperature in degreeC
        results.loc[i,'t2m_me'] = np.nanmean(t2m)
        results.loc[i,'t2m_std'] = np.nanstd(t2m)
        # results.loc[i,'t2m_mi'] = np.nanmin(t2m)
        # results.loc[i,'t2m_ma'] = np.nanmax(t2m)
        
        tp = d_mean.tp #	Total precipitation m
        results.loc[i,'tp_me'] = np.nanmean(tp)
        results.loc[i,'tp_std'] = np.nanstd(tp)
        # results.loc[i,'tp_mi'] = np.nanmin(tp)
        # results.loc[i,'tp_ma'] = np.nanmax(tp)
        
        sde = d_mean.sde # 	Snow depth water equivalent in m of water equivalent
        results.loc[i,'sde_me'] = np.nanmean(sde)
        results.loc[i,'sde_std'] = np.nanstd(sde)
        # results.loc[i,'sde_mi'] = np.nanmin(sde)
        # results.loc[i,'sde_ma'] = np.nanmax(sde)
        
        snowc = d_mean.snowc #Snow cover	in %
        results.loc[i,'snowc_me'] = np.nanmean(snowc)
        results.loc[i,'snowc_std'] = np.nanstd(snowc)
        # results.loc[i,'snowc_mi'] = np.nanmin(snowc)
        # results.loc[i,'snowc_ma'] = np.nanmax(snowc)
        
        e = d_mean.e #evaporation in m of water equivalent
        results.loc[i,'e_me'] = np.nanmean(e)
        results.loc[i,'e_std'] = np.nanstd(e)
        # results.loc[i,'e_mi'] = np.nanmin(e)
        # results.loc[i,'e_ma'] = np.nanmax(e)
        
        ep = tp - e
        results.loc[i,'ep_me'] = np.nanmean(ep)
        results.loc[i,'ep_std'] = np.nanstd(ep)
        
        
        
        
        #############################
        ######## GEOMORPHOLOGY
        dem_to_analyze = BV.geographic.watershed_dem
        watershed_polyg = gpd.read_file(BV.geographic.watershed_shp)
        
        #AREA
        results.loc[i,'area_comp'] = watershed_polyg.geometry.area[0]
        
        if watershed_polyg.geometry.area[0] > 0.5e6:
            
            print('area greater that 0.5km^2')
            print('I continue')
        
            #ELEVATION
            print('##')
            print('I analyse the topography')
            dem = imageio.imread(dem_to_analyze)
            dem[dem<0] = np.nan
            results.loc[i,'elev_me'] = np.nanmean(dem)
            results.loc[i,'elev_std'] = np.nanstd(dem)
            # results.loc[i,'elev_mi'] = np.nanmin(imageio.imread(dem_to_analyze))
            # results.loc[i,'elev_ma'] = np.nanmax(imageio.imread(dem_to_analyze))
            
            #SLOPE
            out_slope = stable_folder+'geographic/'+'watershed_slope.tif'
            wbt.slope(dem_to_analyze, out_slope, zfactor=None, units="degrees")
            slope = imageio.imread(out_slope)
            slope[slope<0] = np.nan
            results.loc[i,'slope_me'] = np.nanmean(slope)
            results.loc[i,'slope_std'] = np.nanstd(slope)
            # results.loc[i,'slope_mi'] = np.nanmin(slope)
            # results.loc[i,'slope_ma'] = np.nanmax(slope)
            
            #RUGGEDNESS INDEX
            out_rug = stable_folder+'geographic/'+'watershed_ruggedness.tif'
            wbt.ruggedness_index(dem_to_analyze, out_rug)
            rug = imageio.imread(out_rug)
            rug[rug<0] = np.nan
            results.loc[i,'rug_me'] = np.nanmean(rug)
            results.loc[i,'rug_std'] = np.nanstd(rug)
            # results.loc[i,'rug_mi'] = np.nanmin(rug)
            # results.loc[i,'rug_ma'] = np.nanmax(rug)
            
            #HYPSOMETRIC CURVE
            out_hypsometric = stable_folder+'geographic/'+'out_hypsometric.html'
            wbt.hypsometric_analysis(
                dem_to_analyze, 
                out_hypsometric, 
                watershed=None)
            
            #WETNESS INDEX
            fill_path = stable_folder + 'geographic/' + 'watershed_fill.tif'
            d8_path = stable_folder+'geographic/'+'watershed_d8.tif'
            out_slope_fill = stable_folder+'geographic/'+'watershed_fill_slope.tif'
            wbt.slope(fill_path, out_slope_fill, zfactor=None, units="degrees")
            wbt.d8_flow_accumulation(fill_path, d8_path, 
                                        out_type="cells", log=False, clip=False, pntr=False, esri_pntr=False)
            
            wti_path = stable_folder + 'geographic/' + 'watershed_wti.tif'
            
            wbt.wetness_index(d8_path, out_slope_fill, wti_path)
            
            if path.exists(wti_path)==True:
                wti = imageio.imread(wti_path)
                wti[wti<-1000] = np.nan
                # import visvis as vv
                # im = vv.imshow(wti, clim=(-10,20))
                # im.colormap = vv.CM_JET
                # vv.colorbar()

                results.loc[i,'wti_me'] = np.nanmean(wti)
                results.loc[i,'wti_std'] = np.nanstd(wti)
            else:
                print('')
                print('!! arrff wbt.wetness_index function did not converged !!')
                print('')
            
            #break
            #close the windows open by hypsometric function    
            TARGET = "explorer.exe"
            [process.kill() for process in psutil.process_iter() if process.name() == TARGET]

            #############################
            ######## DAMS
            print('##')
            print('I check if there are dams')
            dam_pts = gpd.read_file(data_path+'dams/GOODD_data(ScientificData)/data/'+'GOOD2_dams_clipEU.shp')
            watershed_poly = gpd.read_file(stable_folder+'geographic/'+'watershed.shp')
            
            dams_selected = gpd.clip(dam_pts,watershed_poly)
            results.loc[i,'dams_num'] = len(dams_selected)
            
            
            #############################
            ######## STREAM NETWORK  
            #Compute stream length from flow accumulation
            print('##')
            print('I analyse the stream network')
            accumulation_clip = stable_folder+'geographic/'+'watershed_acc.tif'
            path_regional_acc = out_path + '_regional/region_acc.tif';
            wbt.clip_raster_to_polygon(path_regional_acc, 
                                       stable_folder+'geographic/'+'watershed.shp', 
                                       accumulation_clip, 
                                       maintain_dimensions=False)
            
            watershed_stream_path = stable_folder+'geographic/'+'watershed_stream.tif'
            wbt.extract_streams(accumulation_clip, 
                                watershed_stream_path, 
                                6, 
                                zero_background=True) # increase = number of rivers
            
            streams = imageio.imread(watershed_stream_path)
            streams[streams<0] = np.nan
            
            watershed_stream_link_identifier_path = stable_folder+'geographic/'+'watershed_stream_link_identifier.tif'
            wbt.stream_link_identifier(stable_folder+'geographic/'+'watershed_direc.tif',
                                    watershed_stream_path,
                                    watershed_stream_link_identifier_path,
                                    zero_background=True)
            s_id = imageio.imread(watershed_stream_link_identifier_path)

            watershed_stream_link_length_path = stable_folder+'geographic/'+'watershed_stream_link_length.tif'
            wbt.stream_link_length(stable_folder+'geographic/'+'watershed_direc.tif',
                                    watershed_stream_link_identifier_path, 
                                    watershed_stream_link_length_path,
                                    zero_background=True)
            s_id_length = imageio.imread(watershed_stream_link_length_path)
            s_id2 = s_id[s_id>0]
            s_id_length2 = s_id_length[s_id>0]
            
            unique_s_id2, id_unique_s_id2 = np.unique(s_id2, return_index=True)
            stream_length = sum(s_id_length2[id_unique_s_id2])
            results.loc[i,'stream_length'] = stream_length

            
            if path.exists(stable_folder + 'hydrology/EcrRiv_c_tr_alps_pyr.shp')==True:
                streams_db = gpd.read_file(stable_folder + 'hydrology/EcrRiv_c_tr_alps_pyr.shp')
                results.loc[i,'stream_length_db'] = np.sum(streams_db.geometry.length)
            else:
                print('!!')
                print('arrff I cannot find the stream .shp file')
                print('!!')
            
            #Compute the map of distance to nearest stream
            # geomorphons_path = stable_folder + 'geographic/' + 'watershed_geomorphons.tif'
            dist_path = stable_folder + 'geographic/' + 'watershed_distance_to_stream.tif'

            
            # wbt.geomorphons(
            #     fill_path, 
            #     geomorphons_path, 
            #     search=100, 
            #     threshold=2, 
            #     forms=True)
            
            wbt.downslope_distance_to_stream(fill_path, watershed_stream_path, dist_path)
            dist_to_stream = imageio.imread(dist_path)
            dist_to_stream[dist_to_stream<0] = np.nan
            results.loc[i,'dist_to_stream_me'] = np.nanmean(dist_to_stream)
            
            
            #############################
            ######## GEOLOGY
            print('##')
            print('I analyse the geology')
            geol_path = os.path.join(stable_folder,'geology/')
            toolbox.create_folder(geol_path)
            
            # Extract percent of lithology cover
            wbt.clip(data_path+'geology/'+'LiMW_GIS_clip_alps_pyr.shp',
                     stable_folder+'geographic/'+'watershed.shp',
                     stable_folder+'geology/watershed_geology.shp')
            geol=gpd.read_file(stable_folder+'/geology/watershed_geology.shp')
            geol = geol[['xx', 'geometry']]
            geol = geol.dissolve(by='xx')
            geol['area'] = geol['geometry'].area
            geol = geol.sort_values(by=['area'])
            
            for index, row in geol.iterrows():
                results.loc[i,str(index)] = row['area']/watershed_polyg.geometry.area[0]*100
                
            # Extract depth to bedrock stat
            bdticm_path = data_path + 'geology/' + 'BDTICM_M_1km_II_clip.tif'
            wbt.clip_raster_to_polygon(bdticm_path, stable_folder+'geographic/'+'watershed.shp', 
                                       stable_folder +'geology/'+'watershed_bdticm.tif', maintain_dimensions=False)
            
            bdticm = imageio.imread(stable_folder+'geology/'+'watershed_bdticm.tif')
            bdticm = bdticm.astype(float)
            bdticm[bdticm<0] = np.nan
            
            results.loc[i,'bdticm_me'] = (np.nanmean(bdticm)).astype(int)/100
            results.loc[i,'bdticm_std'] = (np.nanstd(bdticm)).astype(int)/100
            # results.loc[i,'bdticm_mi'] = (np.nanmin(bdticm)).astype(int)/100
            # results.loc[i,'bdticm_ma'] = (np.nanmax(bdticm)).astype(int)/100
        
            
            #############################
            ######## GHLYMPS
            #Extract mean hydraulic conductivity from ghlymps
            dempath = stable_folder+'geographic/'+'watershed_dem.tif'
            gl_shp = data_path + 'geology/GLHYMPS_selected_alps_pyr.shp'
            gl_clip_shp = stable_folder+'geology/'+'ghlymps.shp'
            
            wbt.clip(gl_shp, stable_folder+'geographic/'+'watershed.shp', gl_clip_shp)
        
            #POROSITY
            glpor_clip_tif = stable_folder+'geology/'+'gleeson_n.tif'
            wbt.vector_polygons_to_raster(gl_clip_shp, glpor_clip_tif, field="Porosity_x", 
                                          nodata=True, cell_size=None,base=dempath)
            
            if path.exists(glpor_clip_tif)==True:
                por = imageio.imread(glpor_clip_tif)
                por[por<0] = np.nan
                results.loc[i,'glh_n_me'] = np.nanmean(por)
                results.loc[i,'glh_n_std'] = np.nanstd(por)
        
            glkwp_clip_tif = stable_folder+'geology/'+'gleeson_kwp.tif'
            wbt.vector_polygons_to_raster(gl_clip_shp, glkwp_clip_tif, field="logK_Ice_x", 
                                          nodata=True, cell_size=None,base=dempath)
            if path.exists(glkwp_clip_tif)==True:
                kwp = imageio.imread(glkwp_clip_tif)
                kwp[kwp<=-2000] = np.nan
                results.loc[i,'glh_k_me'] = np.nanmean(kwp)
                results.loc[i,'glh_k_std'] = np.nanstd(kwp)
            
            glkstd_clip_tif = stable_folder+'geology/'+'gleeson_kstd.tif'
            wbt.vector_polygons_to_raster(gl_clip_shp, glkstd_clip_tif, field="K_stdev_x1", 
                                          nodata=True, cell_size=None,base=dempath)
            
            if path.exists(glkstd_clip_tif)==True:
                kstd = imageio.imread(glkstd_clip_tif)
                kstd[kstd<0] = np.nan
                results.loc[i,'glh_kstd_me'] = np.nanmean(kstd)
                results.loc[i,'glh_kstd_std'] = np.nanstd(kstd)
                
                
            #############################
            ######## Recession analysis
            #Compute recession coefficients
            
            os.chdir(DIR + "/examples/roques")
            print('##')
            print('I finally do the recession analysis')
            
            from RoquesRecession import RoquesRecession
            import warnings
            warnings.filterwarnings('ignore')

            #  df_obs = pd.read_csv('~/PycharmProjects/fhysa/roquesTestwithnan.csv')
            path_to_discharge = data_path + 'hydrometry/grdc/Alps_pyr/2022-03-09_10-56/' + watershed_name + '_Q_Day.Cmd.txt'
            if path.exists(path_to_discharge)==True:
            
                df_obs = pd.read_csv(path_to_discharge, skiprows = np.arange(36), sep=";", encoding= 'unicode_escape', usecols = [0, 2])
                df_obs.columns = ["t", "q"]
                datetimes = pd.to_datetime(df_obs.t, infer_datetime_format=True)  
                df_obs['Datetime'] = datetimes
                            
                # t = df_obs['Unnamed: 0']
                # q = df_obs.q
                # datetime = df_obs.Datetime
                RR = RoquesRecession(df_obs)
                date_event, d_all, date_H, d_H, aH, bH, rsH, date_L, d_L, aL, bL, ts, rsL = RR.recession_extraction_roques_methods(df_obs, column_names=('Datetime', 'q')
                                                                                        , min_recession_time=5, t_overland=1)
                
              
                df_results_RA = pd.DataFrame([date_event, d_all, date_H, d_H, aH, bH, rsH, date_L, d_L, aL, bL, ts, rsL])
                df_results_RA = df_results_RA.T
                df_results_RA = df_results_RA.rename(columns={0: "date_event", 
                                                              1: "d_all", 
                                                              2: "date_H", 
                                                              3: "d_H", 
                                                              4: "aH", 
                                                              5: "bH", 
                                                              6: "rsH", 
                                                              7: "date_L", 
                                                              8: "d_L", 
                                                              9: "aL",
                                                              10: "bL",
                                                              11: "ts",
                                                              12: "rsL"})
                

                save_RA_file = stable_folder + 'results_RA.csv'
                df_results_RA.to_csv(save_RA_file)
                
                ft1 = d_H>3
                ft2 = rsH>0.5
                ftH = ft1*ft2
                
                ft3 = d_L>3
                ft4 = rsL>0.5
                ftL = ft3*ft4

                results.loc[i,'RA_ts_me'] = np.nanmean(ts[ftL])
                results.loc[i,'RA_ts_std'] = np.nanstd(ts[ftL])
                results.loc[i,'RA_ts_n'] = ftL.sum()
   
                results.loc[i,'RA_bL_me'] = np.nanmean(bL[ftL])
                results.loc[i,'RA_bL_std'] = np.nanstd(bL[ftL])
                results.loc[i,'RA_bL_n'] = ftL.sum()
                
                results.loc[i,'RA_bH_me'] = np.nanmean(bH[ftH])
                results.loc[i,'RA_bH_std'] = np.nanstd(bH[ftH])
                results.loc[i,'RA_bH_n'] = ftH.sum()
                
                results.loc[i,'RA_rsH_me'] = np.nanmean(rsH[ftH])
                results.loc[i,'RA_rsL_me'] = np.nanmean(rsL[ftL])
                
                
            
            
            elapsed = time.time() - t
            
            
            
            print('##')
            print('I worked during ' + str(int(elapsed/60)) + ' min')
            print('')
            print('################### NEXT ###################')
            
            
            results.to_file(out_path + 'results.shp')
            np.save(out_path + 'results.npy', results)










