# coding:utf-8

import pandas as pd
import numpy as np
import os

class Forcing:
    """
    class Forcing inputs the climate data forced to the model,
        - recharge (processed by the groundwater model) (m/day)
        - runoff (added to the outputs of the groundwater model) (m/day)
    
    Forcing are either
        - loaded from data files issued by SURFEX
        - generated (inside this calss) synthetic scenarios (eg sinosoids)
        

    Attributes, public
    -------------------
    data_folder: string
        Reanalysis and Dayon forcing reanalysis and projection
        Reanalysis of Surfex has not changed from 2015 
        
    drias_folder: string
        2021 Drias projection (folder)
    
    freq: string
        Frequency of the forcing chronicles (D:day, M:month, Y:year)
        
    recharge: pandas matrix or float (constant recharge)
        recharge to the aquifer (date,value)
        
    runoff: pandas matrix or float (constant recharge)
        runoff simulated by surfex, remains on the surface (date,value)
    
    unit: string
        unit for the recharge and runoff (m/day) #OBSOLETE or NOT DEVELOPED?
        
    """
    
    def __init__(self, out_path):
        """
        Constructor
            Defines directories where data are stored
            Two types of data can be loaded 
                1- Folder "climatic" contains the SURFEX reanalysis and projection (Gildas Dayon) provided by F. Habets (2019)
                2- Folder "drias" contains the projection EXPLORE 2 obtained from drias (2021)
            Reanalysis: 1950-2019
            Projection: 1960-2100
            
        Parameters
        ----------
        out_path : string
            root path in which are stored the data 

        """
        self.data_folder = os.path.join(out_path, 'results_stable/climatic/')
        self.drias_folder = os.path.join(out_path, 'results_stable/drias/')
        self.freq = None
        self.recharge = None
        self.runoff = None
        self.unit = None
    
    
    def update_recharge(self, values, sim_state):
        """
        Main function to load the recharge

        Parameters
        ----------
        values : fload or panda matrix
            values assigned to the recharge 
            Loading or generation of the recharge values is made elsewhere

        sim_state : string
            value = "steady"
            value = "transient"
            
        """
        self.recharge = values # recharge
        if sim_state == 'steady':
            self.recharge = np.mean(self.recharge)
            if isinstance(self.recharge,(int,float))==False:
                self.recharge = self.recharge[0]
            
            
    def update_runoff(self, values, sim_state):
        """
        Main function to load the runoff

        Parameters
        ----------
        values : fload or panda matrix
            values assigned to the runoff
            Loading or generation of the runoff values is made elsewhere

        sim_state : string
            value = "steady"
            value = "transient"
            
        """
        self.runoff = values # recharge
        if sim_state == 'steady':
            self.runoff = np.mean(self.runoff)
            if isinstance(self.runoff,(int,float))==False:
                self.runoff = self.runoff[0]
    
    
    def update_synthetic_recharge(self, rech, shape, years, start_date= "2020-08", freq = None, dis='normal'):
        """
        Generate synthetic recharge (inverse Gaussian, normal, uniform)

        Parameters
        ----------
            rech : float
                Mean recharge distribution (or first parameter of the distribution)
            
            shape: float
                Std of the recharge distribution (or second parameter of the distribution)
            
            dis: string
                inverse-gaussian 
                normal
                uniform
                
            start_date: string
                year-month
                
            years: float
                durateion in years over wich recharge should be generated
            
            freq: string
                freqency of the rechrage
                D: dayly
                M: monthly
                Y: yearly
        """
        self.freq = freq
        days = years*365
        date = pd.date_range(start_date, periods=days)
        t = np.linspace(1,365,365)
        time = []
        for y in range(0,years):
            time = np.concatenate((time,t))
        mean = 180
        if dis == 'inverse-gaussian':
            pdf = (((mean*shape)/(2*np.pi*time**3))**0.5*np.exp(-(shape*(time-mean)**2)/(2*mean*time)))*rech
        if dis == 'normal':
            pdf = ((1/(shape*np.sqrt(2*np.pi)))*np.exp(-((time-mean)**2/(2*shape**2))))*rech
        if dis == 'uniform':
            pdf = np.zeros(len(time)) 
            pdf[(time >= (mean-(shape/2))) & (time < ((shape/2)+mean))] = rech/shape
        self.recharge = pd.Series(data = pdf, index=date)
        if freq != None:
            self.recharge = self.recharge.resample(self.freq).mean()
        
        
    def update_sinusoid_recharge(self, serie, period, amplitude, offset, omega, phase):
        """
        SYnthetic Sinusiodal recharge 

        Parameters
        ----------
        serie : panda matrix
            input recharge
            
        period : string
            D (day) or M (month)
        
        amplitude : float
            modifies the amplitude (max-min) of the sinusoid
            
        offset : float
            modifies the mean of the sinusoid
            
        omega : float
            modifies the sinusoid frequency
            
        phase : float
            modifies the phase of the sinusoid

        """
        from scipy.optimize import curve_fit
        def sinusoid(x, A , offset, omega, phase):
            return A*np.sin(omega*x+phase) + offset
        def get_p0(Y, T):
            A0 = (max(Y[0:T]) - min(Y[0:T]))/2
            offset0 = Y[0]
            phase0 = 0
            omega0 = 2.*np.pi/T
            return [A0, offset0, omega0, phase0]
        if period=='D':
            T=365
        if period=='M':
            T=12
        date = serie.index
        serie = serie.reset_index(drop=True)
        X = serie.index
        Y = serie.values
        param, covariance = curve_fit(sinusoid, X, Y, p0=get_p0(Y, T))
        param[0] = param[0] * amplitude # Amplitude : max
        param[1] = param[1] * offset # Offset : shift v
        param[2] = param[2] * omega # Omega : cycles
        param[3] = param[3] * phase # Phase : shift h
        sinus = sinusoid(X, *param)
        self.recharge = pd.Series(data = sinus, index=date)
        self.recharge[self.recharge < 0] = 0
    
    
    def update_recharge_surfex(self, clim_mod, clim_sce, first_year, last_year, time_step, sim_state=None):
        """
        Loads surfex data already processed externally 
            unit of the loaded data: mm/day
        Data have been processed by the file "climatic.py", same as SURFEX_PY (with figures) #RISK OF OUTDATING of SURFEX_PY

        Parameters
        ----------
        clim_mod : string
            Name of the climatic model (eg acc, rea, ipsl, cnrm)
            
        clim_sce : string
            Type of scenario (historic, RCP2.6, RCP4.5, RCP6.0, RCP8.5)
        
        first_year : int
            First year of the chronicle that should be loaded (clipping if necessary)
        
        last_year : int
            Last year of the chronicle that should be loaded (clipping if necessary)
        
        time_step : string
            D: day (recommended)
            M: Month
            Y: year 
        
        sim_state : string
            steady
            transient

        """
        self.freq = time_step
        climatic = pd.read_csv(self.data_folder+'_'+'REC'+'_'+time_step+'.csv', sep=';', index_col=0, parse_dates=True)
        climatic = climatic[clim_mod+'_'+clim_sce]
        climatic = climatic[(climatic.index.year >= first_year) & (climatic.index.year <= last_year)]
        self.recharge = climatic/1000 # recharge in meters
        self.recharge.index = self.recharge.asfreq(self.freq).index
        # self.recharge.index = self.recharge.index.to_period(self.freq)
        if sim_state == 'steady':
            self.recharge = self.recharge.mean()

    def update_runoff_surfex(self, clim_mod, clim_sce, first_year, last_year, time_step, sim_state=None):
        """
        Loads surfex data already processed externally 
            unit of the loaded data: mm/day
        Data have been processed by the file "climatic.py", same as SURFEX_PY (with figures) #RISK OF OUTDATING of SURFEX_PY

        Parameters
        ----------
        clim_mod : string
            Name of the climatic model (eg acc, rea, ipsl, cnrm)
            
        clim_sce : string
            Type of scenario (historic, RCP2.6, RCP4.5, RCP6.0, RCP8.5)
        
        first_year : int
            First year of the chronicle that should be loaded (clipping if necessary)
        
        last_year : int
            Last year of the chronicle that should be loaded (clipping if necessary)
        
        time_step : string
            D: day (recommended)
            M: Month
            Y: year 
        
        sim_state : string
            steady
            transient

        """
        self.freq = time_step
        climatic = pd.read_csv(self.data_folder+'_'+'RUN'+'_'+time_step+'.csv', sep=';', index_col=0, parse_dates=True)
        climatic = climatic[clim_mod+'_'+clim_sce]
        climatic = climatic[(climatic.index.year >= first_year) & (climatic.index.year <= last_year)]
        self.runoff = climatic/1000 # recharge in meters
        self.runoff.index = self.runoff.asfreq(self.freq).index
        # self.runoff.index = self.runoff.index.to_period(self.freq)
        if sim_state == 'steady':
            self.runoff = self.runoff.mean()
        
    def update_effppt_surfex(self, clim_mod, clim_sce, first_year, last_year, time_step, sim_state=None):
        """
        Same as update_recharge_surfex but forces groundwater model with Precipitation - Evapotranspiration

        Parameters
        ----------
        clim_mod : string
            Name of the climatic model (eg acc, rea, ipsl, cnrm)
            
        clim_sce : string
            Type of scenario (historic, RCP2.6, RCP4.5, RCP6.0, RCP8.5)
        
        first_year : int
            First year of the chronicle that should be loaded (clipping if necessary)
        
        last_year : int
            Last year of the chronicle that should be loaded (clipping if necessary)
        
        time_step : string
            D: day (recommended)
            M: Month
            Y: year 
        
        sim_state : string
            steady
            transient

        """
        self.freq = time_step
        ppt = pd.read_csv(self.data_folder+'_'+'PPT'+'_'+time_step+'.csv', sep=';', index_col=0, parse_dates=True)
        ppt = ppt[clim_mod+'_'+clim_sce]
        ppt = ppt[(ppt.index.year >= first_year) & (ppt.index.year <= last_year)]
        aet = pd.read_csv(self.data_folder+'_'+'ETP'+'_'+time_step+'.csv', sep=';', index_col=0, parse_dates=True)
        aet = aet[clim_mod+'_'+clim_sce]
        aet = aet[(aet.index.year >= first_year) & (aet.index.year <= last_year)]
        effppt = ppt - aet
        self.recharge = effppt/1000 # recharge in meters
        self.recharge.index = self.recharge.asfreq(self.freq).index
        self.effppt = self.recharge.copy()
        self.pe_pos = self.effppt.clip(lower=0)
        self.pe_neg = self.effppt.clip(upper=0)
        # self.recharge.index = self.recharge.index.to_period(self.freq)
        if sim_state == 'steady':
            self.recharge = self.recharge.mean()
            self.effppt = self.effppt.mean()
            self.pe_pos = self.pe_pos.clip(lower=0)
            self.pe_neg = self.pe_neg.clip(upper=0)
    
    
    def update_recharge_drias(self, gcm_mod, rcm_mod, sce_mod, first_year, last_year, sim_state=None):
        """
        Loads recharge from DRIAS files

        Parameters
        ----------
        gcm_mod : string
            Name of the climatic model (eg acc, rea, ipsl, cnrm)
            
        rcm_mod : string
            regional type of model (wrf, aladin, rca)
            
        sce_mod: string
            Type of scenario (historic, RCP2.6, RCP4.5, RCP6.0, RCP8.5)
        
        first_year : int
            First year of the chronicle that should be loaded (clipping if necessary)
        
        last_year : int
            Last year of the chronicle that should be loaded (clipping if necessary)
        
        time_step : string
            D: day (recommended)
            M: Month
            Y: year 
        
        sim_state : string
            steady
            transient

        """
        data = pd.read_csv(self.drias_folder+'_ALL_D.csv', sep=';', index_col=0, parse_dates=True)
        data = data[(data.index.year >= first_year) & (data.index.year <= last_year)]
        self.recharge = data['REC'+'_'+gcm_mod+'-'+rcm_mod+'_'+sce_mod] / 1000 # mm to m
        if sim_state == 'steady':
            self.recharge = self.recharge.mean()


    def update_runoff_drias(self, gcm_mod, rcm_mod, sce_mod, first_year, last_year, sim_state=None):
        """
        Loads runoff from DRIAS files

        Parameters
        ----------
        gcm_mod : string
            Name of the climatic model (eg acc, rea, ipsl, cnrm)
            
        rcm_mod : string
            regional type of model (wrf, aladin, rca)
            
        sce_mod: string
            Type of scenario (historic, RCP2.6, RCP4.5, RCP6.0, RCP8.5)
        
        first_year : int
            First year of the chronicle that should be loaded (clipping if necessary)
        
        last_year : int
            Last year of the chronicle that should be loaded (clipping if necessary)
        
        time_step : string
            D: day (recommended)
            M: Month
            Y: year 
        
        sim_state : string
            steady
            transient

        """
        data = pd.read_csv(self.drias_folder+'_ALL_D.csv', sep=';', index_col=0, parse_dates=True)
        data = data[(data.index.year >= first_year) & (data.index.year <= last_year)]
        self.runoff = data['RUN'+'_'+gcm_mod+'-'+rcm_mod+'_'+sce_mod] / 1000 # mm to m
        if sim_state == 'steady':
            self.runoff = self.runoff.mean()
            