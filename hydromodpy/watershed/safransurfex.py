# coding:utf-8
"""

"""

#%% LIBRAIRIES

import geopandas as gpd
import pandas as pd
import os 
import sys
from hydromodpy.tools import get_logger
from os.path import dirname, abspath
df = dirname(dirname(abspath(__file__)))
sys.path.append(df)

logger = get_logger(__name__)

# from data import climatic_display

#%% CLASS 1

class SafranSurfex:
    """
    Class to clip and extract climate data from specific .h5 (NetCDF) file at France scale.
    """
    
    def __init__(self, out_path: str, safransurfex_path: str, watershed_shp: str):
        """
        Functions to clip .h5 SURFEX files at the model domain scale
            - Historical data from Quentin COURTOIS thesis ['OLD'] (reanalysis SAFRAN / SURFEX)
            - Historical reanalysis SAFRAN / SURFEX ['REA'] (1958 to 2019) and updated REAUP (2019 to 2023)
            
        Parameters
        ----------
        out_path : str
            Path of the HydroModPy outputs.
        surfex_path : str
            Path of the folder with the climate (safran/surfex) data.
        watershed_shp : str
            Path of the shapefile polygon of the model domain (watershed).
        """
        
        data_folder = os.path.join(out_path, 'results_stable/climatic/')
        if not os.path.exists(data_folder):
                os.makedirs(data_folder)
        self.figure_folder = os.path.join(out_path, 'results_stable/_figures/climatic/')

        if not os.path.exists(self.figure_folder):
                os.makedirs(self.figure_folder)
        logger.info('Extracting SAFRAN-SURFEX climatic data for watershed')
        self.extract_cells_from_shapefile(safransurfex_path, watershed_shp)
        self.extract_values_from_h5file(data_folder, safransurfex_path)
        
    #%% CLIP DATA    
    
    def extract_cells_from_shapefile(self, safransurfex_path, watershed_shp):
        """
        Extract cells in watershed from France scale grid of 8x8km.
        """
        mesh_path = safransurfex_path + '/mesh/maille_meteo_fr_pr93.shp'
        mask = gpd.read_file(watershed_shp , encoding="utf-8")
        mesh = gpd.read_file(mesh_path, encoding="utf-8") 
        intersect = gpd.clip(mesh, mask)
        self.cells_list = intersect.num_id.to_list() # wanted Surfex cells list

    def extract_values_from_h5file(self, data_folder, safransurfex_path):
        """
        Create a .h5 (netCDF) of climate data at the watershed scale for each database.

        Parameters
        ----------
        data_folder : str
            Path of stable results for safran/surfex data.
        """
        variables = ['REC', 'RUN', 'ETP', 'PPT', 'TAS', 'SNOW']
        # scenarios = ['historic','RCP2.6','RCP4.5','RCP6.0','RCP8.5']
        scenarios = ['historic']
        # simulations = ['REA','REAUP','OLD','ACC1','BCC1','BNU1','CAN1','CAN2','CAN3','CAN4','CAN5',
        #                 'CNR1','CSI1','IPS1','MIR1','MIR2','MIR3','NOR1']
        simulations = ['REA','REAUP','OLD']
        self.values = {}
        for sim in simulations:
            try:
                os.remove(data_folder+sim+'.h5')
            except:
                pass
            self.values[sim] = {}
            h5file = (data_folder+sim+'.h5')
            for var in variables:
                self.values[sim][var] = {}
                for sce in scenarios:
                    try:
                        values = pd.read_hdf(safransurfex_path+'/'+sim+'.h5',var+'/'+sce)
                        logger.debug('Loaded %s-%s climate dataset', sim, var)
                        if (sim == 'REA') | (sim == 'OLD') | (sim == 'REAUP'):
                            values.index.freq = values.index.inferred_freq
                        # values = values.loc[:,self.cells_list]
                        values = values[values.columns.intersection(self.cells_list)]
                        values['MEAN'] = values.mean(numeric_only=True, axis=1)
                        values.to_hdf(h5file, var+'/'+sce)
                        self.values[sim][var][sce] = values
                    except Exception as e:
                        logger.debug('No data for %s-%s: %s', sim, var, e)
                        pass

#%% CLASS 2

class Merge:
    """
    Generated timeseries in .csv format from .h5 (netCDF) generated at the watershed scale.
    """    

    def __init__(self, out_path: str):
        """
        Parameters
        ----------
        out_path : str
            Path of the HydroModPy outputs.
        """
        self.variables = ['REC','RUN', 'ETP', 'PPT', 'TAS', 'SNOW']
        # self.scenarios = ['historic','RCP2.6','RCP4.5','RCP6.0','RCP8.5']
        self.scenarios = ['historic']
        # self.simulations = ['REA','ACC1','BCC1','BNU1','CAN1','CNR1','CSI1','IPS1','MIR1','NOR1','OLD','REAUP']
        # self.simulations = ['REA','ACC1','BCC1','BNU1','CAN1','CAN2','CAN3','CAN4','CAN5',
        #                     'CNR1','CSI1','IPS1','MIR1','MIR2','MIR3','NOR1','OLD','REAUP']
        self.simulations = ['REA','OLD','REAUP']

        self.data_folder = os.path.join(out_path, 'results_stable/climatic/')
                
        columns = []
        for sim in self.simulations:
            for sce in self.scenarios:
                if (sim == 'REA') & (sce == 'historic'):
                    columns.append(sim+'_'+sce)
                if (sim == 'OLD') & (sce == 'historic'):
                    columns.append(sim+'_'+sce)
                if (sim == 'REAUP') & (sce == 'historic'):
                    columns.append(sim+'_'+sce)
                if (sim != 'REA') & (sim != 'OLD') & (sim != 'REAUP'):
                    columns.append(sim+'_'+sce)
                        
        date = pd.date_range(start='01/01/1960', end='31/12/2099', freq='D')
        self.base = pd.DataFrame(index=date, columns=columns)
        
        self.df_climate_bv()
    
    #%% MERGE ALL DATA IN CSV
    
    def df_climate_bv(self):
        """
        Concatenate all climate data in one .csv file (mean values at the watershed scale).
        """
        for var in self.variables:
            df = self.base.copy()
            for sim in self.simulations:
                for sce in self.scenarios:
                    try:
                        hdf = pd.read_hdf(self.data_folder+sim+'.h5',var+'/'+sce) # mm/day or °C
                        df[sim+'_'+sce] = hdf.MEAN               
                    except:
                        continue
            
            # if (self.time_step == 'ME'):
            dfm = df.copy()
            dfm = dfm[~dfm.index.duplicated()]
            logger.debug('Monthly resampling for variable %s - shape: %s', var, dfm.shape)
            mask = dfm.resample("ME").count() >= 27
            if (var == 'TAS'):
                dfm = dfm.resample("ME").mean()[mask]
            else:
                # df = df.resample('ME').sum(min_count=27) # mm/month
                dfm = dfm.resample("ME").mean()[mask]
                    
            # if (self.time_step == 'Y'):
            dfy = df.copy()
            mask = dfy.resample("Y").count() >= 364
            if (var == 'TAS'):
                dfy = dfy.resample("Y").mean()[mask]
            else:
                # df = df.resample('Y').sum(min_count=364) # mm/year
                dfy = dfy.resample("Y").mean()[mask]
            
            df.to_csv(self.data_folder+'_'+var+'_'+'D'+'.csv', sep=';')
            dfm.to_csv(self.data_folder+'_'+var+'_'+'M'+'.csv', sep=';')
            dfy.to_csv(self.data_folder+'_'+var+'_'+'Y'+'.csv', sep=';')
            
        # Mix all data in a dataframe
        ppt = pd.read_csv(self.data_folder+'_'+'PPT'+'_'+'D'+'.csv', sep=";", index_col=0, parse_dates=True)
        etp = pd.read_csv(self.data_folder+'_'+'ETP'+'_'+'D'+'.csv', sep=";", index_col=0, parse_dates=True)
        eff = ppt - etp
        eff = eff.add_prefix('EFF'+'_')
        raws = ['REC', 'RUN', 'ETP', 'PPT', 'TAS', 'SNOW']
        liste = []
        for raw in raws :
            dfd = pd.read_csv(self.data_folder+'_'+raw+'_'+'D'+'.csv', sep=";", index_col=0, parse_dates=True)
            dfd = dfd.add_prefix(raw+'_')
            liste.append(dfd)
        dfd = pd.concat(liste, join='inner', axis=1)
        dfd = pd.concat([dfd, eff], join='inner', axis=1)
        dfd = dfd.apply(pd.to_numeric)
        dfd.to_csv(self.data_folder+'_ALL_D.csv', sep=';')

#%% NOTES
