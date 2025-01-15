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
fig_path = res_path + 'out/_calib/'

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

#%% ---- DATA

#%% BASE DATA

sta_hydr = gpd.read_file(res_path + 'sig/' + 'hydrometric_calib.shp', engine='python')
sta_onde = gpd.read_file(res_path + 'sig/' + 'onde_calib.shp', engine='python')
sta_piez = gpd.read_file(res_path + 'sig/' + 'piezometry_calib.shp', engine='python')
sta_pomp = gpd.read_file(res_path + 'sig/' + 'ouvrages_approvis.shp', engine='python')
sta_reje = gpd.read_file(res_path + 'sig/' + 'rejets_vaunoise.shp', engine='python')
limit_cebr = gpd.read_file(res_path + 'sig/' + 'limit_cebr.shp', engine='python')
cours_eau = gpd.read_file(res_path + 'sig/' + 'cours_eau_clip.shp', engine='python')
plan_eau = gpd.read_file(res_path + 'sig/' + 'plan_eau_clip.shp', engine='python')
ville_rennes = gpd.read_file(res_path + 'sig/' + 'ville_rennes.shp', engine='python')
admin_dpmt = gpd.read_file(res_path + 'sig/' + 'admin_departement.shp', engine='python')
cont_frame = gpd.read_file(res_path + 'sig/' + 'Frame.shp', engine='python')
dem = rasterio.open(dem_path)
geol_f = gpd.read_file(data_path+'/GEOLOGY/France/Layer/'+'GEO001M_CART_FR_S_FGEOL_2154_CMYK.shp')
geol_s = gpd.read_file(data_path+'/GEOLOGY/France/Layer/'+'GEO001M_CART_FR_L_STRUCT_2154_CMYK.shp')

#%% BASE MAP

fig, ax = plt.subplots(1,1, figsize=(8,8), dpi=300)
bounds = cours_eau.geometry.total_bounds
xlim = ([bounds[0], bounds[2]])
ylim = ([bounds[1], bounds[3]])
ax.axis('on')
ax.ticklabel_format(style='plain')
ax.tick_params(which='both',
                right= False, top= False, left= False, bottom= False,
                labelright= False, labeltop= False, labelleft= False, labelbottom= False)
ax.set_xlim(xlim)
ax.set_ylim(ylim)
cours_eau[cours_eau.Classe<4].plot(ax=ax, lw=0.75, color='darkblue', alpha=1, zorder=1)
for watershed_name in ['Mordelles','Rophemel','Roche','Dam','Canut','Vaunoise','Drains']:
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    bv_cont = gpd.read_file(stable_folder+'geographic/'+'watershed.shp')
    bv_cont.plot(ax=ax, facecolor='none', edgecolor='k', lw=2, alpha=1, zorder=2)
limit_cebr.plot(ax=ax, lw=1.5, facecolor='none', edgecolor='white', alpha=1, zorder=1)
ville_rennes.plot(ax=ax, lw=0.2, facecolor='k', edgecolor='k', alpha=1, zorder=4)
plan_eau.plot(ax=ax, facecolor='darkblue', edgecolor='none', alpha=1, zorder=1)
sta_hydr.plot(ax=ax, lw=1, facecolor='white', marker='o', edgecolor='k', alpha=1, zorder=5)
sta_onde.plot(ax=ax, lw=1, facecolor='white', marker='s', edgecolor='k', alpha=1, zorder=5)
sta_piez.plot(ax=ax, lw=1, facecolor='white', marker='^', edgecolor='k', alpha=1, zorder=5)
sta_reje.plot(ax=ax, lw=1, facecolor='darkorange', marker='d', edgecolor='k', alpha=1, zorder=5)
sta_pomp.plot(ax=ax, lw=1, facecolor='yellow', marker='d', edgecolor='k', alpha=1, zorder=5)
wbt.hillshade(dem_path,
              'C:/Users/ronan/OneDrive/_HydroDataPy/DEM/France/'+'BDALTI_75m_EBR_HILL'+'.tif',
              azimuth=315.0, 
              altitude=45, 
              zfactor=10)
hill = rasterio.open('C:/Users/ronan/OneDrive/_HydroDataPy/DEM/France/'+'BDALTI_75m_EBR_HILL'+'.tif')
show(hill.read(1), ax=ax, transform=dem.transform, cmap='Greys_r', alpha=0.5, zorder=0)
image_hidden = ax.imshow(np.ma.masked_where(dem.read(1) < 0, dem.read(1)), cmap='terrain')
mnt = rasterio.plot.show(np.ma.masked_where(dem.read(1) < 0, dem.read(1)), 
                          ax=ax, transform=dem.transform, cmap='terrain', alpha=0.5, zorder=0)
# divider = make_axes_locatable(ax)
# cax = divider.new_vertical(size="2%", pad=0.05, pack_start=True)
# fig.add_axes(cax)
# cbar = fig.colorbar(image_hidden, cax=cax, orientation="horizontal")
# ticklabels = cbar.ax.get_ymajorticklabels()
# ticks = list(cbar.get_ticks())
# val = np.ma.masked_where(dem.read(1) < 0, dem.read(1))
# minVal =  int(round(np.min(val[np.nonzero(val)],0)))
# maxVal =  int(round(np.max(val[np.nonzero(val)],0)))
# meanVal = int(round(minVal+((maxVal-minVal)/2),0))
# cbar.set_ticks([minVal, meanVal, maxVal])
# cbar.set_ticklabels([minVal, meanVal, maxVal])
# cbar.mappable.set_clim(minVal, maxVal)
# cbar.ax.tick_params(labelsize=10)
# cbar.ax.yaxis.set_ticks_position('left')
# cbar.ax.tick_params(size=0)

# ls = LightSource(azdeg=315, altdeg=45)
# rgb = ls.shade(imageio.imread(dem_path),
#                 cmap=plt.cm.gist_earth, blend_mode='soft', vert_exag=10, dx=75, dy=75)
# plt.imshow(rgb)

# geol_f.plot(ax=ax, color=list(geol_f['hex']), alpha=0.5, edgecolor='none', zorder=0)
# geol_s.plot(ax=ax, color='dimgrey', alpha=0.5, edgecolor='dimgrey', zorder=0)

#%% BASE METEO

mesh = gpd.read_file(res_path+'sig/'+'maille_meteo_fr_pr93.shp')
mesh = mesh.set_index('num_id')
variables = ['TAS','PPT','ETP','RUN','REC']
for watershed_name in ['Frame']:
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
for var in variables:
    raw = pd.read_hdf(stable_folder+'climatic/'+'REA.h5', var+'/'+'historic')
    num_id = list(raw.columns.values)
    raw = raw.loc[:, raw.columns.isin(num_id)]
    raw = raw[raw.index.notnull()]
    first = 1960
    last = 2019
    mask = (raw.index.year >= first) & (raw.index.year <= last)
    raw = raw[mask]
    raw = raw.mean(axis=0)
    raw = raw.rename(var)
    for i in num_id:
        mesh.loc[i,var] = raw.loc[i]
mesh['PPT'] = mesh['PPT'] * 365
mesh['ETP'] = mesh['ETP'] * 365
mesh['EFF'] = mesh['PPT'] - mesh['ETP']
mesh['RUN'] = mesh['RUN'] * 365
mesh['REC'] = mesh['REC'] * 365
new_vars = ['TAS','PPT','ETP','EFF','RUN','REC']
color_map = ['Reds','Blues','Greens','Greys','Oranges','Purples']
dic_color = dict(zip(new_vars,color_map))
for var in new_vars : 
    fig, ax = plt.subplots(1,1, figsize=(8,8), dpi=300)
    bounds = cours_eau.geometry.total_bounds
    xlim = ([bounds[0], bounds[2]])
    ylim = ([bounds[1], bounds[3]])
    ax.axis('on')
    ax.ticklabel_format(style='plain')
    ax.tick_params(which='both',
                    right= False, top= False, left= False, bottom= False,
                    labelright= False, labeltop= False, labelleft= False, labelbottom= False)
    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    for watershed_name in ['Mordelles','Rophemel','Roche','Dam','Canut','Vaunoise','Drains']:
        stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
        bv_cont = gpd.read_file(stable_folder+'geographic/'+'watershed.shp')
        bv_cont.plot(ax=ax, facecolor='none', edgecolor='k', lw=2, alpha=1, zorder=2)
        clipped = gpd.clip(cours_eau, bv_cont)
        clipped[clipped.Classe<4].plot(ax=ax, lw=0.75, color='darkblue', alpha=1, zorder=1)
        clipped = gpd.clip(plan_eau, bv_cont)
        clipped.plot(ax=ax, facecolor='darkblue', edgecolor='none', alpha=1, zorder=1)
    limit_cebr.plot(ax=ax, lw=1.5, facecolor='none', edgecolor='white', alpha=1, zorder=1)
    ville_rennes.plot(ax=ax, lw=0.2, facecolor='k', edgecolor='k', alpha=1, zorder=4)
    sta_hydr.plot(ax=ax, lw=1, facecolor='white', marker='o', edgecolor='k', alpha=1, zorder=5)
    sta_onde.plot(ax=ax, lw=1, facecolor='white', marker='s', edgecolor='k', alpha=1, zorder=5)
    sta_piez.plot(ax=ax, lw=1, facecolor='white', marker='^', edgecolor='k', alpha=1, zorder=5)
    sta_reje.plot(ax=ax, lw=1, facecolor='darkorange', marker='d', edgecolor='k', alpha=1, zorder=5)
    sta_pomp.plot(ax=ax, lw=1, facecolor='yellow', marker='d', edgecolor='k', alpha=1, zorder=5)
    mesh.plot(ax=ax, column=var, 
              cmap=dic_color[var], lw=0.5, edgecolor='grey', alpha=1,
              vmin=None, vmax=None, zorder=-1)
    divider = make_axes_locatable(ax)
    sm = plt.cm.ScalarMappable(cmap=dic_color[var]) # norm=plt.Normalize(vmin=vmin, vmax=vmax)
    divider = make_axes_locatable(ax)
    cax = divider.new_vertical(size="3%", pad=0.05, pack_start=True)
    fig.add_axes(cax)
    cbar = fig.colorbar(sm, cax=cax, orientation="horizontal")
    ticklabels = cbar.ax.get_ymajorticklabels()
    ticks = list(cbar.get_ticks())
    val = mesh[var]
    minVal =  int(round(np.nanmin(val),0))
    maxVal =  int(round(np.nanmax(val,0)))
    meanVal = int(round(minVal+((maxVal-minVal)/2),0))
    cbar.set_ticks([minVal, meanVal, maxVal])
    cbar.set_ticklabels([minVal, meanVal, maxVal])
    cbar.mappable.set_clim(minVal, maxVal)
    cbar.ax.tick_params(labelsize=10)
    cbar.ax.yaxis.set_ticks_position('left')
    cbar.ax.tick_params(size=0)
        
#%% ---- CALIBRATION PLOT

#%% 0- DICHOTOMY K/R SITES

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
    
    # ax.axvline(df.perennial[0], color=lito[watershed_name], ls='-', zorder=-10)
    # ax.axvline(df.complete[0], color=lito[watershed_name], ls='--', zorder=-10)
    
    print(watershed_name, df.complete[0], df.perennial[0])
    
    ax.plot(df.perennial[0], cp,  color=lito[watershed_name], marker='s', ms=8, lw=0)
    ax.plot(df.complete[0], cp,  color=lito[watershed_name], marker='o', ms=8, lw=0)
    
    # plt.scatter(df.complete[0], np.sqrt(np.exp(df.complete[2])), color=lito[watershed_name], s=100)

    # ax.set_ylim(0.95)
    ax.set_xlim(4e-6, 1e-4)
    ax.set_xscale('log')
    ax.set_xlabel('K [m/s]', labelpad=1)
    
    # ax.grid(color='grey', axis='x')
    ax.hlines(cp, df.complete[0], df.perennial[0], color=lito[watershed_name])

    cp+=1

ax.set_yticks(np.arange(0,8,1))
ax.set_yticklabels(watershed_names)
    
fig.tight_layout()

# outfig = plots_path + 'demgeol_steady/'
# if not os.path.exists(outfig):
#     os.makedirs(outfig)

# fig.savefig(fig_path + 'dichotomy_sites_KR' + '.png', dpi=300, bbox_inches='tight')

#%% 1- DICHOTOMY MAP GEOL

# geol_f = gpd.read_file(geology_path+'GEO001M_CART_FR_S_FGEOL_2154_CMYK.shp')
# geol_s = gpd.read_file(geology_path+'GEO001M_CART_FR_L_STRUCT_2154_CMYK.shp')

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

marker_list = [18,
               6,
               4,
               4,
               4,
               2,
               4,
               4]
divlw_list = [1,
              1.5,
              2,
              2,
              2,
              2,
              2,
              2]

# watershed_names = ['Gael']

dic_marker = dict(zip(watershed_names, marker_list))
dic_divlw = dict(zip(watershed_names, divlw_list))

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
    
    streams = gpd.read_file(stable_folder+'hydrology/'+'perennial'+'.shp')
    complete = gpd.read_file(stable_folder+'hydrology/'+'complete'+'.shp')
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

    # hil = rasterio.plot.show(np.ma.masked_where(hill.read(1) < 0, hill.read(1)), 
    #                           ax=ax, transform=dem.transform,
    #                           cmap='Greys_r', alpha=0.5, zorder=2)
    
    geol_f.plot(ax=ax, color=list(geol_f['hex']),alpha=0.3, edgecolor='grey', lw=0.5, zorder=0)
    
    geol_s.plot(ax=ax, color=list(geol_s['hex']), alpha=0.3, lw=0.5, zorder=1)
    
    xlims = ax.get_xlim()[1] - ax.get_xlim()[0]
    ylims = ax.get_ylim()[1] - ax.get_ylim()[0]
    
    bbox = ax.get_window_extent().transformed(fig.dpi_scale_trans.inverted())
    width, height = bbox.width, bbox.height
    width *= fig.dpi
    height *= fig.dpi
    
    # rast = rasterio.plot.show(np.ma.masked_where(raster.read(1) < 0, raster.read(1)), 
    #                   ax=ax, transform=dem.transform, vmin=0, vmax=1000,
    #                   cmap='RdYlGn_r', alpha=1, zorder=4)

    simflow.plot(ax=ax, alpha=1, column='VALUE1', cmap="RdYlGn_r", 
                  marker='s', markersize=dic_marker[watershed_name], lw=0.1, edgecolor='none',
                  scheme="User_Defined", 
                  classification_kwds=dict(bins=[75, 150, 225, 300]),
                  zorder=4)
    
    from collections import OrderedDict
    
    linestyles = OrderedDict(
        [('solid',               (0, ())),
         ('loosely dotted',      (0, (1, 10))),
         ('dotted',              (0, (1, 5))),
         ('densely dotted',      (0, (1, 1))),
    
         ('loosely dashed',      (0, (5, 10))),
         ('dashed',              (0, (5, 5))),
         ('densely dashed',      (0, (5, 1))),
    
         ('loosely dashdotted',  (0, (3, 10, 1, 10))),
         ('dashdotted',          (0, (3, 5, 1, 5))),
         ('densely dashdotted',  (0, (3, 1, 1, 1))),
    
         ('loosely dashdotdotted', (0, (3, 10, 1, 10, 1, 10))),
         ('dashdotdotted',         (0, (3, 5, 1, 5, 1, 5))),
         ('densely dashdotdotted', (0, (3, 1, 1, 1, 1, 1)))])
    
    complete[complete.persistanc=='Intermittent'].plot(ax=ax, lw=1/dic_divlw[watershed_name],
                                                       color='navy', zorder=5)
    complete[complete.persistanc=='Permanent'].plot(ax=ax, lw=2/dic_divlw[watershed_name],
                                                    color='b', ls='-', zorder=5)
    # streams.plot(ax=ax, lw=2, color='k', zorder=6)
    contour.plot(ax=ax, lw=1.5, color='k', zorder=6)

    fig.tight_layout()
    
    fig.savefig(fig_path + 'dichotomy_streams_mapgeol_' + watershed_name  + '.png', dpi=300, bbox_inches='tight')

#%% 2 - EXPLORATION Q 2D

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
    
    df = pd.read_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')

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

        # cmap = mpl.cm.get_cmap('viridis_r')
        # color_gradients = cmap(c)
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
    pc = ax.contourf(X/3600/24, Y*100, Z, levels=np.arange(0,1.1,0.1), alpha=0.6, ec='none')    
    
    # divider = make_axes_locatable(ax)
    # cax = divider.append_axes('right', size='5%', pad=0.05)
    
    
    # position=fig.add_axes([1.05,0.33,0.03,0.5])  ##
    # cb = fig.colorbar(pc, cax=position, orientation='vertical')
    # cb.set_ticks(np.arange(0,1.1,0.2))
    # cb.set_ticklabels(np.arange(0,101,20)) 
    # cb.set_label('$NSE_{log}$', rotation=270, labelpad=40)
    # cb.ax.tick_params(top=True,
    #             bottom=True,
    #             left=False,
    #             right=False,
    #             labelleft=False,
    #             labelbottom=True)
    
    
    ax.set_xscale('log')
    ax.set_ylabel('Φ [%]')
    ax.set_xlabel('K [m/s]')
    # ax.set_yticks(np.arange(0,11,2))
    # ax.set_yticklabels(np.arange(0,11,2))
    # ax.tick_params(direction='in')
    ax.tick_params(top=True,
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
    '''
    ax.scatter(Xclip, Yclip, c=Z, s=20, marker='s', edgecolor='k',
                cmap=mpl.colors.ListedColormap('white'))
    '''
    
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
    
    ax.axvline(df.perennial[0], color='k', lw=2)
    ax.axvline(df.complete[0], color='k', lw=2, ls='--')
    
    ax.set_title(watershed_name, pad=10)
    plt.tight_layout()
    
    # fig.savefig(figsim_folder+watershed_name+'_calib2D_map'+'.png', dpi=300, bbox_inches='tight')
    fig.savefig(fig_path + 'Qmap_NSElog_' +
                watershed_name + '.png', dpi=300, bbox_inches='tight')

#%% 2 - EXPLORATION SAT 2D

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

# watershed_names = ['Canut']

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
    
    df = pd.read_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')
    
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

    fig, ax = plt.subplots(1,1, figsize=(3.8,3.5))
    ax.set_title(watershed_name, pad=10)
    
    ax.set_aspect('auto')
    ax.axes.tick_params(which='both', direction='out', zorder=10)
    
    X,Y = np.meshgrid(test.params_values[0], test.params_values[1])
    Z = np.empty((3,3,))
    Z[:] = np.nan
    p1 = test.params_values[0]
    p2= test.params_values[1]
    sim_sat_min = np.zeros((len(p1),len(p2)))
    sim_sat_mean = np.zeros((len(p1),len(p2)))
    sim_sat_max = np.zeros((len(p1),len(p2)))
    compt=0
    for i in range(len(p1)):
        for j in range(len(p2)):
            temp = [p1[i],p2[j]]
            string = str(p1[i])+';'+str(+p2[j])
            try:
                # ax.set_title('SAT MIN [%]')
                sim_sat_min[j][i] = pd.to_numeric(sim_res[string][sat_typ]).min()
            except:
                pass
            try:
                # ax.set_title('SAT MEAN [%]')
                sim_sat_mean[j][i] = pd.to_numeric(sim_res[string][sat_typ]).mean()
            except:
                pass
            try:
                # ax.set_title('SAT MAX [%]')
                sim_sat_max[j][i] = pd.to_numeric(sim_res[string][sat_typ]).max()
            except:
                pass
            compt += 1
    
    Z = (sim_sat_max - sim_sat_min)
    # pc = ax.contourf(X/24/3600,Y*100,Z, cmap='rainbow_r', alpha=0.9, levels=np.arange(0,101,10)) #figadd.cmap_white_jet()    
    pc = ax.contourf(X/24/3600,Y*100,Z, cmap='viridis', alpha=0.6, levels=np.arange(0,101,10)) #figadd.cmap_white_jet()    
    ax.set_xscale('log')
    ax.set_ylabel('Φ [%]')
    ax.set_xlabel('K [m/s]')
    
    Z = sim_sat_mean.copy()
    Z[Z<1] = np.nan
    Z[Z>10] = np.nan
    
    '''
    ax.scatter(X/24/3600,Y*100,c=Z, s=20, marker='s', edgecolor='k',
                cmap=mpl.colors.ListedColormap('white'))
    '''
        
    # position=fig.add_axes([1.05,0.2,0.02,0.7])  ## the parameters are the specified position you set 
    # fig.colorbar(pc,cax=position)
    
    # pc = ax.pcolormesh(X/3600/24, Y*100, Z,
    #                   cmap = mpl.colors.ListedColormap('white'),
    #                   alpha=0.5, linewidths=10)
    
    # pc = ax.contourf(X/3600/24, Y*100, Z, cmap=None,
    #                   levels=np.arange(0,100,5), alpha=0.75, linewidths=5,
    #                   colors='k',interpolation='none') # mpl.colors.ListedColormap('Grey')
    
    ax.tick_params(top=True,
               bottom=True,
               left=True,
               right=False,
               labelleft=True,
               labelbottom=True)
    
    ax.axvline(df.perennial[0], color='k', lw=2)
    ax.axvline(df.complete[0], color='k', lw=2, ls='--')
    
    # position=fig.add_axes([1.05,0.33,0.03,0.5])  ##
    # cb = fig.colorbar(pc, cax=position, orientation='vertical')
    # cb.set_ticks(np.arange(0,101,20)) 
    # cb.set_label('$NSE_{log}$', rotation=270, labelpad=40)
    # cb.ax.tick_params(top=True,
    #             bottom=True,
    #             left=False,
    #             right=False,
    #             labelleft=False,
    #             labelbottom=True)
    
    plt.tight_layout()    
    
    fig.savefig(fig_path + 'Smap_NSElog_' +
                watershed_name + '.png', dpi=300, bbox_inches='tight')

#%% ---- SIMULATION PLOT

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

#%% 3 - CHRONICS RESULTS

# watershed_names = [
#                    'Cheze',
#                    'Canut',
#                    'Gael',
#                    'Monfort',
#                    'Vaunoise',
#                    'Jouan',
#                    'Neal',
#                    'Rophemel',
#                    'Nancon',
#                    'Moulin',
#                    ]

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

watershed_names = [
                    'Vaunoise'
                    ]

mod = 'REA'

time_step = 'M'
sim_state = 'transient'

# watershed_names = ['Canut','Nancon']

# watershed_names = ['Canut']
# code_names = ['J7513010']

stats = pd.DataFrame(index=watershed_names)

types_obs = ['complete'] # list of shapefile name layers for clip hydrology
for watershed_name in watershed_names[:] :
    print('##### '+watershed_name.upper()+' #####')
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    BV.add_intermittency(intermittency_path)

    BV.add_forcing()
    scan = 'outflow_drain'
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    # simul_list = glob.glob(simulations_folder+typ+'*')
    simul_list = sorted(glob.glob(simulations_folder+typ+'*'),
                       key=os.path.getmtime)
    
    area = BV.geographic.area
    
    path_hydro = stable_folder+'hydrology/'
    perennial_tif = imageio.imread(path_hydro+'perennial.tif')
    complete_tif = imageio.imread(path_hydro+'complete.tif')
    
    area_complete = round((np.sum(complete_tif > 0) * 75**2) / 1000000 / area *100, 1)
    area_perennial = round((np.sum(perennial_tif > 0) * 75**2) / 1000000 / area*100, 1)
    # drainage = round(area_all / area, 2)
    
    for simul in simul_list[-1:]:
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
        
        stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
        raw_path = stable_folder+'/'+'hydrometry/'
        Qobs_path = fnmatch.filter(os.listdir(raw_path), 'Hydrometric_*')[0]
        Qobs = pd.read_csv(raw_path+Qobs_path, sep=';', index_col=0, parse_dates=True)
        
        f_simu = Qobs.first_valid_index().year+1
        if watershed_name == 'Gael':
            f_simu = 2009
        l_simu = Qobs.last_valid_index().year-1
        if watershed_name == 'Vaunoise':
            l_simu = 1989
        if l_simu == 2021:
            l_simu = 2019
        if f_simu < 1960:
            f_simu = 1960
            
        first = f_simu
        last = l_simu
        
        Smod = select_period(Smod, first, last)
        
        BV.forcing.update_runoff_surfex(clim_mod = mod, clim_sce='historic',
                                        first_year = first, last_year = last, time_step = 'M',
                                        sim_state='transient')
        Runof = BV.forcing.runoff # m/month
        
        Qmod = Smod['outflow_drain'] 
        Qmod = Qmod.squeeze() * 1000 * 30
        Qmod = Qmod + (BV.forcing.runoff * 1000 * 30)
        Cmod = Smod['recharge'] * 1000 * 30 # mm/months

        # area = float(Qobs_path.split('_')[-3])
        area = BV.geographic.area
        Qobs = select_period(Qobs, first, last)
        Qobs = (Qobs / (area*1000000)) * (3600 * 24 * 30) * 1000  # m3/s to mm/month
        Qobs = Qobs.squeeze()
        
        Qobs = Qobs.resample('M').mean()
                
        import hydroeval as he
        y0 = Qobs.copy()
        y1 = Qmod.copy()

        ER = np.nansum(y0-y1) # error 
        ABSER = np.nansum(np.abs(y0-y1))  # absolute error 
        RELER = np.nansum(np.abs(y0-y1)/y0) # relative error 
        PERER = np.nansum(np.abs(y0-y1)/y0*100) # percentage error 
        MAE = np.nanmean(np.abs(y0-y1)) # mean absolute error
        BAL = (np.sum(y1)/np.sum(y0))*100 # balance
        MSE = np.nanmean((y0-y1)**2) # mean square error 
        RMSE = np.sqrt(np.nanmean((y0-y1)**2)) # root mean square error 
        MARE = he.evaluator(he.mare, y1, y0)[0] # mean absolute relative error 
        KGE = he.evaluator(he.kge, y1, y0)[0][0] # kling-gupta efficiency (r, α, β)
        PBIAS  = he.evaluator(he.pbias, y1, y0)[0] # percent bias
        NSE = 1-( np.sum((y1-y0)**2) / np.sum((y0-np.mean(y0))**2) ) # nash–sutcliffe efficiency (add '1-' ==> actual NSE)
        NSElog = he.evaluator(he.nse, y1, y0, transform='log')[0] # nash–sutcliffe efficiency log
        
        stats.loc[watershed_name,'NSE'] = NSE
        
        print(first, last)
        print(round(NSE,2))

        # plt.plot(Cmod)
        # plt.plot(Qobs)
        # plt.plot(Qmod)
        
        o = Qobs # m/j to mm/month
        s = Qmod.copy() # m/j to mm/month
        # nd = 
        sat = Smod['surflow_areas']
        # sat = Smod['seepage_areas']
        
        ######################################################################
        
        fig, ax = plt.subplots(1,1, figsize=(3,3))
        ax.scatter(select_period(o,first,last),select_period(s,first,last),
                   s=25, edgecolor='none', alpha=0.75, facecolor='forestgreen')
        ax.set_xscale('log')
        ax.set_yscale('log')
        ax.plot((0.1,1000),(0.1,1000), color='grey', zorder=-1)
        ax.set_xlim(0.1,1000)
        ax.set_ylim(0.1,1000)    
        ax.set_xlabel('$Q_{obs}$ / A [mm/mois]')
        ax.set_ylabel('$Q_{sim}$ / A [mm/mois]')
        ax.set_title(watershed_name)

        fig.savefig(fig_path+'_obs_sim_compar'+watershed_name+'.png', dpi=300, bbox_inches='tight')

        ######################################################################

        # fig, axs = plt.subplots(2,1, figsize=(7,6))
        # axs = axs.ravel()
        
        fig, ax = plt.subplots(1,1, figsize=(7,3))

        yearsmaj = mdates.YearLocator(5)   # every year
        yearsmin = mdates.YearLocator(1)
        # monthsmaj = mdates.MonthLocator(6)  # every month
        # monthsmin = mdates.MonthLocator(3)
        # months_fmt = mdates.DateFormatter('%m') #b = name of month ?
        years_fmt = mdates.DateFormatter('%Y')
        
        k = '{:.1e}'.format(K)
        sy = Sy
        title = watershed_name
        # nselog = round(((nd[0]))*100,1)
        # label = 'K = '+k+' m/s'+' ; '+'ɸ = '+str(round(sy,1))+'% ; '+\
        #         '$NSE_{log}$ = '+str(nselog)+'%'
        # nse_good.append(str(k)+'_'+str(sy)+'_'+str(nselog))
        
        '''
        ax = axs[0]
        ax.xaxis.set_major_locator(yearsmaj)
        ax.xaxis.set_minor_locator(yearsmin)
        ax.xaxis.set_major_formatter(years_fmt)
        
        # ax.plot(R, color='k', lw=2, label='recharge')
        ax.plot(s, color='red', lw=2, label='modeled')
        # ax.plot(s, lw=1, label=label)   
        ax.set_title(title)
        ax.plot(o, color='grey', lw=2, ls='-', zorder=0, label='observed')
        ax.grid('grey')
        ax.set_ylim(-2,200)
        # ax.set_xlim(pd.to_datetime('2000'), pd.to_datetime('2005'))
        ax.legend(loc='upper left')
        '''
        
        # ax = axs[0]
        ax.set_title(watershed_name)
        ax.set_ylabel('Q / A [mm/mois]')
        axb = ax.twinx()
        axb.set_ylabel('R [mm/mois]', rotation=270, labelpad=25)
        axb.bar(Cmod.index, Cmod,
                color='blue', edgecolor='blue', lw=2.5)
        axb.set_ylim(0,999)
        axb.invert_yaxis()
        axb.set_yticklabels([0,200])
        # axb.xaxis.set_major_formatter_locator(yearsmaj)
        # axb.xaxis.set_minor_locator(yearsmin)
        # axb.xaxis.set_major_formatter(years_fmt)
        # ax.plot(R, color='k', lw=2, label='recharge')
        ax.xaxis.set_major_locator(yearsmaj)
        ax.xaxis.set_minor_locator(yearsmin)
        ax.xaxis.set_major_formatter(years_fmt)
        ax.plot(o, color='k', lw=2, ls='-', zorder=0, label='observed')
        # ax.set_yscale('log')
        ax.plot(s, color='red', lw=2, label='modeled')
        ax.set_ylim(0.11,200)
        # ax.grid('grey')
        # ax.set_title('Discharge')
        # ax.set_xlim(pd.to_datetime('1986'))
        ax.set_xlim(pd.to_datetime(str(first)), pd.to_datetime(str(last)))
        
        fig.savefig(fig_path+'_discharge_chronic'+watershed_name+'.png', dpi=300, bbox_inches='tight')

        ######################################################################
        
        fig, ax = plt.subplots(1,1, figsize=(7,3))

        # fig, axs = plt.subplots(1,2, figsize=(7,4))
        # ax = axs[1]
        ax.set_ylabel('$A_{sat}$ [%]')
        # axb = ax.twinx()
        # axb.set_ylim(0,1000)
        # axb.invert_yaxis()
        # ax.axhline(y=20, color='k', ls= '--', lw=2)
        ax.xaxis.set_major_locator(yearsmaj)
        ax.xaxis.set_minor_locator(yearsmin)
        ax.xaxis.set_major_formatter(years_fmt)    
        # sat_good.append(str(k)+'_'+str(sy)+'_'+str(round(sat.mean(),2)))
        ax.plot(Smod['surflow_areas'], color='darkorange', ls='-', lw=2, label='catchment')
        ax.fill_between(Smod.index, Smod['perenn_areas'], Smod['surflow_areas'],
                        interpolate=False, color='darkorange', alpha=0.75)
        # ax.plot(Smod['intermit_areas'], color='darkorange', lw=2, label='upstream')
        ax.plot(Smod['perenn_areas'], color='dodgerblue',
                marker=None, markeredgecolor='none', markerfacecolor='dodgerblue',
                markersize=5, lw=2, label='upstream')
        ax.fill_between(Smod.index, 0, Smod['perenn_areas'],
                        interpolate=False, color='dodgerblue', alpha=0.75)
        # ax.plot(sat, lw=1, label=label) 
        ax.set_ylim(0,20)
        # title = 'Saturation'
        # ax.set_title(title)
        # ax.set_xlim(pd.to_datetime('1990'), pd.to_datetime('2020'))
        # ax.grid('grey')
        ax.set_xlim(pd.to_datetime(str(first)), pd.to_datetime(str(last)))
        
        ax.axhline(y=area_perennial, c='blue', lw=2, ls='-')
        ax.axhline(y=area_complete, c='navy', lw=1, ls='-')
        
        # fig.savefig(figsim_folder+watershed_name+'_quickly_plot_results'+'.png', dpi=300, bbox_inches='tight')
        
        fig.savefig(fig_path+'_area_intermittency'+watershed_name+'.png', dpi=300, bbox_inches='tight')
        
        ######################################################################

        try:
            len_onde = len(glob.glob(simul+'/_subbasins/intermittency_*'))
            for i in range((len_onde)):
                if i == 0:
                    fig, ax = plt.subplots(1,1, figsize=(6,3))
    
                    Sub_path = glob.glob(simul+'/_subbasins/intermittency_*')[i]+'/_simulated_results.csv'
                    Sub = pd.read_csv(Sub_path, sep=';', index_col=0, parse_dates=True)
                    # ax.axhline(y=20, color='grey', ls='--', lw = 1, label='approxim. observed')
                    # ax.plot(Sub['perenn_areas'], color='dodgerblue', lw=2)
                    # ax.plot(Sub['intermit_areas'], color='darkorange', lw=2)
                    # ax.legend(loc='upper left')
                    d = BV.intermittency.flowing
                    d = d.iloc[:, i]
                    # print(d)
                    assec = d[d==1].dropna()
                    invi = d[d==2].dropna()
                    low = d[d==3].dropna()
                    accep = d[d==4].dropna()
                    visib = d[d==5].dropna()
                    
                    # for u in range(len(noflow)):
                    #     ax.axvline(noflow.index[u], color='salmon', linewidth = 5, alpha=1)
                    # for u in range(len(flow)):
                    #     ax.axvline(flow.index[u], color='lightskyblue', linewidth = 5, alpha=1)
                        
                    for u in range(len(assec)):
                        ax.axvline(assec.index[u], color='salmon', linewidth = 4, alpha=1) # assec
                    for u in range(len(invi)):
                        ax.axvline(invi.index[u], color='gold', linewidth = 4, alpha=1) # pond
                    for u in range(len(low)):
                        ax.axvline(low.index[u], color='lightskyblue', linewidth = 4, alpha=1) # bio mal
                    for u in range(len(accep)):
                        ax.axvline(accep.index[u], color='lightskyblue', linewidth = 4, alpha=1) # bio ok
                    for u in range(len(visib)):
                        ax.axvline(visib.index[u], color='lightskyblue', linewidth = 4, alpha=1) # ecoul
                    
                    ax.axhline(y=0, color='dimgray', lw= 1)
            
                    ax.set_xlim(pd.to_datetime('2012'), pd.to_datetime('2020'))
                    seep = Sub['seepage_areas']
                    seep = seep.fillna(0)
                    ax.plot(seep, color='k', ls=(0, (1, 1)), lw=1.5, label='upstream')
                    tp = Sub['surflow_areas']
                    tp = tp.fillna(0)
                    ax.plot(tp, color='k', lw=1.5, label='upstream')
                    # cond_coul = 0
                    # flow_mod = tp.copy()
                    # flow_mod[flow_mod<=cond_coul] = np.nan
                    # ax.plot(flow_mod, color='navy', marker='o', markersize=3,
                    #         markeredgecolor='none',
                    #         lw=2, label='upstream')
                    # noflow_mod = tp.copy()
                    # noflow_mod[noflow_mod>cond_coul] = np.nan
                    # ax.plot(noflow_mod, color='darkred', marker='o', markersize=3,
                    #         markeredgecolor='none',
                    #         lw=2, label='upstream')
                    ax.grid('grey', axis='x')
                    ax.set_ylim(-0.6,20)
                    ax.set_ylabel('$A_{sat}$ [%]')
                    
                    months_maj = MonthLocator()  # every x month
                    ax.xaxis.set_minor_locator(months_maj)
                    
                    plt.tight_layout()
                    
                    fig.savefig(fig_path+'_onde_validation'+watershed_name+'.png', dpi=300, bbox_inches='tight')

            # ax.legend(bbox_to_anchor=(1.5, 3), ncol=1)
        except:
            pass
        
        # fig.savefig(figsim_folder+watershed_name+'_onde_compar'+'.png', dpi=300, bbox_inches='tight')

#%% 4 - INTERMITTENCY MAP

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

mod = 'REA'

time_step = 'M'
sim_state = 'transient'

# watershed_names = ['Canut']

types_obs = ['complete'] # list of shapefile name layers for clip hydrology
for watershed_name in watershed_names[:] :
    print('##### '+watershed_name.upper()+' #####')
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    wbt.vector_lines_to_raster(stable_folder+'geographic/'+'watershed_contour.shp',
                               stable_folder+'geographic/'+'watershed_contour.tif',
                               base = stable_folder+'geographic/'+'watershed_dem.tif')
    line = imageio.imread(stable_folder+'geographic/'+'watershed_contour.tif')
    line = np.ma.masked_where(line <= 0, line)
    
    mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
    
    # BV.add_intermittency(intermittency_path)

    BV.add_forcing()
    scan = 'outflow_drain'
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    # simul_list = glob.glob(simulations_folder+typ+'*')
    simul_list = sorted(glob.glob(simulations_folder+typ+'*'),
                       key=os.path.getmtime)
         
    for simul in simul_list[-1:]:
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
        
        stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
        
        min_area = Smod['surflow_areas'].min()
        min_idx = np.argmin(Smod['surflow_areas'])
        max_area = Smod['surflow_areas'].max()
        max_idx = np.argmax(Smod['surflow_areas'])
        max_year = Smod['surflow_areas'].index[max_idx]
        
        acc_npy = np.load(os.path.join(simul, '_watershed','accumulation_flux.npy'), allow_pickle=True).item()
        inf = 0
        sup = 12
        compt = 0
        step = int(round(len(acc_npy)/12))
        
        for i in range(step):
            print(str(i)+'/'+str(step))
            interv = list(acc_npy.items())[inf:sup]
            # print(interv)
            for key in range(len(interv)):
                # key = tupl[0]
                # print(key)
                interv[key] = np.ma.masked_array(interv[key][1], mask=(mask<0))

            zero = acc_npy[0] * 0
            for j in range(len(interv)):
                tempo = interv[j].copy()
                tempo[tempo>0] = 1
                zero = zero + tempo
            days_flux = zero.copy()
            days_flux = np.ma.masked_array(days_flux, mask=(mask<0))
            days_flux = np.ma.masked_array(days_flux, mask=(days_flux<=0))
        
        for k, j in enumerate([min_idx, max_idx]):
                
                year = Smod['surflow_areas'].index[j]
                val = Smod.iloc[j]['surflow_areas']

                days_flux = acc_npy[j]
    
                fig, ax = plt.subplots(1,1, figsize=(7,6))
                ax.set_title(str(year)[0:10] + '   ' + '$A_{sat}$ = ' + str(val.round(1)) + ' [%]',
                             pad=10)
                # image_hidden = ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys')
                ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys', alpha=0.5, zorder=0)
                ax.imshow(np.ma.masked_where((days_flux<=0) | (mask <0),
                                             days_flux), 
                          cmap = mpl.colors.ListedColormap(['navy'])) # dodgerblue
                ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
                ax.get_xaxis().set_visible(False)
                ax.get_yaxis().set_visible(False)
                plt.axis('off')
        
                # ax.set_title(years[i])
                
                try:
                    path_sub = glob.glob(stable_folder+'subbasin/' + '/intermittency*')[0] + '/watershed_contour.shp'
                    wbt.vector_lines_to_raster(path_sub,
                                               glob.glob(stable_folder+'subbasin/' + '/intermittency*')[0] + '/watershed_contour.tif',
                                               base = stable_folder+'geographic/'+'watershed_dem.tif')
                    line_sub = imageio.imread(glob.glob(stable_folder+'subbasin/' + '/intermittency*')[0] + '/watershed_contour.tif')
                    line_sub = np.ma.masked_where(line_sub <= 0, line_sub)
                    ax.imshow(line_sub, cmap=mpl.colors.ListedColormap('darkorange'))
                except:
                    pass
                
                fig.savefig(fig_path+'_map_rseau_'+watershed_name+'_'+str(k)+'.png', dpi=300, bbox_inches='tight')
                plt.close()
                
#%% 5 -  CRITERION OPTIM
          
watershed_names = [
                   'Canut',
                   'Cheze',
                   'Gael',
                   # 'Monfort',
                   'Vaunoise',
                    'Neal',
                    'Jouan',
                   # 'Rophemel',
                   'Moulin',
                   'Nancon',
                   ]

# watershed_names = [
#                     'Vaunoise'
#                     ]

mod = 'REA'

time_step = 'M'
sim_state = 'transient'

stats = pd.DataFrame(index=watershed_names)

types_obs = ['complete'] # list of shapefile name layers for clip hydrology
for watershed_name in watershed_names[:] :
    print('##### '+watershed_name.upper()+' #####')
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    # BV.add_intermittency(intermittency_path)

    BV.add_forcing()
    scan = 'outflow_drain'
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    # simul_list = glob.glob(simulations_folder+typ+'*')
    simul_list = sorted(glob.glob(simulations_folder+typ+'*'),
                       key=os.path.getmtime)
    
    area = BV.geographic.area
    
    path_hydro = stable_folder+'hydrology/'
    perennial_tif = imageio.imread(path_hydro+'perennial.tif')
    complete_tif = imageio.imread(path_hydro+'complete.tif')
    
    area_complete = round((np.sum(complete_tif > 0) * 75**2) / 1000000 / area *100, 1)
    area_perennial = round((np.sum(perennial_tif > 0) * 75**2) / 1000000 / area*100, 1)
    # drainage = round(area_all / area, 2)
    
    for simul in simul_list[-1:]:
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
        
        stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
        raw_path = stable_folder+'/'+'hydrometry/'
        Qobs_path = fnmatch.filter(os.listdir(raw_path), 'Hydrometric_*')[0]
        Qobs = pd.read_csv(raw_path+Qobs_path, sep=';', index_col=0, parse_dates=True)
        
        f_simu = Qobs.first_valid_index().year+1
        if watershed_name == 'Gael':
            f_simu = 2009
        l_simu = Qobs.last_valid_index().year-1
        if watershed_name == 'Vaunoise':
            l_simu = 1989
        if l_simu == 2021:
            l_simu = 2019
        if f_simu < 1960:
            f_simu = 1960
            
        first = f_simu
        last = l_simu
        
        Smod = select_period(Smod, first, last)
        
        BV.forcing.update_runoff_surfex(clim_mod = mod, clim_sce='historic',
                                        first_year = first, last_year = last, time_step = 'M',
                                        sim_state='transient')
        Runof = BV.forcing.runoff # m/month
        
        Qmod = Smod['outflow_drain'] 
        Qmod = Qmod.squeeze() * 1000 * 30
        Qmod = Qmod + (BV.forcing.runoff * 1000 * 30)
        Cmod = Smod['recharge'] * 1000 * 30 # mm/months

        # area = float(Qobs_path.split('_')[-3])
        area = BV.geographic.area
        Qobs = select_period(Qobs, first, last)
        Qobs = (Qobs / (area*1000000)) * (3600 * 24 * 30) * 1000  # m3/s to mm/month
        Qobs = Qobs.squeeze()
        
        Qobs = Qobs.resample('M').mean()
                
        import hydroeval as he
        y0 = Qobs.copy()
        y1 = Qmod.copy()

        ER = np.nansum(y0-y1) # error 
        ABSER = np.nansum(np.abs(y0-y1))  # absolute error 
        RELER = np.nansum(np.abs(y0-y1)/y0) # relative error 
        PERER = np.nansum(np.abs(y0-y1)/y0*100) # percentage error 
        MAE = np.nanmean(np.abs(y0-y1)) # mean absolute error
        BAL = (np.sum(y1)/np.sum(y0))*100 # balance
        MSE = np.nanmean((y0-y1)**2) # mean square error 
        RMSE = np.sqrt(np.nanmean((y0-y1)**2)) # root mean square error 
        MARE = he.evaluator(he.mare, y1, y0)[0] # mean absolute relative error 
        KGE = he.evaluator(he.kge, y1, y0)[0][0] # kling-gupta efficiency (+ ==> r, α, β)
        PBIAS  = he.evaluator(he.pbias, y1, y0)[0] # percent bias
        NSE = 1-( np.sum((y1-y0)**2) / np.sum((y0-np.mean(y0))**2) ) # nash–sutcliffe efficiency (add '1-' ==> actual NSE)
        NSElog = he.evaluator(he.nse, y1, y0, transform='log')[0] # nash–sutcliffe efficiency log
        
        stats.loc[watershed_name,'Area'] = area.round(2)
        stats.loc[watershed_name,'Slope'] = BV.geographic.slope.round(2)
        stats.loc[watershed_name,'Asat comp'] = area_complete
        stats.loc[watershed_name,'Asat perm'] = area_perennial
        stats.loc[watershed_name,'R'] = (Smod.recharge*1000*30).mean().round(2)
        stats.loc[watershed_name,'Kcomp'] = np.nan
        stats.loc[watershed_name,'Kperm'] = np.nan
        stats.loc[watershed_name,'Poro'] = np.nan
        
        stats.loc[watershed_name,'NSE'] = NSE
        stats.loc[watershed_name,'NSElog'] = NSElog
        stats.loc[watershed_name,'KGE'] = KGE
        stats.loc[watershed_name,'RMSE'] = RMSE
        stats.loc[watershed_name,'MAE'] = MAE
        stats.loc[watershed_name,'MARE'] = MARE
        
        stats.loc[watershed_name,'Perm mod'] = (Smod.perenn_areas).mean().round(2)
        stats.loc[watershed_name,'Comp mod'] = (Smod.surflow_areas).mean().round(2)
        
        # stats.loc[watershed_name,'ER'] = ER
        # stats.loc[watershed_name,'ABSER'] = ABSER
        # stats.loc[watershed_name,'RELER'] = RELER
        # stats.loc[watershed_name,'PERER'] = PERER
        # stats.loc[watershed_name,'BAL'] = BAL
        # stats.loc[watershed_name,'MSE'] = MSE
        # stats.loc[watershed_name,'PBIAS'] = PBIAS

        print(first, last)
        print(round(NSE,2))

stats = stats.round(2)

stats.to_csv(fig_path+'calibration_stats_all_sites'+'.csv', sep=';')

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
