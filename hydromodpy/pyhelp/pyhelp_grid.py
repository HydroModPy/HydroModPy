# -*- coding: utf-8 -*-
"""
Created on Mon Feb 24 19:03:21 2025

@author: mathi
"""

import pandas as pd
from .pyhelp_csv_manager import PyhelpCsvManager
from hydromodpy.tools.toolbox import load_csv, transform_coordinates, filter_coordinates_by_shape
from typing import Optional
from hydromodpy.tools import get_logger

logger = get_logger(__name__)

class PyhelpGrid(PyhelpCsvManager):
    """
    1) Loads a single-row base CSV (never overwritten).
    2) Takes parameters, replicates the base row to match the number of DEM coords,
       assigns the new parameter values to all rows, appends lat/lon, then saves.
    """

    def __init__(self, base_file_path: str, output_file_path: str,
                 dem_file_path: str, shapefile_path: Optional[str] = None) -> None:    
        """
        :param base_file_path: Path to the single-row CSV (e.g., input_grid_base1.csv).
        :param output_file_path: Where the updated CSV will be saved.
        :param dem_file_path: Path to the DEM for lat/lon extraction.
        :param shapefile_path: (optional) Path to the polygon used to filter lat/lon.
                       If None or "", the DEM is assumed already clipped.
        
        """
        self._base_file_path = base_file_path
        self._output_file_path = output_file_path
        self._dem_file_path = dem_file_path
        self._shapefile_path = shapefile_path
        
        # Load the single-row base CSV
        self._base_data = self._load_base_csv()
        self._data = self._base_data.copy()

    def _load_base_csv(self) -> pd.DataFrame:
        """Load the base CSV file """
        base_df = load_csv(self._base_file_path)
        if base_df.empty:
            logger.error("Base grid CSV %s is empty or missing", self._base_file_path)
        return base_df
    

    def _dem_coordinate(self) -> list:
        """
        Get a list of longitude and latitude from the DEM.
        Here, it transforms from EPSG:2056 to EPSG:4326
        """
        coords = transform_coordinates(self._dem_file_path, "EPSG:2056", "EPSG:4326")
        # Si aucun shapefile n’est indiqué, on ne filtre pas les points :
        if self._shapefile_path:
            return filter_coordinates_by_shape(coords, self._shapefile_path, "EPSG:4326")
        return coords

    def display_data(self) -> None:
        """Displays the current, in-memory _data."""
        if self._data.empty:
            logger.warning("No grid data available to display")
        else:
            logger.info("Grid dataset contains %d rows", len(self._data))
            logger.debug("Grid dataset preview:\n%s", self._data)

    def list_parameters(self) -> None:
        """Lists the columns in the current in-memory DataFrame."""
        if self._data.empty:
            logger.warning("No grid parameters available")
        else:
            logger.info("Grid parameters available: %s", ", ".join(map(str, self._data.columns)))

    def update_parameters(self, **params) -> None:
        """
        Main method which aims to:
        Replicate the single row from base CSV to match DEM coords.
        Assign new parameter values to all rows.
        Append lat_dd / lon_dd columns.
        Save final DataFrame to the output CSV file.
        """
        if not params:
            params = self._prompt_parameters()

        # Start from the base row again each time
        base_df = self._base_data.copy()
        if base_df.empty:
            logger.error("Base CSV is empty; cannot update grid parameters")
            return
        
        # Transform DEM to get coordinates
        coordinates = self._dem_coordinate()
        if not coordinates:
            logger.error("No coordinates extracted from DEM %s", self._dem_file_path)
            return
        
        # Replicate the single base row to match the number of DEM points to create homogeneous case
        rows = len(coordinates)
        df2 = pd.DataFrame([base_df.iloc[0].values] * rows, columns=base_df.columns)

        for param_name, param_value in params.items():
            df2[param_name] = param_value

        # Latitude and Longitude
        df2["lat_dd"] = [coord[1] for coord in coordinates]
        df2["lon_dd"] = [coord[0] for coord in coordinates]

        # Index incrementation
        start = int(df2["cid"].iloc[0])
        df2["cid"] = range(start, start + rows)

        # reorder columns
        keep = ["cid", "lat_dd", "lon_dd"]
        other= [c for c in df2.columns if c not in keep]
        final = keep + other
        df2 = df2[final]

        self._data = df2

        self._save_csv(self._data, self._output_file_path)
        logger.info("Updated grid saved to %s", self._output_file_path)

    def _prompt_parameters(self) -> dict:
        """Prompt the user to input parameter values if none were passed."""
        parameters_to_ask = [
            "wind", "hum1", "hum2", "hum3", "hum4",
            "growth_start", "growth_end", "nlayer",
            "LAI,EZD", "CN", "lay_type1", "thick1",
            "poro1", "fc1", "wp1", "ksat1",
            "dist_dr1", "slope1"
        ]
        params = {}
        for p in parameters_to_ask:
            val = input(f"Enter value for {p}: ")
            if val:
                params[p] = val
        return params
