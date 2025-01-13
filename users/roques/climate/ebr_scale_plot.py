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
from scipy.stats import norm

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
from matplotlib.ticker import ScalarFormatter
from matplotlib.ticker import MaxNLocator
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

def deficiency_evaporation(dfmonth, ppt_col, etp_col, ppt_etp_col, etr_col, ru_col, de_col):
    calc = pd.DataFrame()
    calc[ppt_etp_col] = (dfmonth[ppt_col]-dfmonth[etp_col]).round(2)
    calc[ru_col] = np.nan
    calc[etp_col] = dfmonth[etp_col]
    calc[ppt_col] = dfmonth[ppt_col]
    
    long = np.array(range(0,len(calc)))
    
    for r in long:
        idx = calc.index[0]
        calc[ru_col][idx] = 125
        if r == len(calc)-1:
            break
        else:
            if (calc[ru_col][r] + calc[ppt_etp_col][r+1]) >= 125:
                calc[ru_col][r+1] = 125      
            if 0 < (calc[ru_col][r] + calc[ppt_etp_col][r+1]) < 125:
                calc[ru_col][r+1] = (calc[ru_col][r]+ 
                                              calc[ppt_etp_col][r+1])
            if (calc[ru_col][r] + calc[ppt_etp_col][r+1]) <= 0:
                calc[ru_col][r+1] = 0
    
    calc[etr_col] = np.nan
    for p in calc[ppt_etp_col]:
        if p > 0:
            idx1 = calc.index[calc[ppt_etp_col] == p]
            calc[etr_col][idx1] = calc[etp_col][idx1]
    
        else:
            idx2 = calc.index[calc[ppt_etp_col] == p]
            calc[etr_col][idx2] = (calc[ppt_col][idx2] + (
                calc[ru_col][idx2]-1) - calc[ru_col][idx2])
    
    calc[de_col] = calc[etp_col] - calc[etr_col]

    for n in long:
        if calc[de_col][n] < 0:
            calc[de_col][n] = 0
            
    calc[de_col] = calc[de_col].round(2)
    
    dfmonth[etr_col] = calc[etr_col]
    dfmonth[de_col] = calc[de_col]
    
    return(dfmonth)

def interpolated_intercepts(x, y1, y2):
    def intercept(point1, point2, point3, point4):
        def line(p1, p2):
            A = (p1[1] - p2[1])
            B = (p2[0] - p1[0])
            C = (p1[0]*p2[1] - p2[0]*p1[1])
            return A, B, -C
        def intersection(L1, L2):
            D  = L1[0] * L2[1] - L1[1] * L2[0]
            Dx = L1[2] * L2[1] - L1[1] * L2[2]
            Dy = L1[0] * L2[2] - L1[2] * L2[0]
            x = Dx / D
            y = Dy / D
            return x,y
        L1 = line([point1[0],point1[1]], [point2[0],point2[1]])
        L2 = line([point3[0],point3[1]], [point4[0],point4[1]])
        R = intersection(L1, L2)
        return R
    idxs = np.argwhere(np.diff(np.sign(y1 - y2)) != 0).item()
    xcs = []
    ycs = []
    if type(idxs) is not int:
        for idx in idxs:
            xc, yc = intercept((x[idx], y1[idx]),((x[idx+1], y1[idx+1])), ((x[idx], y2[idx])), ((x[idx+1], y2[idx+1])))
            xcs.append(xc)
            ycs.append(yc)
    else:
        idx = idxs
        xc, yc = intercept((x[idx], y1[idx]),((x[idx+1], y1[idx+1])), ((x[idx], y2[idx])), ((x[idx+1], y2[idx+1])))
        xcs.append(xc)
        ycs.append(yc)
    return np.array(xcs), np.array(ycs)

def main(x, y1, y2):
    # idx = np.argwhere(np.diff(np.sign(y1 - y2)) != 0).item()
    xcs, ycs = interpolated_intercepts(x,y1,y2)
    return ((xcs.item())), ((ycs.item()))

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

#%% PATH WATERSHED

git_path = "D:/Users/abherve/GITHUB/HydroModPy/CORE_COMM/"
# Path to the data folder
data_path = "C:/Users/ronan/OneDrive/_HydroDataPy/"
# Path where the results will be stored
out_path = "D:/Users/abherve/EBR/"
out_path = "G:/RENNES/EBR_PROJECTIONS/"
out_path = "G:/RENNES/EBR_CALIBRATION/"
# Figure folder outputs
res_path = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/15_results/EBR_v1/'
fig_path = res_path + 'out/'

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

dem_name = "BDALTI_75m_EBR.tif" # name of dem
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
    
    # watershed_display.watershed_dem(BV)
    # watershed_display.watershed_local(dem_path, BV)
    
#%% DATA WATERSHED

for site_name in site_names[:]:

    watershed_name = site_name[0]
    code_name = site_name[1]
           
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)

    # BV.add_geology(geology_path)
    # BV.add_hydrology(hydrology_path, types_obs=types_obs, fields_obs=fields_obs)
    # BV.add_oceanic(oceanic_path)
    # BV.add_hydrometry(hydrometry_path)
    # BV.add_intermittency(intermittency_path)
    # BV.add_subbasin()
    # BV.add_surfex(surfex_path)
    BV.add_drias(drias_path)
    # try:
    #     if (watershed_name == 'Monfort') | (watershed_name == 'Roche'):
    #         BV.add_piezometry()
    # except:
    #     pass
        
    print('##### '+watershed_name.upper()+' #####')

    BV.add_hydrodynamic()
    BV.add_forcing()

    watershed_display.watershed_dem(BV)
    watershed_display.watershed_local(dem_path, BV)
    
#%% DATA SURFEX DRIAS

dfd_both = pd.DataFrame()

scenarios = ['RCP2.6','RCP4.5','RCP6.0','RCP8.5']
# models = ['ACC1','BCC1','BNU1','CAN1','CSI1','IPS1','MIR1','NOR1']
models = ['ACC1','BCC1','BNU1','CAN1','CAN2','CAN3','CAN4','CAN5',
            'CNR1','CSI1','IPS1','MIR1','MIR2','MIR3','NOR1']
raws = ['REC', 'RUN', 'ETP', 'PPT', 'TAS']
variables = ['REC', 'RUN', 'ETP', 'PPT', 'TAS', 'EFF']

for watershed_name in ['Frame']:
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
    surfex_data = stable_folder + 'climatic/'

# ppt = pd.read_csv(surfex_data+'_'+'PPT'+'_'+'D'+'.csv', sep=";", index_col=0, parse_dates=True)
# etp = pd.read_csv(surfex_data+'_'+'ETP'+'_'+'D'+'.csv', sep=";", index_col=0, parse_dates=True)
# eff = ppt - etp
# eff = eff.add_prefix('EFF'+'_')

liste = []
for raw in raws :
    dfd = pd.read_csv(surfex_data+'_'+raw+'_'+'D'+'.csv', sep=";", index_col=0, parse_dates=True)
    dfd = dfd.add_prefix(raw+'_')
    liste.append(dfd)
dfd = pd.concat(liste, join='inner', axis=1)
# dfd = pd.concat([dfd,eff], join='inner', axis=1)
dfd = dfd.apply(pd.to_numeric)

for mod in models:
    for sce in ['historic','RCP2.6','RCP4.5','RCP6.0','RCP8.5']:
        try:
            dfd['EFF'+'_'+mod+'_'+sce] = dfd['PPT'+'_'+mod+'_'+sce] - dfd['ETP'+'_'+mod+'_'+sce]
        except:
            pass

for mod in ['REA']:
    for sce in ['historic']:
        try:
            dfd['EFF'+'_'+mod+'_'+sce] = dfd['PPT'+'_'+mod+'_'+sce] - dfd['ETP'+'_'+mod+'_'+sce]
        except:
            pass

for var in ['REC', 'RUN', 'ETP', 'PPT', 'TAS','EFF']:
    for sce in ['historic','RCP2.6','RCP4.5','RCP6.0','RCP8.5']:
        for mod in models:
            if sce == 'historic':
                dfd[var+'_'+mod+'_'+sce][(dfd.index.year)>=2005] = np.nan
            else:
                dfd[var+'_'+mod+'_'+sce][(dfd.index.year)<2005] = np.nan

for var in ['REC', 'RUN', 'ETP', 'PPT', 'TAS','EFF']:
    df_fil = dfd.copy()
    # df_fil = df_fil.filter(regex=('ACC1|BCC1|BNU1|CAN1|CNR1|CSI1|IPS1|MIR1|NOR1'))
    df_fil = df_fil.filter(regex=('ACC1|BCC1|BNU1|CAN1|CAN2|CAN3|CAN4|CAN5|CNR1|CSI1|IPS1|MIR1|MIR2|MIR3|NOR1'))
    for sce in ['historic','RCP2.6','RCP4.5','RCP6.0','RCP8.5']:
        dfb = df_fil.filter(regex=var)
        dfb = dfb.filter(regex=sce)
        dfd[var+'_'+'TOT'+'_'+sce] = np.nanmean(dfb, axis=1)

dfm = dfd.copy() 
mask = dfm.resample("M").count() >= 27
dfm = dfm.resample("M").mean()[mask]

dfm_surf = dfm.copy()
dfm_surf = select_period(dfm_surf, 1960, 2019)
tas = dfm_surf['TAS_REA_historic']
import pyet
dfm_surf['Oudin'] = abs(pyet.oudin(tas, lat=48))
dfm_surf["Hargreaves"] = abs(pyet.hargreaves(tas, tmax=tas.max(), tmin=tas.min(), lat=48))
dfm_surf["Hamon"] = abs(pyet.temperature.hamon(tas, lat=48))
dfm_surf["Macguinness"] = abs(pyet.radiation.mcguinness_bordne(tas, lat=48))
deficiency_evaporation(dfm_surf, 'PPT_REA_historic',
                            'Oudin', 'PPT-ETP',
                            'ETR', 'RU', 'DE')

dfy = dfd.copy()
mask = dfy.resample("Y").count() >= 364
dfy = dfy.resample("Y").mean()[mask]

rea = dfd[(dfd.index.year>=1960) & (dfd.index.year<=2019)].filter(regex='REA')
his = dfd[(dfd.index.year>=1960) & (dfd.index.year<=2004)].filter(regex='historic')
pro = dfd[(dfd.index.year>=2006) & (dfd.index.year<=2099)].filter(regex='RCP')

def sum_hwlw(dfm):
    hw = dfm.dropna(axis=1, how='all')
    hw = dfm.groupby([(dfm.index.year),(dfm.index.month)]).mean()
    hw = hw.rename_axis(["year", "month"])
    hw = hw.query("month == "+"["+'10,11,12,1,2,3'+"]")
    hw = hw.groupby('year').mean()
    hw.index =  pd.to_datetime(hw.index, format='%Y')
    hw[hw==0] = np.nan
    lw = dfm.dropna(axis=1, how='all')
    lw = dfm.groupby([(dfm.index.year),(dfm.index.month)]).mean()
    lw = lw.rename_axis(["year", "month"])
    lw = lw.query("month == "+"["+'4,5,6,7,8,9'+"]")
    lw = lw.groupby('year').mean()
    lw.index =  pd.to_datetime(lw.index, format='%Y')
    lw[lw==0] = np.nan
    return hw, lw
hw, lw = sum_hwlw(dfm)

def sum_wy(dfm):
    wy = dfm.copy()
    wy = wy.dropna(axis=1, how='all')
    wy['wy_y'] = np.where(wy.index.month < 10, wy.index.year, wy.index.year + 1)
    wy['wy_m'] = np.where(wy.index.month < 10, wy.index.month+3, wy.index.month-9)
    wy['wy_m'] = wy['wy_m'].apply(lambda x: '{0:0>2}'.format(x))
    wy['wy_d'] = wy.index.day
    d = pd.to_datetime(wy['wy_y'].astype(str)+wy['wy_m']+wy['wy_d'].astype(str), format='%Y%M%d')
    wy['date'] = wy.index
    wy.index = d
    wy = wy.drop(['wy_y','wy_m','wy_d'], axis=1)
    wy = wy.groupby([(wy.index.year),(wy.index.month)]).mean()
    wy = wy.rename_axis(["year", "month"])
    wy = wy.iloc[:-1]
    wy = wy.groupby('year').mean()
    wy.index =  pd.to_datetime(wy.index, format='%Y')
    wy[wy==0] = np.nan
    return wy
wy = sum_wy(dfm)

both = dfd.copy()

models = ['ECE-RCA','ECE-RAC','HAD-REG','NOR-R15',
          'MPI-CCL','MPI-R09','CNR-RAC','CNR-ALA',
          'IPS-WRF','HAD-CCL','IPS-RCA','NOR-HIR']
        
for watershed_name in ['Frame']:
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
    drias_data = stable_folder+'/'+'drias/'+'_ALL_D.csv'

dfd = pd.read_csv(drias_data, sep=";", index_col=0, parse_dates=True)

for mod in models:
    for sce in ['historic','RCP2.6','RCP4.5','RCP6.0','RCP8.5']:
        try:
            dfd['EFF'+'_'+mod+'_'+sce] = dfd['PPT'+'_'+mod+'_'+sce] - dfd['ETP'+'_'+mod+'_'+sce]
        except:
            pass
        
for var in ['REC', 'RUN', 'ETP', 'PPT', 'TAS', 'EFF']:
    df_fil = dfd.copy()
    df_fil = df_fil.filter(regex=('ECE-RCA|ECE-RAC|HAD-REG|NOR-R15|MPI-CCL|MPI-R09|CNR-RAC|CNR-ALA|IPS-WRF|HAD-CCL|IPS-RCA|NOR-HIR'))
    for sce in ['historic','RCP2.6','RCP4.5','RCP6.0','RCP8.5']:
        dfb = df_fil.filter(regex=var)
        dfb = dfb.filter(regex=sce)
        dfd[var+'_'+'EXP'+'_'+sce] = np.nanmean(dfb, axis=1)

dfm = dfd.copy() 
mask = dfm.resample("M").count() >= 27
dfm = dfm.resample("M").mean()[mask]
        
dfy = dfd.copy()
mask = dfy.resample("Y").count() >= 364
dfy = dfy.resample("Y").mean()[mask]

rea = dfd[(dfd.index.year>=1960) & (dfd.index.year<=2019)].filter(regex='REA')
his = dfd[(dfd.index.year>=1972) & (dfd.index.year<=2004)].filter(regex='historic')
pro = dfd[(dfd.index.year>=2006) & (dfd.index.year<=2099)].filter(regex='RCP')

def sum_hwlw(dfm):
    hw = dfm.dropna(axis=1, how='all')
    hw = dfm.groupby([(dfm.index.year),(dfm.index.month)]).mean()
    hw = hw.rename_axis(["year", "month"])
    hw = hw.query("month == "+"["+'10,11,12,1,2,3'+"]")
    hw = hw.groupby('year').mean()
    hw.index =  pd.to_datetime(hw.index, format='%Y')
    hw[hw==0] = np.nan
    lw = dfm.dropna(axis=1, how='all')
    lw = dfm.groupby([(dfm.index.year),(dfm.index.month)]).mean()
    lw = lw.rename_axis(["year", "month"])
    lw = lw.query("month == "+"["+'4,5,6,7,8,9'+"]")
    lw = lw.groupby('year').mean()
    lw.index =  pd.to_datetime(lw.index, format='%Y')
    lw[lw==0] = np.nan
    return hw, lw
hw, lw = sum_hwlw(dfm)

def sum_wy(dfm):
    wy = dfm.copy()
    wy = wy.dropna(axis=1, how='all')
    wy['wy_y'] = np.where(wy.index.month < 10, wy.index.year, wy.index.year + 1)
    wy['wy_m'] = np.where(wy.index.month < 10, wy.index.month+3, wy.index.month-9)
    wy['wy_m'] = wy['wy_m'].apply(lambda x: '{0:0>2}'.format(x))
    wy['wy_d'] = wy.index.day
    d = pd.to_datetime(wy['wy_y'].astype(str)+wy['wy_m']+wy['wy_d'].astype(str), format='%Y%M%d')
    wy['date'] = wy.index
    wy.index = d
    wy = wy.drop(['wy_y','wy_m','wy_d'], axis=1)
    wy = wy.groupby([(wy.index.year),(wy.index.month)]).mean()
    wy = wy.rename_axis(["year", "month"])
    wy = wy.iloc[:-1]
    wy = wy.groupby('year').mean()
    wy.index =  pd.to_datetime(wy.index, format='%Y')
    wy[wy==0] = np.nan
    return wy
wy = sum_wy(dfm)

both = pd.concat([both, dfd], axis=1)

dfd = both.copy()
dfm = dfd.copy() 
mask = dfm.resample("M").count() >= 27
dfm = dfm.resample("M").mean()[mask]

dfy = dfd.copy()
mask = dfy.resample("Y").count() >= 364
dfy = dfy.resample("Y").mean()[mask]

rea = dfd[(dfd.index.year>=1960) & (dfd.index.year<=2019)].filter(regex='REA')
his = dfd[(dfd.index.year>=1960) & (dfd.index.year<=2004)].filter(regex='historic')
pro = dfd[(dfd.index.year>=2006) & (dfd.index.year<=2099)].filter(regex='RCP')

def sum_hwlw(dfm):
    hw = dfm.dropna(axis=1, how='all')
    hw = dfm.groupby([(dfm.index.year),(dfm.index.month)]).mean()
    hw = hw.rename_axis(["year", "month"])
    hw = hw.query("month == "+"["+'10,11,12,1,2,3'+"]")
    hw = hw.groupby('year').mean()
    hw.index =  pd.to_datetime(hw.index, format='%Y')
    hw[hw==0] = np.nan
    lw = dfm.dropna(axis=1, how='all')
    lw = dfm.groupby([(dfm.index.year),(dfm.index.month)]).mean()
    lw = lw.rename_axis(["year", "month"])
    lw = lw.query("month == "+"["+'4,5,6,7,8,9'+"]")
    lw = lw.groupby('year').mean()
    lw.index =  pd.to_datetime(lw.index, format='%Y')
    lw[lw==0] = np.nan
    return hw, lw
hw, lw = sum_hwlw(dfm)

def sum_wy(dfm):
    wy = dfm.copy()
    wy = wy.dropna(axis=1, how='all')
    wy['wy_y'] = np.where(wy.index.month < 10, wy.index.year, wy.index.year + 1)
    wy['wy_m'] = np.where(wy.index.month < 10, wy.index.month+3, wy.index.month-9)
    wy['wy_m'] = wy['wy_m'].apply(lambda x: '{0:0>2}'.format(x))
    wy['wy_d'] = wy.index.day
    d = pd.to_datetime(wy['wy_y'].astype(str)+wy['wy_m']+wy['wy_d'].astype(str), format='%Y%M%d')
    wy['date'] = wy.index
    wy.index = d
    wy = wy.drop(['wy_y','wy_m','wy_d'], axis=1)
    wy = wy.groupby([(wy.index.year),(wy.index.month)]).mean()
    wy = wy.rename_axis(["year", "month"])
    wy = wy.iloc[:-1]
    wy = wy.groupby('year').mean()
    wy.index =  pd.to_datetime(wy.index, format='%Y')
    wy[wy==0] = np.nan
    return wy
wy = sum_wy(dfm)

#%% TEST DATA

ztest = dfd.resample('Y').sum()
ztest = ztest.filter(regex='PPT')
# ztest = ztest.filter(regex='PPT')

#%% DATA MAP

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

#%% 0 - COMPAR BILAN

def legend_without_duplicate_labels(ax):
    handles, labels = ax.get_legend_handles_labels()
    unique = [(h, l) for i, (h, l) in enumerate(zip(handles, labels)) if l not in labels[:i]]
    ax.legend(*zip(*unique), bbox_to_anchor=(1.1,0.5), prop={'size': 7}, loc="center left", 
              borderaxespad=0)

models = [
          'ECE-RCA','ECE-RAC','HAD-REG','NOR-R15', # Pessimistic
          'MPI-CCL','MPI-R09','CNR-ALA','CNR-RAC'] # Optimistic

# models = ['REA']

couleurs = [
            'red','darkorange','gold','orchid',
            'forestgreen','yellowgreen','dodgerblue','blue']

# models = ['ECE-RCA','NOR-R15','HAD-REG','ECE-RAC'] # Pessimistic
# models = ['MPI-CCL','CNR-RAC','CNR-ALA','MPI-R09'] # Optimistic

color_dict = dict(zip(models, couleurs))
# models = ['HAD-REG']

# mod = 'REA'
# mod = 'HAD-REG'
# sce = 'historic'
var = 'REC'
per = [1960,2019]
cond = 0

scenar = 'RCP2.6'

fig, ax = plt.subplots(1,1, figsize=(3,3))
# axb = ax.twinx()

# ax.set_ylabel('Recharge anomaly \n 2070-2100 vs 2010-2040 [%]', fontsize=12)
# ax.set_ylabel('Recharge anomaly \n 2070-2100 vs 2010-2040 [%]', fontsize=12)

for mod in models:

    for scenar in [ 'RCP2.6',  'RCP8.5']:

        if mod == 'REA':
            sce = 'historic'
            his = dfd[(dfd.index.year>=1960) & (dfd.index.year<=2019)].filter(regex='historic')
        else:
            sce = scenar
            his = dfd[(dfd.index.year>=1972) & (dfd.index.year<=2005)].filter(regex='historic')
        pro = dfd[(dfd.index.year>=2005) & (dfd.index.year<=2098)].filter(regex='RCP')
        
        d = pd.concat((pro.filter(regex=var+'_'+mod+'_'+sce),
                       his.filter(regex=var+'_'+mod+'_'+'historic')), axis=1).mean(axis=1)
        # d = d*365
        
        d.columns = ['values']
        d = d.round(2).squeeze().to_frame()
        d['month'] = d.index.month
        d.columns = ['values','month']
        
        d_lw = d.query("month == "+"["+'5,6,7,8,9,10'+"]") # 4,5,6,7,8,9,10,11
        d_hw = d.query("month == "+"["+'11,12,1,2,3,4'+"]") # 10,11,12,1,2,3,4
        
        if scenar == 'RCP2.6':
            poss = [0.5,1,1.5]
            ax=ax
        if scenar == 'RCP8.5':
            poss = [2.5,3,3.5]
            # ax = axb
            
        ax.plot(poss[0],
                (select_period(d, 2070, 2098).values.mean()-
                select_period(d, 2010, 2040).values.mean())/
                select_period(d, 2010, 2040).values.mean() * 100, marker='s', lw=0, mec=color_dict[mod],
                mew=2, ms=10, mfc='none', label=mod)
        # ax.legend()
        # ax.set_title('ALL')
        # ax.set_ylim(-1, 5)
        
        ax.plot(poss[1],
                (select_period(d_hw, 2070, 2098).values.mean()-
                select_period(d_hw, 2010, 2040).values.mean())/
                select_period(d_hw, 2010, 2040).values.mean() * 100, marker='s', lw=0, mec=color_dict[mod],
                mew=2, ms=10, mfc='none', label=mod)
        # ax.legend()
        # ax.set_title('HW')
        ax.set_ylim(-2, 6)
        
        # ax = axs[2]
        ax.plot(poss[2],
                (select_period(d_lw, 2070, 2098).values.mean()-
                select_period(d_lw, 2010, 2040).values.mean())/
                select_period(d_lw, 2010, 2040).values.mean() * 100, marker='s', lw=0, mec=color_dict[mod],
                mew=2, ms=10, mfc='none', label=mod)
        # ax.set_title('LW')
        ax.set_xlim(0,4)
        # ax.set_xticks([0,0.5,1])
        ax.set_xticklabels([' '])
        ax.axhline(0, color='k', zorder=-10)
        ax.axvline(x=2, c='k')
        
# legend_without_duplicate_labels(ax)
handles, labels = plt.gca().get_legend_handles_labels()
by_label = dict(zip(labels, handles))
leg=ax.legend(by_label.values(), by_label.keys(), loc='upper left', prop={'size': 6.5},
          fontsize=5, frameon=True)
for i in range(8):
    leg.legendHandles[i]._legmarker.set_markersize(6)

plt.tight_layout()

fig.savefig(fig_path + 'compar_models_recharge_bilan' + '.png', dpi=300, bbox_inches='tight')

#%% 0 - COMPAR EVOL

time_step = 'M'

variables = ['REC']
scenarios = ['historic','RCP8.5']

models = [
          'ECE-RCA','ECE-RAC','HAD-REG','NOR-R15', # Pessimistic
          'MPI-CCL','MPI-R09','CNR-ALA','CNR-RAC'] # Optimistic

# models = ['REA']

couleurs = [
            'red','darkorange','gold','orchid',
            'forestgreen','yellowgreen','dodgerblue','blue']

color_dict = dict(zip(models, couleurs))

seasons = ['9,10,11',
           '12,1,2',
           '3,4,5',
           '6,7,8']
string = ['SON','DJF','MAM','JJA']
seas_dict = dict(zip(seasons, string))

space = 10

for var in variables:
    fig, axs = plt.subplots(2,2, figsize=(10,5))
    axs = axs.ravel()
    
    df_fil = dfd.copy()
    df_fil = df_fil.resample('M').mean()

    for i, sea in enumerate(seasons):
        ax = axs[i]
        for sce in scenarios:
            for mod in models:
                dfb = df_fil.filter(regex=var)
                dfb = dfb.filter(regex=sce)
                dfb = dfb.filter(regex=mod)
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
                # dfb = dfb.dropna()
                dfb = dfb.groupby('year').apply(lambda g: g.sum(skipna=False))
                dfb.index =  pd.to_datetime(dfb.index, format='%Y')
                
                dfs = pd.DataFrame(index=dfb.index)
                
                dfb = dfb.rolling(window=space).mean() # .shift(-space)
                
                # ax.plot(dfb, lw=0.1, color=color_dict[sce])
                dfs['MEAN'] = np.nanmean(dfb, axis=1)
                dfs['MIN'] = dfb.min(axis=1)
                dfs['MAX'] = dfb.max(axis=1)
                dfs['Q25'] = dfb.quantile(q=0.25, axis=1)
                dfs['Q50'] = dfb.quantile(q=0.50, axis=1)
                dfs['Q75'] = dfb.quantile(q=0.75, axis=1)
                dfs['STD'] = dfb.std(axis=1)
                dfs = dfs.iloc[1:-1]
                
                # dfs = dfs.rolling(window=space).mean().shift(-space)
                
                # ax.plot(rea, ls='-', color='k', lw=0.25)
                ax.fill_between(dfs.index, dfs['Q25'], dfs['Q75'], color=color_dict[mod], alpha=0.2, edgecolor='none')
                # ax.plot(dfs['Q50'], lw=1, color=color_dict[sce], label=sce)
                # ax.fill_between(dfs.index, dfs.MEAN-dfs['STD'], dfs.MEAN+dfs['STD'], color=color_dict[sce], alpha=0.2, edgecolor='none')
                ax.plot(dfs['Q50'], lw=2, color=color_dict[mod], label=sce)
                ax.set_xlim(pd.to_datetime('1960'), pd.to_datetime('2100'))
                ax.set_title(seas_dict[sea])
                # ax.legend(loc='upper left')
                # ax.axvline(pd.to_datetime('2010'), color='k', ls='--')
                from datetime import date
                ax.axvline(date.today(), color='k', ls='--')
                
                # ax.axvline(dfs.first_valid_index(), color='grey', ls='-', lw=0.1)
                # ax.axvline(dfs.last_valid_index(), color='grey', ls='-', lw=0.1)
                # ax.text(dfs.first_valid_index(),0.8, str(dfs.first_valid_index().year), rotation=90,
                #         transform=ax.get_xaxis_transform())
                
                fig.suptitle(var)
                plt.tight_layout()
                
    fig.savefig(fig_path + 'compar_models_recharge_evol_' + sce + '.png', dpi=300, bbox_inches='tight')

#%% 1 - BASE MAP

dem_fig = False
geol_fig = True

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

if dem_fig == True:
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

if geol_fig == True:
    geol_f.plot(ax=ax, color=list(geol_f['hex']), alpha=0.5, edgecolor='none', zorder=0)
    geol_s.plot(ax=ax, color='dimgrey', alpha=0.5, edgecolor='dimgrey', zorder=0)

#%% 1 - BASE CLIMAT

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
    ax.set_title(var.upper())
    
    fig.savefig(fig_path + var + '.png', dpi=300, bbox_inches='tight')

#%% 1 - CLIMAR OBS

file = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/15_results/EBR_v1/_data/climatic/Station météorologique de Rennes.csv'
raw = pd.read_csv(file, names = ['date','tx','tn','tm','p','pre','e'], 
                                         sep=';', 
                                         header = None,
                                         parse_dates=True,
                                         decimal=".")
raw_data = raw.apply(lambda x: x.str.replace(',','.'))
time = pd.to_datetime(raw_data['date'])
time = time.sort_values()
time_index = pd.DatetimeIndex(time)
raw_tx = pd.Series(raw_data['tx'])
tx = pd.to_numeric(raw_tx, errors='coerce')
raw_tn = pd.Series(raw_data['tn'])
tn = pd.to_numeric(raw_tn, errors='coerce')
raw_tm = pd.Series(raw_data['tm'])
tm = pd.to_numeric(raw_tm, errors='coerce')
raw_p = pd.Series(raw_data['p'])
p = pd.to_numeric(raw_p, errors='coerce')
raw_pre = pd.Series(raw_data['pre'])
pre = pd.to_numeric(raw_pre, errors='coerce')
raw_e = pd.Series(raw_data['e'])
e = pd.to_numeric(raw_e, errors='coerce')

data_raw = pd.DataFrame({'date':time_index,
                     'tx':tx,
                     'tn':tn,
                     'tm':tm,
                     'p':p,
                     'pre':pre,
                     'e':e})

data_index = data_raw.set_index(['date'])

ref = data_index.loc['1980-01-01':'2010-01-01','tm']
ref_mean = ref.mean()
mean_years = data_index.tm.resample('Y').mean()
anomaly = mean_years-ref_mean
anomaly = anomaly.to_frame()
anomaly['year'] = anomaly.index
anomaly['year'] = anomaly.year.dt.year

fig, ax = plt.subplots(figsize=(6,4)) # size figure

anomaly_plus = anomaly[anomaly.tm >= 0]
anomaly_minus = anomaly[anomaly.tm < 0]

ax.bar(anomaly_plus.year, anomaly_plus['tm'], width=1, align='center',
       color='red')
ax.bar(anomaly_minus.year, anomaly_minus['tm'], width=1, align='center',
       color='dodgerblue')

plt.xticks(rotation='horizontal')
plt.xlabel('Date')
plt.ylabel('Temperature anomaly [°C]')
# plt.title('Station météorologique de Rennes')

xmin = 1950
xmax = 2020
ymin = -1.8
ymax = +2
plt.xlim(xmin, xmax)
plt.ylim(ymin,ymax)
space = 10
plt.xticks(np.arange(xmin,xmax+1,space), list((np.arange(xmin,xmax+1,space))), 
           rotation='horizontal')
# plt.xticklabels(np.arange(0,2020+1,10))

plt.hlines(0,xmin,xmax, color='k')
plt.grid(True)
plt.tight_layout()

fig.savefig(fig_path + '_clim/_temp_obs' + '.png', dpi=300, bbox_inches='tight')


ref = data_index.loc['1980-01-01':'2010-01-01','p']
ref_mean = ref.mean()
mean_years = data_index.p.resample('Y').mean()
anomaly = mean_years-ref_mean
anomaly = anomaly.to_frame()
anomaly['year'] = anomaly.index
anomaly['year'] = anomaly.year.dt.year

fig, ax = plt.subplots(figsize=(6,4)) # size figure

anomaly_plus = anomaly[anomaly.p >= 0]
anomaly_minus = anomaly[anomaly.p < 0]

ax.bar(anomaly_plus.year, anomaly_plus['p']*365, width=1, align='center',
       color='forestgreen')
ax.bar(anomaly_minus.year, anomaly_minus['p']*365, width=1, align='center',
       color='darkorange')

plt.xticks(rotation='horizontal')
plt.xlabel('Date')
plt.ylabel('Precipitation anomaly [mm/y]')
# plt.title('Station météorologique de Rennes')

xmin = 1950
xmax = 2020
ymin = -240
ymax = +250
plt.xlim(xmin, xmax)
plt.ylim(ymin,ymax)
space = 10
plt.xticks(np.arange(xmin,xmax+1,space), list((np.arange(xmin,xmax+1,space))), 
           rotation='horizontal')
# plt.xticklabels(np.arange(0,2020+1,10))

plt.hlines(0,xmin,xmax, color='k')
plt.grid(True)
plt.tight_layout()

fig.savefig(fig_path + '_clim/_ppt_obs' + '.png', dpi=300, bbox_inches='tight')

# import pandex
# pd.ext.import_extension('github:connectedblue/pdext_collection -> heat_stripes')
# anomaly = anomaly.reset_index()
# fig = anomaly.ext.heat_stripes('tm', clim=0.7)

#%% 1 - CLIMAT BILAN

df_intm = dfd.resample('M').mean()[dfd.resample("M").count() >= 27]
df_intm = df_intm.groupby([lambda x: x.month]).mean()

fig, ax = plt.subplots(1,1, figsize=(4,4))
axt = ax.twinx()
# ax.bar(df_intm.index, df_intm['PPT_REA_historic']*30, color='skyblue', width=0.5, lw=0, zorder=0)
ax.plot(df_intm.index, df_intm['PPT_REA_historic']*30, marker='o', ms=0,
          color='blue', lw=3, zorder=5)
# ax.plot(df_intm.index, (df_intm['PPT_REA_historic']*30) - (df_intm['ETP_REA_historic']*30), marker='o', ms=5,
#         color='magenta', lw=3, zorder=2)
axt.plot(df_intm.index, df_intm['TAS_REA_historic'], marker='o', ms=0,
         color='red', lw=3, zorder=0)
axt.set_ylim(0,30)
# ax.fill_between(df_intm.index, df_intm['PPT_REA_historic']*30, df_intm['ETP_REA_historic']*30, color='forestgreen',
#                 alpha=0.5, zorder=1)
ax.fill_between(df_intm.index, np.ma.masked_array(df_intm['ETP_REA_historic']*30,
                                            mask=(df_intm['PPT_REA_historic']-df_intm['ETP_REA_historic'])>0),
                               np.ma.masked_array(df_intm['PPT_REA_historic']*30,
                                            mask=(df_intm['PPT_REA_historic']-df_intm['ETP_REA_historic'])>0),
                color='forestgreen',
                alpha=0.5, interpolate=True, zorder=1)
ax.fill_between(df_intm.index, np.ma.masked_array(df_intm['PPT_REA_historic']*30,
                                            mask=(df_intm['PPT_REA_historic']-df_intm['ETP_REA_historic'])<0),
                               np.ma.masked_array(df_intm['ETP_REA_historic']*30,
                                            mask=(df_intm['PPT_REA_historic']-df_intm['ETP_REA_historic'])<0),
                color='dodgerblue',
                alpha=0.5, interpolate=True, zorder=1)
# ax1.fill_between(df_intm.index,, df_intm['ETP_REA_historic']*30, y2, where=y2 <= y1,
#                  facecolor='red', interpolate=True)
ax.plot(df_intm.index, df_intm['ETP_REA_historic']*30, color='forestgreen', lw=3, 
        marker='o', ms=0, zorder=2)
ax.plot(df_intm.index, (df_intm['RUN_REA_historic']*30), color='darkorange', lw=3, marker='o', ms=0, 
                        zorder=2)
ax.plot(df_intm.index, (df_intm['REC_REA_historic']*30), color='purple', lw=3, marker='o', ms=0, 
                        zorder=2)
ax.set_xticks(np.arange(1,13,1))
ax.set_xticklabels(['J','F','M','A','M','J','J','A','S','O','N','D'])
ax.set_xlim(1,12)
ax.set_ylim(0,120)
fig.savefig(fig_path + 'ombro_bilan_intermensual' + '.png', dpi=300, bbox_inches='tight')

#%% 1 - DEFICIENCY EVAP

var = 'DE'

df = dfd.copy()
df = select_period(df, 1960, 2019)

dfm = df.resample('M').mean()#.groupby([lambda x: x.month]).mean()

dfm_surf = dfm.copy()
dfm_surf = select_period(dfm_surf, 1960, 2019)
tas = dfm_surf['TAS_REA_historic']
import pyet
dfm_surf['Oudin'] = abs(pyet.oudin(tas, lat=48))
dfm_surf["Hargreaves"] = abs(pyet.hargreaves(tas, tmax=tas.max(), tmin=tas.min(), lat=48))
dfm_surf["Hamon"] = abs(pyet.temperature.hamon(tas, lat=48))
dfm_surf["Macguinness"] = abs(pyet.radiation.mcguinness_bordne(tas, lat=48))
deficiency_evaporation(dfm_surf, 'PPT_REA_historic',
                            'Oudin', 'PPT-ETP',
                            'ETR', 'RU', 'DE')

dfm = dfm_surf.copy()

wy = dfm.copy()
wy = wy.dropna(axis=1, how='all')
wy['wy_y'] = np.where(wy.index.month < 10, wy.index.year, wy.index.year + 1)
wy['wy_m'] = np.where(wy.index.month < 10, wy.index.month+3, wy.index.month-9)
wy['wy_m'] = wy['wy_m'].apply(lambda x: '{0:0>2}'.format(x))
wy['wy_d'] = wy.index.day
d = pd.to_datetime(wy['wy_y'].astype(str)+wy['wy_m']+wy['wy_d'].astype(str), format='%Y%M%d')
wy['date'] = wy.index
wy.index = d
wy = wy.drop(['wy_y','wy_m','wy_d'], axis=1)
wy = wy.groupby([(wy.index.year),(wy.index.month)]).mean()
wy = wy.rename_axis(["year", "month"])
wy = wy.iloc[:-1]
wy = wy.groupby('year').mean()
wy.index =  pd.to_datetime(wy.index, format='%Y')
wy[wy==0] = 0

tot = dfm.dropna(axis=1, how='all')
tot = dfm.groupby([(dfm.index.year),(dfm.index.month)]).mean()
tot = tot.rename_axis(["year", "month"])
tot = tot.query("month == "+"["+'1,2,3,4,5,6,7,8,9,10,11,12'+"]")
tot = tot.groupby('year').sum()
tot.index =  pd.to_datetime(tot.index, format='%Y')
tot[tot==0] = 0

hw = dfm.dropna(axis=1, how='all')
hw = dfm.groupby([(dfm.index.year),(dfm.index.month)]).mean()
hw = hw.rename_axis(["year", "month"])
hw = hw.query("month == "+"["+'10,11,12'+"]")
hw = hw.groupby('year').sum()
hw.index =  pd.to_datetime(hw.index, format='%Y')
hw[hw==0] = 0

hw2 = dfm.dropna(axis=1, how='all')
hw2 = dfm.groupby([(dfm.index.year),(dfm.index.month)]).mean()
hw2 = hw2.rename_axis(["year", "month"])
hw2 = hw2.query("month == "+"["+'1,2,3'+"]")
hw2 = hw2.groupby('year').sum()
hw2.index =  pd.to_datetime(hw2.index, format='%Y')
hw2[hw2==0] = 0

lw = dfm.dropna(axis=1, how='all')
lw = dfm.groupby([(dfm.index.year),(dfm.index.month)]).mean()
lw = lw.rename_axis(["year", "month"])
lw = lw.query("month == "+"["+'4,5,6'+"]")
lw = lw.groupby('year').sum()
lw.index =  pd.to_datetime(lw.index, format='%Y')
lw[lw==0] = 0

lw2 = dfm.dropna(axis=1, how='all')
lw2 = dfm.groupby([(dfm.index.year),(dfm.index.month)]).mean()
lw2 = lw2.rename_axis(["year", "month"])
lw2 = lw2.query("month == "+"["+'7,8,9'+"]")
lw2 = lw2.groupby('year').sum()
lw2.index =  pd.to_datetime(lw2.index, format='%Y')
lw2[lw2==0] = 0


fig, ax = plt.subplots(1,1,figsize=(7, 3))
ax.step(wy.index, wy.DE*365, color='k', lw=2, alpha=0.6, where='mid')
# ax.step(tot.index, tot.DE*30, color='k', lw=2, alpha=0.6, where='mid')
ax.step(hw2.index, hw2.DE*30, color='dodgerblue', lw=2, alpha=0.6, where='mid')
ax.step(hw.index, hw.DE*30, color='darkorange', lw=2, alpha=0.6, where='mid')
ax.step(lw.index, lw.DE*30, color='forestgreen', lw=2, alpha=0.6, where='mid')
ax.step(lw2.index, lw2.DE*30, color='red', lw=2, alpha=0.6, where='mid')
# ax.bar(hw.index, hw.DE*30, color='darkorange', width=350, lw=0.5, alpha=0.5)
# ax.bar(hw2.index, hw2.DE*30, color='dodgerblue', width=350, lw=0.5, alpha=0.5)
# ax.bar(lw.index, lw.DE*30, color='forestgreen', width=350, lw=0.5, alpha=0.5)
# ax.bar(lw2.index, lw2.DE*30, color='red', width=350, lw=0.5, alpha=0.5)
# ax.plot(hw.index, hw.DE*30, color='darkorange', lw=2, alpha=1)
# ax.plot(hw2.index, hw2.DE*30, color='dodgerblue', lw=2, alpha=1)
# ax.plot(lw.index, lw.DE*30, color='forestgreen', lw=2, alpha=1)
# ax.plot(lw2.index, lw2.DE*30, color='red', lw=2, alpha=1)
ax.set_xlim(pd.to_datetime('1960'), pd.to_datetime('2019'))
ax.set_ylabel('Evaporation \n deficiency [mm/month]')
ax.set_ylim(1, 600)
import matplotlib.dates as mdates
years = mdates.YearLocator(10)   # every year
years_min = mdates.YearLocator(1)   # every year
years_fmt = mdates.DateFormatter('%Y')
ax.xaxis.set_major_locator(years)
ax.xaxis.set_major_formatter(years_fmt)
ax.xaxis.set_minor_locator(years_min)
ax.grid(alpha=0.25, zorder=-1)

center_x,center_y, slope, intercept, r_value, p_value, std_err, lenght_reg = linregress(range(len(wy)), wy.DE*365)
plt.plot(wy.index, (np.arange(0,len(wy),1) * slope)+intercept, c='k', ls='--', lw=2)

# for date in ['1976', '1989', '1990', '2003', '2005', '2006', '2017', '2018', '2019']:
# for date in ['1976', '1989', '1990', '2003']:
#     ax.axvline(pd.to_datetime(date), c='k', zorder=-1000, ls='--', lw=1)

fig.savefig(fig_path + 'evaporation_deficiency_historic' + '.png', dpi=300, bbox_inches='tight')

#%% 1 - CLIMAT RENNES

df_intm = dfd.resample('M').mean()[dfd.resample("M").count() >= 27]
# df_intm10 = dfd.groupby([lambda x: x.month]).quantile(0.1)
# df_intm90 = dfd.groupby([lambda x: x.month]).quantile(0.9)
df_intm = df_intm.groupby([lambda x: x.month]).mean()

fig, ax = plt.subplots(1,1, figsize=(4,4))
axt = ax.twinx()
ax.bar(df_intm.index, df_intm['PPT_REA_historic']*30, color='deepskyblue', 
       width=1, alpha=0.7, zorder=0, lw=0, ec='navy')
df_intm['TAS_REA_historic']
axt.plot(df_intm.index, df_intm['TAS_REA_historic'], marker='o', ms=0, mew=1.5, mec='darkred',
         color='red', lw=4)
# axt.fill_between(df_intm.index, df_intm10['TAS_REA_historic'], df_intm90['TAS_REA_historic'], color='salmon',
#                   alpha=1, interpolate=True)
axt.set_ylim(0,50)
ax.set_xticks(np.arange(1,13,1))
ax.set_xticklabels(['J','F','M','A','M','J','J','A','S','O','N','D'])
ax.set_xlim(0.5,12.5)
ax.set_ylim(0,100)
axt.set_yticks([0,10,20,30,40])
ax.axhline((df_intm['PPT_REA_historic']*30).mean(), color='blue', lw=2, ls='--')
axt.axhline((df_intm['TAS_REA_historic']).mean(), color='darkred', lw=2, ls='--')
ax.set_xlabel('Mois')
ax.set_ylabel('Précipitations [mm/mois]', color='blue')
axt.set_ylabel('Température [°C]', color='red', rotation=270, labelpad=28)

fig.savefig(fig_path + 'ombro_simple_intermensual' + '.png', dpi=300, bbox_inches='tight')

#%% 1 - INTERMENSUAL EVOL

var = 'REC'

df = dfd.copy()
df = select_period(df, 1960, 2019)

fig, ax = plt.subplots(1,1,figsize=(5, 3))
fig.add_subplot(111, frameon=False)
plt.tick_params(labelcolor='none', top=False, bottom=False, left=False, 
                right=False) # hide tick and tick label of the big axis
# plt.xlabel("Months", labelpad=+15)
# plt.ylabel("Water volume [mm/mois]", labelpad=+20)
# plt.xlabel("Mois", labelpad=+15)
# plt.ylabel("Volume d'eau [mM3", labelpad=+25)
 # [Mm$^3$]

intm = df.resample('M').sum()#.groupby([lambda x: x.month]).mean()
intm = intm.groupby([lambda x: x.month]).mean()

move = df.copy()
move['year'] = move.index.year
move['month'] = move.index.month

need = move.copy()
yearly = need.groupby([(need.index.month),(need.index.to_period("Y"))]).sum()

rol = True
space = 10

dictio = {}
for per in range(1,12+1):
    dictio[per] = yearly[yearly.index.get_level_values(0) == per]
    dictio[per] = dictio[per].copy()
    if rol == True :
        dictio[per] = dictio[per].rolling(window=space).mean().shift()
        dictio[per]['year'] = (dictio[per].index.get_level_values(1).year).astype(int)
        dictio[per]['bef'] = dictio[per].year - space
        dictio[per]['per'] = dictio[per].bef.astype(str) + '-' + dictio[per].year.astype(str)
    else:
        space = 0
        dictio[per]['year'] = (dictio[per].index.get_level_values(1).year).astype(int)
        dictio[per]['bef'] = dictio[per].year
        dictio[per]['per'] = (dictio[per].index.get_level_values(1).year).astype(str)

df_list = [ v for k,v in dictio.items()] 
df_rol = pd.concat(df_list ,axis=0)
df_rol = df_rol.set_index(['year'])

f = 1960
l = 2019
df = select_period(df, f, l)
# df = df.dropna()
dates = np.arange(f+space,l+1,1)
n = len(dates)
cmap = cm.get_cmap('jet', n)
# cmaplist = ['cyan','red']
# cmap = mpl.colors.LinearSegmentedColormap.from_list(
#     'Custom cmap', cmaplist)
# cmap = cm.get_cmap(c, n)

# df_slice = df.copy()
# df_slice['month'] = df_slice.index.month

df_slice = df_rol.copy()

# piez['day'] = piez.index.dayofyear.values
# # piez['month'] = piez.index.month.values
# piez['year'] = piez.index.year.values # group by month and year, get the average
# piez = piez.groupby(['day','year']).apply(lambda g: g.mean(skipna=False))
# # piez = piez.groupby(['month','year']).apply(lambda g: g.mean(skipna=False))
# piez = piez.unstack(level=0, fill_value=np.nan)
# piez['MEAN'] = piez.mean(axis=1)

compt=0
# for k in range(compt+1):
for k in range(len(dates)):
    date = dates[k]
    # df_per = df_slice[df_slice.index.year==date]
    # df_per.index = df_per.index.astype(int)
    # df_per = df_per.reset_index()
    # df_per['month']= df_per['index']
    df_per = df_slice[df_slice.index==date] #.groupby(['month']).mean()
    df_per = df_per.reset_index()
    # df_per['month'] = df_per['month'].replace(
    #                                     [10,11,12,1,2,3,4,5,6,7,8,9],
    #                                     [1,2,3,4,5,6,7,8,9,10,11,12])
    df_per = df_per.sort_values(['month'])
    df_per = df_per.set_index('month')
    df_per = df_per.append(df_per.iloc[[0]])
    df_per.index = np.arange(1,14,1)
    datetxt = str(df_per.bef.iloc[0]) + '-' + str(date)
    # ax.plot(df_per.cheze_m3/1e6 + df_per.prelevcheze_m3/1e6,  color=cmap(k), lw=2, marker=None, markersize=5, label=datetxt)
    # ax.plot(df_per.prelevcheze_m3/1e6,  color=cmap(k), lw=2, marker=None, markersize=5, label=datetxt)
    # ax.plot(df_per.cheze_m3/1e6,  color=cmap(k), lw=2, marker=None, markersize=5, label=datetxt)
    # val = df_per.cheze_m3/1e6
    # val = df_per.cheze_m3/1e6 + df_per.prelevcheze_m3/1e6
    # val = df_per.cheze_m3/1e6 - df_per.frommeu_m3/1e6 - df_per.fromcanut_m3/1e6
    # df_cum = df_per.cumsum()
    val = df_per[var+'_REA_historic'] 
    ax.plot(val, color=cmap(k), lw=1, marker=None, markersize=5, label=datetxt)
    # ax.axvline(x=val.index[val==val.min()][0], color=cmap(k))
    # ax.plot(df_per.corec_m3, color=cmap(i), lw=2, marker=None, markersize=5, label=datetxt)
    # ax.legend(bbox_to_anchor=(1.05, 0.45), loc='center left', frameon=False)
    ax.yaxis.set_major_formatter(ScalarFormatter())
    ax.set_xlim(1,12)
    ax.set_ylim(0.5,100)
    # ax.axhline(y=14, ls='--', c='k')
    ax.set_yscale('log')
    # ax.ticklabel_format(axis='y', style='plain')
    ax.tick_params(axis='both', which='major', pad=10)
    x1 = np.arange(1,12+1,1)
    # squad = ['O','N','D','J','F','M','A',
    #           'M','J','J','A','S']
    squad = ['J','F','M','A','M','J','J','A','S','O','N','D']
    ax.set_xticks(x1)
    ax.set_xticklabels(squad, minor=False, rotation='horizontal')
    # ax.grid(True)
compt +=1

ax.plot(intm[var+'_REA_historic'], color='k', lw=3, marker=None, markersize=5, label=datetxt)

# ax.legend(bbox_to_anchor=(1.05, 0.50), loc='center left',
#           frameon=True, prop={'size': 6.8})

fig.savefig(fig_path + '_clim' + 
            '_interm_' + var + '.png', dpi=300, bbox_inches='tight')

#%% 1 - EVOL DAYS MONTHLY REA

from matplotlib.ticker import ScalarFormatter

var = 'ETP'
sign = '>'
cond = 0.90

# var = 'REC'
# sign = '<'
# cond = 0.10

mod = 'REA'
sce = 'historic'
ref = [1960,2019]

freq = dfd.copy()
freq = freq.filter(regex=mod)
freq = freq.dropna(axis=0, how='all')

freq[var+'<'+str(0)] = (freq[var+'_'+mod+'_'+sce].round(3) <= 0.1).astype(int)
quant = 0.10
freq[var+'>'+str(quant)] = (freq[var+'_'+mod+'_'+sce].round(3) > freq[var+'_'+mod+'_'+sce]
                            .round(3).quantile(quant))#.astype(int)
freq[var+'<'+str(quant)] = (freq[var+'_'+mod+'_'+sce].round(3) <= freq[var+'_'+mod+'_'+sce]
                            .round(3).quantile(quant))#.astype(int)
quant = 0.90
freq[var+'<'+str(quant)] = (freq[var+'_'+mod+'_'+sce].round(3) < freq[var+'_'+mod+'_'+sce]
                            .round(3).quantile(quant))#.astype(int)
freq[var+'>'+str(quant)] = (freq[var+'_'+mod+'_'+sce].round(3) >= freq[var+'_'+mod+'_'+sce]
                            .round(3).quantile(quant))#.astype(int)

freq = freq[(freq.index.year >= ref[0]) & (freq.index.year <= ref[1])]
# df_new = df_new[['counts1','counts2']]
group = freq.groupby([(freq.index.year),(freq.index.month)]).sum()

space = 10

dictio = {}
for per in range(1,12+1):
    dictio[per] = group[group.index.get_level_values(1) == per]
    if space > 0:
        dictio[per] = dictio[per].rolling(window=space).mean().shift()
        dictio[per]['year'] = (dictio[per].index.get_level_values(0)).astype(int)
        dictio[per]['month'] = (dictio[per].index.get_level_values(1)).astype(int)
        dictio[per]['bef'] = dictio[per].year - space
        dictio[per]['per'] = dictio[per].bef.astype(str) + '-' + dictio[per].year.astype(str)
    else:
        # dictio[per] = dictio[per].mean().shift()
        dictio[per]['year'] = (dictio[per].index.get_level_values(0)).astype(int)
        dictio[per]['month'] = (dictio[per].index.get_level_values(1)).astype(int)
        dictio[per]['bef'] = dictio[per].year
        dictio[per]['per'] = dictio[per].bef.astype(str) + '-' + dictio[per].year.astype(str)
        
df_list = [v for k,v in dictio.items()]
df_rol = pd.concat(df_list ,axis=0)
df_rol = df_rol.set_index(['year'])

df_slice = df_rol[(df_rol.index >= ref[0]+space) & (df_rol.index <= ref[1])]

fig, ax = plt.subplots(1,1,figsize=(5, 3))
fig.add_subplot(111, frameon=False)
plt.tick_params(labelcolor='none', top=False, bottom=False, left=False, right=False) # hide tick and tick label of the big axis
# plt.xlabel("Months")
# plt.ylabel("Day counts")
axb = ax.twinx()

dates = np.arange(ref[0]+space,ref[1]+1,1)
n = len(dates)
cmap1 = cm.get_cmap('jet', n)
cmap2 = cm.get_cmap('autumn', n)
leg = []

data_f = pd.DataFrame()

compt = 0
for k in range(len(dates)):
    date = dates[k]
    df_per = df_slice[df_slice.index==date].groupby(['month']).mean()
    df_per = df_per.reset_index()
    # df_per['month'] = df_per['month'].replace(
    #                                     [10,11,12,1,2,3,4,5,6,7,8,9],
    #                                     [1,2,3,4,5,6,7,8,9,10,11,12])
    df_per = df_per.sort_values(['month'])
    df_per = df_per.set_index('month')
    # df_per = df_per.append(df_per.iloc[[0]])
    # df_per.index = np.arange(1,14,1)
    
    datetxt = str(int(df_per.bef.iloc[0])) + '-' + str(int(date))
    val1 = df_per[var+sign+str(cond)]
    ax.plot(val1, color=cmap1(k), lw=1, marker=None, markersize=5, label=datetxt)
    # ax.plot(val1, color=cmap1(k), lw=0, marker='o', markersize=5, label=datetxt)
    # ax.legend(bbox_to_anchor=(1.3, 1.02), frameon=False)
    sl = 10
    if k in np.arange(0,len(dates),sl):
        leg.append(datetxt)
        
    ax.yaxis.set_major_formatter(ScalarFormatter())
    ax.set_xlim(1,12)
    ax.set_ylim(0,31)
    ax.tick_params(axis='both', which='major', pad=10)
    x1 = np.arange(1,12+1,1)
    # squad = ['O','N','D','J','F','M','A',
    #           'M','J','J','A','S','O']
    squad = ['J','F','M','A','M','J','J','A','S','O','N','D']

    ax.set_xticks(x1)
    ax.set_xticklabels(squad, minor=False, rotation='horizontal')
    # ax.grid(True)
    ax.set_title(var+sign+str(cond))
    
    # val2 = df_per[var+'>'+str(0.75)]
    # axb.plot(val2, color=cmap2(k), lw=2, marker=None, markersize=5, label=datetxt)
    # axb.set_ylim(0,31)
    axb.get_yaxis().set_visible(False)
    
    # ax.set_yscale('log')

    data_f[str(compt)] = val1
    compt +=1

data_f['MEAN'] = data_f.median(axis=1)
ax.plot(data_f['MEAN'], color='k', lw=3, marker=None, markersize=5, label=datetxt)

# norm = mpl.colors.BoundaryNorm(np.arange(0,n+1)-0.5, n)
# sm = plt.cm.ScalarMappable(cmap=cmap1, norm=norm)
# sm.set_array([])
# cbar = plt.colorbar(sm, aspect=30)
# cbar.set_ticks(np.arange(0,n,sl))
# cbar.set_ticklabels(leg)
# cbar.ax.tick_params(labelsize=10) 

# l = ax.legend(leg, bbox_to_anchor=(1.3, 1.02), frameon=False)
# for i in range(len(leg)):
#     l.legendHandles[i].set_color(cmap1(i))
# ax.plot(val1, color=cmap(k), lw=0.2, marker=None, markersize=5, label=datetxt)

# fig.savefig(fig_path + '_clim/' + 
#             '_daycounts_' + var + '.png', dpi=300, bbox_inches='tight')


#%% 1 - EVOL DAYS MONTHLY MODS

from matplotlib.ticker import ScalarFormatter

var = 'REC'
sign = '<'
cond = 0.1

mod = 'CNR-ALA'
sce = 'RCP8.5'
ref = [2010,2098]

freq = dfd.copy()
freq = freq.filter(regex=mod)
freq = freq.dropna(axis=0, how='all')

freq[var+'<'+str(0)] = (freq[var+'_'+mod+'_'+sce].round(3) <= 0.1).astype(int)
quant = cond
freq[var+'>'+str(quant)] = (freq[var+'_'+mod+'_'+sce].round(3) > freq[var+'_'+mod+'_'+sce]
                            .round(3).quantile(quant))#.astype(int)
freq[var+'<'+str(quant)] = (freq[var+'_'+mod+'_'+sce].round(3) <= freq[var+'_'+mod+'_'+sce]
                            .round(3).quantile(quant))#.astype(int)
quant = 0.90
freq[var+'<'+str(quant)] = (freq[var+'_'+mod+'_'+sce].round(3) < freq[var+'_'+mod+'_'+sce]
                            .round(3).quantile(quant))#.astype(int)
freq[var+'>'+str(quant)] = (freq[var+'_'+mod+'_'+sce].round(3) >= freq[var+'_'+mod+'_'+sce]
                            .round(3).quantile(quant))#.astype(int)

freq = freq[(freq.index.year >= ref[0]) & (freq.index.year <= ref[1])]
# df_new = df_new[['counts1','counts2']]
group = freq.groupby([(freq.index.year),(freq.index.month)]).sum()

space = 10

dictio = {}
for per in range(1,12+1):
    dictio[per] = group[group.index.get_level_values(1) == per]
    if space > 0:
        dictio[per] = dictio[per].rolling(window=space).mean().shift()
        dictio[per]['year'] = (dictio[per].index.get_level_values(0)).astype(int)
        dictio[per]['month'] = (dictio[per].index.get_level_values(1)).astype(int)
        dictio[per]['bef'] = dictio[per].year - space
        dictio[per]['per'] = dictio[per].bef.astype(str) + '-' + dictio[per].year.astype(str)
    else:
        # dictio[per] = dictio[per].mean().shift()
        dictio[per]['year'] = (dictio[per].index.get_level_values(0)).astype(int)
        dictio[per]['month'] = (dictio[per].index.get_level_values(1)).astype(int)
        dictio[per]['bef'] = dictio[per].year
        dictio[per]['per'] = dictio[per].bef.astype(str) + '-' + dictio[per].year.astype(str)
        
df_list = [v for k,v in dictio.items()]
df_rol = pd.concat(df_list ,axis=0)
df_rol = df_rol.set_index(['year'])

df_slice = df_rol[(df_rol.index >= ref[0]+space) & (df_rol.index <= ref[1])]

fig, ax = plt.subplots(1,1,figsize=(5, 3))
fig.add_subplot(111, frameon=False)
plt.tick_params(labelcolor='none', top=False, bottom=False, left=False, right=False) # hide tick and tick label of the big axis
# plt.xlabel("Months")
# plt.ylabel("Day counts")
axb = ax.twinx()

dates = np.arange(ref[0]+space,ref[1]+1,1)
n = len(dates)
cmap1 = cm.get_cmap('jet', n)
cmap2 = cm.get_cmap('autumn', n)
leg = []

data_f = pd.DataFrame()

compt = 0
for k in range(len(dates)):
    date = dates[k]
    df_per = df_slice[df_slice.index==date].groupby(['month']).mean()
    df_per = df_per.reset_index()
    # df_per['month'] = df_per['month'].replace(
    #                                     [10,11,12,1,2,3,4,5,6,7,8,9],
    #                                     [1,2,3,4,5,6,7,8,9,10,11,12])
    df_per = df_per.sort_values(['month'])
    df_per = df_per.set_index('month')
    # df_per = df_per.append(df_per.iloc[[0]])
    # df_per.index = np.arange(1,14,1)
    
    datetxt = str(int(df_per.bef.iloc[0])) + '-' + str(int(date))
    val1 = df_per[var+sign+str(cond)]
    ax.plot(val1, color=cmap1(k), lw=1, marker=None, markersize=5, label=datetxt)
    # ax.plot(val1, color=cmap1(k), lw=0, marker='o', markersize=5, label=datetxt)
    # ax.legend(bbox_to_anchor=(1.3, 1.02), frameon=False)
    sl = 10
    if k in np.arange(0,len(dates),sl):
        leg.append(datetxt)
        
    ax.yaxis.set_major_formatter(ScalarFormatter())
    ax.set_xlim(1,12)
    ax.set_ylim(0,31)
    ax.tick_params(axis='both', which='major', pad=10)
    x1 = np.arange(1,12+1,1)
    # squad = ['O','N','D','J','F','M','A',
    #           'M','J','J','A','S','O']
    squad = ['J','F','M','A','M','J','J','A','S','O','N','D']

    ax.set_xticks(x1)
    ax.set_xticklabels(squad, minor=False, rotation='horizontal')
    # ax.grid(True)
    ax.set_title(var+sign+str(cond))
    
    # val2 = df_per[var+'>'+str(0.75)]
    # axb.plot(val2, color=cmap2(k), lw=2, marker=None, markersize=5, label=datetxt)
    # axb.set_ylim(0,31)
    axb.get_yaxis().set_visible(False)
    
    # ax.set_yscale('log')

    data_f[str(compt)] = val1
    compt +=1

data_f['MEAN'] = data_f.median(axis=1)
ax.plot(data_f['MEAN'], color='k', lw=3, marker=None, markersize=5, label=datetxt)

# norm = mpl.colors.BoundaryNorm(np.arange(0,n+1)-0.5, n)
# sm = plt.cm.ScalarMappable(cmap=cmap1, norm=norm)
# sm.set_array([])
# cbar = plt.colorbar(sm, aspect=30)
# cbar.set_ticks(np.arange(0,n,sl))
# cbar.set_ticklabels(leg)
# cbar.ax.tick_params(labelsize=10) 

# l = ax.legend(leg, bbox_to_anchor=(1.3, 1.02), frameon=False)
# for i in range(len(leg)):
#     l.legendHandles[i].set_color(cmap1(i))
# ax.plot(val1, color=cmap(k), lw=0.2, marker=None, markersize=5, label=datetxt)

# fig.savefig(fig_path + '_clim/' + 
#             '_daycounts_' + var + '.png', dpi=300, bbox_inches='tight')

#%% 1 - EVOL DAYS YEARLY REA

mod = 'REA'
sce = 'historic'
var = 'ETP'
per = [1960,2020]

d = dfd.copy()

fig, ax = plt.subplots(1,1, figsize=(5,3))

val_quants = [0.05, 0.1]
# val_quants = [0, 0.25]
val_quants = [0.99, 0.95]

for val_quant in val_quants:
    
    quant = select_period(d[var+'_'+mod+'_'+sce],
                          1980 ,2010).quantile(val_quant)
    
    if val_quant == 0:
        val_quant = 0
            
    d = d[(d.index.year>=per[0]) & (d.index.year<=per[1])]
    d = d.filter(regex=var+'_'+mod+'_'+sce)
    d = d.round(2)
    
    x = d.copy()
    x['counter'] = x.diff().ne(0).cumsum()
    
    d['diff'] = d.diff()
                          
    # quant = d[var+'_'+mod+'_'+sce].min()
    if var == 'ETP':
        quant = d[var+'_'+mod+'_'+sce].quantile(val_quant)
        # quant = d[var+'_'+mod+'_'+sce].max()
    cond = quant
    
    if (var =='PPT') | (var == 'REC'):
        cond = quant
    
    # cond = 0
    
    years = d.index.year.unique()
    
    # fig, ax = plt.subplots(1,1, figsize=(5,3))
    # axs = axs.ravel()
    n = len(years)
    cmap = cm.get_cmap('jet', n)
    
    max_consec_list = []
    min_consec_list = []
    
    counts = []
    for i, year in enumerate(years):
    
        each = d[d.index.year==year]
        # count = ((each['diff'] <= cond) & (each[var+'_'+mod+'_'+sce] <= cond)).astype(int).sum(axis=0)
        count = ((each[var+'_'+mod+'_'+sce] <= cond)).astype(int).sum(axis=0)
        if var =='ETP':
            test = ((each['diff'] <= cond) & (each[var+'_'+mod+'_'+sce] >= cond)).astype(int)
            count = ((each['diff'] <= cond) & (each[var+'_'+mod+'_'+sce] >= cond)).astype(int).sum(axis=0)
        counts.append(count)
        
        new = x[x.index.year==year]
        df2 = new.groupby('counter')[var+'_'+mod+'_'+sce].min().to_frame(name='value').join(new.groupby('counter')[var+'_'+mod+'_'+sce].count().rename('number'))
        max_consec0 = df2[df2['value']<=quant]['number'].tolist()
        if var =='ETP':
            max_consec0 = df2[df2['value']>=quant]['number'].tolist()
        max_consec1 = df2[df2['value']==1]['number'].tolist()
        try:
            max_consec_list.append(max(max_consec0))
        except:
            max_consec_list.append(np.nan)
            pass
        # min_consec_list.append(min(max_consec0))
        
        # ax = axs[0]
        # ax.plot(each['diff'].values, c=cmap(i), lw=0.5)
        # ax.set_xlim(0,365)
        # ax.set_ylabel('Diff. day before')
        # ax.set_title(var)
        
        # ax = axs[1]
        # ax.plot(max_consec0, c=cmap(i), lw=0.5)
        # ax.set_ylabel('Max consec. 0')
        # ax.set_title(var)
        
    # ax.set_xlim(0, None)
    # ax.set_ylim(0, None)
        
    # ax.plot(pd.to_datetime(years, format='%Y'), counts, c='k', lw=2)
    if val_quant == val_quants[0]:
        col = 'darkorange'
        ax.bar(pd.to_datetime(years, format='%Y'), counts,
               align='center', color=col, width=280, lw=0.5, zorder=10)
    if val_quant == val_quants[1]:
        col = 'lightgrey'
        ax.bar(pd.to_datetime(years, format='%Y'), counts,
               align='center', color=col, width=280, lw=0.5, zorder=0)
    
# ax.fill_between(pd.to_datetime(years, format='%Y'), counts, np.array(counts)-
#                 np.array(max_consec_list), lw=0, color='cyan')
# ax.bar(pd.to_datetime(years, format='%Y'), np.array(max_consec_list), color='white',
#        width=300)
# axb = ax.twinx()
# ax.plot(pd.to_datetime(years, format='%Y'), np.array(counts)-
#                 np.array(max_consec_list), c='b', lw=1)
# axb.plot(pd.to_datetime(years, format='%Y'), max_consec_list, c='red', lw=2)
# ax.set_ylim(1,182)
# axb.set_ylim(1,182)
# ax.set_ylabel('>= 2 days consec.'+' = '+str(cond))
ax.set_title(var)
ax.set_xlim(pd.to_datetime('1959'), pd.to_datetime('2021'))
if (var=='PPT') | (var=='REC'):
    ax.set_ylim(0,180)
    ax.set_yticks(np.arange(0, 180+1, 30))

ax.set_axisbelow(True)
# ax.grid(zorder=-1000)
ax.xaxis.grid(color='gray', alpha=0.2, zorder=-20)
ax.yaxis.grid(color='gray', alpha=0.2, zorder=-20, which='both')

plt.tight_layout()

# fig.savefig(fig_path+'_clim/'+'days_consec_'+var+'_'+
#             str(val_quants)+'.png', dpi=300, bbox_inches='tight')

#%% 1 - *** EVOL DAYS YEARLY MODS

dayon_list = ['ACC1','BCC1','BNU1','CAN1','CAN2','CAN3','CAN4','CAN5',
              'CNR1','CSI1','IPS1','MIR1','MIR2','MIR3','NOR1']

explore2_list = ['ECE-RCA','ECE-RAC','HAD-REG','NOR-R15',
                 'MPI-CCL','MPI-R09','CNR-RAC','CNR-ALA',
                 'IPS-WRF','HAD-CCL','IPS-RCA','NOR-HIR']

sce = 'RCP8.5'
var = 'PPT'
var = 'REC'
per = [1975,2100]

typ = 'EXPLORE2'
mod_list = [
            'ECE-RCA','ECE-RAC',
            'HAD-REG','HAD-CCL',
            'NOR-R15','NOR-HIR',
            'MPI-CCL','MPI-R09',
            'CNR-RAC','CNR-ALA',
            'IPS-WRF','IPS-RCA'
            ]
mod_list = [
            'ECE-RCA',
            'MPI-CCL',
            'CNR-ALA',
            ]

typ = 'DAYON'
mod_list = ['ACC1','BCC1','BNU1','CAN1','CAN2','CAN3','CAN4','CAN5',
            'CNR1','CSI1','IPS1','MIR1','MIR2','MIR3','NOR1']
mod_list = ['IPS1',
            'CAN3',
            'NOR1']

typ = 'MIX'
mod_list = ['ECE-RCA',
            'MPI-CCL',
            'CNR-ALA',
            'IPS1',
            'CAN3',
            'NOR1']

df_rec = pd.DataFrame()

# fig, ax = plt.subplots(1,1, figsize=(6,3))

val_quant = 0.1

for mod in mod_list :
    
    d = dfd.copy()
    # d = d.resample('M').sum()
    
    quant = select_period(d[var+'_'+mod+'_'+'historic'],
                          1980, 2004).quantile(val_quant)
    if var == 'PPT':
        quant = 0
    cond = quant

    d = d[(d.index.year>=per[0]) & (d.index.year<=per[1])]
    d = d.filter(regex=var+'_'+mod)
    
    # if typ == 'DAYON':
    if len(mod.split('-')) == 1:
        d[var+'_'+mod+'_'+'historic'][(d.index.year)>=2005] = np.nan
        d[var+'_'+mod+'_'+sce][(d.index.year)<2005] = np.nan

    d = pd.concat((d.filter(regex=var+'_'+mod+'_'+sce),
                    d.filter(regex=var+'_'+mod+'_'+'historic')), axis=1).mean(axis=1).to_frame()
    
    ish = (d.filter(regex=var+'_'+mod+'_'+'historic')).dropna().shape[1]
    isf = (d.filter(regex=var+'_'+mod+'_'+sce)).dropna().shape[1]
        
    # print(mod, sce, ish, isf, d.shape)

    # plt.plot(d)

    d.columns = [var+'_'+mod+'_'+sce]
    d = d.round(2)
    
    x = d.copy()
    x['counter'] = x.diff().ne(0).cumsum()
    
    d['diff'] = d.diff()
    
    years = d.index.year.unique()
    
    # fig, ax = plt.subplots(1,1, figsize=(6,3))
    # axs = axs.ravel()
    n = len(years)
    cmap = cm.get_cmap('jet', n)
    
    max_consec_list = []
    min_consec_list = []
    
    counts = []
    for i, year in enumerate(years):
    
        each = d[d.index.year==year]
        
        count = ((each['diff'] <= 0) & (each[var+'_'+mod+'_'+sce] <= cond)).astype(int).sum(axis=0)
        
        # count = ((each[var+'_'+mod+'_'+sce] <= cond)).astype(int).sum(axis=0)

        if (var =='ETP') | (var =='TAS'):
            # test = ((each['diff'] <= cond) & (each[var+'_'+mod+'_'+sce] >= cond)).astype(int)
            # count = ((each['diff'] <= cond) & (each[var+'_'+mod+'_'+sce] >= cond)).astype(int).sum(axis=0)
            count = ((each[var+'_'+mod+'_'+sce] >= cond)).astype(int).sum(axis=0)
        counts.append(count)
        
        new = x[x.index.year==year]
        df2 = new.groupby('counter')[var+'_'+mod+'_'+sce].min().to_frame(name='value').join(
              new.groupby('counter')[var+'_'+mod+'_'+sce].count().rename('number'))
        max_consec0 = df2[df2['value']<=quant]['number'].tolist()
        if var =='ETP':
            max_consec0 = df2[df2['value']>=quant]['number'].tolist()
        max_consec1 = df2[df2['value']==1]['number'].tolist()
        try:
            max_consec_list.append(max(max_consec0))
        except:
            max_consec_list.append(np.nan)
            pass
        # min_consec_list.append(min(max_consec0))
        
        # ax = axs[0]
        # ax.plot(each['diff'].values, c=cmap(i), lw=0.5)
        # ax.set_xlim(0,365)
        # ax.set_ylabel('Diff. day before')
        # ax.set_title(var)
        
        # ax = axs[1]
        # ax.plot(max_consec0, c=cmap(i), lw=0.5)
        # ax.set_ylabel('Max consec. 0')
        # ax.set_title(var)
    
    df_rec[mod] = counts
    
    # ax.set_xlim(0, None)
    # ax.set_ylim(0, None)

df_rec.index = years
# df_rec.boxplot()

x = df_rec.copy()
x['med'] = df_rec.quantile(0.50, axis=1)
x['med'] = df_rec.mean(axis=1)
# threshold = 60
# x['cond'] = False
# x['cond'][x[mod] >= 60] = True 
x['cond'] = np.nan
x['cond'][x['med']<60] = 0
x['cond'][x['med']>=60] = 1
# x['consecutive'] = x['cond'].groupby((x['cond'] != x['cond'].shift()).cumsum()).transform('size') * x['cond']
# x['consecutive'] = (x['cond'].groupby((x['cond'] != x['cond'].shift()).cumsum()).transform('size') * x['cond'] >= 1).astype(int)
# x['cumsum'] = x[mod].cumsum()
# x['diff'] = x[mod].diff()
# x['cond'] = np.nan
x['cons'] = 0
for j in x.index:
    # print(j)
    if j > x.index[0]:
        if (x.loc[j,'cond'] == 1) & (x.loc[j-1,'cond'] == 1):
            x.loc[j,'cons'] = 1
# y = pd.concat([x[mod], x[mod].diff().ne(0).cumsum()], axis=1)
l = []
for p in [[1975,2010],[2010,2040],[2040,2070],[2070,2100]]:
    v_cond = x[(x.index>=p[0])&(x.index<=p[1])].groupby(x['cond'].diff().ne(0).cumsum()).sum().sum()
    val_cond = v_cond['cond'] #/ (p[1]-p[0])
    v_cons = x[(x.index>=p[0])&(x.index<=p[1])].groupby(x['cons'].diff().ne(0).cumsum()).sum().sum()
    val_cons = v_cons['cons'] #/ (p[1]-p[0])
    y = x[(x.index>=p[0])&(x.index<=p[1])]['cond']
    v_maxi = y.groupby((y != y.shift()).cumsum()).transform('size') * y
    val_maxi = v_maxi.max()
    print(p, val_cond.round(3), val_cons.round(3), val_maxi.round(3))
    l.append(val_cond.round(3))
    l.append(val_cons.round(3))
    l.append(val_maxi.round(3))

df_rec = df_rec.T

# df_rec.boxplot()

fig, ax = plt.subplots(1,1, figsize=(10,4))

ax.set_title(l, fontsize=6)

normaliz = plt.Normalize(df_rec.median().min(), df_rec.median().max())
norm = matplotlib.colors.Normalize(vmin=0, vmax=120)
# if sce == 'RCP2.6':
#     to_norm = df_rec.median()
colors = plt.cm.jet(norm(df_rec.median()))
# colors = plt.cm.jet(norm([60] * len(df_rec.columns)))
# colors = plt.cm.jet(norm(to_norm))

medianprops = dict(linestyle='-', linewidth=1, color='black')
meanpointprops = dict(markersize=0, marker='o', markeredgecolor='black',
                      markerfacecolor='k', linestyle='-')

ax.vlines(x=years, 
            ymin=df_rec.quantile(0.75), 
            ymax=df_rec.quantile(0.95), color='k', zorder=2)
ax.vlines(x=years, 
            ymin=df_rec.quantile(0.05), 
            ymax=df_rec.quantile(0.25), color='k', zorder=2)

# boxprops = dict(linestyle='-', linewidth=1, color='k',
#                 facecolor='cyan', alpha=0.5)
# bp = ax.boxplot(df_rec, widths=0.75,
#                 positions=years,
#                   whis=False, showfliers=False, showmeans=False, 
#                   medianprops=medianprops, meanprops=meanpointprops,
#                   patch_artist=True, boxprops=boxprops)

for i in range(len(years)):
    # print(i)
    boxprops = dict(linestyle='-', linewidth=1, color='k',
                    facecolor=colors[i], 
                    alpha=0.5)
    bp = ax.boxplot(df_rec.iloc[:,i], widths=0.75,
                    positions=[df_rec.columns[i]],
                      whis=False, showfliers=False, showmeans=False, 
                      medianprops=medianprops, meanprops=meanpointprops,
                      patch_artist=True, boxprops=boxprops)

ax.plot(years, df_rec.mean(), marker='o', mec='k', ms=1.5, lw=0,
        mfc='k', mew=1,
        color='k', zorder=1000)
  
for element in bp['whiskers']:
    element.set_color('k')
    element.set_linestyle('-')
# for patch in bp['boxes']:
#     patch.set(facecolor='r')    
ax.set_xticks(np.arange(1980, 2100+1, 10))
ax.set_xticklabels(np.arange(1980, 2100+1, 10))

# ax.get_xaxis().set_visible(False)
# ax.set_yscale('log')

ax.set_ylim(-5, 180)
ax.set_yticks(np.arange(0, 180+1, 30))

ax.set_xlim(1974,2100)
ax.tick_params(axis='x', which='minor')

from matplotlib.ticker import (MultipleLocator)
ax.xaxis.set_minor_locator(MultipleLocator(1))

ax.set_axisbelow(True)
# ax.grid(zorder=-1000)
ax.xaxis.grid(color='gray', alpha=0.2, zorder=-20)
ax.yaxis.grid(color='gray', alpha=0.2, zorder=-20, which='both')

# ax.set_title(var+' - '+mod)
# ax.set_xlim(pd.to_datetime('1974'), pd.to_datetime('2100'))

plt.tight_layout()

# fig.savefig(fig_path+'_clim/'+'recharge_days_'+str(mod_list)+'_'+
#             str(val_quant)+'.png', dpi=300, bbox_inches='tight')

res_path = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/15_results/EBR_v2/'

# ax.set_ylim(-5, 180)

folder_fig = res_path + 'figures/' + 'raw_' + 'All' + '/'

# fig.savefig(folder_fig + 
#             'SUCCESSIVE_' + sce + '_' + str(mod_list) + '.png',
#             dpi=300, bbox_inches='tight')

# df_rec.to_csv("C:/Users/ronan/Downloads/"+
#               "RCP2.6 - nombre de jours inférieur au Q10 historique.csv")
df_rec.to_csv("C:/Users/ronan/Downloads/"+
              "RCP8.5 - nombre de jours inférieur au Q10 historique.csv")

#%% 1 - BASE HYDRO

'''
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
'''     

for site_name in site_names[:]:

    watershed_name = site_name[0]
    code_name = site_name[1]
    
    if code_name != None:

        print('##### '+watershed_name.upper()+' #####')
        
        BV = watershed_root.Watershed(watershed_name=watershed_name,
                                      dem_path=dem_path, 
                                      out_path=out_path,
                                      load=True)
        area = BV.geographic.area
        print(area)
        
        stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
        Qobs_path = glob.glob(stable_folder+'hydrometry/'+'Hydrometric_'+'*'+'.csv')[0]
        naming = Qobs_path.split('\\')[-1]
        
        Qobs = pd.read_csv(Qobs_path, sep=';', index_col=0, parse_dates=True)
        # area = float(Qobs_path.split('_')[-3])
        Qobs = Qobs.squeeze()
        Qobs = Qobs.rename('Q')
        
        first = Qobs.first_valid_index().year+1
        last = Qobs.last_valid_index().year-1
        
        if watershed_name == 'Gael':
            first=2009
        
        Qobs = select_period(Qobs, first, last)
        Qobs = (Qobs / (area*1000000)) * (3600 * 24) * 1000 # m3/s to mm/d

        data_index = Qobs.copy()
    
        mean_mensual = data_index.resample('M').mean() # mensual mean
        mean_annual = data_index.resample('Y').mean() # annual mean
        Mean = round(data_index.mean(),2)
        Mean = data_index.mean()
        Min = data_index.resample('Y').min()
        Q10 = data_index.resample('Y').quantile(0.10)
        Q25 = data_index.resample('Y').quantile(0.25)
        Q50 = data_index.resample('Y').quantile(0.50)
        Q75 = data_index.resample('Y').quantile(0.75)
        Q90 = data_index.resample('Y').quantile(0.90)
        print(Q10.min())
        print(Q90.max())
        Max = data_index.resample('Y').max()
        mean_interan_days = data_index.groupby([data_index.index.month,
                                        data_index.index.day], as_index=True).mean().to_frame()
        std_interan_days = data_index.groupby([data_index.index.month,
                            data_index.index.day], as_index=True).std()
        q10_interan_days = data_index.groupby([data_index.index.month,
                            data_index.index.day], as_index=True).quantile(0.10)
        q90_interan_days = data_index.groupby([data_index.index.month,
                            data_index.index.day], as_index=True).quantile(0.90)
        q50_interan_days = data_index.groupby([data_index.index.month,
                            data_index.index.day], as_index=True).quantile(0.50)
        mean_interan_days['std'] = std_interan_days
        mean_interan_days['q10'] = q10_interan_days
        mean_interan_days['q90'] = q90_interan_days
        mean_interan_days['q50'] = q50_interan_days
        mean_interan_days.index.names = ['months','days']
        mean_interan_days = mean_interan_days.reset_index()
        # mean_interan_days.months = mean_interan_days.months.replace(
        #                                     [10,11,12,1,2,3,4,5,6,7,8,9],
        #                                     [1,2,3,4,5,6,7,8,9,10,11,12])
        mean_interan_days = mean_interan_days.sort_values(['months','days'])
        mean_interan_days['counts'] = np.array(range(1,len(mean_interan_days)+1))
        # mean_interan_days.q10 = mean_interan_days.q10.replace(0,0.01)
        fig, ax = plt.subplots(figsize=(5,4))
        # ax.plot(mean_interan_days.counts, mean_interan_days[station+'_mmm'],
        #         lw=1, color='red', label='Mean')
        
        '''
        ones = [1976, 1990, 2001]
        dates = ones
        colors = ['red','darkorange','forestgreen']
        linestyles = ['-','-','-','-']
        for z in range(len(dates)):
            onlyone = data_index[(data_index.index.year==dates[z])].to_frame()
            onlyone = onlyone.groupby([onlyone.index.month,
                                        onlyone.index.day], as_index=True).mean()
            onlyone['counts'] = np.array(range(1,len(onlyone)+1))
            ax.plot(onlyone.counts, onlyone['Q'],
                    color=colors[z], lw=1, ls=linestyles[z], label = str(dates[z]),
                    zorder=-10)
        '''
        
        ax.plot(mean_interan_days.counts, mean_interan_days.q50,
                lw=2, color='darkred', label='Median')
        yerrmax = mean_interan_days.q90
        yerrmin = mean_interan_days.q10
        ax.fill_between(mean_interan_days.counts, yerrmin, yerrmax,
                          color='cyan',edgecolor='grey',
                          alpha = 0.5, label='10-90th')
        ax.set_yscale('log')
        # ax.yaxis.set_major_formatter(ScalarFormatter())
        ax.set_xlim(0,366)
        ax.set_ylim(0.01,100)
        ax.tick_params(axis='both', which='major', pad=10)
        x1 = np.linspace(0,366,13)
        squad = ['J','F','M','A','M','J','J','A','S','O','N','D','J']
        ax.set_xticks(x1)
        ax.set_xticklabels(squad, minor=False, rotation='horizontal')
        ax.set_xlabel('Months', labelpad=+10)
        ax.set_ylabel('Q / A [mm/day]',labelpad=+10)
        ax.set_title(watershed_name + ' [' + str(first) + ' to ' + str(last) + ']')
        # ax.grid(color='grey', lw=0.5, zorder=0)            
        ax.legend(loc='upper left', frameon=False)

        plt.tight_layout()
        
        
        # fig.savefig(path + 'plot_figures/' + site + '/' + 'regime' + '.png', dpi=300, bbox_inches='tight')
        # fig.savefig(figsim_folder+'/'+watershed_name+'_intermensual'+'.png', dpi=300, bbox_inches='tight')
        fig.savefig(fig_path + '_hydro/' + site_name[0] + '_intermensual' + '.png', dpi=300, bbox_inches='tight')

#%% 1 - BASE PIEZO 

piezos = ['boisgervilly', 'mezieres']

piezos = ['boisgervilly']

for name in piezos[:]:

    path_p = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/2_data/Hydrology/ADES/'+name+'.txt'
    
    piezs = pd.read_csv(path_p, sep='|', encoding='latin-1', engine='python')
    piezs['Date de la mesure'] = pd.to_datetime(piezs['Date de la mesure'], format="%d/%m/%Y %H:%M:%S")
    piezs.index = piezs['Date de la mesure']
    
    piez = piezs['Profondeur relative/repère de mesure']
    # piez = piezs['Côte NGF']
    piez = piez.rename('P').to_frame()
    
    x = piez.index
    y = piez['P']
    
    # y.to_csv(r"D:\PHD\4_model\MFLOW3D\modflow_calibration\namesite_v0\data\piezo\Well_Boisgervilly (2005-2020).csv",
    #          index=True, header=None)
    
    mask_mo = piez.resample("M",label="left", closed="left").P.count() >= 20
    mask_an = piez.resample("Y",label="left", closed="left").P.count() >= 300
    
    mo_x = (piez.resample("M", label="left").mean())[mask_mo].index
    mo_y = (piez.resample("M", label="left").mean())[mask_mo].P
    an_x = (piez.resample("Y", label="left").mean())[mask_an].index
    an_y = (piez.resample("Y", label="left").mean())[mask_an].P
    
    altitude = 82
    
    fig, axs = plt.subplots(figsize=(6, 3.5))
    
    axs.plot(x, y, marker=".",color ='navy',markersize=5,linestyle = 'None',
             label='Daily values')
    # axs.plot(mo_x, mo_y, linestyle = 'None', linewidth=2,color='dodgerblue',
    #          label='Monthly values', marker='v',markersize=6)
    axs.plot(an_x, an_y, marker="o", markersize=9, linestyle = 'None',
             markeredgecolor='black', mew=2, markerfacecolor='white',
             label='Yearly values')
        
    plt.xlabel("Date", labelpad=+7)
    plt.ylabel("Water table level [mBGS]", labelpad=+10)
    
    # title = str(piez.LibPoint[0])+' - '+str(piez.CdPoint[0])
    # axs.set_title(title, fontsize=12)
    
    import matplotlib.dates as mdates
    
    years = mdates.YearLocator(2)   # every year
    years_min = mdates.YearLocator(1)   # every year
    months = mdates.MonthLocator(12)  # every month
    years_fmt = mdates.DateFormatter('%Y')
    
    axs.xaxis.set_major_locator(years)
    axs.xaxis.set_major_formatter(years_fmt)
    axs.xaxis.set_minor_locator(years_min)
    
    axs.grid(linestyle='--', alpha=0.5)
    axs.invert_yaxis()
    axs.set_ylim(13, 0)
    
    ymin, ymax = axs.get_ylim()
    
    axs.fill_between(x, 0, y, color='saddlebrown', alpha=0.2)
    axs.fill_between(x, ymin, y, color='cyan', alpha=0.2)

    axs.set_xlim(pd.to_datetime('2006'), pd.to_datetime('2022'))

    plt.legend(loc='best')

    plt.tight_layout()
    
    # fig.savefig(fig_path + '_hydro/' + name + '.png', dpi=300, bbox_inches='tight')

    fig, ax = plt.subplots(figsize=(6, 3.5))
    piezs = pd.read_csv(path_p, sep='|', encoding='latin-1', engine='python')
    piezs['Date de la mesure'] = pd.to_datetime(piezs['Date de la mesure'], format="%d/%m/%Y %H:%M:%S")
    piezs.index = piezs['Date de la mesure']
    piez = piezs['Profondeur relative/repère de mesure']
    # piez = piezs['Côte NGF']
    piez = piez.rename('P').to_frame()
    piez['day'] = piez.index.dayofyear.values
    # piez['month'] = piez.index.month.values
    piez['year'] = piez.index.year.values # group by month and year, get the average
    piez = piez.groupby(['day','year']).apply(lambda g: g.mean(skipna=False))
    # piez = piez.groupby(['month','year']).apply(lambda g: g.mean(skipna=False))
    piez = piez.unstack(level=0, fill_value=np.nan)
    piez = piez.P
    piez = piez.T
    piez['MEAN'] = piez.mean(axis=1)
    piez['MAX'] = piez.max(axis=1)
    piez['MIN'] = piez.min(axis=1)
    Q10 = piez.quantile(0.25, axis=1)
    Q90 = piez.quantile(0.75, axis=1)
    ax.fill_between(piez.index, piez['MIN'], piez['MAX'], color='lightgrey', lw=0,
                    alpha=1, label='Min to Max')
    ax.fill_between(piez.index, Q10, Q90, color='grey', lw=0, alpha=0.7, label='Q25 to Q75')
    ax.plot(piez.index, piez[2020], lw=3, c='blue', label='2020')
    ax.plot(piez.index, piez.MEAN, lw=4, c='k', label='Mean')
    ax.plot(piez.index, piez[2017], lw=3, c='red', label='2017')
    ax.set_xticks(np.arange(0,370,30))
    ax.set_xlim(0,365)
    # ax.set_ylim(0,13)
    ax.invert_yaxis()
    ax.legend(loc='upper center', frameon=False)
    # secax = ax.secondary_xaxis('top')
    # secax.set_xticks([], minor=True)
    # secax.set_xticks(np.arange(15,370,30), minor=False)
    # secax.tick_params(axis='both', which='both', length=0)
    # secax.set_xlim(0,365)
    # secax.set_xticklabels(['J','F','M','A','M','J','J','A','S','O','N','D'])
    # secax.set_xlabel('Months')
    ax.set_xlabel('Days')
    ax.set_ylabel("Water table level [mBGS]")
    # secax.minorticks_off()
    ax.set_ylim(13,0)
    
    fig.savefig(fig_path + '_hydro/' + name + '_daily' + '.png', dpi=300, bbox_inches='tight')

#%% 1 - MATRIX HYDRO

for site_name in site_names[:]:

    watershed_name = site_name[0]
    code_name = site_name[1]
    
    if code_name != None:

        print('##### '+watershed_name.upper()+' #####')
        
        BV = watershed_root.Watershed(watershed_name=watershed_name,
                                      dem_path=dem_path, 
                                      out_path=out_path,
                                      load=True)
        area = BV.geographic.area
        
        stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
        Qobs_path = glob.glob(stable_folder+'hydrometry/'+'Hydrometric_'+'*'+'.csv')[0]
        naming = Qobs_path.split('\\')[-1]
        
        Qobs = pd.read_csv(Qobs_path, sep=';', index_col=0, parse_dates=True)
        # area = float(Qobs_path.split('_')[-3])
        Qobs = Qobs.squeeze()
        Qobs = Qobs.rename('Q')
        
        # first = Qobs.first_valid_index().year+1
        # last = Qobs.last_valid_index().year-1
        
        first = 1968
        last = 2021
        
        # if watershed_name == 'Gael':
        #     first=2009
        
        Qobs = select_period(Qobs, first, last)
        Qobs = (Qobs / (area*1000000)) * (3600 * 24) * 1000 # m3/s to mm/d

        data_index = Qobs.copy()
        
        hist = pd.DataFrame(index=pd.date_range(start='1/1/1968', end='31/12/2021'))
        hist['Q'] = Qobs
        
        hist['day'] = hist.index.dayofyear.values
        hist['year'] = hist.index.year.values # group by month and year, get the average
        hist = hist.groupby(['day','year']).apply(lambda g: g.mean(skipna=False))
        hist = hist.unstack(level=0, fill_value=np.nan)
        hist = hist['Q']
        hist[hist==0] = 0.001
        # hist = hist.T
        
        lims = (hist.min(), hist.max())
        # vmin = np.array(lims).min()
        # vmax = np.array(lims).max()
        vmin = 0.001
        vmax = 10
        normalize = mpl.colors.Normalize(vmin=vmin, vmax=vmax)
        
        fig, ax = plt.subplots(1,1, figsize=(5, 4))
        colori = "jet"
        
        import matplotlib as mpl
        pc = ax.pcolormesh(hist, cmap='jet_r', vmin=vmin, vmax=vmax,
                            norm = mpl.colors.LogNorm(),
                           edgecolor='none', lw=0.2, alpha=0.7)
                          # norm=mpl.colors.LogNorm(vmin, vmax)
                          # norm=mpl.colors.CenteredNorm()
                      
        xticks = np.arange(0,365+1,60)
        days = np.arange(0,365+1,60)              
        ax.set_xticks(xticks)
        ax.set_xticklabels(days, minor=False, rotation='horizontal', fontsize=13)
        yticks = np.arange((hist.index[-1]+1) - hist.index[0])+0.5+2
        years = list((hist.index.values+2).astype(str))[::5]
        ax.set_yticks(yticks[::5])
        ax.set_yticklabels(years, minor=False, rotation='horizontal', fontsize=13)
        ax.invert_yaxis()
        ax.tick_params(axis="x", direction='out', length=5)
        ax.tick_params(axis="y", direction='out', length=5)
        plt.tick_params(right=False, top=False)
        ax.set_title(watershed_name)
        ax.set_xlabel('Days of the year')
        ax.set_ylabel('Years')
        
        divider = make_axes_locatable(ax)
        cax = divider.append_axes('right', size='1.25%', pad=0.1)
        cb = plt.colorbar(pc, cax=cax, orientation="vertical")
        cax.set_ylabel('Discharge [mm/day]', rotation=270, labelpad=20)
        
        fig.savefig(fig_path + '_hydro/' + '_dailydischarge_' + site_name[0] + '.png', dpi=300, bbox_inches='tight')

#%% 1 - MATRIX CLIMAT


hist = pd.DataFrame(index=dfm.index)
hist['Q'] = dfm['REC_REA_historic']
hist = select_period(hist,1960,2019)

hist['day'] = hist.index.month.values
hist['year'] = hist.index.year.values # group by month and year, get the average
hist = hist.groupby(['day','year']).apply(lambda g: g.mean(skipna=False))
hist = hist.unstack(level=0, fill_value=np.nan)
hist = hist['Q']
# hist[hist==0] = 0.001
# hist = hist.T

lims = (hist.min(), hist.max())
# vmin = np.array(lims).min()
# vmax = np.array(lims).max()
vmin = 0.001
vmax = 10
normalize = mpl.colors.Normalize(vmin=vmin, vmax=vmax)

fig, ax = plt.subplots(1,1, figsize=(2.5, 6))
colori = "jet"

import matplotlib as mpl
pc = ax.pcolormesh(hist, cmap='jet_r', vmin=vmin, vmax=vmax,
                    norm = mpl.colors.LogNorm(),
                   edgecolor='grey', lw=0.2, alpha=0.7)
                  # norm=mpl.colors.LogNorm(vmin, vmax)
                  # norm=mpl.colors.CenteredNorm()
              
xticks = np.arange(12)+0.5
ax.set_xticks(xticks)
mois = ['J','F','M','A','M','J','J','A','S','O','N','D']
ax.set_xticklabels(mois, minor=False, rotation='horizontal', fontsize=13)
# ax.xaxis.tick_top()

yticks = np.arange((hist.index[-1]+1) - hist.index[0])+0.5
years = list(hist.index.astype(str))[::5] 
ax.set_yticks(yticks[::5])
ax.set_yticklabels(years, minor=False, rotation='horizontal', fontsize=13)
# ax.invert_yaxis()
ax.tick_params(axis="x", direction='out', length=5)
ax.tick_params(axis="y", direction='out', length=5)

# divider = make_axes_locatable(ax)
# cax = divider.append_axes('right', size='1.25%', pad=0.1)
# cb = plt.colorbar(pc, cax=cax, orientation="vertical")
# cax.set_ylabel('Recharge [mm/month]', rotation=270, labelpad=20)

fig.savefig(fig_path + '_clim/' + '_monthly_recharge_bis' + '.png', dpi=300, bbox_inches='tight')

#%% 1 - STRIPES PLOT

anomaly = dfd.resample('Y').mean()
idx_df = pd.DataFrame(index=anomaly.index)
idx_df['values'] = anomaly['TAS_IPS1_historic']
idx_df['values'] = anomaly['TAS_IPS1_RCP8.5']
anomaly = idx_df.dropna()
anomaly = anomaly.resample('Y').mean()
anomaly.index = anomaly.index.year

from matplotlib.patches import Rectangle
from matplotlib.collections import PatchCollection
from matplotlib.colors import ListedColormap

cmap = ListedColormap([
    '#08306b', '#08519c', '#2171b5', '#4292c6',
    '#6baed6', '#9ecae1', '#c6dbef', '#deebf7',
    '#fee0d2', '#fcbba1', '#fc9272', '#fb6a4a',
    '#ef3b2c', '#cb181d', '#a50f15', '#67000d',
])

FIRST = 1980
LAST = 2099  # inclusive

FIRST_REFERENCE = 1980
LAST_REFERENCE = 2010
LIM = 3 # degrees

col = PatchCollection([
    Rectangle((y, 0), 1, 1)
    for y in range(FIRST, LAST + 1)
])

anomaly = anomaly.loc[FIRST:LAST, 'values'].dropna()
reference = anomaly.loc[FIRST_REFERENCE:LAST_REFERENCE].mean()

# set data, colormap and color limits

fig = plt.figure(figsize=(10, 1))

ax = fig.add_axes([0, 0, 1, 1])
ax.set_axis_off()

col.set_array(anomaly)
col.set_cmap(cmap)
col.set_clim(reference - LIM, reference + LIM)
ax.add_collection(col)
ax.set_ylim(0, 1)
ax.set_xlim(FIRST, LAST + 1)


#%% 2 - ONDE DATA

fig, ax = plt.subplots(1,1, figsize=(6,3))

onde_naming = []

onde_naming = [
'Canut',
'Boutavent',
'Rohuel',
'Grehedan',
'Meu',
'Vaunoise',
'Rance',
'Fremeur',
'Guerabouin',
'Nancon'
             ]

toget = True

compt=0
for site_name in ['Canut','Mordelles','Vaunoise','Rophemel','Roche']:

    watershed_name = site_name
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)
    area = BV.geographic.area
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
    onde_clip = stable_folder+'intermittency/onde.shp'
    
    flowing = pd.DataFrame()
    shp = gpd.read_file(onde_clip)
    
    print('##### '+watershed_name.upper()+' #####')

    shp['date'] =  pd.to_datetime(shp['<DtRealObs'], format = '%Y-%m-%d')
    shp['code_flow'] = np.nan
    dicecoul = {'Assec':1,
                'Ecoulement non visible':2,
                'Ecoulement visible faible':3,
                'Ecoulement visible acceptable':4,
                'Ecoulement visible':5}
    for i in range(len(shp)):
        shp.loc[i,'code_flow'] = dicecoul[shp.loc[i,'<LbRsObser']]


    for code in shp['<CdSiteHyd'].unique():
        
        # code = "J7380001"
        mask = (shp['<CdSiteHyd'] == code)
        raw = shp.copy()
        raw = raw[mask]

        append = raw[['date','code_flow']]
        append = append.set_index('date')
        append['compt'] = compt
        flowing = pd.concat([flowing, append], axis=1).sort_index()
                
        # onde_naming.append(lab)

        fig2, ax2 = plt.subplots(1,1, figsize=(6,0.6))
        ax2.scatter(append.index, append['compt'], c=append['code_flow'], cmap='jet_r', alpha=1,
                   vmin=1, vmax=5,
                   marker='|', s=1300, lw=4)
        ax2.set_yticklabels([''])
        lab = raw.iloc[0]['<LbSiteHyd']
        ax2.set_xlim(([pd.to_datetime('2012'), pd.to_datetime('2022')]))                  
        years = mdates.YearLocator(2)   # every year
        ax2.xaxis.set_major_locator(years)
        years_fmt = mdates.DateFormatter('%Y')
        ax2.xaxis.set_major_formatter(years_fmt)
        yearsmin = mdates.YearLocator(1)
        ax2.xaxis.set_minor_locator(yearsmin)
        ax2.grid(True, axis='x', which='both')   
        ax2.set_yticks(np.arange(0,1,1))
        # for i in np.arange(0,compt,1)+0.5:
        #     ax.axhline(i, color='k', lw=1.5)
        #     ax.set_ylim(-0.5,9.5)
        plt.tight_layout()
        ax2.set_title(onde_naming[compt], fontsize=10)
        for i in np.arange(2012,2022,1).astype(str):
            ax2.axvline(pd.to_datetime(i), color='grey', lw=1)
        ax2.xaxis.set_ticks_position('none')
        ax2.set_xticklabels('')
        ax2.tick_params(axis=u'both', which=u'both',length=0)
        
        # fig2.savefig(fig_path + '_onde/'+ onde_naming[compt] + '_onde.png', dpi=300,
        #              bbox_inches='tight', transparent=False, frameon=False)


        if toget == True:
            # fig, ax = plt.subplots(1,1, figsize=(5,2))
            ax.scatter(append.index, append['compt'], c=append['code_flow'], cmap='jet_r',
                        vmin=1, vmax=5,
                        marker='|', s=300, lw=4)
            ax.set_yticklabels([watershed_name])
            
            # try:
            #     lab = raw['<LbSiteHyd'][0]
            # except:
            lab = raw.iloc[0]['<LbSiteHyd']
                # pass
            # ax.set_title(code+' - '+lab)
            # ax.set_yticks([-1, 0, 1, 2, 3])
            # try:
            # except:
            #     ax.set_yticks([1, 2, 3, 4, 5])
            #     pass
            # ax.set_xticks(zip([-1, 0, 1, 2, 3],
            #                   ['-','Assec','Invisible','Faible','Acceptable','Visible']))
            # ax.yaxis.set_ticks(['-','Assec','Invisible','Faible','Acceptable','Visible'])
            # ax.set_ylim(0.5,5.5)
            ax.set_xlim(([pd.to_datetime('2012'), pd.to_datetime('2022')]))                  
            years = mdates.YearLocator(2)   # every year
            ax.xaxis.set_major_locator(years)
            years_fmt = mdates.DateFormatter('%Y')
            ax.xaxis.set_major_formatter(years_fmt)
            yearsmin = mdates.YearLocator(1)
            ax.xaxis.set_minor_locator(yearsmin)
            # months = mdates.MonthLocator(6)  # every month
            # months_fmt = mdates.DateFormatter('%m') #b = name of month ? 
            # ax.xaxis.set_minor_locator(months)
            ax.grid(True, axis='x', which='both')   
            plt.tight_layout()
            print(code)
       
        compt+=1

onde_naming = [
'Canut',
'Boutavent',
'Rohuel',
'Grehedan',
'Meu',
'Vaunoise',
'Rance',
'Fremeur',
'Guerabouin',
'Nancon'
             ]

ax.set_yticks(np.arange(0,compt,1))
ax.set_yticklabels(onde_naming)
for i in np.arange(0,compt,1)+0.5:
    ax.axhline(i, color='k', lw=1.5)
    ax.set_ylim(-0.5,9.5)
    
fig.savefig(fig_path + '_onde/'+ 'onde_total.png', dpi=300, bbox_inches='tight')

#%% 2 - HYSTERESIS OBS

var = 'EFF'
mod = 'REA'
sce = 'historic'

temporal = True
space = -10
norm = False

watershed_names = ['Cheze','Monfort','Nancon']

df_stats = pd.DataFrame()

for watershed_name in watershed_names :

    print('##### '+watershed_name.upper()+' #####')
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)
    area = BV.geographic.area

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    Qobs_path = glob.glob(stable_folder+'hydrometry/'+'Hydrometric_'+'*'+'.csv')[0]
    naming = Qobs_path.split('\\')[-1]
    
    Qobs = pd.read_csv(Qobs_path, sep=';', index_col=0, parse_dates=True)
    # area = float(Qobs_path.split('_')[-3])
    Qobs = Qobs.squeeze()
    Qobs = Qobs.rename('Q')
    
    # first = Qobs.first_valid_index().year+1
    # last = Qobs.last_valid_index().year-1
    
    first = 1990
    last = 2019
    
    # if watershed_name == 'Gael':
    #     first=2009
    
    Qobs = select_period(Qobs, first, last)
    Qobs = (Qobs / (area*1000000)) * (3600 * 24) * 1000 # m3/s to mm/d
    
    Cobs_path = stable_folder+'/climatic/_ALL_D.csv'
    Cobs = pd.read_csv(Cobs_path, sep=';', index_col=0, parse_dates=True)
    Cobs = Cobs[var+'_'+mod+'_'+sce]
    
    DFobs = pd.DataFrame(columns=['x','y'])
    DFobs['x'] = Cobs
    DFobs['y'] = Qobs
    first_valid_loc = DFobs[DFobs.index.month==10].apply(lambda col: col.first_valid_index()).max().year
    last_valid_loc = DFobs[DFobs.index.month==9].apply(lambda col: col.last_valid_index()).min().year
    DFobs = select_period(DFobs, first_valid_loc, last_valid_loc)
    for idx in range(len(DFobs)):
        if DFobs.index[idx].month == 10:
            DFobs = DFobs[idx:]   
            break
    DFobs = DFobs.sort_index(ascending=False)
    for idx in range(len(DFobs)):
        if DFobs.index[idx].month == 9:
            DFobs = DFobs[idx:]
            break
    DFobs = DFobs.sort_index(ascending=True)
    def very_resamp(array_like):
        if any(pd.isnull(array_like)):
            return np.nan
        else:
            return array_like.sum()
    mask = DFobs.resample("M").count() >= 27
    DFobs = DFobs.resample('M').apply(very_resamp)[mask]

    hyst = Hysteresis(DFobs, watershed_name)
    hyst.prepare_xy_raw()
    hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
    
    columns_x = hyst.xrecapl.columns
    columns_y = hyst.yrecapl.columns
    
    sce_list = ['historic']
    sce_cmap = ['RdBu_r']
    # cmaplist = ['cyan','red']
    # cmap = mpl.colors.LinearSegmentedColormap.from_list(
    #     'Custom cmap', cmaplist)
    # sce_cmap = [cmap]
    sce_color = ['k']
    cmap_dict = dict(zip(sce_list, sce_cmap))
    color_dict = dict(zip(sce_list, sce_color))
    
    n = len(columns_x)
    cmap = cmap_dict[sce]
    cmap_color = plt.get_cmap(cmap)(np.linspace(0, 1, n))
    color = color_dict[sce]
    
    dfevol = hyst.dfmet.iloc[:-1]
    dfevol = dfevol.set_index(pd.to_datetime(dfevol.index, format='%Y'))
    dfmean = hyst.dfmet.iloc[-1]
    transp = pd.DataFrame(dfmean).transpose()
    
    ######################### FIG ######################### 

    fig, axs = plt.subplots(1,3, figsize=(10,3))
    fig.add_subplot(111, frameon=False)
    plt.tick_params(labelcolor='none', top=False, bottom=False, left=False, right=False)
    axs = axs.ravel()
    x_label = var + ' [mm]'
    y_label='Q [mm]'
    x_lim=[-150,150]
    y_lim=[0,150]
        
    ######################### AX 1 #########################    
    ax = axs[0]
    # ax.grid(zorder=-1000)
    scat = ax.scatter(hyst.x, hyst.y, c=hyst.wy, cmap='jet', marker="o", 
                      s=10, vmin=1, vmax=12, alpha=0.75, ec='none', zorder=-2)
    ax.plot(hyst.xi, hyst.yi, marker="o", markersize=9, markeredgecolor='black', 
            markerfacecolor='white', linestyle = 'None') 
    for k in hyst.wyi:
        ax.annotate(k,(hyst.xi[k],hyst.yi[k]), family='sans-serif', fontsize=5, 
                    color='black', weight="bold", ha='center', va='center')
    # maxi = max(max(x_lim),max(y_lim))
    # mini = min(min(x_lim),min(y_lim))
    # ax.plot((mini,maxi), (mini,maxi), 
    #             linestyle='-', color='grey', linewidth=1.5, zorder=-1)
    # ax.plot(np.linspace(*ax.get_xlim()), np.linspace(*ax.get_xlim()), 
    #         linestyle='-', color='grey', linewidth=1.5, zorder=0)
    ax.plot(np.linspace(0.1,max(x_lim),50), np.linspace(0.1,max(x_lim),50), 
            linestyle='-', color='grey', linewidth=1.5, zorder=-1)
    ax.errorbar(hyst.xi, hyst.yi,
                yerr=np.vstack([hyst.yi-hyst.ye.q25, hyst.ye.q75-hyst.yi]),
                xerr=np.vstack([hyst.xi-hyst.xe.q25, hyst.xe.q75-hyst.xi]),
                ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
                capthick=0.5, zorder=1)
    ax.plot(hyst.xiline, hyst.yiline, linestyle = '-', lw=1.5, color='k', zorder=-1)
    # if i == 0:
    #     ax.set_ylabel(y_label)
    #     ax.set_title(hyst.name)
    # else:
    #     ax.set_title(str(hyst.first)+'-'+str(hyst.last))
    ax.set_xlim(x_lim[0], x_lim[1])
    ax.set_ylim(y_lim[0]+0.1, y_lim[1])
    ax.set_xticks(np.linspace(x_lim[0], x_lim[1], 5))
    ax.set_yticks(np.linspace(y_lim[0]+0.1, y_lim[1], 5))
    ax.set_yscale('log')
    plt.tight_layout()
    # position = fig1.add_axes([0.95,0.32,0.02,0.5])
    # cb = plt.colorbar(scat,cax=position)
    # x1 = [1,2,3,4,5,6,7,8,9,10,11,12]
    # squad = ['Oct','Nov','Dec','Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep']
    # cb.set_ticks(x1)
    # cb.set_ticklabels(squad)
    # cb.ax.tick_params(labelsize=10)
    # cb.update_ticks()
    # ax.set_xlabel('P - E')
    # ax.set_ylabel('Q / A')

    ######################### AX 2 #########################
     
    ax = axs[2]
    # ax.grid(zorder=-1000)
    for i, (colx, coly) in enumerate(zip(columns_x, columns_y)):
        # print(colx)
        data = pd.DataFrame()
        data['inx'] = hyst.xrecapl[colx]
        data['iny'] = hyst.yrecapl[coly]
        ax.plot(data.inx, data.iny, linestyle = '-', lw=1.5, color=cmap_color[i],
                alpha=1, zorder=0)
    ax.plot(data.inx, data.iny, linestyle = '-', lw=1.5, color=color, zorder=2)
    maxi = max(max(ax.get_xlim()),max(ax.get_ylim()))
    mini = min(min(ax.get_xlim()),min(ax.get_ylim()))
    ax.plot(np.linspace(0.1,max(x_lim),50), np.linspace(0.1,max(x_lim),50), 
            linestyle='-', color='grey', linewidth=1.5, zorder=-1)
    ax.set_yscale('log')
    # if temporal==True:
        # ax.set_title(str(abs(space))+' - years moving')
    # ax.set_xlim(x_lim[0], x_lim[1])
    # ax.set_ylim(y_lim[0]+0.1, y_lim[1])
    # ax.set_xticks(np.linspace(x_lim[0], x_lim[1], 5))
    # ax.set_yticks(np.linspace(y_lim[0]+0.1, y_lim[1], 5))
    # ax.set_xlabel('P - E')
    # ax.set_ylabel('Q / A')
    ax.set_xlim(-100, 100)
    ax.set_ylim(0.5, 100)
    # ax.set_xticks(np.linspace(x_lim[0], x_lim[1], 5))

    ######################### AX 3 #########################

    ax3 = axs[1]
    # ax3.grid(zorder=-1000)
    x = hyst.x.diff() #/ 1e6 # *1000
    y = hyst.y.diff()
    c = hyst.wy
    wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                            [1,2,3,4,5,6,7,8,9,10,11,12])

    xi = x.groupby([lambda x: x.month]).mean()
    yi = y.groupby([lambda y: y.month]).mean()
    
    xiline = xi.append(xi.iloc[[0]])
    xiline.index = np.arange(1,14,1)
    yiline = yi.append(yi.iloc[[0]])
    yiline.index = np.arange(1,14,1)
    
    
    # year = 2018
    # spe_year_x = select_period(x, year, year)
    # spe_year_y = select_period(y, year, year)
    # xiline_spe = spe_year_x.append(spe_year_x.iloc[[0]])
    # xiline_spe.index = np.arange(1,14,1)
    # yiline_spe = spe_year_y.append(spe_year_y.iloc[[0]])
    # yiline_spe.index = np.arange(1,14,1)
    # ax3.plot(xiline_spe, yiline_spe, linestyle = '-', lw=1.5, color='red', zorder=0)
    # year = 2002
    # spe_year_x = select_period(x, year, year)
    # spe_year_y = select_period(y, year, year)
    # xiline_spe = spe_year_x.append(spe_year_x.iloc[[0]])
    # xiline_spe.index = np.arange(1,14,1)
    # yiline_spe = spe_year_y.append(spe_year_y.iloc[[0]])
    # yiline_spe.index = np.arange(1,14,1)
    # ax3.plot(xiline_spe, yiline_spe, linestyle = '-', lw=1.5, color='blue', zorder=0)
    
    
    # xt = xiline.diff()
    # yt = yiline.diff()
    
    cmapping = 'jet'
    ax3.scatter((x) , (y), c=wy, marker='o', cmap=cmapping,
                s=10, vmin=1, vmax=12, alpha=0.75, ec='none', lw=0.2, zorder=-1)
    # ax3.scatter(xt, yt)
    
    xi = xiline.diff()
    xi.iloc[0] = xi.iloc[-1]
    xi = xi[:-1]
    yi = yiline.diff()
    yi.iloc[0] = yi.iloc[-1]
    yi = yi[:-1]
              
    # ax3.plot(xi, yi, linestyle = '-', lw=1.5, color=coul, zorder=0)

    wyi = np.arange(1,12+1,1)
    wyi = pd.Series(wyi).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                 [1,2,3,4,5,6,7,8,9,10,11,12])
    
    ax3.scatter(xi, yi, c=wyi, marker='o', cmap=cmapping,
                s=35, vmin=1, vmax=12, alpha=1, 
                ec='k', lw = 0.5)

    cl = mpl.cm.jet(np.linspace(0,1,len(wyi)))
    compt = 2
    wyi = np.arange(1,12+1,1)
    for k in wyi:
        ax3.annotate(k,(xi[k],yi[k]), family='sans-serif',
                     fontsize=5, 
                      color='black', weight="bold", ha='center', va='center',
                      zorder=compt)
        ax3.plot(xi[k], yi[k], marker='o', lw=2, markersize=9,
                  markeredgecolor='black', 
                    markerfacecolor='white', markeredgewidth=1,
                    linestyle = 'None', zorder=compt) # cl[k-1]
        compt+=1
        
    ax3.axhline(y=0, color='k', zorder=-1, ls='--')
    ax3.axvline(x=0, color='k', zorder=-1, ls='--')
    ax3.set_xlim(-150, 150)
    ax3.set_xticks(np.linspace(x_lim[0], x_lim[1], 5))
    ax3.set_ylim(-100, 100)
    
    # ax3.set_xlabel('\u0394 P - E')
    # ax3.set_ylabel('\u0394 Q / A')
    
    ax3.plot(np.linspace(min(x_lim),max(x_lim),50), np.linspace(min(x_lim),max(x_lim),50), 
            linestyle='-', color='grey', linewidth=1.5, zorder=-1)
    
    plt.tight_layout()
    
    fig.savefig(fig_path + '_hyst/'+ watershed_name + '.png', dpi=300, bbox_inches='tight')
    
    ######################### FIG BIS ######################### 

    fig_b, ax3 = plt.subplots(1,1, figsize=(3,3))
    
    # ax3.grid(zorder=-1000)
    x = hyst.x.diff() #/ 1e6 # *1000
    y = hyst.y.diff()
    c = hyst.wy
    wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                            [1,2,3,4,5,6,7,8,9,10,11,12])

    xi = x.groupby([lambda x: x.month]).mean()
    yi = y.groupby([lambda y: y.month]).mean()
    
    xiline = xi.append(xi.iloc[[0]])
    xiline.index = np.arange(1,14,1)
    yiline = yi.append(yi.iloc[[0]])
    yiline.index = np.arange(1,14,1)
    
    
    # year = 2016
    # spe_year_x = select_period(x, year, year)
    # spe_year_y = select_period(y, year, year)
    # xiline_spe = spe_year_x.append(spe_year_x.iloc[[0]])
    # xiline_spe.index = np.arange(1,14,1)
    # yiline_spe = spe_year_y.append(spe_year_y.iloc[[0]])
    # yiline_spe.index = np.arange(1,14,1)
    # ax3.plot(xiline_spe, yiline_spe, linestyle = '-', lw=1.5, color='red', zorder=0)
    # year = 2001
    # spe_year_x = select_period(x, year, year)
    # spe_year_y = select_period(y, year, year)
    # xiline_spe = spe_year_x.append(spe_year_x.iloc[[0]])
    # xiline_spe.index = np.arange(1,14,1)
    # yiline_spe = spe_year_y.append(spe_year_y.iloc[[0]])
    # yiline_spe.index = np.arange(1,14,1)
    # ax3.plot(xiline_spe, yiline_spe, linestyle = '-', lw=1.5, color='b', zorder=0)
    
    
    # xt = xiline.diff()
    # yt = yiline.diff()
    
    cmapping = 'jet'
    ax3.scatter((x) , (y), c=wy, marker='o', cmap=cmapping,
                s=10, vmin=1, vmax=12, alpha=0.75, ec='none', lw=0.2, zorder=-1)
    # ax3.scatter(xt, yt)
    
    xi = xiline.diff()
    xi.iloc[0] = xi.iloc[-1]
    xi = xi[:-1]
    yi = yiline.diff()
    yi.iloc[0] = yi.iloc[-1]
    yi = yi[:-1]
              
    # ax3.plot(xi, yi, linestyle = '-', lw=1.5, color=coul, zorder=0)

    wyi = np.arange(1,12+1,1)
    wyi = pd.Series(wyi).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                 [1,2,3,4,5,6,7,8,9,10,11,12])
    
    ax3.scatter(xi, yi, c=wyi, marker='o', cmap=cmapping,
                s=35, vmin=1, vmax=12, alpha=1, 
                ec='k', lw = 0.5)

    cl = mpl.cm.jet(np.linspace(0,1,len(wyi)))
    compt = 2
    wyi = np.arange(1,12+1,1)
    for k in wyi:
        ax3.annotate(k,(xi[k],yi[k]), family='sans-serif',
                     fontsize=5, 
                      color='black', weight="bold", ha='center', va='center',
                      zorder=compt)
        ax3.plot(xi[k], yi[k], marker='o', lw=2, markersize=9,
                  markeredgecolor='black', 
                    markerfacecolor='white', markeredgewidth=1,
                    linestyle = 'None', zorder=compt) # cl[k-1]
        compt+=1
        
    ax3.axhline(y=0, color='k', zorder=-1, ls='--')
    ax3.axvline(x=0, color='k', zorder=-1, ls='--')
    ax3.set_xlim(-50, 50)
    ax3.set_xticks(np.linspace(-50, 50, 5))
    ax3.set_ylim(-50, 50)
    ax3.set_yticks(np.linspace(-50, 50, 5))
    
    # ax3.set_xlabel('\u0394 P - E')
    # ax3.set_ylabel('\u0394 Q / A')
    
    ax3.plot(np.linspace(min(x_lim),max(x_lim),50), np.linspace(min(x_lim),max(x_lim),50), 
            linestyle='-', color='grey', linewidth=1.5, zorder=-1)
    
    plt.tight_layout()
    
    fig_b.savefig(fig_path + '_hyst/'+ watershed_name + '_bis' + '.png',
                  dpi=300, bbox_inches='tight')
    
    df_stats[watershed_name] = dfmean
    
    dfevol.to_csv(fig_path + '_hyst/'+ watershed_name + '_df_evol' + '.csv',
                    sep=';')

df_stats.to_csv(fig_path + '_hyst/'+ '_recap_df_mean' + '.csv',
                sep=';')

#%% 2 - HYSTERESIS STATS

watershed_names = ['Cheze','Monfort','Nancon']


sce_color = ['forestgreen','darkorange','red']
color_dict = dict(zip(watershed_names, sce_color))

df_stats = pd.read_csv(fig_path + '_hyst/'+ '_recap_df_mean' + '.csv',
                sep=';', index_col=0)

fig, ax = plt.subplots(1,1, figsize=(7,4))

for watershed_name in watershed_names :

    print('##### '+watershed_name.upper()+' #####')
    
    dfevol = pd.read_csv(fig_path + '_hyst/'+ watershed_name + '_df_evol' + '.csv',
                    sep=';', index_col=0, parse_dates=True)
    
    col = 'q10'
    ax.plot(dfevol[col], lw=3, c = color_dict[watershed_name])
    ax.set_title(col.upper())

#%% 2 - EVOLUTION ANNUAL

for watershed_name in ['Frame']:
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'

# for watershed_name in ['Cheze']:
#     stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'

time_step = 'Y'

variables = ['REC', 'RUN', 'ETP', 'PPT', 'TAS','EFF']
scenarios = ['historic','RCP2.6','RCP8.5']
simulations = 'ACC1|BCC1|BNU1|CAN1|CNR1|CSI1|IPS1|MIR1|NOR1'
# simulations = 'TOT1'

variables = ['PPT']
simulations = 'MPI-CCL|ECE-RCA|ECE-RAC|CNR-RAC|NOR-R15|CNR-ALA|HAD-REG|MPI-R09'
# simulations = 'NOR-R15'
simulations = 'ECE-RCA|ECE-RAC|HAD-REG|NOR-R15|MPI-CCL|MPI-R09|CNR-RAC|CNR-ALA|IPS-WRF|HAD-CCL|IPS-RCA|NOR-HIR'

# variables = ['REC']

sce_colors=["dimgrey","dodgerblue","red"]
line_colors=["k","navy","darkred"]
color_dict = dict(zip(scenarios, sce_colors))
line_dict = dict(zip(scenarios, line_colors))

df_fil = dfd.copy()
df_fil = df_fil.resample('Y').mean()
# df_fil = df_fil.resample('Y').sum()
df_fil = df_fil.filter(regex=(simulations))

for var in variables:
    fig, ax = plt.subplots(1,1, figsize=(6,3))
    cp = 0
    for sce in scenarios:
        dfb = df_fil.filter(regex=var)
        dfb = dfb.filter(regex=sce)        
        if sce == 'historic':
            dfb = dfb[(dfb.index.year >= 1960) & (dfb.index.year <= 2009)]
        else:
            dfb = dfb[(dfb.index.year >= 2009) & (dfb.index.year <= 2099)]
        dfs = pd.DataFrame(index=dfb.index)
        
        dfb = dfb.rolling(window=10).mean()
        # ax.plot(dfb, lw=0.2, color=color_dict[sce])
        dfs['MEAN'] = dfb.mean(axis=1)
        dfs['MIN'] = dfb.min(axis=1)
        dfs['MAX'] = dfb.max(axis=1)
        dfs['Q25'] = dfb.quantile(q=0.25, axis=1)
        dfs['Q50'] = dfb.quantile(q=0.50, axis=1)
        dfs['Q75'] = dfb.quantile(q=0.75, axis=1)
        if var != 'TAS':
            dfs = dfs * 365
        # ax.vlines(dfs.index, dfs['MIN'], dfs['MAX'], color=color_dict[sce], alpha=0.5)
        # ax.vlines(dfs.index, dfs['Q25'], dfs['Q75'], lw=1, color=color_dict[sce])
        # ax.plot(dfs['MEAN'], marker='o', lw=1, markersize=2, mec='none',
        #         color=color_dict[sce])
        if sce == 'RCP2.6':
            zord = 20
        else:
            zord = 0
        ax.fill_between(dfs.index, dfs['Q25'], dfs['Q75'], color=color_dict[sce], alpha=0.25,
                        edgecolor='k', zorder=cp)
        ax.plot(dfs['Q50'], lw=2, marker='o', markersize=0,
                markeredgecolor='none', color=line_dict[sce], label=sce,
                zorder=cp)
        ax.set_xlim(pd.to_datetime('1960'), pd.to_datetime('2100'))
        ax.set_title(var)
        if var == 'EFF':
            ax.axhline(y=0, color='k', zorder=-10)
        # ax.legend(loc='upper left')
        # ax.axvline(pd.to_datetime('2010'), color='k', ls='--', lw=0.5)
        # if sce != 'historic':
        #     ax.axhline(y=dfs['MEAN'][(dfs.index.year >= 2050) & (dfs.index.year <= 2099)].mean(), color=color_dict[sce])
        # else:
        #     ax.axhline(y=dfs['MEAN'].mean(), color=color_dict[sce])
        from datetime import date
        # ax.axvline(date.today(), color='k', ls='-', lw=0.5)
        ax.set_axisbelow(True)
        # ax.grid(zorder=-1000)
        ax.xaxis.grid(color='gray', alpha=0.2, zorder=-20)
        ax.yaxis.grid(color='gray', alpha=0.2, zorder=-20)
        
        cp+=1
        
        # fig.savefig(fig_path + 'evolution_annual_' + var + '.png', dpi=300, bbox_inches='tight')
        
#%% 2 - EVOLUTION SEASON

typ_climate = 'DRIAS'
typ_climate = 'SURFEX'

time_step = 'M'

variables = ['REC', 'RUN', 'ETP', 'PPT', 'TAS','EFF']
scenarios = ['historic','RCP2.6','RCP8.5']
# simulations = 'ACC1|BCC1|BNU1|CAN1|CNR1|CSI1|IPS1|MIR1|NOR1'
# simulations = 'IPS1'
# variables = ['ETP']
simulations = 'MPI-CCL|ECE-RCA|ECE-RAC|CNR-RAC|NOR-R15|CNR-ALA|HAD-REG|MPI-R09'

# simulations = 'ECE-RCA|ECE-RAC|HAD-REG|NOR-R15|MPI-CCL|MPI-R09|CNR-RAC|CNR-ALA|IPS-WRF|HAD-CCL|IPS-RCA|NOR-HIR'
simulations = 'ACC1|BCC1|BNU1|CAN1|CAN2|CAN3|CAN4|CAN5|CNR1|CSI1|IPS1|MIR1|MIR2|MIR3|NOR1'

# variables = ['REC']

sce_colors=["dimgrey","dodgerblue","red"]
line_colors=["k","navy","darkred"]
color_dict = dict(zip(scenarios, sce_colors))
line_dict = dict(zip(scenarios, line_colors))

seasons = ['1,2,3,4,5,6,7,8,9,10,11,12',
           '9,10,11',
           '12,1,2',
           '3,4,5',
           '6,7,8']
# seasons = ['1,2,3,4,5,6,7,8,9,10,11,12']
# seasons = ['12,11,2']
string = ['ANN','SON','DJF','MAM','JJA']
seas_dict = dict(zip(seasons, string))

space = 10

for var in variables:
    fig, axs = plt.subplots(1,5, figsize=(22,3))
    axs = axs.ravel()
    
    df_fil = dfd.copy()
    df_fil = df_fil.dropna(axis=1, how='all')
    if var != 'TAS':
        df_fil = df_fil.resample('M').sum()
    else:
        df_fil = df_fil.resample('M').mean()
        
    df_fil = df_fil.filter(regex=(simulations))

    for i, sea in enumerate(seasons):
        ax = axs[i]
        for sce in scenarios:
            dfb = df_fil.filter(regex=var)
            dfb = dfb.filter(regex=sce)
            # if sce == 'historic':
                # dfb = dfb[(dfb.index.year >= 1960) & (dfb.index.year <= 2009)]
                
                # rea = dfb['REA_historic']
                # rea = rea.groupby([(rea.index.year),(rea.index.month)]).mean()
                # rea = rea.rename_axis(["year", "month"]).to_frame()
                # rea = rea.query("month == "+"["+sea+"]")
                # rea = rea.groupby('year').sum()
                # rea.index =  pd.to_datetime(rea.index, format='%Y')
            
            if typ_climate == 'SURFEX':
                # else:
                if sce == 'historic':
                    dfb = dfb[(dfb.index.year >= 1960) & (dfb.index.year <= 2005)]
                else:
                    dfb = dfb[(dfb.index.year >= 2005) & (dfb.index.year <= 2099)]
            
            if typ_climate == 'DRIAS':
                # else:
                if sce == 'historic':
                    dfb = dfb[(dfb.index.year >= 1975) & (dfb.index.year <= 2005)]
                else:
                    dfb = dfb[(dfb.index.year >= 2005) & (dfb.index.year <= 2100)]    
            
            dfb = dfb.groupby([(dfb.index.year),(dfb.index.month)]).mean()
            dfb = dfb.rename_axis(["year", "month"])
            
            dfb = dfb.query("month == "+"["+sea+"]")
            # dfb = dfb.dropna()
            if var == 'TAS':
                dfb = dfb.groupby('year').apply(lambda g: g.mean(skipna=False))
            else:
                dfb = dfb.groupby('year').apply(lambda g: g.sum(skipna=False))

            dfb.index =  pd.to_datetime(dfb.index, format='%Y')
            
            dfs = pd.DataFrame(index=dfb.index)
            
            dfb = dfb.rolling(window=space).mean() # .shift(-space)
            
            # ax.plot(dfb, lw=0.1, color=color_dict[sce])
            dfs['MEAN'] = np.nanmean(dfb, axis=1)
            dfs['MIN'] = dfb.min(axis=1)
            dfs['MAX'] = dfb.max(axis=1)
            dfs['Q25'] = dfb.quantile(q=0.25, axis=1)
            dfs['Q50'] = dfb.quantile(q=0.50, axis=1)
            dfs['Q75'] = dfb.quantile(q=0.75, axis=1)
            dfs['STD'] = dfb.std(axis=1)
            dfs = dfs.iloc[1:-1]
            
            # if var != 'TAS':
            #     if i == 0:
            #         dfs = dfs * 365
            
            # dfs = dfs.rolling(window=space).mean().shift(-space)
            
            if sce == 'RCP2.6':
                zord = 20
            else:
                zord = 0
            
            # ax.plot(rea, ls='-', color='k', lw=0.25)
            ax.fill_between(dfs.index, dfs['Q25'], dfs['Q75'], color=color_dict[sce], 
                            alpha=0.2, edgecolor='k', zorder=0)
            # ax.plot(dfs['Q50'], lw=1, color=color_dict[sce], label=sce)
            # ax.fill_between(dfs.index, dfs.MEAN-dfs['STD'], dfs.MEAN+dfs['STD'], color=color_dict[sce], alpha=0.2, edgecolor='none')
            ax.plot(dfs['Q50'], lw=2, color=line_dict[sce], label=sce, zorder=1-zord)
            ax.set_xlim(pd.to_datetime('1960'), pd.to_datetime('2100'))
            ax.set_title(seas_dict[sea])
            # ax.legend(loc='upper left')
            # ax.axvline(pd.to_datetime('2010'), color='k', ls='--')
            from datetime import date
            # ax.axvline(date.today(), color='k', ls='-')
            if typ_climate == 'SURFEX':
                ax.axvline(pd.to_datetime('1969'), color='dimgray', ls='--')
                ax.axvline(pd.to_datetime('2004'), color='dimgray', ls='--')
                ax.axvline(pd.to_datetime('2014'), color='dimgray', ls='--')
            if typ_climate == 'DRIAS':
                ax.axvline(pd.to_datetime('1984'), color='dimgray', ls='--')
                ax.axvline(pd.to_datetime('2004'), color='dimgray', ls='--')
                ax.axvline(pd.to_datetime('2014'), color='dimgray', ls='--')
                ax.set_xlim(pd.to_datetime('1975'))
            
            # ax.axvline(dfs.first_valid_index(), color='grey', ls='-', lw=0.1)
            # ax.axvline(dfs.last_valid_index(), color='grey', ls='-', lw=0.1)
            # ax.text(dfs.first_valid_index(),0.8, str(dfs.first_valid_index().year), rotation=90,
            #         transform=ax.get_xaxis_transform())
            
            ax.set_axisbelow(True)
            # ax.grid(zorder=-1000)
            ax.xaxis.grid(color='gray', alpha=0.2, zorder=-20)
            ax.yaxis.grid(color='gray', alpha=0.2, zorder=-20)
            
            from pylab import MaxNLocator
            
            ya = ax.get_yaxis()
            ya.set_major_locator(MaxNLocator(integer=True))   
            
            from matplotlib import ticker
            M = 5
            yticks = ticker.MaxNLocator(M)
                     
            # Set the yaxis major locator using your ticker object. You can also choose the minor
            # tick positions with set_minor_locator.
            ax.yaxis.set_major_locator(yticks)
            
            yearsmaj = mdates.YearLocator(20)   # every year
            # yearsmin = mdates.YearLocator(years_min)
            # monthsmaj = mdates.MonthLocator(6)  # every month
            # monthsmin = mdates.MonthLocator(3)
            # months_fmt = mdates.DateFormatter('%m') #b = name of month ?
            # years_fmt = mdates.DateFormatter('%Y')
            # ax.xaxis.set_major_locator(yearsmaj)
            # ax.xaxis.set_minor_locator(yearsmin)
            # ax.xaxis.set_major_formatter(years_fmt)
            
            fig.suptitle(var)
            plt.tight_layout()
            
    if typ_climate == 'SURFEX':
        fig.savefig(fig_path + 'evolution_seasonnal_' + var + '.png', dpi=300, bbox_inches='tight')
    # else:
    #     fig.savefig(fig_path + '_recharge/recharge_models_with_26&85' + var + '.png', dpi=300, bbox_inches='tight')

#%% 2 - EVOLUTION MENSUAL

dfd = both.copy()

models = ['MPI-CCL','ECE-RCA','ECE-RAC','CNR-RAC',
          'NOR-R15','CNR-ALA','HAD-REG','MPI-R09']
# models = ['ACC1','BCC1','BNU1','CAN1','CSI1','IPS1','MIR1','NOR1']

# models = ['MPI-CCL']

import matplotlib.ticker as ticker

var = 'REC'
scenarios = ['RCP2.6','RCP8.5']

ref = [1980,2010]
per = [[2010,2040],[2040,2070],[2070,2100]]

for mod in models:
    
    his = dfd[(dfd.index.year>=1980) & (dfd.index.year<=2010)].filter(regex='historic')
    pro = dfd[(dfd.index.year>=2010) & (dfd.index.year<=2099)].filter(regex='RCP')

    hist = his.copy()
    hist = hist[(hist.index.year>=ref[0]) & (hist.index.year<=ref[1])]
    hist = hist[var+'_'+mod+'_'+'historic'].to_frame()
    hist = hist.resample('M').sum()[hist.resample("M").count() >= 27]
    hist_intm = hist.groupby([lambda x: x.month]).mean()
    
    horiz = len(per)
    # fig, axs = plt.subplots(1, horiz, figsize=(horiz*4, 3))
    fig, axs = plt.subplots(1, horiz, figsize=(12, 3))
    axs = axs.ravel()    
    
    lims = []
    
    for sce in scenarios:
        compt=0
        for p in per:
            fut = pro.copy()
            fut = fut[(fut.index.year>=p[0]) & (fut.index.year<=p[1])]
            fut = fut[var+'_'+mod+'_'+sce].to_frame()
            fut = fut.resample('M').sum()[fut.resample("M").count() >= 27]
            fut_intm = fut.groupby([lambda x: x.month]).mean()
        
            ano = (fut_intm - hist_intm.values)
            lims.append(ano.min())
            lims.append(ano.max())
        
            ax = axs[compt]
            
            name = sce+'_'+str(p[0])+'-'+str(p[1])
            
            mean = ano.values.mean() / hist_intm.mean().values[0] * 100
    
            if sce=='RCP2.6':
                colori = 'dodgerblue'
                coledge='navy'
                space = -0.20
                x = 0.20
            # if sce=='RCP4.5':
            #     colori = 'forestgreen'
            #     space = -0.10
            #     x = 0.5
            # if sce=='RCP6.0':
            #     colori = 'darkorange'
            #     space = +0.10
            #     x = 0.7
            if sce=='RCP8.5':
                colori = 'red'
                coledge = 'darkred'
                space = +0.20
                x = 0.8
            
            y=0.1
            ax.text(x, y, 
                r'$\bar{x}$'+ ' = '+str(mean.round(1))+' %',
                fontsize=14, ha='center', va='center', color=colori,
                weight="bold",
                transform=ax.transAxes)
            
            ax.bar(ano.index+(space), ano[var+'_'+mod+'_'+sce], 
                   width=0.35, align='center', color=colori, 
                   edgecolor=coledge, label=sce)
            ax.axhline(y=0, linewidth=1, color='k')
        
            x1 = [1,2,3,4,5,6,7,8,9,10,11,12]
            squad = ['J','F','M','A','M','J','J','A','S','O','N','D']
            ax.set_xticks(x1)
            ax.set_xticklabels(squad, minor=False, rotation='horizontal')
            plt.xticks(rotation='horizontal')
            ax.set_xlim(0.5,12.5)
            ax.set_ylim(-15,15)
            minorXlocator = ticker.MultipleLocator(0.5)
            ax.xaxis.set_minor_locator(minorXlocator)
            ax.grid(True, which='minor')
            ax.set_title('Period : '+str(p[0])+'-'+str(p[1]), 
                         fontproperties=fontprop, fontsize=13)                
            # ax.set_xlabel('Months', fontproperties=fontprop)
            
            # if compt==0:
            #     if var == 'TAS':
            #         ax.set_ylabel(var + ' [°C]')
            #     else:
            #         ax.set_ylabel(var + ' [mm/mois]')
            #     ax.legend()
            
            compt+=1
    
    compt = 0
    for i in range(len(per)):
        ax = axs[compt]
        vmin = round(np.array(lims).min(),2)
        vmax = round(np.array(lims).max(),2)
        # ax.set_ylim(vmin, vmax)
    
    plt.suptitle('MODEL : '+mod+' - '+'ANOMALY HISTORIC : '+str(ref[0])+'-'+str(ref[1]),
                 fontproperties=fontprop, fontsize=14, y=0.98)
    plt.tight_layout()
    
    # fig.savefig(fig_path + '_ppt/evolution_mensual_' + mod + '_' + var + '.png', dpi=300, bbox_inches='tight')
    fig.savefig(fig_path + 'evolution_mensual_' + mod + '_' + var + '.png', dpi=300, bbox_inches='tight')


#%% 3 - BILAN HW LW

typ_climate = 'DRIAS'
# typ_climate = 'SURFEX'

if typ_climate == 'SURFEX':
    mod = 'TOT'
if typ_climate == 'DRIAS':
    mod = 'EXP'

sce = 'RCP8.5'

perio = ['10,11,12,1,2,3','4,5,6,7,8,9']
string = ['HW','LW']
seas_dict = dict(zip(perio, string))

space = 10

# bilan = rech_sum['pe_mmm_'+rcp].values + etiag_sum['pe_mmm_'+rcp].values
# mpl.colors.ListedColormap(['k'])

fig, ax = plt.subplots(1,1,figsize=(4, 4))
cmap = ['Greens','Oranges']

rea_hw, rea_lw = sum_hwlw(rea)
rea_bil = [rea_hw, rea_lw]

for i, j in enumerate([hw,lw]):

    j = j.filter(regex=mod)
    x = j[['EFF'+'_'+mod+'_'+'historic', 'EFF'+'_'+mod+'_'+sce]].mean(axis=1) * 365
    # x = j[['PPT'+'_'+mod+'_'+'historic', 'PPT'+'_'+mod+'_'+sce]].mean(axis=1) * 365


    y = j[['TAS'+'_'+mod+'_'+'historic', 'TAS'+'_'+mod+'_'+sce]].mean(axis=1)
    n = j.index.year
    scat = ax.scatter(x, y, c=n, cmap=cmap[i], marker="o", s=150, zorder=1, lw=0.5,
                      alpha=1)

    k = rea_bil[i].filter(regex='REA')
    x = k['EFF'+'_'+'REA'+'_'+'historic'] * 365

    # x = k['PPT'+'_'+'REA'+'_'+'historic'] * 365
    y = k['TAS'+'_'+'REA'+'_'+'historic']
    n = k.index.year
    
    if typ_climate == 'SURFEX':
        ax.scatter(x, y, c=n, cmap=mpl.colors.ListedColormap(['k']), marker="o", s=5, zorder=1, lw=0.5,
                    alpha=1)

    if i==0:
        pos1 = fig.add_axes([0.93,0.25,0.02,0.5])
        plt.tick_params(labelcolor='none', top=False, bottom=False, left=False, right=False)
        cb = plt.colorbar(scat,cax=pos1)
        x1 = np.arange(1960,2100,40)
        squad = np.arange(1960,2100,40).astype(str)
        cb.set_ticks(x1)
        cb.set_ticklabels(squad)
        cb.ax.tick_params(labelsize=10)
        cb.update_ticks()
        plt.gca().get_xaxis().set_visible(False)
        plt.gca().get_yaxis().set_visible(False)
    
    if i==1:
        pos2 = fig.add_axes([0.98,0.25,0.02,0.5])
        cb = plt.colorbar(scat,cax=pos2)
        x1 = np.arange(1960,2100,40)
        squad = np.arange(1960,2100,40).astype(str)
        cb.set_ticks(x1)
        cb.set_ticklabels(squad)
        cb.ax.tick_params(labelsize=10)
        cb.update_ticks()
    
ax.set_title('LW - HW')
ax.axvline(x=0,color='k',ls='--', zorder=-1)    
ax.set_xlabel('Precipitation - Evapotranspiration [mm]', labelpad = +15)
ax.set_ylabel('Temperature [°C]', labelpad = +15)

if typ_climate == 'SURFEX':
    ax.set_xlim(-1000,1000)
if typ_climate == 'DRIAS':
    ax.set_xlim(-500, 1000)
    ax.set_xticks([-500, 0, 500, 1000])
    
# ax.set_axisbelow(True)
# # ax.grid(zorder=-1000)
# ax.xaxis.grid(color='gray', alpha=0.2, zorder=-20)
# ax.yaxis.grid(color='gray', alpha=0.2, zorder=-20, which='both')

fig.savefig(fig_path+'BILAN HW LW'+'_'+mod+'.png', dpi=300, bbox_inches='tight')

# ax.set_xticks(np.arange(-600,1100,400))
# ax.set_xlim(-600,1000)
# ax.set_ylim(8.5,15)
# ax.spines['right'].set_visible(False)
# ax.spines['top'].set_visible(False)
# tick = np.arange(min(y), max(y)+1, 1.0)
# ax.set_yticklabels(tick.astype(int))
# ax.yaxis.set_major_locator(MaxNLocator(integer=True))
# ax.yaxis.set_ticks_position('left')
# ax.xaxis.set_ticks_position('bottom')
# ax.hlines(12,x.min(),x.max(), color='grey', lw=1, zorder=0)
# ax.vlines(325,y.min(),y.max(), color='grey', lw=1, zorder=0)

fig, ax = plt.subplots(1,1,figsize=(4, 4))
cmap = 'cool'

h = hw.filter(regex=mod) + lw.filter(regex=mod)
x = h[['EFF'+'_'+mod+'_'+'historic', 'EFF'+'_'+mod+'_'+sce]].mean(axis=1) * 365
y = h[['TAS'+'_'+mod+'_'+'historic', 'TAS'+'_'+mod+'_'+sce]].mean(axis=1) / 2
n = h.index.year
scat = ax.scatter(x, y, c=n, cmap=cmap, marker="o", s=100, zorder=1, lw=0.5, alpha=1)

pos1 = fig.add_axes([0.93,0.25,0.02,0.5])
cb = plt.colorbar(scat,cax=pos1)
x1 = np.arange(1960,2100,40)
squad = np.arange(1960,2100,40).astype(str)
cb.set_ticks(x1)
cb.set_ticklabels(squad)
cb.ax.tick_params(labelsize=10)
cb.update_ticks()
if typ_climate == 'SURFEX':
    ax.set_xlim(-500,500)
    ax.set_xticks([-500, -250, 0, 250, 500])
if typ_climate == 'DRIAS':
    ax.set_xlim(250, 750)
    ax.set_xticks([250, 500, 750])
# ax.set_xticklabels(-500, -250, 0, 250, 500)

# test = x = k[['PPT'+'_'+'REA'+'_'+'historic', 'PPT'+'_'+'REA'+'_'+'historic']].mean(axis=1) * 365
# k = hw.filter(regex='REA') + lw.filter(regex='REA')
# x = k[['EFF'+'_'+'REA'+'_'+'historic', 'EFF'+'_'+'REA'+'_'+'historic']].mean(axis=1) * 365
# y = k[['TAS'+'_'+'REA'+'_'+'historic', 'TAS'+'_'+'REA'+'_'+'historic']].mean(axis=1) / 2
# n = k.index.year
# ax.scatter(x, y, c=n, cmap=mpl.colors.ListedColormap(['k']), marker="o", s=5, zorder=1, lw=0.5,
#             alpha=1)

ax.set_title('Bilan')
ax.axvline(x=0,color='k',ls='--', zorder=-1)    
ax.set_xlabel('Precipitation - Evapotranspiration [mm]', labelpad = +15)
ax.set_ylabel('Temperature [°C]', labelpad = +15)   

fig.savefig(fig_path+'BILAN ANNUAL'+'_'+mod+'.png', dpi=300, bbox_inches='tight')

#%% 4 - DROUGHTS REA

dfd = both.copy()

# models = ['MPI-CCL','ECE-RCA','ECE-RAC','CNR-RAC',
#           'NOR-R15','CNR-ALA','HAD-REG','MPI-R09']

mod = 'REA'
# mod = 'HAD-REG'
# sce = 'RCP8.5'
sce = 'historic'
var = 'REC'
per = [1960,2019]
cond = 0

# for var in ['TAS','PPT','ETP','EFF','REC']:

# for var in ['PPT','ETP']:
for var in ['REC']:    

    if mod == 'REA':
        his = dfd[(dfd.index.year>=1960) & (dfd.index.year<=2019)].filter(regex='historic')
    else:
        his = dfd[(dfd.index.year>=1972) & (dfd.index.year<=2005)].filter(regex='historic')
    pro = dfd[(dfd.index.year>=2005) & (dfd.index.year<=2098)].filter(regex='RCP')
    
    d = pd.concat((pro.filter(regex=var+'_'+mod+'_'+sce),
                   his.filter(regex=var+'_'+mod+'_'+'historic')), axis=1).mean(axis=1)
    
    d.columns = ['values']
    d = d.round(2).squeeze().to_frame()
    d['month'] = d.index.month
    d.columns = ['values','month']
    
    d_lw = d.query("month == "+"["+'4,5,6,7,8,9'+"]")
    d_hw = d.query("month == "+"["+'10,11,12,1,2,3'+"]")
    
    years = d.index.year.unique()[:]
    data_fin = years.copy().to_frame()
    
    # cond_hw = select_period(d_hw['values'],1960,2019).min()
    # cond_lw = select_period(d_lw['values'],1960,2019).min()
    # cond_hw = select_period(d_hw['values'],1960,2019).quantile(0.05)
    # cond_lw = select_period(d_lw['values'],1960,2019).quantile(0.05)
    if (var == 'ETP') | (var=='TAS'):
        cond_hw = select_period(d_hw['values'],1960,2019).quantile(0.75)
        cond_lw = select_period(d_lw['values'],1960,2019).quantile(0.75)
    else :
        # print(var)
        cond_hw = select_period(d_hw['values'],1960,2019).quantile(0.10)
        cond_lw = select_period(d_lw['values'],1960,2019).quantile(0.10)
    # cond_hw = 5
    # cond_lw = 5
    
    counts = []
    for i, year in enumerate(years):
    
        each_hw = d_hw[d_hw.index.year==year]
        # each_hw = each_hw.resample('M').sum()
        
        each_lw = d_lw[d_lw.index.year==year]
        # each_lw = each_lw.resample('M').sum()
        
        # Method 1
        if (var == 'ETP') | (var=='TAS'): #| (var=='TAS')
            m = each_hw['values'].ge(cond_hw)
            # print(var)
        else:
            m = each_hw['values'].le(cond_hw)
        count_hw = sum(m)
        s = (m != m.shift())[m].cumsum()
        each_hw['max_cons'] = s.map(s.value_counts()).mask(~s.duplicated())
        each_hw['max_cons'] = each_hw['max_cons'].ffill().fillna(1).astype(int)
        
        if (var == 'ETP') | (var=='TAS'):
            m = each_lw['values'].ge(cond_lw)
            # print(var)
        else:
            m = each_lw['values'].le(cond_lw)
        count_lw = sum(m)
        s = (m != m.shift())[m].cumsum()
        each_lw['max_cons'] = s.map(s.value_counts()).mask(~s.duplicated())
        each_lw['max_cons'] = each_lw['max_cons'].ffill().fillna(1).astype(int)
        
        data_fin.loc[year,'max_cons_hw'] = each_hw['max_cons'].max()
        data_fin.loc[year,'max_cons_lw'] = each_lw['max_cons'].max()
        data_fin.loc[year,'max_tot_hw'] = count_hw
        data_fin.loc[year,'max_tot_lw'] = count_lw
        
        # Method 2
        # each['counter'] = each['values'].diff().le(0).cumsum()
        # each['diff'] = each['values'].diff()
        # count = ((each['diff'] <= 0) & (each['values'] <= 0)).astype(int).sum(axis=0)
        # counts.append(count)
        # df2 = each.groupby('counter')['values'].min().to_frame(name='value').join(each.groupby('counter')['values'].count().rename('number'))
        # max_consec0 = df2[df2['value']==0]['number'].tolist()
        # max_consec1 = df2[df2['value']==1]['number'].tolist()
        
    # data_fin.index = pd.to_datetime(data_fin.index, format='%Y')
    
    fig, ax = plt.subplots(1,1, figsize=(6,4))
    axb = ax.twiny()
    axb.tick_params(
        axis='x',          # changes apply to the x-axis
        which='both',      # both major and minor ticks are affected
        bottom=False,      # ticks along the bottom edge are off
        top=False,         # ticks along the top edge are off
        labelbottom=False)
    axc = ax.twinx()
    # ax.barh(data_fin[0]+0.25, data_fin['max_tot_hw']/182*100, height=1, lw=0, 
    #         color='forestgreen',
    #         align='center')
    ax.barh(data_fin[0]+0.25, data_fin['max_tot_hw'], height=1, lw=0, 
            color='dodgerblue', alpha=0.75,
            align='center')
    # axb.barh(data_fin[0]+0.25, data_fin['max_tot_lw']/182*100, height=1, lw=0, 
    #         color='darkorange',
    #         align='center')
    axb.barh(data_fin[0]+0.25, data_fin['max_tot_lw'], height=1, lw=0, 
            color='red',
            align='center', alpha=0.75,)
    axb.invert_xaxis()
    # ax.invert_xaxis()
    ax.set_ylim(1960, 2020)
    ax.set_xlim(0, 180)
    axb.set_xlim(180, 0)
    ax.set_yticks(np.arange(1960, 2020+1, 10))
    ax.set_yticklabels(np.arange(1960, 2020+1, 10))
    
    
    sech = [1962,1976,1989,1990,1996,2003,
                2005,2011,2018,2019] # 2011
    sech_str = ['1962','1976','1989-1990','','1996','2003',
                '2005-2006','2010','2018-2019',''] # 2011
    # for s in sech:
    #     ax.axhline(s, color='k', ls='--', zorder=10)
    #     axb.axhline(s, color='k', ls='--', zorder=10)
    # axc.barh(data_fin[0]+0.25, data_fin['max_tot_lw']/182*100, height=0, lw=0, 
    #         color='darkorange',
    #         align='center')
    axc.barh(data_fin[0]+0.25, data_fin['max_tot_lw'], height=0, lw=0, 
            color='red',
            align='center', alpha=0.75)
    axc.set_ylim(1960, 2020)
    axc.set_yticks(sech)
    axc.set_yticklabels(sech_str, fontsize=8, color='red')
    
    
    ax.grid()
    # ax.axvline(x=80)
    if (var == 'ETP') | (var=='TAS'): #| (var=='TAS')
        ax.set_title('Day counts > Q75th '+var+' [%]', pad=30)
    else:
        ax.set_title('Day counts < Q5th '+var+' [%]', pad=30)
    ax.set_xlabel('High water period & Low water period', color='k')
    axb.set_xlabel(' ')
    axb.set_xticklabels(' ')
    ax.set_xticks(np.arange(0, 180+1, 30))
    ax.set_xticklabels([0,30,60,90,60,30,0])

    # axy1 = ax.twiny()
    # axy1.plot(d_hw.resample('Y').sum()['values'].values,
    #           d_hw.index.year.unique(),
    #           lw=2, color='blue')
    # axy1.set_xlim(0,600)
    # # axy1.set_xticks(np.arange(0, 1400+1, 350))
    # # axy1.set_xticklabels([200,400,600,600,400,200])
    # # axy1.set_xticklabels(' ')

    # test = d_lw.resample('Y').sum()
    
    # axy2 = ax.twiny()
    # axy2.plot(d_lw.resample('Y').sum()['values'].values, d_lw.index.year.unique(),
    #           lw=2, color='darkred')
    # axy2.invert_xaxis()
    # axy2.set_xlim(600,0)
    # axy2.set_xticklabels(' ')
    # plt.tick_params(
    #     axis='x',          # changes apply to the x-axis
    #     which='both',      # both major and minor ticks are affected
    #     bottom=False,      # ticks along the bottom edge are off
    #     top=False,         # ticks along the top edge are off
    #     labelbottom=False)
    
    fig.savefig(fig_path+'droughts_analysis_'+var+'.png', dpi=300, bbox_inches='tight')

#%% 4 - DROUGHTS MODS

dfd = both.copy()

# models = ['MPI-CCL','ECE-RCA','ECE-RAC','CNR-RAC',
#           'NOR-R15','CNR-ALA','HAD-REG','MPI-R09']

mod = 'REA'
mod = 'HAD-REG'
mod = 'CNR-ALA'
mod = 'ECE-RCA'
sce = 'RCP8.5'
# sce = 'historic'
var = 'REC'
# per = [1960,2019]
cond = 0

# for var in ['TAS','PPT','ETP','EFF','REC']:

# for var in ['PPT','ETP']:
for var in ['REC']:    

    if mod == 'REA':
        his = dfd[(dfd.index.year>=1960) & (dfd.index.year<=2019)].filter(regex='historic')
    else:
        his = dfd[(dfd.index.year>=1972) & (dfd.index.year<=2005)].filter(regex='historic')
    pro = dfd[(dfd.index.year>=2005) & (dfd.index.year<=2098)].filter(regex='RCP')
    
    d = pd.concat((pro.filter(regex=var+'_'+mod+'_'+sce),
                   his.filter(regex=var+'_'+mod+'_'+'historic')), axis=1).mean(axis=1)
    
    d.columns = ['values']
    d = d.round(2).squeeze().to_frame()
    d['month'] = d.index.month
    d.columns = ['values','month']
    
    d_lw = d.query("month == "+"["+'4,5,6,7,8,9'+"]")
    d_hw = d.query("month == "+"["+'10,11,12,1,2,3'+"]")
    
    years = d.index.year.unique()[:]
    data_fin = years.copy().to_frame()
    
    # cond_hw = select_period(d_hw['values'],1960,2019).min()
    # cond_lw = select_period(d_lw['values'],1960,2019).min()
    # cond_hw = select_period(d_hw['values'],1960,2019).quantile(0.05)
    # cond_lw = select_period(d_lw['values'],1960,2019).quantile(0.05)
    if (var == 'ETP') | (var=='TAS'):
        cond_hw = select_period(d_hw['values'],1960,2019).quantile(0.75)
        cond_lw = select_period(d_lw['values'],1960,2019).quantile(0.75)
    else :
        # print(var)
        cond_hw = select_period(d_hw['values'],1960,2019).quantile(0.10)
        cond_lw = select_period(d_lw['values'],1960,2019).quantile(0.10)
    # cond_hw = 5
    # cond_lw = 5
    
    counts = []
    for i, year in enumerate(years):
    
        each_hw = d_hw[d_hw.index.year==year]
        # each_hw = each_hw.resample('M').sum()
        
        each_lw = d_lw[d_lw.index.year==year]
        # each_lw = each_lw.resample('M').sum()
        
        # Method 1
        if (var == 'ETP') | (var=='TAS'): #| (var=='TAS')
            m = each_hw['values'].ge(cond_hw)
            # print(var)
        else:
            m = each_hw['values'].le(cond_hw)
        count_hw = sum(m)
        s = (m != m.shift())[m].cumsum()
        each_hw['max_cons'] = s.map(s.value_counts()).mask(~s.duplicated())
        each_hw['max_cons'] = each_hw['max_cons'].ffill().fillna(1).astype(int)
        
        if (var == 'ETP') | (var=='TAS'):
            m = each_lw['values'].ge(cond_lw)
            # print(var)
        else:
            m = each_lw['values'].le(cond_lw)
        count_lw = sum(m)
        s = (m != m.shift())[m].cumsum()
        each_lw['max_cons'] = s.map(s.value_counts()).mask(~s.duplicated())
        each_lw['max_cons'] = each_lw['max_cons'].ffill().fillna(1).astype(int)
        
        data_fin.loc[year,'max_cons_hw'] = each_hw['max_cons'].max()
        data_fin.loc[year,'max_cons_lw'] = each_lw['max_cons'].max()
        data_fin.loc[year,'max_tot_hw'] = count_hw
        data_fin.loc[year,'max_tot_lw'] = count_lw
        
        # Method 2
        # each['counter'] = each['values'].diff().le(0).cumsum()
        # each['diff'] = each['values'].diff()
        # count = ((each['diff'] <= 0) & (each['values'] <= 0)).astype(int).sum(axis=0)
        # counts.append(count)
        # df2 = each.groupby('counter')['values'].min().to_frame(name='value').join(each.groupby('counter')['values'].count().rename('number'))
        # max_consec0 = df2[df2['value']==0]['number'].tolist()
        # max_consec1 = df2[df2['value']==1]['number'].tolist()
        
    # data_fin.index = pd.to_datetime(data_fin.index, format='%Y')
    
    fig, ax = plt.subplots(1,1, figsize=(6,4))
    axb = ax.twiny()
    axb.tick_params(
        axis='x',          # changes apply to the x-axis
        which='both',      # both major and minor ticks are affected
        bottom=False,      # ticks along the bottom edge are off
        top=False,         # ticks along the top edge are off
        labelbottom=False)
    axc = ax.twinx()
    # ax.barh(data_fin[0]+0.25, data_fin['max_tot_hw']/182*100, height=1, lw=0, 
    #         color='forestgreen',
    #         align='center')
    ax.barh(data_fin[0]+0.25, data_fin['max_tot_hw'], height=1, lw=0, 
            color='dodgerblue', alpha=0.75,
            align='center')
    # axb.barh(data_fin[0]+0.25, data_fin['max_tot_lw']/182*100, height=1, lw=0, 
    #         color='darkorange',
    #         align='center')
    axb.barh(data_fin[0]+0.25, data_fin['max_tot_lw'], height=1, lw=0, 
            color='red',
            align='center', alpha=0.75,)
    axb.invert_xaxis()
    # ax.invert_xaxis()
    # ax.set_ylim(1960, 2020)
    ax.set_xlim(0, 180)
    axb.set_xlim(180, 0)
    # ax.set_yticks(np.arange(1960, 2020+1, 10))
    # ax.set_yticklabels(np.arange(1960, 2020+1, 10))
    
    
    sech = [1962,1976,1989,1990,1996,2003,
                2005,2011,2018,2019] # 2011
    sech_str = ['1962','1976','1989-1990','','1996','2003',
                '2005-2006','2010','2018-2019',''] # 2011
    # for s in sech:
    #     ax.axhline(s, color='k', ls='--', zorder=10)
    #     axb.axhline(s, color='k', ls='--', zorder=10)
    # axc.barh(data_fin[0]+0.25, data_fin['max_tot_lw']/182*100, height=0, lw=0, 
    #         color='darkorange',
    #         align='center')
    axc.barh(data_fin[0]+0.25, data_fin['max_tot_lw'], height=0, lw=0, 
            color='red',
            align='center', alpha=0.75)
    # axc.set_ylim(1960, 2020)
    axc.set_yticks(sech)
    axc.set_yticklabels(sech_str, fontsize=8, color='red')
    
    
    ax.grid()
    # ax.axvline(x=80)
    if (var == 'ETP') | (var=='TAS'): #| (var=='TAS')
        ax.set_title('Day counts > Q75th '+var+' [%]', pad=30)
    else:
        ax.set_title('Day counts < Q5th '+var+' [%]', pad=30)
    ax.set_xlabel('High water period & Low water period', color='k')
    axb.set_xlabel(' ')
    axb.set_xticklabels(' ')
    ax.set_xticks(np.arange(0, 180+1, 30))
    ax.set_xticklabels([0,30,60,90,60,30,0])

    # axy1 = ax.twiny()
    # axy1.plot(d_hw.resample('Y').sum()['values'].values,
    #           d_hw.index.year.unique(),
    #           lw=2, color='blue')
    # axy1.set_xlim(0,600)
    # # axy1.set_xticks(np.arange(0, 1400+1, 350))
    # # axy1.set_xticklabels([200,400,600,600,400,200])
    # # axy1.set_xticklabels(' ')

    # test = d_lw.resample('Y').sum()
    
    # axy2 = ax.twiny()
    # axy2.plot(d_lw.resample('Y').sum()['values'].values, d_lw.index.year.unique(),
    #           lw=2, color='darkred')
    # axy2.invert_xaxis()
    # axy2.set_xlim(600,0)
    # axy2.set_xticklabels(' ')
    # plt.tick_params(
    #     axis='x',          # changes apply to the x-axis
    #     which='both',      # both major and minor ticks are affected
    #     bottom=False,      # ticks along the bottom edge are off
    #     top=False,         # ticks along the top edge are off
    #     labelbottom=False)
    
    # fig.savefig(fig_path+'droughts_analysis_'+var+'.png', dpi=300, bbox_inches='tight')

#%% 5 - RETURN CONDITIONS

models = ['MPI-CCL','ECE-RCA','ECE-RAC','CNR-RAC',
          'NOR-R15','CNR-ALA','HAD-REG','MPI-R09']

models = ['REA',
          'ECE-RCA','ECE-RAC','HAD-REG','NOR-R15', # Pessimistic
          'MPI-CCL','MPI-R09','CNR-ALA','CNR-RAC'] # Optimistic

# models = ['REA',
#             'ECE-RCA','ECE-RAC','HAD-REG','NOR-R15',
#             'MPI-CCL','MPI-R09','CNR-RAC','CNR-ALA',
#             'IPS-WRF','HAD-CCL','IPS-RCA','NOR-HIR']

# models= ['REA']

# models = ['NOR-R15']

couleurs = ['k',
            'red','darkorange','gold','orchid',
            'forestgreen','yellowgreen','dodgerblue','blue']

color_dict = dict(zip(models, couleurs))
# models = ['HAD-REG']

# mod = 'REA'
# mod = 'HAD-REG'
# sce = 'historic'
var = 'REC'
per = [1960,2019]
cond = 0

sce_list = ['RCP2.6','RCP8.5']
# sce_list = ['RCP8.5']

for sce in sce_list:

    fig, axs = plt.subplots(1,2, figsize=(8,4))
    axs = axs.ravel()
    
    for idx, focus in enumerate(['max_cons_hw','max_cons_lw']):
    # for idx, focus in enumerate(['max_tot_hw','max_tot_lw']):
        
        ax = axs[idx]
        
        for mod in models:
        
            if mod == 'REA':
                scen = 'historic'
                his = dfd[(dfd.index.year>=1960) & (dfd.index.year<=2019)].filter(regex='historic')
                pro = dfd[(dfd.index.year>=1960) & (dfd.index.year<=2019)].filter(regex='RCP')
            else:
                scen = sce
                his = dfd[(dfd.index.year>=1972) & (dfd.index.year<=2005)].filter(regex='historic')
                pro = dfd[(dfd.index.year>=2005) & (dfd.index.year<=2098)].filter(regex='RCP')
            
            d = pd.concat((pro.filter(regex=var+'_'+mod+'_'+scen),
                           his.filter(regex=var+'_'+mod+'_'+'historic')), axis=1).mean(axis=1)
            
            d.columns = ['values']
            d = d.round(3).squeeze().to_frame()
            d['month'] = d.index.month
            d.columns = ['values','month']
            
            d_lw = d.query("month == "+"["+'5,6,7,8,9,10'+"]") # 4,5,6,7,8,9,10,11
            d_hw = d.query("month == "+"["+'11,12,1,2,3,4'+"]") # 10,11,12,1,2,3,4
            
            if mod == 'REA':
                years = d.index.year.unique()[:]
            else:
                years = d.index.year.unique()[:]
                years = years[(years.values>=2040)&(years.values<=2070)]
            data_fin = years.copy().to_frame()
            
            # cond_hw = select_period(d_hw['values'],1972,2005).min()
            # cond_lw = select_period(d_lw['values'],1972,2005).min()
            # cond_hw = select_period(d_hw['values'],1972,2005).quantile(0.05)
            # cond_lw = select_period(d_lw['values'],1972,2005).quantile(0.05)
            # cond_hw = select_period(d_hw['values'],1960,2019).quantile(0.5)
            # cond_lw = select_period(d_lw['values'],1960,2019).quantile(0.5)
            # cond_hw = select_period(d_hw['values'],1960,2019).quantile(0.5)
            # cond_lw = select_period(d_lw['values'],1960,2019).quantile(0.5)
            
            if (var == 'ETP') | (var=='TAS'):
                print(var)
                cond_hw = select_period(d_hw['values'],1972,2005).quantile(0.95)
                cond_lw = select_period(d_lw['values'],1972,2005).quantile(0.95)
            else :
                # print(var)
                cond_hw = select_period(d_hw['values'],1972,2005).quantile(0.05)
                cond_lw = select_period(d_lw['values'],1972,2005).quantile(0.05)
                # cond_lw = 0
                # cond_hw = select_period(d_hw['values'],1972,2005).quantile(0.95)
                # cond_lw = select_period(d_lw['values'],1972,2005).quantile(0.95)
            
            counts = []
        
            for i, year in enumerate(years):
            
                each_hw = d_hw[d_hw.index.year==year]
                # each_hw = each_hw.resample('M').sum()
                
                each_lw = d_lw[d_lw.index.year==year]
                # each_lw = each_lw.resample('M').sum()
                
                # Method 1
                if (var == 'ETP') | (var=='TAS'): #| (var=='TAS')
                    m = each_hw['values'].ge(cond_hw)
                    # print(var)
                else:
                    m = each_hw['values'].le(cond_hw) #ge
                count_hw = sum(m)
                s = (m != m.shift())[m].cumsum()
                each_hw['max_cons'] = s.map(s.value_counts()).mask(~s.duplicated())
                each_hw['max_cons'] = each_hw['max_cons'].ffill().fillna(1).astype(int)
                
                if (var == 'ETP') | (var=='TAS'):
                    m = each_lw['values'].ge(cond_lw)
                    # print(var)
                else:
                    m = each_lw['values'].le(cond_lw) #ge
                count_lw = sum(m)
                s = (m != m.shift())[m].cumsum()
                each_lw['max_cons'] = s.map(s.value_counts()).mask(~s.duplicated())
                each_lw['max_cons'] = each_lw['max_cons'].ffill().fillna(1).astype(int)
                
                data_fin.loc[year,'max_cons_hw'] = each_hw['max_cons'].max()
                data_fin.loc[year,'max_cons_lw'] = each_lw['max_cons'].max()
                data_fin.loc[year,'max_tot_hw'] = count_hw
                data_fin.loc[year,'max_tot_lw'] = count_lw
                # if year == 1976:
                #     break
                # Method 2
                # each['counter'] = each['values'].diff().le(0).cumsum()
                # each['diff'] = each['values'].diff()
                # count = ((each['diff'] <= 0) & (each['values'] <= 0)).astype(int).sum(axis=0)
                # counts.append(count)
                # df2 = each.groupby('counter')['values'].min().to_frame(name='value').join(each.groupby('counter')['values'].count().rename('number'))
                # max_consec0 = df2[df2['value']==0]['number'].tolist()
                # max_consec1 = df2[df2['value']==1]['number'].tolist()
                
            '''
            fig, ax = plt.subplots(1,1, figsize=(6,3))
            ax.bar(data_fin[0]-0.25, data_fin['max_cons_hw']/182*100, lw=0, color='forestgreen',
                    width=0.5, align='center',)
            ax.bar(data_fin[0]+0.25, data_fin['max_cons_lw']/182*100, lw=0, color='darkorange',
                    width=0.5, align='center',)
            ax.set_title(mod)
            ax.set_ylim(0,100)
            '''
        
            # data_fin.index = pd.to_datetime(data_fin.index, format='%Y')
            # data_fin = data_fin.rolling(window=20).mean()
            # data_fin = data_fin.dropna()
        
            data_fin = (data_fin) #/182)*100
            # data_fin = d_lw.copy()
            # data_fin.columns = ['max_cons_lw','month']
            
            # fig, ax = plt.subplots(1,1, figsize=(6,3))
            
            years = mdates.YearLocator(20)   # every year
            yearsmin = mdates.YearLocator(10)
            months = mdates.MonthLocator(7)  # every month
            years_fmt = mdates.DateFormatter('%Y')
            months_fmt = mdates.DateFormatter('%m') #b = name of month ?
            raw = data_fin.copy()
            qmna = data_fin.copy()
            # ax.plot(raw['max_cons_lw'], color='k')
            qmna_sort = qmna.sort_values([focus]).round(0)
            
            ### By rank
            n = qmna_sort.shape[0]
            qmna_sort.insert(0, "rank", range(1, 1 + n))
            qmna_sort["pr"] = (n - qmna_sort["rank"] + 1) / (n + 1)
            qmna_sort["return-period"] = 1 / qmna_sort["pr"]
            # plt.plot(qmna_sort['return-period'], qmna_sort['max_cons_lw'])
            
            ### By freq
            freq = qmna_sort.groupby([focus]).size().reset_index(name='counts')
            freq['frequency'] = freq.counts/freq.counts.sum() #freq
            freq['cumulative_frequency'] = freq['frequency'].cumsum() #freq cumulated
            freq['retour'] = 1/(1-(freq['cumulative_frequency']))
            # freq['retour'] = 1/freq['cumulative_frequency']
            # freq['retour'] = 1/freq['frequency']
            freq['target'] = 5
            
            ### By pdf
            Z = qmna_sort[focus]
            pdf = np.histogram(Z, bins=100, density=True)
            from scipy.stats import norm
            pdf = norm.pdf(Z, Z.mean(), Z.std())
            N = len(Z)
            count, bins_count = np.histogram(Z, bins=100, density=True)
            pdf = count / sum(count)
            cdf = np.cumsum(pdf)
            # plt.plot(pdf*100, lw=4, label="PDF")
            # plt.plot(cdf*100, lw=4, label="CDF")
        
            Mean = raw[focus].mean()
            print(Mean)
            Min = raw[focus].min()
            Q10 = raw[focus].quantile(0.10)
            Q50 = raw[focus].quantile(0.5)
            Q90 = raw[focus].quantile(0.90)
            Max = raw[focus].max()
            
            if mod == 'REA':
                # s_1976 = [qmna_sort.loc[1976][focus],
                #           qmna_sort.loc[1989][focus],
                #           qmna_sort.loc[1990][focus],
                #           qmna_sort.loc[2003][focus],
                #           qmna_sort.loc[2018][focus]]
                s_1976 = [qmna_sort.loc[1976][focus]]
            
            # for i in s_1976:
            #     ax.axhline(i, color='dimgray', ls='--', lw=2)
            
            # ax.plot(qmna_sort['return-period'], qmna_sort['max_cons_lw'], ls='-', c=color_dict[mod],
            #             linewidth=2, label=mod)
            
            if mod == 'REA':
                ax.plot(freq.iloc[:-1]['retour'], freq.iloc[:-1][focus], ls='-', c=color_dict[mod],
                        linewidth=3, label=mod)
            else:
                ax.plot(freq['retour'], freq[focus], ls='-', c=color_dict[mod],
                        linewidth=2.5, label=mod)
            
            ax.set_xlabel('Return period [years]')
            # ax.set_ylabel('Day counts < $Q5^{th}$ REC [%]')
            # ax.set_yscale('log')
            # ax.set_xscale('log')
            ax.xaxis.set_major_formatter(ScalarFormatter())
            ax.xaxis.set_major_locator(MaxNLocator(integer=True))
            ax.yaxis.set_major_locator(MaxNLocator(integer=True))
            ax.set_xlim(1, 20)
            ax.set_xticks([5,10,15,20])
            if idx == 0:
                # ax.set_ylim(0, 25)
                # ax.set_yticks(np.arange(0,25+1,5))
                # ax.set_ylim(0, 60)
                # ax.set_yticks(np.arange(0,60+1,15))
                ax.set_ylim(0, 90)
                ax.set_yticks(np.arange(0,90+1,15))
                # ax.set_title('High period')
            if idx == 1:
                # ax.set_ylim(0, 75)
                # ax.set_yticks(np.arange(0,75+1,25))
                ax.set_ylim(0, 90)
                ax.set_yticks(np.arange(0,90+1,15))
                # ax.set_title('Low period')
            # if idx == 0:
            #     ax.legend(loc='lower right', frameon=True)
            ax.grid()
            # xmin = 0
            # xmax = 1
            # ymin = 0
            # ymax = 4
            # ax.set_ylim(ymin, ymax)     
            # ax.axvline(x=5, color='grey')
            # ax.set_xticks([2,5,10,20])
            # exist = 5 in freq['retour'].values
            # if exist == True:
            #     icross = freq['outflow_drain'][freq['retour']==5].values[0]
            # else:
            #     icross, jcross = main(freq['max_cons_lw'], freq['target'], freq['retour'])
            # print(icross)
            # ax.axhline(y=icross, color=color)               
            # if scenario == 'historic':
            #     t0 = ax.text(0.65, 0.90,
            #                 "QMNA5 = " + f"{round(icross,2)}",
            #                 ha='left', va='center', color=color, transform=ax.transAxes)
            # if scenario == 'RCP4.5':
            #     t2 = ax.text(0.65, 0.80,
            #                 "QMNA5 = " + f"{round(icross,2)}",
            #                 ha='left', va='center', color=color, transform=ax.transAxes)
            # if scenario == 'RCP8.5':
            #     t2 = ax.text(0.65, 0.70,
            #                 "QMNA5 = " + f"{round(icross,2)}",
            #                 ha='left', va='center', color=color, transform=ax.transAxes)
            # ax.set_title(mask.split('_')[2][0:-1].capitalize()+' '+mask.split('_')[2][-1], fontsize=12) #keep only station names
        
        # ax.invert_xaxis()
        plt.tight_layout()
        
    fig.savefig(fig_path+'return_period_'+sce+'_'+var+'.png', dpi=300, bbox_inches='tight')

#%% 6 - EVOL XY TEMPPT

mod = 'REA'
sce = 'historic'

fig, axs = plt.subplots(1,3, figsize=(12,4))
axs = axs.ravel()

tit = ['High water','Low water','Water year']

xlims = []
ylims = []

for i, j in enumerate([hw,lw,wy]):    
    ax = axs[i]
    p = j.filter(regex='PPT'+'_'+'REA')
    p = p.dropna(axis=0) * 365
    t = j.filter(regex='TAS'+'_'+'REA')
    t = t.dropna(axis=0)    
    xlims.append(p.min())
    xlims.append(p.max())
    ylims.append(t.min())
    ylims.append(t.max())
    xm = ( p.min() + p.max() ) / 2
    ym = ( t.min() + t.max() ) / 2

    n = p.index.year
    scat = ax.scatter(p, t, c=n, cmap='jet', marker="o", s=200, zorder=1, lw=0.5, alpha=0.75)
    for k, txt in enumerate(n):
        ax.annotate(txt, (p.iloc[k], t.iloc[k]), family='sans-serif', fontsize=4.5, 
                    color='black', weight="bold", ha='center', va='center', zorder=2)    
    ax.set_xlabel('Precipitation [mm] ', labelpad = +15)
    ax.set_ylabel('Température [°C]', labelpad = +15)    
    ax.set_title(tit[i], pad = +10) #keep only station names
    # ax.spines['right'].set_visible(False)
    # ax.spines['top'].set_visible(False)
    # tick = np.linspace(t.min()[0], t.max()[0] +1, 10)
    # ax.set_yticks(tick)
    # tick = np.linspace(p.min()[0], p.max()[0] +10, 5)
    # ax.set_xticks(tick)
    import matplotlib.ticker as plticker
    loc = plticker.MultipleLocator(base=200) # this locator puts ticks at regular intervals
    ax.xaxis.set_major_locator(loc)
    loc = plticker.MultipleLocator(base=1) # this locator puts ticks at regular intervals
    ax.yaxis.set_major_locator(loc)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.yaxis.set_ticks_position('left')
    ax.xaxis.set_ticks_position('bottom')
    ax.axvline(x=xm[0], c='k', ls='--', zorder=0)
    ax.axhline(y=ym[0], c='k', ls='--', zorder=0)
    
# for a in range(3):
#     fig.axes[a].set_xlim(np.array(xlims).min(), np.array(xlims).max())
#     fig.axes[a].set_ylim(np.array(ylims).min(), np.array(ylims).max())

dates = n
dates = dates[0::10]
leng = len(dates)
cmap = cm.get_cmap('jet', len(n))

cax = fig.add_axes([1.0, 0.25, 0.01, 0.5])
norm = mpl.colors.BoundaryNorm(np.arange(0,len(n)+1)-0.5, len(n))
sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
sm.set_array([])
cbar = plt.colorbar(sm, cax=cax, aspect=30, alpha=0.75)
cbar.set_ticks(np.arange(0,len(n),10))
cbar.set_ticklabels(dates)
cbar.ax.tick_params(labelsize=10) 
    
plt.tight_layout()

fig.savefig(fig_path+'evolution_xy_temppt'+'.png', dpi=300, bbox_inches='tight')

#%% 7 - MATRIX ANOMALY FUTURE

var = 'EFF'
mod = 'TOT'
sce = 'RCP8.5'

ref = [1970,2009]
per = [[2010,2049],[2050,2089]]

hist = his.copy()
hist = hist[var+'_'+mod+'_'+'historic'].to_frame()
hist_intm = hist.groupby([lambda x: x.month]).mean() * 30
hist['month'] = hist.index.month.values
hist['year'] = hist.index.year.values # group by month and year, get the average
hist = hist.groupby(['month', 'year']).apply(lambda g: g.sum(skipna=False))
hist = hist.unstack(level=0, fill_value=np.nan)
hist = hist[var+'_'+mod+'_'+'historic']
# hist = hist.iloc[::-1]
lims = (hist.min(), hist.max())
vmin = round(np.array(lims).min(),2)
vmax = round(np.array(lims).max(),2)

fig, axs = plt.subplots(1,3, figsize=(10, 12))
axs = axs.ravel()
colori = "jet_r"
# if var=='PPT' or var=='RUN' or var=='REC':
#     colori = colori+"_r"
xticks = np.arange(12)+0.5

ax = axs[0]
ax.pcolormesh(hist, cmap='Greys', vmin=vmin, vmax=vmax, edgecolor='grey', lw=0.2, alpha=0.7) # norm=mpl.colors.LogNorm(vmin, vmax)
xticks = np.arange(12)+0.5
ax.set_xticks(xticks)
mois = ['J','F','M','A','M','J','J','A','S','O','N','D']
ax.set_xticklabels(mois, minor=False, rotation='horizontal', fontsize=13)
ax.xaxis.tick_top()
yticks = np.arange((hist.index[-1]+1) - hist.index[0])+0.5
years = list(hist.index.values.astype(str))[::2] 
ax.set_yticks(yticks[::2])
ax.set_yticklabels(years, minor=False, rotation='horizontal', fontsize=13)
ax.invert_yaxis()
ax.tick_params(axis="x", direction='out', length=5)
ax.tick_params(axis="y", direction='out', length=5)

compt=1
for p in per:
    fut = pro.copy()
    fut = fut[(fut.index.year>=p[0]) & (fut.index.year<=p[1])]
    fut = fut[var+'_'+mod+'_'+sce].to_frame()
    fut['month'] = fut.index.month.values
    fut['year'] = fut.index.year.values # group by month and year, get the average
    fut = fut.groupby(['month', 'year']).apply(lambda g: g.sum(skipna=False))
    fut = fut.unstack(level=0, fill_value=np.nan)
    ano = fut[var+'_'+mod+'_'+sce].T
    ano = ano.sub(hist_intm.values, axis=0)
    ano = ano.T
    
    anolims = (ano.min(), ano.max())
    anomin = round(np.array(anolims).min(),2)
    anomax = round(np.array(anolims).max(),2)
    
    ax = axs[compt]
    ax.tick_params(axis="x", direction='out', length=5)
    ax.tick_params(axis="y", direction='out', length=5)
    ax.pcolormesh(ano, cmap=colori, norm=mpl.colors.TwoSlopeNorm(vmin=anomin, vcenter=0, vmax=anomax), 
                  edgecolor='grey', lw=0.2, alpha=0.7)                    
    ax.set_xticks(xticks)
    ax.set_xticklabels(mois, minor=False, rotation='horizontal', fontsize=13)
    ax.xaxis.tick_top()
    yticks = np.arange((ano.index[-1]+1) - ano.index[0])+0.5
    years = list(ano.index.values.astype(str))[::2]
    ax.set_yticks(yticks[::2])
    ax.set_yticklabels(years, minor=False, rotation='horizontal', fontsize=13)
    ax.invert_yaxis()
    
    compt+=1
    
plt.suptitle('MODEL : '+mod+' - '+str(sce), fontproperties=fontprop, fontsize=20, y=1.02)
plt.tight_layout()

# sm = plt.cm.ScalarMappable(cmap=colori, norm=mpl.colors.LogNorm(vmin, vmax))
sm = plt.cm.ScalarMappable(cmap='Greys', norm=plt.Normalize(vmin, vmax))
cax = fig.add_axes([-0.1, 0.2, 0.02, 0.6])
cbar = fig.colorbar(sm, cax=cax, orientation='vertical', alpha=0.7)
if var == 'TAS':
    cbar.ax.set_ylabel(var + ' [°C]', labelpad=30, rotation=90)
else:
    cbar.ax.set_ylabel(var + ' [mm/mois]', labelpad=30, rotation=90)
cbar.ax.yaxis.set_label_position('left')

# sm2 = plt.cm.ScalarMappable(cmap=colori, norm=plt.Normalize(vmin=anomin, vmax=anomax))
sm2 = plt.cm.ScalarMappable(cmap=colori, norm=mpl.colors.TwoSlopeNorm(vmin=anomin, vcenter=0, vmax=anomax))
cax2 = fig.add_axes([1, 0.2, 0.02, 0.6])
cbar2 = fig.colorbar(sm2, cax=cax2, orientation='vertical', alpha=0.7)   
if var == 'TAS':
    cbar2.ax.set_ylabel(var + ' ANOMALY [°C]', labelpad=30, rotation=270)
else:
    cbar2.ax.set_ylabel(var + ' ANOMALY [mm/mois]', labelpad=30, rotation=270)
    
fig.savefig(fig_path+'evolution_matrix_'+ var + '.png', dpi=300, bbox_inches='tight')

#%% 8 -  INTENSITY FREQUENCY QINF

models = [
          'ECE-RCA','ECE-RAC','HAD-REG','NOR-R15', # Pessimistic
          'MPI-CCL','MPI-R09','CNR-ALA','CNR-RAC'] # Optimistic

# models = ['HAD-REG']

couleurs = ['k',
            'red','darkorange','gold','orchid',
            'forestgreen','yellowgreen','dodgerblue','blue']

color_dict = dict(zip(models, couleurs))
# models = ['HAD-REG']

# mod = 'REA'
# mod = 'HAD-REG'
# sce = 'historic'
var = 'REC'
per = [1960,2019]
cond = 0

sce_list = ['RCP2.6','RCP8.5']
sce_list = ['RCP8.5']

dfd = both.copy()

for sce in sce_list:
    
    df_stat = pd.DataFrame(index=range(3))

    # axs = axs.ravel()
    
    # ax = axs[idx]
    
    for mod in models:
            
        his = dfd[(dfd.index.year>=1972) & (dfd.index.year<=2005)].filter(regex='historic')
        pro = dfd[(dfd.index.year>=2005) & (dfd.index.year<=2098)].filter(regex='RCP')
        
        d = pd.concat((pro.filter(regex=var+'_'+mod+'_'+sce),
                       his.filter(regex=var+'_'+mod+'_'+'historic')), axis=1).mean(axis=1)
        d = d * 30
        
        d.columns = ['values']
        d = d.round(4).squeeze().to_frame()
        d['month'] = d.index.month
        d.columns = ['values','month']
        
        d_lw = d.query("month == "+"["+'5,6,7,8,9,10'+"]") # 4,5,6,7,8,9,10,11
        d_hw = d.query("month == "+"["+'11,12,1,2,3,4'+"]") # 10,11,12,1,2,3,4
        
        if mod == 'REA':
            years = d.index.year.unique()[:]
        else:
            years = d.index.year.unique()[:]
            years = years[years.values>=2070]
        data_fin = years.copy().to_frame()
        
        d = d['values']
        d = d.round(1)
        cond = select_period(d,1972,2005).quantile(0.25)
        
        print(mod, cond)
        # cond_hw = select_period(d_hw['values'],1972,2005).quantile(0.05)
        # cond_lw = select_period(d_lw['values'],1972,2005).quantile(0.05)
    
        ### HISTORIC and FUTURE ###
        
        # fig1, ax1 = plt.subplots(1,1, figsize=(4,4))
        fig2, ax2 = plt.subplots(1,1, figsize=(3,3))
        # fig3, ax3 = plt.subplots(1,1, figsize=(4,4))

        for p, per in enumerate([[1980,2010],[2070,2100]]):
            
            if p == 0:
                color = 'darkmagenta'
            if p == 1:
                color = 'darkorange'       
            
            df = select_period(d,per[0],per[1])
            Z = df.sort_values().round(4).to_frame()
            # test = np.histogram(Z, bins=100, density=True)[0]
            pdf = norm.pdf(Z, Z.mean(), Z.std())
            N = len(Z)
            count, bins_count = np.histogram(Z, bins=100, density=True)
            pdf = count / sum(count)
            cdf = np.cumsum(pdf)
            # ax = ax1
            # ax.plot(pdf, color=color, lw=2)
            # ax.set_xscale('log')
            # ax.set_yscale('log')
            # ax.axvline(cond, color='k', ls='--')
    
            freq = Z.groupby('values').size().reset_index(name='counts')
            freq['frequency'] = freq.counts/freq.counts.sum() #freq
            freq['cumulative_frequency'] = freq['frequency'].cumsum() #freq cumulated
            freq['retour'] = 1/(1-(freq['cumulative_frequency']))
            freq['target'] = cond
            ax = ax2           
            ax.set_xscale('log')
            ax.set_yscale('log')
            # ax.plot(freq['values'], freq['frequency'], color=color, lw=2)
            ax.plot(freq['values'], freq['cumulative_frequency'], color=color, lw=3)
                        
            qh = np.array(Z.copy())
            LBINS = 100
            # No log
            linbins = np.linspace(0,qh.max(),LBINS)
            hist_lin, bins_lin = np.histogram(qh, bins=linbins, density=True)
            bins_lin_centers = 0.5*(bins_lin[1:]+bins_lin[:-1])
            # Log
            logbins = np.logspace(np.log10(qh.max())-3,np.log10(qh.max()),LBINS)
            hist_log, bins_log = np.histogram(qh, bins=logbins, density=True)
            bins_log_centers = 10**(0.5*(np.log10(bins_log[1:])+np.log10(bins_log[:-1])))
            # ax = ax3
            # ax.plot(hist_log, color=color, lw=2)
            # ax.set_xscale('log')
            # ax.set_yscale('log')
            # ax.axvline(cond, color='k', ls='--')
            
            def find_closest(A, target):
                #A must be sorted
                idx = A.searchsorted(target)
                idx = np.clip(idx, 1, len(A)-1)
                left = A[idx-1]
                right = A[idx]
                idx -= target - left < right - target
                return idx
            
            if p == 0:
                ax.axvline(cond, color='forestgreen', ls='--')
                # ax.axhline(freq[freq['values'].round(1)==cond.round(1)]['cumulative_frequency'].values[0],
                #            color='k', ls='--')
                int_eq = freq.loc[find_closest(freq['values'], cond), 'cumulative_frequency']
                ax.axhline(int_eq,
                           color='blue', ls='--')
                # int_eq = freq[freq['values'].round(1)==cond.round(1)]['cumulative_frequency'].values[0]
                freq_eq = cond
                
            if p == 1:
                ax.plot(cond, int_eq, lw=0, marker='s', color = 'k')
                idx_int = find_closest(freq['cumulative_frequency'], int_eq)
                ch_int = freq.loc[idx_int, 'values']
                ax.plot(ch_int, int_eq, lw=0, marker='o', color = 'blue')
                idx_freq = find_closest(freq['values'], freq_eq)
                ch_freq = freq.loc[idx_freq, 'cumulative_frequency']
                ax.plot(cond, ch_freq, lw=0, marker='o', color = 'forestgreen')
            
                ax.set_xlabel('Recharge [mm/month]')
                ax.set_ylabel('CDF [-]')
                ax.set_xlim(0.1,100)
                ax.set_ylim(0.01,1)
                
                ax.set_title(mod+' '+sce)
            
            #     icross, jcross = main(freq['values'],
            #                           freq['target'],
            #                           freq['cumulative_frequency'])

                df_stat.loc[0,mod+'_'+sce] = cond # value historic
                df_stat.loc[1,mod+'_'+sce] = int_eq # frequency historic
                df_stat.loc[2,mod+'_'+sce] = ch_int # value future
                df_stat.loc[3,mod+'_'+sce] = ch_freq # frequency future
            
        fig2.savefig(fig_path+'_recharge/'+ 'Qinf_' + mod + '_' + sce + '.png', dpi=300, bbox_inches='tight')

    change_int = ((df_stat.loc[2] - df_stat.loc[0])/df_stat.loc[0]) * 100
    change_freq = ((df_stat.loc[3] - df_stat.loc[1])/df_stat.loc[1]) * 100

    fig, axs = plt.subplots(1,2, figsize=(8,4))
    axs = axs.ravel()
    ax = axs[0]
    list_name = [i.split('_', 1)[0] for i in list(change_freq.index)]
    ax.bar(change_freq.index, change_freq, color='forestgreen')
    ax.set_xticklabels(list_name, rotation=90)
    ax.set_xlabel('Climate models')
    ax.set_ylabel('Frequency change [%]')
    ax.set_ylim(0,50)
    ax = axs[1]
    list_name = [i.split('_', 1)[0] for i in list(change_int.index)]
    ax.bar(change_int.index, change_int, color='blue')
    ax.set_xticklabels(list_name, rotation=90)
    ax.set_xlabel('Climate models')
    ax.set_ylabel('Intensity change [%]')
    ax.set_ylim(-75,0)
    plt.tight_layout()
    plt.suptitle(sce, y=1.05)
    
    # fig.savefig(fig_path+'_recharge/'+ '_Qinf_freqintensity_' + sce + '.png', dpi=300, bbox_inches='tight')

#%% 8 - INTENSITY FREQUENCY RECAP
    
fig, ax = plt.subplots(1,1, figsize=(3, 3))
ax.plot(change_int[0:4], change_freq[0:4], marker='o', ms=12, c='red', lw=0, mec='k', mew=1.5)
ax.plot(change_int[4:], change_freq[4:], marker='o', ms=12, c='dodgerblue', lw=0, mec='k', mew=1.5)
# for i in range(len(change_int)):
#     ax.annotate(change_int.index[i], (change_int[i], change_freq[i]))
ax.set_xlabel('Intensity change [%]')
ax.set_ylabel('Frequency change [%]')
ax.set_xlim(-100,0)
ax.set_ylim(0, 50)

fig.savefig(fig_path+'_recharge/'+ '_Qinf_freqintensity_recap_' + sce + '.png', dpi=300, bbox_inches='tight')

#%% 8 -  INTENSITY FREQUENCY QSUP

models = [
          'ECE-RCA','ECE-RAC','HAD-REG','NOR-R15', # Pessimistic
          'MPI-CCL','MPI-R09','CNR-ALA','CNR-RAC'] # Optimistic

# models = ['HAD-REG']

couleurs = ['k',
            'red','darkorange','gold','orchid',
            'forestgreen','yellowgreen','dodgerblue','blue']

color_dict = dict(zip(models, couleurs))
# models = ['HAD-REG']

# mod = 'REA'
# mod = 'HAD-REG'
# sce = 'historic'
var = 'REC'
per = [1960,2019]
cond = 0

sce_list = ['RCP2.6','RCP8.5']
sce_list = ['RCP8.5']

dfd = both.copy()

df_stat = pd.DataFrame(index=range(3))

for sce in sce_list:

    # axs = axs.ravel()
    
    # ax = axs[idx]
    
    for mod in models:
            
        his = dfd[(dfd.index.year>=1972) & (dfd.index.year<=2005)].filter(regex='historic')
        pro = dfd[(dfd.index.year>=2005) & (dfd.index.year<=2098)].filter(regex='RCP')
        
        d = pd.concat((pro.filter(regex=var+'_'+mod+'_'+sce),
                       his.filter(regex=var+'_'+mod+'_'+'historic')), axis=1).mean(axis=1)
        d = d * 30
        
        d.columns = ['values']
        d = d.round(4).squeeze().to_frame()
        d['month'] = d.index.month
        d.columns = ['values','month']
        
        d_lw = d.query("month == "+"["+'5,6,7,8,9,10'+"]") # 4,5,6,7,8,9,10,11
        d_hw = d.query("month == "+"["+'11,12,1,2,3,4'+"]") # 10,11,12,1,2,3,4
        
        if mod == 'REA':
            years = d.index.year.unique()[:]
        else:
            years = d.index.year.unique()[:]
            years = years[years.values>=2070]
        data_fin = years.copy().to_frame()
        
        d = d['values']
        d = d.round(1)
        cond = select_period(d,1972,2005).quantile(0.25)
        # cond = select_period(d,1972,2005).quantile(0.75)
        
        print(mod, cond)
        # cond_hw = select_period(d_hw['values'],1972,2005).quantile(0.05)
        # cond_lw = select_period(d_lw['values'],1972,2005).quantile(0.05)
    
        ### HISTORIC and FUTURE ###
        
        # fig1, ax1 = plt.subplots(1,1, figsize=(4,4))
        fig2, ax2 = plt.subplots(1,1, figsize=(3,3))
        # fig3, ax3 = plt.subplots(1,1, figsize=(4,4))

        for p, per in enumerate([[1980,2010],[2070,2100]]):
            
            if p == 0:
                color = 'darkmagenta'
            if p == 1:
                color = 'darkorange'       
            
            df = select_period(d,per[0],per[1])
            Z = df.sort_values(ascending=False).round(4).to_frame()
            # test = np.histogram(Z, bins=100, density=True)[0]
            pdf = norm.pdf(Z, Z.mean(), Z.std())
            N = len(Z)
            count, bins_count = np.histogram(Z, bins=100, density=True)
            pdf = count / sum(count)
            cdf = np.cumsum(pdf)
            # ax = ax1
            # ax.plot(pdf, color=color, lw=2)
            # ax.set_xscale('log')
            # ax.set_yscale('log')
            # ax.axvline(cond, color='k', ls='--')
    
            freq = Z.groupby('values').size().reset_index(name='counts')
            # freq['values' ]= freq['values'].values[::-1]
            # freq['counts' ]= freq['counts'].values[::-1]
            freq['frequency'] = freq.counts/freq.counts.sum() #freq
            freq['cumulative_frequency'] = freq['frequency'].cumsum() # freq cumulated [::-1]
            freq['cumulative_frequency'] = 1 - freq['cumulative_frequency']
            freq['retour'] = 1/(1-(freq['cumulative_frequency']))
            freq['target'] = cond
            ax = ax2           
            ax.set_xscale('log')
            ax.set_yscale('log')
            # ax.plot(freq['values'], freq['frequency'], color=color, lw=2)
            ax.plot(freq['values'], freq['cumulative_frequency'], color=color, lw=3)
            
            sum_sup = freq[freq['values']>cond]['counts'].sum()
            tot = freq.counts.sum()

            qh = np.array(Z.copy())
            LBINS = 100
            # No log
            linbins = np.linspace(0,qh.max(),LBINS)
            hist_lin, bins_lin = np.histogram(qh, bins=linbins, density=True)
            bins_lin_centers = 0.5*(bins_lin[1:]+bins_lin[:-1])
            # Log
            logbins = np.logspace(np.log10(qh.max())-3,np.log10(qh.max()),LBINS)
            hist_log, bins_log = np.histogram(qh, bins=logbins, density=True)
            bins_log_centers = 10**(0.5*(np.log10(bins_log[1:])+np.log10(bins_log[:-1])))
            # ax = ax3
            # ax.plot(hist_log, color=color, lw=2)
            # ax.set_xscale('log')
            # ax.set_yscale('log')
            # ax.axvline(cond, color='k', ls='--')
            
            def find_closest(A, target):
                #A must be sorted
                idx = A.searchsorted(target)
                idx = np.clip(idx, 1, len(A)-1)
                left = A[idx-1]
                right = A[idx]
                idx -= target - left < right - target
                return idx
            
            if p == 0:
                ax.axvline(cond, color='forestgreen', ls='--')
                # ax.axhline(freq[freq['values'].round(1)==cond.round(1)]['cumulative_frequency'].values[0],
                #            color='k', ls='--')
                int_eq = freq.loc[find_closest(freq['values'], cond), 'cumulative_frequency']
                ax.axhline(int_eq,
                           color='blue', ls='--')
                # int_eq = freq[freq['values'].round(1)==cond.round(1)]['cumulative_frequency'].values[0]
                freq_eq = cond
                
            if p == 1:
                ax.plot(cond, int_eq, lw=0, marker='s', color = 'k')
                idx_int = np.argmin(np.abs(freq['cumulative_frequency'] - int_eq))
                ch_int = freq.loc[idx_int, 'values']
                ax.plot(ch_int, int_eq, lw=0, marker='o', color = 'blue')
                idx_freq = find_closest(freq['values'], freq_eq)
                ch_freq = freq.loc[idx_freq, 'cumulative_frequency']
                ax.plot(cond, ch_freq, lw=0, marker='o', color = 'forestgreen')
                
                ax.set_xlabel('Recharge [mm/month]')
                ax.set_ylabel('CDF [-]')
                ax.set_xlim(0.1,100)
                ax.set_ylim(0.01,1)
                
                ax.set_title(mod+' '+sce)
                
            #     icross, jcross = main(freq['values'],
            #                           freq['target'],
            #                           freq['cumulative_frequency'])
    
                df_stat.loc[0,mod+'_'+sce] = cond # value historic
                df_stat.loc[1,mod+'_'+sce] = int_eq # frequency historic
                df_stat.loc[2,mod+'_'+sce] = ch_int # value future
                df_stat.loc[3,mod+'_'+sce] = ch_freq # frequency future

        # fig2.savefig(fig_path+'_recharge/'+ 'Qsup_' + mod + '_' + sce + '.png', dpi=300, bbox_inches='tight')

    change_int = -1 * ((df_stat.loc[2] - df_stat.loc[0])/df_stat.loc[0]) * 100
    change_freq = ((df_stat.loc[3] - df_stat.loc[1])/df_stat.loc[1]) * 100

    fig, axs = plt.subplots(1,2, figsize=(8,4))
    axs = axs.ravel()
    ax = axs[0]
    list_name = [i.split('_', 1)[0] for i in list(change_freq.index)]
    ax.bar(change_freq.index, change_freq, color='forestgreen')
    ax.set_xticklabels(list_name, rotation=90)
    ax.set_xlabel('Climate models')
    ax.set_ylabel('Frequency change [%]')
    # ax.set_ylim(0,50)
    ax = axs[1]
    list_name = [i.split('_', 1)[0] for i in list(change_int.index)]
    ax.bar(change_int.index, change_int, color='blue')
    ax.set_xticklabels(list_name, rotation=90)
    ax.set_xlabel('Climate models')
    ax.set_ylabel('Intensity change [%]')
    # ax.set_ylim(-75,0)
    plt.tight_layout()
    plt.suptitle(sce, y=1.05)
    
    # fig.savefig(fig_path+'_recharge/'+ '_Qsup_freqintensity_' + sce + '.png', dpi=300, bbox_inches='tight')

#%% NOTES