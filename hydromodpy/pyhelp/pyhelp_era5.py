from .pyhelp_csv_manager import PyhelpCsvManager
from hydromodpy.tools.toolbox import load_shapefile, select_nearest_point, get_centroid_coordinates, convert_units, select_within_polygon_points
import xarray as xr
import pandas as pd
import os
from typing import Optional
from hydromodpy.tools import get_logger

logger = get_logger(__name__)

class PyhelpEra5(PyhelpCsvManager):
    """ERA5 climate data extraction and processing for PyHelp"""
    
    def __init__(self, folder_path: str, shapefile_path: Optional[str] = None) -> None:
        """Initialize ERA5 data extraction"""
        self._folder_path = folder_path
        self._shapefile_path = shapefile_path

    def _get_nearest_point(self, ds: xr.Dataset) -> xr.Dataset:
        """Find the nearest grid point in the NetCDF dataset from the shapefile geometry"""
        if not self._shapefile_path:
            return ds   
        
        gdf = load_shapefile(self._shapefile_path)
        lon, lat = get_centroid_coordinates(gdf)
        return select_nearest_point(ds, lon, lat)
    
    def _select_within_polygon_points(self, ds: xr.Dataset) -> xr.Dataset:
        """Find the grid points in the NetCDF dataset that are within the shapefile geometry"""
        if not self._shapefile_path:          # ← nouveau bloc
            return ds 
        gdf = load_shapefile(self._shapefile_path)
        return select_within_polygon_points(ds, gdf)
    
    def extract_era5_daily_timeseries(self) -> None:
        """
        Extract timeseries from ERA5 NetCDF files and save to CSV in the correct PyHelp format
        for each variable (radiation, precipitation, temperature).
        """
        variables = {
            "radiation": "solrad_input_data.csv",
            "precipitation": "precip_input_data.csv",
            "temperature": "airtemp_input_data.csv"
        }
            
        for folder, output_file in variables.items():
            var_folder = os.path.join(self._folder_path, folder)
            all_dataframes = []
    
            try:
                # iterate through every year folder
                for year in sorted(os.listdir(var_folder)):
                    year_folder = os.path.join(var_folder, year)
                    netcdf_files = self._get_netcdf_files(year_folder)
    
                    # Open and process the dataset
                    ds = self._process_dataset(netcdf_files)
    
                    # Convert the dataframe
                    df = self._process_dataframe(ds)
                    
                    df = convert_units(df, folder)
    
                    all_dataframes.append(df)
    
                dataframe = self._combine_dataframes(all_dataframes)
    
                self._save_csv(dataframe, output_file)
    
            except Exception as e:
                logger.exception("Failed processing ERA5 %s dataset", folder)

    def _get_netcdf_files(self, year_folder: str) -> list:
        """Get a sorted list of NetCDF files from a year folder."""
        return [os.path.join(year_folder, file) for file in sorted(os.listdir(year_folder))]

    def _process_dataset(self, netcdf_files: list, nearest_filter: bool = True) -> xr.Dataset:
    
        ds = xr.open_mfdataset(netcdf_files, combine='by_coords', decode_times=True)
    
        if 'time' in ds.coords and 'valid_time' not in ds.coords:
            ds = ds.rename({'time': 'valid_time'})
    
        ds = self._get_nearest_point(ds) if nearest_filter else self._select_within_polygon_points(ds)
    
        if 'valid_time' not in ds.dims:
            raise ValueError("Pas de dimension temporelle détectée.")
    
        var = list(ds.data_vars)[0]
        da = ds[var]
          
        if var in ("tp", "fal"):
            da_diff = da.diff('valid_time', label='upper').clip(min=0)
            da_daily = da_diff.resample(valid_time='1D').sum()
        if var == "t2m":
            da_daily = da.resample(valid_time='1D').mean()
    
        return da_daily.to_dataset(name=var)
    
    

    def _process_dataframe(self, ds: xr.Dataset) -> pd.DataFrame:
        """Convert the preprocessed dataset to a dataframe and reshape it"""
        df = ds.to_dataframe().reset_index()
        
        df["valid_time"] = pd.to_datetime(df["valid_time"], errors='coerce')
        
        df = df.sort_values(by="valid_time")
    
        main_var = list(ds.data_vars)[0]  
        df = df.pivot_table(
            index="valid_time", 
            columns=["latitude", "longitude"], 
            values=main_var
        )
        return df

    def _combine_dataframes(self, all_dataframes: list) -> pd.DataFrame:
        """Combine all DataFrames into one and processes it"""
        dataframe = pd.concat(all_dataframes, ignore_index=False)
        
        dataframe.index = pd.to_datetime(dataframe.index, dayfirst=True)
        dataframe = dataframe.sort_index()
        dataframe.index = dataframe.index.strftime("%d/%m/%Y")
        
        dataframe.index.name = "Date"
        return dataframe

    def _save_csv(self, dataframe: pd.DataFrame, output_file: str) -> None:
        """Save the DataFrame to a CSV file with correct headers"""
        latitude_values = ["Latitude (dd)"] + [str(col[0]) for col in dataframe.columns]
        longitude_values = ["Longitude (dd)"] + [str(col[1]) for col in dataframe.columns]

        output_path = os.path.join(self._folder_path, output_file)

        with open(output_path, "w") as f:
            f.write(",".join(latitude_values) + "\n")
            f.write(",".join(longitude_values) + "\n")
            f.write("\n")
    
        dataframe.to_csv(output_path, mode="a", index=True, header=False)

    def display_data(self, csv_name) -> None:
        """Display chosen weather csv file data"""
        file = os.path.join(self._folder_path, csv_name)
        
        data = pd.read_csv(file)
        if data.empty:
            logger.warning("ERA5 CSV %s contains no data", csv_name)
        else:
            logger.info("Loaded %d rows from ERA5 CSV %s", len(data), csv_name)
            logger.debug("ERA5 CSV %s content:\n%s", csv_name, data)

    def list_parameters(self) -> None:
        pass
