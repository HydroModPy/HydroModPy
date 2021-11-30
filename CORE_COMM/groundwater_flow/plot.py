# -*- coding: utf-8 -*-
"""
Created on Fri Nov 26 10:10:56 2021

@author: Alexandre Gauvain
"""

import matplotlib.pyplot as plt
import glob
import pandas as pd
import geopandas as gpd
import rasterio
import imageio

from tools import file_adds


def transient_surfaceflow(BV, ident):
    rch = BV.forcing.recharge 

    site= 'RejetVaunoise'

    ### PATH ###

    dir_to_analyse = BV.simulations_folder + ident + '/_extraction/'
    list_traces = glob(dir_to_analyse+'_surfaceflow/'+'trace_*.shp')

    figdir = dir_to_analyse + '_fig/'
    pngdir = dir_to_analyse + '_fig/_png/'
    gifdir = dir_to_analyse + '_fig/_gif/'
    file_adds.create_folder(figdir)
    file_adds.create_folder(pngdir)
    file_adds.create_folder(gifdir)

    ### INTERMITTENCY ###

    compt = 1
    c1 = 0
    c12 = 12

    for i in list_traces:
        print('Detect intermittency : '+str(compt))
        inter = list_traces[c1:c12]
        test = []
        for j in inter:
            outflow = gpd.read_file(j)
            x_list = outflow.geometry.x
            y_list = outflow.geometry.y
            mix = list(zip(x_list, y_list))
            test.extend(mix)
            df = pd.DataFrame(test, columns=['x','y'])
        df['z'] = df['x'].astype(str) + df['y'].astype(str)
        values = df['z'].value_counts()
        values = values[values==12]
        for j in inter:
            outflow = gpd.read_file(j)
            outflow['x'] = outflow.geometry.x
            outflow['y'] = outflow.geometry.y
            outflow['z'] = outflow['x'].astype(str) + outflow['y'].astype(str)
            outflow['persit'] = 0
            for h in values.index:
                outflow.loc[outflow['z']==h,'persit'] = 1
            outflow.to_file(j)
        
        c1+=12
        c12+=12
        compt+=1

    ### PLOT STREAMS ###

    compt = 0

    for i in list_traces:
    
        lead_numb = "%03d" % (compt,)
        print(lead_numb)
        outflow = gpd.read_file(i)
    
        fig, ax = plt.subplots(1, 1, figsize=(4,4), dpi=300)
        
        dem = rasterio.open(BV.geographic.watershed_dem)
        contour = gpd.read_file(BV.stable_folder+'/geographic/'+'watershed_contour.shp')
        
        sections = gpd.read_file(BV.stable_folder+'/hydrology/'+'sections.shp')
        sections[sections.Persistanc=='3'].plot(ax=ax, lw=1, color='grey', ls='-', zorder=7)
        sections[sections.Persistanc=='4'].plot(ax=ax, lw=1, color='k', ls='-', zorder=7)
        
        bounds = contour.geometry.total_bounds
        xlim = ([bounds[0], bounds[2]])
        ylim = ([bounds[1], bounds[3]])
        
        ax.set_xlim(xlim)
        ax.set_ylim(ylim)
        ax.get_xaxis().set_visible(False)
        ax.get_yaxis().set_visible(False)
        ax.set_title(site+'  '+str(rch.index[compt])[:10], fontproperties=fontprop)
        ax.set(aspect='equal') 
        
        image_hidden = ax.imshow(np.ma.masked_where(dem.read(1) < 0, dem.read(1)), cmap='Greys')
        mnt = rasterio.plot.show(np.ma.masked_where(dem.read(1) < 0, dem.read(1)), ax=ax, transform=dem.transform,
                                 cmap='Greys', alpha=0.5, zorder=2)
        
        contour.plot(ax=ax, lw=1.5, color='k', zorder=6)
        divider = make_axes_locatable(ax)
        cax = divider.append_axes("right", size="1%", pad=0.05)
        fig.add_axes(cax)
        cbar = fig.colorbar(image_hidden, cax=cax, orientation="vertical")
        val = np.ma.masked_where(dem.read(1) < 0, dem.read(1))
        minVal =  int(round(np.min(val[np.nonzero(val)],0)))
        maxVal =  int(round(np.max(val[np.nonzero(val)],0)))
        meanVal = int(round(minVal+((maxVal-minVal)/2),0))
        cbar.set_ticks([minVal, meanVal, maxVal])
        cbar.set_ticklabels([minVal, meanVal, maxVal])
        cbar.mappable.set_clim(minVal, maxVal)
        cbar.ax.tick_params(labelsize=10)
        
        # outflow.plot(ax=ax, alpha=1, column='persit', cmap="winter_r", 
        #               marker='s', markersize=7.5, lw=0.1, edgecolor='none',
        #               scheme="User_Defined", 
        #               classification_kwds=dict(bins=[1, 0]),
        #               zorder=4)
           
        # from matplotlib.colors import ListedColormap
        # cmap = ListedColormap(['darkorange','blue'])
        
        outflow[outflow.persit==0].plot(ax=ax, alpha=1, column='persit', color='darkorange', 
                                        marker='s', markersize=7.5, lw=0.1, edgecolor='none',
                                        zorder=4)
        
        outflow[outflow.persit==1].plot(ax=ax, alpha=1, column='persit', color='dodgerblue', 
                                        marker='s', markersize=7.5, lw=0.1, edgecolor='none',
                                        zorder=4)
        
        hydro = gpd.read_file(stable_folder + '/hydrology/' + 'hydrometric.shp')
        hydro.plot(ax=ax, lw=1, facecolor='white', marker='o', edgecolor='k', alpha=1, zorder=7)
        
        onde = gpd.read_file(stable_folder + '/hydrology/' + 'onde.shp')
        allsta = onde['<LbSiteHyd'].unique()
        for idx, lib in enumerate(allsta):
            sta = onde[onde['<LbSiteHyd']==lib]
            sta.plot(ax=ax, lw=1, facecolor='yellow', marker='^', edgecolor='k', alpha=1, zorder=8)
        
        name_fig = 'interm_' + str(lead_numb) + '.png'
        plt.tight_layout()
        plt.savefig(pngdir + name_fig)
        plt.close()
        
        compt+=1
    
    ### MAKE GIF ###
    
    filenames = glob(pngdir+'/'+'interm_*.png')  
    import imageio
    images = []
    for filename in filenames:
        images.append(imageio.imread(filename))
    imageio.mimsave(gifdir+'/'+'interm_outflow.gif', images, duration=1, loop=1)
    
    
    # from matplotlib.gridspec import GridSpec
    # fig = plt.figure(figsize=(12, 6))
    # gs = GridSpec(nrows=2, ncols=2, width_ratios=[3, 1], height_ratios=[1, 2])
    # ax1 = fig.add_subplot(gs[0, 0])
    # ax2 = fig.add_subplot(gs[0, 1])
    # ax3 = fig.add_subplot(gs[1, 0])
    # ax4 = fig.add_subplot(gs[1, 1])
    
    ##### DEM #####
    
    dem_cut = stable_folder + 'geographic/watershed_dem.tif'
    demDs = gdal.Open(dem_cut)
    demData = demDs.GetRasterBand(1).ReadAsArray()
    geot = demDs.GetGeoTransform()
    dx = geot[1] #delta x
    dy = abs(geot[5]) #delta y
    demData_raw = demData
    msk = (demData==np.min(demData))
    demData = np.ma.masked_array(demData, mask=msk)
    lx,ly = demData.shape
    x = np.linspace(0,lx,lx)
    y = np.linspace(0,ly,ly)
    xx, yy = np.meshgrid(y,x)
    xx_mi = np.min(np.ma.array(xx, mask=msk))
    xx_ma = np.max(np.ma.array(xx, mask=msk))
    ext_x = xx_ma-xx_mi
    yy_mi = np.min(np.ma.array(yy, mask=msk))
    yy_ma = np.max(np.ma.array(yy, mask=msk))
    ext_y = yy_ma-yy_mi
    
    ##### MODLOW #####
    
    dir_to_analyse = simulations_folder + ident + '/_extraction/'
    mass_to_analyse = simulations_folder + ident + '/_extraction/_surfaceflow/'
    figdir = dir_to_analyse + '_fig/'
    pngdir = dir_to_analyse + '_fig/_png/'
    gifdir = dir_to_analyse + '_fig/_gif/'
    file_adds.create_folder(figdir)
    file_adds.create_folder(pngdir)
    file_adds.create_folder(gifdir)
    water_table_path = dir_to_analyse + 'watertable_elevation.npy'
    outflow_path = dir_to_analyse + 'outflow_drain.npy'
    
    wt_all = np.load(water_table_path, allow_pickle=True).item() 
    outflow_all = np.load(outflow_path, allow_pickle=True).item() 
    
    surface_sat = []
    rch_for_gif = []
    time_for_gif = []
    flow_rate = []
    
    time_tot = rch.index
    
    ##### LOOP #####
    
    for key in wt_all:
        ### PREP ###
           
        outflow = outflow_all[key]
        msk_outflow = (outflow==np.min(outflow))
        outflow = np.ma.masked_array(outflow, mask=msk_outflow)
        outflow = np.ma.masked_where(outflow==0,outflow)
        outflow_len = len(outflow[outflow>0])
        
        cell = demData.count()
        
        flow_rate_temp = np.sum(outflow) / (cell * 75**2)
        flow_rate.append(flow_rate_temp)
        
        wt = wt_all[key]
        wt = np.ma.masked_array(wt, mask=msk)
        wt_len = len(wt[wt>0])
        surface_sats = outflow_len/wt_len*100
        surface_sat.append(surface_sats)
    
    for key in wt_all:
        lead_numb = "%03d" % (key,)
        
        t_temp = rch.index[key]
        time_for_gif.append(t_temp)
        
        outflow = imageio.imread(mass_to_analyse+'mass_outflow_drain_t('+lead_numb+')'+'.tif')
        
        msk_outflow = (outflow<0)
        outflow = np.ma.masked_array(outflow, mask=msk_outflow)
        outflow = np.ma.masked_where(outflow==0, outflow) / 75**2 * 1000
        outflow_len = len(outflow[outflow>0])
        
        cell = demData.count()
        
        wt = wt_all[key]
        wt = np.ma.masked_array(wt, mask=msk)
        wt_len = len(wt[wt>0])
        
        ls = LightSource(azdeg=45, altdeg=45)
        cmap = plt.cm.Greys
        rgb = ls.shade(demData, cmap=cmap, blend_mode='soft', vert_exag=2, dx=dx, dy=dy)
        
        ### PLOT ###
        
        fig = plt.figure(figsize=(11,6))
        gs = fig.add_gridspec(3,2)
        ax1 = fig.add_subplot(gs[:, 0])
        ax2 = fig.add_subplot(gs[0, 1])
        ax3 = fig.add_subplot(gs[1, 1])
        ax4 = fig.add_subplot(gs[2, 1])
        
        ax = ax1
        ax.get_xaxis().set_visible(False)
        ax.get_yaxis().set_visible(False)
        im = ax.imshow(rgb, alpha=0.8, cmap=cmap)
        # levels = np.arange(1000, 3000, 100)
        hc=ax.contour(xx, yy, wt, alpha=0.25, cmap=mpl.colors.ListedColormap('k'), linewidths=1)
        ax.clabel(hc, inline=True, fontsize=8, fmt='%1.0f')
        # levels_outflow = np.arange(-1, 3.5, 0.5)
        # cf=ax.contourf(xx, yy, np.log10(outflow), levels=levels_outflow, cmap='jet_r', alpha=1, antialiased = True)
        # norm = mpl.colors.Normalize(vmin=-1, vmax=4)
        # cf=ax.imshow(np.log10(outflow), cmap='jet_r', alpha=1, vmin=-1, vmax=4)
        cf=ax.imshow(outflow / 75**2, cmap='jet_r', alpha=1, vmin=0, vmax=int(round(rch.mean()*1000)))
        plt.xlim(xx_mi-0.1*ext_x,xx_ma+0.1*ext_x)
        plt.ylim(yy_ma+0.1*ext_y,yy_mi-0.1*ext_y)
     
        divider = make_axes_locatable(ax)
        # Legend 1
        cax = divider.append_axes("right", size="1%", pad=0.05)
        fig.add_axes(cax)
        cbar = fig.colorbar(im, cax=cax, orientation="vertical")
        val = np.ma.masked_where(demData < 0, demData)
        minVal =  int(round(np.min(val[np.nonzero(val)],0)))
        maxVal =  int(round(np.max(val[np.nonzero(val)],0)))
        meanVal = int(round(minVal+((maxVal-minVal)/2),0))
        cbar.set_ticks([minVal, meanVal, maxVal])
        cbar.set_ticklabels([minVal, meanVal, maxVal])
        cbar.mappable.set_clim(minVal, maxVal)
        cbar.ax.tick_params(labelsize=10)
        # Legend 2
        cax = divider.new_vertical(size="2%", pad=0.05, pack_start=True)
        fig.add_axes(cax)
        cbar = fig.colorbar(cf, cax=cax, orientation="horizontal")
        ticks = np.arange(0, int(round(rch.mean()*1000))+5, 5)
        cbar.set_ticks(ticks)
        cbar.set_ticklabels(ticks)
        cbar.set_label('Cumulated upstream discharge [mm/M]')
        plt.tight_layout()
        
        ax = ax2
        xlim = [pd.to_datetime(str(first-1)), pd.to_datetime(str(last+2))]
        rechs = rch[key]
        rch_for_gif.append(rechs)
        ax.set_title("Recharge, [mm/M]")
        ax.plot(time_tot, rch*1000, color='magenta', lw=2)
        ax.axvline(x=t_temp, color='k', lw=2)
        plt.setp(ax.get_xticklabels(), visible=False)
        ax.set_xlim(xlim)
        ax.set_ylim(rch.min()*1000, rch.max()*1000)
        plt.tight_layout()
    
        ax = ax3
        #ax3.set_xlabel("time")
        ax.set_title("Saturated area, [%]")
        ax.plot(time_tot, surface_sat,'darkorange', lw=2)
        plt.setp(ax.get_xticklabels(), visible=False)
        ax.axvline(x=t_temp, color='k', lw=2)
        ax.set_xlim(xlim)
        ax.set_ylim(np.array(surface_sat).min(), np.array(surface_sat).max())
        plt.tight_layout()
    
        ax = ax4
        ax.set_xlabel("Time")
        ax.set_title("Discharge, [mm/M]")
        ax.plot(time_tot, np.array(flow_rate) * 1000,'dodgerblue', lw=2)
        ax.axvline(x=t_temp, color='k', lw=2)
        # ax.set_yscale("log")
        ax.invert_yaxis()
        ax.set_xlim(xlim)
        ax.set_ylim(np.array(flow_rate).min()* 1000, np.array(flow_rate).max()* 1000)
        plt.tight_layout()
        
        name_fig = 'dyn_' + str(lead_numb) + '.png'
        plt.tight_layout()
        plt.savefig(pngdir + name_fig)
        plt.close(fig)
        print(str(key))
               
    filenames = glob(pngdir+'/'+'dyn_*.png')  
    import imageio
    images = []
    for filename in filenames:
        images.append(imageio.imread(filename))
    imageio.mimsave(gifdir+'/'+'dyn_outflow.gif', images, duration=1, loop=1)