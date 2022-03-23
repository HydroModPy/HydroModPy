# -*- coding: utf-8 -*-
"""
Created on Tue Dec 21 14:43:47 2021

@author: ronan
"""

# General
import sys
from os.path import dirname, abspath
DIR = dirname(dirname(abspath(__file__)))
sys.path.append(DIR)
import glob
import os
import numpy as np
import pandas as pd
from osgeo import gdal
import matplotlib.dates as mdates
from IPython import get_ipython

# Plot
import matplotlib.pyplot as plt
import matplotlib as mpl
from matplotlib.dates import YearLocator, MonthLocator, DateFormatter
from mpl_toolkits.axes_grid1 import make_axes_locatable
from matplotlib.colors import LightSource
from mpl_toolkits.axes_grid1.anchored_artists import AnchoredSizeBar

# Gis
import imageio
import rasterio
import geopandas as gpd
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = True

# Modules                   
from tools import toolbox

class SurfaceOutputs():
    def __init__(self, recharge, simulations_folder, stable_folder, model_name, 
                 types_obs, save_gif=False, first_only = True,
                 outflow=False, accflux=False, intermittency=False,
                 chronics=True,
                 sim_state='steady'):

        self.fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large
        
        self.stable_folder = stable_folder
        self.dir_to_analyse = os.path.join(simulations_folder, model_name,'_watershed')
        self.list_traces = sorted(glob.glob(os.path.join(self.dir_to_analyse,'_surfaceflow','tracept_*.shp')), 
                                  key=os.path.getmtime)
        self.list_outflow = sorted(glob.glob(os.path.join(self.dir_to_analyse,'_tifs','outflow_*.tif')),
                                   key=os.path.getmtime)
        self.list_accflux = sorted(glob.glob(os.path.join(self.dir_to_analyse,'_tifs','accumulation_*.tif')),
                                   key=os.path.getmtime)
        self.recharge = recharge
        
        self.types_obs = types_obs
        
        self.figdir = self.dir_to_analyse + '_fig/'
        self.pngdir = self.dir_to_analyse + '_fig/_png/'
        self.gifdir = self.dir_to_analyse + '_fig/_gif/'
        
        toolbox.create_folder(self.figdir)
        toolbox.create_folder(self.pngdir)
        toolbox.create_folder(self.gifdir)
                
        if intermittency == True:
            for iter_time in range(len(self.list_traces)):
                print('Plot intermittency : '+str(iter_time)+' / '+str(len(self.list_traces)))
                if first_only==True:
                    if iter_time>=12*7:
                        break                        
                self.plot_map_intermittency(iter_time)

        if outflow == True:
            self.scanning_discharge()
            for iter_time in range(len(self.list_outflow)):
                print('Plot discharge : '+str(iter_time)+' / '+str(len(self.list_outflow)))
                if first_only==True:
                    if iter_time>0:
                        break
                self.plot_map_discharge(iter_time, 'outflow_drain')

        if accflux == True:
            self.scanning_discharge()
            for iter_time in range(len(self.list_accflux)):
                print('Plot accummulation : '+str(iter_time)+' / '+str(len(self.list_accflux)))
                if first_only==True:
                    if iter_time>0:
                        break
                self.plot_map_discharge(iter_time, 'accumulation_flux')
        
        if sim_state == 'transient':
            if chronics == True:
                self.scanning_discharge()
                for iter_time in range(len(self.list_outflow)):
                    print('Plot chronics : '+str(iter_time)+' / '+str(len(self.list_outflow)))
                    if first_only==True:
                        if iter_time>0:
                            break
                    self.plot_chronic_results(iter_time)
        
        if save_gif==True:
            if chronics == True:
                self.make_a_gif('results_')
            if intermittency == True:
                self.make_a_gif('map_intermittency_')
            if outflow == True:
                self.make_a_gif('map_outflow_drain_')
            if accflux == True:
                self.make_a_gif('map_accumulation_flux_')
        
    def plot_map_intermittency(self, iter_time):
        # Select file
        file = self.list_traces[iter_time]
        # lead_numb = "%03d" % (iter_time,)
        lead_numb = str(iter_time)
        # Open files
        outflow = gpd.read_file(file)
        dem = rasterio.open(self.stable_folder+'/geographic/'+'watershed_dem.tif')
        imageio.imread(self.stable_folder+'/geographic/'+'watershed_dem.tif')
        contour = gpd.read_file(self.stable_folder+'/geographic/'+'watershed_contour.shp')
        try:
            streams = gpd.read_file(self.stable_folder+'/hydrology/'+self.types_obs[1]+'.shp')
            sections = gpd.read_file(self.stable_folder+'/hydrology/'+self.types_obs[0]+'.shp')
        except:
            pass
        # Plot observed
        fig, ax = plt.subplots(1, 1, figsize=(6,6), dpi=300)
        try:
            sections[sections.Persistanc=='3'].plot(ax=ax, lw=2, color='k', ls='--', zorder=7,
                            label='Temporary - Obs.')
            sections[sections.Persistanc=='4'].plot(ax=ax, lw=2, color='k', ls='-', zorder=7,
                            label='Perennial - Obs.')
        except:
            pass
        bounds = contour.geometry.total_bounds
        xlim = ([bounds[0], bounds[2]])
        ylim = ([bounds[1], bounds[3]])
        ax.set_xlim(xlim)
        ax.set_ylim(ylim)
        ax.get_xaxis().set_visible(False)
        ax.get_yaxis().set_visible(False)
        try:
            ax.set_title(str(self.recharge.index[iter_time])[:10])
        except:
            pass
        ax.set(aspect='equal') 
        image_hidden = ax.imshow(np.ma.masked_where(dem.read(1) < 0, dem.read(1)), cmap='Greys')
        rasterio.plot.show(np.ma.masked_where(dem.read(1) < 0, dem.read(1)), ax=ax, transform=dem.transform,
                                 cmap='Greys', alpha=0.5, zorder=2)
        contour.plot(ax=ax, lw=1.5, color='k', zorder=6)
        # Color bar
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
        # Plot simulated
        outflow[outflow.Persistanc==0].plot(ax=ax, alpha=1, column='Persistanc', color='darkorange', 
                            marker='s', markersize=30, lw=0.1, edgecolor='none',
                            zorder=4, label='Temporary - Sim.')
        outflow[outflow.Persistanc==1].plot(ax=ax, alpha=1, column='Persistanc', color='dodgerblue', 
                            marker='s', markersize=30, lw=0.1, edgecolor='none',
                            zorder=4, label='Perennial - Sim.')
        scalebar = AnchoredSizeBar(ax.transData, 1000, '1 km', 'lower left', 
                                   pad=0.5, color='k', frameon=False, size_vertical=1,
                                   fontproperties=self.fontprop)
        ax.add_artist(scalebar)
        ax.legend(frameon=False, loc='best') # bbox_to_anchor=(0,0), bbox_transform=ax.transAxes)
        # Plot stations if exist
        try:
            hydro = gpd.read_file(self.stable_folder + '/hydrometric/' + 'hydrometric.shp')
            hydro.plot(ax=ax, lw=1, facecolor='white', marker='o', edgecolor='k', alpha=1, zorder=7)
            onde = gpd.read_file(self.stable_folder + '/hydrometric/' + 'onde.shp')
            allsta = onde['<LbSiteHyd'].unique()
            for idx, lib in enumerate(allsta):
                sta = onde[onde['<LbSiteHyd']==lib]
                sta.plot(ax=ax, lw=1, facecolor='yellow', marker='^', edgecolor='k', alpha=1, zorder=8)
        except:
            pass
        # Save figure
        name_fig = 'map_intermittency_' + str(lead_numb) + '.png'
        plt.tight_layout()
        fig.savefig(self.pngdir + name_fig)
        plt.close()
    
    def scanning_discharge(self):
        # Open data
        self.df = pd.read_csv(os.path.join(self.dir_to_analyse,'_simulated_results.csv'), sep=';',
                         index_col='date', parse_dates=True)
        try:
            self.first = self.df.first_valid_index().year
            self.last = self.df.last_valid_index().year    
        except:
            pass
        self.df['spe'] = (self.df.outflow_drain) * 1000 # mm/m
        self.df['rec'] = self.recharge * 1000
        self.maxrec = self.df['rec'].max()
        # Dem to watershed scale
        dem_cut = os.path.join(self.stable_folder,'geographic','watershed_dem.tif')
        demDs = gdal.Open(dem_cut)
        self.demData = demDs.GetRasterBand(1).ReadAsArray()
        geot = demDs.GetGeoTransform()
        self.dx = geot[1] #delta x
        self.dy = abs(geot[5]) #delta y
        self.msk = (self.demData<0)
        self.demData = np.ma.masked_array(self.demData, mask=self.msk)
        lx,ly = self.demData.shape
        x = np.linspace(0,lx,lx)
        y = np.linspace(0,ly,ly)
        self.xx, self.yy = np.meshgrid(y,x)
        self.xx_mi = np.min(np.ma.array(self.xx, mask=self.msk))
        self.xx_ma = np.max(np.ma.array(self.xx, mask=self.msk))
        self.ext_x = self.xx_ma-self.xx_mi
        self.yy_mi = np.min(np.ma.array(self.yy, mask=self.msk))
        self.yy_ma = np.max(np.ma.array(self.yy, mask=self.msk))
        self.ext_y = self.yy_ma-self.yy_mi
        # Open files to plot
        self.mass_to_analyse = os.path.join(self.dir_to_analyse, '_tifs')
        water_table_path = os.path.join(self.dir_to_analyse, 'watertable_elevation.npy')
        outflow_path = os.path.join(self.dir_to_analyse,'outflow_drain.npy')
        self.wt_all = np.load(water_table_path, allow_pickle=True).item() 
        self.outflow_all = np.load(outflow_path, allow_pickle=True).item() 
        self.surface_sat = []
        self.rch_for_gif = []
        self.time_for_gif = []
        self.flow_rate = []
        self.time_tot = self.df.index
        self.minflow = []
        self.maxflow = []
        # Loop to store each times
        for key in self.wt_all:
            outflow = self.outflow_all[key]
            msk_outflow = (self.demData<0)
            outflow = np.ma.masked_array(outflow, mask=msk_outflow)
            outflow = np.ma.masked_where(outflow==0, outflow)
            outflow_len = len(outflow[outflow>0])
            cell = self.demData.count()
            flow_rate_temp = np.sum(outflow) / (cell * self.dx**2)
            self.flow_rate.append(flow_rate_temp)
            wt = self.wt_all[key]
            wt = np.ma.masked_array(wt, mask=self.msk)
            wt_len = len(wt[wt>0])
            surface_sats = outflow_len/wt_len*100
            self.surface_sat.append(surface_sats)
            self.minflow.append(outflow.min())
            self.maxflow.append(outflow.max())
                    
    def plot_map_discharge(self, iter_times, typ_file):
        # Open data
        # lead_numb = "%03d" % (iter_times,)
        lead_numb = str(iter_times)
        outflow = imageio.imread(os.path.join(self.mass_to_analyse,typ_file+'_t('+lead_numb+')'+'.tif'))
        # Mask data
        msk_outflow = (outflow<0)
        outflow = np.ma.masked_array(outflow, mask=msk_outflow)
        outflow = np.ma.masked_array(outflow, mask=(self.demData<=0))
        outflow = np.ma.masked_where(outflow==0, outflow) / 75**2 * 1000
        outflow = np.log10(outflow)
        wt = self.wt_all[iter_times]
        wt = np.ma.masked_array(wt, mask=self.msk)
        # Params for plot
        ls = LightSource(azdeg=45, altdeg=45)
        cmap = plt.cm.Greys
        rgb = ls.shade(self.demData, cmap=cmap, blend_mode='soft', vert_exag=2, dx=self.dx, dy=self.dy)
        # Plot
        fig, ax = plt.subplots(1, 1, figsize=(6,6), dpi=300)
        try:
            ax.set_title(str(self.recharge.index[iter_times])[:10])
        except:
            ax.set_title(str(iter_times))
        vmin = np.log10(min(self.minflow))
        vmax = np.log10(max(self.maxflow))
        ax.get_xaxis().set_visible(False)
        ax.get_yaxis().set_visible(False)
        im = ax.imshow(rgb, alpha=0.8, cmap=cmap)
        hc=ax.contour(self.xx, self.yy, wt, alpha=0.25, 
                      cmap=mpl.colors.ListedColormap('k'), linewidths=1)
        ax.clabel(hc, inline=True, fontsize=8, fmt='%1.0f')
        # levels_outflow = np.arange(vmin, vmax, 0.5)
        # cf=ax.contourf(self.xx, self.yy, outflow, levels=levels_outflow, 
        #                cmap='jet_r', alpha=1, antialiased = True)
        # norm = mpl.colors.Normalize(vmin=vmin, vmax=vmax)
        # ax.set_xlim(self.xx_mi-0.1*self.ext_x,self.xx_ma+0.1*self.ext_x)
        # ax.set_ylim(self.yy_ma+0.1*self.ext_y,self.yy_mi-0.1*self.ext_y)
        cf=ax.imshow(outflow, cmap='jet_r', alpha=1, vmin=vmin, vmax=vmax)
        # Color bar elevation
        divider = make_axes_locatable(ax)
        cax = divider.append_axes("right", size="1%", pad=0.05)
        fig.add_axes(cax)
        cbar = fig.colorbar(im, cax=cax, orientation="vertical")
        val = np.ma.masked_where(self.demData < 0, self.demData)
        minVal =  int(round(np.min(val[np.nonzero(val)],0)))
        maxVal =  int(round(np.max(val[np.nonzero(val)],0)))
        meanVal = int(round(minVal+((maxVal-minVal)/2),0))
        cbar.set_ticks([minVal, meanVal, maxVal])
        cbar.set_ticklabels([minVal, meanVal, maxVal])
        cbar.mappable.set_clim(minVal, maxVal)
        cbar.ax.tick_params(labelsize=10)
        # cbar.set_label('Elevation [m]', rotation=270, fontsize=10, labelpad=10)    
        # Color bar discharge
        cax = divider.new_vertical(size="2%", pad=0.05, pack_start=True)
        fig.add_axes(cax)
        cbar = fig.colorbar(cf, cax=cax, orientation="horizontal")
        ticks = np.linspace(vmin, vmax, 5)
        cbar.set_ticks(ticks)
        cbar.set_ticklabels(ticks.round(1).astype(float))
        if typ_file =='accumulation_flux':
            cbar.set_label('Cumulated flux Log(Q) [mm/months]')
        if typ_file =='outflow_drain':
            cbar.set_label('Outflow flux Log(Q) [mm/months]')    
        # Save figure
        plt.tight_layout()
        name_fig = 'map_'+typ_file+'_' + str(lead_numb) + '.png'
        plt.tight_layout()
        plt.savefig(self.pngdir + name_fig)
        plt.close(fig)
            
    def plot_chronic_results(self, iter_times):
        # Times to plot
        # lead_numb = "%03d" % (iter_times,)
        lead_numb = str(iter_times)
        t_temp = self.df.index[iter_times]
        self.time_for_gif.append(t_temp)
        # Dates for plot
        yearsmaj = mdates.YearLocator(2)   # every year
        yearsmin = mdates.YearLocator(1)
        # monthsmaj = mdates.MonthLocator(6)  # every month
        # monthsmin = mdates.MonthLocator(3)
        # months_fmt = mdates.DateFormatter('%m') #b = name of month ?
        years_fmt = mdates.DateFormatter('%Y')
        # Plot
        fig, axs = plt.subplots(2, 1, figsize=(8,6), dpi=300)
        axs = axs.ravel()
        # Recharge
        rechs = self.df.iloc[iter_times]
        self.rch_for_gif.append(rechs)
        try:
            xlim = [pd.to_datetime(str(self.first)), pd.to_datetime(str(self.last+1))]
        except:
            pass
        # Saturation
        ax = axs[0]
        #ax3.set_xlabel("time")
        ax.set_title("Saturated area, [%]")
        ax.plot(self.time_tot, self.surface_sat,'blue', lw=2)
        plt.setp(ax.get_xticklabels(), visible=False)
        ax.axvline(x=t_temp, color='k', lw=2)
        try:
            ax.set_xlim(xlim)
            ax.xaxis.set_major_locator(yearsmaj)
            ax.xaxis.set_minor_locator(yearsmin)
            ax.xaxis.set_major_formatter(years_fmt)
        except:
            pass
        ax.set_ylim(0, 100)
        plt.tight_layout()
        # Discharge
        ax = axs[1]
        ax.plot(self.time_tot, self.df.rec, color='k', lw=2, label='Recharge')
        ax.set_xlabel("Time")
        ax.set_title("Discharge, [mm/M]")
        ax.plot(self.time_tot, np.array(self.flow_rate)*1000,'red', lw=2, label='Outflow')
        ax.legend(loc='upper right')
        ax.axvline(x=t_temp, color='k', lw=2)
        # ax.set_yscale("log")
        ax.invert_yaxis()
        try:
            ax.set_xlim(xlim)
            ax.xaxis.set_major_locator(yearsmaj)
            ax.xaxis.set_minor_locator(yearsmin)
            ax.xaxis.set_major_formatter(years_fmt)
        except:
            pass
        ax.set_ylim(0, self.maxrec + (self.maxrec*0.1))
        plt.tight_layout()
        # Save figure
        name_fig = 'results_' + str(lead_numb) + '.png'
        plt.tight_layout()
        plt.savefig(self.pngdir + name_fig)
        plt.close(fig)
            
    def make_a_gif(self, begin_by):
        filenames = sorted(glob.glob(self.pngdir+'/'+begin_by+'*.png'), key=os.path.getmtime)
        images = []
        for filename in filenames:
            images.append(imageio.imread(filename))
        imageio.mimsave(self.gifdir+'/'+begin_by+'.gif', images, duration=0.5, loop=1)

#%% Interactive cross-section head

def interactive_cross_section(dem_data, wt_data, river_data, interactive=True):
    
    # Modules
    mpl.rcParams.update(mpl.rcParamsDefault)
    get_ipython().run_line_magic('matplotlib', 'qt')
    
    # Figure params
    fig, main_ax = plt.subplots(figsize=(5, 5))
    # title = plt.suptitle('Interactive cross section head',y=0.98)
    divider = make_axes_locatable(main_ax)
    top_ax = divider.append_axes("top",1.1, pad=0.2, sharex=main_ax)
    right_ax = divider.append_axes("right",1.1, pad=0.2, sharey=main_ax)
    
    # Axis names
    top_ax.xaxis.set_tick_params(labelbottom=False)
    right_ax.yaxis.set_tick_params(labelleft=False)
    main_ax.set_xlabel('X [pixel]')
    main_ax.set_ylabel('Y [pixel]')
    top_ax.set_ylabel('Z [m]')
    right_ax.set_xlabel('Z [m]')
    
    # Dimensions
    xvalues = np.linspace(-1,1,dem_data.shape[1])
    yvalues = np.linspace(-1,1,dem_data.shape[0])
    xx, yy = np.meshgrid(xvalues,yvalues)
    
    # Positions
    pos = np.empty(xx.shape + (2,))
    pos[:, :, 0] = xx
    pos[:, :, 1] = yy
    
    # V and H lines
    if interactive == True:
        cur_x = dem_data.shape[1] - 1
        cur_y = dem_data.shape[0] - 1
    else:
        cur_x = dem_data.shape[1] /2
        cur_y = dem_data.shape[0] /2
    
    # Data dem
    dem_max = dem_data.max()
    dem_prof = dem_data.astype(float)
    dem_prof[dem_prof<0] = np.nan
    
    # Plot dem
    dem_plot = np.ma.masked_array(dem_data, mask=(dem_data<0))
    main_ax.imshow(dem_plot, origin='lower', cmap='terrain')
    
    # Plot rivers
    try:
        river_plot = np.ma.masked_array(river_data, mask=(river_data<=0))
        main_ax.imshow(river_plot, origin='lower', cmap=mpl.colors.ListedColormap('navy'))
    except:
        pass
    
    plt.gca().invert_yaxis()
    
    # Data wt
    wt_prof = wt_data.astype(float)
    wt_prof[wt_prof<0] = np.nan
    # wt_max = wt_data.max()
    
    # Scaling axis
    main_ax.autoscale(enable=False)
    right_ax.autoscale(enable=False)
    top_ax.autoscale(enable=False)
    right_ax.set_xlim(right=dem_max)
    top_ax.set_ylim(top=dem_max)
    
    # Plot lines
    v_line = main_ax.axvline(cur_x, color='k', lw=2)
    h_line = main_ax.axhline(cur_y, color='k', lw=2)
    # d_line = main_ax.plot((x0,x1),(y0,y1), 'white', '-')
    
    # Plot dem cross-sections
    if interactive == True:
        lw = 1.5
    else:
        lw = 1
    
    dem_v_plot = dem_prof[:,int(cur_x)]
    dem_v_plot[dem_v_plot == 0] = np.nan
    dem_v_prof, = right_ax.plot(dem_v_plot,np.arange(xx.shape[0]), c='saddlebrown', lw=lw)
    
    dem_h_plot = dem_prof[int(cur_y),:]
    dem_h_plot[dem_h_plot == 0] = np.nan
    dem_h_prof, = top_ax.plot(np.arange(xx.shape[1]),dem_h_plot, c='saddlebrown', lw=lw)
    # dem_h_prof, = top_ax.plot(x, zi, 'b-')
    
    # # Plot wt cross-sections
    if interactive == True:
        lw = 1.5
    else:
        lw = 0
        
    wt_v_plot = wt_prof[:,int(cur_x)]
    wt_v_plot[wt_v_plot == 0] = np.nan
    wt_v_prof, = right_ax.plot(wt_v_plot,np.arange(xx.shape[0]), c='dodgerblue', lw=lw)
    
    if interactive != True:
        wt_v_fill = right_ax.fill_betweenx(np.arange(xx.shape[0]), 0, wt_v_plot,
                                           color='deepskyblue', alpha=0.5, lw=0)
        wt_v_fill = right_ax.fill_betweenx(np.arange(xx.shape[0]), wt_v_plot, dem_v_plot,
                                           color='saddlebrown', alpha=0.5, lw=0)
    
    wt_h_plot = wt_prof[int(cur_y),:]
    wt_h_plot[wt_h_plot == 0] = np.nan
    wt_h_prof, = top_ax.plot(np.arange(xx.shape[1]), wt_h_plot, c='dodgerblue', lw=lw)
    
    if interactive != True:
        wt_h_fill = top_ax.fill_between(np.arange(xx.shape[1]), 0, wt_h_plot,
                                        color='deepskyblue', alpha=0.5, lw=0)
        wt_h_fill = top_ax.fill_between(np.arange(xx.shape[1]), wt_h_plot, dem_h_plot,
                                        color='saddlebrown', alpha=0.5, lw=0)
    
    plt.tight_layout()
    
    # Animation interactive
    
    def on_move_dem(event):
        if event.inaxes is main_ax:       
            cur_x = event.xdata
            cur_y = event.ydata
            dem_v_plot = dem_prof[:,int(cur_x)]
            dem_v_plot[dem_v_plot == 0] = np.nan
            dem_h_plot = dem_prof[int(cur_y),:]
            dem_h_plot[dem_h_plot == 0] = np.nan    
            v_line.set_xdata([cur_x, cur_x])
            h_line.set_ydata([cur_y, cur_y])
            dem_v_prof.set_xdata(dem_v_plot)
            dem_h_prof.set_ydata(dem_h_plot)
            fig.canvas.draw_idle()
            
    def on_move_wt(event):
        if event.inaxes is main_ax:       
            cur_x = event.xdata
            cur_y = event.ydata
            wt_v_plot = wt_prof[:,int(cur_x)]
            wt_v_plot[wt_v_plot == 0] = np.nan
            wt_h_plot = wt_prof[int(cur_y),:]
            wt_h_plot[wt_h_plot == 0] = np.nan
            v_line.set_xdata([cur_x, cur_x])
            h_line.set_ydata([cur_y, cur_y])
            wt_v_prof.set_xdata(wt_v_plot)
            wt_h_prof.set_ydata(wt_h_plot)
            wt_v_fill.set_xdata(wt_v_plot)
            wt_h_fill.set_xdata(wt_h_plot)   
            fig.canvas.draw_idle()
    
    def on_close(event):
        get_ipython().run_line_magic('matplotlib', 'inline')
    
    if interactive == True:
        fig.canvas.mpl_connect('motion_notify_event', on_move_dem)
        fig.canvas.mpl_connect('motion_notify_event', on_move_wt)
    
    fig.canvas.mpl_connect('close_event', on_close)

#%% Notes

# fig = plt.figure(figsize=(11,6))
# gs = fig.add_gridspec(3,3)
# ax1 = fig.add_subplot(gs[:, 0])
# ax2 = fig.add_subplot(gs[0, 1])
# ax3 = fig.add_subplot(gs[1, 1])
# ax4 = fig.add_subplot(gs[2, 1])
# ax5 = fig.add_subplot(gs[:, 2])
# fig.tight_layout()
# fig.savefig(self.pngdir + name_fig)
# plt.close()