#!/usr/bin/env python
# coding: utf-8

# <h1><center>TD1 - Notebook 1 : Extract your watershed </center></h1>

# ### 1. Load Hydromodpy librairies 

# In[1]:


# Libraries installed by default
import sys
import os
# Libraries need to be installed if not
import numpy as np
# Libraries added from 'conda install' procedure
import matplotlib.pyplot as plt
# Libraries added from 'conda forge' procedure
import rasterio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False


# ### 2. Complete your personal paths where hydromodpy sources are

# In[2]:


# Fill in the directory where Hydromodpy codes are
# root_dir = '/home/jean.marcais/Modeles/hydromodpy/HydroModpy'
root_dir = 'D:/Users/abherve/GITHUB/HydroModPy-0.1/'
# Add to the path the Hydromodpy directory to recognize HydroModpy functions, classes, etc.
sys.path.append(root_dir)
# Define the directory where the notebook is stored as the current working directory
cwd = os.getcwd()
if not cwd == root_dir:
    os.chdir(root_dir)
    print("Root path directory is: {0}".format(cwd))


# ##### Import the hydromodpy source files 

# In[3]:


import src # import the folder src from HydroModpy codes
import importlib # 
importlib.reload(src)
# import all the classes necessary to extract the watershed from Hydromodpy source files.
from src import watershed_root
from src.display import visualization_watershed
from src.tools import toolbox
fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large


# ##### Complete the paths where data are

# In[4]:


# complete the data paths
teaching_path = root_dir + "/teaching/"
data_path = teaching_path + "/data/"
# complete where modflow sources are
modflow_path = os.path.join(root_dir,'bin/')


# In[10]:


data_path


# ### 3. Start geographic analysis

# ##### Fill in data paths, watershed names and outlet coordinates

# In[5]:


# in the data folder, complete the DEM filename (it is the tif file, that you can also open in QGis)
dem_filename = 'BDAltiv2_75m.tif'
# full path of the dem tif file
dem_path = data_path + dem_filename
# Put load to False so that the watershed is created from scratch
load = False
# Complete the watershed name
watershed_name = 'Glueyre'
# Extract the watershed with the outlet coordinates
from_xyv = [820019.377455, 6.41561849e+06, 75, 10, 'EPSG:2154'] # [x, y, snap distance, buffer size]
# save_object to True will save the watershed object in the out_path for future reutilisation
save_object = True


# ##### Plot the dem and the outlet

# In[6]:


from rasterio.plot import show
from matplotlib_scalebar.scalebar import ScaleBar
dem_tmp = rasterio.open(dem_path)
fig, ax = plt.subplots(1, 1, figsize=(3,3), dpi=300)

bounds = dem_tmp.bounds
xlim = ([bounds[0], bounds[2]])
ylim = ([bounds[1], bounds[3]])
ax.set_xlim(xlim)
ax.set_ylim(ylim)
ax.get_xaxis().set_visible(False)
ax.get_yaxis().set_visible(False)
ax.set(aspect='equal') 
scalebar = ScaleBar(1,box_alpha=0, scale_loc = 'top', location='lower left')

ax.imshow(np.ma.masked_where(dem_tmp.read(1) < -100,dem_tmp.read(1)), cmap='terrain')
show(np.ma.masked_where(dem_tmp.read(1) < -100, dem_tmp.read(1)), ax=ax, transform=dem_tmp.transform, 
         cmap='terrain', alpha=0.75, zorder=2, aspect="auto")
ax.plot(from_xyv[0],from_xyv[1],'ro')


# ##### Complete the folder directory where data will be stored

# In[7]:


# out_path = '/home/jean.marcais/Bureau/tmp/hydromodpy/'
out_path = 'D:/Users/abherve/SIMULATIONS/HYDROMODPY/'
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'


# ##### Extract watershed contour from the DEM and the outlet coordinates

# In[8]:


print('##### '+watershed_name.upper()+' #####')
BV = watershed_root.Watershed(dem_path=dem_path,
                              out_path=out_path,
                              load=load,
                              watershed_name=watershed_name,
                              from_lib=None, # os.path.join(root_dir,'watershed_library.csv')
                              from_dem=None, # [path, cell size]
                              from_shp=None, # [path, buffer size]
                              from_xyv=from_xyv, # [x, y, snap distance, buffer size]
                              #bottom_path=bottom_path, # path
                              #modflow_path=modflow_path, 
                              save_object=save_object)


# ##### Plot the watershed

# In[11]:


visualization_watershed.watershed_dem(BV)


# <em> Compare the two figures, you have plotted. What have done the hydromodpy automatically ? Do you know other means to complete this task ? What is the advantage of doing it with hydromodpy ? </em>

# ##### Clip the Geology and Stream Network data to the watershed scale

# In[ ]:


BV.add_geology(data_path, types_obs='GEO1M.shp', fields_obs='CODE_LEG')
BV.add_hydrography(data_path, types_obs=['cours_eau_V'], fields_obs=['fid'])
BV.add_hydrometry(data_path, 'france hydrometric stations.shp')


# ##### Plot the watershed geology

# In[ ]:


visualization_watershed.watershed_geology(BV)


# <em> Describe the geology of the watershed. What is important to notice in the perspective of modeling the hydrogeology of this watershed. </em>

# 
# <em> All the data created for this specific catchment have been stored in your 'results_stable' folder. They are stored as shp or tif files depending on the nature of the data (vector or raster). Open some of them on QGis. Do not hesitate to generate plots on QGis rather than on Python if you are more comfortable with this. </em>
