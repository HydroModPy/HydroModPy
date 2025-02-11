# -*- coding: utf-8 -*-
"""
Developed by Bastien Boivin (2025)
"""
#%%
import xarray as xr
import pandas as pd
import numpy as np
import rasterio
import geopandas as gpd
from shapely.geometry import mapping
import logging
import os
import rioxarray
import plotly.offline as pyo
from rasterio.warp import transform
import plotly.graph_objects as go

class NetCDFReader:
    """
    A class to read, process, and visualize NetCDF files.

    Attributes
    ----------
    filepath : str
        Path to the NetCDF file (.nc).
    epsg_project : int, optional
        EPSG code for projection. If None, no reprojection is performed.
    mask : str, optional
        Mask type. Default is 'all'.
    ds : xarray.Dataset
        The loaded dataset.
    metadata : dict
        Metadata extracted from the dataset.
    epsg : int
        EPSG code of the dataset's coordinate reference system.

    Methods
    -------
    open_dataset()
        Opens a NetCDF file and loads its contents into memory (xarray.dataset).
    md()
        Extracts and returns metadata from the dataset.
    to_df(extraction, var=None)
        Converts dataset to a DataFrame based on extraction parameters.
    spatial_aggregate(func="mean")
        Aggregates spatial data using the specified function.
    convert_time(target_freq)
        Converts the time frequency of the dataset.
    save_to_netcdf(output_path)
        Saves the dataset to a new NetCDF file.
    plot_interactive(variable, date_min, date_max, homogeneous_color=False, show_pixel_grid=False, open_browser=False)
        Plots an interactive visualization of a variable over a specified date range.
    """

    def __init__(self, filepath, epsg_project=None, mask='all'):
        """
        Initializes the NetCDFReader with the given file path and optional EPSG projection.

        Parameters
        ----------
        filepath : str
            Path to the NetCDF file.
        epsg_project : int, optional
            EPSG code for projection. If None, no reprojection is performed.
        mask : str, optional
            Mask type. Default is 'all'.
        """
        self.filepath = filepath
        self.epsg_project = epsg_project
        self.mask = mask

        self.ds = self.open_dataset()
        self.metadata = self.md()
        self.epsg = self.metadata['crs']

        if self.epsg_project is not None and self.epsg != self.epsg_project:
            try:
                self.ds = self.ds.rio.reproject(self.epsg_project)
                self.epsg = self.epsg_project
                self.metadata['crs'] = self.epsg_project
            except:
                logging.warning(f"Reprojection to EPSG:{self.epsg_project} failed. EPSG:{self.epsg} will be used.")

        if "x" in self.ds.coords and "y" in self.ds.coords:
            self.ds = self.ds.set_coords(["x", "y"]).swap_dims({"x": "x", "y": "y"})

    def open_dataset(self):
        """
        Opens a NetCDF file and loads its contents into memory.

        Returns
        -------
        xarray.Dataset
            The loaded dataset.
        """
        ds = xr.open_dataset(self.filepath, decode_coords='all')
        return ds

    def md(self):
        """
        Extracts and returns metadata from the dataset.

        Returns
        -------
        dict
            A dictionary containing:
            - bbox : tuple
                Spatial extent (bounding box).
            - start_date : str
                First available date in the dataset.
            - end_date : str
                Last available date in the dataset.
            - timestep : str
                Time step between consecutive records.
            - crs : int
                EPSG code of the dataset's coordinate reference system.
            - shape : tuple
                Spatial dimensions of the dataset.
            - resolution : tuple
                Spatial resolution of the dataset.
            - variables : list
                List of available variables in the dataset.
            - global_attributes : dict
                Global attributes from the dataset.
            - dimensions : dict
                Size of each dimension in the dataset.
            - variable_attributes : dict
                Attributes for each variable in the dataset.
        """
        meta = {
            'bbox': self.ds.rio.bounds(),
            'start_date': pd.to_datetime(str(self.ds.time[0].values)).strftime("%Y-%m-%d"),
            'end_date': pd.to_datetime(str(self.ds.time[-1].values)).strftime("%Y-%m-%d"),
            'timestep': pd.to_timedelta((self.ds.time[1] - self.ds.time[0]).values).isoformat(),
            'crs': self.ds.rio.crs.to_epsg(),
            'shape': self.ds.rio.shape,
            'resolution': self.ds.rio.resolution(),
            'variables': list(self.ds.data_vars),
            'global_attributes': {attr: self.ds.attrs[attr] for attr in self.ds.attrs},
            'dimensions': {dim: len(self.ds[dim]) for dim in self.ds.dims},
            'variable_attributes': {var: self.ds[var].attrs for var in self.ds.data_vars}
        }
        return meta

    def to_df(self, extraction, var=None):
        """
        Converts dataset to a DataFrame based on extraction parameters.

        Parameters
        ----------
        extraction : list, tuple, or str
            Extraction parameters. Can be a list [x, y, epsg], a path to a TIFF file, or a path to a shapefile.
        var : str, optional
            Variable to extract. If None, all variables are extracted.

        Returns
        -------
        pandas.DataFrame or dict
            DataFrame if a single variable is extracted, otherwise a dictionary of DataFrames.
        """
        x = None
        y = None

        if isinstance(extraction, (list, tuple)) and len(extraction) == 3:
            x0, y0, src_epsg = extraction
            if src_epsg != self.epsg:
                new_x, new_y = transform(f"EPSG:{src_epsg}", f"EPSG:{self.epsg}", [x0], [y0])
                x, y = new_x[0], new_y[0]
            else:
                x, y = x0, y0

        elif isinstance(extraction, str):
            ext = os.path.splitext(extraction)[-1].lower()
            if ext in ['.tif', '.tiff']:
                with rasterio.open(extraction) as src:
                    data = src.read(1)
                    indices = np.where(data == 1)
                    if len(indices[0]) == 0:
                        logging.error("No pixel with the value 1 was found in the raster.")
                    if len(indices[0]) > 1:
                        logging.error("More than one pixel with the value 1 was found in the raster.")
                    row, col = indices[0][0], indices[1][0]
                    x_mask, y_mask = rasterio.transform.xy(src.transform, row, col, offset='center')
                    mask_epsg = src.crs.to_epsg() if src.crs is not None else None
                    if mask_epsg is not None and mask_epsg != self.epsg:
                        new_x, new_y = transform(f"EPSG:{mask_epsg}", f"EPSG:{self.epsg}", [x_mask], [y_mask])
                        x, y = new_x[0], new_y[0]
                    else:
                        x, y = x_mask, y_mask

            elif ext == '.shp':
                mask_gdf = gpd.read_file(extraction)
                if mask_gdf.empty:
                    logging.error("The shapefile is empty.")
                geom = mask_gdf.geometry.iloc[0]
                if geom.geom_type != 'Point':
                    geom = geom.centroid
                x_shp, y_shp = geom.x, geom.y
                shp_epsg = mask_gdf.crs.to_epsg()
                if shp_epsg != self.epsg:
                    new_x, new_y = transform(f"EPSG:{shp_epsg}", f"EPSG:{self.epsg}", [x_shp], [y_shp])
                    x, y = new_x[0], new_y[0]
                else:
                    x, y = x_shp, y_shp
            else:
                logging.error(f"Unsupported extraction format: {ext}. Accepted formats: .tif, .tiff, and .shp")
        else:
            logging.error("The 'extraction' parameter must be a file path or a list [x, y, epsg].")

        try:
            selected = self.ds.sel(x=x, y=y, method="nearest")
        except Exception as e:
            logging.error(f"Error selecting the point ({x}, {y}) in the dataset: {e}")

        def dataarray_to_df(da, var_name):
            df = da.to_dataframe(name=var_name).reset_index()
            df.attrs = da.attrs
            df.attrs['extraction_point'] = {'x': x, 'y': y, 'crs': f"EPSG:{self.epsg}"}
            return df

        if var is not None:
            if var not in selected.data_vars:
                logging.error(f"The variable '{var}' does not exist in the dataset.")
            da = selected[var]
            return dataarray_to_df(da, var)
        else:
            result = {}
            for variable in selected.data_vars:
                da = selected[variable]
                result[variable] = dataarray_to_df(da, variable)
            return result

    def spatial_aggregate(self, func="mean"):
        """
        Aggregates spatial data using the specified function.

        Parameters
        ----------
        func : str, optional
            Aggregation function. Must be 'mean' or 'sum'. Default is 'mean'.
        """
        if func not in ["mean", "sum"]:
            logging.error("Aggregation function must be 'mean' or 'sum'.")
            return

        if not all(dim in self.ds.dims for dim in ["x", "y"]):
            logging.error(
                f"Dimensions 'x' and 'y' are missing. Available dimensions: {list(self.ds.dims)}"
            )
            return

        if func == "mean":
            agg = self.ds.mean(dim=["x", "y"])
        else:
            agg = self.ds.sum(dim=["x", "y"])

        agg_expanded = agg.expand_dims({'y': self.ds.coords['y'], 'x': self.ds.coords['x']})

        new_ds = agg_expanded.broadcast_like(self.ds)
        new_ds = new_ds.transpose("time", "y", "x")

        self.ds = new_ds
        self.metadata = self.md()

    def convert_time(self, target_freq):
        """
        Converts the time frequency of the dataset.

        Parameters
        ----------
        target_freq : str
            Target frequency. Must be 'D', 'W', or 'M'.
        """
        valid_freqs = ["D", "W", "M"]
        if target_freq not in valid_freqs:
            logging.error("The target frequency must be 'D', 'W', or 'M'.")

        # Infer the current frequency from the dataset's time coordinate.
        time_values = pd.to_datetime(self.ds.time.values)
        inferred = pd.infer_freq(time_values)
        if inferred is None:
            logging.error("Unable to infer the dataset's time frequency.")

        # Normalize inferred frequency to "D", "W", or "M".
        if inferred.startswith("D"):
            current_freq = "D"
        elif inferred.startswith("W"):
            current_freq = "W"
        elif "M" in inferred:
            current_freq = "M"
        else:
            logging.error(f"Unsupported time frequency: {inferred}")

        order = {"D": 1, "W": 2, "M": 3}

        # If the current frequency matches the target, no conversion is needed.
        if order[current_freq] == order[target_freq]:
            return

        if order[current_freq] < order[target_freq]:
            # Aggregation: resample and sum values (e.g., D -> W, D -> M, or W -> M).
            new_ds = self.ds.resample(time=target_freq).sum()
        else:
            # Disaggregation: convert to daily first, then aggregate if needed.
            if current_freq == "D":
                daily_ds = self.ds
            else:
                daily_ds = self._disaggregate_to_daily(current_freq)
            if target_freq == "D":
                new_ds = daily_ds
            else:
                new_ds = daily_ds.resample(time=target_freq).sum()

        self.ds = new_ds
        self.metadata = self.md()

    def _disaggregate_to_daily(self, current_freq):
        """
        Disaggregates the dataset to daily frequency.

        Parameters
        ----------
        current_freq : str
            Current frequency of the dataset.

        Returns
        -------
        xarray.Dataset
            Dataset with daily frequency.
        """
        new_vars = {var: [] for var in self.ds.data_vars}
        new_time_all = []  # Cumulative list of daily dates

        for t in pd.to_datetime(self.ds.time.values):
            if current_freq == "M":
                period = pd.Period(t, freq="M")
            elif current_freq == "W":
                period = pd.Period(t, freq="W")
            else:
                logging.error("Disaggregation not supported for frequency: " + current_freq)
            daily_range = pd.date_range(start=period.start_time, end=period.end_time, freq="D")
            n_days = len(daily_range)
            new_time_all.extend(daily_range)
            for var in self.ds.data_vars:
                original_da = self.ds[var].sel(time=t)
                daily_values = original_da.values / n_days
                repeated = np.repeat(daily_values[np.newaxis, ...], n_days, axis=0)
                new_da = xr.DataArray(
                    repeated,
                    dims=("time",) + original_da.dims,
                    coords={"time": daily_range,
                            **{dim: original_da.coords[dim] for dim in original_da.dims if dim != "time"}}
                )
                new_vars[var].append(new_da)

        final_vars = {}
        for var in self.ds.data_vars:
            final_vars[var] = xr.concat(new_vars[var], dim="time")
        new_ds = xr.Dataset(final_vars).sortby("time")
        return new_ds

    def save_to_netcdf(self, output_path):
        """
        Saves the dataset to a new NetCDF file.

        Parameters
        ----------
        output_path : str
            Path to the output NetCDF file.
        """
        self.ds.to_netcdf(output_path)

    def plot_interactive(self, variable, date_min, date_max, homogeneous_color=False, show_pixel_grid=False, open_browser=False):
        """
        Plots an interactive visualization of a variable over a specified date range.

        Parameters
        ----------
        variable : str
            Variable to plot.
        date_min : str
            Start date for the plot.
        date_max : str
            End date for the plot.
        homogeneous_color : bool, optional
            Whether to use a homogeneous color scale. Default is False.
        show_pixel_grid : bool, optional
            Whether to show the pixel grid. Default is False.
        open_browser : bool, optional
            Whether to open the plot in a browser. Default is False.
        """
        if variable not in self.ds.data_vars:
            logging.error(f"The variable '{variable}' does not exist in the dataset.")

        start = pd.to_datetime(date_min)
        end = pd.to_datetime(date_max)

        times = pd.to_datetime(self.ds.time.values)
        mask = (times >= start) & (times <= end)
        if not np.any(mask):
            logging.error("No data found between the specified dates.")
        subset = self.ds.sel(time=times[mask])
        da = subset[variable]

        x_coords = da.coords.get("x")
        y_coords = da.coords.get("y")

        if homogeneous_color:
            global_min = np.nanmin(da.values)
            global_max = np.nanmax(da.values)
        else:
            global_min, global_max = None, None

        first_frame_data = da.isel(time=0).values
        heatmap = go.Heatmap(
            z=first_frame_data,
            x=x_coords.values if x_coords is not None else None,
            y=y_coords.values if y_coords is not None else None,
            colorscale='Viridis',
            zsmooth=False,
            xgap=0,
            ygap=0,
            colorbar=dict(
                title=variable,
                tickfont=dict(size=12)
            ),
            zmin=global_min,
            zmax=global_max
        )
        fig = go.Figure(data=[heatmap])

        frames = []
        for i, t in enumerate(da.time.values):
            frame_data = da.isel(time=i).values
            frame = go.Frame(
                data=[go.Heatmap(
                    z=frame_data,
                    x=x_coords.values if x_coords is not None else None,
                    y=y_coords.values if y_coords is not None else None,
                    colorscale='Viridis',
                    zsmooth=False,
                    xgap=0,
                    ygap=0,
                    zmin=global_min,
                    zmax=global_max
                )],
                name=str(pd.to_datetime(t).strftime('%Y-%m-%d'))
            )
            frames.append(frame)
        fig.frames = frames

        slider_steps = []
        for frame in frames:
            step = {
                "args": [
                    [frame.name],
                    {"frame": {"duration": 300, "redraw": True},
                    "mode": "immediate",
                    "transition": {"duration": 300}}
                ],
                "label": frame.name,
                "method": "animate"
            }
            slider_steps.append(step)

        sliders = [dict(
            active=0,
            pad={"t": 50},
            steps=slider_steps,
            currentvalue={"prefix": "Date : ", "font": {"size": 16}}
        )]

        fig.update_layout(
            title={
                "text": f"Interactive visualization of the variable '{variable}'<br>from {date_min} to {date_max}",
                "x": 0.5,
                "xanchor": "center",
                "font": {"size": 18}
            },
            xaxis_title="X Coordinate",
            yaxis_title="Y Coordinate",
            sliders=sliders,
            template="plotly_white",
            margin=dict(l=50, r=50, t=100, b=50)
        )

        fig.update_xaxes(constrain="domain")
        fig.update_yaxes(scaleanchor="x", scaleratio=1)

        if show_pixel_grid and x_coords is not None and y_coords is not None:
            shapes = []
            x_array = x_coords.values
            y_array = y_coords.values
            if len(x_array) > 1:
                x_spacing = np.mean(np.diff(x_array))
            else:
                x_spacing = 1
            if len(y_array) > 1:
                y_spacing = np.mean(np.diff(y_array))
            else:
                y_spacing = 1
            x_min_edge = x_array[0] - x_spacing / 2
            x_max_edge = x_array[-1] + x_spacing / 2
            y_min_edge = y_array[0] - y_spacing / 2
            y_max_edge = y_array[-1] + y_spacing / 2

            x_edges = [x_min_edge + i * x_spacing for i in range(len(x_array) + 1)]
            for x_edge in x_edges:
                shapes.append({
                    'type': 'line',
                    'x0': x_edge,
                    'y0': y_min_edge,
                    'x1': x_edge,
                    'y1': y_max_edge,
                    'line': {'color': 'black', 'width': 2}
                })
            y_edges = [y_min_edge + i * y_spacing for i in range(len(y_array) + 1)]
            for y_edge in y_edges:
                shapes.append({
                    'type': 'line',
                    'x0': x_min_edge,
                    'y0': y_edge,
                    'x1': x_max_edge,
                    'y1': y_edge,
                    'line': {'color': 'black', 'width': 2}
                })
            fig.update_layout(shapes=shapes)

        if open_browser:
            pyo.plot(fig, auto_open=True)
        else:
            fig.show()

#%% Test

if __name__ == "__main__":
    # Example usage of the NetCDFReader class
    filepath = 'path'
    epsg_project = 2154
    mask = "all"
    template_raster = 'path'
    output_path = 'path'

    # Initialize the NetCDFReader
    reader = NetCDFReader(filepath, epsg_project=epsg_project)
    reader.save_to_netcdf(output_path)
    print("Metadata:", reader.metadata)

#%% Convert time frequency to monthly
    reader.convert_time("M")
    print("Converted time frequency to monthly.")

#%% Aggregate spatial data by mean
    reader.spatial_aggregate(func="mean")
    print("Spatially aggregated data by mean.")
    print("Metadata:", reader.metadata)

#%% Extract time series for a specific variable at a given point
    extraction_point = [331300, 6781273, 2154]
    variable = "DRAINC_Q"
    time_series = reader.to_df(extraction_point, var=variable)
    print(f"Time series for variable '{variable}':")
    print(time_series)

#%% Plot
    reader.plot_interactive(variable="DRAINC_Q",
                            date_min="2022",
                            date_max="2024",
                            homogeneous_color=True,
                            show_pixel_grid=True,
                            open_browser=True
                            )
