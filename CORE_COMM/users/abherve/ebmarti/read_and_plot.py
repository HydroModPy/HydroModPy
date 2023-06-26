# -*- coding: utf-8 -*-
"""
Created on Wed Mar 30 12:31:22 2022

@author: Etienne Marti
"""
import os
import pandas as pd 
import numpy as np
import geopandas as gpd
import rasterio
import xarray as xr
import rioxarray as rxr
import matplotlib.pyplot as plt
from matplotlib import colors
from matplotlib.colors import ListedColormap
from matplotlib.ticker import FormatStrFormatter
from matplotlib import ticker, cm
from matplotlib.colors import LightSource
from mpl_toolkits.axes_grid1 import make_axes_locatable
import flopy.utils.mflistfile as mflf
#%%



dempath = 'D:/emarti/Tarapaca/out/Tarapaca/results_stable/geographic/watershed_dem.tif'

study_cuenca = 'Tarapaca'




if study_cuenca == 'Tarapaca':
    shp_mask = 'D:/emarti/Tarapaca/out/' + study_cuenca + '/results_stable/geographic/watershed.shp'
    
else:
    shp_mask = 'D:/emarti/Tarapaca/subbasins/' + study_cuenca + '/watershed.shp'
    
    
river_red_shp = 'D:/emarti/Tarapaca/data/hydrology/streams.shp'
river_red_tif = 'D:/emarti/Tarapaca/data/hydrology/streams_raster.tif'


dem_cuenca_total =  rxr.open_rasterio(dempath, masked=True).squeeze()
dx = float(dem_cuenca_total.x[2] - dem_cuenca_total.x[1])
dy = float(dem_cuenca_total.y[1] - dem_cuenca_total.y[2])
dem_total_np = dem_cuenca_total.to_numpy()
x_1 = dem_cuenca_total.x
y_1 = dem_cuenca_total.y

river_tif =  rxr.open_rasterio(river_red_tif, masked=True).squeeze()

extent = dem_cuenca_total.x.min(), dem_cuenca_total.x.max(), dem_cuenca_total.y.min(), dem_cuenca_total.y.max()
Tarapaca = 'D:/emarti/Tarapaca/out/Tarapaca/results_stable/geographic/watershed.shp'
#Import shapefile
cuenca = gpd.read_file(shp_mask)
cuenca_1 = gpd.read_file(Tarapaca)

river_cuenca =gpd.read_file(river_red_shp)
#river_cuenca = river_red.clip(cuenca)
L_river = np.sum(river_cuenca.length)

dem_cuenca_clipped = dem_cuenca_total.rio.clip(cuenca.geometry, drop=False)
dem_cuenca_clipped_np = dem_cuenca_clipped.to_numpy()     
area = float(cuenca.area)


red_area_norm = float(river_tif.where(river_tif==1, drop=True).count())*dx*dy/area






#%%Define model parameters

#defKR = np.concatenate((np.logspace(-3,-1,3), np.linspace(0.2,1,5), np.linspace(2,10,3), np.logspace(1.5, 2.5,5)), axis=None)
defKR = np.logspace(-2,2,25)
#defKR = [1/0.01]

k= 1e-7 * 86400 # m/s en m/j
#BV.hydrodynamic.update_hyd_cond(k) 
#recharge = 1e-7  #m/j
#BV.forcing.update_recharge(recharge, 'steady')
#defKR = np.logspace(-1,2,4)
#recharge = 1e-4 
thickness = 500
deflaynb = [10]
defbc = [1825]
box=True
bottom=-1000

#%%
results_pdf = []
label = []
MBR_MFR = []




for lay_nb in deflaynb:
    for bc_left in defbc:
        for KR in defKR:   
            KR_name = round(KR,3)
            recharge = round(k / KR_name, 7)
            save_path_sflows = 'D:/emarti/Tarapaca/out/figures/final/'+study_cuenca+'/3zones_sflows/layers_nb_' + str(lay_nb) +'/bchead_'+str(bc_left)+'/'
            save_path_wt = 'D:/emarti/Tarapaca/out/figures/final/'+study_cuenca+'/wt/layers_nb_' + str(lay_nb) +'/bchead_'+str(bc_left)+'/'
            modeldir = 'D:/emarti/Tarapaca/out/final/'+study_cuenca+'/results_simulations/KR_' + str(KR_name) + '_layers_nb_' + str(lay_nb) + '_bchead_'+str(bc_left)+'m_bottom_' + str(bottom) +'/'
            #modeldir = 'D:/emarti/Tarapaca/out/'+study_cuenca+'/results_simulations/KR_' + str(KR_name) + '_layers_nb_' + str(lay_nb) + '_bchead_'+str(bc_left)+'m_thickness_' + str(thickness) +'/'
            namepath      = 'KR_' + str(KR_name) + '_layers_nb_' + str(lay_nb) +'_bchead_'+str(bc_left)+'m_bottom_' + str(bottom)
            #namepath      = 'KR_' + str(KR_name) + '_layers_nb_' + str(lay_nb) +'_bchead_'+str(bc_left)+'m_thickness_' + str(thickness)
            print(modeldir)
            print(study_cuenca)
            data = pd.read_csv(modeldir + 'surface_flows.txt', sep=' |\t', engine='python')
            data_2D = np.reshape(data['flow'].to_numpy(), (data['rowI'].max()+1,data['colJ'].max()+1))
            #data_2D_plot = data_2D[0:-1,1:-1] #delete borders with no recharge for representation
            data_2D_plot = data_2D/recharge
            #data_2D_plot_seepage = data_2D
            #data_2D_plot_seepage[data_2D_plot_seepage > 0] = np.nan
            #data_2D_plot_seepage = np.abs(data_2D_plot_seepage)
            m = np.ma.masked_where(np.isnan(dem_cuenca_clipped.data), dem_cuenca_clipped.data)
            data_2D_basin = np.ma.masked_where(np.ma.getmask(m), data_2D_plot)
            #data_2D_plot_seepage_basin = np.ma.masked_where(np.ma.getmask(m), data_2D_plot_seepage)
            data_2D_basin_masked = data_2D_basin[data_2D_basin.mask == False]
            #sflows_norm_2D = data_2D_basin_masked/recharge
            bins = [data_2D_basin_masked.min(), 0, 0.99, 1.1]
            hist, bins_ = np.histogram(data_2D_basin_masked, bins=bins)
            pdf = (hist/data_2D_basin_masked.size)
            results_pdf.append(pdf)

            
            data_head = pd.read_csv(modeldir + 'heads.txt', sep=' |\t', engine='python')
            data_head_2D = np.reshape(data_head['head_height'].to_numpy(), (data['rowI'].max()+1,data['colJ'].max()+1))
            #data_head_2D = data_head_2D[0:-1,0:-1] #delete borders with no recharge
            data_head_2D_basin = np.ma.masked_where(np.ma.getmask(m), data_head_2D)


            label.append([lay_nb, KR_name, bc_left])
            
            # mf_list = mflf.MfListBudget(modeldir+namepath+'.list')
            # incremental, cumulative = mf_list.get_budget(['TOTAL_OUT', 'CONSTANT_HEAD_OUT', 'DRAINS_OUT'])
            # MBR = cumulative['CONSTANT_HEAD_OUT'][0]
            # SMFR = cumulative['DRAINS_OUT'][0]
            # MFR = cumulative['TOTAL_OUT'][0]
            # MBR_MFR.append([MBR, SMFR, MFR])
            
            
            if os.path.exists(modeldir+'3zones_surface_flows_map.png'):
                os.remove(modeldir+'3zones_surface_flows_map.png')
            fig, ax1 = plt.subplots(figsize=(16,9))
            cmapmine = cm.jet
            #bounds=[data_2D_plot.min(), 0,  data_2D_plot.max()-0.00000001*data_2D_plot.max(), data_2D_plot.max()+0.000000001*data_2D_plot.max()]
            #bounds=[data_2D_plot.min(), 0, 0.99,  1.1]
            bounds=[data_2D_plot.min(), 0.99,  1.1] ### All is seepage
            norm = colors.BoundaryNorm(bounds, cmapmine.N)
            H = ax1.imshow(data_2D_basin, extent=extent, cmap='jet', norm=norm, interpolation='nearest')
            #cbar=plt.colorbar(H,format='%.2E')
            cbar=plt.colorbar(H)
            #cbar.set_ticklabels(['Seepage','R<Rpot','Rpot',''])
            cbar.set_ticklabels(['Seepage','Rpot','']) #SEEPAGE ONLY
            #cbar.ax.get_yaxis().set_ticks([])
            #for j, lab in enumerate(['Seepage','O>R>Rpot','R=Rpot']):
            #    cbar.ax.text(1.5, (2*j+1)/3, lab)
            #cbar.ax.get_yaxis().labelpad = 15
            #cbar.ax.set_ylabel('# of contacts', rotation=270)
            cuenca.plot(color='None', edgecolor='black',linewidths=3, ax=ax1)
            cuenca_1.plot(color='None', edgecolor='black',linewidths=3, ax=ax1)
            plt.gca().yaxis.set_major_formatter(FormatStrFormatter('%d'))
            plt.xlabel('Easting (m)')
            plt.ylabel('Northing (m)')
            #plt.title('Surface flows R/k='+str(round(1/KR_name,4)))
            plt.title('Seepage distribution R/k='+str(round(1/KR_name,4)))
            #plt.gcf().savefig(modeldir+"3zones_surface_flows_map.png", dpi=800, format='png')
            #file = 'sflows_Rk'+str(round(1/KR_name,4))+'rch'+str(recharge)+'.png'
            file = 'seepage_Rk'+str(round(1/KR_name,4))+'rch'+str(recharge)+'.png'
            if not os.path.isdir(save_path_sflows):
                os.makedirs(save_path_sflows)
            fig.savefig(os.path.join(save_path_sflows, file))
            plt.show()
            plt.gcf().clf()
            
            # if os.path.exists(modeldir+'seepage_flow_map.png'):
            #     os.remove(modeldir+'seepage_flow_map.png')
            # fig, ax1 = plt.subplots(figsize=(16,9))
            # ls = LightSource(azdeg=315, altdeg=45)
            # ax1.imshow(ls.hillshade(dem_total_np, vert_exag=1, dx=dx, dy=dy), cmap='gray', extent=extent)
            # H = ax1.imshow(np.log10(data_2D_plot_seepage_basin), extent=extent, interpolation='nearest')
            # cbar = plt.colorbar(H)
            # cbar.set_label('log(seepage)', loc='center')
            # cuenca.plot(color='None', edgecolor='red',linewidths=3, ax=ax1)
            # cuenca_1.plot(color='None', edgecolor='red',linewidths=3, ax=ax1)
            # plt.gca().yaxis.set_major_formatter(FormatStrFormatter('%d'))
            # plt.xlabel('Easting (m)')
            # plt.ylabel('Northing (m)')
            # plt.title('Surface flows K/R='+str(KR_name))
            # #plt.gcf().savefig(modeldir+"3zones_surface_flows_map.png", dpi=800, format='png')
            # file = 'seepage_flow_KR'+ str(KR_name)+'rch'+str(recharge)+'.png'
            # if not os.path.isdir(save_path_sflows):
            #     os.makedirs(save_path_sflows)
            # fig.savefig(os.path.join(save_path_sflows, file))
            # plt.show()
            # plt.gcf().clf()
            
            # fig , ax2 = plt.subplots(figsize=(16,9))
            # #plot DEM with hillshade and cmap 
            # ls = LightSource(azdeg=315, altdeg=45)
            # ax2.imshow(ls.hillshade(dem_total_np, vert_exag=1, dx=dx, dy=dy), cmap='gray', extent=extent)
            # ax2.imshow(dem_total_np, extent=extent, alpha=0.2, cmap='jet')
            # #plot the head contour lines
            # levels = np.arange(0, 6000, 250)
            # hc=ax2.contour(x_1, y_1, data_head_2D_basin, linewidths=0.9, levels=levels, colors='k')
            # ax2.clabel(hc, inline=True, fontsize=11, fmt='%1.0f') 
            # #Plot cuenca limits
            # cuenca.plot(color='None', edgecolor='red',linewidths=1.5, ax=ax2) 
            # #Title and axis
            # plt.gca().yaxis.set_major_formatter(FormatStrFormatter('%d'))
            # plt.xlabel('Easting (m)')
            # plt.ylabel('Northing (m)')
            # plt.title('Watertable elevation R/k='+str(round(1/KR_name,4)))
            # file_wt = 'wt_Rk'+str(round(1/KR_name,4))+'rch'+str(recharge)+'.png'
            # if not os.path.isdir(save_path_wt):
            #     os.makedirs(save_path_wt)
            # fig.savefig(os.path.join(save_path_wt, file_wt))
            # plt.show()
            # plt.gcf().clf()
   
#df_sflows = pd.DataFrame(results_pdf,columns=['Seepage','R<Rpot','Rpot'])
#final_df_sflows = df_sflows.join(pd.DataFrame(label,columns=['lay_nb','KR','bc_head']))

# df_MBR = pd.DataFrame(MBR_MFR, columns=['MBR','SMFR', 'MFR'])
# df_MBR['prop_MBR'] = (df_MBR['MBR']/df_MBR['MFR'])*100
# df_MBR['prop_SMFR'] = 100 - df_MBR['prop_MBR']
# final_df_MBR = df_MBR.join(pd.DataFrame(label,columns=['lay_nb','KR','bc_head']))

#%%

#df_lay1 = final_df_sflows[final_df_sflows['lay_nb'] == 1]
df_lay3 = final_df_sflows[final_df_sflows['lay_nb'] == 3]
#df_lay5 = final_df_sflows[final_df_sflows['lay_nb'] == 5]

#%%

fig, ax1 = plt.subplots(figsize=(16,9))
ax1.plot(1/final_df_sflows['KR'],final_df_sflows['Seepage'], 'o-',c='blue', label='Seepage')
ax1.plot(1/final_df_sflows['KR'],final_df_sflows['Rpot'], 'o-',c='red', label='R=Rpot')
ax1.plot(1/final_df_sflows['KR'],final_df_sflows['R<Rpot'], 'o-',c='green',label='0<R<Rpot')


#plt.axvline(x=5.88, color='k', linewidth=2)
#ax1.plot(df_final['true_hait_cst_exfil_2'],df_final['seep_area_exfil_norm'])
#ax1.set_yscale('log')
ax1.set_xscale('log')
plt.legend(loc='best')
plt.xlabel(r'$\frac{R}{k}$')
plt.ylabel('normalized surface flows')
plt.title('sflows/Rpot vs R/k=['+str(round(1/defKR.max(),4))+'-'+str(round(1/defKR.min(),3))+']')
plt.grid(visible=True, linewidth=0.25)
plt.rc('font', size=18)
plt.rc('legend', fontsize=14)




#%%

barWidth = 0.25
br1 = np.arange(len(df_lay3.iloc[0:4]))
br2 = [x + barWidth for x in br1]
br3 = [x + barWidth for x in br2]
#%%
fig, ax3= plt.subplots(figsize=(20, 10))

bc_1000 = [plt.bar(br1, df_lay1.iloc[0:15]['Seepage'], color='r', width= barWidth, edgecolor ='black', label='Seepage'),
                plt.bar(br1, df_lay1.iloc[0:15]['R<Rpot'], color='g',bottom=df_lay1.iloc[0:15]['Seepage'], width=barWidth, edgecolor ='black', label='R<Rpot'),
                plt.bar(br1, df_lay1.iloc[0:15]['Rpot'], color='b', bottom = df_lay1.iloc[0:15]['Seepage']+ df_lay1.iloc[0:15]['R<Rpot'], width=barWidth, label='Rpot')]
bc_1500 = [plt.bar(br2, df_lay1.iloc[15:30]['Seepage'], color='r', width= barWidth, edgecolor ='black'),
                plt.bar(br2, df_lay1.iloc[15:30]['R<Rpot'], color='g', bottom=df_lay1.iloc[15:30]['Seepage'], width=barWidth, edgecolor ='black'),
                plt.bar(br2, df_lay1.iloc[15:30]['Rpot'], color='b', bottom = df_lay1.iloc[15:30]['Seepage']+ df_lay1.iloc[15:30]['R<Rpot'], width=barWidth, edgecolor ='black')]
# bc_2000 = [plt.bar(br3, df_lay1.iloc[30:45]['Seepage'], color='r', width= barWidth, edgecolor ='black'),
#                 plt.bar(br3, df_lay1.iloc[30:45]['R<Rpot'], color='g', bottom=df_lay1.iloc[30:45]['Seepage'], width=barWidth, edgecolor ='black'),
#                 plt.bar(br3, df_lay1.iloc[30:45]['Rpot'], color='b',bottom = df_lay1.iloc[30:45]['Seepage']+ df_lay1.iloc[30:45]['R<Rpot'], width=barWidth, edgecolor ='black')]

plt.xticks([r + barWidth for r in range(len(df_lay1.iloc[0:15]))],
        df_lay1.iloc[0:15]['KR'])
plt.text(br1[0]-(barWidth/3), 5, 'bc head = 1000', fontsize=14, rotation='vertical')
plt.text(br2[0]-(barWidth/3), 5, '1500', fontsize=14, rotation='vertical')
#plt.text(br3[0]-(barWidth/3), 5, '2000', fontsize=14, rotation='vertical')
plt.grid()
plt.xlabel('KR')
plt.ylabel('Distribution of surface flows (%)')
plt.legend(loc='best', fontsize=14)
plt.title('1 layer')
ax3.set_yscale('log')

#%%
fig, ax4= plt.subplots(figsize=(20, 10))

bc_1000 = [plt.bar(br1, df_lay3.iloc[0:4]['Seepage'], color='r', width= barWidth, edgecolor ='black', label='Seepage'),
                plt.bar(br1, df_lay3.iloc[0:4]['R<Rpot'], color='g',bottom=df_lay3.iloc[0:4]['Seepage'], width=barWidth, edgecolor ='black', label='R<Rpot'),
                plt.bar(br1, df_lay3.iloc[0:4]['Rpot'], color='b', bottom = df_lay3.iloc[0:4]['Seepage']+ df_lay3.iloc[0:4]['R<Rpot'], width=barWidth, label='Rpot')]
# bc_300 = [plt.bar(br2, df_lay3.iloc[3:30]['Seepage'], color='r', width= barWidth, edgecolor ='black'),
#                 plt.bar(br2, df_lay3.iloc[3:30]['R<Rpot'], color='g', bottom=df_lay3.iloc[3:30]['Seepage'], width=barWidth, edgecolor ='black'),
#                 plt.bar(br2, df_lay3.iloc[3:30]['Rpot'], color='b', bottom = df_lay3.iloc[3:30]['Seepage']+ df_lay3.iloc[3:30]['R<Rpot'], width=barWidth, edgecolor ='black')]
# bc_2000 = [plt.bar(br3, df_lay3.iloc[30:45]['Seepage'], color='r', width= barWidth, edgecolor ='black'),
#                 plt.bar(br3, df_lay3.iloc[30:45]['R<Rpot'], color='g', bottom=df_lay3.iloc[30:45]['Seepage'], width=barWidth, edgecolor ='black'),
#                 plt.bar(br3, df_lay3.iloc[30:45]['Rpot'], color='b',bottom = df_lay3.iloc[30:45]['Seepage']+ df_lay3.iloc[30:45]['R<Rpot'], width=barWidth, edgecolor ='black')]

plt.xticks([r for r in range(len(df_lay3.iloc[0:4]))],
        df_lay3.iloc[0:4]['KR'])
# plt.text(br1[0]-(barWidth/3), 5, 'bc head = 1000', fontsize=14, rotation='vertical')
# plt.text(br2[0]-(barWidth/3), 5, '1500', fontsize=14, rotation='vertical')
#plt.text(br3[0]-(barWidth/3), 5, '2000', fontsize=14, rotation='vertical')
plt.grid()
plt.xlabel('K/R')
plt.ylabel('Distribution of surface flows (%)')
plt.legend(loc='best', fontsize=14)
plt.title('surface flows inside the basin - 3 layers - smaller total area')
#ax4.set_yscale('log')

#%%
fig, ax5= plt.subplots(figsize=(20, 10))

bc_1000 = [plt.bar(br1, df_lay5.iloc[0:15]['Seepage'], color='r', width= barWidth, edgecolor ='black', label='Seepage'),
                plt.bar(br1, df_lay5.iloc[0:15]['R<Rpot'], color='g',bottom=df_lay5.iloc[0:15]['Seepage'], width=barWidth, edgecolor ='black', label='R<Rpot'),
                plt.bar(br1, df_lay5.iloc[0:15]['Rpot'], color='b', bottom = df_lay5.iloc[0:15]['Seepage']+ df_lay5.iloc[0:15]['R<Rpot'], width=barWidth, label='Rpot')]
bc_1500 = [plt.bar(br2, df_lay5.iloc[15:30]['Seepage'], color='r', width= barWidth, edgecolor ='black'),
                plt.bar(br2, df_lay5.iloc[15:30]['R<Rpot'], color='g', bottom=df_lay5.iloc[15:30]['Seepage'], width=barWidth, edgecolor ='black'),
                plt.bar(br2, df_lay5.iloc[15:30]['Rpot'], color='b', bottom = df_lay5.iloc[15:30]['Seepage']+ df_lay5.iloc[15:30]['R<Rpot'], width=barWidth, edgecolor ='black')]
# bc_2000 = [plt.bar(br3, df_lay5.iloc[30:45]['Seepage'], color='r', width= barWidth, edgecolor ='black'),
#                 plt.bar(br3, df_lay5.iloc[30:45]['R<Rpot'], color='g', bottom=df_lay5.iloc[30:45]['Seepage'], width=barWidth, edgecolor ='black'),
#                 plt.bar(br3, df_lay5.iloc[30:45]['Rpot'], color='b',bottom = df_lay5.iloc[30:45]['Seepage']+ df_lay5.iloc[30:45]['R<Rpot'], width=barWidth, edgecolor ='black')]

plt.xticks([r + barWidth for r in range(len(df_lay1.iloc[0:15]))],
        df_lay1.iloc[0:15]['KR'])
plt.text(br1[0]-(barWidth/3), 5, 'bc head = 1000', fontsize=14, rotation='vertical')
plt.text(br2[0]-(barWidth/3), 5, '1500', fontsize=14, rotation='vertical')
#plt.text(br3[0]-(barWidth/3), 5, '2000', fontsize=14, rotation='vertical')
plt.grid()
plt.xlabel('KR')
plt.ylabel('Distribution of surface flows (%)')
plt.legend(loc='best', fontsize=14)
plt.title('5 layers')
#ax5.set_yscale('log')

#%%

df_MBR_lay1 = final_df_MBR[final_df_MBR['lay_nb'] == 1]
df_MBR_lay3 = final_df_MBR[final_df_MBR['lay_nb'] == 3]
df_MBR_lay5 = final_df_MBR[final_df_MBR['lay_nb'] == 5]


#%%


barWidth = 0.25
br1 = np.arange(len(df_MBR_lay1.iloc[0:15]))
br2 = [x + barWidth for x in br1]
br3 = [x + barWidth for x in br2]

#%%
fig, ax3= plt.subplots(figsize=(20, 10))

bc_1000 = [plt.bar(br1, df_MBR_lay1.iloc[0:15]['prop_MBR'], color='r', width= barWidth, edgecolor ='black', label='MBR'),
                plt.bar(br1, df_MBR_lay1.iloc[0:15]['prop_SMFR'], color='b',bottom=df_MBR_lay1.iloc[0:15]['prop_MBR'], width=barWidth, edgecolor ='black', label='SMFR')]
bc_1500 = [plt.bar(br2, df_MBR_lay1.iloc[15:30]['prop_MBR'], color='r', width= barWidth, edgecolor ='black'),
                plt.bar(br2, df_MBR_lay1.iloc[15:30]['prop_SMFR'], color='b', bottom=df_MBR_lay1.iloc[15:30]['prop_MBR'], width=barWidth, edgecolor ='black')]
# bc_2000 = [plt.bar(br3, df_MBR_lay1.iloc[30:45]['prop_MBR'], color='r', width= barWidth, edgecolor ='black'),
#                 plt.bar(br3, df_MBR_lay1.iloc[30:45]['prop_SMFR'], color='b', bottom=df_MBR_lay1.iloc[30:45]['prop_MBR'], width=barWidth, edgecolor ='black')]

plt.xticks([r + barWidth for r in range(len(df_MBR_lay1.iloc[0:15]))],
        df_MBR_lay1.iloc[0:15]['KR'])
plt.text(br1[0]-(barWidth/3), 5, 'bc head = 1000', fontsize=14, rotation='vertical')
plt.text(br2[0]-(barWidth/3), 5, '1500', fontsize=14, rotation='vertical')
#plt.text(br3[0]-(barWidth/3), 5, '2000', fontsize=14, rotation='vertical')
plt.grid()
plt.xlabel('KR')
plt.ylabel('Proportion of MBR vs SMFR(%)')
plt.legend(loc='best', fontsize=14)
plt.title('1 layer')
#ax3.set_yscale('log')

#%%
fig, ax3= plt.subplots(figsize=(20, 10))

bc_1000 = [plt.bar(br1, df_MBR_lay3.iloc[0:15]['prop_MBR'], color='r', width= barWidth, edgecolor ='black', label='MBR'),
                plt.bar(br1, df_MBR_lay3.iloc[0:15]['prop_SMFR'], color='b',bottom=df_MBR_lay3.iloc[0:15]['prop_MBR'], width=barWidth, edgecolor ='black', label='SMFR')]
bc_1500 = [plt.bar(br2, df_MBR_lay3.iloc[15:30]['prop_MBR'], color='r', width= barWidth, edgecolor ='black'),
                plt.bar(br2, df_MBR_lay3.iloc[15:30]['prop_SMFR'], color='b', bottom=df_MBR_lay3.iloc[15:30]['prop_MBR'], width=barWidth, edgecolor ='black')]
# bc_2000 = [plt.bar(br3, df_MBR_lay3.iloc[30:45]['prop_MBR'], color='r', width= barWidth, edgecolor ='black'),
#                 plt.bar(br3, df_MBR_lay3.iloc[30:45]['prop_SMFR'], color='b', bottom=df_MBR_lay3.iloc[30:45]['prop_MBR'], width=barWidth, edgecolor ='black')]

plt.xticks([r + barWidth for r in range(len(df_MBR_lay3.iloc[0:15]))],
        df_MBR_lay3.iloc[0:15]['KR'])
plt.text(br1[0]-(barWidth/3), 5, 'bc head = 1000', fontsize=14, rotation='vertical')
plt.text(br2[0]-(barWidth/3), 5, '1500', fontsize=14, rotation='vertical')
#plt.text(br3[0]-(barWidth/3), 5, '2000', fontsize=14, rotation='vertical')
plt.grid()
plt.xlabel('KR')
plt.ylabel('Proportion of MBR vs SMFR(%)')
plt.legend(loc='best', fontsize=14)
plt.title('3 layers')

#%%
fig, ax3= plt.subplots(figsize=(20, 10))

bc_1000 = [plt.bar(br1, df_MBR_lay5.iloc[0:15]['prop_MBR'], color='r', width= barWidth, edgecolor ='black', label='MBR'),
                plt.bar(br1, df_MBR_lay5.iloc[0:15]['prop_SMFR'], color='b',bottom=df_MBR_lay5.iloc[0:15]['prop_MBR'], width=barWidth, edgecolor ='black', label='SMFR')]
bc_1500 = [plt.bar(br2, df_MBR_lay5.iloc[15:30]['prop_MBR'], color='r', width= barWidth, edgecolor ='black'),
                plt.bar(br2, df_MBR_lay5.iloc[15:30]['prop_SMFR'], color='b', bottom=df_MBR_lay5.iloc[15:30]['prop_MBR'], width=barWidth, edgecolor ='black')]
# bc_2000 = [plt.bar(br3, df_MBR_lay5.iloc[30:45]['prop_MBR'], color='r', width= barWidth, edgecolor ='black'),
#                 plt.bar(br3, df_MBR_lay5.iloc[30:45]['prop_SMFR'], color='b', bottom=df_MBR_lay5.iloc[30:45]['prop_MBR'], width=barWidth, edgecolor ='black')]

plt.xticks([r + barWidth for r in range(len(df_MBR_lay5.iloc[0:15]))],
        df_MBR_lay5.iloc[0:15]['KR'])
plt.text(br1[0]-(barWidth/3), 5, 'bc head = 1000', fontsize=14, rotation='vertical')
plt.text(br2[0]-(barWidth/3), 5, '1500', fontsize=14, rotation='vertical')
plt.text(br3[0]-(barWidth/3), 5, '2000', fontsize=14, rotation='vertical')
plt.grid()
plt.xlabel('KR')
plt.ylabel('Proportion of MBR vs SMFR(%)')
plt.legend(loc='best', fontsize=14)
plt.title('5 layers')

#%%
import flopy
#%%


#defKR = np.concatenate((np.logspace(-3,-1,3), np.linspace(0.2,1,5), np.linspace(2,10,3), np.logspace(1.5, 2.5,5)), axis=None)
defKR = np.logspace(-2,2,25)
#defKR = [1/0.01]

k= 1e-7 * 86400 # m/s en m/j
#BV.hydrodynamic.update_hyd_cond(k) 
#recharge = 1e-7  #m/j
#BV.forcing.update_recharge(recharge, 'steady')
#defKR = np.logspace(-1,2,4)
#recharge = 1e-4 
thickness = 500
deflaynb = [10]
defbc = [1825]
box=True
bottom=-1000
lay_nb = 10
bc_left = 1825
bottom=-1000
dcol = 86.61266
drow = 86.61266

boxdempath = 'D:/emarti/Tarapaca/out/Tarapaca/results_stable/geographic/watershed_box_buff_dem.tif'

boxdem= rxr.open_rasterio(boxdempath, masked=True).squeeze()

xhead_toplot = np.linspace(0,669*drow, 669)

for KR in defKR:   
    KR_name = round(KR,3)
    recharge = round(k / KR_name, 7)    
    save_path_xc = 'D:/emarti/Tarapaca/out/figures/fixed_k/'+study_cuenca+'/xc/layers_nb_' + str(lay_nb) +'/bchead_'+str(bc_left)+'/'
    modeldir = 'D:/emarti/Tarapaca/out/final/'+study_cuenca+'/results_simulations/KR_' + str(KR_name) + '_layers_nb_' + str(lay_nb) + '_bchead_'+str(bc_left)+'m_bottom_' + str(bottom) +'/'
    #modeldir = 'D:/emarti/Tarapaca/out/'+study_cuenca+'/results_simulations/KR_' + str(KR_name) + '_layers_nb_' + str(lay_nb) + '_bchead_'+str(bc_left)+'m_thickness_' + str(thickness) +'/'
    namepath      = 'KR_' + str(KR_name) + '_layers_nb_' + str(lay_nb) +'_bchead_'+str(bc_left)+'m_bottom_' + str(bottom)
    full_path = modeldir
    nam_file = '{}.nam'.format(modeldir + namepath)
    head_file = '{}.hds'.format(modeldir + namepath)
    #dcol          = np.unique(mydis.delc)[0]
    #drow          = np.unique(mydis.delr)[0]
    mf = flopy.modflow.Modflow.load(nam_file,model_ws=full_path, version='mfnwt', verbose=False, check=False)
    hdsfile = flopy.utils.HeadFile(head_file)
    hds = hdsfile.get_data(kstpkper=(0, 0))
    
    #saturated_area_200 = boxdem.to_numpy()[200,:-1]
    #saturated_area_200[boxdem.to_numpy()[200,:-1] - hds[0,200,:-1]>0.01] = np.nan
    
    saturated_area_280 = boxdem.to_numpy()[280,:-1]
    saturated_area_280[boxdem.to_numpy()[280,:-1] - hds[0,280,:-1]>0.01] = np.nan
    
    # First step is to set up the plot
    fig = plt.figure(figsize=(21|, 7))
    ax = fig.add_subplot(1, 1, 1)
    # Next we create an instance of the PlotCrossSection class
    xsect = flopy.plot.PlotCrossSection(model=mf, line={"Row": 280})
    wt = xsect.plot_surface(hds, color="blue", lw=.5)
    linecollection = xsect.plot_grid()
    ax.scatter(xhead_toplot, saturated_area_280, color='red')
    plt.ylim((0, 6000))
    plt.xlabel('Distance (m)')
    plt.ylabel('Elevation (m)')
    #plt.title('Seepage distribution R/k='+str(round(1/KR_name,4)))
    #plt.gcf().savefig(modeldir+"3zones_surface_flows_map.png", dpi=800, format='png')
    #file = 'sflows_Rk'+str(round(1/KR_name,4))+'rch'+str(recharge)+'.png'
    t = ax.set_title('Cross-Section - Model Grid - R/k='+str(round(1/KR_name,4)))
    file = 'xc_row_280_Rk'+str(round(1/KR_name,4))+'rch'+str(recharge)+'.png'
    if not os.path.isdir(save_path_xc):
        os.makedirs(save_path_xc)
    fig.savefig(os.path.join(save_path_xc, file))
    plt.show()
    plt.gcf().clf()
    
    # fig = plt.figure(figsize=(15, 5))
    # ax1 = fig.add_subplot(1, 1, 1)
    # # Next we create an instance of the PlotCrossSection class
    # xsect = flopy.plot.PlotCrossSection(model=mf, line={"Row": 200})
    # wt = xsect.plot_surface(hds, color="blue", lw=.5)
    # linecollection = xsect.plot_grid()
    # ax1.scatter(xhead_toplot, saturated_area_200, color='red')
    # plt.ylim((-1000, 6000))
    # t = ax1.set_title('Row 200 Cross-Section - Model Grid - K/R='+str(KR_name))
    # file_2 = 'xc_row_200_KR'+ str(KR_name)+'rch'+str(recharge)+'.png'
    # if not os.path.isdir(save_path_xc):
    #     os.makedirs(save_path_xc)
    # fig.savefig(os.path.join(save_path_xc, file_2))
    # plt.show()
    # plt.gcf().clf()


#%%
extent = boxdem.x.min(), boxdem.x.max(), boxdem.y.min(), boxdem.y.max()
fig, ax1 = plt.subplots(figsize=(16,9))

x = plt.imshow(boxdem, extent=extent, cmap='jet')
cuenca.plot(color='None', edgecolor='red',linewidths=1.5, ax=ax1) 
plt.axhline(y=float(boxdem.y.max()-280*float((boxdem.y.max() - boxdem.y.min())/366)), color='k', linewidth=2)
plt.text(x=float(boxdem.x.min()+1000),y=(float(boxdem.y.max()-280*float((boxdem.y.max() - boxdem.y.min())/366)))+100,s='row 280' )
plt.axhline(y=float(boxdem.y.max()-200*float((boxdem.y.max() - boxdem.y.min())/366)), color='k', linewidth=2)
plt.text(x=float(boxdem.x.min()+1000),y=(float(boxdem.y.max()-200*float((boxdem.y.max() - boxdem.y.min())/366)))+100,s='row 200' )

#cuenca.plot(color='None', edgecolor='red',linewidths=1.5, ax=ax1) 
#river_cuenca.plot(ax=ax1)
#gdf.plot(color='blue', ax=ax1)

#%%
data_head = pd.read_csv(modeldir + 'heads.txt', sep=' |\t', engine='python')
data_head_2D = np.reshape(data_head['head_height'].to_numpy(), (366,670))
data_head_2D = data_head_2D[:,0:-1] #delete borders with no recharge
boxdem = boxdem[:,0:-1]

head_toplot = (data_head_2D[round(boxdem.shape[0]/3),:])
topo_toplot = boxdem[round(boxdem.shape[0]/3),:]
xhead_toplot = np.linspace(0,669*drow, 669)


plt.plot(xhead_toplot, head_toplot, label='Water Table')
plt.plot(xhead_toplot, topo_toplot, label='Topography')
plt.grid()
plt.legend(loc='best')
plt.xlabel('X (m)')
plt.ylabel('Elevation (m)')


