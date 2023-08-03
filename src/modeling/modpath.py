# -*- coding: utf-8 -*-
"""

Created on 2023

@author: Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy

"""

#%% LIBRAIRIES

# Python
import os
import sys
import flopy
import flopy.utils.binaryfile as fpu
import numpy as np
from os.path import dirname, abspath
import random
import pickle
import geopandas as gpd

# Root
df = dirname(dirname(abspath(__file__)))
sys.path.append(df)

# HydroModPy
from tools import toolbox

#%% CLASS

class Modpath:

    #%% INIT
    
    def __init__(self,
                 geographic,
                 model_modflow,
                 # Worflow settings
                 model_folder=os.getcwd()[:2]+'/'+'HydroModPy_Output/',
                 model_name='modflow_model',
                 bin_path = os.path.join(os.getcwd(),'bin'),
                 # Specific settings
                 zone_partic='domain'):
        
        self.zone_partic = zone_partic
        self.model_name = model_name
        self.geographic = geographic
        self.model_folder = model_folder
        self.full_path = os.path.join(model_folder, model_name)
        if not os.path.isdir(self.full_path):
            raise FileNotFoundError('Directory not found: {}'.format(self.full_path))
        if (sys.platform == 'win32') or (sys.platform == 'win64'):
            self.exe = self.exe = os.path.join(bin_path, 'win' ,'mp6.exe')
        if (sys.platform == 'linux'):
            self.exe = os.path.join(bin_path, 'linux' ,'mp6')
        if (sys.platform == 'darwin'):
            self.exe = os.path.join(bin_path, 'mac' ,'mp6')
        
        self.model_modflow = model_modflow
        
    #%% PRE-PROCESSING
    
    def pre_processing(self):
        
        prefix = os.path.join(self.full_path, self.model_name)
        nam_file = '{}.nam'.format(prefix)
        dis_file = '{}.dis'.format(prefix)
        head_file = '{}.hds'.format(prefix)
        bud_file = '{}.cbc'.format(prefix)
        bas_file = '{}.bas'.format(prefix)
        lpf_file = '{}.upw'.format(prefix)

        self.mf = flopy.modflow.Modflow.load(nam_file, model_ws=self.full_path, verbose=False, check=False)
        
        bas = flopy.modflow.ModflowBas.load(bas_file, self.mf)
        lpf = flopy.modflow.ModflowUpw.load(lpf_file, self.mf, check=False)
        nlay = self.mf.nlay
        ncol = self.mf.ncol
        nrow = self.mf.nrow
        laytype = lpf.laytyp.array
        iboundData = bas.ibound.array
        
        self.mp = flopy.modpath.Modpath6(modelname=self.mf.name,model_ws=self.full_path, simfile_ext='mpsim', namefile_ext='mpnam', version='modpath',
                               exe_name=self.exe, modflowmodel=self.mf, head_file=head_file, dis_file=dis_file, dis_unit=87, budget_file=bud_file)
        self.mp.array_free_format = True
        cbb = fpu.CellBudgetFile(bud_file)
        # cbb.list_records()
        rec_drn = cbb.get_data(kstpkper=(0, 0), text='DRAINS')
        rec_rch = cbb.get_data(kstpkper=(0, 0), text='RECHARGE')
        
        drn = np.ones((nrow, ncol))
        compti = 0
        comptj = 0
        for ii in range(0, rec_drn[0].shape[0]):
            drn[compti, comptj] = -1 * rec_drn[0][ii][1]
            comptj += 1
            if comptj == ncol:
                compti += 1
                comptj = 0
        rch = rec_rch[0][1]
        b = drn / rch
        b[np.isnan(b)]=0
        szone = []
        for i in range(0, nlay):
            a = np.zeros((nrow, ncol), dtype=int)
            if i == 0:
                a[b >= 1] = 1
            a[iboundData[i] == -1] = 1
            szone.append(a)

        self.mp.dis_file = dis_file
        self.mp.head_file = head_file
        self.mp.budget_file = bud_file

        flopy.modpath.Modpath6Sim(model=self.mp, option_flags=[2, 1, 1, 1, 1, 2, 2, 1, 1, 2, 1, 1],
                                   group_placement=[[1, 1, 1, 0, 1, 1]], stop_zone=1, zone=szone)
        
        stl = flopy.modpath.mp6sim.StartingLocationsFile(model=self.mp, inputstyle=1)
        prow = 1
        pcol = 1
        
        # To apply particules only on the pixels of the catchment, buff box
        if self.zone_partic == 'watershed':
            mask_dem = self.geographic.dem_clip
            stldata = stl.get_empty_starting_locations_data(npt=np.sum(mask_dem != -9999)*pcol*prow)
        if self.zone_partic == 'domain':
            mask_dem = self.geographic.dem_clip
            stldata = stl.get_empty_starting_locations_data(npt=np.sum(mask_dem >= -9999)*pcol*prow)

        hds_1c = fpu.HeadFile(head_file)
        head_1c = hds_1c.get_alldata(mflay=None)

        head = np.full((nrow, ncol), np.nan)
        for i in range(0, nrow):
            for j in range(0, ncol):
                for k in range(0, nlay):
                    if head_1c[0][k][i, j] > 0:
                        head[i, j] = head_1c[0][k][i, j]
                        break

        compt = 0
        for i in range(0, nrow):
            for j in range(0, ncol):
                if self.zone_partic == 'watershed':
                    if self.geographic.dem_clip[i,j] != -9999.: # active or note
                        if head_1c[0][0][i][j] != 0.48:
                            for ii in range (0, prow):
                                for jj in range (0, pcol):
                                    stldata[compt]['label'] = 'p' + str(compt + 1) + '-'+str(ii)+ '-'+str(jj)
                                    for k in range(0, nlay):
                                        if head_1c[0][k, i, j] > 0:
                                            stldata[compt]['k0'] = k
                                            break
                                    stldata[compt]['j0'] = j
                                    stldata[compt]['i0'] = i
                                    stldata[compt]['zloc0'] = 1
                                    stldata[compt]['xloc0'] = (ii+0.1)/(prow+0.2)
                                    stldata[compt]['yloc0'] = (jj+0.1)/(pcol+0.2)
                                    compt = compt + 1
                if self.zone_partic == 'domain':
                    if self.geographic.dem_clip[i,j] >= -9999.: # active or note
                        if head_1c[0][0][i][j] != 0.48:
                            for ii in range (0, prow):
                                for jj in range (0, pcol):
                                    stldata[compt]['label'] = 'p' + str(compt + 1) + '-'+str(ii)+ '-'+str(jj)
                                    for k in range(0, nlay):
                                        if head_1c[0][k, i, j] > 0:
                                            stldata[compt]['k0'] = k
                                            break
                                    stldata[compt]['j0'] = j
                                    stldata[compt]['i0'] = i
                                    stldata[compt]['zloc0'] = 1
                                    stldata[compt]['xloc0'] = (ii+0.1)/(prow+0.2)
                                    stldata[compt]['yloc0'] = (jj+0.1)/(pcol+0.2)
                                    # print(compt)
                                    compt = compt + 1
        self.point_data = stldata
        stl.data = stldata
        
        self.poro_modpath = self.model_modflow.ps
        
        flopy.modpath.Modpath6Bas(self.mp, hnoflo=-9999.0, hdry=-100, def_face_ct=0,
                                  laytyp=laytype, ibound=iboundData,
        										prsity=self.poro_modpath, prsityCB=self.poro_modpath,
                                  extension='mpbas', unitnumber=86)
        
        self.mp.write_input()    
        
    #%% PROCESSING
    
    def processing(self,
                   write_model=True,
                   run_model=False):
        
        # Create modflow files
        if write_model == True:
            self.mp.write_input()  
       
        # Run modflow files
        success_model = False
        if run_model == True:
            verbose = True
            success_model, tempo = self.mp.run_model(silent=not verbose) # True without msg
        
        return success_model

    #%% POST-PROCESSING
    
    def post_processing(self, 
                        model_modpath,
                        ending_point = True,
                        starting_point = True,
                        pathlines_shp = True,
                        particules_shp = True,
                        random_id = None):
        
        self.full_path = os.path.join(model_modpath.model_folder, model_modpath.model_name)
        
        self.particules_file = os.path.join(self.full_path, '_postprocess', '_particules')
        toolbox.create_folder(self.particules_file)
        
        grid_model = model_modpath.mf.modelgrid
        
        path_mpend = os.path.join(model_modpath.model_folder, model_modpath.model_name, model_modpath.model_name)
        endobj = flopy.utils.EndpointFile(path_mpend+'.mpend')
        e = endobj.get_alldata()
        
        crs = model_modpath.geographic.crs_proj
        if isinstance(crs, (int,float)) == True:
            epsg = crs
        elif crs[:4].upper() == 'EPSG':
            epsg = int(crs.split(':')[-1])
        else:
            epsg = None
        
        if ending_point == True:
            endobj.write_shapefile(endpoint_data=e,
                                   shpname=os.path.join(self.particules_file, 'ending.shp'),
                                   direction='ending',
                                   mg=grid_model,
                                   epsg=epsg,
                                   sr=None)
        
        if starting_point == True:
            endobj.write_shapefile(endpoint_data=e,
                                   shpname=os.path.join(self.particules_file, 'starting.shp'),
                                   direction='starting',
                                   mg=grid_model,
                                   epsg=epsg,
                                   sr=None)
        
        path_mppth = os.path.join(model_modpath.model_folder, model_modpath.model_name, model_modpath.model_name)
        pthobj = flopy.utils.PathlineFile(path_mppth+'.mppth')
        pth_data = pthobj.get_alldata()
            
        if random_id != None:
            shp_endpoint = gpd.read_file(os.path.join(self.particules_file, 'ending.shp'))
            keep_id = shp_endpoint.particleid
            keep_id = keep_id.tolist()
 
            # if not os.path.exists(self.particules_file+'/_random_id.data'):
            id_random_particules = random.sample(keep_id[:-1], random_id)
            with open(self.particules_file+'/_random_id.data', 'wb') as f:
                pickle.dump(id_random_particules, f)
                    
            pth_data_save = []
            for o, i in enumerate(id_random_particules):
                # print(o, i, len(id_random_particules))
                for j in pth_data:
                    if i == j.particleid[0]:
                        pth_data_save.append(j)
        else:
            pth_data_save = pth_data
        
        if pathlines_shp == True:
            pthobj.write_shapefile(pathline_data=pth_data_save,
                                    shpname=os.path.join(self.particules_file, 'pathlines.shp'),
                                    one_per_particle=True, 
                                    direction='ending',
                                    mg=grid_model,
                                    epsg=epsg,
                                    sr=None)
        
        if particules_shp == True:
            pthobj.write_shapefile(pathline_data=pth_data_save,
                                    shpname=os.path.join(self.particules_file, 'particules.shp'),
                                    one_per_particle=False, 
                                    direction='ending',
                                    mg=grid_model,
                                    epsg=epsg,
                                    sr=None)
        
#%% NOTES

#ifaces = [6]  # top face:6 ; bottom face:5 ; row face:3-4 ; column face:1-2

#%% KEEP

"""
if residence_times == True:
    print('residence_times')
    # path_file = "D:/Users/abherve/DYNAMIC/Lasset/results_simulations/case4_0.05500000000000001/case4_0.05500000000000001"
    # res_time = np.zeros(np.shape(imageio.imread(BV.geographic.watershed_dem)))
    # pthobj = flopy.utils.PathlineFile(self.path_file+'.mppth')
    # pth_data = pthobj.get_alldata()
    res_time = np.zeros(np.shape(self.dem)) * np.nan
    endobj = flopy.utils.EndpointFile(self.path_file+'.mpend')
    e = endobj.get_alldata()
    for k in range(len(e)):
        # time_out = pth_data[j].time[0] # explore pathlines
        # res_time[e[j].i0,e[j].j0] = np.log10(e[j].time) # where infiltrated
        # res_time[e[j].i,e[j].j] = np.log10(e[j].time) # where outputed
        res_time[e[k].i,e[k].j] = (e[k].time) / 365 # where outputed in years
    if export_tif==True:
        output_path = self.tifs_file+'/residence_times_t('+lead_numb+').tif'
        toolbox.export_tif(self.dem_path, res_time, -9999, output_path)
    self.dict_residence_times[item] = res_time
    
try:
    if residence_times == True:
        np.save(self.save_file+'/residence_times', self.dict_residence_times)
except:
    pass
"""
