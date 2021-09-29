# coding:utf-8

# Modules
import flopy
import numpy as np
import os
import pandas as pd
import sys
from os.path import dirname, abspath

import flopy.utils.binaryfile as fpu

# HydroModPy modules
df = dirname(dirname(abspath(__file__)))
sys.path.append(df)
from tools import file_adds
from tools import tif_adds

# VARIABLES GLOBALES

class Modflow():
    """
    model_name
    model_path
    dem : path of dem file (.tif)
    climatic : float or Dataframe Datatimeseries
    lay_number: int - number of layer - default is 1
    thickness_aquifer: float
    cond_hyd :
        - homogeneous : float
        - heterogeneous : numpy array (same size as the dem)
    porosity: :
        - homogeneous : float
        - heterogeneous : numpy array (same size as the dem)
    """
    def __init__(self, geographic,
                 climatic=8e-4, lay_number=1, thick=50,
                 bottom=None, thick_exp=1., hyd_cond=8.64e-2, porosity=0.01, 
                 sea_level=None, cond_decay=0.,
                 time_step='daily', model_name='modflow_model', 
                 model_folder=os.path.join(os.path.dirname(os.getcwd()), 'output'), 
                 exe=os.path.join(os.path.dirname(os.getcwd()), 'bin', 'mfnwt.exe')):
          
        self.model_name = model_name
        self.model_folder = model_folder
        self.full_path = os.path.join(model_folder, model_name) #'modraw'
        self.climatic = climatic
        self.sea_level = sea_level 
        self.time_step = time_step
        self.thick = thick
        self.thick_exp = thick_exp
        self.resolution = geographic.resolution
        self.bottom = bottom
        self.nlay = lay_number
        self.hyd_cond = hyd_cond
        self.porosity = porosity
        self.cond_decay = cond_decay
        self.xul = geographic.xmin
        self.yul = geographic.ymax
        if sea_level == None:
            self.dem = geographic.dem_data
            self.dem_path = geographic.watershed_buff_dem
        else:
            self.dem = geographic.dem_box_data     
            self.dem_path = geographic.watershed_box_buff_dem
        self.dem_clip = geographic.dem_clip
        self.exe = exe

    def pre_processing(self):
        print('Construction d\'un modèle')
        self.mf = flopy.modflow.Modflow(self.model_name, 
                                        exe_name=self.exe, version='mfnwt',listunit=2, verbose=False,
                                        model_ws=self.full_path) # external_path=self.full_path
        self.nwt = flopy.modflow.ModflowNwt(self.mf, headtol=0.001, fluxtol=500, maxiterout=1000, thickfact=1e-05, linmeth=1,iprnwt=0,ibotav=0, options='COMPLEX')

        try:
            if len(self.hyd_cond)!=1:
                self.dem[self.hyd_cond<0]=-9999
        except:
            pass

        if isinstance(self.climatic,(int,float))==True:
            self.nper = 1
            self.perlen = 1
            self.nstp = [1]
            self.steady = True
            self.start_datetime = None
        else:
            self.start_datetime = self.climatic.index[0]
            self.steady = np.zeros(len(self.climatic),dtype=bool)
            self.steady[0] = True
            self.nstp = np.ones(len(self.climatic))
            self.nper = len(self.climatic)
            self.perlen = np.ones(len(self.climatic))
            if self.time_step=='daily':
                for i in range(1,len(self.climatic)):
                    dif = self.climatic.index[i]-self.climatic.index[i-1]
                    self.perlen[i] = dif.days

        self.nrow = self.dem.shape[0]
        self.ncol = self.dem.shape[1]

        self.zbot = np.ones((self.nlay, self.nrow, self.ncol))
        if self.bottom is None:
            bottom_layer = self.dem - self.thick
        else:
            bottom_layer = self.bottom

        if self.thick_exp != 1.:
            exp_scale = 1-self.thick_exp**self.nlay
    
        for i in range(1, self.nlay+1):
            if self.thick_exp == 1.:
                p = i / self.nlay
            else:
                p = (1-self.thick_exp**i) / exp_scale
            self.zbot[i-1] = bottom_layer * p + self.dem * (1-p)

        self.dis = flopy.modflow.ModflowDis(self.mf, self.nlay, self.nrow, self.ncol, 
            delr=self.resolution, delc=self.resolution, top=self.dem.data, 
            botm=self.zbot, itmuni=4, lenuni=2, nper=self.nper, perlen=self.perlen, 
            nstp=self.nstp, steady=self.steady, xul=self.xul, yul=self.yul, start_datetime=self.start_datetime)
		#proj4_str=self.dem.crs)
    
        self.iboundData = np.ones((self.nlay, self.nrow, self.ncol))
        self.strtData = np.ones((self.nlay, self.nrow, self.ncol))* self.dem

        for i in range (self.nlay):
            if isinstance(self.sea_level,(int,float)) == True:
                self.iboundData[i][self.dem <= self.sea_level] = -1
                self.strtData[self.iboundData == -1] = self.sea_level
            self.iboundData[i][self.dem < -1000] = 0

        self.bas = flopy.modflow.ModflowBas(self.mf, ibound=self.iboundData, strt=self.strtData, hnoflo=-9999)

        # Constant Head package
        if self.sea_level != None:
            package = np.zeros((self.nper,self.nrow, self.ncol))
            if isinstance(self.sea_level,(int,float)) == False:
                self.chdData = {}
                for kper in range(0, self.nper):
                    chdKper = []
                    for i in range (0,self.nrow):
                        for j in range (0, self.ncol):
                            if self.dem[i,j] < self.sea_level[kper]:
                                package[kper,i,j] = 1
                                chdKper.append([0,i,j,self.sea_level[kper],self.sea_level[kper]])
                            self.rchData[kper] = chdKper

        # lpf package
        self.laywet = np.zeros(self.nlay)
        self.laytype = np.ones(self.nlay)

        self.hk = np.ones((self.nlay, self.nrow, self.ncol))*self.hyd_cond
        if self.cond_decay != 0.:
            depth = np.zeros(self.hk.shape)
            depth[1:,:,:] = self.dem - self.zbot[:-1,:,:]
            self.hk *= np.exp(-self.cond_decay*depth)
        '''
        for i in range(0,len(self.number_structure)):
            for j in range(0,nlay):
                self.hk[j][self.structure.geology==self.number_structure[i]]= logParamValue[i]*3600*24
		'''
        self.upw = flopy.modflow.ModflowUpw(self.mf, iphdry=1, hdry=-100, laytyp=self.laytype, laywet=self.laywet, hk=self.hk,
                                       vka=1, sy=self.porosity, noparcheck=False, extension='upw', unitnumber=31)

        self.rchData = {}
        for kper in range(0, self.nper):
            if isinstance(self.climatic,(int,float)):
                self.rchData[kper] = self.climatic
            else:
                if kper == 0:
                    self.rchData[kper] = np.nanmean(self.climatic)
                else:
                    self.rchData[kper] = self.climatic[kper]
        self.rch = flopy.modflow.ModflowRch(self. mf, rech=self.rchData)

        # Drain package (DRN)
        self.drnData = np.zeros((self.nrow*self.ncol, 5))
        compt = 0
        self.drnData[:, 0] = 0 # layer
        for i in range (0,self.nrow):
            for j in range (0, self.ncol):
                self.drnData[compt, 1] = i #row
                self.drnData[compt, 2] = j #col
                self.drnData[compt, 3]= self.dem[i, j]#elev
                self.drnData[compt, 4] =self.hk[0, i, j]* self.thick*self.resolution**2  #cond() 
                compt += 1
        lrcec= {0:self.drnData}
        self.drn = flopy.modflow.ModflowDrn(self.mf, stress_period_data=lrcec)

        # oc package
        stress_period_data = {}
        for kper in range(self.nper):
            kstp = self.nstp[kper]
            stress_period_data[(kper, kstp-1)] = ['save head','save budget',]
        self.oc = flopy.modflow.ModflowOc(self.mf, stress_period_data=stress_period_data, extension=['oc','hds','cbc'],
                                unitnumber=[14, 51, 52, 53, 0], compact=True)
        self.oc.reset_budgetunit(fname= self.model_name+'.cbc')

    def processing(self):
        print('Simulation d\'un modèle')
        # write input files
        self.mf.write_input()
        # run model
        succes, buff = self.mf.run_model(silent=False) # True without msg
        
    def post_processing(self):
        # post_processing
        print('Extraction des résultats d\'un modèle')
        
        self.dem_mask = (self.dem_clip==-99999)
        
        # Model parameters
        self.path_file = os.path.join(self.full_path, self.model_name)

        self.nper = self.dis.nper
        self.kper = np.arange(0,self.nper,1) # ==> time
        self.kstp = self.nstp[self.kper] - 1
        
        self.rechval = self.rch.rech[0][0,0]
        
        col = ['nrow','ncol','res','nlay','nper','rech','hk','sy']
        var = [self.nrow,self.ncol,self.resolution,self.nlay,self.nper,self.rechval,self.hyd_cond,self.porosity]
        params = pd.DataFrame(var).T
        params.columns = col
        params = params.round(3)
        self.params = params
        self.params.to_csv(self.full_path+'/_model_parameters.txt', sep=';', index=False)
        # np.savetxt(self.path_file+'_model_parameters.txt', self.params, delimiter=';')

        self.save_file = os.path.join(self.full_path, '_extraction')
        file_adds.create_folder(self.save_file)
        
        # Import essential data
        self.head_fpu = fpu.HeadFile(self.path_file+'.hds')        
        self.cbb = fpu.CellBudgetFile(self.path_file+'.cbc')
        
        # Import times
        self.times = self.head_fpu.get_times()
        self.kstpkper = self.head_fpu.get_kstpkper()
        if len(self.times) == 1:
            self.kstpkper = self.kstpkper[0]
                
        # Create dictionnaries
        self.dict_watertable_elevation = {}
        self.dict_watertable_depth = {}
        self.dict_seepage_areas = {}
        self.dict_outflow_drain = {}
        self.dict_gw_flux = {}
        self.dict_specific_discharge = {}
        
        for item, time in enumerate(self.times):
            print('Time : ', item)
                        
            if len(self.times) > 1:
                self.kstpkper = (self.kstp[item], self.kper[item])
            
            lead_numb = "%03d" % (item,)
            
            """
            watertable_outputs
            """
            # Import data
            self.head_all = self.head_fpu.get_alldata() # mflay=None
            self.head_data = self.head_fpu.get_data(totim=time)
            
            ### Watertable elevation
            # Top layer
            self.wt_elev = self.head_data[0]
            # Mask
            self.wt_elev[self.dem_mask] = -9999
            # Export
            # if item == 0:
            tif_adds.export_tif(self.dem_path, self.wt_elev, -9999,
                                self.save_file+'/watertable_elevation_('+lead_numb+').tif')
            # print('export watertable_elevation')
                
            ### Watertable depth
            self.wt_depth = self.dem - self.wt_elev
            # Mask
            self.wt_depth[self.dem_mask] = -9999
            # Export
            # if item == 0:
            tif_adds.export_tif(self.dem_path, self.wt_depth, -9999,
                                self.save_file+'/watertable_depth_t('+lead_numb+').tif')
            # print('export watertable_depth')
            
            ### Watertable intercept
            self.seep_area = self.dem - self.wt_elev
            # Mask
            self.seep_area[self.seep_area >= 0] = 0
            self.seep_area[self.seep_area < 0] = 1
            self.seep_area[self.dem_mask] = -9999
            # Export
            # if item == 0:
            tif_adds.export_tif(self.dem_path, self.seep_area, -9999,
                                self.save_file+'/seepage_areas_t('+lead_numb+').tif')
            # print('export seepage_areas')
        
            """
            outflow_drain
            """
            # Import data
            self.out_all = np.ones((1, self.dis.nrow, self.dis.ncol))
            self.drain = self.cbb.get_data(text='DRAINS', kstpkper=self.kstpkper, totim=time)
            # self.drain = self.cbb.get_data(text='DRAINS', kstpkper=self.kstpkper)
            # Loop storage
            sim = 0
            count = 0
            for i in range(0, self.dis.nrow):
                for j in range(0, self.dis.ncol):
                    self.out_all[sim, i, j] = np.abs(self.drain[0][count][1])
                    count = count + 1
            # Top layer
            self.out_drn = self.out_all[0]
            # Mask
            self.out_drn[self.dem_mask] = -9999
            # Export
            # if item == 0:
            tif_adds.export_tif(self.dem_path, self.out_drn, -9999,
                                self.save_file+'/outflow_drain_t('+lead_numb+').tif')
            # print('export outflow_drain')
        
            """
            gw_flux
            """
            ### Groundwater flux
            # Import data
            self.cbb_data = self.cbb.get_data(kstpkper=(0, 0))
            self.frf = self.cbb.get_data(text='FLOW RIGHT FACE', kstpkper=self.kstpkper, totim=time)[0]
            self.fff = self.cbb.get_data(text='FLOW FRONT FACE', kstpkper=self.kstpkper, totim=time)[0]
            # Depend nlayers
            if self.nlay == 1:
                self.flux = np.sqrt(self.frf**2 + self.fff**2)        
            if self.nlay > 1:
                self.flf = self.cbb.get_data(text='FLOW LOWER FACE', kstpkper=self.kstpkper, totim=time)[0] # > 1 lay
                self.flux = np.sqrt(self.frf**2 + self.fff**2, self.flf**2)
                
            # Top layer
            self.flux_top = self.flux[0]
            # Mask
            self.flux_top[self.dem_mask] = -9999
            # Export
            # if item == 0:
            tif_adds.export_tif(self.dem_path, self.flux_top, -9999,
                                self.save_file+'/gw_flux_t('+lead_numb+').tif')
            # print('export gw_flux')
            
            ### Specific discharge
            # # Import data
            # if self.nlay == 1:
            #     self.qx, self.qy, self.qz = pp.get_specific_discharge((self.frf, self.fff, None), 
            #                                                            self.mf, self.path_file+'.cbc')
            # if self.nlay > 1:
            #     self.qx, self.qy, self.qz = pp.get_specific_discharge((self.frf, self.fff, self.flf),                                                                    
            #                                                            self.mf, self.path_file+'.cbc')            
            # self.specif_disch = np.sqrt(self.qx**2 + self.qy**2 + self.qz**2)
            # # Top layer
            # self.sepcif_disch_top = self.specif_disch[0]
            # # Mask
            # self.sepcif_disch_top[self.dem_mask] = -9999
            # # Export
            # if item == 0:
            #     tif_adds.export_tif(self.dem_path, self.specif_disch, -9999,
            #              self.save_file+'/specific_discharge_t('+lead_numb+').tif')
            #     print('export specific_discharge')
        
            """
            store_dict
            """
            self.dict_watertable_elevation[item] = self.wt_elev
            self.dict_watertable_depth[item] = self.wt_depth
            self.dict_seepage_areas[item] = self.seep_area
            self.dict_outflow_drain[item] = self.out_drn
            self.dict_gw_flux[item] = self.flux_top
            # self.dict_specific_discharge[item] = self.specif_disch
            
        """
        save_dict
        """
        np.save(self.save_file+'/watertable_elevation', self.dict_watertable_elevation)
        np.save(self.save_file+'/watertable_depth', self.dict_watertable_depth)
        np.save(self.save_file+'/seepage_areas', self.dict_seepage_areas)
        np.save(self.save_file+'/outflow_drain', self.dict_outflow_drain)
        np.save(self.save_file+'/gw_flux', self.dict_gw_flux)
        # np.save(self.save_file+'/specific_discharge.h5', self.dict_specific_discharge)

class Chronics:
    def __init__(self, geographic, 
                 first=1960, last=2020, time_step='monthly',
                 model_name='modflow_model', model_folder=os.path.join(os.path.dirname(os.getcwd()), 'output')):
                 
        
        self.dem_clip = geographic.dem_clip
        self.resolution = geographic.resolution
        
        self.first = first
        self.last = last
        self.time_step = time_step
        
        self.model_name = model_name
        self.model_folder = model_folder
        self.full_path = os.path.join(model_folder, model_name)
        self.save_file = os.path.join(self.full_path, '_extraction')
        
        self.generate_chronic()
        
    def generate_chronic(self):
        
        df = pd.DataFrame()
        
        def mask_by_dem(target_data, mask_data, value_masked):
            masked = np.ma.masked_array(target_data, mask=mask_data==value_masked)
            return masked

        if self.time_step=='monthly':
            freq = 'M'
            df['date'] = pd.date_range(str(self.first),str(self.last+1),freq=freq)
            
        if self.time_step=='daily':
            freq = 'D'
            df['date'] = pd.date_range(str(self.first),str(self.last+1),freq=freq)
        
        loaded = np.load(os.path.join(self.save_file, 'watertable_elevation'+'.npy'), allow_pickle=True).item()
        for key in loaded:
            masked = mask_by_dem(loaded[key], self.dem_clip, -99999)
            calc = np.nanmean(masked)
            df.loc[key,'watertable_elevation'] = calc

        loaded = np.load(os.path.join(self.save_file, 'watertable_depth'+'.npy'), allow_pickle=True).item()
        for key in loaded:
            masked = mask_by_dem(loaded[key], self.dem_clip, -99999)
            calc = np.nanmean(masked)
            df.loc[key,'watertable_depth'] = calc

        loaded = np.load(os.path.join(self.save_file, 'seepage_areas'+'.npy'), allow_pickle=True).item() 
        for key in loaded:
            masked = mask_by_dem(loaded[key], self.dem_clip, -99999)
            cell = masked.count()
            count = (masked > 0).sum()
            calc = (count/cell) * 100
            df.loc[key,'seepage_areas'] = calc
            
        loaded = np.load(os.path.join(self.save_file, 'outflow_drain'+'.npy'), allow_pickle=True).item()
        for key in loaded:
            masked = mask_by_dem(loaded[key], self.dem_clip, -99999)
            cell = masked.count()
            calc = (np.nansum(masked) / (cell * self.resolution**2)) # mm/m
            df.loc[key,'outflow_drain'] = calc

        loaded = np.load(os.path.join(self.save_file, 'gw_flux'+'.npy'), allow_pickle=True).item()
        for key in loaded:
            masked = mask_by_dem(loaded[key], self.dem_clip, -99999)
            calc = np.nanmean(masked)
            df.loc[key,'gw_flux'] = calc
        
        df['date'] = pd.to_datetime(df['date'], format='%Y-%m-%d')
        df = df.set_index(['date'])
        df = df.round(2)
        df.to_csv(self.save_file + '/_simulated_chronics.csv', sep=';')
        
        
