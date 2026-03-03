# -*- coding: utf-8 -*-
#%% LIBRAIRIES
import requests
import pandas as pd
import xarray as xr
import matplotlib.pyplot as plt
from pathlib import Path
from typing import Optional
from hydromodpy.watershed import initializing

# Variable mapping: SIM2 variable names -> user-friendly names
VAR_MAPPING = {
    'DLI_Q': 'solarradiation',
    'DRAINC_Q': 'recharge',
    'ETP_Q': 'potentialevapotranspiration',
    'FF_Q': 'wind',
    'HU_Q': 'relative_moisture',
    'PRELIQ_Q': 'liquidprecipitation',
    'PRENEI_Q': 'solidprecipitation',
    'SSI_Q': 'visibleradiation',
    'SWI_Q': 'soilmoistureindex',
    'TINF_H_Q': 'min_temperature',
    'TSUP_H_Q': 'max_temperature',
    'T_Q': 'temperature'
}

# Reverse mapping: user-friendly names -> SIM2 variable names
REVERSE_VAR_MAPPING = {v: k for k, v in VAR_MAPPING.items()}

#% CLASS
class Sim2_API:
    """
    Class to interact with the SIM2 API from GEOSAS for retrieving climatic data
    
    data available:
    DLI_Q : Rayonnement atmosphérique (cumul quotidien)
    DRAINC_Q : Drainage (cumul quotidien 06-06 UTC)
    ETP_Q : Evapotranspiration potentielle (formule de Penman-Monteith)
    FF_Q : Vent (moyenne quotidienne)
    HU_Q : Humidité relative (moyenne quotidienne)
    PRELIQ_Q : Précipitations liquides (cumul quotidien 06-06 UTC)
    PRENEI_Q : Précipitations solide (cumul quotidien 06-06 UTC)
    SSI_Q : Rayonnement visible (cumul quotidien)
    SWI_Q : Indice d'humidité des sols (moyenne quotidienne 06-06 UTC)
    TINF_H_Q : Température minimale des 24 températures horaires
    TSUP_H_Q : Température maximale des 24 températures horaires
    T_Q : Température (moyenne quotidienne).
    
    """

    def __init__(self, box, crs, var_list, formatting, date, coords: Optional[str] = None):
        
        print('Initializing SIM2 API client')
        self.coords = coords
        self.box = box
        self.crs = crs
        self.var_list_user = var_list  # Store user-friendly names
        self.var_list = self._convert_var_names(var_list)  # Convert to SIM2 names for API
        self.formatting = formatting
        self.date = date
        self.stable_folder   = initializing.stable_folder
        self.metadata, self.data = self._download_from_box()
        self._save_data_by_variable()

#%% GET DATA FROM XY LOCATION AND TIME PERIOD
    def _download_from_box(self):
        
        #METADATA REQUEST
        url_service = "https://api.geosas.fr/edr/collections/safran-isba/"
        
        r = requests.get(url_service)
        if r.ok:
            print("requete ok")
            self.metadata = r.json()
        else:
            print("erreur code :", r.status_code)
            self.metadata = None
        
        #DATA DOWNLOAD
        url = "https://api.geosas.fr/edr/collections/safran-isba/cube"
        
        params = {
            "bbox": self.box,
            "crs": self.crs,
            "parameter-name": self.var_list,
            "f": self.formatting,
            "datetime": self.date
        }

        r = requests.get(url, params=params)
        if r.ok:
            print("requête ok")
            print(r.request.url)  
            self.data = xr.open_dataset(r.content)
            
        else:
            print("erreur code :", r.status_code)
            self.data = None
        
        return self.metadata, self.data

    def _convert_var_names(self, var_list):
        """
        Convert user-friendly variable names to SIM2 variable names.
        Examples: 'solarradiation' -> 'DLI_Q', 'wind' -> 'FF_Q'
        
        Parameters
        ----------
        var_list : str
            Comma-separated list of user-friendly variable names
            
        Returns
        -------
        str
            Comma-separated list of SIM2 variable names
        """
        sim2_vars = []
        for var in var_list.split(','):
            var = var.strip()
            if var in REVERSE_VAR_MAPPING:
                mapped = REVERSE_VAR_MAPPING[var]
                if isinstance(mapped, list):
                    sim2_vars.extend(mapped)
                else:
                    sim2_vars.append(mapped)
            else:
                # If not found in mapping, assume it's already a SIM2 name
                sim2_vars.append(var)
        
        return ','.join(sim2_vars)

    def _save_data_by_variable(self, sim_id='ID', frequency='D'):
        """
        Save each variable to a separate NetCDF file in the stable folder.
        Follows naming convention: variablename_SIM2_ID_startdate_enddate_frequency.nc
        
        Parameters
        ----------
        sim_id : str, optional
            Simulation ID (default: 'ID')
        frequency : str, optional
            Frequency of data (default: 'D')
        """
        if self.data is None:
            print("No data to save")
            return
        
        self.start_date, self.end_date = self.date.split('/')
        self.start_date = self.start_date.strip().replace('-', '')
        self.end_date = self.end_date.strip().replace('-', '')

        # Create data subfolder
        data_folder = Path(self.stable_folder)
        
        processed_vars = set()  # Track variables to avoid duplicates
        
        for var in self.var_list.split(','):
            var = var.strip()  # Remove any whitespace
            
            if var in self.data.data_vars and var not in processed_vars:
                # Get the mapped variable name
                var_name = VAR_MAPPING.get(var, var)
                
                # Create filename with specific nomenclature
                filename = f"{var_name}_SIM2_{sim_id}_{self.start_date}_{self.end_date}_{frequency}.nc"
                filepath = data_folder / filename
                
                self.data[[var]].to_netcdf(filepath)
                print(f"Saved {var} to {filepath}")
                
                processed_vars.add(var)
            elif var not in self.data.data_vars:
                print(f"Variable {var} not found in data")

    def plot_spatiotemporal_data(self):
        for var in self.var_list.split(','):
            var = var.strip()
            if var in self.data.data_vars:
                fig, ax = plt.subplots()
                self.data[var].mean("time").plot(ax=ax)
                user_name = VAR_MAPPING.get(var, var)
                ax.set_title(f"Moyenne des {user_name} quotidiennes", size=14)
        return fig 
    
    def plot_distribution_data(self):
        for var in self.var_list.split(','):
            var = var.strip()
            if var in self.data.data_vars:
                fig, ax = plt.subplots()
                self.data[var].plot.hist(ax=ax)
                user_name = VAR_MAPPING.get(var, var)
                ax.set_title(f"Histogramme des {user_name} quotidiennes", size=14)
        return fig    
    
    def download_from_xy(self):
        "Not called yet by HydroModPy, but can be used to retrieve data for a specific point and time period"
        
        #METADATA REQUEST
        url_service = "https://api.geosas.fr/edr/collections/safran-isba/"
        
        r = requests.get(url_service)
        if r.ok:
            print("requete ok")
            self.metadata = r.json()
        else:
            print("erreur code :", r.status_code)
            self.metadata = None
            
        #DATA DOWNLOAD
        url = "https://api.geosas.fr/edr/collections/safran-isba/position"
        
        params = {
            "coords": self.coords,
            "crs": self.crs,
            "parameter-name": self.var_list,
            "f": self.formatting,
            "datetime": self.date
        }
        
        r = requests.get(url, params=params)
        print(r.request.url)
        if r.ok:
            print("requête ok")
            self.data = r.json()
        else:
            print(f"erreur code : {r.status_code}")
            self.data = None
            
        return self.metadata, self.data
    
    def plot_data_chronicle(self):
        """
        Plot data for a specific parameter without seaborn dependency
        
        Parameters:
        -----------
        df : pandas.DataFrame
            DataFrame containing the data with 'date' and parameter columns
        param_name : str
            Name of the parameter to plot
        """
        if self.metadata is None:
            print("Erreur : Les métadonnées ne sont pas disponibles")
            return
            
        for name, parametre in self.metadata["parameter_names"].items():
            if name == self.var_list:
                unit_label = parametre["observedProperty"]["label"]
                unit_symbol = parametre["unit"]["symbol"]["value"]
                description = parametre["description"]

                fig, ax = plt.subplots(figsize=(12, 6))
                ax.plot(self.data["date"], self.data[self.var_list], linewidth=2)
                ax.tick_params(axis="x", rotation=45)
                ax.set_title(description, size=16)
                ax.set_xlabel("Date", size=14)
                ax.set_ylabel(f"{unit_label} ({unit_symbol})", size=14)
                fig.tight_layout()
                break
            
        return fig 

#%% MAIN 

# sim2_API = Sim2_API(
#     box = "333482,6794494,350629,6813081",
#     crs = "EPSG:2154", 
#     var_list="solarradiation,recharge,potentialevapotranspiration",  # ← noms user-friendly
#     formatting="NetCDF4", 
#     date="2020-01-01/2020-12-31"
# )