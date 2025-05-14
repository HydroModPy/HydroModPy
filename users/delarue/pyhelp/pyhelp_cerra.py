from pyhelp_csv_manager import PyhelpCsvManager
from helper import load_shapefile, select_nearest_point, get_centroid_coordinates, convert_units, select_within_polygon_points
import xarray as xr
import pandas as pd
import os

class PyhelpCerra(PyhelpCsvManager):
    """ERA5 climate data extraction and processing for PyHelp"""
    
    def __init__(self, folder_path: str, shapefile_path: str) -> None:
        """Initialize cerra data extraction"""
        self._folder_path = folder_path
        self._shapefile_path = shapefile_path
        
        
        

    def _get_nearest_point(self, ds: xr.Dataset) -> xr.Dataset:
        """Find the nearest grid point in the NetCDF dataset from the shapefile geometry"""
        gdf = load_shapefile(self._shapefile_path)
        lon, lat = get_centroid_coordinates(gdf)
        return select_nearest_point(ds, lon, lat)
    
    def _select_within_polygon_points(self, ds: xr.Dataset) -> xr.Dataset:
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
                print(f"Error processing ERA5 data for {folder}: {e}")

    def _get_netcdf_files(self, year_folder: str) -> list:
        """Get a sorted list of NetCDF files from a year folder."""
        return [os.path.join(year_folder, file) for file in sorted(os.listdir(year_folder))]

    def _process_dataset(self, netcdf_files: list) -> xr.Dataset:
        """
        Open the NetCDF files, find the nearest grid point 
        or the grid points within the shapefile area
        and reshape the data to daily timeseries.
        """
        ds = xr.open_mfdataset(netcdf_files)
        
        
        #  if the bassin shapefile is bigger than the netCDF cells, change the method accordingly
        #ds = self._select_within_polygon_points(ds)
        ds = self._get_nearest_point(ds)
        
        ds = ds.coarsen(valid_time=24, boundary="trim").mean()
        return ds

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
            print("No data available.")
        else:
            print("Données du fichier CSV:")
            print(data)

    def list_parameters(self) -> None:
        pass
