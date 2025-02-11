# -*- coding: utf-8 -*-
"""
Created on Thu May 25 14:03:30 2023

@author: Nicolas Cornette

Loads flow data using API from HUB'EAU (gestion des APIs de HydroPartail, de la piézométrie, de la qualité...)
It is necessarily loaded from internet (no internal save to avoid any outdate)
"""
#%%
import requests
import pickle
from io import StringIO
import pandas as pd
import datetime
from datetime import date
import json


class Hydrometry():
    
    """
    Hydrometry class, used to process streamflow timeseries data.
    
    Parameters:
    ----------
    bh_id : str
        national hydrological station identifier (BanqueHydro).
    
    Attributes:
    ----------
    id : str
        national hydrological station identifier (BanqueHydro).
    station_sheet : dict
        All informations on the stations (BanqueHydro).
    name : str
        national hydrological station name (BanqueHydro).
    area : float
        watershed area (km²).
    outlet : list
        outlet coordinates.
    discharge : DataFrame
        Discharge dataframe (nt, nq).
        Frequency : daily
        Discharge : m3/s
    
    Methods (public):
    ----------
    get_data(bh_id)
        Extract hydrological station sheet, discharge timeseries and save object.
        
    Methods (private):
    ----------
    __load_station_sheet(bh_id)
        Extract hydrological station sheet with api requests.
    __api_hubeau()
        Extract streamflow timeseries with api requests.
    """
    
    def __init__(self, bh_id: str, update: bool = False):
        
        # Download discharge using Hub'Eau platform
        self.get_data(bh_id)
        
        
    def get_data(self, bh_id):
        """
        Extract hydrological station sheet, discharge timeseries and save object.

        Parameters
        ----------
        bh_id : str
            national hydrological station identifier (BanqueHydro).

        Returns
        -------
        station_sheet : dict
            national hydrological station identifier (BanqueHydro).
        name : str
            national hydrological station name (BanqueHydro).
        area : float
            watershed area (km²).
        outlet : list
            outlet coordinates.
        discharge : DataFrame
            Discharge dataframe (nt, nq).
            Frequency : daily
            Discharge : m3/s
        """
        
        # Download hydrological station sheet
        self.station_sheet = self.__load_station_sheet(bh_id)
        self.name = self.station_sheet['libelle_site']
        self.area = self.station_sheet['surface_bv']
        self.outlet = [self.station_sheet['coordonnee_x_site'], self.station_sheet['coordonnee_y_site']]
        
        # Extract data from hubeau
        self.discharge = self.api_hubeau(bh_id)
        self.specific_discharge = self.discharge / (self.area * 1e+6)
    
    
    def __load_station_sheet(self, bh_id):
        """
        Extract hydrological station sheet with api requests.

        Parameters
        ----------
        bh_id : str
            national hydrological station identifier (BanqueHydro).

        Returns
        -------
        wb : Dict
            Dictionnary with hydrological station sheet.

        """
        works = None
        fails = 0
        
        # api url : .json (from hub'eau)
        while works == None and fails < 10:
            try:
                api_root = "https://hubeau.eaufrance.fr/api//v1/hydrometrie/referentiel/sites"
                url_api = '{a}?code_site={code}'.format(a=api_root, code=bh_id)
                req = requests.get(url_api)
                wb = req.json()
                wb = wb['data']
                wb = wb[0]
                works =+ 1
            except:
                fails =+ 1
        
        return wb    
    
    
    def api_hubeau(self, bh_id):
        """
        Extract streamflow timeseries with api requests.

        Parameters
        ----------
        bh_id : str
            national hydrological station identifier (BanqueHydro).

        Returns
        -------
        serie : DataFrame
            Discharge timeseries dataframe.

        """
        
        works = None
        fails = 0
        
        while works == None and fails < 3:
            try:
                # Define variable to download
                variable='QmJ'
                
                # get the current date
                end_date = pd.to_datetime(date.today()) 
                
                # api url : .json (from hub'eau)
                api_root_json = "https://hubeau.eaufrance.fr/api/v1/hydrometrie/obs_elab"
                
                # Count number of observations (daily discharge values)
                number_url = '{a}?code_entite={code}&grandeur_hydro_elab={var}&date_fin_obs_elab={d}&size=1'.format(a=api_root_json, code=bh_id, var=variable, d=end_date)
                number = json.loads(requests.get(number_url).text)['count']
                print(number)        
                
                # api url : .csv (from hub'eau)
                api_root_csv = "https://hubeau.eaufrance.fr/api/v1/hydrometrie/obs_elab.csv"
                
                # number of maximal observations = 20 000
                if number < 20000:
                    url_api = '{a}?code_entite={code}&grandeur_hydro_elab={var}&date_fin_obs_elab={d}&size={nb}'.format(a=api_root_csv, code=bh_id, var=variable, d=end_date, nb=number+1)
                else:
                    start_date = end_date - datetime.timedelta(days=20000)
                    url_api = '{a}?code_entite={code}&grandeur_hydro_elab={var}&date_debut_obs_elab={ds}&date_fin_obs_elab={de}&size={nb}'.format(a=api_root_csv, code=bh_id, var=variable, ds=start_date, de=end_date, nb=20000)
        
                # convert to dataframe
                data = pd.read_csv(StringIO(requests.get(url_api).text), sep=';',
                                   parse_dates=['date_obs_elab'])
                
                serie = data[['date_obs_elab', 'resultat_obs_elab']]
                serie.loc[:,'resultat_obs_elab'] = serie['resultat_obs_elab'] / 1000 # l/s to m3/s
                serie = serie.set_axis(['t', 'Q'], axis=1)
                serie.sort_values(by=['t'],inplace=True)
                serie = serie.set_index("t")
                works =+ 1
                fails += 1
            except:
                fails += 1
        
        return serie
#%%
if __name__ == "__main__":
    # Example of usage
    # bh_id = "K0014010"
    bh_id = "J7364220"
    hydrometry = Hydrometry(bh_id)
    series = hydrometry.api_hubeau(bh_id)

# %%
