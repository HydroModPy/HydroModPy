# -*- coding: utf-8 -*-
"""
Created on Tue Jul 11 08:57:35 2023

@author: emarti
"""
import numpy as np
import pandas as pd
import statistics
import xarray as xr
import rioxarray as rxr

#%%

###geol_model_path
### This should link to a xyz file  with 4 columns 
### In this order : X Y Z Formation_ID (columns name is not important only the order)
### Firt row is the header 

###formation_param_path
### This should link to a file  with 3 columns linking formation_ID to hydraulic conductivity and porosity 
### In this order : Formation_ID HK Porosity (columns name is not important only the order)
### Firt row is the header 
###Then one row for each formation 

####Dem path and z_discretization shoud be given to function in order to get the spatial discretization in xyz of the modflow model

### extrapol_method 1 based on the generation of an index associating modflow cell and geological model cell (Modified from Hugo code)
### Takes longer in time yet the generated index can be stor and reuse in the future if both discretization stay the same but geological model change
### Looks more accurate as well

###extrpapol method 2 based on Hatarilabs tutorial https://hatarilabs.com/ih-en/how-to-insert-a-3d-geology-into-a-modflow-model-with-python-and-flopy-tutorial
###Faster but less accurate, need to recreate the model for each change in geology in contrast with 1st method 

##load index can be used if extrapol method 1 was used before to reload the geological index instead of creating it again

def geol(geol_model_path, formation_param_path, dem_path, z_discretization, extrapol_method: int=1, load_index: bool=False):
    geological_path = 'D:/emarti/geological_model/'
    ####Import DEM to retrieve discretization info
    dem =  rxr.open_rasterio(dem_path, masked=False).squeeze()
    nrow = dem.shape[0]
    ncol = dem.shape[1]
    nlay = np.shape(z_discretization)[0]-1 ##nlay obtained from the DIS package modelgrid should be defined

    ##To compare modflow discretization with geological model, need to have similar format
    ###MODFLOW model to XYZ with element indexing (additional corresponding col,row,lay for modflow model)
    x_1 = dem.x.to_numpy()
    y_1 = dem.y.to_numpy()
    zVerts = z_discretization
    
    ###We want to have the center of the cell to extrapolate correctly 
    x_mid = [(x_1[i]+x_1[i+1])/2 for i in range(ncol-1)]
    y_mid = [(y_1[i]+y_1[i+1])/2 for i in range(nrow-1)]
    z_mid = np.rollaxis(np.dstack([(zVerts[i]+zVerts[i+1])/2 for i in range(nlay)]),-1)
    
    #Using meshgrid to associate x and y 
    xx_mid,yy_mid=np.meshgrid(x_mid,y_mid)
    ##Defining similar idea for rows and cols
    rows=[x for x in range(nrow-1)]
    cols = [x for x in range(ncol-1)]
    cc,rr=np.meshgrid(cols,rows)
    
    ###After meshgrid generation formatting it to columns again
    cc_list=np.squeeze(cc.reshape(-1,1))
    rr_list=np.squeeze(rr.reshape(-1,1))
    xxmid_list = np.squeeze(xx_mid.reshape(-1,1))
    yymid_list= np.squeeze(yy_mid.reshape(-1,1))
    
    #Adding the Z and lay coordinates to the dataframe 
    xyz=[]
    for lay in range(nlay):
        df=pd.DataFrame({'X': xxmid_list,'Y':yymid_list,'Z': np.squeeze(z_mid[lay,:-1,:-1].reshape(-1,1)),'col':cc_list,'row':rr_list,'lay':lay})
        xyz.append(df)
    #Final df for modflow model 
    df_modflow=pd.concat(xyz,axis=0)
    #Associating an element ID to each cell to compare with geological model
    df_modflow['E'] =[i for i in range(len(df_modflow))]
    
    #Importing xyz geological model into a df
    if geol_model_path.endswith('csv'):
        df_geol = pd.read_csv(geol_model_path)
    else:
        df_geol  = pd.read_table(geol_model_path, delim_whitespace=True)
    
    ##Importing file associating formation and hydro parameters
    if formation_param_path.endswith('csv'):
        df_param = pd.read_csv(formation_param_path)
    else:
        df_param  = pd.read_table(formation_param_path, delim_whitespace=True)
    
    
    ####Define dictionnaries for mapping function 
    hk_dict = dict(df_param.iloc[:,[0,1]].values)
    porosity_dict = dict(df_param.iloc[:,[0,2]].values)
    ###Initializing hydraulic conductivity & porosity matrix  
    
    hk = np.ones((nlay, nrow, ncol))
    porosity = np.ones((nlay, nrow, ncol))
    
    ##Method 1 based on the index generation (initial code modified to restrain the seach radius around the looked cell)
    if extrapol_method == 1: 
        Posmin=[]
        print('Index in creation : Advancement %')
        for i in df_modflow['E']:
            # Target cell coordinates
            target_layer = int(df_modflow['lay'][df_modflow['E']==i])
            target_row = int(df_modflow['row'][df_modflow['E']==i])
            target_col = int(df_modflow['col'][df_modflow['E']==i])
            
            # Define the range for neighboring cells
            neighbor_range = 1
            
            # Loop to select neighboring cells
            neighbors = df_modflow[
                (df_modflow['lay'].between(target_layer - neighbor_range, target_layer + neighbor_range)) &
                (df_modflow['row'].between(target_row - neighbor_range, target_row + neighbor_range)) &
                (df_modflow['col'].between(target_col - neighbor_range, target_col + neighbor_range))]
            
            neighbors_geol = df_geol[
                (df_geol['X'].between(min(neighbors['X']),max(neighbors['X']))) &
                (df_geol['Y'].between(min(neighbors['Y']),max(neighbors['Y']))) &
                (df_geol['Z'].between(min(neighbors['Z']),max(neighbors['Z'])))]
            if neighbors_geol.empty:
                dist = np.square(df_modflow['X'].iloc[i]-df_geol['X']) + np.square(df_modflow['Y'].iloc[i]-df_geol['Y']) + np.square(df_modflow['Z'].iloc[i]-df_geol['Z'])
                posmin = np.argmin(dist)
            else:
                dist = np.square(float(neighbors['X'][neighbors['E']==i])-neighbors_geol['X']) + np.square(float(neighbors['Y'][neighbors['E']==i])-neighbors_geol['Y']) + np.square(float(neighbors['Z'][neighbors['E']==i])-neighbors_geol['Z'])
                posmin = dist.index[np.argmin(dist)]
            Posmin.append(posmin)
            ###Print the porcentage of advancement in index creation 
            print(str(round(i/len(df_modflow['E'])*100,5))+'%')
            
        ##New df creation with index association with modflow cell and formation 
        df_final = df_modflow.copy()
        df_final['geol_index'] = Posmin
        df_final['Formation'] = [x for x in df_geol.iloc[:,3].loc[Posmin]] ##3rd column is the formation column
        df_final['HK'] = df_final['Formation'].map(hk_dict) ###Add corresponding hk value
        df_final['Porosity'] = df_final['Formation'].map(porosity_dict) ###Add corresponding porosity value
        
        ####Extract corresponding HK and Porosity matrix
        hk[df_final['lay'],df_final['row'],df_final['col']] = df_final['HK']
        porosity[df_final['lay'],df_final['row'],df_final['col']] = df_final['Porosity']
        
        
        ####generate a dataframe csv that include the index for future uses
        df_final.to_csv(geological_path+'index.csv')
        ####Return the final matrices and 
    
    ##Method 2 modified from Hatarilab approach
    if extrapol_method == 2: 
        for lay in range(nlay):
            for row in range(nrow-1):
                for col in range(ncol-1):
                    cellXmin = x_1[col]
                    cellXmax = x_1[col+1]
                    cellYmin = y_1[row+1]
                    cellYmax = y_1[row]
                    cellZmin = zVerts[lay+1,row,col]
                    cellZmax = zVerts[lay,row,col]
                    
                    df_cell= df_geol[((df_geol.X>=cellXmin) & (df_geol.X<cellXmax) & (df_geol.Y>=cellYmin) & (df_geol.Y<cellYmax) & (df_geol.Z>=cellZmin) & (df_geol.Z<cellZmax))]
                    
                    if len(df_cell)>0:
                        try:
                            litoMode = statistics.mode(df_cell.formation)
                        except statistics.StatisticsError:
                            litoMode = max(df_cell.formation)            
                    else:
                        litoMode = -9999
                    if litoMode ==-9999:
                        hk[lay,row,col]=np.nan
                        porosity[lay,row,col]=np.nan
                    else:
                        hk[lay,row,col]=hk_dict[litoMode]
                        porosity[lay,row,col]=porosity_dict[litoMode]
     
    ####Extrapolation function for NoData value look for the most represented non-NoValue data around itself
    for lay in range(nlay):
        for row in range(nrow-1):
            for col in range(ncol-1):
                col_range = [col-1,col,col+1]
                row_range = [row-1,row,row+1]
                if np.isnan(hk[lay,row,col]): ### For hydraulic conductivity
                    extrapol= []
                    for row_treat in row_range:
                        for col_treat in col_range:
                            extrapol.append(hk[lay,row_treat,col_treat])
                    hk_extrapol=statistics.mode(extrapol)
                    hk[lay,row,col] = hk_extrapol
                if np.isnan(porosity[lay,row,col]): ###For porosity 
                    extrapol_1 = []
                    for row_treat in row_range:
                        for col_treat in col_range:
                            extrapol_1.append(porosity[lay,row_treat,col_treat])
                    porosity_extrapol=statistics.mode(extrapol_1)
                    porosity[lay,row,col] = porosity_extrapol
    
    ####Return the final matrices
    return(hk, porosity)  

#%%
import flopy
import os 

#%%
bin_folder = 'D:/emarti/bin'
modelname = "test_geol"
exe=os.path.join(bin_folder, 'mfnwt.exe')
mf = flopy.modflow.Modflow(modelname, exe_name=exe, version='mfnwt', listunit=2, verbose=False,)

nwt = flopy.modflow.ModflowNwt(mf, headtol=0.001, fluxtol=500, maxiterout=5000,
                                            thickfact=1e-05, linmeth=1, iprnwt=1, ibotav=1, options='COMPLEX',
                                            Continue=False, backflag=0) # ibotav=0



# dempath = 'D:/emarti/Tarapaca/out/final/Tarapaca/results_stable/geographic/watershed_box_buff_dem.tif'
dempath = 'D:/emarti/geological_model/geo_model_40x40.tif'
dem =  rxr.open_rasterio(dempath, masked=True).squeeze()
nrow = dem.shape[0]
ncol = dem.shape[1]
dx = float(dem.x[-1] - dem.x[0])/ncol
dy = float(dem.y[0] - dem.y[-1])/nrow
nlay=10
bottom=-1000
thick_exp = 1.

##Bottom definition for each of the layers 
zbot = np.ones((nlay, nrow, ncol))
bottom_layer = bottom              # Float for flat bottom case
exp_scale = 1-thick_exp**nlay

# p: evoling proportions of bottom layer to surface values
for i in range(1, nlay+1):
    if thick_exp == 1.:
        p = i / nlay    # Uniform thicknesses
    else:
        p = (1-thick_exp**i) / exp_scale   # Increasing thicknesses with depth
    # Weighted formula to go from bottom_layer to surface (self.dem)
    zbot[i-1] = bottom_layer * p + dem * (1-p)
    
dis = flopy.modflow.ModflowDis(mf, nlay, nrow, ncol, 
    delr=dy, delc=dx, top=dem.data, 
    botm=zbot)

#%%
geol_model_path = 'D:/emarti/geological_model/2layers_fold_xyz.vox'
formation_param_path = 'D:/emarti/geological_model/hydro_parameters_2layers.txt'
dempath = 'D:/emarti/geological_model/geo_model_40x40.tif'
z_discretization=mf.modelgrid.zvertices
extrapol_method = 1

#%%

hk, porosity = geol(geol_model_path, formation_param_path, dempath, z_discretization, extrapol_method)


#%%
import matplotlib.pyplot as plt
fig = plt.figure(figsize=(20, 3))
ax = fig.add_subplot(1, 1, 1)
modelxsect = flopy.plot.PlotCrossSection(model=mf, line={'Row': 20})

modelxsect.plot_array(hk)
linecollection = modelxsect.plot_grid()
plt.ylim(-1000)

#%%

fig = plt.figure(figsize=(12,8))
ax = fig.add_subplot(1, 1, 1, aspect='equal')
modelmap = flopy.plot.PlotMapView(model=mf)
linecollection = modelmap.plot_grid(linewidth=0.5, color='royalblue')
modelmap.plot_array(hk)

