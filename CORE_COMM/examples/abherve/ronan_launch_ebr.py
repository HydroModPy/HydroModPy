# -*- coding: utf-8 -*-
"""
Created on Wed Jan 26 10:49:18 2022

@author: ronan
"""

#%% LIBRARIES MODULES

# General
import sys
from os.path import dirname, abspath
DIR = dirname(dirname(dirname(abspath(__file__))))
sys.path.append(DIR)
import numpy as np
import pandas as pd
from osgeo import gdal, osr
import matplotlib.pyplot as plt

import glob
import geopandas as gpd
from shapely.geometry.polygon import LineString, Polygon
from shapely.ops import linemerge, unary_union, polygonize
from datetime import datetime
import os
import re
from matplotlib.dates import YearLocator, MonthLocator, DateFormatter
import scipy.stats as sp
import shapely.geometry as SG
import matplotlib.pylab as pl
import math
# import seaborn as sns
from pyproj import Transformer
from mpl_toolkits.axes_grid1 import make_axes_locatable
from matplotlib.colors import Normalize
from matplotlib import cm
import matplotlib as mpl
import rasterio
import fnmatch
import deepdish as dd
import matplotlib.dates as mdates
import seaborn as sns

# Plot
from matplotlib_scalebar.scalebar import ScaleBar
from rasterio.plot import show
from matplotlib.colors import LightSource
import earthpy.spatial as es
import earthpy.plot as ep

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
               
#%HYDROMODPY MODULES
                    
from watershed import watershed_root, watershed_display, forcing
from watershed.data import climatic
from tools import toolbox, vtk
from groundwater_flow import visualization, modflow_display
from calibration import calib_root

# LAYOUT PLOT

fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% CLASS FUNCTIONS

def fmt_xaxes(ax, years_maj, years_min):
    yearsmaj = mdates.YearLocator(years_maj)   # every year
    yearsmin = mdates.YearLocator(years_min)
    # monthsmaj = mdates.MonthLocator(6)  # every month
    # monthsmin = mdates.MonthLocator(3)
    # months_fmt = mdates.DateFormatter('%m') #b = name of month ?
    years_fmt = mdates.DateFormatter('%Y')
    ax.xaxis.set_major_locator(yearsmaj)
    ax.xaxis.set_minor_locator(yearsmin)
    ax.xaxis.set_major_formatter(years_fmt)

def add_subplot_axes(ax,rect,axisbg='w'):
    fig = plt.gcf()
    box = ax.get_position()
    width = box.width
    height = box.height
    inax_position  = ax.transAxes.transform(rect[0:2])
    transFigure = fig.transFigure.inverted()
    infig_position = transFigure.transform(inax_position)    
    x = infig_position[0]
    y = infig_position[1]
    width *= rect[2]
    height *= rect[3]  # <= Typo was here
    # subax = fig.add_axes([x,y,width,height],facecolor=facecolor)  # matplotlib 2.0+
    subax = fig.add_axes([x,y,width,height])  # matplotlib 2.0+
    # subax = fig.add_axes([x,y,width,height],axisbg=axisbg)
    x_labelsize = subax.get_xticklabels()[0].get_size()
    y_labelsize = subax.get_yticklabels()[0].get_size()
    x_labelsize *= rect[2]**0.5
    y_labelsize *= rect[3]**0.5
    subax.xaxis.set_tick_params(labelsize=x_labelsize)
    subax.yaxis.set_tick_params(labelsize=y_labelsize)
    return subax

def colorFader(c1,c2,mix=0): #fade (linear interpolate) from color c1 (at mix=0) to c2 (mix=1)
    c1=np.array(mpl.colors.to_rgb(c1))
    c2=np.array(mpl.colors.to_rgb(c2))
    return mpl.colors.to_hex((1-mix)*c1 + mix*c2)
c1='navy' #blue
c2='deepskyblue' #green
n=500
# fig, ax = plt.subplots(figsize=(8, 5))
# for x in range(n+1):
#     ax.axvline(x, color=colorFader(c1,c2,x/n), linewidth=4) 
# plt.show()

import numpy as np
import matplotlib
import matplotlib.pyplot as plt
from mpl_toolkits.axes_grid1 import AxesGrid

class MidpointNormalize(mpl.colors.Normalize):
    def __init__(self, vmin=None, vmax=None, vcenter=None, clip=False):
        self.vcenter = vcenter
        super().__init__(vmin, vmax, clip)

    def __call__(self, value, clip=None):
        # I'm ignoring ed values and all kinds of edge cases to make a
        # simple example...
        # Note also that we must extrapolate beyond vmin/vmax
        x, y = [self.vmin, self.vcenter, self.vmax], [0, 0.5, 1.]
        return np.ma.masked_array(np.interp(value, x, y,
                                            left=-np.inf, right=np.inf))

    def inverse(self, value):
        y, x = [self.vmin, self.vcenter, self.vmax], [0, 0.5, 1]
        return np.interp(value, x, y, left=-np.inf, right=np.inf)

def shiftedColorMap(cmap, start=0, midpoint=0.5, stop=1.0, name='shiftedcmap'):
    '''
    Function to offset the "center" of a colormap. Useful for
    data with a negative min and positive max and you want the
    middle of the colormap's dynamic range to be at zero.

    Input
    -----
      cmap : The matplotlib colormap to be altered
      start : Offset from lowest point in the colormap's range.
          Defaults to 0.0 (no lower offset). Should be between
          0.0 and `midpoint`.
      midpoint : The new center of the colormap. Defaults to 
          0.5 (no shift). Should be between 0.0 and 1.0. In
          general, this should be  1 - vmax / (vmax + abs(vmin))
          For example if your data range from -15.0 to +5.0 and
          you want the center of the colormap at 0.0, `midpoint`
          should be set to  1 - 5/(5 + 15)) or 0.75
      stop : Offset from highest point in the colormap's range.
          Defaults to 1.0 (no upper offset). Should be between
          `midpoint` and 1.0.
    '''
    cdict = {
        'red': [],
        'green': [],
        'blue': [],
        'alpha': []
    }

    # regular index to compute the colors
    reg_index = np.linspace(start, stop, 257)

    # shifted index to match the data
    shift_index = np.hstack([
        np.linspace(0.0, midpoint, 128, endpoint=False), 
        np.linspace(midpoint, 1.0, 129, endpoint=True)
    ])

    for ri, si in zip(reg_index, shift_index):
        r, g, b, a = cmap(ri)

        cdict['red'].append((si, r, r))
        cdict['green'].append((si, g, g))
        cdict['blue'].append((si, b, b))
        cdict['alpha'].append((si, a, a))

    newcmap = matplotlib.colors.LinearSegmentedColormap(name, cdict)
    plt.register_cmap(cmap=newcmap)

    return newcmap

def select_period(df, first, last):
    df = df[(df.index.year>=first) & (df.index.year<=last)]
    return df

def linregress(inx,iny):
    x=np.array(inx, dtype=float)
    y=np.array(iny, dtype=float)
    xmas = np.ma.masked_array(x,mask=np.isnan(y)).compressed()
    ymas = np.ma.masked_array(y,mask=np.isnan(y)).compressed()
    slope, intercept, r_value, p_value, std_err = sp.linregress(xmas,ymas)    
    xf = np.linspace(min(x),max(x),100)
    xf1 = xf.copy()
    xf1 = pd.to_datetime(xf1)
    yf = (slope*xf)+intercept
    center_x = xf.mean()
    center_y = yf.mean()
    lenght_reg = [[xf.min(),xf.max()],[yf.min(),yf.max()]]
    return (center_x,center_y, slope, intercept, r_value, p_value, std_err, lenght_reg)

def sklearn_linregress(inx, iny):
    from sklearn import datasets, linear_model
    from sklearn.metrics import mean_squared_error, r2_score
    regr = linear_model.LinearRegression()
    regr.fit(inx, iny)
    y_pred = regr.predict(inx)
    print("Slope: %.2f" % regr.coef_[0])
    print("Mean squared error: %.2f" % mean_squared_error(iny, y_pred))
    print("Coefficient of determination: %.2f" % r2_score(iny, y_pred))
    print("Intercept: %.2f" % regr.intercept_)
    plt.scatter(inx, iny, color="black")
    plt.plot(inx, y_pred, color="blue", linewidth=3)
    plt.xticks(())
    plt.yticks(())
    plt.show()
# sklearn_linregress(hyst.xw.values.reshape(len(hyst.xw),1),
#                     hyst.yw.values)
    
def line(x, line_point1, line_point2, get_eq=False):
    m = (line_point1[1] - line_point2[1])/(line_point1[0] - line_point2[0])
    b = line_point1[1] - m*line_point1[0]
    if get_eq:
        return m, b
    else:
        return m*x + b

def perpendicular_line(x, random_point, line_point1, line_point2, get_eq=False):
    m, b = line(0, line_point1, line_point2, True)
    m2 = -1/m
    b2 = random_point[1] - m2*random_point[0]
    if get_eq:
        return m2, b2
    else:
        return m2*x + b2
    
def cut_polygon_by_line(polygon, line):
    merged = linemerge([polygon.boundary, line])
    borders = unary_union(merged)
    polygons = polygonize(borders)
    return list(polygons)

def plot(shapely_objects, figure_path='fig.png'):
    boundary = gpd.GeoSeries(shapely_objects)
    boundary.plot(color=['red', 'green'])

# CLASS

class Hysteresis:
    
    def __init__(self, df, name):
        
        self.df = df
        self.name = name
    
    def prepare_xy_raw(self):
        
        self.first = self.df.first_valid_index().year
        self.last = self.df.last_valid_index().year
        self.years = self.df.index.year.unique()
        
        self.x = self.df.x
        self.y = self.df.y
        self.wy = pd.Series(self.df.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],[1,2,3,4,5,6,7,8,9,10,11,12])
        
        self.xi = self.x.groupby([lambda x: x.month]).mean()
        self.yi = self.y.groupby([lambda y: y.month]).mean()
        self.wyi = np.arange(1,12+1,1)
        
        self.xe = pd.DataFrame()
        self.xe['q25'] = (self.x.groupby(self.x.index.month).quantile(0.25))
        self.xe['q75'] = (self.x.groupby(self.x.index.month).quantile(0.75))

        self.ye = pd.DataFrame()
        self.ye['q25'] = (self.y.groupby(self.y.index.month).quantile(0.25))
        self.ye['q75'] = (self.y.groupby(self.y.index.month).quantile(0.75))
    
        self.xiline = self.xi.append(self.xi.iloc[[0]])
        self.xiline.index = np.arange(1,14,1)
        self.yiline = self.yi.append(self.yi.iloc[[0]])
        self.yiline.index = np.arange(1,14,1)
        
        self.date_range = pd.date_range(str(self.first), str(self.last), freq='M')
        self.xw = self.x.copy()
        self.xw.index = self.date_range
        self.xrecap = pd.DataFrame(columns=self.years)
        for year in self.years[0:-1]:
            self.xrecap[year] = self.xw[self.xw.index.year == year].values
        self.xrecap.index = [10,11,12,1,2,3,4,5,6,7,8,9]
        self.xrecap = self.xrecap.sort_index()       
        self.xrecap['xi'] = self.xi
        self.xrecap = self.xrecap.dropna(axis=1, how='all')
        
        self.yw = self.y.copy()
        self.yw.index = self.date_range
        self.yrecap = pd.DataFrame(columns=self.years)        
        for year in self.years[0:-1]:
            self.yrecap[year] = self.yw[self.yw.index.year == year].values
        self.yrecap.index = [10,11,12,1,2,3,4,5,6,7,8,9]
        self.yrecap = self.yrecap.sort_index()              
        self.yrecap['yi'] = self.yi
        self.yrecap = self.yrecap.dropna(axis=1, how='all')
                    
    def plot_xy_obs(self, x_label, y_label, x_lim, y_lim, cmap):
        
        logs = ['linear', 'log']
        
        fig, axs = plt.subplots(1,2,figsize=(7, 3.5))
        fig.add_subplot(111, frameon=False)
        plt.tick_params(labelcolor='none', top=False, bottom=False, left=False, right=False) # hide tick and tick label of the big axis
        axs = axs.ravel()
        
        for i, log in enumerate(logs):
            
            ax = axs[i]
            scat = ax.scatter(self.x, self.y, c=self.wy, cmap=cmap, marker="o", 
                              s=10, vmin=1, vmax=12, alpha=0.75, ec='none')
            ax.plot(self.xi, self.yi, marker="o", markersize=9, markeredgecolor='black', 
                    markerfacecolor='white', linestyle = 'None') 
            for k in self.wyi:
                ax.annotate(k,(self.xi[k],self.yi[k]), family='sans-serif', fontsize=5, 
                            color='black', weight="bold", ha='center', va='center')
            if log != 'log':
                maxi = max(max(x_lim),max(y_lim))
                mini = min(min(x_lim),min(y_lim))
                ax.plot((mini,maxi), (mini,maxi), 
                            linestyle='-', color='grey', linewidth=1.5, zorder=0)
            else:
                # ax.plot(np.linspace(*ax.get_xlim()), np.linspace(*ax.get_xlim()), 
                #         linestyle='-', color='grey', linewidth=1.5, zorder=0)
                ax.plot(np.linspace(0.1,max(x_lim),50), np.linspace(0.1,max(x_lim),50), 
                        linestyle='-', color='grey', linewidth=1.5, zorder=0)
            ax.errorbar(self.xi, self.yi,
                        yerr=np.vstack([self.yi-self.ye.q25, self.ye.q75-self.yi]),
                        xerr=np.vstack([self.xi-self.xe.q25, self.xe.q75-self.xi]),
                        ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
                        capthick=0.5, zorder=1)
            ax.plot(self.xiline, self.yiline, linestyle = '-', lw=1.5, color='k', zorder=-1)
            
            ax.set_xlabel(x_label)
            if i == 0:
                ax.set_ylabel(y_label)
                ax.set_title(self.name)
            else:
                ax.set_title(str(self.first)+'-'+str(self.last))
            ax.set_xlim(x_lim[0], x_lim[1])
            ax.set_ylim(y_lim[0]+0.1, y_lim[1])
            ax.set_xticks(np.linspace(x_lim[0], x_lim[1], 5))
            ax.set_yticks(np.linspace(y_lim[0]+0.1, y_lim[1], 5))
            
            ax.set_yscale(log)
            
        plt.tight_layout()
        position = fig.add_axes([0.95,0.32,0.02,0.5])
        cb = plt.colorbar(scat,cax=position)
        x1 = [1,2,3,4,5,6,7,8,9,10,11,12]
        squad = ['Oct','Nov','Dec','Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep']
        cb.set_ticks(x1)
        cb.set_ticklabels(squad)
        cb.ax.tick_params(labelsize=10)
        cb.update_ticks()

        # fig.savefig(path+'.png', dpi=300, bbox_inches='tight')
    
    def compute_xy_metrics(self, temporal, space, norm):
                
        self.xrecapl = self.xrecap.copy()
        self.xrecapl = self.xrecapl.append(self.xrecapl.iloc[[0]])
        self.xrecapl.index = np.arange(1,14,1)
        
        self.yrecapl = self.yrecap.copy()
        self.yrecapl = self.yrecapl.append(self.yrecapl.iloc[[0]])
        self.yrecapl.index = np.arange(1,14,1)
        
        if norm == True:
            self.xrecapl = (self.xrecapl - self.xrecapl.min()) / \
                           (self.xrecapl.max() - self.xrecapl.min())
            self.yrecapl = (self.yrecapl - self.yrecapl.min()) / \
                         (self.yrecapl.max() - self.yrecapl.min())

        if temporal == False:
            columns_x = self.xrecapl.columns[-1:]
            columns_y = self.yrecapl.columns[-1:]

        else:
            columns_x = self.xrecapl.columns[:]
            columns_y = self.yrecapl.columns[:]
            if space!=0 :
                compt=-1
                itneg=space-1
                for i, col in enumerate(sorted(columns_y[:-1], key=int, reverse=True)):
                    self.xspace = self.xrecapl.iloc[:, itneg:compt]
                    self.yspace = self.yrecapl.iloc[:, itneg:compt]
                    if len(self.xspace.columns) == abs(space):
                        self.xrecapl[col] = self.xspace.mean(axis=1).values
                        self.yrecapl[col] = self.yspace.mean(axis=1).values
                    itneg-=1
                    compt-=1
                self.xrecapl = self.xrecapl.iloc[:,abs(space):]
                self.yrecapl = self.yrecapl.iloc[:,abs(space):]
                columns_x = self.xrecapl.columns
                columns_y = self.yrecapl.columns
        
        # fig, ax = plt.subplots(1,1, figsize=(4,3))
        # n = len(columns_x)
        # colors = pl.cm.jet(np.linspace(0,1,n))        
        
        self.dfmet = pd.DataFrame(columns=[])
        
        for i, (colx, coly) in enumerate(zip(columns_x, columns_y)):
            
            # print(colx)
            
            self.xlist = self.xrecapl[colx]
            self.ylist = self.yrecapl[coly]
            
            self.data = pd.DataFrame()
            self.data['inx'] = self.xlist.values
            self.data['iny'] = self.ylist.values
            
            # ax.scatter(self.data.inx, self.data.iny, s=0, color=colors[i], cmap='jet')
            # ax.plot(self.data.inx,self.data.iny, linestyle = '-', lw=1, color=colors[i], zorder=-1)
            # ax.set_yscale('log') 
            # if colx == 'xi':
            #     if temporal==True:
            #         ax.set_title(str(columns_x[0]) + ' - ' + str(columns_x[-2]))
            #         if space!=0:
            #             ax.set_title(str(columns_x[0]) + ' - ' + str(columns_x[-2]) + ' / ' + str(abs(space)))
            #     else:
            #         ax.set_title(str(self.xrecapl.columns[0]) + ' - ' + str(self.xrecapl.columns[-2]))
            #     ax.plot(self.data.inx,self.data.iny, linestyle = '-', lw=3, color='k', zorder=-1)
            
            # ax.set_xscale('log')
            # plt.close()
              
            self.qmax = self.ylist.max()
            self.qmin = self.ylist.min()
            self.qmed = self.ylist.median()
            self.qmean = self.ylist.mean()
            self.absmin = self.xlist.min()
            self.absmax = self.xlist.max()
            self.q10 = self.ylist.quantile(0.1)
            self.q90 = self.ylist.quantile(0.9)
            self.centerx = self.xlist.mean()
            self.centery = self.ylist.mean()
            self.center = self.centerx / self.centery
            
            self.q0 = self.ylist.iloc[10]
            self.qmid = (self.q0+self.qmax)/2
            self.qsep = (self.qmin+self.qmax)/2
            
            line_loop = SG.LineString(list(zip(self.data.inx,self.data.iny)))            
            line_qmid = SG.LineString([(min(self.data.inx), self.qmid), 
                                        (max(self.data.inx), self.qmid)])
            self.inters_qmid_loop = np.array(line_loop.intersection(line_qmid))

            if len(self.inters_qmid_loop)>=2:
                try:
                    max_hi = np.amax(self.inters_qmid_loop, axis=0)[0]
                    min_hi = np.amin(self.inters_qmid_loop, axis=0)[0]
                    self.hi = max_hi - min_hi
                except:
                    max_hi = np.nan
                    min_hi = np.nan
                    self.hi = np.nan
                    pass
            else:
                max_hi = np.nan
                min_hi = np.nan
                self.hi = np.nan
            
            id_min = self.data.iny.index[self.data.iny == self.data.iny.min()].values[0]
            id_max = self.data.iny.index[self.data.iny == self.data.iny.max()].values[0]
            xmax = self.data.inx[id_max]
            xmin = self.data.inx[id_min]
            
            x_lim = [self.data.inx.min(), self.data.inx.max()]    
            y_lim = [self.data.iny.min(), self.data.iny.max()]    
            maxi = max(max(x_lim),max(y_lim))
            mini = min(min(x_lim),min(y_lim))
            
            self.long = np.sqrt( (xmax - xmin)**2 + (self.qmax - self.qmin)**2 )
            x_m_point = (self.data.inx[id_min] + self.data.inx[id_max])/2
            y_m_point = (self.qmin + self.qmax)/2
            long_min = (xmin, self.qmin)
            long_max = (xmax, self.qmax)
            
            id_y_min = self.data.inx.index[self.data.inx == self.data.inx.min()].values[0]
            id_y_max = self.data.inx.index[self.data.inx == self.data.inx.max()].values[0]
            themax = self.data.iny[id_y_max]
            themin = self.data.iny[id_y_min]
            abs_min = (self.absmin, themin)
            abs_max = (self.absmax, themax)
            
            abs_x = np.linspace(abs_min[0], abs_max[0], 100)
            abs_y = np.linspace(abs_min[1], abs_max[1], 100)
            reg_abs = linregress(abs_x, abs_y)
            self.reg_stat_abs = pd.DataFrame(columns=['center_x','center_y','slope','intercept',
                                              'r_value','p_value','std_err','lenght_reg'])
            self.reg_stat_abs.loc[len(self.reg_stat_abs)] = reg_abs
            self.slope_abs = self.reg_stat_abs.slope[0]
            line_abs = SG.LineString([abs_min, abs_max])
            
            long_x = np.linspace(long_min[0], long_max[0], 100)
            long_y = np.linspace(long_min[1], long_max[1], 100)
            reg = linregress(long_x, long_y)
            self.reg_stat = pd.DataFrame(columns=['center_x','center_y','slope','intercept',
                                              'r_value','p_value','std_err','lenght_reg'])
            self.reg_stat.loc[len(self.reg_stat)] = reg
            self.slope = self.reg_stat.slope[0]
            
            domain = np.linspace(long_min[0], long_max[0])
            try:
                perp_line = [perpendicular_line(x, [x_m_point, y_m_point],
                                            list(long_min), list(long_max)) for x in domain]
                line_perp = SG.LineString([(min(domain), max(perp_line)), (max(domain), (min(perp_line)))])
            except:
                pass
            
            try:
                self.inters_perp_loop = np.array(line_loop.intersection(line_perp))
                if len(self.inters_perp_loop)>=2:
                    try:
                        max_xs = np.amax(self.inters_perp_loop, axis=0)[0]
                        min_xs = np.amin(self.inters_perp_loop, axis=0)[0]
                        max_ys = np.amax(self.inters_perp_loop, axis=0)[1]
                        min_ys = np.amin(self.inters_perp_loop, axis=0)[1]
                        self.short_plus = np.sqrt( (x_m_point - min_xs)**2 + (y_m_point - max_ys)**2 )
                        self.short_minus = np.sqrt( (x_m_point - max_xs)**2 + (y_m_point - min_ys)**2 )
                        self.short = self.short_plus + self.short_minus
                        self.excent = self.long / self.short
                    except:
                        self.short_plus = np.nan
                        self.short_minus = np.nan
                        self.short = np.nan
                        self.excent = np.nan
                        pass
                else:
                    self.short_plus = np.nan
                    self.short_minus = np.nan
                    self.short = np.nan
                    self.excent = np.nan
            except:
                pass
            
            polyg_loop = Polygon(tuple(self.data.itertuples(index=False, name=None)))
            line_long = SG.LineString([long_min, long_max])
            xpolyg, ypolyg = polyg_loop.exterior.xy
            maxi = max(max(x_lim),max(y_lim))
            mini = min(min(x_lim),min(y_lim))
            line_oneone = SG.LineString([(mini,mini), (maxi,maxi)])
            # areas = cut_polygon_by_line(polyg_loop, line_long)
            areas = cut_polygon_by_line(polyg_loop, line_oneone)
            
            try:
                self.area_plus = areas[1].area
                self.area_minus = areas[0].area
                self.area = polyg_loop.area
            except:
                self.area_plus = np.nan
                self.area_minus = np.nan
                self.area = np.nan
                pass
            try:
                self.area = polyg_loop.area
            except:
                pass
            
            reg = linregress(self.xlist, self.ylist)
            reg = linregress(self.xw, self.yw)
            self.reg_stat_reg = pd.DataFrame(columns=['center_x','center_y','slope','intercept',
                                              'r_value','p_value','std_err','lenght_reg'])
            self.reg_stat_reg.loc[len(self.reg_stat_reg)] = reg
            self.slope_reg = self.reg_stat_reg.slope[0]
                        
            # Storage
            self.dfmet.loc[colx, 'qmax'] = self.qmax
            self.dfmet.loc[colx, 'qmin'] = self.qmin
            self.dfmet.loc[colx, 'qmed'] = self.qmed
            self.dfmet.loc[colx, 'qmean'] = self.qmean
            self.dfmet.loc[colx, 'q10'] = self.q10
            self.dfmet.loc[colx, 'q90'] = self.q90
            self.dfmet.loc[colx, 'q0'] = self.q0
            self.dfmet.loc[colx, 'qmid'] = self.qmid
            self.dfmet.loc[colx, 'qsep'] = self.qsep
            self.dfmet.loc[colx, 'center'] = self.center
            self.dfmet.loc[colx, 'hi'] = self.hi
            self.dfmet.loc[colx, 'long'] = self.long
            try:
                self.dfmet.loc[colx, 'short'] = self.short
            except:
                pass
            try:
                self.dfmet.loc[colx, 'short_p'] = self.short_plus
                self.dfmet.loc[colx, 'short_n'] = self.short_minus
            except:
                pass
            try:
                self.dfmet.loc[colx, 'excent'] = self.excent
            except:
                pass
            self.dfmet.loc[colx, 'area'] = self.area
            self.dfmet.loc[colx, 'area_p'] = self.area_plus
            self.dfmet.loc[colx, 'area_n'] = self.area_minus
            self.dfmet.loc[colx, 'area_r'] =  self.area_minus / self.area_plus
            self.dfmet.loc[colx, 'slope'] = self.slope
            self.dfmet.loc[colx, 'slope_abs'] = self.slope_abs
            self.dfmet.loc[colx, 'slope_reg'] = self.slope_reg
            
            '''
            if temporal == False:
                
                fig, ax = plt.subplots(1,1, figsize=(5,5))
                ax.plot(*line_loop.xy, lw=2, color='dodgerblue')
                ax.plot(*line_qmid.xy, ls=':', lw=2, color='grey')
                ax.plot(*line_long.xy, ls='-', lw=2, color='gold')
                ax.plot(*line_oneone.xy, lw=2, color='k')
                ax.plot(*line_perp.xy, ls='--', lw=2, color='gold')
                ax.plot(*line_abs.xy, ls='-', lw=2, color='darkorange')
                ax.plot(np.linspace(abs_min, abs_max, 100),
                        self.reg_stat_reg.intercept[0] + self.slope_reg*np.linspace(abs_min, abs_max, 100),
                        ls='-', lw=2, color='red')
                
                # plt.gca().set_aspect('equal', adjustable='box')
                plt.axis('square')
                plt.xlim(mini, maxi)
                plt.ylim(mini, maxi)
            '''
            
        # self.dfmet.to_csv('Metrics_'+'Obs_'+self.name+'_'+str(space)+'.csv', sep=';')

    def plot_xy_mod(self, ax, x_label, y_label, x_lim, y_lim, cmap, scale):
        
        ax = ax
        scat = ax.scatter(self.x, self.y, c=self.wy, cmap=cmap, marker="o", 
                          s=10, vmin=1, vmax=12, alpha=0.75, ec='none')
        ax.plot(self.xi, self.yi, marker="o", markersize=9, markeredgecolor='black', 
                markerfacecolor='white', linestyle = 'None') 
        for k in self.wyi:
            ax.annotate(k,(self.xi[k],self.yi[k]), family='sans-serif', fontsize=5, 
                        color='black', weight="bold", ha='center', va='center')
        if scale != 'log':
            try:
                maxi = max(max(x_lim),max(y_lim))
                mini = min(min(x_lim),min(y_lim))
                ax.plot((mini,maxi), (mini,maxi), 
                            linestyle='-', color='grey', linewidth=1.5, zorder=0)
            except:
                pass
        else:
            # ax.plot(np.linspace(*ax.get_xlim()), np.linspace(*ax.get_xlim()), 
            #         linestyle='-', color='grey', linewidth=1.5, zorder=0)
            ax.plot(np.linspace(0.1,max(x_lim),50), np.linspace(0.1,max(x_lim),50), 
                    linestyle='-', color='grey', linewidth=1.5, zorder=0)
        ax.errorbar(self.xi, self.yi,
                    yerr=np.vstack([self.yi-self.ye.q25, self.ye.q75-self.yi]),
                    xerr=np.vstack([self.xi-self.xe.q25, self.xe.q75-self.xi]),
                    ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
                    capthick=0.5, zorder=1)
        ax.plot(self.xiline, self.yiline, linestyle = '-', lw=1.5, color='k', zorder=-1)
        
        ax.set_xlabel(x_label)
        ax.set_ylabel(y_label)
        ax.set_title(self.name)
        ax.set_title(str(self.first)+'-'+str(self.last))
        try:
            ax.set_xlim(x_lim[0], x_lim[1])
            ax.set_ylim(y_lim[0]+0.1, y_lim[1])
            ax.set_xticks(np.linspace(x_lim[0], x_lim[1], 5))
            ax.set_yticks(np.linspace(y_lim[0]+0.1, y_lim[1], 5))
        except:
            pass
        
        ax.set_yscale(scale)
            
        plt.tight_layout()
        
        # position = fig.add_axes([0.95,0.32,0.02,0.5])
        # cb = plt.colorbar(scat,cax=position)
        # x1 = [1,2,3,4,5,6,7,8,9,10,11,12]
        # squad = ['Oct','Nov','Dec','Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep']
        # cb.set_ticks(x1)
        # cb.set_ticklabels(squad)
        # cb.ax.tick_params(labelsize=10)
        # cb.update_ticks()

#%% ---- CATCH

#%% PATH WATERSHED

git_path = "D:/Users/abherve/GITHUB/HydroModPy/CORE_COMM/"
# Path to the data folder
data_path = "C:/Users/ronan/OneDrive/_HydroDataPy/"
# Path where the results will be stored
out_path = "D:/Users/abherve/EBR/"
# Figure folder outputs
res_path = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/15_results/EBR_v1/'

dems_path = data_path + 'DEM/France/' # reginal DEM or conceptual DEM
shp_path = data_path + 'SHAPEFILE/' # if you want run a model from a shapefile
modflow_path = data_path + 'SOFTWARE/MODFLOW/' # add bin/ folder with necessary .exe

# surfex_path =  data_path + 'CLIMATE/France/SURFEX/Brittany/'
surfex_path =  data_path + 'CLIMATE/France/SURFEX/Rennes/' # add surfex models in .h5 format (France scale, else, specify None)
drias_path = data_path + 'CLIMATE/France/DRIAS/Bretagne/'
geology_path = data_path + 'GEOLOGY/France/Layer/' # add geologic layers
oceanic_path = data_path + 'OCEANIC/' # add specific sea level files
hydrology_path = data_path + 'HYDROLOGY/France/Hydrographic/EBR/' # add hydrographic shapefiles
hydrometry_path = data_path + 'HYDROLOGY/France/Hydrometry/' # add hydrometry data for automatic download
intermittency_path = data_path + 'HYDROLOGY/France/Intermittency/' # add intermittency data for automatic download
piezometry_path = False # add piezometry data for automatic download
subbasin_path = True # generate subbasins from stations or manual points

# dem_name = "BDALTI_75m_EBR.tif" # name of dem
dem_name = "BDALTI_75m_MA.tif" # name of dem
from_shp = None # specify a path if process start from a given shapefile
from_dem = False # True or False if the process start from a given DEM of xyz file
cell_size = None # specify new resolution from a given DEM or None

from_xy = []

# Depending on the choices
dem_path = dems_path + dem_name

library_path = res_path + '_data/' + 'watershed_library.csv' # each row is a study site with outlet coordinates

# watershed_names = ['Horn','Leff','Canut','Nancon','Arguenon','Flume','Gael']
# code_names = ['J3014330','J1803010','J7513010','J0014010','J1105810','J7214010','J7313010']

watershed_names = [
                   'Cheze',
                   'Canut',
                   'Gael',
                   'Monfort',
                   'Mordelles',
                   'Vaunoise',
                   'Jouan',
                   'Neal',
                   'Rophemel',
                   'Nancon',
                   'Roche',
                   'Minette',
                   'Loisance',
                   'Moulin',
                   'Chanut',
                   'Drains',
                   'Dam',
                   'Frame'
                   ]

code_names = ['J736422001',
              'J751301001',
              'J731301001',
              'J735301001',
              None,
              'J737311001',
              'J061161001',
              'J062661001',
              'J062161001',
              'J001401001',
              None,
              None,
              None,
              'J014401001',
              None,
              None,
              None,
              None,
              ]

site_names = np.column_stack((watershed_names,code_names))

types_obs = ['perennial','complete'] # list of shapefile name layers for clip hydrology
fields_obs = ['fid','persiatnc']

#%% GENERATE WATERSHED

load = True

# site_names = [['Nancon','J001401001']]
# site_names = [['Cheze','x']]

for site_name in site_names[:]:

    watershed_name = site_name[0]
    code_name = site_name[1]
        
    if (watershed_name != 'Chanut') & (watershed_name != 'Drains') & (watershed_name != 'Frame'):
        print('##### '+watershed_name.upper()+' #####')
        BV = watershed_root.Watershed(watershed_name=watershed_name,
                                      dem_path=dem_path, 
                                      out_path=out_path,
                                      modflow_path=modflow_path,
                                      library_path=library_path,
                                      load=load,
                                      from_shp=from_shp,
                                      from_dem=from_dem,
                                      from_xy=from_xy,
                                      cell_size=cell_size)
    
    if (watershed_name == 'Chanut') & (watershed_name == 'Drains') & (watershed_name == 'Frame'):
        print('##### '+watershed_name.upper()+' #####')
        BV = watershed_root.Watershed(watershed_name=watershed_name,
                                      dem_path=dem_path, 
                                      out_path=out_path,
                                      modflow_path=modflow_path,
                                      library_path=library_path,
                                      load=load,
                                      from_shp=res_path+'sig/'+watershed_name+'.shp',
                                      from_dem=from_dem,
                                      from_xy=from_xy,
                                      cell_size=cell_size)
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots  
  
    print(BV.geographic.area.round(2))
    print(BV.geographic.slope.round(2))
    
    watershed_display.watershed_dem(BV)
    watershed_display.watershed_local(dem_path, BV)
        
#%% DATA WATERSHED

# surfex_path =  'G:/SURFEX/DATA/COREC_h5/' # add surfex models in .h5 format (France scale, else, specify None)

# site_names = [['Drains',None]]

site_names = [['Cheze', None]]

for site_name in site_names[:]:

    watershed_name = site_name[0]
    code_name = site_name[1]
           
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)
    
    print('##### '+watershed_name.upper()+' #####')

    # BV.add_geology(geology_path)
    # BV.add_hydrology(hydrology_path, types_obs=types_obs, fields_obs=fields_obs)
    # BV.add_oceanic(oceanic_path)
    # BV.add_hydrometry(hydrometry_path)
    # BV.add_intermittency(intermittency_path)
    # BV.add_subbasin()
    BV.add_surfex(surfex_path)

    # BV.add_drias(drias_path,
    #              list_models=['all'],
    #              list_vars=['all'])

    # BV.add_hydrodynamic()
    # BV.add_forcing()
    
    # watershed_display.watershed_dem(BV)
    # watershed_display.watershed_local(dem_path, BV)
    
    # try:
    #     if (watershed_name == 'Monfort') | (watershed_name == 'Roche'):
    #         BV.add_piezometry()
    # except:
    #     pass
    
#%% HYDROPORTAIL SERIES

series_path = res_path + '_data/hydrometric/' +'export_hydro_series.csv'
series = pd.read_csv(series_path, sep=';', index_col = 4, parse_dates= True)
series = series.iloc[1:]
series.index.name = None
series.index = pd.to_datetime(series.index)
series['<ResObsElaborHydro>'] = pd.to_numeric(series['<ResObsElaborHydro>'])

for site_name in site_names[:]:

    watershed_name = site_name[0]
    code_name = site_name[1]
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots  
  
    # print('##### '+watershed_name.upper()+' #####')
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)
    area = BV.geographic.area
    
    if code_name != None:
        print('##### '+watershed_name.upper()+' #####')
        serie = series[series['<CdStationHydro>']==code_name]
        serie = serie['<ResObsElaborHydro>']
        serie = serie.rename('Q')
        serie = ( serie / 1000 ) # L/s to m3/s

        # fig, ax = plt.subplots(1,1, figsize=(10,5), dpi=300)
        # ax.scatter(serie.index, serie)
        # ax.set_title(watershed_name)
        # ax.set_yscale('log')
        
        if watershed_name == 'Gael':
            serie = select_period(serie, 2008, 2022)
        
        if watershed_name != 'Vaunoise':
            serie.to_csv(stable_folder+'hydrometry/'+'Hydrometric_'+code_name+'.csv', sep=';')
        
        plt.plot(serie)
        
#%% ---- CALIB

#%% DICHOTOMY STREAMS

watershed_names = [
                    'Cheze',
                    'Canut',
                    'Gael',
                    'Monfort',
                    'Mordelles',
                    'Vaunoise',
                    'Jouan',
                    'Neal',
                    'Rophemel',
                    'Nancon',
                    'Roche',
                    'Minette',
                    'Loisance',
                    'Moulin',
                    'Chanut',
                    'Drains',
                    'Dam',
                   # 'Frame'
                   ]

hydrology_path = data_path + 'HYDROLOGY/France/Hydrographic/EBR/' # add hydrographic shapefiles

from calibration import calib_root, calib_dichotomy, calib_analysis, calib_exploration, calib_basis

for watershed_name in watershed_names[:] :
    
    print('##### '+watershed_name.upper()+' #####')

    types_obs = ['perennial','complete'] # list of shapefile name layers for clip hydrology
    fields_obs = ['fid','persistanc']
        
    df = pd.DataFrame(np.nan, index=range(1), columns=types_obs)
    
    for type_obs, field_obs in zip(types_obs, fields_obs):
   
        
        BV = watershed_root.Watershed(watershed_name=watershed_name,
                                      dem_path=dem_path, 
                                      out_path=out_path,
                                      load=True,
                                      modflow_path=modflow_path)
        BV.add_forcing()
        BV.add_hydrodynamic()
        
        area = BV.geographic.area
        
        stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
            
        BV.add_hydrology(hydrology_path, types_obs=[type_obs], fields_obs=[field_obs])
        
        print(BV.hydrology.streams)
        
        try:
            raw_path = stable_folder+'/'+'hydrometry/'
            Qobs_path = fnmatch.filter(os.listdir(raw_path), 'Hydrometric_*')[0]
            Qobs = pd.read_csv(raw_path+Qobs_path, sep=';', index_col=0, parse_dates=True)
            f_simu = Qobs.first_valid_index().year+1-5
            l_simu = Qobs.last_valid_index().year-1
            if l_simu == 2021:
                l_simu = 2019
            if f_simu < 1960:
                f_simu = 1960
        except:
            l_simu = 2019
            f_simu = 1960
        
        BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic',
                                          first_year = f_simu, last_year=l_simu, time_step = 'D',
                                          sim_state='steady') #

        # BV.hydrodynamic.update_porosity(0.1)
        # BV.hydrodynamic.update_hyd_cond(2)
        BV.hydrodynamic.update_nlay(1)
        BV.hydrodynamic.update_thickness(30)
        BV.hydrodynamic.update_bottom(None)
        BV.hydrodynamic.update_cond_decay(0)
        BV.hydrodynamic.update_thick_exp(1)
        
        params_df = pd.DataFrame(columns=['params',
                                          'init_values','lower_bounds','higher_bounds',
                                          'units','scale'])
        params_df.loc[0] = ['k1',8.64e-01,8.64e-03,8.64e+01,'m/j','lin']
        
        params_file = 'calib_dicot_hom_1v_k1'
        
        params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)

        # params_file = 'calib_dicot_het_2v_k1-k2'
        # params_file = 'calib_dicot_hom_2v_k1-n1'
        calib = calib_root.Calibration(params_file, BV, observations = ['streams'])
        
        dicot = calib.dichotomy(gap=1)

    for i, type_obs in enumerate(types_obs):
        
        typ_calib = 'streams_calibration'
        list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, typ_calib, '*.calib')),
                           key=os.path.getmtime)
        list_path = list_path[-len(types_obs):]
        name_file = list_path[i].split('\\')[-1]
        calib_file = os.path.join(BV.calibration_folder, params_file, typ_calib, name_file)
        test = calib_analysis.CalibAnalysis(calib_file)
        test.display_objective_function(save=None)
        
        koptim = test.calib['params_values'][-1]
        print(name_file)
        print(koptim)
        kr = koptim / test.calib['recharge']
        obj_func = test.calib['objective_function'][-1]
        
        # df.loc[0,watershed_name] = koptim / 24 / 3600
        # df.loc[1,watershed_name] = kr
        # df.loc[2,watershed_name] = obj_func
        
        df.loc[0,type_obs] = koptim / 24 / 3600
        df.loc[1,type_obs] = kr
        df.loc[2,type_obs] = obj_func
        
    df.to_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')
    df = pd.read_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')

#%% DICHOTOMY PLOT

watershed_names = [
                   'Cheze',
                   'Canut',
                   'Gael',
                   'Vaunoise',
                   'Neal',
                   'Jouan',
                   'Nancon',
                   'Moulin',
                   ]
watershed_names = watershed_names[::-1]

lito = {'Nancon':'tomato',
        'Moulin':'tomato',
        'Jouan':'darkorange',
        'Vaunoise':'violet',
        'Neal':'violet',
        'Gael':'violet',
        'Cheze':'darkgreen',
        'Canut':'darkgreen'}

styl = {'Nancon':'s',
        'Moulin':'s',
        'Jouan':'d',
        'Vaunoise':'o',
        'Neal':'o',
        'Gael':'o',
        'Cheze':'^',
        'Canut':'^'}

from matplotlib.ticker import (MultipleLocator, AutoMinorLocator)

fig, ax = plt.subplots(1,1, figsize=(4,3), sharex=True, sharey=True)
    
n = len(watershed_names)

cp=0
for idx, watershed_name in enumerate(watershed_names):
    
    site = watershed_name
    
    s='o'
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)
    
    df = pd.read_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')
    
    ax.axvline(df.perennial[0], color=lito[watershed_name], ls='-')
    ax.axvline(df.complete[0], color=lito[watershed_name], ls='--')
    
    ax.plot(df.perennial[0], cp,  color=lito[watershed_name], marker='s', ms=10, lw=0)
    ax.plot(df.complete[0], cp,  color=lito[watershed_name], marker='o', ms=10, lw=0)
    
    # plt.scatter(df.complete[0], np.sqrt(np.exp(df.complete[2])), color=lito[watershed_name], s=100)

    # ax.set_ylim(0.95)
    ax.set_xlim(4e-6, 1e-4)
    ax.set_xscale('log')

    cp+=1

ax.set_yticks(np.arange(0,8,1))
ax.set_yticklabels(watershed_names)
    
fig.tight_layout()

# outfig = plots_path + 'demgeol_steady/'
# if not os.path.exists(outfig):
#     os.makedirs(outfig)

geol_f = gpd.read_file(geology_path+'GEO001M_CART_FR_S_FGEOL_2154_CMYK.shp')
geol_s = gpd.read_file(geology_path+'GEO001M_CART_FR_L_STRUCT_2154_CMYK.shp')

for idx, watershed_name in enumerate(watershed_names):

    site = watershed_name
    
    s='o'
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots

    df = pd.read_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')
    
    fig, ax = plt.subplots(1, 1, figsize=(4,4), dpi=300)
    
    obs = 'complete'
    
    print('#################### SITE '+str(idx)+' PLOT '+' : '+site.upper()+' ####################')

    optim = BV.calibration_folder+'/'+'calib_dicot_hom_1v_k1/'+'streams_calibration/'+'_streams/'
    simflow = gpd.read_file(optim+'/simflow.shp')
    
    streams = gpd.read_file(stable_folder+'hydrology/'+obs+'.shp')
    polyg = gpd.read_file(stable_folder+'geographic/'+'watershed.shp')
    contour = gpd.read_file(stable_folder+'geographic/'+'watershed_contour.shp')
    
    bounds = contour.geometry.total_bounds
    xlim = ([bounds[0], bounds[2]])
    ylim = ([bounds[1], bounds[3]])

    dem = stable_folder+'geographic/'+'watershed_extent.tif'
    gdal.Translate(dem, gdal.Open(dem_path), 
                    projWin=[xlim[0],ylim[1],xlim[1],ylim[0]], noData=-99999)
    hill = stable_folder+'geographic/'+'watershed_extent_hill.tif'
    wbt.hillshade(dem, hill, azimuth=315.0, altitude=45.0, zfactor=2)
    
    dem = rasterio.open(stable_folder+'geographic/'+'watershed_extent.tif')
    hill = rasterio.open(stable_folder+'geographic/'+'watershed_extent_hill.tif')
    img = imageio.imread(stable_folder+'geographic/'+'watershed_extent.tif')
    # raster =  rasterio.open(optim+'/simflow_raster.tif')
        
    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    ax.set_title(site, fontproperties=fontprop)

    hil = rasterio.plot.show(np.ma.masked_where(hill.read(1) < 0, hill.read(1)), 
                              ax=ax, transform=dem.transform,
                              cmap='Greys_r', alpha=0.5, zorder=2)
    
    geol_f.plot(ax=ax, color=list(geol_f['hex']),alpha=0.5, edgecolor='dimgrey', zorder=0)
    
    geol_s.plot(ax=ax, color=list(geol_s['hex']), alpha=0.5, zorder=1)
    
    xlims = ax.get_xlim()[1] - ax.get_xlim()[0]
    ylims = ax.get_ylim()[1] - ax.get_ylim()[0]
    
    bbox = ax.get_window_extent().transformed(fig.dpi_scale_trans.inverted())
    width, height = bbox.width, bbox.height
    width *= fig.dpi
    height *= fig.dpi

    streams.plot(ax=ax, lw=1, color='navy', zorder=3)
    contour.plot(ax=ax, lw=1.5, color='k', zorder=5)
    
    # rast = rasterio.plot.show(np.ma.masked_where(raster.read(1) < 0, raster.read(1)), 
    #                   ax=ax, transform=dem.transform, vmin=0, vmax=1000,
    #                   cmap='RdYlGn_r', alpha=1, zorder=4)
    
    simflow.plot(ax=ax, alpha=1, column='VALUE1', cmap="RdYlGn_r", 
                  marker='s', markersize=7.5, lw=0.1, edgecolor='none',
                  scheme="User_Defined", 
                  classification_kwds=dict(bins=[150, 450, 750]),
                  zorder=4)

    fig.tight_layout()

#%% EXPLORATION DISCHARGE

watershed_names = [
                   'Cheze',
                   'Canut',
                   'Gael',
                   # 'Monfort',
                   'Vaunoise',
                   'Jouan',
                   'Neal',
                   # 'Rophemel',
                   'Nancon',
                   'Moulin',
                   ]

# watershed_names = ['Monfort']

modflow_path = data_path + 'SOFTWARE/MODFLOW/'

from watershed import watershed_root, watershed_display, forcing
from calibration import calib_root, calib_dichotomy, calib_analysis, calib_exploration, calib_basis, calib_params

for watershed_name in watershed_names[:] :
    
    print('##### '+watershed_name.upper()+' #####')
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    BV.add_forcing()
    BV.add_hydrodynamic()
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    
    sim_state = 'transient'
    time_step = 'M'
    
    var = 'REC'
    wr = True
    wish = 0
    mod = 'REA'
    
    raw_path = stable_folder+'/'+'hydrometry/'
    Qobs_path = fnmatch.filter(os.listdir(raw_path), 'Hydrometric_*')[0]
    Qobs = pd.read_csv(raw_path+Qobs_path, sep=';', index_col=0, parse_dates=True)
    # area = float(Qobs_path.split('_')[-3])
    area = BV.geographic.area
    Qobs = (Qobs / (area*1000000)) * (3600 * 24) # m3/s to m/day
    Qobs = Qobs.squeeze()
    Qobs = Qobs.resample('M').mean()
    # plt.plot(Qobs)
    # plt.yscale('log')
    
    f_simu = Qobs.first_valid_index().year+1-5
    l_simu = Qobs.last_valid_index().year-1
    # if l_simu == 2021:
    #     l_simu = 2019
    # if f_simu < 1960:
    #     f_simu = 1960
        
    Qobs = select_period(Qobs, f_simu, l_simu)
    print(Qobs.mean() * 1000)
    
    # Normalize with discharge
    BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = 'historic',
                                             first_year = f_simu, last_year = l_simu,
                                             time_step = time_step, sim_state=sim_state)
    Rech = BV.forcing.recharge
    BV.forcing.update_runoff_surfex(clim_mod = mod, clim_sce='historic',
                                          first_year = f_simu, last_year = l_simu,
                                          time_step = time_step, sim_state=sim_state)
    Runof = BV.forcing.runoff # m/month
    
    norm_Rea = select_period(Rech, f_simu, l_simu)
    norm_Qobs = select_period(Qobs, f_simu, l_simu)
    
    Rt_Rea_Qobs = (norm_Qobs.mean() / norm_Rea.mean())
    print(Rt_Rea_Qobs.round(2))
    Nt = (norm_Rea * Rt_Rea_Qobs)
    
    BV.forcing.update_recharge(Nt, sim_state=sim_state)
    fig, ax = plt.subplots()
    plt.plot(BV.forcing.recharge, c='r')
    plt.plot(Qobs, c='b')
    
    BV.forcing.update_recharge(select_period(BV.forcing.recharge, f_simu, l_simu), sim_state=sim_state)
    BV.forcing.update_runoff(select_period(BV.forcing.runoff, f_simu, l_simu), sim_state=sim_state)

    BV.hydrodynamic.update_thickness(30)
    # BV.hydrodynamic.update_porosity(0.001)
    # BV.hydrodynamic.update_hyd_cond(0.08640) # 1e-6 m/s
    
    params_df = pd.DataFrame(columns=['params',
                                      'init_values','lower_bounds','higher_bounds',
                                      'units','scale'])
    
    params_df.loc[0] = ['k1',0.864, 0.864e-03, 0.864e+03,'m/j','lin']
    params_df.loc[1] = ['n1',0.01,0.001,0.10,'m/j','lin']
        
    params_file = 'calib_explo_hom_2v_k1-n1'
    
    list_npy = glob.glob(BV.calibration_folder+'/'+params_file+'/hydrometry_calibration/_watershed/'+'*'+'.npy')
    for npy in list_npy:
        os.remove(npy)
    
    params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)
    
    # params_file = 'calib_explo_hom_1v_n1'
    # params_file = 'calib_explo_hom_1v_k1'
    # params_file = 'calib_dicot_het_2v_k1-k2'

    print((BV.forcing.recharge*1000*365).mean())
            
# EXPLORATION LAUNCH

    calib = calib_root.Calibration(params_file, BV, observations = ['hydrometry'])
    # calib.exploration(resolution=100)

#%% EXPLORATION PLOT

from calibration import calib_root, calib_dichotomy, calib_analysis, calib_exploration, calib_basis

watershed_names = [
                   'Cheze',
                   'Canut',
                   'Gael',
                   # 'Monfort',
                   'Vaunoise',
                   'Jouan',
                   'Neal',
                   # 'Rophemel',
                   'Nancon',
                   'Moulin',
                   ]

params_file = 'calib_explo_hom_2v_k1-n1'

wish = 0

sat_typ = 'seepage_areas'

for watershed_name in watershed_names[:]:
    
    print('##### '+watershed_name.upper()+' #####')
    
    min_nse = 60
    min_maxsat = 3
    max_maxsat = 25
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)

    typ_calib = 'hydrometry_calibration'
    list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, typ_calib, '*.calib')),
                        key=os.path.getmtime, reverse=True)
    name_file = list_path[wish].split('\\')[-1]
    calib_file = os.path.join(BV.calibration_folder, params_file, typ_calib, name_file)
    test = calib_analysis.CalibAnalysis(calib_file)
    
    # test.display_objective_function(save=None)
    # test.find_best_values()
    # test.display_best_data()
    
    sim_res=test.sim_results
    
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
    for t in range(len(synt)):     
        sat = test.sim_results[synt[t]][sat_typ]
        sat = pd.to_numeric(sat, errors='coerce').isnull()
        rsat.append(sat.mean())
    
    nse_good = []
    sat_good = []
    
    fig, axs = plt.subplots(2,2, figsize=(9,5))
    axs = axs.ravel()
    fig.suptitle(watershed_name.upper())
    
    numb = 0
    for i in range(len(obs[typ_name])):
        o = obs[typ_name][i] * 1000 * 30 # m/j to mm/month
        s = sim[typ_name][i] * 1000 * 30 # m/j to mm/month
        nd = ind[typ_name][i]
        sat = test.sim_results[synt[i]][sat_typ]
        sat = pd.to_numeric(sat)
        
        k = '{:.1e}'.format(float(synt[i].split(';')[0])/24/3600)
        sy = float(synt[i].split(';')[1]) * 100
        title = 'Discharge [mm/month]'
        nselog = round(((nd[0]))*100,1)
        label = 'K = '+k+' m/s'+' ; '+'ɸ = '+str(round(sy,1))+'% ; '+\
                '$NSE_{log}$ = '+str(nselog)+'%'
        nse_good.append(str(k)+'_'+str(sy)+'_'+str(nselog))
        if nselog > min_nse:
            # if all(i <= 50 for i in sat):
            if sat.max() < max_maxsat:
                if sat.max() > min_maxsat:
                    numb += 1
                # c = []
                # for h in range(len(ind[typ_name])):
                #     d = ind[typ_name][h][0]
                #     c.append(d)
        
        c = np.linspace(0,1,len(obs[typ_name]))

        cmap = mpl.cm.get_cmap('viridis_r')
        color_gradients = cmap(c)
        # vmin = min(c)
        # vmax = max(c)
        # norm = mpl.colors.Normalize(vmin=vmin, vmax=vmax)
        
        if nselog > min_nse:
            # if all(i <= 50 for i in sat):
            if sat.max() < max_maxsat:
                if sat.max() > min_maxsat:    
                
                    ax = axs[0]
                    fmt_xaxes(axs[0], 6, 1)                 
                    ax.plot(s, color=color_gradients[i], lw=1, label=label)
                    ax.set_title(title)
                    ax.plot(o, color='grey', lw=3, ls='-', zorder=0)
                    ax.set_xlim(pd.to_datetime('1989'), pd.to_datetime('2021'))
                    del(ax)
                
                    ax = axs[1]
                    fmt_xaxes(axs[1], 6, 1)
                    ax.set_title('Log discharge [mm/month]')
                    ax.plot(select_period(o.copy(),2010,2019), color='grey', lw=3, ls='-', zorder=0)
                    ax.set_yscale('log')
                    ax.plot(select_period(s.copy(),2010,2019), color=color_gradients[i], lw=1, label=label)

                    ax = axs[2]
                    fmt_xaxes(axs[2], 6, 1)
                    sat_good.append(str(k)+'_'+str(sy)+'_'+str(round(sat.mean(),2)))
                    ax.plot(select_period(sat.copy(),2010,2019), color=color_gradients[i], lw=1, label=label)
                    ax.set_ylim(-2,50)
                    title = 'Saturation [%]'
                    ax.set_title(title)
                    # ax.set_xlim(pd.to_datetime('2000'), pd.to_datetime('2005'))
                                
    plt.tight_layout()
    ncol = 2
    ax.legend(bbox_to_anchor=(1.2,0.5), prop={'size': 5}, loc="center left", 
              borderaxespad=0, ncol=ncol)
    ax = axs[3]
    plt.axis('off')
        
    # divider = make_axes_locatable(ax)
    # cax = divider.append_axes('right', size='1.25%', pad=0.1)
    # fig.add_axes(cax)
    # norm = Normalize(vmin=vmin, vmax=vmax)
    # n_cmap = cm.ScalarMappable(norm=norm, cmap=cmap)
    # n_cmap.set_array([])
    # ax.get_figure().colorbar(n_cmap, cax=cax, orientation="vertical")

    fig.savefig('D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/15_results/EBR_v1/out/_calib/' +
                '_quick_plot/'+
                watershed_name + '_CHR' + '.png', dpi=300, bbox_inches='tight')

    fig, axs = plt.subplots(1,3, figsize=(10,3.5))
    fig.suptitle(watershed_name.upper())
    axs = axs.ravel()
    
    for k in range(3):
        ax = axs[k]
        ax.axes.tick_params(which='both', direction='out', zorder=10)
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
                if k == 0:
                    try:
                        ax.set_title('SAT MIN [%]')
                        sim_sat[j][i] = pd.to_numeric(sim_res[string][sat_typ]).min()
                    except:
                        pass
                if k == 1:
                    try:
                        ax.set_title('SAT MEAN [%]')
                        sim_sat[j][i] = pd.to_numeric(sim_res[string][sat_typ]).mean()
                    except:
                        pass
                if k == 2:
                    try:
                        ax.set_title('SAT MAX [%]')
                        sim_sat[j][i] = pd.to_numeric(sim_res[string][sat_typ]).max()
                    except:
                        pass
                compt += 1
        Z=sim_sat
        pc = ax.contourf(X,Y,Z,cmap='jet', levels=np.arange(0,51,5)) #figadd.cmap_white_jet()
        ax.set_xscale('log')
        ax.set_ylabel('Sy [-]')
        ax.set_xlabel('K [m/j]')
   
    position=fig.add_axes([1.05,0.2,0.02,0.7])  ## the parameters are the specified position you set 
    fig.colorbar(pc,cax=position)
    plt.tight_layout()


    fig.savefig('D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/15_results/EBR_v1/out/_calib/' +
                '_quick_plot/'+
                watershed_name + '_2DS' + '.png', dpi=300, bbox_inches='tight')


    fig, axs = plt.subplots(1,3, figsize=(15,4))
    fig.suptitle(watershed_name.upper())
    axs = axs.ravel()
    
    ax = axs[0]
    X,Y = np.meshgrid(test.params_values[0], test.params_values[1])
    Z=test.obj_function.copy()
    Z[Z<0] = 0
    from numpy import inf
    Z[Z == inf] = 0
    pc = ax.imshow(Z, vmin = 0, vmax = 1, aspect='auto') #figadd.cmap_white_jet() , shading='gouraud'
    # ax.set_xscale('log')
    ax.set_ylabel('Sy [-]')
    ax.set_xlabel('K [m/j]')
    divider = make_axes_locatable(ax)
    cax = divider.append_axes('right', size='5%', pad=0.05)
    cb=fig.colorbar(pc, cax=cax, orientation='vertical')
    cb.set_label('$NSE_{log}$', rotation=270, labelpad=40)

    ax = axs[1]
    ax.axes.tick_params(which='both', direction='out', zorder=10)
    X,Y = np.meshgrid(test.params_values[0], test.params_values[1])
    Z=test.obj_function.copy()
    Z[Z<0] = 0
    Z[Z == inf] = 0
    pc = ax.pcolormesh(X,Y,Z, cmap='jet', shading='gouraud', vmin=0, vmax=1) #figadd.cmap_white_jet()
    ax.set_xscale('log')
    ax.set_ylabel('Sy [-]')
    ax.set_xlabel('K [m/j]')
    divider = make_axes_locatable(ax)
    cax = divider.append_axes('right', size='5%', pad=0.05)
    cb = fig.colorbar(pc, cax=cax, orientation='vertical')
    cb.set_ticks(np.arange(0,1.1,0.1)) 
    cb.set_label('$NSE_{log}$', rotation=270, labelpad=40)

    ax = axs[2]
    ax.axes.tick_params(which='both', direction='out', zorder=10)
    X,Y = np.meshgrid(test.params_values[0], test.params_values[1])
    Z=test.obj_function.copy()
    Z[Z<0] = 0
    from numpy import inf
    Z[Z == inf] = 0
    bounds = np.arange(0,1.1,0.1)
    norm = mpl.colors.Normalize(vmin=-1, vmax=1.0)
    pc = ax.contourf(X, Y, Z, levels=np.arange(0,1.1,0.1))    
    divider = make_axes_locatable(ax)
    cax = divider.append_axes('right', size='5%', pad=0.05)
    cb = fig.colorbar(pc, cax=cax, orientation='vertical')
    cb.set_ticks(np.arange(0,1.1,0.1)) 
    cb.set_label('$NSE_{log}$', rotation=270, labelpad=40)
    ax.set_xscale('log')
    ax.set_ylabel('Sy [-]')
    ax.set_xlabel('K [m/j]')
    
    plt.tight_layout()
    
    fig.savefig('D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/15_results/EBR_v1/out/_calib/' +
                '_quick_plot/'+
                watershed_name + '_2DQ' + '.png', dpi=300, bbox_inches='tight')

#%% ---- MODEL

#%% TYP SIM NAMING

# typ = 'calibr-t1'
# typ = 'projec-1'
# typ = 'projec-2'
# typ = 'reanal-1'
# typ = 'steady-1'
# typ = 'pathlines-1'

# typ = 'calib-test-v2'
# typ = 'calib-cont-v1'
# typ = 'app-stead-v1'
# typ = 'app-trans-v2'
typ = 'surf-trans-v3'


# mod_list = ['MPI-CCL','ECE-RCA','ECE-RAC','CNR-RAC',
#             'NOR-R15','CNR-ALA','HAD-REG','MPI-R09']
# mod_list = ['ECE-RCA','ECE-RAC','HAD-REG','NOR-R15',
#             'MPI-CCL','MPI-R09','CNR-RAC','CNR-ALA',
#             'IPS-WRF','HAD-CCL','IPS-RCA','NOR-HIR']
# mod_list = ['ECE-RCA'
#             'HAD-REG',
#             'MPI-R09']
# mod_list = ['CNR-ALA']
# mod_list = ['MPI-CCL','ECE-RCA','ECE-RAC',
#             'NOR-R15','HAD-REG','MPI-R09']
# mod_list = ['MPI-R09','NOR-R15']
# mod_list = ['HAD-REG']
# mod_list = ['REA']
# mod_list = ['ACC1','BCC1','BNU1','CAN1','CNR1','CSI1','IPS1','MIR1','NOR1']
mod_list = ['ACC1','BCC1','BNU1','CAN1','CAN2','CAN3','CAN4','CAN5',
            'CNR1','CSI1','IPS1','MIR1','MIR2','MIR3','NOR1']
filter_list = 'ACC1|BCC1|BNU1|CAN1|CAN2|CAN3|CAN4|CAN5|CNR1|CSI1|IPS1|MIR1|MIR2|MIR3|NOR1'
# mod_list = ['TOT1']
# mod_list = ['TOT1']
# mod_list = ['IPS1','NOR1']

typ_climate = 'SURFEX'
# typ_climate = 'DRIAS'

# sce_list = ['historic']
sce_list = ['RCP2.6','RCP8.5']
# sce_list = ['RCP8.5']

#%% PARAM RUN MODEL

sim_state = 'transient' # 'steady' or 'transient'
# sim_state = 'steady' # 'steady' or 'transient'
# modpath_sim = True # run modpath particle tracking if True
modpath_sim = False # run modpath particle tracking if True
nlay = 1

# watershed_names = [
#                     'Vaunoise',
#                    ]

watershed_names = [
                   'Cheze',
                   'Canut',
                   'Gael',
                   'Vaunoise',
                   'Neal',
                   'Jouan',
                   'Nancon',
                   'Moulin',
                   ]
dic_t = watershed_names
dic_kv = [5.1e-5,
          3.4e-5,
          6.0e-5,
          3.0e-5,
          3.4e-5,
          4.0e-5,
          2.4e-5]
dic_pv = [0.001,
          0.001,
          0.002,
          0.002,
          0.0035,
          0.01,
          0.02]

watershed_names = [
                   'Monfort',
                   'Rophemel',
                   ]
dic_t = watershed_names
dic_kv = [7.0e-5,
          3.0e-5]
dic_pv = [0.002,
          0.002]

watershed_names = [
                   'Dam',
                   ]
dic_t = watershed_names
dic_kv = [3.4e-5]
dic_pv = [0.001]

watershed_names = [
                   'Canut',
                   ]
dic_t = watershed_names
dic_kv = [5.1e-5]
dic_pv = [0.001]

watershed_names = [
                   'Cheze',
                   ]
dic_t = watershed_names
dic_kv = [3.4e-5]
dic_pv = [0.001]

# watershed_names = [
#                    'Canut',
#                    'Dam',
#                    'Mordelles',
#                    'Vaunoise',
#                    'Rophemel',
#                    'Roche',
#                    'Drains',
#                    ]

dic_p = dict(zip(dic_t,dic_pv))
dic_k = dict(zip(dic_t,dic_kv))

# watershed_names = ['Canut']
# code_names = ['J7513010']

obs_dates = True
normalize = True

#%% LAUNCH

watershed_names = ['Frame']

for watershed_name in watershed_names[:] :
    
    print('##### '+watershed_name.upper()+' #####')
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    BV.add_forcing()
    BV.add_hydrodynamic()
    
    surfex = pd.read_csv(stable_folder+'climatic/'+'_ALL_D.csv',
                         sep=';', index_col=0, parse_dates=True)#.resample('M').mean() / 1000
    surfex = surfex.filter(regex=filter_list)
    surfex = surfex.resample('M').mean() / 1000
    for v in ['REC','RUN']:
        for s in ['historic','RCP2.6','RCP8.5']:
            t = surfex.filter(regex=v)
            t = t.filter(regex=s)
            t['M'] = t.mean(axis=1)
            surfex[v+'_'+'TOT1'+'_'+s] = t['M']
    
    drias = pd.read_csv(stable_folder+'drias/'+'_ALL_D.csv',
                        sep=';', index_col=0, parse_dates=True)#.resample('M').mean() / 1000
    drias = drias.resample('M').mean() / 1000
    
    # rec = drias['REC_HAD-REG_RCP8.5']
    # run = drias['RUN_HAD-REG_RCP8.5']
    # plt.plot(rec)
    # plt.plot(run)
    # plt.yscale('log')
    
    df = pd.read_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')

    # Observed discharge
    # try:
    if watershed_name == 'Dam':
        raw_path = out_path+'/'+'Cheze'+'/'+'results_stable/'+'hydrometry/'
    else:
        raw_path = stable_folder+'/'+'hydrometry/'
    Qobs_path = fnmatch.filter(os.listdir(raw_path), 'Hydrometric_*')[0]
    Qobs = pd.read_csv(raw_path+Qobs_path, sep=';', index_col=0, parse_dates=True)
    area = BV.geographic.area
    # area = float(Qobs_path.split('_')[-3])
    Qobs = (Qobs / (area*1000000)) * (3600 * 24) # m3/s to m/day
    Qobs = Qobs.squeeze()
    Qobs = Qobs.resample('M').mean()
    # except:
    #     pass
        
    # Input recharge
    bzh_rech = False
    var = 'REC'
    wr = True
    time_step = 'M' # or 'D'
    actual_date = True # False if date is conceptual
    
    # Active of not modules
    box = False # if True generate a rectangular model
    sink_fill = False # permit to fill sinks
    verbose = True # add print of MODFLOW in console
    post_process = False # necessary to decompose post process of process
    
    # Strcture of the model
    lay_number = 1 # vertical discrtization
    bottom = 0 # aquifer flat or not
    thick_exp = 1 # exponential decay of K with nlay
    cond_decay = 0 # exponential decay of K with depth
    thick = 30 # m
    
    # Hydraulic properties
    # Koptim = 4.5e-5 # koptim 1.4e-5 / 5.33e-5
    # Koptim = df.perennial[0]
    Koptim = dic_k[watershed_name]
    Sy = dic_p[watershed_name]
    Ks = np.array([Koptim]) * 3600 * 24 # m/second to m/day
    Sys = [Sy]
    
    # Model of recharge
    for mod in mod_list:           
        for sce in sce_list:
            
            # Recharge  
            if mod == 'REA':
                
                if obs_dates == True:
                    f_simu = Qobs.first_valid_index().year+1-5
                    l_simu = Qobs.last_valid_index().year-1
                    if l_simu == 2021:
                        l_simu = 2019
                    if f_simu < 1960:
                        f_simu = 1960
                else:
                    f_simu = 1970
                    l_simu = 2019
                
                # if watershed_name == 'Vaunoise':
                #     l_simu = 2019
                    
                Qobs = select_period(Qobs, f_simu, l_simu)
                # print(Qobs.mean() * 1000)
                
                # Normalize with discharge
                BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = 'historic',
                                                         first_year = f_simu, last_year = l_simu,
                                                         time_step = time_step, sim_state=sim_state)
                Rech = BV.forcing.recharge
                BV.forcing.update_runoff_surfex(clim_mod = mod, clim_sce='historic',
                                                      first_year = f_simu, last_year = l_simu,
                                                      time_step = time_step, sim_state=sim_state)
                Runof = BV.forcing.runoff # m/month
                
                if normalize == True :
                
                    norm_Rea = Rech.copy()
                    norm_Qobs = Qobs.copy()
                    
                    Rt_Rea_Qobs = (norm_Qobs.mean() / norm_Rea.mean())
                    print(Rt_Rea_Qobs.round(2))
                    Nt = (norm_Rea * Rt_Rea_Qobs)
                    
                    BV.forcing.update_recharge(Nt, sim_state=sim_state)
                    fig, ax = plt.subplots()
                    plt.plot(BV.forcing.recharge, c='r')
                    plt.plot(Qobs, c='b')
                    
                    if sim_state == 'transient':
                        BV.forcing.update_recharge(select_period(BV.forcing.recharge, f_simu, l_simu), sim_state=sim_state)
                        BV.forcing.update_runoff(select_period(BV.forcing.runoff, f_simu, l_simu), sim_state=sim_state)
                    if sim_state == 'steady':
                        BV.forcing.update_recharge(BV.forcing.recharge,
                                                   sim_state=sim_state)
                        BV.forcing.update_runoff(BV.forcing.runoff,
                                                 sim_state=sim_state)
            
            if mod != 'REA':
                
                if typ_climate == 'SURFEX':
                    
                    if obs_dates == True:
                        f_simu = Qobs.first_valid_index().year+1-5
                        # l_simu = Qobs.last_valid_index().year-1
                        # if l_simu == 2021:
                        #     l_simu = 2019
                        if f_simu < 1960:
                            f_simu = 1960
                        l_simu = 2004
                    
                    first_hist = 1960
                    last_hist = 2005
                    first_fut = 2006
                    last_fut = 2100
                        
                    Qobs = select_period(Qobs, f_simu, l_simu)
                                        
                    if (select_period(surfex['REC_'+mod+'_'+'historic'], 1975, 2000).isnull().all() == False) & \
                       (select_period(surfex['REC_'+mod+'_'+sce], 2020, 2090).isnull().all() == False):
                           print(mod, sce, 'OK')
                    else:
                        continue

                    Rech_norm = select_period(surfex['REC_'+mod+'_historic'],
                                              f_simu, l_simu)
                    
                    # fig, ax = plt.subplots(1,1, figsize=(7,3))
                    # # ax.plot(surfex['REC_'+mod+'_'+sce])
                    # ax.plot(select_period(surfex['REC_'+mod+'_'+'historic'],
                    #                           1975, 2100).resample('Y').sum()*1000*30, c='b')
                    
                    Runof_norm = select_period(surfex['RUN_'+mod+'_historic'],
                                              f_simu, l_simu)
                    
                    # Normalize
                    if normalize == True:
                        
                        Ratio_norm = Qobs.mean() / Rech_norm.mean() #+ Runof_norm.mean()
                        # print(mod, sce, Ratio_norm.round(5))
    
                    # for t in Q_norm.index.year:
                        # Ratio_norm = (Q_norm[Q_norm.index.year==t].mean() / Rech_norm[Rech_norm.index.year==t].mean())
                        # print(Ratio_norm.round(2))
                    
                        Rech_hist = select_period(surfex['REC_'+mod+'_'+'historic'], 
                                                  first_hist, last_hist) * Ratio_norm
                        Runof_hist = select_period(surfex['RUN_'+mod+'_'+'historic'], 
                                                   first_hist, last_hist)
                        Rech_fut = select_period(surfex['REC_'+mod+'_'+sce], 
                                                 first_fut, last_fut) * Ratio_norm
                        Runof_fut = select_period(surfex['RUN_'+mod+'_'+sce], 
                                                  first_fut, last_fut)
                        
                        Rech = pd.concat((Rech_fut, Rech_hist), axis=1).mean(axis=1)
                        Runof = pd.concat((Runof_fut, Runof_hist), axis=1).mean(axis=1)
                    
                        # Update recharge
                        
                        Rech = Rech.dropna()
                        Runof = Runof.dropna()
                        
                        BV.forcing.update_recharge(Rech, sim_state = sim_state)
                        BV.forcing.update_runoff(Runof, sim_state = sim_state)
                        
                        # fig, ax = plt.subplots(1,1, figsize=(7,3))
                        # # ax.plot(surfex['REC_'+mod+'_'+sce])
                        # ax.plot(Rech*1000*30, c='b')
                        
                        # plt.plot(BV.forcing.recharge, lw=2)
                        # plt.plot(BV.forcing.runoff, lw=2)
                        # plt.yscale('log')
                
                    init_rech = select_period(Rech, 1960, 2005).mean() # first or mean or value

                if typ_climate == 'DRIAS':
                                            
                    if obs_dates == True:
                        f_simu = Qobs.first_valid_index().year+1-5
                        # l_simu = Qobs.last_valid_index().year-1
                        # if l_simu == 2021:
                        #     l_simu = 2019
                        if f_simu < 1960:
                            f_simu = 1960
                        l_simu = 2004
                    
                    first_hist = 1975
                    last_hist = 2005
                    first_fut = 2005
                    last_fut = 2100
                    
                    Qobs = select_period(Qobs, f_simu, l_simu)
                    
                    gcm = mod.split('-')[0]
                    rcm = mod.split('-')[1]
                    
                    Rech_norm = select_period(drias['REC_'+gcm+'-'+rcm+'_historic'],
                                              f_simu, l_simu)
                                        
                    Runof_norm = select_period(drias['RUN_'+gcm+'-'+rcm+'_historic'],
                                              f_simu, l_simu)
                    
                    # Normalize
                    if normalize == True:
                        
                        Ratio_norm = (Qobs.mean() / Rech_norm.mean()) #+ Runof_norm.mean()
                        print(mod, sce, Ratio_norm.round(2))

                    # for t in Q_norm.index.year:
                        # Ratio_norm = (Q_norm[Q_norm.index.year==t].mean() / Rech_norm[Rech_norm.index.year==t].mean())
                        # print(Ratio_norm.round(2))
                    
                        Rech_hist = select_period(drias['REC_'+gcm+'-'+rcm+'_'+'historic'], 
                                                  first_hist, last_hist) * Ratio_norm
                        Runof_hist = select_period(drias['RUN_'+gcm+'-'+rcm+'_'+'historic'], 
                                                   first_hist, last_hist)
                        Rech_fut = select_period(drias['REC_'+gcm+'-'+rcm+'_'+sce], 
                                                 first_fut, last_fut) * Ratio_norm
                        Runof_fut = select_period(drias['RUN_'+gcm+'-'+rcm+'_'+sce], 
                                                  first_fut, last_fut)
                        
                        Rech = pd.concat((Rech_fut, Rech_hist), axis=1).mean(axis=1)
                        Runof = pd.concat((Runof_fut, Runof_hist), axis=1).mean(axis=1)
                    
                        # Update recharge
                        
                        Rech = Rech.dropna()
                        Runof = Runof.dropna()
                        
                        BV.forcing.update_recharge(Rech, sim_state = sim_state)
                        BV.forcing.update_runoff(Runof, sim_state = sim_state)
                        
                        # fig, ax = plt.subplots(1,1, figsize=(7,3))
                        # ax.plot(surfex['REC_'+mod+'_'+sce])
                        # ax.plot(Rech, c='b')
                        
                        # plt.plot(BV.forcing.recharge, lw=2)
                        # plt.plot(BV.forcing.runoff, lw=2)
                            # plt.yscale('log')
                    
                    init_rech = select_period(Rech, 1975,2004).mean() # first or mean or value

            # print(init_rech)
            # plt.plot(init_rech)
            # plt.yscale('log')
            
            fig, ax = plt.subplots(1,1, figsize=(7,3))
            # ax.plot(surfex['REC_'+mod+'_'+sce])
            # ax.plot(Rech.resample('Y').sum()*1000, c='r')
            # print(select_period(Rech, 1960, 2005).sum())
            # print(init_rech)
            ax.plot(Rech, c='r')
            ax.plot(Rech_norm, c='k')
            # ax.plot(Qobs, c='k')
            ax.set_title(mod+'-'+sce)
            # ax.set_yscale('log')
            ax.set_xlim(pd.to_datetime('1970'), pd.to_datetime('2100'))

            list_model_name = []
            list_of_success = []
            list_flow_model = []
            list_var_store = []

            # Update properties
            compt = 1
            for Sy in Sys:
                for K in Ks:

                    BV.hydrodynamic.update_nlay(nlay) # 1
                    BV.hydrodynamic.update_bottom(None) # None
                    BV.hydrodynamic.update_cond_decay(0.) # 0
                    BV.hydrodynamic.update_thick_exp(1) # 1
                    BV.hydrodynamic.update_thickness(30) # 30 / intervient pas si bottom != None
                    
                    BV.hydrodynamic.update_hyd_cond(K) 
                    BV.hydrodynamic.update_porosity(Sy)
                      
                    date_today = datetime.now().strftime("%d/%m/%Y %H:%M:%S") # just a string
                    date_today = date_today.replace('/','-')
                    date_today = date_today.replace(':','-')
                    date_today = date_today.replace(' ','_')
                    
                    if sim_state == 'transient':
                        model_name = typ+'_'+str(compt)+'_'+\
                                     var+'-'+mod+'-'+sce+'_'+\
                                     str(Sy*100)+'-'+str(round(K,2))+'-'+str(thick)+'_'+\
                                     str(Rech.first_valid_index().year)+'-'+str(Rech.last_valid_index().year)
                    else:
                        model_name = typ+'_'+str(compt)+'_'+\
                                     var+'-'+mod+'-'+sce+'_'+\
                                     str(Sy*100)+'-'+str(round(K,2))+'-'+str(thick)
                                     
                    # Run model
                    try:
                        print('SIM - ' + model_name)
                        success, flow_model = BV.run_modflow(ident=model_name,
                                                             modpath_sim=modpath_sim,
                                                             sink_fill=sink_fill,
                                                             box=box,
                                                             verbose=verbose,
                                                             post_process=post_process, 
                                                             init_rech=init_rech)
                        if success == True:
                            print(     'Success')
                        else:
                            print(     'Error')
                    except:
                        pass
                    list_model_name.append(model_name)
                    list_of_success.append(success)
                    list_flow_model.append(flow_model)
                    list_var_store.append(BV.forcing.runoff)
                    compt+=1
                    
            print(list_of_success)
            
            dictio = {}
            dictio['list_model_name'] = list_model_name
            dictio['list_of_success'] = list_of_success
            dictio['list_flow_model'] = list_flow_model
            dictio['list_var_store'] = list_var_store
            h5file = simulations_folder+'/'+'list_'+typ+'_'+var+'-'+mod+'-'+sce
            
            dd.io.save(h5file, dictio)
                        
# POSTPROCESS MODEL

# mod_list = ['ECE-RCA','HAD-REG','MPI-R09']

for watershed_name in watershed_names :
    
    print('##### '+watershed_name.upper()+' #####')
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    BV.add_forcing()
    
    for mod in mod_list:
        for sce in sce_list:
    
            h5file = simulations_folder+'/'+'list_'+typ+'_'+var+'-'+mod+'-'+sce
            if os.path.exists(h5file):
                d = dd.io.load(h5file)
                list_model_name = d['list_model_name'][:]
                list_of_success = d['list_of_success'][:]
                list_flow_model = d['list_flow_model'][:]
                list_var_store = d['list_var_store'][:]
                
                for model_name, success, flow_model, var_store in zip(list_model_name,
                                                                      list_of_success,
                                                                      list_flow_model,
                                                                      list_var_store):
                    print(mod, success)
    
    # CHECK
    
                    if success==True:
                            
                            
                            BV.matrix_modflow(success,
                                              flow_model,
                                              first_only = True,
                                              watertable_elevation = True,
                                              watertable_depth = True, 
                                              seepage_areas = True,
                                              outflow_drain = True,
                                              groundwater_flux = True,
                                              specific_discharge = False,
                                              accumulation_flux = True,
                                              perenn_intermit_shp = False,
                                              groundwater_storage = True,
                                              residence_times = False,
                                              verbose = True,
                                              export_tif = True)
                            
                            # Necessary for results_modflow
                            BV.forcing.update_recharge(flow_model.climatic,
                                                       sim_state=sim_state)
                            recharge = BV.forcing.recharge
                            runoff = var_store.copy()
                        
                            
                            # # Extract results
                            BV.results_modflow(ident=model_name,
                                               recharge=recharge,
                                               runoff=runoff,
                                               actual_date=actual_date,
                                               time_step=time_step)
                            
                            ## Plot maps
                            surf = modflow_display.SurfaceOutputs(flow_model.climatic,
                                                                  simulations_folder, stable_folder,
                                                                  model_name, types_obs,
                                                                  save_gif=False,
                                                                  first_only=True,
                                                                  sim_state=sim_state,
                                                                  outflow=True,
                                                                  accflux=True,
                                                                  intermittency=False,
                                                                  chronics=False)

#%% ---- NOTES

#%% PATHLINES

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True,
                              modflow_path=modflow_path)

dem = rasterio.open(BV.geographic.watershed_dem)
dem_data = dem.read(1)

list_path = sorted(glob.glob(simulations_folder+typ+'*'),
                    key=os.path.getmtime, reverse=False)
model_name = list_path[0].split('\\')[-1]

compt=0
# for case, prop in zip(case_list[:], prop_list[:]):
#     for porosity in porosity_list[:]:
    
folder_results = simulations_folder + '/' + model_name + '/' + '_watershed/_tifs/'

##### LOOOP 2D #####
visu = visualization.Visualization(BV, model_name)
# visu.visual2D(object_list = ['map','grid', 'watertable', 'watertable_depth','drain_flow','surface_flow','pathlines', 'residence_times'],
              # color_scale = [(None,None),(0,140),(0,140),(0,2),(None,None),(None,None),(None,None),(None,None)], lines=10000)
visu.visual2D(object_list = ['pathlines'],
              color_scale = [(None,None)], lines=1000)

#%% ---- PROJECTION

res_folder = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/14_manuscript/figures/5_application/5.3/'

watershed_names = ['Cheze']

typ_climate = 'SURFEX'
# typ = 'app-trans-v2'
typ = 'surf-trans-v3'
# mod_list = [
#             'MPI-CCL','MPI-R09',
#             'CNR-RAC','CNR-ALA',
#             'ECE-RCA','ECE-RAC',
#             'HAD-REG',
#             'NOR-R15'
#             ]

# typ_climate = 'SURFEX'
# typ = 'surf-trans-v2'
mod_list = ['TOT1']

fig_path = res_folder+typ+'/'

if not os.path.exists(fig_path):
    toolbox.create_folder(fig_path)

#%% EVOLUTION
 
typ = 'surf-trans-v3'

watershed_names = ['Cheze']
mod_list = ['ACC1','BCC1','BNU1','CAN1','CAN2','CAN3','CAN4','CAN5',
            'CNR1','CSI1','IPS1','MIR1','MIR2','MIR3','NOR1']
# mod_list = ['TOT1']

sce_list = ['historic','RCP2.6','RCP8.5']

df = pd.DataFrame()

for watershed_name in watershed_names :
    
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        for sce in sce_list:
            
            if sce == 'historic':
                sce_name = 'RCP8.5'
            else:
                sce_name = sce
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce_name+'*')
            
            if len(simul_list)>0 :
                simul = simul_list[0]
            else:
                continue
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
                        
            # df['Q_'+mod+'_'+sce] = Smod['recharge'] #+ Smod['runoff'] 
            df['Q_'+mod+'_'+sce] = (Smod['outflow_drain']+ Smod['runoff']) * 1000 * 365 #
            # df['Q_'+mod+'_'+sce] = Smod['surflow_areas']
                        
            # plt.plot(Smod.recharge*1000)
            # plt.plot(Smod.outflow_drain*1000)
            # plt.yscale('log')         
            
            # plt.scatter(Smod.recharge, Smod.outflow_drain+Smod.runoff)
            # plt.xscale('log')
            # plt.yscale('log')
            
            # plt.plot(df['Q_'+mod+'_'+sce].resample('Y').mean()*365)
            # plt.plot(Smod.runoff)
            # plt.yscale('log')

fig, ax = plt.subplots(1,1, figsize=(10,4))

per_list = [[1975,2005],[2005,2100],[2005,2100]]
sce_list = ['historic','RCP2.6','RCP8.5']

col_list = ['dimgrey','dodgerblue','red']
col_list_b = ['k','navy','darkred']
dict_c = dict(zip(sce_list, col_list))
dict_c_b = dict(zip(sce_list, col_list_b))

for sce, per in zip(sce_list, per_list):
    
    # d = select_period(df, per[0], per[1])
    
    # if typ_climate == 'DRIAS' :
    d = df.copy()
    d['MIN'] = d.filter(regex=sce).min(axis=1)
    d['Q5'] = d.filter(regex=sce).quantile(0.05, axis=1)
    d['Q10'] = d.filter(regex=sce).quantile(0.10, axis=1)
    d['Q25'] = d.filter(regex=sce).quantile(0.25, axis=1)
    d['MEAN'] = d.filter(regex=sce).mean(axis=1)
    d['MED'] = d.filter(regex=sce).median(axis=1)
    d['Q75'] = d.filter(regex=sce).quantile(0.75, axis=1)
    d['Q90'] = d.filter(regex=sce).quantile(0.90, axis=1)
    d['Q95'] = d.filter(regex=sce).quantile(0.95, axis=1)
    d['MAX'] = d.filter(regex=sce).max(axis=1)
    d = d.resample('Y').mean() #* 1000 * 365
        
    # if typ_climate == 'SURFEX':
    #     d = (df.resample('Y').mean()).copy()
    #     d['MIN'] = df.filter(regex=sce).resample('Y').min()
    #     d['Q5'] = df.filter(regex=sce).resample('Y').quantile(0.05)
    #     d['Q10'] = df.filter(regex=sce).resample('Y').quantile(0.10)
    #     d['Q25'] = df.filter(regex=sce).resample('Y').quantile(0.25)
    #     d['MEAN'] = df.filter(regex=sce).resample('Y').mean()
    #     d['MED'] = df.filter(regex=sce).resample('Y').median()
    #     d['Q75'] = df.filter(regex=sce).resample('Y').quantile(0.75)
    #     d['Q90'] = df.filter(regex=sce).resample('Y').quantile(0.90)
    #     d['Q95'] = df.filter(regex=sce).resample('Y').quantile(0.95)
    #     d['MAX'] = df.filter(regex=sce).resample('Y').max()
    #     d = d * 1000 * 365
    #     ax.set_yscale('log')
    
    # d = (df.resample('Y').mean()).copy()
    # d['MIN'] = df.filter(regex=sce).resample('Y').min()
    # d['Q5'] = df.filter(regex=sce).resample('Y').quantile(0.05)
    # d['Q10'] = df.filter(regex=sce).resample('Y').quantile(0.10)
    # d['Q25'] = df.filter(regex=sce).resample('Y').quantile(0.25)
    # d['MEAN'] = df.filter(regex=sce).resample('Y').mean()
    # d['MED'] = df.filter(regex=sce).resample('Y').median()
    # d['Q75'] = df.filter(regex=sce).resample('Y').quantile(0.75)
    # d['Q90'] = df.filter(regex=sce).resample('Y').quantile(0.90)
    # d['Q95'] = df.filter(regex=sce).resample('Y').quantile(0.95)
    # d['MAX'] = df.filter(regex=sce).resample('Y').max()
    # d = d* 365
    # df = select_period(df, 1970, 2005)
    
    # d = d * 365
    # val = d['MAX'].rolling(window=10).mean()
    high = select_period(d['Q25'].copy(), per[0], per[1]).rolling(window=5).mean()
    mean = select_period(d['MED'].copy(), per[0], per[1]).rolling(window=5).mean()
    low = select_period(d['Q75'].copy(), per[0], per[1]).rolling(window=5).mean()
    
    # high = select_period(d['MIN'].copy(), per[0], per[1])
    # mean = select_period(d['MED'].copy(), per[0], per[1])
    # low = select_period(d['Q90'].copy(), per[0], per[1])
    
    ax.plot(mean, c=dict_c_b[sce], lw=4)
    ax.fill_between(mean.index, low, high, color=dict_c[sce], alpha=0.25)
    # d = d.T
    # ax.boxplot(d)
    # ax.set_yscale('log')
    ax.set_axisbelow(True)
    # ax.grid(zorder=-1000)
    ax.xaxis.grid(color='gray', alpha=0.2, zorder=-20)
    ax.yaxis.grid(color='gray', alpha=0.2, zorder=-20)
    ax.set_xlim(pd.to_datetime('1975'), pd.to_datetime('2100'))
    
    ax.axvline(pd.to_datetime('1980'), c='k', ls='--')
    ax.axvline(pd.to_datetime('2006'), c='k', ls='--')
    ax.axvline(pd.to_datetime('2010'), c='k', ls='--')
    
    ax.set_ylim(100, 700)
    
    yearsmaj = mdates.YearLocator(10)   # every year
    # yearsmin = mdates.YearLocator(years_min)
    # monthsmaj = mdates.MonthLocator(6)  # every month
    # monthsmin = mdates.MonthLocator(3)
    # months_fmt = mdates.DateFormatter('%m') #b = name of month ?
    years_fmt = mdates.DateFormatter('%Y')
    ax.xaxis.set_major_locator(yearsmaj)
    # ax.xaxis.set_minor_locator(yearsmin)
    ax.xaxis.set_major_formatter(years_fmt)

    # ax.set_yscale('log')
    
    fig.savefig(fig_path + watershed_name +
                '_evolution_' + str(mod_list[0]) + '.png', dpi=300, bbox_inches='tight')

#%% BOXPLOT

mod_list = ['ACC1','BCC1','BNU1','CAN1','CAN2','CAN3','CAN4','CAN5',
            'CNR1','CSI1','IPS1','MIR1','MIR2','MIR3','NOR1']

sce_list = ['historic','RCP2.6','RCP8.5']

df = pd.DataFrame()

for watershed_name in watershed_names :
    
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        for sce in sce_list:
            
            if sce == 'historic':
                sce_name = 'RCP8.5'
            else:
                sce_name = sce
                
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce_name+'*')
                        
            if len(simul_list)>0 :
                simul = simul_list[0]
            else:
                continue
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
                        
            df['Q_'+mod+'_'+sce] = ( Smod['outflow_drain'] + Smod['runoff'] ) * 1000 * 30
            # df['Q_'+mod+'_'+sce] = Smod['surflow_areas']
            # plt.plot(df['Q_'+mod+'_'+sce])
    
fig, ax = plt.subplots(1,1, figsize=(5,4))

per_list = [[1980,2010],[2010,2040],[2040,2070],[2070,2098]]
# per_list = [[1980,2010]]

sce_list = ['RCP2.6','RCP8.5']
col_list = ['dodgerblue','red']
dict_c = dict(zip(sce_list, col_list))

for sce in sce_list:
    
    i = 0
    
    for per in per_list:
        
        # if per[0] == 1980:
        #     sce = 'RCP8.5'
        
        d = df.copy()
        d = d.filter(regex=sce) 
        d = select_period(d, per[0], per[1])
        d = pd.Series(d.values.ravel('F'))
        # d = d * 1000 * 365

        coul = dict_c[sce]

        if sce == 'RCP2.6':
            ps = -0.12
            ax.axvline(1.5, c='grey')
        if sce == 'RCP8.5':
            ps = +0.12
            ax.axvline(2.5, c='grey')
        if per[0] == 1980:
            ps = 0
            ax.axvline(3.5, c='grey')
            coul = 'dimgray'
        
        boxprops = dict(linestyle='-', linewidth=1, color='black',
                        facecolor=coul, alpha=0.40)
        medianprops = dict(linestyle='-', linewidth=1, color='black')
        meanpointprops = dict(markersize=0, marker='o', markeredgecolor='black',
                              markerfacecolor='k', linestyle='-')
        
        bp = ax.boxplot(d, widths=0.2,
                        positions=[i+1+ps],
                          whis=False, showfliers=False, showmeans=False, 
                          medianprops=medianprops, meanprops=meanpointprops,
                          patch_artist=True, boxprops=boxprops)
        for element in bp['whiskers']:
            element.set_color('k')
            element.set_linestyle('-')
        
        ax.vlines(x=i+1+ps, 
                    ymin=d.quantile(0.75), 
                    ymax=d.quantile(0.90), color='k', zorder=2)
        ax.vlines(x=i+1+ps, 
                    ymin=d.quantile(0.10), 
                    ymax=d.quantile(0.25), color='k', zorder=2)
        ax.plot(i+1+ps, 
                  d.quantile(0.10), color='k', zorder=2, lw=0,
                  marker='_', mew=1)
        ax.plot(i+1+ps, 
                  d.quantile(0.90), color='k', zorder=2, lw=0,
                  marker='_', mew=1)
          
        ax.plot(i+1+ps, d.mean(), marker='o', mec='k', ms=3, lw=0,
                mfc='k', mew=1,
                color='k', zorder=1000)
        
        # ax.get_xaxis().set_visible(False)
        ax.set_yscale('log')
        ax.set_ylim(2, 200)
        # ax.set_yticks([2,10,100])
        # ax.xaxis.set_major_formatter(matplotlib.ticker.ScalarFormatter())
        ax.set_xlim(0.5,4.5)
        
        ax.set_axisbelow(True)
        # ax.grid(zorder=-1000)
        ax.xaxis.grid(color='gray', alpha=0.2, zorder=-20)
        ax.yaxis.grid(color='gray', alpha=0.2, zorder=-20, which='both')

        i += 1
        
fig.savefig(fig_path + watershed_name +
            '_boxplot_' + str(mod_list[0]) + '.png', dpi=300, bbox_inches='tight')

#%% INTERMENSUAL

sce_list = ['historic','RCP2.6','RCP8.5']

typ = 'surf-trans-v3'

watershed_names = ['Cheze']
mod_list = ['ACC1','BCC1','BNU1','CAN1','CAN2','CAN3','CAN4','CAN5',
            'CNR1','CSI1','IPS1','MIR1','MIR2','MIR3','NOR1']

df = pd.DataFrame()

for watershed_name in watershed_names :
    
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        for sce in sce_list:
            
            if sce == 'historic':
                sce_name = 'RCP8.5'
            else:
                sce_name = sce
                
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce_name+'*')
            if len(simul_list)>0 :
                simul = simul_list[0]
            else:
                continue
            
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            
            # df['Q_'+mod+'_'+sce] = Smod['recharge'] * 1000

            df['Q_'+mod+'_'+sce] = (Smod['outflow_drain']+Smod['runoff']) * 1000 * 30 # + (Smod['runoff']*1)) 
            # df['Q_'+mod+'_'+sce] = Smod['surflow_areas']

# per_list = [[2010,2040],[2040,2070],[2070,2100],[1980,2005]]
per_list = [[2070,2100],[1980,1990]]

# per_list = [[1980,1990]]

sce_list = ['RCP8.5','RCP2.6']
# sce_list = ['RCP2.6']
# sce_list = ['RCP8.5']
col_list = ['red','dodgerblue']
col_list_b = ['darkred','navy']
dict_c = dict(zip(sce_list, col_list))
dict_c_b = dict(zip(sce_list, col_list))

for sce in sce_list:
    
    i = 0
    
    fig, ax = plt.subplots(1,1, figsize=(5.5,3.5))
    
    for per in per_list:
        
        if sce == 'RCP8.5':
            list_c = ['gold','darkorange','red','k']
        if sce == 'RCP2.6':
            list_c = ['forestgreen','dodgerblue','darkviolet','k']
            
        if sce == 'RCP8.5':
            list_c = ['red','grey']
            list_c_b = ['darkred','k']
        if sce == 'RCP2.6':
            list_c = ['dodgerblue','grey']
            list_c_b = ['navy','k']
        
        d = df.copy()
        d = d.filter(regex=sce)
        d = select_period(d, per[0], per[1])
        print(d.shape)
        # d = pd.Series(d.values.ravel('F'))
        d = d.stack().reset_index()
        d = d.set_index('date')
        d = d[0]
        
        if (sce == 'RCP8.5') & (per[0] == 1980):
            store = d
        
        if (sce == 'RCP2.6') & (per[0] == 1980):
            d = store.copy()
            
        dg = d.groupby([(d.index.month)]).median().to_frame()
        dg.columns = ['MED']
        dg['MIN'] = d.groupby([(d.index.month)]).min()
        dg['Q5'] = d.groupby([(d.index.month)]).quantile(0.05)
        dg['Q10'] = d.groupby([(d.index.month)]).quantile(0.1)
        dg['Q25'] = d.groupby([(d.index.month)]).quantile(0.25)
        dg['MEAN'] = d.groupby([(d.index.month)]).mean()
        dg['Q75'] = d.groupby([(d.index.month)]).quantile(0.75)
        dg['Q90'] = d.groupby([(d.index.month)]).quantile(0.90)
        dg['Q95'] = d.groupby([(d.index.month)]).quantile(0.95)
        dg['MAX'] = d.groupby([(d.index.month)]).max()
        
        '''
        d['MIN'] = d.filter(regex=sce).min(axis=1)
        d['Q5'] = d.filter(regex=sce).quantile(0.05, axis=1)
        d['Q10'] = d.filter(regex=sce).quantile(0.10, axis=1)
        d['Q25'] = d.filter(regex=sce).quantile(0.25, axis=1)
        d['MEAN'] = d.filter(regex=sce).mean(axis=1)
        d['MED'] = d.filter(regex=sce).median(axis=1)
        d['Q75'] = d.filter(regex=sce).quantile(0.75, axis=1)
        d['Q90'] = d.filter(regex=sce).quantile(0.90, axis=1)
        d['Q95'] = d.filter(regex=sce).quantile(0.95, axis=1)
        d['MAX'] = d.filter(regex=sce).max(axis=1)
        '''

        # dfb = d.groupby([(d.index.month)]).mean()
        # dfb = dfb.rename_axis(["year", "month"])
        
        coul = dict_c[sce]
        
        # if sce == 'RCP2.6':
        # if sce == 'RCP8.5':
        if per[0] == 1980:
            coul = 'k'
        
        '''
        # ax.plot(d['MED'], c=coul, lw=3)
        ax.plot(d['MED'], c=list_c_b[i], lw=2)
        # for idx in d.index:
        #     ax.vlines(idx, d.loc[idx,'Q25'], d.loc[idx,'Q75'], color=coul)
        ax.fill_between(d.index, d['Q10'], d['Q90'], color=coul, alpha=0.5, ec='none')
        '''
        
        # ax.plot(d['MED'], c=coul, lw=3)
        ax.plot(dg['MED'], c=list_c_b[i], lw=3)
        # for idx in d.index:
        #     ax.vlines(idx, d.loc[idx,'Q25'], d.loc[idx,'Q75'], color=coul)
        ax.fill_between(dg.index, dg['Q10'], dg['Q90'], color=coul, alpha=0.25, ec='none')
        
        squad = ['J','F','M','A','M','J','J','A','S','O','N','D']
        x1 = np.arange(1,12+1,1)
        ax.set_xticks(x1)
        ax.set_xticklabels(squad, minor=False, rotation='horizontal')
        ax.set_xlim(1,12)
        ax.set_yscale('log')
        
        ax.set_ylim(1, 500)
        
        ax.set_axisbelow(True)
        # ax.grid(zorder=-1000)
        ax.xaxis.grid(color='gray', alpha=0.2, zorder=-20)
        ax.yaxis.grid(color='gray', alpha=0.2, zorder=-20, which='both')

        i += 1
        
    fig.savefig(fig_path + watershed_name +
                '_intermensual_' + str(mod_list[0]) + '_' + sce + '.png', dpi=300, bbox_inches='tight')

#%% TABLEAU

sce_list = ['historic','RCP2.6','RCP8.5']

typ = 'surf-trans-v3'

watershed_names = ['Cheze']
mod_list = ['ACC1','BCC1','BNU1','CAN1','CAN2','CAN3','CAN4','CAN5',
            'CNR1','CSI1','IPS1','MIR1','MIR2','MIR3','NOR1']

# mod_list = ['ACC1','BCC1','BNU1','CAN1','CNR1','CSI1','IPS1','MIR1','NOR1']

mod_list = ['TOT1']

df = pd.DataFrame()

for watershed_name in watershed_names :
    
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        for sce in sce_list:
            
            if sce == 'historic':
                sce_name = 'RCP8.5'
            else:
                sce_name = sce
                
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce_name+'*')
            if len(simul_list)>0 :
                simul = simul_list[0]
            
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
                        
            df['Q_'+mod+'_'+sce] = Smod['outflow_drain'] * 1000 * 30
            # df['Q_'+mod+'_'+sce] = Smod['surflow_areas']

per = [2040,2070]

sce_list = ['RCP2.6','RCP8.5']
col_list = ['dodgerblue','red']
dict_c = dict(zip(sce_list, col_list))

fig, ax = plt.subplots(1,1, figsize=(4,3))

# dft = pd.DataFrame(columns=np.arange(1,13,1))
dft = pd.DataFrame()

for sce in sce_list:
    
    i = 0
    
    # if typ_climate == 'DRIAS':
        
    hist = df.copy()
    hist = hist.filter(regex='historic')
    hist = select_period(hist, 1980, 2005)
    hist = hist.stack().reset_index()
    hist = hist.set_index('date')
    hist = hist[0]
    dft['Past'] = hist.groupby([(hist.index.month)]).mean()
    # hist = hist.T
    
    fut = df.copy()
    fut = fut.filter(regex=sce)
    fut = select_period(fut, per[0], per[1])
    fut = fut.stack().reset_index()
    fut = fut.set_index('date')
    fut = fut[0]
    dft['Future_'+sce] = fut.groupby([(fut.index.month)]).mean()
    
    dft['d_min_'+sce] = ((fut.groupby([(fut.index.month)]).min()-
                          hist.groupby([(hist.index.month)]).min())/
                          hist.groupby([(hist.index.month)]).min())*100
    dft['d_mean_'+sce] = ((fut.groupby([(fut.index.month)]).mean()-
                          hist.groupby([(hist.index.month)]).mean())/
                          hist.groupby([(hist.index.month)]).mean())*100
    dft['d_med_'+sce] = ((fut.groupby([(fut.index.month)]).median()-
                          hist.groupby([(hist.index.month)]).median())/
                          hist.groupby([(hist.index.month)]).median())*100
    dft['d_max_'+sce] = ((fut.groupby([(fut.index.month)]).max()-
                          hist.groupby([(hist.index.month)]).max())/
                          hist.groupby([(hist.index.month)]).max())*100

    '''
    dft['Past'] = hist.mean(axis=1)
    dft['Future_'+sce] = fut.mean(axis=1)

    dft['d_min_'+sce] = ((fut.min(axis=1)-hist.min(axis=1))/hist.min(axis=1))*100
    dft['d_mean_'+sce] = ((fut.mean(axis=1)-hist.mean(axis=1))/hist.mean(axis=1))*100
    dft['d_med_'+sce] = ((fut.median(axis=1)-hist.median(axis=1))/hist.median(axis=1))*100
    dft['d_max_'+sce] = ((fut.max(axis=1)-hist.max(axis=1))/hist.max(axis=1))*100
    '''   
    
    # if typ_climate == 'SURFEX':
        
    #     hist = df.copy()
    #     hist = hist.filter(regex=sce)
    #     hist = select_period(hist, 1980, 2005)
    #     hist_min = hist.groupby([(hist.index.month)]).min()
    #     hist_mean = hist.groupby([(hist.index.month)]).mean()
    #     hist_med = hist.groupby([(hist.index.month)]).median()
    #     hist_max = hist.groupby([(hist.index.month)]).max()
    #     # hist = hist.T
        
    #     fut = df.copy()
    #     fut = fut.filter(regex=sce)
    #     fut = select_period(fut, per[0], per[1])
    #     fut_min = fut.groupby([(fut.index.month)]).min()
    #     fut_mean = fut.groupby([(fut.index.month)]).mean()
    #     fut_med = fut.groupby([(fut.index.month)]).median()
    #     fut_max = fut.groupby([(fut.index.month)]).max()
    
    #     dft['Past'] = hist.groupby([(hist.index.month)]).mean()
    #     dft['Future_'+sce] = fut.groupby([(fut.index.month)]).mean()
        
    #     dft['d_min_'+sce] = ((fut_min-hist_min)/hist_min)*100
    #     dft['d_mean_'+sce] = ((fut_mean-hist_mean)/hist_mean)*100
    #     dft['d_med_'+sce] = ((fut_med-hist_med)/hist_med)*100
    #     dft['d_max_'+sce] = ((fut_max-hist_max)/hist_max)*100

dft.boxplot(rot=-270)   

# dft = dft[['Past','Future_RCP','b','f','d','a']]

dft = dft.T

dft.to_csv(fig_path + watershed_name +
            '_table_' + str(mod_list) + '.csv', sep=';')

#%% QMNA

sce_list = ['historic','RCP2.6','RCP8.5']

typ = 'surf-trans-v3'

watershed_names = ['Cheze']
mod_list = ['ACC1','BCC1','BNU1','CAN1','CAN2','CAN3','CAN4','CAN5',
            'CNR1','CSI1','IPS1','MIR1','MIR2','MIR3','NOR1']
mod_list = ['TOT1']

df = pd.DataFrame()

for watershed_name in watershed_names :
    
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        for sce in sce_list:
            
            if sce == 'historic':
                sce_name = 'RCP8.5'
            else:
                sce_name = sce
                
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce_name+'*')
            if len(simul_list)>0 :
                simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
                        
            df['Q_'+mod+'_'+sce] = (Smod['outflow_drain']+Smod['runoff']) * 1000 * 30
            # df['Q_'+mod+'_'+sce] = Smod['surflow_areas']

per = [2040,2070]

sce_list = ['RCP2.6','RCP8.5']
col_list = ['dodgerblue','red']
col_list_b = ['navy','darkred']
dict_c = dict(zip(sce_list, col_list))
dict_c_b = dict(zip(sce_list, col_list_b))

fig, ax = plt.subplots(1,1, figsize=(4.5,3.5))

# dft = pd.DataFrame(columns=np.arange(1,13,1))
dft = pd.DataFrame()

# for mod in mod_list:

for sce in sce_list:
    
    i = 0
    
    '''
    hist = df.copy()
    hist = hist.filter(regex=sce) #* 365
    hist = select_period(hist, 1980, 2004)
    hist = hist.median(axis=1)
    # hist = hist.groupby([(hist.index.month)]).mean()
    # hist = hist.T
    # hist = hist.groupby([(hist.index.year)]).min()
    
    fut = df.copy()
    fut = fut.filter(regex=sce) #* 365
    fut = select_period(fut, per[0], per[1])
    fut = fut.median(axis=1)
    # fut = fut.groupby([(fut.index.month)]).mean()
    # fut = hist.groupby([(hist.index.year)]).min()
    '''
    
    hist = df.copy()
    hist = hist.filter(regex='historic')
    hist = hist.filter(regex=mod)
    hist = select_period(hist, 1980, 2005)
    hist = hist.stack().reset_index()
    hist = hist.set_index('date')
    hist = hist[0]

    fut = df.copy()
    fut = fut.filter(regex=sce)
    fut = fut.filter(regex=mod)
    fut = select_period(fut, per[0], per[1])
    fut = fut.stack().reset_index()
    fut = fut.set_index('date')
    fut = fut[0]
    
    ################################################
    
    qmna_hist = hist.groupby([(hist.index.year)]).min()
    qmna_sort = qmna_hist.sort_values().to_frame()
    qmna_sort.columns = ['x']

    qmna_sort = qmna_sort.round(3) #/ 12
    
    # Method 1
    Z = qmna_sort.copy()
    N = len(Z)
    count, bins_count = np.histogram(Z, bins=100, density=True)
    pdf = count / sum(count)
    cdf = np.cumsum(pdf)
    
    # Method 2
    qh = np.array(qmna_sort.copy())
    LBINS = 100
    # No log
    linbins = np.linspace(0, qh.max(), LBINS)
    hist_lin, bins_lin = np.histogram(qh, bins=linbins, density=True)
    bins_lin_centers = 0.5*(bins_lin[1:]+bins_lin[:-1])
    # Log
    logbins = np.logspace(np.log10(qh.min()), np.log10(qh.max()), LBINS)
    hist_log, bins_log = np.histogram(qh, bins=logbins, density=True)
    bins_log_centers = 10**(0.5*(np.log10(bins_log[1:]) + np.log10(bins_log[:-1])))
    
    # freq = pd.DataFrame(bins_log.copy(), columns=['x']).round(1)
    freq = qmna_sort.groupby('x').size().reset_index(name='counts')
    # freq = freq.groupby('x').size().reset_index(name='counts')
    freq['frequency'] = freq.counts/freq.counts.sum() #freq
    freq['cumulative_frequency'] = freq['frequency'].cumsum() #freq cumulated
    freq['retour'] = 1/(freq['cumulative_frequency'])
    freq['target'] = 5
    
    # ax.plot(bins_log)
    ax.plot(freq['retour'], freq['x'], ls='-', c='grey', linewidth=2)
    ax.plot(freq['retour'], freq['x'], ls='-', c='k', marker='+',
            ms=6, mew=2, linewidth=0)
    # ax.plot(pdf, ls='-', c=dict_c[sce], linewidth=1)

    ################################################

    qmna_fut = fut.groupby([(fut.index.year)]).min()
    qmna_sort = qmna_fut.sort_values().to_frame()
    qmna_sort.columns = ['x']
    qmna_sort = qmna_sort.round(3) #/ 12
    
    # Method 1
    Z = qmna_sort.copy()
    N = len(Z)
    count, bins_count = np.histogram(Z, bins=100, density=True)
    pdf = count / sum(count)
    cdf = np.cumsum(pdf)
    
    # Method 2
    qh = np.array(qmna_sort.copy())
    LBINS = 100
    # No log
    linbins = np.linspace(0, qh.max(), LBINS)
    hist_lin, bins_lin = np.histogram(qh, bins=linbins, density=True)
    bins_lin_centers = 0.5*(bins_lin[1:]+bins_lin[:-1])
    # Log
    logbins = np.logspace(np.log10(qh.min()), np.log10(qh.max()), LBINS)
    hist_log, bins_log = np.histogram(qh, bins=logbins, density=True)
    bins_log_centers = 10**(0.5*(np.log10(bins_log[1:]) + np.log10(bins_log[:-1])))
    
    freq = qmna_sort.groupby('x').size().reset_index(name='counts')
    
    # freq = pd.DataFrame(bins_log.copy(), columns=['x']).round(1)
    # freq = freq.groupby('x').size().reset_index(name='counts')
    
    freq['frequency'] = freq.counts/freq.counts.sum() #freq
    freq['cumulative_frequency'] = freq['frequency'].cumsum() #freq cumulated
    freq['retour'] = 1/(freq['cumulative_frequency'])
    freq['target'] = 5
    
    # ax.plot(bins_log)
    ax.plot(freq['retour'], freq['x'], ls='-', c=dict_c[sce], linewidth=2)
    ax.plot(freq['retour'], freq['x'], ls='-', c=dict_c_b[sce], marker='+',
            ms=6, mew=2, linewidth=0)
    # ax.plot(pdf, ls='-', c=dict_c[sce], linewidth=1)
    
    ################################################
    
    # ax.set_yscale('log')
    ax.set_xlim(1, 20)
    # ax.set_ylim(2, 7)
    # ax.set_yticks([1, 2, 3, 4])
    ax.set_xscale('log')
    # ax.set_yscale('log')
    # ax.set_xticks([2, 5, 10, 20])
    ax.set_xticks([2, 5, 10, 20])
    ax.get_xaxis().set_major_formatter(matplotlib.ticker.ScalarFormatter())
    
    ax.set_axisbelow(True)
    # ax.grid(zorder=-1000)
    ax.xaxis.grid(color='gray', alpha=0.5, zorder=-20)
    ax.yaxis.grid(color='gray', alpha=0.5, zorder=-20, which='both')
        
fig.savefig(fig_path + watershed_name +
            '_qmna_' + str(mod_list) + '.png', dpi=300, bbox_inches='tight')

#%% PERSISTENCY

plot_maps = True

# mod_list = [
#             # 'MPI-CCL','MPI-R09',
#             # 'CNR-RAC',
#             # 'ECE-RCA',
#             # 'ECE-RCA','ECE-RAC',
#             'HAD-REG',
#             # 'NOR-R15'
#             ]
# mod_list = ['TOT1']

watershed_names = ['Cheze']

# typ_climate = 'SURFEX'
typ = 'surf-trans-v3'
# mod_list = ['IPS1']

# mod_list = ['ACC1','BCC1','BNU1','CAN1','CAN2','CAN3','CAN4','CAN5',
#             'CNR1','CSI1','IPS1','MIR1','MIR2','MIR3','NOR1']
mod_list = ['TOT1']
# mod_list = ['IPS1']

mods_list = [mod_list]

# sce_list = ['RCP2.6', 'RCP8.5']
# sce_list = ['RCP8.5']
sce_list = ['RCP2.6']

for sce in sce_list:

    superficie = pd.DataFrame()
    
    for m in np.arange(0,11+1,1):
    
        for mod_list in mods_list:
        
            for watershed_name in watershed_names:
                    
                rcp26 = pd.DataFrame()
                rcp85 = pd.DataFrame()
            
                stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'  # necessary for plots
                simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
                
                mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
                cell = np.ma.masked_array(mask, mask=(mask<0)).count()
                
                wbt.vector_lines_to_raster(stable_folder+'geographic/'+'watershed_contour.shp',
                                           stable_folder+'geographic/'+'watershed_contour.tif',
                                           base = stable_folder+'geographic/'+'watershed_dem.tif')
                
                df_ano = pd.DataFrame()
                
                _SON_h = []
                _DJF_h = []
                _MAM_h = []
                _JJA_h = []
                
                _SON_f = []
                _DJF_f = []
                _MAM_f = []
                _JJA_f = []
                
                _SON_ano = []
                _DJF_ano = []
                _MAM_ano = []
                _JJA_ano = []
                
                # for sce in ['RCP2.6','RCP8.5']:
                # for sce in sce_list:
                        
                for mod in mod_list:
                
                    simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
                    
                    # if len(simul_list)>0 :
                
                    for simul in simul_list:
                        
                        model_name = simul.split('\\')[-1]
                        Sy = float(model_name.split('_')[3].split('-')[0]) # %
                        K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
                        E = float(model_name.split('_')[3].split('-')[2]) # m
                        D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
                        params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
                        
                        Smod_path = simul+'/_watershed/_simulated_results.csv'            
                        Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)

                        '''
                        figb, axb = plt.subplots(1,1, figsize=(5,5))
                        axb.plot(select_period(Smod.recharge,2010, 2040),
                                 select_period(Smod.recharge,2068, 2098),marker='o', lw=0)
                        # axb.plot(select_period(Smod.recharge,2070, 2100))
                        axb.set_yscale('log')
                        axb.set_xscale('log')
                        axb.set_xlim(0, 0.008)
                        axb.set_ylim(0, 0.008)
                        axb.set_title(mod)
                        '''
                        
                        acc_npy = np.load(os.path.join(simul, '_watershed','accumulation_flux.npy'), allow_pickle=True).item()
                        
                        def season_anomaly(months, begin_h, end_h, begin_f, end_f):
                            # months = [5,6,7]
                            # begin_h = 18*12
                            # end_h = 48*12
                            # begin_f = -30*12
                            # end_f = 0
                        
                            # Historic
                            if begin_h == 0:
                                acc_npy_h = list(acc_npy.items())[:end_h]
                            else:
                                acc_npy_h = list(acc_npy.items())[begin_h:end_h]
                            acc_npy_1 = list(acc_npy_h)[months[0]::12]
                            acc_npy_2 = list(acc_npy_h)[months[1]::12]
                            acc_npy_3 = list(acc_npy_h)[months[2]::12]
                            acc_npy_h = acc_npy_1 + acc_npy_2 + acc_npy_3
                            for key in range(len(acc_npy_h)):
                                acc_npy_h[key] = np.ma.masked_array(acc_npy_h[key][1], mask=(mask<0))
                            zero = acc_npy_h[0] * 0
                            for i in range(len(acc_npy_h)):
                                tempo = acc_npy_h[i].copy()
                                tempo[tempo>0] = 1
                                zero = zero + tempo
                            days_flux_h = zero.copy() / len(acc_npy_h)
                        
                            # To look
                            if end_f == 0:
                                acc_npy_f = list(acc_npy.items())[begin_f:]
                            else:
                                acc_npy_f = list(acc_npy.items())[begin_f:end_f]
                            acc_npy_1 = list(acc_npy_f)[months[0]::12]
                            acc_npy_2 = list(acc_npy_f)[months[0]::12]
                            acc_npy_3 = list(acc_npy_f)[months[2]::12]
                            acc_npy_f = acc_npy_1 + acc_npy_2 + acc_npy_3
                            for key in range(len(acc_npy_f)):
                                acc_npy_f[key] = np.ma.masked_array(acc_npy_f[key][1], mask=(mask<0))
                            zero = acc_npy[0] * 0
                            for i in range(len(acc_npy_f)):
                                tempo = acc_npy_f[i].copy()
                                tempo[tempo>0] = 1
                                zero = zero + tempo
                            days_flux_f = zero.copy() / len(acc_npy_f)
                            
                            # Anomaly
                            # days_flux_ano = ( (days_flux_f - days_flux_h) ) * 100
                            days_flux_ano = ( (days_flux_f - days_flux_h) ) / days_flux_h
                            # data = np.ma.masked_where((days_flux_ano==0)&(days_flux_h==0), days_flux_ano)
                            data = np.ma.masked_where((days_flux_ano==0)|(days_flux_h==0), days_flux_ano)
                            # data = data.flatten().filled(np.nan)
                            # data = data.flatten()
                            # data = days_flux_ano[~days_flux_ano.mask]
                            # data = data.compressed()
                            # data = data[~np.isnan(data)]
                            data = days_flux_ano[~days_flux_ano.mask]
                            
                            return days_flux_h, days_flux_f, days_flux_ano, data
                        
                        begin_h = 20*12
                        end_h = 50*12
                        # begin_h = 3*12
                        # end_h = 38*12
                        # begin_f = -60*12
                        # end_f = -30*12
                        begin_f = -60*12
                        end_f = -30*12
                        
                        h_son, f_son, ano_son, son = season_anomaly([8,9,10], begin_h, end_h, begin_f, end_f)
                        # plt.plot(son)
                        # print(len(son))
                        h_djf, f_djf, ano_djf, djf = season_anomaly([9,10,11,0,1,2], begin_h, end_h, begin_f, end_f)
                        # plt.plot(djf)
                        # print(len(djf))
                        h_mam, f_mam, ano_mam, mam = season_anomaly([2,3,4], begin_h, end_h, begin_f, end_f)
                        # plt.plot(mam)
                        # print(len(mam))
                        h_jja, f_jja, ano_jja, jja = season_anomaly([3,4,5,6,7,8], begin_h, end_h, begin_f, end_f)
                        # h_jja, f_jja, ano_jja, jja = season_anomaly([0,0,0], begin_h, end_h, begin_f, end_f)
                        # h_jja, f_jja, ano_jja, jja = season_anomaly([0,1,2,3,4,5,6,7,8,9,10,11], begin_h, end_h, begin_f, end_f)
                        h_jja, f_jja, ano_jja, jja = season_anomaly([m,m,m], begin_h, end_h, begin_f, end_f)
    
                        # plt.plot(jja)
                        # print(len(jja))
                        
                        df_ano['SON_'+mod+'_'+sce] = pd.Series(son)
                        df_ano['DJF_'+mod+'_'+sce] = pd.Series(djf)
                        df_ano['MAM_'+mod+'_'+sce] = pd.Series(mam)
                        df_ano['JJA_'+mod+'_'+sce] = pd.Series(jja)
                        
                        _SON_h.append(h_son)
                        _DJF_h.append(h_djf)
                        _MAM_h.append(h_mam)
                        _JJA_h.append(h_jja)
                        
                        _SON_f.append(f_son)
                        _DJF_f.append(f_djf)
                        _MAM_f.append(f_mam)
                        _JJA_f.append(f_jja)
                        
                        _SON_ano.append(ano_son)
                        _DJF_ano.append(ano_djf)
                        _MAM_ano.append(ano_mam)
                        _JJA_ano.append(ano_jja)
        
                if watershed_name == 'Dam':
                    canut_ano = df_ano.copy()
                # if watershed_name == 'Nancon':
                #     nancon_ano = df_ano.copy()
            
                _SON_h_mean = sum(_SON_h)/len(_SON_h)
                _DJF_h_mean = sum(_DJF_h)/len(_DJF_h)
                _MAM_h_mean = sum(_MAM_h)/len(_MAM_h)
                _JJA_h_mean = sum(_JJA_h)/len(_JJA_h)
                
                _SON_f_mean = sum(_SON_f)/len(_SON_f)
                _DJF_f_mean = sum(_DJF_f)/len(_DJF_f)
                _MAM_f_mean = sum(_MAM_f)/len(_MAM_f)
                _JJA_f_mean = sum(_JJA_f)/len(_JJA_f)
                
                # _SON_ano_mean = sum(_SON_ano)/len(_SON_ano)
                # _DJF_ano_mean = sum(_DJF_ano)/len(_DJF_ano)
                # _MAM_ano_mean = sum(_MAM_ano)/len(_MAM_ano)
                # _JJA_ano_mean = sum(_JJA_ano)/len(_JJA_ano)
                 
                _SON_ano_mean = ( _SON_f_mean - _SON_h_mean ) / _SON_h_mean
                _DJF_ano_mean = ( _DJF_f_mean - _DJF_h_mean ) / _DJF_h_mean
                _MAM_ano_mean = ( _MAM_f_mean - _MAM_h_mean ) / _MAM_h_mean
                _JJA_ano_mean = ( _JJA_f_mean - _JJA_h_mean ) / _JJA_h_mean
                
                if watershed_name == 'Canut':
                    canut_ano = df_ano.copy()
                if watershed_name == 'Nancon':
                    nancon_ano = df_ano.copy()
                
                # for season, days_flux_h, days_flux_f, days_flux_ano in zip(['SON', 'DJF', 'MAM', 'JJA'],
                #                                                             [_SON_h_mean, _DJF_h_mean, _MAM_h_mean, _JJA_h_mean],
                #                                                             [_SON_f_mean, _DJF_f_mean, _MAM_f_mean, _JJA_f_mean],
                #                                                             [_SON_ano_mean, _DJF_ano_mean, _MAM_ano_mean, _JJA_ano_mean]):
            
                # for season, days_flux_h, days_flux_f, days_flux_ano in zip(['DJF',  'JJA'],
                #                                                             [_DJF_h_mean, _JJA_h_mean],
                #                                                             [_DJF_f_mean, _JJA_f_mean],
                #                                                             [_DJF_ano_mean, _JJA_ano_mean]):
                            
                for season, days_flux_h, days_flux_f, days_flux_ano in zip(['JJA'],
                                                                            [_JJA_h_mean],
                                                                            [_JJA_f_mean],
                                                                            [_JJA_ano_mean]):
    
                    if plot_maps == True:
                    
                        fig, ax = plt.subplots(1,1, figsize=(10,10))
                        
                        stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'  # necessary for plots
                        line = imageio.imread(stable_folder+'geographic/'+'watershed_contour.tif')
                        line = np.ma.masked_where(line < 0, line)
                        mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
                        
                        cmap = plt.cm.Oranges_r
                        cmaplist = [cmap(i) for i in range(cmap.N)]
                        cmaplist = ['darkred','orange']
                        # cmaplist[-1] = (.5, .5, .5, 1.0) # first value
                        cmap = mpl.colors.LinearSegmentedColormap.from_list(
                            'Custom cmap', cmaplist, cmap.N)
                        minn = -1.01 # 0 
                        maxn = 0 # 1.1
                        intn = 0.1 # 0.1
                        bounds = np.arange(minn, maxn, intn)
                        norm = mpl.colors.BoundaryNorm(bounds, cmap.N)
                        pcn = ax.imshow(np.ma.masked_where(days_flux_ano >= 0, days_flux_ano), #1
                                        cmap = cmap,
                                        norm=norm, alpha=1)
                        # plt.imshow(days_flux_ano)
                        # plt.colorbar()
                        
                        cmap = plt.cm.Blues
                        # cmap = plt.cm.winter_r
                        cmaplist = [cmap(i) for i in range(cmap.N)]
                        cmaplist = ['deepskyblue','navy']
                        # cmaplist[-1] = (.5, .5, .5, 1.0) # first value
                        cmap = mpl.colors.LinearSegmentedColormap.from_list(
                            'Custom cmap', cmaplist, cmap.N)
                        minp = 0 # 1
                        maxp = 1.01 # 2.1
                        intp = 0.1 # 0.1
                        bounds = np.arange(minp, maxp, intp)
                        norm = mpl.colors.BoundaryNorm(bounds, cmap.N)
                        # pcp = ax.imshow(np.ma.masked_where(days_flux_ano <= 0, days_flux_ano), #1
                        #                 cmap = cmap,
                        #                 norm=norm, alpha=1)
                        
                        # plt.imshow(np.ma.masked_where(days_flux_ano <= 0, days_flux_ano))
                        # plt.colorbar()
                        
                        pc = ax.imshow(np.ma.masked_where((days_flux_ano>-1),
                                                          days_flux_ano),
                                                    cmap = mpl.colors.ListedColormap('darkred'))
                        
                        pc = ax.imshow(np.ma.masked_where((days_flux_ano<=-1)|(days_flux_ano>=0),
                                                          days_flux_ano),
                                                    cmap = mpl.colors.ListedColormap('darkorange'))
                        
                        pc = ax.imshow(np.ma.masked_where((days_flux_ano<=0)|(days_flux_ano>=1),
                                                          days_flux_ano),
                                                    cmap = mpl.colors.ListedColormap('dodgerblue'))
                        
                        pc = ax.imshow(np.ma.masked_where((days_flux_ano<1),
                                                          days_flux_ano),
                                                    cmap = mpl.colors.ListedColormap('navy'))
                        
                        pc = ax.imshow(np.ma.masked_where((days_flux_ano!=0)|(days_flux_h==0),
                                                          days_flux_ano),
                                                    cmap = mpl.colors.ListedColormap('darkgray'))
                        
                        pc = ax.imshow(np.ma.masked_where((days_flux_f==0)|(days_flux_h!=0),
                                                          days_flux_f),
                                                    cmap = mpl.colors.ListedColormap('forestgreen'))
                        
                        # try:
                        #     days = days_flux_ano.copy()
                        #     days[(days_flux==0)|(days_flux_h!=0)] = np.nan
                        #     plt.imshow(days, cmap = mpl.colors.ListedColormap('k'))
                        # except:
                        #     pass
                        
                        ax.get_xaxis().set_visible(False)
                        ax.get_yaxis().set_visible(False)
                        ax.axis('off')
                        
                        ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
                        
                        plt.subplots_adjust(hspace = -0.6)
                                        
                        # position=fig1.add_axes([1,0.3,0.015,0.32])  ## the parameters are the specified position you set 
                        # cb = fig1.colorbar(pcp,cax=position) ##
                        # cb.set_ticks(np.arange(minp, maxp, intp))
                        # cb.set_ticklabels(np.arange(minp, maxp, intp).round(1))
                        # # cb.ax.invert_xaxis()
                        
                        # position=fig1.add_axes([1.10,0.3,0.015,0.32])  ## the parameters are the specified position you set 
                        # cb = fig1.colorbar(pcn,cax=position) ##   
                        # cb.set_ticks(np.arange(minn, maxn, intn))
                        # cb.set_ticklabels(np.arange(minn, maxn, intn).round(1))
                        
                        ax.set_title(mod+'_'+sce+'_'+str(m), fontsize=8)

                        # plt.close()
                        
                        fig.savefig(fig_path + watershed_name +
                                    '_PI_' + '_' + str(mod_list) +
                                    '_' + sce + '_' + str(m) + '.png', dpi=300, bbox_inches='tight')
                    
                    days_flux_ano = days_flux_ano * 100
                    total = days_flux_ano.count()
                    
                    n_0_100 = np.ma.masked_where((days_flux_ano >= 0)|(days_flux_ano <= -100), days_flux_ano).count()
                    n_100 = np.ma.masked_where((days_flux_ano > -100), days_flux_ano).count()
                    p_0_100 = np.ma.masked_where((days_flux_ano <= 0)|(days_flux_ano >= 100), days_flux_ano).count()
                    p_100 = np.ma.masked_where((days_flux_ano < 100), days_flux_ano).count()
                    flow_0 = np.ma.masked_where((days_flux_ano!=0)|(days_flux_h==0), days_flux_ano).count()
                    new_f = np.ma.masked_where((days_flux_f==0)|(days_flux_h!=0), days_flux_f).count()
                    
                    index_name = sce+'_'+mod_list[0]+'_'+season+'_'+str(m)
                    column_name = watershed_name+'_'
                    superficie.loc[index_name,column_name+'dry_100'] = (n_100 / total)*100
                    superficie.loc[index_name,column_name+'loosing_100-0'] = (n_0_100 / total)*100
                    superficie.loc[index_name,column_name+'flow_0'] = (flow_0 / total)*100
                    superficie.loc[index_name,column_name+'gaining_0-100'] = (p_0_100 / total)*100
                    superficie.loc[index_name,column_name+'wetter_100'] = (p_100 / total)*100
                    superficie.loc[index_name,column_name+'new_flow'] = (new_f / total)*100
                    
                    superficie.to_csv(fig_path + watershed_name +
                                '_table_PI_' + str(mod_list) + '_' + sce + '.csv', sep=';')
                
                
                

                
