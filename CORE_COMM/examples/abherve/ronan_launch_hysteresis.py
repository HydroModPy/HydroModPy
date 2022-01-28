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

import geopandas as gpd
from shapely.geometry.polygon import LineString, Polygon
from shapely.ops import linemerge, unary_union, polygonize
from datetime import datetime

import scipy.stats as sp
import shapely.geometry as SG
import matplotlib.pylab as pl
import math

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
                    
from watershed import watershed_root, watershed_display
from tools import toolbox, vtk
from groundwater_flow import visualization, modflow_display
from calibration import calib_root

# LAYOUT PLOT

fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% CLASS FUNCTIONS

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
                    
    def plot_xy_data(self, x_label, y_label, x_lim, y_lim, cmap):
        
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
    
    def compute_xy_metrics(self, temporal, space):
        
        self.xrecapl = self.xrecap.copy()
        self.xrecapl = self.xrecapl.append(self.xrecapl.iloc[[0]])
        self.xrecapl.index = np.arange(1,14,1)
        
        self.yrecapl = self.yrecap.copy()
        self.yrecapl = self.yrecapl.append(self.yrecapl.iloc[[0]])
        self.yrecapl.index = np.arange(1,14,1)
        
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
        
        fig, ax = plt.subplots(1,1, figsize=(4,3))
        n = len(columns_x)
        colors = pl.cm.jet(np.linspace(0,1,n))        
        
        self.dfmet = pd.DataFrame(columns=[])
        
        for i, (colx, coly) in enumerate(zip(columns_x, columns_y)):
            
            print(colx)
            
            self.xlist = self.xrecapl[colx]
            self.ylist = self.yrecapl[coly]
            
            self.data = pd.DataFrame()
            self.data['inx'] = self.xlist.values
            self.data['iny'] = self.ylist.values
            
            ax.scatter(self.data.inx, self.data.iny, s=0, color=colors[i], cmap='jet')
            ax.plot(self.data.inx,self.data.iny, linestyle = '-', lw=1, color=colors[i], zorder=-1)
            ax.set_yscale('log') 
            if colx == 'xi':
                if temporal==True:
                    ax.set_title(str(columns_x[0]) + ' - ' + str(columns_x[-2]))
                    if space!=0:
                        ax.set_title(str(columns_x[0]) + ' - ' + str(columns_x[-2]) + ' / ' + str(abs(space)))
                else:
                    ax.set_title(str(self.xrecapl.columns[0]) + ' - ' + str(self.xrecapl.columns[-2]))
                ax.plot(self.data.inx,self.data.iny, linestyle = '-', lw=3, color='k', zorder=-1)
            # ax.set_xscale('log')
            # plt.close()
              
            self.qmax = self.ylist.max()
            self.qmin = self.ylist.min()
            self.qmed = self.ylist.median()
            self.qmean = self.ylist.mean()
            self.q10 = self.ylist.quantile(0.1)
            self.q90 = self.ylist.quantile(0.9)
            
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
            
            self.long = np.sqrt( (xmax - xmin)**2 + (self.qmax - self.qmin)**2 )
            x_m_point = (self.data.inx[id_min] + self.data.inx[id_max])/2
            y_m_point = (self.qmin + self.qmax)/2
            long_min = (xmin, self.qmin)
            long_max = (xmax, self.qmax)
            
            long_x = np.linspace(long_min[0], long_max[0], 100)
            long_y = np.linspace(long_min[1], long_max[1], 100)

            reg = linregress(long_x, long_y)
            self.reg_stat = pd.DataFrame(columns=['center_x','center_y','slope','intercept',
                                              'r_value','p_value','std_err','lenght_reg'])
            self.reg_stat.loc[len(self.reg_stat)] = reg
            self.slope = self.reg_stat.slope[0]
            
            domain = np.linspace(long_min[0], long_max[0])
            perp_line = [perpendicular_line(x, [x_m_point, y_m_point],
                                            list(long_min), list(long_max)) for x in domain]

            line_perp = SG.LineString([(min(domain), max(perp_line)), (max(domain), (min(perp_line)))])
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

            polyg_loop = Polygon(tuple(self.data.itertuples(index=False, name=None)))
            line_long = SG.LineString([long_min, long_max])
            areas = cut_polygon_by_line(polyg_loop, line_long)
            try:
                self.area_plus = areas[1].area
                self.area_minus = areas[0].area
                self.area = polyg_loop.area
            except:
                self.area_plus = np.nan
                self.area_minus = np.nan
                self.area = np.nan
                pass
                        
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
            self.dfmet.loc[colx, 'hi'] = self.hi
            self.dfmet.loc[colx, 'long'] = self.long
            self.dfmet.loc[colx, 'short'] = self.short
            self.dfmet.loc[colx, 'excent'] = self.excent
            self.dfmet.loc[colx, 'short_p'] = self.short_plus
            self.dfmet.loc[colx, 'short_n'] = self.short_minus
            self.dfmet.loc[colx, 'area'] = self.area
            self.dfmet.loc[colx, 'area_p'] = self.area_plus
            self.dfmet.loc[colx, 'area_n'] = self.area_minus
            self.dfmet.loc[colx, 'slope'] = self.slope
            
        self.dfmet.to_csv('Metrics_'+'Obs_'+self.name+'_'+str(space)+'.csv', sep=';')

#%% OBS. LAUNCH

var = 'EFF'
mod = 'REA'
sce = 'historic'

# Qobs_path = 'D:/Users/abherve/HYDROMETRY/data/EBR/J7353010_Le Meu ï¿½ Montfort-sur-Meu - L\'Abbaye/Hydrometric_J7353010_Le Meu à Montfort-sur-Meu [L\'Abbaye]_281446-2356379_468_29_1968-2022.csv'
Qobs_path = 'D:/Users/abherve/HYDROMETRY/data/EBR/J7364220_La Chï¿½ze ï¿½ Plï¿½lan-le-Grand - L\'Enlevrier/Hydrometric_J7364220_La Chèze à Plélan-le-Grand [L\'Enlevrier]_273631-2343510_9.3_88_1989-2022.csv'
Qobs = pd.read_csv(Qobs_path, sep=';', index_col=0, parse_dates=True)
area = float(Qobs_path.split('_')[-3])
Qobs = (Qobs / (area*1000000)) * (3600 * 24) * 1000 # m3/s to mm/day
Qobs = Qobs.squeeze()

Cobs_path = 'D:/Users/abherve/TEST/Outlet/results_stable/climatic/_ALL_D.csv'
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
            
hyst = Hysteresis(DFobs, 'Cheze')
hyst.prepare_xy_raw()
hyst.plot_xy_data(var + ' [mm]', 'Q [mm]', [-150,150], [0,150], 'gist_rainbow_r')
hyst.compute_xy_metrics(temporal=True, space=-10)

d = hyst.dfmet[:-1]
for i in d.columns:
    fig, ax = plt.subplots(1,1, figsize=(7,4))
    col = i
    ax.plot(d[col])
    ax.ticklabel_format(useOffset=False)
    ax.set_title(col.upper())
    ax.set_xticks(np.arange(d.index.min(), d.index.max()+1, 5))
    ax.grid(axis='x')
    ax.set_yscale('log')
    plt.close()

#%% WATERSHED MODEL

git_path = "D:/Users/abherve/GITHUB/HydroModPy/CORE_COMM/"
# Path to the data folder
data_path = "C:/Users/ronan/OneDrive/_HydroDataPy/"
# Path where the results will be stored
out_path = "D:/Users/abherve/HYSTERESIS/"

dems_path = data_path + 'DEM/France/' # reginal DEM or conceptual DEM
shp_path = data_path + 'SHAPEFILE/' # if you want run a model from a shapefile
modflow_path = data_path + 'SOFTWARE/MODFLOW/' # add bin/ folder with necessary .exe

surfex_path =  data_path + 'CLIMATE/FRANCE/SURFEX/Rennes/' # add surfex models in .h5 format (France scale, else, specify None)
geology_path = data_path + 'GEOLOGY/France/Layer/' # add geologic layers
oceanic_path = data_path + 'OCEANIC/' # add specific sea level files
hydrology_path = data_path + 'HYDROLOGY/France/Hydrographic/' # add hydrographic shapefiles
hydrometry_path = data_path + 'HYDROLOGY/France/Hydrometry/' # add hydrometry data for automatic download
intermittency_path = data_path + 'HYDROLOGY/France/Intermittency/' # add intermittency data for automatic download
piezometry_path = False # add piezometry data for automatic download
subbasin_path = False # generate subbasins from stations or manual points

library_path = git_path + 'watershed/' + 'watershed_library.csv' # each row is a study site with outlet coordinates

watershed_name = 'Cheze' # search the name in watershed_library or just label your result folder
print('##### '+watershed_name.upper()+' #####')

dem_name = "BDALTI_bzh_75m.tif" # name of dem
from_shp = None # specify a path if process start from a given shapefile
from_dem = False # True or False if the process start from a given DEM of xyz file
cell_size = None # specify new resolution from a given DEM or None

types_obs = ['streams_fr','sections_bzh'] # list of shapefile name layers for clip hydrology
fields_obs = ['FID', 'Persistanc'] # list of shapefile name columns to translate as a tif

# Depending on the choices
dem_path = dems_path + dem_name

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    
load = True

BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              modflow_path=modflow_path,
                              library_path=library_path,
                              load=load,
                              from_shp=from_shp,
                              from_dem=from_dem,
                              cell_size=cell_size)

if load != True :
    BV.add_surfex(surfex_path) 
    BV.add_geology(geology_path) 
    BV.add_hydrology(hydrology_path, types_obs=types_obs, fields_obs=fields_obs)
    BV.add_oceanic(oceanic_path)
    BV.add_hydrometry(hydrometry_path)
    BV.add_intermittency(intermittency_path)
    if piezometry_path == True:
        BV.add_piezometry()
    if subbasin_path == True:
        BV.add_subbasin()

watershed_display.watershed_dem(BV)
watershed_display.watershed_local(dem_path, BV)

#%% SET PARAMETERS

# Input recharge
var = 'REC'
mod = 'REA'
sce = 'historic'
typ = 'sinu' # sinu / hist / proj

# Choice temporal of the simulation
sim_state = 'transient' # 'steady' or 'transient'
period = [2015,2019] # rehcarge period
first = period[0]
last = period[1]
time_step = 'M' # or 'D'
actual_date = True # False if date is conceptual
start = str(period[0])+'-01-01' # necessary to specify the first time_step date

# Active of not modules
first_only = False # if True generate results only for the first tim_step
box = False # if True generate a rectangular model
sink_fill = False # permit to fill sinks
modpath_sim = False # run modpath particle tracking if True
verbose = True # add print of MODFLOW in console

# Strcture of the model
lay_number = 1 # vertical discrtization
bottom = None # aquifer flat or not
thick_exp = 1 # exponential decay of K with nlay
cond_decay = 0 # exponential decay of K with depth
thick = 30 # m

# Hydraulic properties
Koptim = 1e-5
Ks = np.array([Koptim/10,Koptim,Koptim*10]) * 3600 * 24 * 30 # m/second to m/month
Sys = [0.001,0.01,0.1]

# Ks = np.array([Koptim/10]) * 3600 * 24 * 30 # m/second to m/month
# Sys = [0.001]

#%% RUN SIMULATIONS

# Update properties
for K in Ks:
    for Sy in Sys:
        # K = 1e-5
        # Sy = 0.01
        # print(K)
        BV.hydrodynamic.update_thickness(thick)
        BV.hydrodynamic.update_hyd_cond(K) 
        BV.hydrodynamic.update_porosity(Sy)
        
        BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = sce,
                                          first_year = first, last_year = last, 
                                          time_step = time_step, sim_state=sim_state)
        Rech = BV.forcing.recharge # m/month
        if typ == 'sinu':
            BV.forcing.update_sinusoid_recharge(Rech, 'M', 1, 1, 1, 1) # serie, period, amplitude, offset, omega, phase
            Rech = BV.forcing.recharge
            
        date_today = datetime.now().strftime("%d/%m/%Y %H:%M:%S") # just a string
        date_today = date_today.replace('/','-')
        date_today = date_today.replace(':','-')
        date_today = date_today.replace(' ','_')
        
        model_name = typ+'_'+var+'-'+mod+'-'+sce+'_'+str(round(K,2))+'-'+str(Sy)+'-'+str(thick)+'_'+str(first)+'-'+str(last)
        
        # Run model
        BV.run_modflow(ident=model_name,
                        modpath_sim=modpath_sim,
                        first_only=first_only,
                        sink_fill=sink_fill,
                        box=box,
                        lay_number=lay_number,
                        bottom=bottom,
                        thick_exp=thick_exp,
                        cond_decay=cond_decay,
                        verbose=verbose)

        # Extract results
        BV.results_modflow(ident=model_name,
                            actual_date=actual_date,
                            start=start,
                            time_step=time_step)
        
        # Plot maps
        from groundwater_flow import modflow_display
        freq_interv = 12 # number of tim_step to take account in intermittency check
        save_gif = True # save a gif after plots
        surf = modflow_display.SurfaceOutputs(Rech, simulations_folder, stable_folder, model_name, 
                                              types_obs, freq_interv=freq_interv, save_gif=save_gif,
                                              outflow=True, accflux=True, intermittency=True, 
                                              chronics=True, sim_state=sim_state)
            
#%% MOD. SYNTHETIC

import os

var = 'REC'
mod = 'REA'
sce = 'historic'

simuls = os.listdir(simulations_folder)

for simul in simuls:
    try:

        Qmod_path = simulations_folder+simul+'/_watershed/_simulated_results.csv'
        Qmod = pd.read_csv(Qmod_path, sep=';', index_col=0, parse_dates=True)
        Qmod = Qmod['outflow_drain'] * 1000 # m/month to mm/month
        # Qmod = Qmod['seepage_areas'] # %
        Qmod = Qmod.squeeze()
        
        Cmod_path = simulations_folder+simul+'/_watershed/_simulated_results.csv'
        Cmod = pd.read_csv(Cmod_path, sep=';', index_col=0, parse_dates=True)
        Cmod = Cmod['recharge'] * 1000 # m/month to mm/month
        
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
        
        hyst = Hysteresis(DFmod, 'Test')
        hyst.prepare_xy_raw()
        hyst.plot_xy_data(var + ' [mm]', 'Q [mm]', [-10,50], [0.1,100], 'gist_rainbow_r')
        # hyst.compute_xy_metrics(temporal=False, space=0)

    except:
        pass
    
#%% ORTHO ARCHIVE
"""
def line(x, line_point1, line_point2, get_eq=False):
    m = (line_point1[1] - line_point2[1])/(line_point1[0] - line_point2[0])
    b = line_point1[1] - m*line_point1[0]
    if get_eq:
        return m, b
    else:
        return m*x + b

def perpendicular_line(x, line_point1, line_point2, random_point, get_eq=False):
    m, b = line(0, line_point1, line_point2, True)
    m2 = -1/m
    b2 = random_point[1] - m2*random_point[0]
    if get_eq:
        return m2, b2
    else:
        return m2*x + b2
    
def get_intersection(line_point1, line_point2, random_point):
    m, b = line(0, line_point1, line_point2, True)
    m2, b2 = perpendicular_line(0, line_point1, line_point2, random_point, True)
    x = (b2 - b) / (m - m2)
    y = line(x, line_point1, line_point2)
    return [x, y]

#####################################################################################################
one = np.arange(min(data.min()),max(data.max()),0.1)
line_point1 = [one.min(),one.min()]
line_point2 = [one.max(),one.max()]
plt.plot(one)
plt.plot(line_point1)
compteur = 1
ortho = pd.DataFrame(index=range(1,len(data)))
for d in range(1,len(data)):
    random_point = [data.inx.loc[d], data.iny.loc[d]]
    plt.plot(random_point)
    intersection = get_intersection(line_point1, line_point2, random_point)
    plt.plot(intersection)
    xgiv = (random_point[0] - intersection[0])
    ygiv = (random_point[1] - intersection[1])
    distance = ((random_point[0] - intersection[0])**2 + (random_point[1] - intersection[1])**2)**0.5
    plt.plot(distance)
    if ygiv <= 0:
        distance = abs(distance)
    ortho.loc[compteur,'ecart'] = distance
    ortho.loc[compteur,'inters_x'] = intersection[0]
    ortho.loc[compteur,'inters_y'] = intersection[1]
    compteur += 1
    
random_point = [reg_stat.center_x, reg_stat.center_y]
intersection = get_intersection(line_point1, line_point2, random_point)
xgiv = (random_point[0] - intersection[0])
ygiv = (random_point[1] - intersection[1])
ecart_center = ((random_point[0] - intersection[0])**2 + (random_point[1] - intersection[1])**2)**0.5
#####################################################################################################
"""
#%% NOTES 

# qmax = hyst.yrecap.apply(lambda i: i.max(), axis=0)

# fig = plt.figure()
# ax = fig.add_subplot(111)
# ax.plot(domain, [line(x) for x in domain], label='given line')
# ax.plot(random_point[0], random_point[1], 'ro', label='given point')
# ax.plot(domain, perp_line, '--', color='orange', label='perpendicular line')
# ax.set_aspect('equal')

