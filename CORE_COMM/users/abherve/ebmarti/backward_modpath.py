# -*- coding: utf-8 -*-
"""
Created on Mon Sep 26 14:31:36 2022

@author: emarti
"""

import os
import sys
import flopy
import flopy.utils.binaryfile as fpu
import numpy as np
from os.path import dirname, abspath
import matplotlib.pyplot as plt
import pandas as pd
import rioxarray as rxr
import geopandas as gpd

from matplotlib import colors
from matplotlib.colors import ListedColormap
from matplotlib.ticker import FormatStrFormatter
from matplotlib import ticker, cm
from matplotlib.colors import LightSource
from mpl_toolkits.axes_grid1 import make_axes_locatable

#%%

study_cuenca = 'Tarapaca'
dempath = 'D:/emarti/Tarapaca/out/' + study_cuenca + '/results_stable/geographic/watershed_dem.tif'
basin_dem = rxr.open_rasterio(dempath, masked=False).squeeze()

dempath_box = 'D:/emarti/Tarapaca/out/' + study_cuenca + '/results_stable/geographic/watershed_box_buff_dem.tif'
shp_mask = 'D:/emarti/Tarapaca/out/' + study_cuenca + '/results_stable/geographic/watershed.shp'
cuenca = gpd.read_file(shp_mask)
dem_box_full =  rxr.open_rasterio(dempath_box, masked=True).squeeze()
dem_box = dem_box_full[0:-1,1:-1]
dem_total_np = dem_box.to_numpy()
dem_box_head = dem_box_full[0:-1,0:-1]
extent = dem_box.x.min(), dem_box.x.max(), dem_box.y.min(), dem_box.y.max()
#altitud Level lines
x_1 = dem_box_head.x
y_1 = dem_box_head.y
xx_1, yy_1 = np.meshgrid(x_1,y_1)
dx = float(dem_box.x[2] - dem_box.x[1])
dy = float(dem_box.y[1] - dem_box.y[2])

#%%Define model parameters

recharge = 1e-4  #m/j
defKR = [1.0]
#defKR = np.concatenate((np.logspace(-3,-1,3), np.linspace(0.2,1,5), np.linspace(2,10,3), np.logspace(1.5, 2.5,5)), axis=None)
deflaynb = [3]
defbc = [1825]
elapsed = []
box=True
bottom=-1000
porosity = 0.01
k= 1e-7 * 86400


inj_row = 249 #intended row-1 for python indexing
inj_col = 299


for lay_nb in deflaynb:
    for bc_left in defbc:
        for KR in defKR:  
            KR_name = round(KR, 3)
            R = round(k / KR_name, 7)
            save_path_backward = 'D:/emarti/Tarapaca/out/figures/fixed_k/'+study_cuenca+'/backward/layers_nb_' + str(lay_nb) +'/bchead_'+str(bc_left)+'/ij_'+str(inj_row+1)+'_'+str(inj_col+1)+'/'
            modeldir = 'D:/emarti/Tarapaca/out/fixed_k/Tarapaca/results_simulations/KR_' + str(KR_name) + '_layers_nb_' + str(lay_nb) + '_bchead_'+str(bc_left)+'m_bottom_' + str(bottom) +'/'
            print('Performing simulation for model : KR = ' +str(KR_name)+' layer_nb='+str(lay_nb)+' bc='+str(bc_left))
            namepath      = 'KR_' + str(KR_name) + '_layers_nb_' + str(lay_nb) + '_bchead_'+str(bc_left)+'m_bottom_' + str(bottom)
            
            porosity = 0.01
            full_path = modeldir
            bin_folder = 'D:/emarti/Tarapaca/data/MODFLOW/bin/'
            exe= bin_folder + 'mp6.exe'
            
            
            nam_file = '{}.nam'.format(modeldir + namepath)
            dis_file = '{}.dis'.format(modeldir + namepath)
            head_file = '{}.hds'.format(modeldir + namepath)
            bud_file = '{}.cbc'.format(modeldir + namepath)
            bas_file = '{}.bas'.format(modeldir + namepath)
            lpf_file = '{}.upw'.format(modeldir + namepath)
            
            
            #dcol          = np.unique(mydis.delc)[0]
            #drow          = np.unique(mydis.delr)[0]
            mf = flopy.modflow.Modflow.load(nam_file,model_ws=full_path, version='mfnwt', verbose=False, check=False)
            bas = flopy.modflow.ModflowBas.load(bas_file, mf)
            mydis= mf.get_package('DIS')
            lpf = flopy.modflow.ModflowUpw.load(lpf_file, mf, check=False)
            nlay = mf.nlay
            ncol = mf.ncol
            nrow = mf.nrow
            btm = mydis.botm[nlay-1,0,0]
            top = mydis.top[0,0]
            depth = top - btm
            dcol = mydis.delc[0]
            drow = mydis.delr[0]
            delv = (top - btm) / nlay
            iboundData = bas.ibound.array
            
            hdsfile = flopy.utils.HeadFile(head_file)
            hds = hdsfile.get_data(kstpkper=(0, 0))




            #%%
                                  
            mp = flopy.modpath.Modpath6(modelname=mf.name + '_backward',model_ws=full_path, simfile_ext='mpsim', namefile_ext='mpnam', version='modpath',
                                        exe_name=exe, modflowmodel=mf, head_file=head_file, dis_file=dis_file, 
                                        dis_unit=87, budget_file=bud_file)
            
            flopy.modpath.Modpath6Sim(model=mp, option_flags=[2, 2, 1, 1, 1, 2, 2, 1, 1, 1, 1, 1])
            
            
            stl = flopy.modpath.mp6sim.StartingLocationsFile(model=mp, inputstyle=1)
            
            ptnb = 2000 ##number of particle injected
            stldata = stl.get_empty_starting_locations_data(npt=ptnb)
            
            for pt in range(0,ptnb):
                stldata[pt]['label'] = 'p' + str(pt) + '-0-0'
                stldata[pt]['i0'] = inj_row ###Row that we want
                stldata[pt]['j0'] = inj_col ###Column
                if pt < ptnb/2 :
                    stldata[pt]['k0'] = 1
                    stldata[pt]['zloc0'] = (pt/(ptnb/2))*1
                else:
                    stldata[pt]['k0'] = 2
                    stldata[pt]['zloc0'] = ((pt-(ptnb/2))/(ptnb/2))*1
                    
            stl.data = stldata
            
            mpb = flopy.modpath.Modpath6Bas(
                mp, hdry=lpf.hdry, laytyp=lpf.laytyp.array, ibound=iboundData, prsity=porosity
            )
            
            mp.write_input()
            
            mp.run_model(silent=False)
    

            #%%
            
            
            data = pd.read_csv(modeldir + namepath + '_backward.mppth', delim_whitespace=True, header=None, skiprows=3, engine='python')
            data.columns =['ParticleID',	'ParticleGroup'	,'Time_Point_Index',	'Cumulative_Time_Step',	'Tracking_Time'	,'Global_X','Global_Y','Global_Z','	Layer','Row','Column','Grid','Local_X','Local_Y','Local_Z','Line_segment_Index']
            
            
            data_end = pd.read_csv(modeldir + namepath + '_backward.mpend', delim_whitespace=True, header=None, skiprows=6, engine='python')
            data_end.columns =['ParticleID',	'ParticleGroup',	'Status',	'Initial_Time',	'Final_time',	'Initial_Grid',	'Initial_Layer',	'Initial_Row',	'Initial_Column',	'Initial_Cell_Face',	'Initial_Zone',	'Initial_local_X',	'Initial_local_Y',	'Initial_local_Z',	'Initial_global_X',	'Initial_global_Y',	'Initial_global_Z',	'Final_grid',	'Final_Layer',	'Final_Row',	'Final_Column',	'Final_Cell_Face',	'Final_Zone',	'Final_local_X',	'Final_local_Y',	'Final_local_Z',	'Final_global_X',	'Final_global_Y',	'Final_global_Z',	'Label']
            
            data_end= data_end[data_end['Final_time'] != 0]
            
            final_position = []
            
            for i in data_end['ParticleID']:
            #for i in range(1,max(data['ParticleID'])+1):
                df = data[data['ParticleID'] == i]
                #print(df)
                #X = df.iloc[-1]['Global_X']
                #Y = df.iloc[-1]['Global_Y']
                row = int(df.iloc[-1]['Row'])
                col = int(df.iloc[-1]['Column'])
                X_UTM = float(dem_box_full[row,col].x)
                Y_UTM = float(dem_box_full[row,col].y)
                final_position.append([row, col, X_UTM, Y_UTM])
                
            
            final_df = pd.DataFrame(final_position,columns=['row', 'col', 'X_UTM', 'Y_UTM'])





            #%%
            
            fig , ax2 = plt.subplots(figsize=(16,9))
            #plot DEM with hillshade and cmap 
            ls = LightSource(azdeg=315, altdeg=45)
            ax2.imshow(ls.hillshade(dem_total_np, vert_exag=1, dx=dx, dy=dy), cmap='gray', extent=extent) 
            cuenca.plot(color='None', edgecolor='red',linewidths=1.5, ax=ax2)
            ax2.scatter(final_df['X_UTM'], final_df['Y_UTM'])
            ax2.scatter(dem_box_full[inj_row+1,inj_col+1].x, dem_box_full[inj_row+1,inj_col+1].y, color='red')
            #Title and axis
            plt.gca().yaxis.set_major_formatter(FormatStrFormatter('%d'))
            plt.xlabel('Easting (m)')
            plt.ylabel('Northing (m)')
            plt.title('Backward particle (n='+str(ptnb)+') tracking, row='+ str(inj_row+1)+'col='+ str(inj_col+1) + 'KR=' + str(KR_name))
            file = 'bw_pt_track_n='+str(ptnb)+'_KR_'+ str(KR_name) + '_i_'+ str(inj_row+1)+'_j_'+ str(inj_col+1) +'.png'
            if not os.path.isdir(save_path_backward):
                os.makedirs(save_path_backward)
            fig.savefig(os.path.join(save_path_backward, file))
            #plt.show()
            plt.gcf().clf()






#%%


# First step is to set up the plot
fig = plt.figure(figsize=(15, 5))
ax = fig.add_subplot(1, 1, 1)

# Next we create an instance of the PlotCrossSection class
xsect = flopy.plot.PlotCrossSection(model=mf, line={"Row": 250})
#patches = xsect.plot_ibound()
#contour_set = xsect.contour_array(hds)
# Then we can use the plot_grid() method to draw the grid
# The return value for this function is a matplotlib LineCollection object,
# which could be manipulated (or used) later if necessary.
linecollection = xsect.plot_grid()
#cb = plt.colorbar(contour_set, shrink=0.75)
plt.ylim((-1000, 6000))
t = ax.set_title("Row 250 Cross-Section - Model Grid")