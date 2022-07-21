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
        
# DATA WATERSHED

# site_names = [['Drains',None]]

for site_name in site_names[:]:

    watershed_name = site_name[0]
    code_name = site_name[1]
           
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)

    BV.add_geology(geology_path)
    BV.add_hydrology(hydrology_path, types_obs=types_obs, fields_obs=fields_obs)
    BV.add_oceanic(oceanic_path)
    BV.add_hydrometry(hydrometry_path)
    BV.add_intermittency(intermittency_path)
    BV.add_subbasin()
    BV.add_surfex(surfex_path)
    BV.add_drias(drias_path)

    print('##### '+watershed_name.upper()+' #####')

    BV.add_hydrodynamic()
    BV.add_forcing()
    
    watershed_display.watershed_dem(BV)
    watershed_display.watershed_local(dem_path, BV)
    
    try:
        if (watershed_name == 'Monfort') | (watershed_name == 'Roche'):
            BV.add_piezometry()
    except:
        pass
    
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
typ = 'calib-test-v2'

# mod_list = ['MPI-CCL','ECE-RCA','ECE-RAC','CNR-RAC',
#             'NOR-R15','CNR-ALA','HAD-REG','MPI-R09']
# mod_list = ['CNR-ALA']
# mod_list = ['MPI-R09','NOR-R15']
# mod_list = ['MPI-R09']
mod_list = ['REA']

sce_list = ['historic']
# sce_list = ['RCP2.6','RCP8.5']
# sce_list = ['RCP2.6']

#%% PARAM RUN MODEL

sim_state = 'transient' # 'steady' or 'transient'
# sim_state = 'steady' # 'steady' or 'transient'
modpath_sim = True # run modpath particle tracking if True
modpath_sim = False # run modpath particle tracking if True
nlay = 1

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
dic_v = [0.001,0.001,0.002,0.002,0.002,0.005,0.02,0.02]
# dic_v = [0.01]
dic_m = dict(zip(dic_t,dic_v))

# watershed_names = ['Canut']
# code_names = ['J7513010']

normalize=False

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
    
    df = pd.read_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')

    # Observed discharge
    # try:
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
    init_rech = None
    
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
    Koptim = df.perennial[0]
    Sy = dic_m[watershed_name]
    Ks = np.array([Koptim]) * 3600 * 24 # m/second to m/day
    Sys = [Sy]
    
    # Model of recharge
    for mod in mod_list:           
        for sce in sce_list:    
            
            # Recharge  
            if mod == 'REA':
                    
                f_simu = Qobs.first_valid_index().year+1-5
                l_simu = Qobs.last_valid_index().year-1
                if l_simu == 2021:
                    l_simu = 2019
                if f_simu < 1960:
                    f_simu = 1960
                    
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
                
                norm_Rea = Rech.copy()
                norm_Qobs = Qobs.copy()
                
                Rt_Rea_Qobs = (norm_Qobs.mean() / norm_Rea.mean())
                print(Rt_Rea_Qobs.round(2))
                Nt = (norm_Rea * Rt_Rea_Qobs)
                
                BV.forcing.update_recharge(Nt, sim_state=sim_state)
                fig, ax = plt.subplots()
                plt.plot(BV.forcing.recharge, c='r')
                plt.plot(Qobs, c='b')
                
                BV.forcing.update_recharge(select_period(BV.forcing.recharge, f_simu, l_simu), sim_state=sim_state)
                BV.forcing.update_runoff(select_period(BV.forcing.runoff, f_simu, l_simu), sim_state=sim_state)

            list_model_name = []
            list_of_success = []
            list_flow_model = []

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
                    compt+=1
                    
            print(list_of_success)
            
            dictio = {}
            dictio['list_model_name'] = list_model_name
            dictio['list_of_success'] = list_of_success
            dictio['list_flow_model'] = list_flow_model
            h5file = simulations_folder+'/'+'list_'+typ+'_'+var+'-'+mod+'-'+sce
            
            dd.io.save(h5file, dictio)
                        
#%% POSTPROCESS MODEL

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
            d = dd.io.load(h5file)
            list_model_name = d['list_model_name'][:]
            list_of_success = d['list_of_success'][:]
            list_flow_model = d['list_flow_model'][:]
            
            for model_name, success, flow_model in zip(list_model_name, list_of_success, list_flow_model):
                    
                if success==True:
                        print(success)
                        
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
                        
                        # # Extract results
                        BV.results_modflow(ident=model_name,
                                           actual_date=actual_date,
                                           time_step=time_step)
                        
                        ## Plot maps
                        surf = modflow_display.SurfaceOutputs(flow_model.climatic, simulations_folder, stable_folder,
                                                              model_name, types_obs,
                                                              save_gif=False,
                                                              first_only=True,
                                                              sim_state=sim_state,
                                                              outflow=True,
                                                              accflux=True,
                                                              intermittency=False,
                                                              chronics=False)

#%% ---- QUICK

#%% EXTRACT RESIDENCE TIMES

watershed_names = ['Canut','Nancon']

for watershed_name in watershed_names[:] :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    df = pd.read_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'
    
    figsim_folder = simulations_folder + '_figures/'
    toolbox.create_folder(figsim_folder)
    dem = rasterio.open(BV.geographic.watershed_dem)
    dem_data = dem.read(1)
    
    for mod in mod_list:

        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]

            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            # Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas

            folder_results = simulations_folder + '/' + model_name + '/' + '_watershed/_tifs/'
        
            path_res = folder_results+'residence_times_t(0).tif'
            
            res_time = rasterio.open(path_res)
            res_time_data = res_time.read(1)
            res_time_data = res_time_data
                
            if watershed_name == 'Canut':
                path_obs = stable_folder+'/add_data/'+'recap_terrain.shp'
                path_shp = simulations_folder + '/' + model_name + '/' + '_watershed/_shp/'
                toolbox.create_folder(path_shp)
                path_dat = path_shp+'residence_times_data.shp'

                shp_obs = gpd.read_file(path_obs)
                shp_obs['geometry'] = shp_obs.geometry.buffer(100)
                # shp_obs = shp_obs[['ID_station', 'geometry']]
                shp_obs.to_file(path_dat, encoding='utf-8') # mode a

                # wbt.extract_raster_values_at_points(
                #                 path_res, 
                #                 path_dat, 
                #                 out_text=False)
                
                # Mathod 1
                wbt.raster_to_vector_polygons(
                        path_res, 
                        path_shp+'raster_polygonized.shp')
                raster_polyg = gpd.read_file(path_shp+'raster_polygonized.shp')
                intersect = gpd.overlay(shp_obs, raster_polyg, how='intersection')
                intersect[intersect['VALUE']==-np.inf] = np.nan
                res_dat = gpd.read_file(path_dat)
                res_dat['RES_TIME'] = np.nan
                res_dat['STD_TIME'] = np.nan
            
                for ID in intersect['Site'].unique():
                    # threshold = 1 #year
                    # threshold = threshold*365
                    # threshold = np.log10(threshold)
                    
                    mask = (intersect[intersect['Site']==ID]['VALUE'] !=0)
                    
                    mean_ID = np.nanmean(intersect[intersect['Site']==ID]['VALUE'][mask])
                    res_dat['RES_TIME'][res_dat['Site']==ID] = mean_ID
                    
                    std_ID = np.nanstd(intersect[intersect['Site']==ID]['VALUE'][mask])
                    res_dat['STD_TIME'][res_dat['Site']==ID] = std_ID
                
                # Method 2
                '''
                from rasterstats import zonal_stats
                stats = zonal_stats(path_dat, path_res)
                # print(stats[0].keys())
                # print(stats)
                means = [f['mean'] for f in stats]
                res_dat = gpd.read_file(path_dat)
                res_dat['RES_TIME'] = means
                '''
            
                res_dat['RES_TIME'][res_dat['RES_TIME']==-np.inf] = np.nan
                res_dat['STD_TIME'][res_dat['STD_TIME']==-np.inf] = np.nan
                res_dat.to_file(path_shp + 'extract_RTD.shp', encoding = 'utf-8')
                
                res_dat['RES_TIME'] = (10**(res_dat['RES_TIME']))/365
                res_dat['STD_TIME'] = (10**(res_dat['STD_TIME']))/365
            
            vmin = 0
            vmax = res_time_data.max()
            
            fig, ax = plt.subplots(1,1, figsize=(5,5))
            # plt.imshow(res_time_data)
            # plt.colorbar()
            
            #show(np.ma.masked_where(dem_data < -0, res_time_data), ax=ax, transform=dem.transform, 
            show(np.ma.masked_where(dem_data < -0, (10**res_time_data)/365), ax=ax, transform=dem.transform, 
                 cmap='jet', alpha=1, zorder=2, aspect="auto", vmin=vmin, vmax=vmax)

            if watershed_name=='Canut':
                shp_obs.plot(ax=ax, color=None, marker='o', markersize=10,
                             edgecolor='k', lw=1, zorder=30)
            # res = res_dat.plot(ax=ax, cmap='jet',  marker='o', markersize=10,
            #              edgecolor='k', lw=1, column='RES_TIME', zorder=30,
            #              vmin=vmin, vmax=vmax)
            bounds = dem.bounds
            xlim = ([bounds[0], bounds[2]])
            ylim = ([bounds[1], bounds[3]])
            ax.set_xlim(xlim)
            ax.set_ylim(ylim)
            scalebar = ScaleBar(1,box_alpha=0, scale_loc = 'bottom', location='upper left')
            ax.add_artist(scalebar)
            ax.get_xaxis().set_visible(False)
            ax.get_yaxis().set_visible(False)
            ax.set_title(model_name, fontproperties=fontprop)
            ax.set(aspect='equal')
            sm = plt.cm.ScalarMappable(cmap='jet', norm=plt.Normalize(vmin=vmin, vmax=vmax))
            divider = make_axes_locatable(ax)
            cax = divider.append_axes(size="2%",position='right', pad=0.05)
            fig.add_axes(cax)
            cbar = fig.colorbar(sm, cax=cax, orientation="vertical")
            cbar.ax.get_ymajorticklabels()
            cbar.ax.tick_params(labelsize=10)
            cbar.ax.yaxis.set_ticks_position('right')
            cbar.ax.tick_params(size=2)
            contour = gpd.read_file(BV.geographic.watershed_contour_shp)
            contour.plot(ax=ax, lw=1.5, color='k', zorder=20, legend=False, label='Watershed')
            cbar.set_ticks(list(cbar.get_ticks()))
            # cbar.set_ticklabels(list(cbar.get_ticks())[::-1])
            cbar.set_label('Residence times [years]', rotation=270, labelpad=25)
    
            if watershed_name=='Canut':
                res_dat['coords'] = res_dat['geometry'].apply(lambda x: x.representative_point().coords[:])
                res_dat['coords'] = [res_dat[0] for res_dat in res_dat['coords']]
                for idx, row in res_dat.iterrows():
                    row['coords'] = (row['coords'][0], row['coords'][1]+100)
                    ax.annotate(s=row['Site'], xy=row['coords'],
                                 horizontalalignment='center')
    
            fig.savefig(figsim_folder+model_name+'.png', dpi=300, bbox_inches='tight')
    
            if watershed_name=='Canut':

                fig, ax = plt.subplots(1,1, figsize=(4,4))
                mean_obs = res_dat[['Tot']].mean(axis=1)
                std_obs = res_dat[['Tot']].std(axis=1)
                x=2021-(mean_obs)
                xerr=std_obs
                mean_sim = res_dat['RES_TIME']
                y=mean_sim
                yerr = res_dat['STD_TIME']
                ax.scatter(x, y, c=y, s=50, cmap=mpl.colors.ListedColormap('k'))
                plt.errorbar(x, y , xerr=list(xerr), yerr=yerr, lw=1, fmt="o", color='k')
                # ax.legend()
                ax.set_xlabel('$Age_{obs}$ [years]')
                ax.set_ylabel('$Age_{sim}$ [years]')
                ax.set_title(model_name, fontproperties=fontprop)
                for i, txt in enumerate(res_dat['Site']):
                    ax.annotate(txt, (x[i], y[i]))
                xn=20
                xx=80
                yn=20
                yx=80
                # ax.set_xlim(xn, xx)
                # ax.set_ylim(yn, yx)
                # ax.set_xscale('log')
                # ax.set_yscale('log')
                # ax.plot(np.linspace(xn,xx,50), np.linspace(yn,yx,50), 
                #         linestyle='--', color='grey', linewidth=2, zorder=-1)
                maxx = max(ax.get_xlim()[0],ax.get_xlim()[1])
                maxy = max(ax.get_ylim()[0],ax.get_ylim()[1])
                minx = min(ax.get_xlim()[0],ax.get_xlim()[1])
                miny = min(ax.get_ylim()[0],ax.get_ylim()[1])
                maxt = max(maxx,maxy)
                mint = max(minx,miny)
                # ax.plot(np.linspace(mint,maxt,50),
                #         np.linspace(mint,maxt,50), 
                #         linestyle='--', color='grey', linewidth=2, zorder=-1)
                
                fig.savefig(figsim_folder+'obs_vs_sim_'+model_name+'.png', dpi=300, bbox_inches='tight')
                
            all_dat = res_dat.copy()
            all_dat[model_name] = res_dat['RES_TIME']
            
all_dat['coords'] = np.nan
all_dat.to_file(simulations_folder+'residence_times_all.shp', sep=';', encoding='utf-8')

#%% EXTRACT PATHLINES TIMES

for watershed_name in watershed_names[:] :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    # df = pd.read_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

    dem = rasterio.open(BV.geographic.watershed_dem)
    dem_data = dem.read(1)

    simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
    simul = simul_list[0]

    model_name = simul.split('\\')[-1]

    folder_results = simulations_folder + '/' + model_name + '/' + '_watershed/_tifs/'
    
    ##### LOOOP 2D #####
    visu = visualization.Visualization(BV, model_name)
    # visu.visual2D(object_list = ['map','grid', 'watertable', 'watertable_depth','drain_flow','surface_flow','pathlines', 'residence_times'],
                  # color_scale = [(None,None),(0,140),(0,140),(0,2),(None,None),(None,None),(None,None),(None,None)], lines=10000)
    visu.visual2D(object_list = ['pathlines'],
                  color_scale = [(None,None)], lines=None)

#%% CROSS SECTION 2D INTERAC

watershed_names = ['Nancon']
# watershed_names = ['Canut']

for watershed_name in watershed_names[:]:
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    interactive = False
    
    dem = rasterio.open(BV.geographic.watershed_dem)
    dem_data = np.ma.masked_where(dem.read(1) < -100, dem.read(1)) # dem data
    list_path = sorted(glob.glob(simulations_folder+typ+'*'),
                        key=os.path.getmtime, reverse=True)
    model_name = list_path[-1].split('\\')[-1]
    wt_data = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+'watertable_elevation_t(0).tif') # watertable data
    river_data = imageio.imread(stable_folder+'/hydrology/'+'complete.tif') # river data
    modflow_display.interactive_cross_section(dem_data, wt_data, river_data, interactive=interactive)

#%% CROSS SECTION 2D MANUAL

from IPython import get_ipython

BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True,
                              modflow_path=modflow_path)

interactive = False

dem = rasterio.open(BV.geographic.watershed_dem)
dem_data = np.ma.masked_where(dem.read(1) < -100, dem.read(1)) # dem data
list_path = sorted(glob.glob(simulations_folder+typ+'*'),
                    key=os.path.getmtime, reverse=True)
model_name = list_path[-1].split('\\')[-1]

dem_data = imageio.imread(BV.geographic.watershed_dem)
wt_data = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+'watertable_elevation_t(0).tif')
river_data = imageio.imread(stable_folder+'/hydrology/'+'complete.tif')

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

#%% CROSS SECTION 2D SIMPLE

typ = 'calibr-t1'

watershed_names = ['Canut','Nancon']
# watershed_names = ['Canut']

# fig, axs = plt.subplots(2, 1, figsize=(5,4), dpi=300)

dates = pd.date_range(start='01/01/1972', end='31/12/2019', freq='M')

for watershed_name in watershed_names[:]:    
    
    # if watershed_name == 'Nancon':
    #     ax = axs[1]
    # if watershed_name == 'Canut':
    #     ax = axs[0]
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    dem = rasterio.open(BV.geographic.watershed_dem)
    dem_data = np.ma.masked_where(dem.read(1) < -100, dem.read(1)) # dem data
    list_path = sorted(glob.glob(simulations_folder+typ+'*'),
                        key=os.path.getmtime, reverse=True)
    model_name = list_path[-1].split('\\')[-1]
        
    wbt.vector_lines_to_raster(stable_folder+'geographic/'+'watershed_contour.shp',
                               stable_folder+'geographic/'+'watershed_contour.tif',
                               base = stable_folder+'geographic/'+'watershed_dem.tif')
    line = imageio.imread(stable_folder+'geographic/'+'watershed_contour.tif')
    line = np.ma.masked_where(line <= 0, line)
        
    mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
    
    import itertools            
    
    watertable_elevation = np.load(simulations_folder+model_name+'/_watershed/'+'watertable_elevation'+'.npy', allow_pickle=True).item()
    # acc_npy = np.load(simulations_folder+model_name+'/_watershed/'+'accumulation_flux.npy', allow_pickle=True).item()
    # acc_npy = dict(itertools.islice(acc_npy.items(), 12))

    # for key in acc_npy:
    #     # print(key)
    #     # acc = np.ma.masked_where(dem.read(1) < 0, dem.read(1))
    #     acc_npy[key] = np.ma.masked_array(acc_npy[key], mask=(mask<0))
    # zero = acc_npy[0] * 0
    # for l in range(len(acc_npy)):
    #     tempo = acc_npy[l].copy()
    #     tempo[tempo>0] = 1
    #     zero = zero + tempo
    # days_flux = zero.copy() # / len(acc_npy)

    for key in dict(itertools.islice(watertable_elevation.items(),
                                     len(watertable_elevation)-12*10,
                                     len(watertable_elevation))):
    # for key in watertable_elevation:
        print(key)

        dem_data = imageio.imread(BV.geographic.watershed_dem)
        # wt_data = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+'watertable_elevation_t(0).tif')
        wt_data = watertable_elevation[key]
        river_data = imageio.imread(stable_folder+'/hydrology/'+'complete.tif')
    
        xvalues = np.linspace(-1,1,dem_data.shape[1])
        yvalues = np.linspace(-1,1,dem_data.shape[0])
        xx, yy = np.meshgrid(xvalues,yvalues)
        
        cur_x = dem_data.shape[1] /2
        cur_y = dem_data.shape[0] /2
        
        cur_x = 65
        cur_y = 40
        
        dem_max = dem_data.max()
        dem_prof = dem_data.astype(float)
        dem_prof[dem_prof<0] = np.nan
        wt_prof = wt_data.astype(float)
        wt_prof[wt_prof<0] = np.nan
        
        # if watershed_name == 'Nancon':
        #     x0, y0 = 50, 40 # These are in _pixel_ coordinates !
        #     x1, y1 = 100, 50
        #     num = int(np.hypot(x1-x0, y1-y0))
        #     num = x1-x0
        #     # num=100
        #     x, y = np.linspace(x0, x1, num), np.linspace(y0, y1, num)
        #     zd = dem_data[y.astype(np.int), x.astype(np.int)]
        #     zw = wt_data[y.astype(np.int), x.astype(np.int)]
        # if watershed_name == 'Canut':
        #     x0, y0 = 60, 20 # These are in _pixel_ coordinates !
        #     x1, y1 = 60, 50
        #     num = int(np.hypot(x1-x0, y1-y0))
        #     num = x1-x0
        #     num=100
        #     x, y = np.linspace(x0, x1, num), np.linspace(y0, y1, num)
        #     zd = dem_data[y.astype(np.int), x.astype(np.int)]
        #     zw = wt_data[y.astype(np.int), x.astype(np.int)]
        
        if watershed_name == 'Nancon':
            dem_h_plot = dem_prof[int(cur_y),:]
            dem_h_plot[dem_h_plot == 0] = np.nan
            wt_h_plot = wt_prof[int(cur_y),:]
            wt_h_plot[wt_h_plot == 0] = np.nan
        if watershed_name == 'Canut':
            dem_v_plot = dem_prof[:,int(cur_x)]
            dem_v_plot[dem_v_plot == 0] = np.nan
            wt_v_plot = wt_prof[:,int(cur_x)]
            wt_v_plot[wt_v_plot == 0] = np.nan
            
        dem_max = dem_data.max()
        dem_prof = dem_data.astype(float)
        dem_prof[dem_prof<0] = np.nan
        dem_plot = np.ma.masked_array(dem_data, mask=(dem_data<0))
        
        wt_prof = wt_data.astype(float)
        wt_prof[wt_prof<0] = np.nan
                
        # fig, ax = plt.subplots(1, 1, figsize=(5,8))
        # # axs = axs.ravel()
        # # ax = axs[0]
        # # ax.autoscale(enable=False)
        # # ax.plot(Rech)
        # # ax = axs[1]
        # # ax.autoscale(enable=False)
        # ax.imshow(dem_plot, origin='lower', cmap='Greys', aspect="equal",)
        # ax.set_ylim(ax.get_ylim()[::-1])
        # # d_line = ax.plot((x0,x1),(y0,y1), 'b-')
        # v_line = ax.axvline(cur_x, color='k', lw=2)
        # h_line = ax.axhline(cur_y, color='k', lw=2)
        
        # if watershed_name == 'Nancon':
        #     d_prof = ax.plot(x, zd, 'r-')
        #     w_prof = ax.plot(x, zw, 'b-')
        # if watershed_name == 'Canut':
        #     d_prof = ax.plot(y, zd, 'r-')
        #     w_prof = ax.plot(y, zw, 'b-')

        # fig, axs = plt.subplots(1, 2, figsize=(8,3), dpi=300)
        # fig, ax = plt.subplots(1, 1, figsize=(6,3), dpi=300)
     
        # import matplotlib.gridspec as gridspec
        # gs = gridspec.GridSpec(1,2, width_ratios=[1], height_ratios=[1,1])
        # fig = plt.figure()
        
        # ax = plt.subplot(gs[0])
        
        # ax = axs[0]
        # # ax.autoscale(enable=False)
        # ax.imshow(dem_plot, origin='lower', cmap='Greys',
        #           aspect="equal")
        # ax.set_ylim(ax.get_ylim()[::-1])
        # # d_line = ax.plot((x0,x1),(y0,y1), 'b-')
        # if watershed_name == 'Canut':
        #     v_line = ax.axvline(cur_x, color='k', lw=2)
        # if watershed_name == 'Nancon':
        #     h_line = ax.axhline(cur_y, color='k', lw=2)
            
        # # acc_npy = np.load(os.path.join(simul, '_watershed','accumulation_flux.npy'), allow_pickle=True).item()
        # inf = 0
        # sup = 12
        # compt = 0
        # step = int(round(len(acc_npy)/12))
        
        # for i in range(step):
        #     print(str(i)+'/'+str(step))
        #     interv = list(acc_npy.items())[inf:sup]
        #     # print(interv)
        #     for l in range(len(interv)):
        #         # key = tupl[0]
        #         # print(key)
        #         interv[l] = np.ma.masked_array(interv[l][1], mask=(mask<0))
                
        #     zero = acc_npy[0] * 0
        #     for j in range(len(interv)):
        #         tempo = interv[j].copy()
        #         tempo[tempo>0] = 1
        #         zero = zero + tempo
        #     days_flux = zero.copy()
        #     days_flux = np.ma.masked_array(days_flux, mask=(mask<0))
        #     days_flux = np.ma.masked_array(days_flux, mask=(days_flux<=0))
            
        #     for k in range(len(interv)):
        #         to = interv[k].copy()
                
        #         # fig, ax = plt.subplots(1,1, figsize=(7,6))
        #         # ax.imshow(to)
                
        #         to[(to>0) & (days_flux==12)] = 2
        #         to[(to>0) & (days_flux<12)] = 1
                
        #         to = np.ma.masked_array(to, mask=(mask<0))
        #         to = np.ma.masked_array(to, mask=(to<=0))
                
        #         # fig, ax = plt.subplots(1,1, figsize=(7,6))
        #         # image_hidden = ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys')
        #         ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys', alpha=0.5, zorder=0)
        #         ax.imshow(np.ma.masked_where(to==1, to),
        #                   cmap = mpl.colors.ListedColormap(['dodgerblue']))
        #         ax.imshow(np.ma.masked_where(to==2, to),
        #                   cmap = mpl.colors.ListedColormap(['darkorange']))
        #         ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
        #         ax.get_xaxis().set_visible(False)
        #         ax.get_yaxis().set_visible(False)
                
        #         # ax.set_title(str(years[i])+'-'+(str(k+1)))
                
        #         # plt.close()
                
        #         # hydromet = gpd.read_file(BV.hydrometry.hydrometric_clip)
        #         # ax.plot(65, 45, zorder=7, marker='o', color='yellow', 
        #         #         markersize=5, lw=1)

        #         # intermit = gpd.read_file(BV.intermittency.onde_clip)
        #         # ax.plot(color='yellow', zorder=8, marker='s',markersize=5,
        #         #                       edgecolor='black', lw=1)

        #         compt += 1
                
        #     inf+=12
        #     sup+=12
    
        # x1,x2 = ax.get_xlim()
        # y1,y2 = ax.get_ylim()
        # xRange = abs(x2-x1)
        # yRange = abs(y2-y1)

        # ax = plt.subplot(gs[1])
        # ax = axs[1]
        # ax.autoscale(enable=False)
        
        fig, ax = plt.subplots(1, 1, figsize=(5,3), dpi=300)
    
        if watershed_name == 'Nancon':
            # dem_h_prof, = ax.plot(np.arange(xx.shape[1])*75,dem_h_plot, c='saddlebrown', lw=2)
            # wt_h_prof, = ax.plot(np.arange(xx.shape[1])*75, wt_h_plot, c='dodgerblue', lw=2)
            wt_h_fill = ax.fill_between(np.arange(xx.shape[1])*75, 0, wt_h_plot,
                                            color='deepskyblue', alpha=0.5, lw=0)
            wt_h_fill = ax.fill_between(np.arange(xx.shape[1])*75, wt_h_plot, dem_h_plot,
                                            color='saddlebrown', alpha=0.5, lw=0)
            ax.set_xlim(4000, 7000)
            ax.set_ylim(130, 170)
            ax.set_yticks([140,160])
        if watershed_name == 'Canut':
            # dem_v_prof, = ax.plot(np.arange(xx.shape[0])*75, dem_v_plot, c='saddlebrown', lw=2)
            # wt_v_prof, = ax.plot(np.arange(xx.shape[0])*75, wt_v_plot, c='dodgerblue', lw=2)
            wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75, 0, wt_v_plot,
                                                color='deepskyblue', alpha=0.5, lw=0)
            wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75, wt_v_plot, dem_v_plot,
                                                color='saddlebrown', alpha=0.5, lw=0)
            ax.set_xlim(1000, 4000)
            ax.set_ylim(90, 130)
            ax.set_yticks([100,120])
        
        # ax.set_aspect(xRange/yRange)
        # asp = np.diff(ax.get_xlim())[0] / np.diff(ax.get_ylim())[0]
        # ax.set_aspect(asp)
        
        ax.set_title(str(dates[key])[:7])
        
        plt.tight_layout()
        
        fig.savefig(simulations_folder+model_name+'/_figures/'+'cross_'+str(key)+'.png', dpi=300, bbox_inches='tight')

        # plt.plot(dem_h_plot)
        # plt.plot(wt_h_plot)

for watershed_name in watershed_names[:]:    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    list_path = sorted(glob.glob(simulations_folder+typ+'*'),
                        key=os.path.getmtime, reverse=True)
    model_name = list_path[-1].split('\\')[-1]

    begin_by = simulations_folder+model_name+'/_figures/'+'cross_'
    filenames = sorted(glob.glob(begin_by+'*.png'), key=os.path.getmtime)
    images = []
    for filename in filenames:
        images.append(imageio.imread(filename))
    imageio.mimsave(simulations_folder+model_name+'/_figures/'+'_GIF_cross_'+'.gif', images, duration=0.5, loop=0)

#%% MAPS TOP VIEW STEADY

# watershed_names = ['Nancon']
watershed_names = ['Canut']

for watershed_name in watershed_names[:]:
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
        
    list_path = sorted(glob.glob(simulations_folder+typ+'*'),
                        key=os.path.getmtime, reverse=True)
    model_name = list_path[-1].split('\\')[-1]

    visu = visualization.Visualization(BV, model_name)
    
    visu.visual2D(object_list = ['map', 'grid', 'watertable', 'watertable_depth',
                                  'drain_flow', 'surface_flow'],
                  color_scale = [(None,None),(None,None),(None,None),(0,10),
                                  (None,None),(None,None)])
    
    # visu.visual2D(object_list = ['pathlines', 'residence_times'],
    #               color_scale = [(None,None),(None,None)], 
    #               lines=100)



from calibration import calib_root, calib_dichotomy, calib_analysis, calib_exploration, calib_basis

typ = 'calib'

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

# watershed_names = ['Canut']

params_file = 'calib_explo_hom_2v_k1-n1'

wish = 0

sat_typ = 'seepage_areas'

for watershed_name in watershed_names[:]:
    
    print('##### '+watershed_name.upper()+' #####')

    min_nse = 50
    mean_meansat = 3 # sup
    min_maxsat = 8
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

    fig, ax = plt.subplots(1,1, figsize=(3.8,3.5))
    ax.set_aspect('auto')
    ax.axes.tick_params(which='both', direction='out', zorder=10)
    X,Y = np.meshgrid(test.params_values[0], test.params_values[1])
    Z=test.obj_function.copy()
    Z[Z<0] = 0
    from numpy import inf
    Z[Z == inf] = 0
    bounds = np.arange(0,1.1,0.1)
    norm = mpl.colors.Normalize(vmin=-1, vmax=1.0)
    # pc = ax.pcolormesh(X,Y,Z, cmap='jet', shading='gouraud', vmin=0, vmax=1) #figadd.cmap_white_jet()
    pc = ax.contourf(X/3600/24, Y*100, Z, levels=np.arange(0,1.1,0.1))    
    # divider = make_axes_locatable(ax)
    # cax = divider.append_axes('right', size='5%', pad=0.05)
    # position=fig.add_axes([1.05,0.33,0.03,0.5])  ##
    # cb = fig.colorbar(pc, cax=position, orientation='vertical')
    # cb.set_ticks(np.arange(0,1.1,0.2)) 
    # cb.set_label('$NSE_{log}$', rotation=270, labelpad=40)
    ax.set_xscale('log')
    ax.set_ylabel('Φ [%]')
    ax.set_xlabel('K [m/s]')
    # ax.set_yticks(np.arange(0,11,2))
    # ax.set_yticklabels(np.arange(0,11,2))
    # ax.tick_params(direction='in')
    ax.tick_params(top=False,
               bottom=True,
               left=True,
               right=False,
               labelleft=True,
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
    
    ax.set_title(watershed_name)
    plt.tight_layout()
    
    # fig.savefig(figsim_folder+watershed_name+'_calib2D_map'+'.png', dpi=300, bbox_inches='tight')
    fig.savefig('D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/15_results/EBR_v1/out/_calib/' + 
                watershed_name + '.png', dpi=300, bbox_inches='tight')

#%% ---- STORAGE
      
#%% FIG : Hysteresis

figsim_folder = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/8_paper/hysteresis/figures/_outputs/'

# Things
typ = 'projec-1'
time_step = 'M'
sim_state = 'transient'
var = 'REC'
scan = 'outflow_drain'

# Colored
mod_list = ['NOR-R15']
sce_list = ['historic','RCP2.6','RCP8.5']
sce_list = ['RCP8.5']
sce_cmap = ["Greys","Greens","Reds"]
sce_color = ['k',"dodgerblue","red"]
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

# Hysteres
temporal = True
space = 10
norm = False

watershed_names = ['Canut','Nancon']

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
    
    fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
    xn = 0.1
    xx = 100
    yn = 0.1
    yx = 100
    ax = axs1
    ax.set_title(mod_list)
    ax.set_xscale('log')
    ax.set_yscale('log')
    # ax.set_aspect('equal', adjustable='box')
    '''
    from mpl_toolkits.axes_grid1.inset_locator import inset_axes
    axz = inset_axes(ax, width="40%", height="40%", loc='upper left',
                     bbox_to_anchor=(0.0,0,1,1), bbox_transform=ax.transAxes)
    axz.set_aspect('equal', adjustable='box')
    '''
    
    for mod in mod_list:
        
        # fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
        # xn = 0.1
        # xx = 100
        # yn = 0.1
        # yx = 100
        # ax = axs1
        # ax.set_title(mod)
        # ax.set_aspect('equal', adjustable='box')
        # from mpl_toolkits.axes_grid1.inset_locator import inset_axes
        # axz = inset_axes(ax, width="40%", # width = 30% of parent_bbox
        #                   height=1., # height : 1 inch
        #                   loc=2)
        # axz.set_aspect('equal', adjustable='box')
            
        for sce in sce_list:
            
            if sce != 'historic':
                simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
                simul = simul_list[0]
            
            if sce == 'historic':
                simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+'RCP8.5'+'*')
                simul = simul_list[0]

            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
                        
            Qmod = (Smod[scan] * 1000 * 30).squeeze()   # mm/months            
            Cmod = Smod['recharge'] * 1000 * 30 # mm/months

            # if sce == 'historic' :
            #     Qmod = select_period(Qmod, 1990, 2019)
            #     Cmod = select_period(Cmod, 1990, 2019)
            # if sce != 'historic':
            #     Qmod = select_period(Qmod, 2070, 2099)
            #     Cmod = select_period(Cmod, 2070, 2099)
            
            DFmod = pd.DataFrame(columns=['x','y'])
            DFmod['x'] = Cmod
            DFmod['y'] = Qmod
            first_valid_loc = DFmod[DFmod.index.month==10].apply(lambda col: col.first_valid_index()).max().year
            last_valid_loc = DFmod[DFmod.index.month==9].apply(lambda col: col.last_valid_index()).min().year
            DFmod = select_period(DFmod, first_valid_loc, last_valid_loc)
            for idx in range(len(DFmod)):
                if DFmod.index[idx].month == 10:
                    DFmod = DFmod[idx:]   
                    break
            DFmod = DFmod.sort_index(ascending=False)
            for idx in range(len(DFmod)):
                if DFmod.index[idx].month == 9:
                    DFmod = DFmod[idx:]
                    break
            DFmod = DFmod.sort_index(ascending=True)
            
            hyst = Hysteresis(DFmod, simul)
            hyst.prepare_xy_raw()
            hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
            columns_x = hyst.xrecapl.columns
            columns_y = hyst.yrecapl.columns
            
            n = len(columns_x)
            cmap = cmap_dict[sce]
            cmap = 'jet'
            cmap_color = plt.get_cmap(cmap)(np.linspace(0, 1, n))
            
            color = color_dict[sce]
            
            dfevol = hyst.dfmet.iloc[:-1]
            dfevol = dfevol.set_index(pd.to_datetime(dfevol.index, format='%Y'))
            dfmean = hyst.dfmet.iloc[-1]
            
            for i, (colx, coly) in enumerate(zip(columns_x, columns_y)):
                data = pd.DataFrame()
                data['inx'] = hyst.xrecapl[colx]
                data['iny'] = hyst.yrecapl[coly]
                ax.plot(data.inx, data.iny, linestyle = '-', lw=2,
                        color=cmap_color[i], alpha=0.75, zorder=0)
                # ax.plot(data.inx, data.iny, marker='.', linestyle = '-', lw=0,
                #         color=cmap_color[i], alpha=0.75, zorder=0)
            ax.plot(data.inx, data.iny, linestyle = '-', lw=2, color=color, zorder=1)

            # ax.scatter(hyst.x, hyst.y, c=hyst.wy, cmap=cmap_dict[sce], marker=".", 
            #            s=10, vmin=1, vmax=12, alpha=0.75, ec='none', zorder=0)
            # ax.plot(hyst.xi, hyst.yi, marker="o", markersize=9, markeredgecolor='black', 
            #         markerfacecolor='white', linestyle = 'None') 
            # for k in hyst.wyi:
            #     ax.annotate(k,(hyst.xi[k],hyst.yi[k]), family='sans-serif', fontsize=5, 
            #                 color='black', weight="bold", ha='center', va='center')
            
            for k in hyst.wyi:
                # if (k == 10) | (k == 11) | (k == 12) | (k == 1) | (k == 2) | (k == 3) | (k == 4) :
                if (k == 12) :
                    ax.plot(hyst.xi[k], hyst.yi[k], marker="o", markersize=0, lw=0,
                              markeredgecolor='k', markerfacecolor=color,
                              mew=0, linestyle = '-')
                    # ax.plot(hyst.xi[k], hyst.yi[k], marker="o", markersize=7,
                    #           markeredgecolor=color, markerfacecolor='white',
                    #           mew=1,
                    #           linestyle = 'None', zorder=csce+cp+cont)
                    # ax.annotate(k,(hyst.xi[k],hyst.yi[k]),
                    #               family='sans-serif', fontsize=5, 
                    #               color=color, weight="bold", ha='center', va='center',
                    #               zorder=csce+cp+cont)
                    
            # ax.xaxis.set_ticks(np.arange(xn, xx+1, 25))
            # ax.yaxis.set_ticks(np.arange(yn, xx+1, 25))
            # ax.errorbar(hyst.xi, hyst.yi,
            #             yerr=np.vstack([hyst.yi-hyst.ye.q25, hyst.ye.q75-hyst.yi]),
            #             xerr=np.vstack([hyst.xi-hyst.xe.q25, hyst.xe.q75-hyst.xi]),
            #             ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
            #             capthick=0.5, zorder=1)
            
            polyg_loop = Polygon(tuple(hyst.data.itertuples(index=False, name=None)))
            xpolyg, ypolyg = polyg_loop.exterior.xy
            maxi = 1.5
            mini = -0.1
            line_oneone = SG.LineString([(mini,mini), (maxi,maxi)])
            areas = cut_polygon_by_line(polyg_loop, line_oneone)
            from descartes import PolygonPatch
            for i in range(len(areas)):
                ring_patch = PolygonPatch(areas[i], color=color, alpha=0.6, lw=0, ec="k", zorder=1000)
                # ax.add_patch(ring_patch)
            
            # plt.setp(axs2, xlim=(min(xmin),max(xmax)), ylim=(min(ymin),max(ymax)))
            
            # ax.plot(np.linspace(xn,xx,50), np.linspace(yn,yx,50), 
            #         linestyle='--', color='grey', linewidth=1.5, zorder=-1)

            ax.grid(color='grey',alpha=0.2)
            ax.set_ylabel('Q [mm/month]')
            ax.set_xlabel('R [mm/month]')
            
            '''
            # AX ZOOM
            axz.plot(data.inx, data.iny, linestyle = '-', lw=1, color=color, zorder=1)
            xmin, xmax = axz.get_xlim()
            ymin, ymax = axz.get_ylim()
            axz.plot(np.linspace(xn,xx,50), np.linspace(yn,yx,50), 
                    linestyle='--', color='grey', linewidth=1, zorder=-1)
            axz.set_xlim(xn,xx)
            axz.set_ylim(yn,yx)
            axz.get_xaxis().set_visible(False)
            axz.get_yaxis().set_visible(False)
            axz.set_xscale('log')
            axz.set_yscale('log')
            # axz.axis('off')
            for axis in ['top','bottom','left','right']:
                axz.spines[axis].set_linewidth(1)
            '''

    plt.tight_layout()
                        
    # fig1.savefig(figsim_folder+'hysteresis_loop'+'.svg', dpi=300, bbox_inches='tight')

#%% FIG : Matrix

figsim_folder = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/8_paper/hysteresis/figures/_outputs/'

# Things
typ = 'proj1'
time_step = 'M'
sim_state = 'transient'
var = 'REC'
scan = 'outflow_drain'

# Colored
mod_list = ['NOR1','IPS1']
mod_list = ['NOR1']
sce_list = ['RCP2.6','RCP8.5']
sce_cmap = ["Greys","Greens","Reds"]
sce_color = ['k',"dodgerblue","red"]
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

# Hysteres
scan_list = ['intermit_areas','perenn_areas']

temporal = True
space = 0
norm = False

watershed_names = ['Canut','Nancon']
watershed_names = ['Canut']

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    
    for mod in mod_list:
                
        fig, axs = plt.subplots(1,2, figsize=(8,3))
        axs = axs.ravel()
    
        for sce in sce_list:
            
            print(watershed_name + ' + ' + mod + ' + ' + sce)
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*')
        
            compt = 0
            
            list_max = []
            list_max_per = []
            list_max_int = []
                    
            for it, simul in enumerate(simul_list[:]):
                    
                model_name = simul.split('\\')[-1]
                Sy = float(model_name.split('_')[3].split('-')[0]) # %
                K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
                E = float(model_name.split('_')[3].split('-')[2]) # m
                D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
                params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
                Smod_path = simul+'/_watershed/_simulated_results.csv'            
                if not os.path.exists(Smod_path):
                    compt += 1
                    continue
                
                Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
                idx = pd.date_range(start='01/01/2000', end='31/12/2099', freq='M')
                # Smod = Smod.set_index(idx)
                years = Smod.index.year.unique()
                
                Smod['prop_perenn'] = Smod['perenn_areas'] / Smod['surflow_areas']
                Smod['prop_intermit'] = Smod['intermit_areas'] / Smod['surflow_areas']
                
                Smod['year'] = Smod.index.year.values # group by month and year, get the average
                Smod['month'] = Smod.index.month.values # group by month and year, get the average
                Smod = Smod.pivot('month','year')
                
                max_per = Smod['perenn_areas'].max().max()
                max_int = Smod['intermit_areas'].max().max()
                max_tot = max(max_per,max_int)
            
                list_max.append(max_tot)
                list_max_per.append(max_per)
                list_max_int.append(max_int)
                
            for it, simul in enumerate(simul_list[:]):
                
                ax = axs[it]
                
                model_name = simul.split('\\')[-1]
                Sy = float(model_name.split('_')[3].split('-')[0]) # %
                K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
                E = float(model_name.split('_')[3].split('-')[2]) # m
                D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
                params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
                Smod_path = simul+'/_watershed/_simulated_results.csv'            
                if not os.path.exists(Smod_path):
                    compt += 1
                    continue
                
                Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
                idx = pd.date_range(start='01/01/2000', end='31/12/2099', freq='M')
                # Smod = Smod.set_index(idx)
                years = Smod.index.year.unique()
                
                Smod['prop_perenn'] = Smod['perenn_areas'] / Smod['surflow_areas']
                Smod['prop_intermit'] = Smod['intermit_areas'] / Smod['surflow_areas']
                
                Smod['year'] = Smod.index.year.values # group by month and year, get the average
                Smod['month'] = Smod.index.month.values # group by month and year, get the average
                Smod = Smod.pivot('month','year')
                
                max_per = Smod['perenn_areas'].max().max()
                max_int = Smod['intermit_areas'].max().max()
                max_tot_per = max(list_max_per)
                max_tot_per = 5
                max_tot_int = max(list_max_int) 
                max_tot_int = 20
                max_tot = max(list_max)
                max_tot = 20
                
                # fig, ax = plt.subplots(1,1, figsize=(8,5))
                from matplotlib import colors
                import matplotlib.cm as cmx
                
                for year in years[:]:
                    p = Smod[['prop_perenn','perenn_areas']]
                    i = Smod[['prop_intermit','intermit_areas']]
                                        
                    p = p.droplevel(level=0, axis=1)
                    p = p[year]
                    p.columns = ['prop_perenn','perenn_areas']
                    p = p.sort_values('prop_perenn', ascending=False)
                    p['prop_perenn'] = p.prop_perenn.cumsum() / 12
                        
                    p1 = p.prop_perenn.shift(+1)
                    p1.iloc[0] = 0
                    x1 = p1.values
                    x2 = p.prop_perenn.values
                    values = p.perenn_areas.values
                    # jet = cm = plt.get_cmap('winter_r')
                    cmaplist = ['c','deepskyblue','dodgerblue','blue','navy']
                    cmaplist = ['lightgreen','seagreen']
                    import colorcet as cc
                    # cmaplist[-1] = (.5, .5, .5, 1.0) # first value
                    cmap = mpl.colors.LinearSegmentedColormap.from_list(
                        'Custom cmap', cmaplist)
                    cmap = cc.cm.kbc_r
                    # cmap = 'cool_r'
                    jet = cm = plt.get_cmap(cmap)
                    cNorm  = colors.Normalize(vmin=0, vmax=max_tot_per)
                    scalarMap = cmx.ScalarMappable(norm=cNorm, cmap=jet)
                    if year == 2020:
                        if it==1:
                            position=fig.add_axes([1.1,0.3,0.02,0.35])  ## the parameters are the specified position you set 
                            cb = fig.colorbar(scalarMap,cax=position) ##
                            cb.set_label('Saturation [%]', rotation=270, labelpad=30)
                        
                    for idx, x, y in zip(values, x1, x2):          
                        colorVal = scalarMap.to_rgba(idx)  
                        start = x
                        endp = y
                        width = endp-start
                        ax.bar(x = year, height=width, bottom=start, width=1,
                                label = str(idx), color=colorVal, lw=0)
                    
                    i = i.droplevel(level=0, axis=1)
                    i = i[year]
                    i.columns = ['prop_intermit','intermit_areas']
                    i = i.sort_values('prop_intermit', ascending=True)
                    i['prop_intermit'] = i.prop_intermit.cumsum() / 12
                    
                    i1 = i.prop_intermit.shift(+1)
                    i1.iloc[0] = 0
                    i1 = i1 + endp
                    x1 = i1.values
                    x2 = i.prop_intermit.values + endp
                    values = i.intermit_areas.values
                    # jet = cm = plt.get_cmap('autumn_r')
                    cmaplist = ['darkred','red','orangered','orange']
                    cmaplist = ['saddlebrown','moccasin']
                    import colorcet as cc
                    # cmaplist[-1] = (.5, .5, .5, 1.0) # first value
                    cmap = mpl.colors.LinearSegmentedColormap.from_list(
                        'Custom cmap', cmaplist)
                    cmap = cc.cm.fire_r
                    # cmap = 'Wistia'
                    jet = cm = plt.get_cmap(cmap) 
                    cNorm  = colors.Normalize(vmin=0, vmax=max_tot_int)
                    scalarMap = cmx.ScalarMappable(norm=cNorm, cmap=jet)
                    if year == 2020:
                        if it==1:
                            position=fig.add_axes([1,0.3,0.02,0.35])  ## the parameters are the specified position you set 
                            cb = fig.colorbar(scalarMap,cax=position) ## 
            
                    for idx, x, y in zip(values, x1, x2):          
                        colorVal = scalarMap.to_rgba(idx)
                        start = x
                        endi = y
                        width = endi-start
                        ax.bar(x = year, height = width, bottom=start, width = 1,
                                label = str(idx), color=colorVal, lw=0)
                    
                    ax.set_ylim(0,1)
                    bal = ((i.prop_intermit.sum()) + (p.prop_perenn.sum())).sum()
                    min_max = [2020, 2099]
                    ax.set_xlim(min_max)
                    ax.set_xticks(np.arange(min_max[0], min_max[1]+2, 20.0))
                    tox = np.arange(min_max[0], min_max[1]+2, 20.0).astype(int)
                    ax.set_xticklabels(tox)
                    
                    if ((it) == 0) | ((it) == 3) | ((it) == 6):
                        ax.set_ylabel('Proportion of network')
                                 # ax.set_ylabel('$Eccent_{ratio}$ [-]')
                    if ((it) == 6) | ((it) == 7) | ((it) == 8):
                        ax.set_xlabel('Date')
                        
                    x_ticks = ax.xaxis.get_major_ticks()
                    x_ticks[0].label1.set_visible(False) ## set first x tick label invisible
                    x_ticks[-1].label1.set_visible(False)
                    
            # plt.tight_layout()
            
            # fig1.savefig(figsim_folder+'matrix_evol_'+sce+'.png',
            #               dpi=300, bbox_inches='tight', transparent=True)

#%% FIG : Boxplot

sim_state='transient'
time_step = 'M'
mod = 'NOR1'
typ = 'projnor'
var = 'REC'
scan = 'outflow_drain'
sce_list = ['historic','RCP2.6','RCP8.5']
# sce_list = ['historic']
sce_cmap = ["Blues","Reds"]
sce_color = ['grey',"dodgerblue","red"]

cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

scan_list = ['surflow_areas','perenn_areas','intermit_areas']
bxlim = (0.5,3.5)
sce_pos = ["1","2","3"]
pos_dict = dict(zip(sce_list, sce_pos))

temporal = True
space = -10
norm = False

fig1, axs = plt.subplots(3,3, figsize=(9,9))
axs = axs.ravel()
xmin = []
xmax = []
ymin = []
ymax = []
            
compt = 1

f = 2020
l = 2099

simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    
ord_min = []
ord_max = []

metric = 'qmean'

for ix in np.arange(1,9+1,1):
    # simul_list = glob.glob(simulations_folder+'*'+typ+'_'+str(i)+'*')
    
    ax = axs[ix-1]
    # ax.set_aspect('equal', adjustable='box')
    
    csce = 20
    for sce in sce_list:
        if sce == 'historic':
            simul = glob.glob(simulations_folder+'*'+typ+'_'+str(ix)+'*'+'RCP8.5'+'*')[0]
        
        # simul_list = glob.glob(simulations_folder+'*'+typ+'_'+str(i)+'*'+sce+'*')
        else:
            simul = glob.glob(simulations_folder+typ+'_'+str(ix)+'*'+sce+'*')[0]
        print(simul)
        
        print(sce)

        model_name = simul.split('\\')[-1]
        Sy = float(model_name.split('_')[3].split('-')[0]) # %
        K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
        E = float(model_name.split('_')[3].split('-')[2]) # m
        D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
        params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
        Smod_path = simul+'/_watershed/_simulated_results.csv'            
        if not os.path.exists(Smod_path):
            compt += 1
            continue
        Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
        
        BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = 'historic',
                                                 first_year = 1960, last_year = 2010,
                                                 time_step = time_step, sim_state=sim_state)
        Hist = BV.forcing.recharge
        BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = sce,
                                          first_year = 1960, last_year = 2099, 
                                          time_step = time_step, sim_state=sim_state)
        BV.forcing.update_recharge(BV.forcing.recharge, sim_state=sim_state)
        Rech = BV.forcing.recharge # m/month
        if (sce == 'RCP2.6') | (sce == 'RCP8.5'):
            Rech = pd.concat((Rech, Hist), axis=1).mean(axis=1)
            BV.forcing.update_recharge(Rech, sim_state=sim_state)
            Rech = BV.forcing.recharge # m/month
            
        # idx = pd.date_range(start='01/01/2000', end='31/12/2099', freq='M')
        # Smod = Smod.set_index(idx)
        if sce == 'historic':
            Smod = select_period(Smod, 1960, 2010)
        else:
            Smod = select_period(Smod, f, l)
        
        Smod.recharge = Rech
        
        Qmod = Smod[scan]
        if scan == 'outflow_drain':
            Qmod = Qmod * 1000 # mm/months
            Qmod = Qmod.squeeze()    
        Cmod = Smod['recharge'] * 1000 # mm/months
        DFmod = pd.DataFrame(columns=['x','y'])
        DFmod['x'] = Cmod
        DFmod['y'] = Qmod
        first_valid_loc = DFmod[DFmod.index.month==10].apply(lambda col: col.first_valid_index()).max().year
        last_valid_loc = DFmod[DFmod.index.month==9].apply(lambda col: col.last_valid_index()).min().year
        DFmod = select_period(DFmod, first_valid_loc, last_valid_loc)
        for idx in range(len(DFmod)):
            if DFmod.index[idx].month == 10:
                DFmod = DFmod[idx:]   
                break
        DFmod = DFmod.sort_index(ascending=False)
        for idx in range(len(DFmod)):
            if DFmod.index[idx].month == 9:
                DFmod = DFmod[idx:]
                break
        DFmod = DFmod.sort_index(ascending=True)
        
        # hyst = Hysteresis(DFmod, simul)
        # hyst.prepare_xy_raw()
        # hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
        # columns_x = hyst.xrecapl.columns
        # columns_y = hyst.yrecapl.columns
        
        color = color_dict[sce]
        print(color)
        
        # dfevol = hyst.dfmet.iloc[:-1]
        # dfevol = dfevol.set_index(pd.to_datetime(dfevol.index, format='%Y'))
        # dfmean = hyst.dfmet.iloc[-1]

        ################ FIG 2 ################
        # ax.set_title(params, fontsize=8)
        # fig3.suptitle(metric.upper(), y=0.98)
        boxprops = dict(linestyle='-', linewidth=1, color='black',
                        facecolor=color)
        medianprops = dict(linestyle='-', linewidth=1, color='black')
        meanpointprops = dict(markersize=3, marker='o', markeredgecolor='black',
                              markerfacecolor='black', linestyle='-')
        
        if sce !='historic':
            bp = ax.boxplot(Qmod[(Qmod.index.year>=2020)&(Qmod.index.year<2060)],
                            positions=[int(pos_dict[sce])-0.1],
                              whis=True, showfliers=False, showmeans=True,
                              medianprops=medianprops, meanprops=meanpointprops,
                              patch_artist=True, boxprops=boxprops)
            for element in bp['whiskers']:
                element.set_color('k')
                element.set_linestyle('-')
            bp = ax.boxplot(Qmod[(Qmod.index.year>=2060)&(Qmod.index.year<2100)],
                            positions=[int(pos_dict[sce])+0.1],
                              whis=True, showfliers=False, showmeans=True,
                              medianprops=medianprops, meanprops=meanpointprops,
                              patch_artist=True, boxprops=boxprops)
            for element in bp['whiskers']:
                element.set_color('k')
                element.set_linestyle('-')
        else:
            bp = ax.boxplot(Qmod, positions=[int(pos_dict[sce])],
                              whis=True, showfliers=False, showmeans=True,
                              medianprops=medianprops, meanprops=meanpointprops,
                              patch_artist=True, boxprops=boxprops)
        for element in bp['whiskers']:
            element.set_color('k')
            element.set_linestyle('-')

        # ax.scatter(int(pos_dict[sce]), Qmod.min(), marker='.',color='dimgrey',s = 3)
        # ax.scatter(int(pos_dict[sce]), Qmod.max(), marker='.',color='dimgrey',s = 3)
        # ax.scatter(int(pos_dict[sce]),
        #             Qmod.mean()-Qmod.std(),
        #             marker='_',color='dimgrey',s = 7, zorder=2)
        # ax.scatter(int(pos_dict[sce]),
        #             Qmod.mean()+Qmod.std(),
        #             marker='_',color='dimgrey',s = 7, zorder=2)
        
        ax.set_xticks(np.arange(1,len(sce_list)+1,1))
        # ax.set_xticklabels([x.upper() for x in sce_list], fontsize=10)
        # bmin.append(Qmod.min())
        # bmax.append(Qmod.max())
        # plt.setp(axs3, ylim=(min(bmin),max(bmax)))
        ax.set_ylim(-0.1,2.5)
        # ax.set_xlim(bxlim)
        plt.tight_layout()

        # if ((ix-1) == 6) | ((ix-1) == 7) | ((ix-1) == 8):
        #     ax.set_xlabel('Date')
        
        # ord_min.append(q25.min())
        # ord_max.append(q75.max())
        # plt.setp(axs, ylim=(min(ord_min),max(ord_max)))
        # plt.setp(axs, ylim=(0.05,3))
        

plt.tight_layout()

fig1.savefig(figsim_folder+'boxplot_discharge'+'.svg', dpi=300, bbox_inches='tight')

#%% FIG : Violin

from scipy.stats import binned_statistic

typ = 'projec-1'

# Things
time_step = 'M'
sim_state = 'transient'
var = 'REC'

# Colored
mod_list = ['NOR-R15', 'MPI-R09']
# mod_list = ['MPI-R09']
mod_list = ['NOR-R15']
sce_list = ['RCP2.6', 'RCP8.5']
sce_cmap = ['Blues', 'Reds']
sce_color = ['dodgerblue', 'red']
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

# Hysteres
temporal = False
space = 0
norm = False

watershed_names = ['Canut','Nancon']

# y_name = 'surflow_areas'
y_name = 'intermit_areas'
y_name = 'prop_ratio'
# y_name = 'perenn_areas'
# y_name = 'outflow_drain'
# y_name = 'recharge'
# y_name = 'seepage_areas'
xmin = []
xmax = []
ymin = []
ymax = []

inds_tot = []

fig, axs = plt.subplots(1,2, figsize=(6,4))
axs = axs.ravel()

compt = 0

for watershed_name in watershed_names[:] :
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'  # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
    
    mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')

    ax = axs[compt]
    
    # fig, ax = plt.subplots(1,1, figsize=(3,4))
    
    ser_p1_26 = pd.Series()
    ser_p1_85 = pd.Series()
    ser_p2_26 = pd.Series()
    ser_p2_85 = pd.Series()
    
    data1 = (pd.Series(), pd.Series())
    data2 = (pd.Series(), pd.Series())
    
    for mod in mod_list:
        
        # fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
        # xn = 0.1
        # xx = 100
        # yn = 0.1
        # yx = 100
        # ax = axs1
        # ax.set_title(mod)
        # ax.set_aspect('equal', adjustable='box')

        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
            
            # if sce == 'historic':
            #     simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+'RCP8.5'+'*')
            #     simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas
            Smod['sce'] = sce
            
            # ax.violinplot(Smod['surflow_areas'],
            #                   showmeans=False,
            #                   showmedians=True)
            
            # from matplotlib import pyplot as plt
            # import seaborn as sns
            # import numpy as np
            
            # sns.set_style('white')
            # # iris = sns.load_dataset('iris')
            # # palette = 'Set2'
            # iris = Smod
            # ax = sns.violinplot(x="sce", y="surflow_areas", data=iris, hue="sce", dodge=False,
            #                     facecolor=color_dict[sce], alpha=0.5,
            #                     scale="width", inner=None)

            # xlim = ax.get_xlim()
            # ylim = ax.get_ylim()
            # for violin in ax.collections:
            #     bbox = violin.get_paths()[0].get_extents()
            #     x0, y0, width, height = bbox.bounds
            #     violin.set_clip_path(plt.Rectangle((x0, y0), width / 2, height, transform=ax.transData))
            
            # sns.boxplot(x="sce", y="surflow_areas", data=iris, saturation=1, showfliers=False,
            #             width=0.1, boxprops={'zorder': 3, 'facecolor': 'none'}, ax=ax)
            # old_len_collections = len(ax.collections)
            # sns.stripplot(x="sce", y="surflow_areas", data=iris, hue="sce", dodge=False, ax=ax)
            # for dots in ax.collections[old_len_collections:]:
            #     dots.set_offsets(dots.get_offsets() + np.array([-0.12, 0]))
            # ax.set_xlim(xlim)
            # ax.set_ylim(0,20)
            # ax.legend_.remove()
            # plt.show()
            
            '''
            if sce == 'RCP2.6':
                rcp26_one = Smod[y_name].copy()
                ser_p1_26 = ser_p1_26.append(select_period(rcp26_one.copy(), 2020, 2048), ignore_index=True)
                ser_p2_26 = ser_p2_26.append(select_period(rcp26_one.copy(), 2070, 2098), ignore_index=True)
            if sce == 'RCP8.5':
                rcp85_one = Smod[y_name].copy()
                ser_p1_85 = ser_p1_85.append(select_period(rcp85_one.copy(), 2020, 2048), ignore_index=True)
                ser_p2_85 = ser_p2_85.append(select_period(rcp85_one.copy(), 2070, 2098), ignore_index=True)
            '''
                
            acc_npy = np.load(os.path.join(simul, '_watershed','accumulation_flux.npy'), allow_pickle=True).item()
                
            # Historic
            acc_npy_h = list(acc_npy.items())[30*12:48*12]
            for key in range(len(acc_npy_h)):
                acc_npy_h[key] = np.ma.masked_array(acc_npy_h[key][1], mask=(mask<0))
            zero = acc_npy_h[0] * 0
            for i in range(len(acc_npy_h)):
                tempo = acc_npy_h[i].copy()
                tempo[tempo>0] = 1
                zero = zero + tempo
            days_flux_h = zero.copy() / len(acc_npy_h)
                
            dates = ['p1', 'p2']
            for date in dates:
                if date == 'p1':
                    acc_npy_f = list(acc_npy.items())[-80*12:-50*12]
                if date == 'p2':
                    acc_npy_f = list(acc_npy.items())[-30*12:]
                for key in range(len(acc_npy_f)):
                    acc_npy_f[key] = np.ma.masked_array(acc_npy_f[key][1], mask=(mask<0))
                zero = acc_npy_f[0] * 0
                for i in range(len(acc_npy_f)):
                    tempo = acc_npy_f[i].copy()
                    tempo[tempo>0] = 1
                    zero = zero + tempo
                days_flux_f = zero.copy() / len(acc_npy_f)
                
                days_flux_ano = ( (days_flux_f - days_flux_h) ) * 100
                
                # days_flux_ano = ( (days_flux_f - days_flux_h) / days_flux_h.mean())
                
                # data = np.ma.masked_where((days_flux_ano==0)|(days_flux_h==0), days_flux_ano)
                data = np.ma.masked_where((days_flux_ano==0)|(days_flux_h==0), days_flux_ano)
                data = data.flatten().filled(np.nan)
                # data = data.flatten()
                # data = days_flux_ano[~days_flux_ano.mask]
                # data = data.compressed()
                data = data[~np.isnan(data)]
                if date == 'p1':
                    data_p1 = pd.Series(data.copy())
                if date == 'p2':
                    data_p2 = pd.Series(data.copy())
            
            if sce == 'RCP2.6':
                rcp26_one = Smod[y_name].copy()
                ser_p1_26 = ser_p1_26.append(data_p1, ignore_index=True)
                ser_p2_26 = ser_p2_26.append(data_p2, ignore_index=True)
            if sce == 'RCP8.5':
                rcp85_one = Smod[y_name].copy()
                ser_p1_85 = ser_p1_85.append(data_p1, ignore_index=True)
                ser_p2_85 = ser_p2_85.append(data_p2, ignore_index=True)
         
    data1 = (np.array(ser_p1_26), np.array(ser_p2_26))
    data2 = (np.array(ser_p1_85), np.array(ser_p2_85))
        
    # data1 = (select_period(rcp26, 2020, 2050),
    #          select_period(rcp85, 2020, 2050))
    # data2 = (select_period(rcp26, 2070, 2099),
    #          select_period(rcp85, 2070, 2099))
    
    labels = []
    import matplotlib.patches as mpatches
    def add_label(violin, label):
        color = violin["bodies"][0].get_facecolor().flatten()
        labels.append((mpatches.Patch(color=color), label))
    
    v1 = ax.violinplot(data1, points=1000, positions=np.arange(0, len(data1)),
                   showmeans=False, showextrema=False, showmedians=False)

    for b in v1['bodies']:
        # get the center
        m = np.mean(b.get_paths()[0].vertices[:, 0])
        # modify the paths to not go further right than the center
        b.get_paths()[0].vertices[:, 0] = np.clip(b.get_paths()[0].vertices[:, 0], -np.inf, m)
        b.set_color('r')

    v2 = ax.violinplot(data2, points=1000, positions=np.arange(0, len(data2)), 
                   showmeans=False, showextrema=False, showmedians=False)

    for b in v2['bodies']:
        # get the center
        m = np.mean(b.get_paths()[0].vertices[:, 0])
        # modify the paths to not go further left than the center
        b.get_paths()[0].vertices[:, 0] = np.clip(b.get_paths()[0].vertices[:, 0], m, np.inf)
        b.set_color('b')
    
    for pc in v1['bodies']:
        pc.set_facecolor('dodgerblue')
        pc.set_edgecolor('black')
        pc.set_alpha(0.5)
    for pc in v2['bodies']:
        pc.set_facecolor('red')
        pc.set_edgecolor('black')
        pc.set_alpha(0.5)
    
    
    old_len_collections = len(ax.collections)
    sns.stripplot(data=data1,dodge=False, ax=ax, color='dodgerblue', size=1)
    for dots in ax.collections[old_len_collections:]:
        dots.set_offsets(dots.get_offsets() + np.array([-0.1, 0]))
        dots.set_alpha(0.25)
    old_len_collections = len(ax.collections)
    sns.stripplot(data=data2, dodge=False, ax=ax, color='red', size=1)
    for dots in ax.collections[old_len_collections:]:
        dots.set_offsets(dots.get_offsets() + np.array([+0.1, 0]))
        dots.set_alpha(0.25)
    
    # sns.swarmplot(data=data2, dodge=False, ax=ax, color='red', size=1)
    
    def adjacent_values(vals, q1, q3):
        upper_adjacent_value = q3 + (q3 - q1) * 1.5
        upper_adjacent_value = np.clip(upper_adjacent_value, q3, vals[-1])
    
        lower_adjacent_value = q1 - (q3 - q1) * 1.5
        lower_adjacent_value = np.clip(lower_adjacent_value, vals[0], q1)
        return lower_adjacent_value, upper_adjacent_value
    
    for i in range(2):
        quartile1, medians, quartile3 = np.percentile(data1[i], [25, 50, 75]) # axis = 1
        # whiskers = np.array([
        #     adjacent_values(sorted_array, q1, q3)
        #     for sorted_array, q1, q3 in zip(data1, quartile1, quartile3)])
        # whiskersMin, whiskersMax = whiskers[:, 0], whiskers[:, 1]
        inds = i + - 0.05 # np.arange(1, len(medians) + 1) - 1 - 0.05
        ax.scatter(inds, medians, marker='o', color='k', s=10, zorder=1000)
        # print(medians)
        ax.vlines(inds, quartile1, quartile3, color='k', linestyle='-', lw=1, zorder=1000)
        # ax.vlines(inds, whiskersMin, whiskersMax, color='k', linestyle='-', lw=1)
        inds_tot.append(inds)
        
    for i in range(2):
        quartile1, medians, quartile3 = np.percentile(data2[i], [25, 50, 75]) # axis = 1
        # whiskers = np.array([
        #     adjacent_values(sorted_array, q1, q3)
        #     for sorted_array, q1, q3 in zip(data2, quartile1, quartile3)])
        # whiskersMin, whiskersMax = whiskers[:, 0], whiskers[:, 1]
        inds = i + 0.05 # np.arange(1, len(medians) + 1) - 1 + 0.05
        ax.scatter(inds, medians, marker='o', color='k', s=10, zorder=1000)
        # print(medians)
        ax.vlines(inds, quartile1, quartile3, color='k', linestyle='-', lw=1,zorder=1000)
        # ax.vlines(inds, whiskersMin, whiskersMax, color='k', linestyle='-', lw=1)
        inds_tot.append(inds)
    
    # ax.get_xaxis().set_visible(False)
    ax.set_title(watershed_name)
    ax.set_ylim(-20,20)
    # ax.set_ylabel(y_name.upper())
    # ax.set_yscale('log')
    # ax.set_xticks(inds-0.05)
    ax.set_xticks([0.0,1.0])
    ax.set_xticklabels(['2020-2050', '2070-2100'])
    
    if watershed_name == 'Canut':
        ax.legend([v1['bodies'][0], v2['bodies'][0]], ['RCP2.6', 'RCP8.5'], loc=2)
        leg = ax.get_legend()
        leg.legendHandles[0].set_color('dodgerblue')
        leg.legendHandles[1].set_color('red')
    
    ax.axhline(y=0, color='k')
    
    compt += 1
    
plt.tight_layout()
    
#%% FIG : Intermensual

figsim_folder = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/8_paper/hysteresis/figures/_outputs/'

sim_state='transient'
time_step = 'M'
mod = 'NOR1'
typ = 'projnor'
var = 'REC'
scan = 'outflow_drain'
sce_list = ['historic','RCP2.6','RCP8.5']
# sce_list = ['historic']
sce_cmap = ["Blues","Reds"]
sce_color = ['k',"dodgerblue","red"]

cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

temporal = True
space = -10
norm = False

fig1, axs = plt.subplots(3,3, figsize=(10,9))
axs = axs.ravel()
xmin = []
xmax = []
ymin = []
ymax = []
            
compt = 1

f = 2020
l = 2099

simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    
ord_min = []
ord_max = []

for ix in np.arange(1,9+1,1):
    # simul_list = glob.glob(simulations_folder+'*'+typ+'_'+str(i)+'*')
    
    ax = axs[ix-1]
    # ax.set_aspect('equal', adjustable='box')
    
    csce = 20
    for sce in sce_list:
        if sce == 'historic':
            simul = glob.glob(simulations_folder+'*'+typ+'_'+str(ix)+'*'+'RCP8.5'+'*')[0]
        
        # simul_list = glob.glob(simulations_folder+'*'+typ+'_'+str(i)+'*'+sce+'*')
        else:
            simul = glob.glob(simulations_folder+typ+'_'+str(ix)+'*'+sce+'*')[0]
        print(simul)
        
        print(sce)

        model_name = simul.split('\\')[-1]
        Sy = float(model_name.split('_')[3].split('-')[0]) # %
        K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
        E = float(model_name.split('_')[3].split('-')[2]) # m
        D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
        params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
        Smod_path = simul+'/_watershed/_simulated_results.csv'            
        if not os.path.exists(Smod_path):
            compt += 1
            continue
        Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
        
        BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = 'historic',
                                                 first_year = 1960, last_year = 2010,
                                                 time_step = time_step, sim_state=sim_state)
        Hist = BV.forcing.recharge
        BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = sce,
                                          first_year = 1960, last_year = 2099, 
                                          time_step = time_step, sim_state=sim_state)
        BV.forcing.update_recharge(BV.forcing.recharge, sim_state=sim_state)
        Rech = BV.forcing.recharge # m/month
        if (sce == 'RCP2.6') | (sce == 'RCP8.5'):
            Rech = pd.concat((Rech, Hist), axis=1).mean(axis=1)
            BV.forcing.update_recharge(Rech, sim_state=sim_state)
            Rech = BV.forcing.recharge # m/month
            
        # idx = pd.date_range(start='01/01/2000', end='31/12/2099', freq='M')
        # Smod = Smod.set_index(idx)
        if sce == 'historic':
            Smod = select_period(Smod, 1960, 2005)
        else:
            Smod = select_period(Smod, f, l)
        
        Smod.recharge = Rech
        
        Qmod = Smod[scan] 
        Qmod = Qmod * 1000 # mm/months
        Qmod = Qmod.squeeze()    
        Cmod = Smod['recharge'] * 1000 # mm/months
        DFmod = pd.DataFrame(columns=['x','y'])
        DFmod['x'] = Cmod
        DFmod['y'] = Qmod
        first_valid_loc = DFmod[DFmod.index.month==10].apply(lambda col: col.first_valid_index()).max().year
        last_valid_loc = DFmod[DFmod.index.month==9].apply(lambda col: col.last_valid_index()).min().year
        DFmod = select_period(DFmod, first_valid_loc, last_valid_loc)
        for idx in range(len(DFmod)):
            if DFmod.index[idx].month == 10:
                DFmod = DFmod[idx:]   
                break
        DFmod = DFmod.sort_index(ascending=False)
        for idx in range(len(DFmod)):
            if DFmod.index[idx].month == 9:
                DFmod = DFmod[idx:]
                break
        DFmod = DFmod.sort_index(ascending=True)
        
        hyst = Hysteresis(DFmod, simul)
        hyst.prepare_xy_raw()
        hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
        columns_x = hyst.xrecapl.columns
        columns_y = hyst.yrecapl.columns
        
        color = color_dict[sce]
        print(color)
        
        dfevol = hyst.dfmet.iloc[:-1]
        dfevol = dfevol.set_index(pd.to_datetime(dfevol.index, format='%Y'))
        dfmean = hyst.dfmet.iloc[-1]

        ################ FIG 2 ################
                       
        # ax = axs2
        # ax.set_title(params, fontsize=8)
        # fig2.suptitle(metric.upper(), y=0.98)
        # ax.plot(dfevol[metric], dfevol.index, linestyle = '-', lw=2, color=color,
        #         zorder=1)
        
        mean = hyst.y.groupby([lambda x: x.month]).mean()
        mean = mean.append(mean.iloc[[0]])
        mean.index = np.arange(1,14,1)
        q25 = hyst.y.groupby([lambda x: x.month]).quantile(0.25)
        q25 = q25.append(q25.iloc[[0]])
        q25.index = np.arange(1,14,1)
        q75 = hyst.y.groupby([lambda x: x.month]).quantile(0.75)
        q75 = q75.append(q75.iloc[[0]])
        q75.index = np.arange(1,14,1)
        
        # if scan == 'perenn_areas':
        #     alpha=0.5
        ax.plot(mean, color=color, lw=2)
        ax.fill_between(mean.index, q25, q75, alpha=0.2, color=color,
                          linewidth=0)
        xticks = np.arange(1,13+1,1)
        mois = ['J','F','M','A','M','J','J','A','S','O','N','D','J']
        ax.set_xticks(xticks)
        ax.set_xticklabels(mois, minor=False, rotation='horizontal', fontsize=13)
        ax.set_xlim(1,13)
        
        ax.set_yscale('log')
        # ax.fill_between(dfevol.index, dfevol.q10, dfevol.q90, linestyle = '-',
        #                  lw=0, color=color, alpha=0.25)
        # ax.plot(dfevol.qmean, linestyle = '-', lw=2, color=color,
        #         zorder=1)

        # ax.plot(dfevol[dfevol.index.year<=2021][metric], linestyle = '-', lw=3, color='k',
        #         zorder=40)
        
        # metric = 'excent'
        # ax.plot(dfevol[metric], dfevol.index, linestyle = '-', lw=2, color=color,
        #         zorder=1)
        # metric1 = 'slope'
        # metric2 = 'slope_abs'
        # ax.plot(dfevol[metric1]/dfevol[metric2], dfevol.index, linestyle = '-', lw=2, color='pink',
        #         zorder=1)
        
        # ax.set_xscale('log') 
        # ax.axhline(1, linestyle = '--', lw=2, color='grey', zorder=0)
        # ax.set_xlim(-10,100)
        # ax.set_ylim(1,8)
        
        
        # years_maj = YearLocator(40)   # every x year
        # # years_min = YearLocator(1)
        # years_maj_fmt = DateFormatter('%Y')
        # # months_maj = MonthLocator(6)  # every x month
        # # months_min = MonthLocator(3)
        # # months_maj_fmt = DateFormatter('%m') #b = name of month ?
        # ax.xaxis.set_major_locator(years_maj)
        # # ax.xaxis.set_minor_locator(years_min)
        # ax.xaxis.set_major_formatter(years_maj_fmt)
        # # ax.set_ylim(0,40)
        # ymin.append(dfevol.index.year.min())
        # ymax.append(dfevol.index.year.max())
        # xmin.append(dfevol[metric].min())
        # xmax.append(dfevol[metric].max())
        # ax.set_xlim(pd.to_datetime(str(1960-space)),pd.to_datetime(str(2100+1)))
        
        
        # ax.set_ylim(0.5,4)
        # ax.set_ylim(0,25)
        plt.tight_layout()
        # ax.set_yticks(np.arange(1,4+1,1))
        # ax.set_yticklabels(np.arange(1,4+1,1))
        # ax.set_yticks(np.arange(5,25+1,5))
        # ax.set_yticklabels(np.arange(5,25+1,5))
        # ax.invert_yaxis()
        # ax.grid('grey')
        
        if ((ix-1) == 0) | ((ix-1) == 3) | ((ix-1) == 6):
            ax.set_ylabel('Q [mm/month]')
            # ax.set_ylabel('$Eccent_{ratio}$ [-]')
        if ((ix-1) == 6) | ((ix-1) == 7) | ((ix-1) == 8):
            ax.set_xlabel('Date')
        
        ord_min.append(q25.min())
        ord_max.append(q75.max())
        plt.setp(axs, ylim=(min(ord_min),max(ord_max)))
        plt.setp(axs, ylim=(0.05,3))

plt.tight_layout()

fig1.savefig(figsim_folder+'intermensual_discharge'+'.svg', dpi=300, bbox_inches='tight')
fig1.savefig(figsim_folder+'intermensual_discharge'+'.png', dpi=300, bbox_inches='tight')

#%% FIG : Evolution

figsim_folder = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/8_paper/hysteresis/figures/_outputs/'

# Things
typ = 'proj1'
time_step = 'M'
sim_state = 'transient'
var = 'REC'
scan = 'outflow_drain'

# Colored
mod_list = ['NOR1','IPS1']
sce_list = ['historic','RCP2.6','RCP8.5']
sce_cmap = ["Greys","Greens","Reds"]
sce_color = ['k',"dodgerblue","red"]
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

# Hysteres
temporal = True
space = -10
norm = False

watershed_names = ['Canut','Nancon']

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
    
    fig1, axs1 = plt.subplots(1,1, figsize=(8,3))
    ax = axs1
    
    for mod in mod_list:
            
        for sce in sce_list:
            
            if sce != 'historic':
                simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
                simul = simul_list[0]
            
            if sce == 'historic':
                simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+'RCP8.5'+'*')
                simul = simul_list[0]

            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            
            idx = pd.date_range(start='01/01/2000', end='31/12/2099', freq='M')
            # Smod = Smod.set_index(idx)
            years = Smod.index.year.unique()
            
            Smod['prop_perenn'] = Smod['perenn_areas'] / Smod['surflow_areas']
            Smod['prop_intermit'] = Smod['intermit_areas'] / Smod['surflow_areas']
            Smod['prop_ratio'] = Smod['prop_intermit'] / Smod['prop_perenn']
            
            Smod['year'] = Smod.index.year.values # group by month and year, get the average
            Smod['month'] = Smod.index.month.values # group by month and year, get the average
            # Smod = Smod.pivot('month','year')
            
            # ax.plot(Smod.surflow_areas)
            
            max_per = Smod['perenn_areas'].max().max()
            max_int = Smod['intermit_areas'].max().max()
            max_tot = max(max_per,max_int)
        
            intm = select_period(Smod, 1960,2021)
            intm = intm.groupby([lambda x: x.month]).mean()
            
            list_max.append(max_tot)
            
            for i in intm.month.values:
                Smod.loc[Smod.index.month==i, 'ano_prop_ratio'] = Smod.loc[Smod.index.month==i,'prop_ratio'] \
                                                                  - intm.loc[intm.month==i,'prop_ratio'].values[0]
                Smod.loc[Smod.index.month==i, 'ano_intermit_areas'] = Smod.loc[Smod.index.month==i,'intermit_areas'] \
                                                                  - intm.loc[intm.month==i,'intermit_areas'].values[0]
                Smod.loc[Smod.index.month==i, 'ano_perenn_areas'] = Smod.loc[Smod.index.month==i,'perenn_areas'] \
                                                                  - intm.loc[intm.month==i,'perenn_areas'].values[0]
                Smod.loc[Smod.index.month==i, 'ano_surflow_areas'] = Smod.loc[Smod.index.month==i,'surflow_areas'] \
                                                                  - intm.loc[intm.month==i,'surflow_areas'].values[0]                   
            col = 'ano_prop_ratio'
            ax.set_ylim(-1,1)
            ax.set_ylabel('Anomaly')
            ax.set_xlabel('Date')
    
            plus = Smod[col][Smod[col] >= 0]
            minus = Smod[col][Smod[col] < 0]
            
            color = color_dict[sce]
            
            if sce == 'historic':
                zorder = 10
                Smod = select_period(Smod, 1990, 2021)
                Smod = Smod.resample('Y').mean()
                Smod = Smod.rolling(window=10).mean()#.shift(-10)
            else:
                zorder = 0
                Smod = select_period(Smod, 2021, 2099)
                Smod = Smod.resample('Y').mean()
                Smod = Smod.rolling(window=10).mean()#.shift(-10)
            
            ax.plot(Smod[col], color=color, zorder=zorder)
            ax.axhline(y=0, c='k')
            ax.set_xlim(pd.to_datetime(str(1990)),pd.to_datetime(str(2100)))
            plt.xticks(rotation='horizontal')
            plt.xlabel('Date')
            ax.axvspan(pd.to_datetime(str(1990)), pd.to_datetime(str(2021)), color='lightgrey', alpha=0.1, zorder=0)

            years = mdates.YearLocator(20)   # every year
            yearsmin = mdates.YearLocator(1)
            years_fmt = mdates.DateFormatter('%Y')
            months_fmt = mdates.DateFormatter('%m') #b = name of month ?
            ax.xaxis.set_major_locator(years)
            ax.xaxis.set_minor_locator(yearsmin)
            ax.xaxis.set_major_formatter(years_fmt)
            
plt.tight_layout()

# fig1.savefig(figsim_folder+'evolution_intermitperenn'+'.svg', dpi=300, bbox_inches='tight')

#%% FIG : Pdf

from scipy.stats import binned_statistic

mod_list = ['MPI-R09','NOR-R15']


figsim_folder = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/8_paper/hysteresis/figures/_outputs/'

# Things
typ = 'projec-1'
time_step = 'M'
sim_state = 'transient'
var = 'REC'
scan = 'outflow_drain'

# Colored
sce_list = ['RCP2.6','RCP8.5']
# sce_list = ['RCP8.5']
sce_cmap = ["Greens","Reds"]
sce_color = ["dodgerblue","red"]
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

# Hysteres
temporal = False
space = 0
norm = False

watershed_names = ['Canut','Nancon']

# y_name = 'seepage_areas'
y_name = 'surflow_areas'
# y_name = 'intermit_areas'
# y_name = 'prop_ratio'
# y_name = 'perenn_areas'
# y_name = 'outflow_drain'
# y_name = 'groundwater_storage'
xmin = []
xmax = []
ymin = []
ymax = []

fig1, axs1 = plt.subplots(1,1, figsize=(5,4))
xn = [] #1e-6
xx = 1e-2
yn = 1e-3
yx = 1e1
ax = axs1
# ax.set_aspect('equal', adjustable='box')

# fig2, ax2 = plt.subplots(1,1, figsize=(5,4))

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
    
    # fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
    # xn = [] #1e-6
    # xx = 1e-2
    # yn = 1e-3
    # yx = 1e1
    # ax = axs1
    # ax.set_title(watershed_name+' '+' + '.join(mod_list))
    # # ax.set_aspect('equal', adjustable='box')
    
    if watershed_name == 'Canut':
        color = 'green'
    if watershed_name == 'Nancon':
        color = 'darkmagenta'
    
    for mod in mod_list:
        
        # fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
        # xn = 0.1
        # xx = 100
        # yn = 0.1
        # yx = 100
        # ax = axs1
        # ax.set_title(mod)
        # ax.set_aspect('equal', adjustable='box')

        for sce in sce_list:
            
            # if sce == 'RCP2.6':
            #     color = 'dodgerblue'
            # if sce == 'RCP8.5':
            #     color = 'red'
            
            if sce != 'historic':
                simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
                simul = simul_list[0]
            
            if sce == 'historic':
                simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+'RCP8.5'+'*')
                simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas
            
            if sce == 'historic':
                Smod = select_period(Smod, 1960, 2005)
            else:
                Smod = select_period(Smod, 2020, 2099)
            
            Qmod = Smod[scan] 
          
            Qmod = Qmod # mm/months
            Qmod = Qmod.squeeze()    
            Cmod = Smod['recharge'] # mm/months
            DFmod = pd.DataFrame(columns=['x','y'])
            DFmod['x'] = Cmod
            DFmod['y'] = Qmod
            first_valid_loc = DFmod[DFmod.index.month==10].apply(lambda col: col.first_valid_index()).max().year
            last_valid_loc = DFmod[DFmod.index.month==9].apply(lambda col: col.last_valid_index()).min().year
            DFmod = select_period(DFmod, first_valid_loc, last_valid_loc)
            for idx in range(len(DFmod)):
                if DFmod.index[idx].month == 10:
                    DFmod = DFmod[idx:]   
                    break
            DFmod = DFmod.sort_index(ascending=False)
            for idx in range(len(DFmod)):
                if DFmod.index[idx].month == 9:
                    DFmod = DFmod[idx:]
                    break
            DFmod = DFmod.sort_index(ascending=True)
                        
            ax = axs1
            # ax.set_aspect('equal', adjustable='box')
            # ax.scatter(Qmod, Smod.seepage_areas, color='grey', ec='none',
            #            s=30, alpha=0.5)
            # ax.scatter(Qmod, Smod.surflow_areas, color='k', ec='none',
            #            s=30, alpha=0.5)
            # ax.scatter(Qmod, Smod.perenn_areas, color='dodgerblue', ec='none',
            #            s=30, alpha=0.5)
            # ax.scatter(Qmod, Smod.intermit_areas, color='darkorange', ec='none',
            #            s=30, alpha=0.5)
                        
            Z = Smod[y_name]
            from scipy.stats import norm
            pdf = norm.pdf(Z, Z.mean(), Z.std())
            # ax.scatter(Z, pdf, s=1, color=color)
            
            import seaborn as sns
            sns.distplot(Z, hist = False, kde = True, norm_hist = True,
                  kde_kws = {'shade': False, 'linewidth': 2},
                  color=color)
            
            # ax.hist(Z, bins = 100, density=True,
            #         color = color, edgecolor = 'none')
                        
            ax.grid(color='grey',alpha=0.2)
                
            plt.tight_layout()
            
            ax.set_xlabel(y_name)
            ax.set_ylabel('PDF')
            
            # ax.set_xscale('log')
            
            xmin.append(Z.min())
            xmax.append(Z.max())
            ymin.append(pdf.min())
            ymax.append(pdf.max())
                        
            # if xn == []:
            #     plt.setp(ax,
            #              xlim=(min(xmin),max(xmax)),
            #              ylim=(min(ymin),max(ymax)))
            # else:
            #     ax.set_xlim(xn,xx)
            #     ax.set_ylim(yn,yx)
            
    fig1.tight_layout()
    # fig1.savefig(figsim_folder+'relation_qall'+'.png', dpi=300, bbox_inches='tight')

#%% ---- NOTES

#%% SEASONNAL EVOLUTION

time_step = 'M'

variables = ['REC']
scenarios = ['RCP8.5']
# scenarios = ['RCP8.5']
# simulations = ['MPI-CCL','ECE-RCA','ECE-RAC','CNR-RAC',
#                'NOR-R15','CNR-ALA','HAD-REG','MPI-R09']
simulations = 'MPI-CCL|ECE-RCA|ECE-RAC|CNR-RAC|NOR-R15|CNR-ALA|HAD-REG|MPI-R09'
# simulations = ['BCC1','CAN1','IPS1','NOR1']
# simulations = 'BCC1|CAN1|IPS1|NOR1'
# simulations = 'IPS1'

# sce_colors=["k","dodgerblue","forestgreen","darkorange","red"]
sce_colors = ["k","dodgerblue","red"]
color_dict = dict(zip(scenarios, sce_colors))

colors = mpl.cm.jet(np.linspace(0,1,n))

seasons = ['9,10,11',
           '12,1,2',
           '3,4,5',
           '6,7,8']
string = ['SON','DJF','MAM','JJA']
seas_dict = dict(zip(seasons, string))

space = 30

for var in variables:
    debut = 'D:/Users/abherve/PAPER/Canut/results_stable/drias/_ALL_D'
    df = pd.read_csv(debut+'.csv',
                     sep=';', index_col=0, parse_dates=True)
    df = df.filter(regex=simulations).filter(regex=var)
    fig, axs = plt.subplots(2,2, figsize=(10,5))
    axs = axs.ravel()
    for i, sea in enumerate(seasons):
        ax = axs[i]
        for sce in scenarios:
            try:
                dfb = df.filter(regex=sce)
                # if sce == 'historic':
                    # dfb = dfb[(dfb.index.year >= 1960) & (dfb.index.year <= 2009)]
                    
                    # rea = dfb['REA_historic']
                    # rea = rea.groupby([(rea.index.year),(rea.index.month)]).mean()
                    # rea = rea.rename_axis(["year", "month"]).to_frame()
                    # rea = rea.query("month == "+"["+sea+"]")
                    # rea = rea.groupby('year').sum()
                    # rea.index =  pd.to_datetime(rea.index, format='%Y')
                    
                # else:
                dfb = dfb[(dfb.index.year >= 1960) & (dfb.index.year <= 2099)]
                
                dfb = dfb.groupby([(dfb.index.year),(dfb.index.month)]).mean()
                dfb = dfb.rename_axis(["year", "month"])
                
                dfb = dfb.query("month == "+"["+sea+"]")
                dfb = dfb.dropna()
                dfb = dfb.groupby('year').sum()
                dfb.index =  pd.to_datetime(dfb.index, format='%Y')
                
                dfs = pd.DataFrame(index=dfb.index)
                dfs['MEAN'] = dfb.mean(axis=1)
                dfs['MIN'] = dfb.min(axis=1)
                dfs['MAX'] = dfb.max(axis=1)
                dfs['Q25'] = dfb.quantile(q=0.25, axis=1)
                dfs['Q50'] = dfb.quantile(q=0.50, axis=1)
                dfs['Q75'] = dfb.quantile(q=0.75, axis=1)
                dfs['STD'] = dfb.std(axis=1)
                dfs = dfs.iloc[1:-1]
                
                dfs = dfs.rolling(window=space).mean().shift(-space)
                
                # ax.plot(rea, ls='-', color='k', lw=0.25)
                # ax.fill_between(dfs.index, dfs['Q25'], dfs['Q75'],
                #                 color=color_dict[sce], alpha=0.1, edgecolor='none')
                # ax.plot(dfs['Q50'], lw=1, color=color_dict[sce], label=sce)
                # ax.fill_between(dfs.index, dfs.MEAN-dfs['STD'], dfs.MEAN+dfs['STD'], color=color_dict[sce], alpha=0.2, edgecolor='none')
                
                # ax.plot(dfb.rolling(window=space).mean().shift(-space),
                #         lw=1,
                #         label=dfb.columns) 
                
                cmap = cm.jet(np.linspace(0,1,len(dfb.columns)))
                for i,j in enumerate(dfb.columns):
                    ax.plot(dfb[j].rolling(window=space).mean().shift(0),
                            lw=1, color=cmap[i],
                            label=j) 
                
                # ax.plot(dfs['MEAN'], lw=5, color=color_dict[sce], label=sce)
                
                ax.set_xlim(pd.to_datetime('1960'), pd.to_datetime('2100'))
                ax.set_title(seas_dict[sea])
                # ax.legend(loc='upper left')
                # ax.axvline(pd.to_datetime('2010'), color='k', ls='--')
                from datetime import date
                ax.axvline(date.today(), color='k', ls='-')
                
                ax.axvline(dfs.first_valid_index(), color='grey', ls='-', lw=0.1)
                ax.axvline(dfs.last_valid_index(), color='grey', ls='-', lw=0.1)
                # ax.text(dfs.first_valid_index(),0.8, str(dfs.first_valid_index().year), rotation=90,
                #         transform=ax.get_xaxis_transform())
                
                if sea == '9,10,11':
                    ax.legend(loc='upper left')
                
            except:
                pass
    fig.suptitle(var)
    plt.tight_layout()
    # fig.savefig(fig_path+'SEASON EVOLUTION'+'.png', dpi=300, bbox_inches='tight')

#%% METHOD COLOR CMAP

# cmap = plt.cm.autumn
# cmaplist = [cmap(i) for i in range(cmap.N)]
# # cmaplist = ['darkred','orange']
# cmaplist[-1] = 'dodgerblue' # first value
# cmap = mpl.colors.LinearSegmentedColormap.from_list(
#     'Custom cmap', cmaplist, cmap.N)
# minn = 0
# maxn = 1.1
# intn = 0.1
# bounds = np.arange(minn, maxn, intn)
# norm = mpl.colors.BoundaryNorm(bounds, cmap.N)

# Met 1
# cmap = plt.cm.seismic_r  # define the colormap
# cmaplist = [cmap(i) for i in range(cmap.N)]
# # cmaplist[0] = (.5, .5, .5, 1.0)
# cmap = mpl.colors.LinearSegmentedColormap.from_list(
#     'Custom cmap', cmaplist, cmap.N)
# bounds = np.linspace(-0.8, 0.02, 10)
# norm = mpl.colors.BoundaryNorm(bounds, cmap.N)

# Met 2
# import cmasher as cmr
# import cmastro as cma
# import colorcet as cc
# bounds = np.array([-0.8, -0.6, -0.4, -0.2, 0.0, 0.01, 0.02])
# norm = mpl.colors.BoundaryNorm(boundaries=bounds, ncolors=256)
# divnorm = mpl.colors.TwoSlopeNorm(vmin=-0.8, vcenter=0, vmax=0.02)
# # midnorm = MidpointNormalize(vmin=-1., vcenter=0, vmax=0.02)
# bi = matplotlib.colors.LinearSegmentedColormap.from_list("", ["#ff0080","#ff0080","#a349a4","#0000ff","#0000ff"]) 
# bi_r = matplotlib.colors.LinearSegmentedColormap.from_list("", ["#0000ff","#0000ff","#a349a4","#ff0080","#ff0080"]) #reversed
# pc = ax.imshow(days_flux_ano,
#                 cmap=cmr.redshift_r, norm=divnorm, alpha=1)
# ax.imshow(np.ma.masked_where(mask >= 0, mask),
#            cmap=mpl.colors.ListedColormap('white'))

# Met 3
# cmap = 'seismic_r'
# orig_cmap = plt.cm.coolwarm_r
# shifted_cmap = shiftedColorMap(orig_cmap, midpoint=0.9, name='shifted')

# pcn = ax.imshow(np.ma.masked_where(days_flux_ano > 0, days_flux_ano),
#                 cmap = 'autumn_r', vmin = -0.5, vmax = 0.05,
#                 alpha=1)
# pcp = ax.imshow(np.ma.masked_where(days_flux_ano < 0, days_flux_ano),
#                 cmap = 'winter_r',
#                 norm=MidpointNormalize(vmin=-0.8, midpoint=0., vmax=0.02,
#                 alpha=1))
# mpl.colors.ListedColormap(['red'])

# import cmasher as cmr
# import cmastro as cma
# import colorcet as cc
# from colorcet.plotting import swatch, swatches, candy_buttons
# import holoviews as hv
# hv.extension('matplotlib')
# swatch('cyclic_isoluminant')
# cmap = cc.cm.bmy_r  # define the colormap
# cmap = cmr.guppy

# from mintpy.colors import ColormapExt
# cmap = ColormapExt('cmy').colormap

# from colour import Color
# red = Color("darkblue")
# colors = list(red.range_to(Color("cyan"),10))
# plt.plot(10,10, c=colors)

#%% DRIAS RECHARGE

gcm_list = ['CNR','MPI','HAD','ECE','IPS','NOR']
rcm_list = ['ALA','CCL','REG','RCA','WRF','R15','RAC','R09','HIR']
mix_list = ['MPI-CCL','ECE-RCA','ECE-RAC','IPS-RCA','CNR-RAC','NOR-R15',
            'CNR-ALA','NOR-HIR','HAD-CCL','IPS-WRF','HAD-REG','MPI-R09']
mix_list = ['MPI-CCL','ECE-RCA','ECE-RAC','CNR-RAC',
            'NOR-R15','CNR-ALA','HAD-REG','MPI-R09']
# mix_list = ['CNR-ALA']

n = len(mix_list)
colors = mpl.cm.jet(np.linspace(0,1,n))

fig, ax = plt.subplots(1,1, figsize=(10,5))
for i, mix in enumerate(mix_list):
    gcm = mix.split('-')[0]
    rcm = mix.split('-')[1]
    # BV.forcing.update_recharge_drias(gcm, rcm, 'historic', 1972, 2005, sim_state='transient')
    # histo =  BV.forcing.recharge.resample('M').sum()
    # idx = histo.index
    # histo = histo.iloc[::-1].reset_index(drop=True)
    # histo.index = idx
    # histo = histo.rolling(window=25).mean()
    BV.forcing.update_recharge_drias(gcm, rcm, 'RCP8.5', 2010, 2098, sim_state='transient')
    recharge = BV.forcing.recharge.resample('M').sum()
    idx = recharge.index
    # recharge = recharge.iloc[::-1].reset_index(drop=True)
    # recharge.index = idx
    # recharge = recharge.rolling(window=25).mean()
    tot = recharge.sum()
    # ax.plot(histo*1000, color=colors[i])
    ax.plot(recharge*1000, color=colors[i], label=mix+'_'+str(tot.round(2)))
    ax.set_yscale('log')
    ax.legend(loc='lower left')
    # ax.set_ylim(50)

#%% SURFEX RECHARGE

surfex_list = ['ACC1','BCC1','BNU1','CAN1',
               'CNR1','CSI1','IPS1','MIR1','NOR1']
fig, ax = plt.subplots(1,1, figsize=(10,5))
n = len(surfex_list)
colors = mpl.cm.jet(np.linspace(0,1,n))
for i, mod in enumerate(surfex_list):
    BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce='RCP8.5', 
                                      first_year=2010, last_year=2098, time_step='D',
                                      sim_state='transient')
    # BV.forcing.update_runoff_drias(gcm, rcm, 'historic', 2070, 2099, sim_state='transient')
    recharge = BV.forcing.recharge
    recharge = recharge.resample('M').sum()
    # recharge = recharge.rolling(window=10).mean()
    # runoff = BV.forcing.runoff
    tot = recharge.sum()
    ax.plot(recharge, color=colors[i], label=mod+'_'+str(tot.round(2)))
    # plt.plot(runoff)
    ax.set_yscale('log')
    ax.legend(loc='best')

#%% BINS EXAMPLES

# from scipy.stats import binned_statistic

# x = Smod.recharge * 30 * 1000
# y = Smod.outflow_drain * 30 * 1000

# x = np.log(x)
# y = np.log(y)

# # Method 1
# fig, ax = plt.subplots()
# ax.scatter(x,y, s=9)
# s, edges, _ = binned_statistic(x,y, statistic='mean', bins=np.logspace(min(x),max(x),100))
# ys = np.repeat(s,2)
# xs = np.repeat(edges,2)[1:-1]
# ax.hlines(s,edges[:-1],edges[1:], color="crimson", )
# for e in edges:
#     ax.axvline(e, color="grey", linestyle="--")
# ax.scatter(edges[:-1]+np.diff(edges)/2, s, c="limegreen", zorder=3)
# ax.set_xscale("log")
# ax.set_yscale("log")
# plt.show()

# # Method 2
# import numpy as np
# import matplotlib.pyplot as plt
# nbins = 10
# n, _ = np.histogram(x, bins=nbins)
# sy, _ = np.histogram(x, bins=nbins, weights=y)
# sy2, _ = np.histogram(x, bins=nbins, weights=y*y)
# mean = sy / n
# std = np.sqrt(sy2/n - mean*mean)
# fig, ax = plt.subplots()
# plt.plot(x, y, 'bo')
# plt.errorbar((_[1:] + _[:-1])/2, mean, yerr=std, fmt='r-')
# plt.show()

#%% WTI

# path_dem = 'C:/Users/ronan/OneDrive/_HydroDataPy/DEM/France/BDALTI_bzh_75m.tif'
# path_test = "D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/2_data/Test/"

# wbt.slope(
#     path_dem, 
#     path_test+'/'+'slope.tif', 
#     zfactor=None, 
#     units="degrees")

# wbt.d8_flow_accumulation(
#     path_dem, 
#     path_test+'/'+'acc.tif', 
#     out_type="cells", 
#     log=False, 
#     clip=False, 
#     pntr=False, 
#     esri_pntr=False)

# wbt.wetness_index(
#     path_test+'/'+'acc.tif', 
#     path_test+'/'+'slope.tif', 
#     path_test+'/'+'wti.tif')

#%% USING SURFEX PROJECTIONS

# # if (sce == 'RCP2.6') | (sce == 'RCP8.5'):
# if mod != 'REA':
    
#     # Historic
#     BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = sce,
#                                           first_year = first_hist, last_year = last_hist,
#                                           time_step = time_step, sim_state = sim_state)
#     Rech_hist = BV.forcing.recharge * Ratio_norm
#     BV.forcing.update_runoff_surfex(clim_mod = mod, clim_sce = sce,
#                                     first_year = first_hist, last_year = last_hist,
#                                     time_step = time_step, sim_state = sim_state)
#     Runof_hist = BV.forcing.runoff # m/month
    
#     # Future
#     BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = sce,
#                                       first_year = first, last_year = last,
#                                       time_step = time_step, sim_state = sim_state)
#     Rech_fut = BV.forcing.recharge * Ratio_norm
#     BV.forcing.update_runoff_surfex(clim_mod = mod, clim_sce=sce,
#                                     first_year = first, last_year = last,
#                                     time_step = time_step, sim_state = sim_state)
#     Runof_fut = BV.forcing.runoff # m/month
                    
#     Rech = pd.concat((Rech_fut, Rech_hist), axis=1).mean(axis=1)
#     Runof = pd.concat((Runof_fut, Runof_hist), axis=1).mean(axis=1)

#     BV.forcing.update_recharge(Rech, sim_state = sim_state)
#     BV.forcing.update_runoff(Runof, sim_state = sim_state)
    
#     plt.plot(Rech)

#%% H5

# dictio.to_hdf(h5file)    
# import pickle
# with open(h5file, 'wb') as handle:
#     pickle.dump(dictio, handle, protocol=pickle.HIGHEST_PROTOCOL)

# BV.list_flow_model = list_flow_model
# BV.list_of_success = list_success
# BV.save_object()

#%% MERGE GIFS

import imageio
import numpy as np    
gif1 = imageio.get_reader('D:/Users/abherve/PAPER/Canut/results_simulations/calibr-t1_1_REC-REA-historic_0.1-4.75-30_1972-2019/_figures/cross/_GIF_cross_.gif')
gif2 = imageio.get_reader('D:/Users/abherve/PAPER/Nancon/results_simulations/calibr-t1_1_REC-REA-historic_10.0-4.75-30_1972-2019/_figures/cross/_GIF_cross_.gif')
number_of_frames = min(gif1.get_length(), gif2.get_length()) 
new_gif = imageio.get_writer('D:/Users/abherve/PAPER/output.gif')
for frame_number in range(number_of_frames):
    img1 = gif1.get_next_data()
    img2 = gif2.get_next_data()
    new_image = np.hstack((img1, img2))
    new_gif.append_data(new_image)
gif1.close()
gif2.close()    
new_gif.close()

#%% GAEL
    
typ='good'

print('##### '+watershed_name.upper()+' #####')

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True,
                              modflow_path=modflow_path)

# Observed discharge
raw_path = stable_folder+'/'+'hydrometry/'

# Input recharge
bzh_rech = False
var = 'REC'
wr = True
sim_state = 'steady' # 'steady' or 'transient'
time_step = 'M' # or 'D'
actual_date = True # False if date is conceptual

# Active of not modules
box = False # if True generate a rectangular model
sink_fill = False # permit to fill sinks
modpath_sim = True # run modpath particle tracking if True
verbose = True # add print of MODFLOW in console
post_process = False # necessary to decompose post process of process

# Strcture of the model
nlay = 1 # vertical discrtization
bottom = None # aquifer flat or not
thick_exp = 1 # exponential decay of K with nlay
cond_decay = 0 # exponential decay of K with depth
thickness = 30 # m

# Hydraulic properties
KR = 7090
Koptim = 3.9
R = 3.9/7090

K = Koptim
Sy = 0.01

list_model_name = []
list_of_success = []
list_flow_model = []

BV.add_hydrodynamic()

# Update properties
BV.hydrodynamic.update_nlay(nlay) # 1
BV.hydrodynamic.update_bottom(bottom) # None
BV.hydrodynamic.update_cond_decay(cond_decay) # 0
BV.hydrodynamic.update_thick_exp(thick_exp) # 1
BV.hydrodynamic.update_thickness(thickness)

BV.hydrodynamic.update_hyd_cond(K) 
BV.hydrodynamic.update_porosity(Sy)

BV.add_forcing()
BV.add_oceanic(oceanic_path)
BV.forcing.update_recharge(R, sim_state=sim_state)
  
date_today = datetime.now().strftime("%d/%m/%Y %H:%M:%S") # just a string
date_today = date_today.replace('/','-')
date_today = date_today.replace(':','-')
date_today = date_today.replace(' ','_')

model_name = typ+'_'+str(0)+'_'+\
             str(Sy*100)+'-'+str(round(K,2))+'-'+str(thickness)
             
"""
# Run model
try:
    print('SIM - ' + model_name)
    success, flow_model = BV.run_modflow(ident=model_name,
                                         modpath_sim=modpath_sim,
                                         sink_fill=sink_fill,
                                         box=box,
                                         verbose=verbose,
                                         post_process=post_process)
    if success == True:
        print(     'Success')
    else:
        print(     'Error')
except:
    pass

list_model_name.append(model_name)
list_of_success.append(success)
list_flow_model.append(flow_model)
        
print(list_of_success)

dictio = {}
dictio['list_model_name'] = list_model_name
dictio['list_of_success'] = list_of_success
dictio['list_flow_model'] = list_flow_model
h5file = simulations_folder+'/'+'list_'+typ

dd.io.save(h5file, dictio)
    
print('##### '+watershed_name.upper()+' #####')

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
BV = watershed_root.Watershed(watershed_name=watershed_name,
                          dem_path=dem_path, 
                          out_path=out_path,
                          load=True,
                          modflow_path=modflow_path)

h5file = simulations_folder+'/'+'list_'+typ
d = dd.io.load(h5file)
list_model_name = d['list_model_name'][:]
list_of_success = d['list_of_success'][:]
list_flow_model = d['list_flow_model'][:]

for model_name, success, flow_model in zip(list_model_name, list_of_success, list_flow_model):
    
    if success==True:
        print(success)
        
        BV.matrix_modflow(success,
                          flow_model,
                          first_only = True,
                          watertable_elevation = True,
                          watertable_depth = True, 
                          seepage_areas = True,
                          outflow_drain = True,
                          groundwater_flux = False,
                          specific_discharge = False,
                          accumulation_flux = True,
                          perenn_intermit_shp = False,
                          groundwater_storage = False,
                          verbose = True,
                          export_tif = True)
        
        # Necessary for results_modflow
        BV.forcing.update_recharge(flow_model.climatic,
                                   sim_state=sim_state)
        
        # # Extract results
        BV.results_modflow(ident=model_name,
                           actual_date=actual_date,
                           time_step=time_step)
        
        ## Plot maps
        surf = modflow_display.SurfaceOutputs(flow_model.climatic, simulations_folder, stable_folder,
                                              model_name, types_obs,
                                              save_gif=False,
                                              first_only=True,
                                              sim_state=sim_state,
                                              outflow=True,
                                              accflux=True,
                                              intermittency=False,
                                              chronics=False)
        
"""

from tools import toolbox, vtk
from groundwater_flow import visualization, modflow_display

# 3D parameters
list_view = ['watertable_depth'] # object to represent in 3D
interactive = True
z_scale = 10
view = 'south-west'
lines = 200

vtk.VTK(BV, model_name)
visu = visualization.Visualization(BV, model_name)
visu.visual3D(interactive=interactive, object_list=list_view, z_scale=z_scale, view=view,
              lines=lines, cloc=(0.7,0.1))
