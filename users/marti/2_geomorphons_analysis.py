# -*- coding: utf-8 -*-
"""
Created on Thu Aug 31 12:40:43 2023

@author: emarti
"""

#%% LIBRAIRIES

import numpy as np
import pandas as pd
import rioxarray as rxr
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False


#%%PATHS
user_path = "Etienne"
data_path = "D:/emarti/Chile/data/"
out_path = "D:/emarti/Chile/out/"
watershed_name="North_chile"

##Variables defintion for wbt.geomorphons 
search_distance = 10 #Distance in DEM cells
angle_threshold = 1 #In degrees 
skip_distance = 1 #Distance in DEM cells 

stable_folder = out_path+str(watershed_name)+'/'+'results_stable/'
geographic = stable_folder+'geographic/'
dem_path = geographic+'watershed_dem.tif'
wbt.geomorphons(dem_path,geographic+'geomorphons.tif',search=search_distance,threshold=angle_threshold,skip=skip_distance)

forms = ['Flat','Peak','Ridge','Shoulder','Spur','Slope','Hollow','Footslope','Valley','Pit']

#Definiton of a df with geomorphons classified according to the landform associated to each value. 
geomorphonspath = geographic+'geomorphons.tif'
geomorphons_ = rxr.open_rasterio(geomorphonspath, masked=True).squeeze()
geomorphons_np = geomorphons_.to_numpy()
geomorphons_np[geomorphons_np == -32768] = np.nan
geomorphons = geomorphons_np[~np.isnan(geomorphons_np)]
results_geomorphons = []
for iteration, form in enumerate(forms):
    results_geomorphons.append(
        {'Form': form, 'Count': np.count_nonzero(geomorphons == iteration+1)})
df_geomorphons = pd.DataFrame(results_geomorphons)
df_geomorphons = df_geomorphons.set_index('Form')
df_geomorphons['Normalized'] = df_geomorphons['Count']/geomorphons.size


#Histogram definition of normalized occurences of each landform defined (the color code was defined following the color associated on the plot of the geomoprhopns map)
fig, ax = plt.subplots(figsize=(11.8, 9.8))
df_geomorphons.plot.bar(y='Normalized', color=[
    '#ec9334', '#d1403f', '#bfd358', '#a777b2', '#3c4697', '#d0338b', '#7ebe66', '#80c180', '#67c3c8', '#85a8d9'], width=0.85, legend=False, fontsize=32, ax=ax)
#plt.xlim([0.00001, 100])
plt.ylim([0, max(df_geomorphons['Normalized'])+0.05])
plt.xlabel('', fontsize=24)
plt.ylabel('Normalized occurrences', fontsize=30)
plt.grid(visible=True, which='both', linewidth=0.25)
image_format = 'svg'  # e.g .png, .svg, etc.
image_name = 'histo_geomorphons_xtreme2.svg'
#fig.savefig(out_path+image_name, format=image_format, dpi=1200)
plt.show()

    