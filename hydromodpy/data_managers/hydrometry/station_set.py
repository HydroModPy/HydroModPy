"""
File Name: station_set.py
Author: Bastien Boivin
Email: bastien.boivin@univ-rennes.fr | @proton.me
Creation Date: 2025-04-08
Description: Station set wrapper for Hub'Eau hydrometry API and local files.
"""
#%% Import libraries
import requests
import pandas as pd
from datetime import datetime
from typing import Dict, List, Union, Optional, Mapping, Any
from pathlib import Path

try:
   from .station import Station
   from .loaders_api import ApiStationLoader
   from .loaders_local import LocalStationLoader
except ImportError:
   import sys
   _this_dir = Path(__file__).resolve().parent
   if str(_this_dir) not in sys.path:
       sys.path.insert(0, str(_this_dir))
   from station import Station
   from loaders_api import ApiStationLoader
   from loaders_local import LocalStationLoader

#%% Constants
API_BASE_URL = "https://hubeau.eaufrance.fr/api/v2/"

AVAILABLE_VARIABLES = {
   'QmnJ': 'Daily mean discharge',
   'QmM': 'Monthly mean discharge',
   'HIXM': 'Maximum monthly instantaneous water level',
   'HIXnJ': 'Maximum daily instantaneous water level',
   'QINM': 'Minimum monthly instantaneous discharge',
   'QINnJ': 'Minimum daily instantaneous discharge',
   'QixM': 'Maximum monthly instantaneous discharge',
   'QIXnJ': 'Maximum daily instantaneous discharge'
}

STATUS_MESSAGES = {
   200: "Success: All results present in the response",
   206: "Partial content: Some results may be missing",
   400: "Bad request: Check your request parameters",
   401: "Unauthorized: Check your credentials",
   403: "Forbidden: Check your permissions",
   404: "Not found: Check your URL",
   500: "Internal server error: Try again later"
}

#%% Class definition
class StationSet:
   """Container orchestrating multi-station hydrometric series.

   The class centralizes:
   - station selection (explicit ids or geographic mask),
   - data loading (Hub'Eau API or local exports),
   - harmonization into :class:`Station` objects,
   - completeness diagnostics and optional exports.
   """

   @classmethod
   def from_toml(cls, config_path: Union[str, Path]):
       """
       Build a :class:`StationSet` from a TOML configuration file.

       Parameters
       ----------
       config_path : str or Path
           Path to a TOML file validated by ``load_hydrometry_toml``.

       Returns
       -------
       StationSet
           Initialized instance with loaded stations.
       """
       try:
           from .hydrometry_config import load_hydrometry_toml
       except ImportError:
           from hydrometry_config import load_hydrometry_toml

       cfg = load_hydrometry_toml(config_path)
       return cls.from_config(cfg)

   @classmethod
   def from_config(cls, config_data: Mapping[str, Any]):
       """
       Build a :class:`StationSet` from normalized config sections.

       Parameters
       ----------
       config_data : Mapping[str, Any]
           Validated configuration with ``hydrometry``, ``source``,
           ``selection`` and ``output`` sections.

       Returns
       -------
       StationSet
           Initialized instance with loaded stations.
       """
       hydrometry_cfg = dict(config_data["hydrometry"])
       source_cfg = dict(config_data["source"])
       selection_cfg = dict(config_data["selection"])
       output_cfg = dict(config_data["output"])

       station_ids = None
       mask_path = None
       if selection_cfg["mode"] == "stations":
           station_ids = selection_cfg["station_ids"]
       else:
           mask_path = selection_cfg["mask_path"]

       output_value = None
       if output_cfg["enabled"]:
           if output_cfg["export_mode"] == "full":
               output_value = [output_cfg["path"], "full"]
           else:
               output_value = output_cfg["path"]

       return cls(
           variable=hydrometry_cfg["variable"],
           id=station_ids,
           mask=mask_path,
           display=hydrometry_cfg["display"],
           date_start=hydrometry_cfg.get("date_start"),
           date_end=hydrometry_cfg.get("date_end"),
           output=output_value,
           source_mode=source_cfg["mode"],
           local_data_dir=source_cfg.get("local_data_dir"),
       )

   def __init__(self,
                *,
                variable: str = 'QmnJ',
                id: Optional[Union[str, List[str], None]] = None,
                mask: Optional[Union[str, Path, None]] = None,
                display: Optional[bool] = False,
                date_start: Optional[str] = None,
                date_end: Optional[str] = None,
                output: Optional[Union[str, List[str], None]] = None,
                source_mode: str = "api",
                local_data_dir: Optional[Union[str, Path, None]] = None,
                ):
       """
       Initialize StationSet instance.

       Parameters
       ----------
       variable : str, default 'QmnJ'
           Hydrometric variable code. Must be one of: QmnJ, QmM, HIXM,
           HIXnJ, QINM, QINnJ, QixM, QIXnJ.
       id : str or list of str, optional
           Station ID(s) - 8 or 10 characters. Single string or list of strings.
       mask : str or Path, optional
           Path to geographic zone file (.shp, .geojson for vector or .tif, .img for raster).
       display : bool, default False
           Whether to display raw JSON responses.
       date_start : str, optional
           Start date for filtering in format 'YYYY-MM-DD'.
       date_end : str, optional
           End date for filtering in format 'YYYY-MM-DD'.
       output : str or list, optional
           Output path for exports. If str: lite mode. If [path, "full"]: full mode.
       source_mode : str, default "api"
           Data source mode: "api" or "local".
       local_data_dir : str or Path, optional
           Directory containing local exported hydrometry files used when
           source_mode="local".

       Raises
       ------
       ValueError
           If inputs are invalid (variable code, id format, source mode...).
       FileNotFoundError
           If ``source_mode='local'`` and ``local_data_dir`` does not exist.
       """
       # Validate variable
       if variable not in AVAILABLE_VARIABLES:
           available = ', '.join(AVAILABLE_VARIABLES.keys())
           raise ValueError(f"Invalid variable: {variable}. Available: {available}")

       self.variable = variable
       self.display = display
       self.date_start = datetime.strptime(date_start, "%Y-%m-%d") if date_start else None
       self.date_end = datetime.strptime(date_end, "%Y-%m-%d") if date_end else None
       self.output = output
       self.source_mode = str(source_mode).strip().lower()
       self.local_data_dir = Path(local_data_dir).expanduser().resolve() if local_data_dir else None

       if self.source_mode not in ("api", "local"):
           raise ValueError("source_mode must be 'api' or 'local'.")
       if self.source_mode == "local" and self.local_data_dir is None:
           raise ValueError("local_data_dir is required when source_mode='local'.")
       if self.source_mode == "local" and not self.local_data_dir.exists():
           raise FileNotFoundError(f"local_data_dir not found: {self.local_data_dir}")

       # Initialize containers as DataFrames
       self.stations_info = pd.DataFrame()
       self.sites_info = pd.DataFrame()
       self.data = pd.DataFrame()
       self.metadata = pd.DataFrame()
       self.missing_data_summary = pd.DataFrame()
       self.stations: Dict[str, Station] = {}

       # Process IDs or mask
       if mask is not None:
           self.station_id, self.site_id = self._get_stations_from_mask(mask)
       elif id is not None:
           self.station_id, self.site_id = self._process_ids(id)
       else:
           raise ValueError("Either 'id' or 'mask' parameter must be provided")

       # Load all data
       self.__load_all_data()

       # Export if output specified
       if self.output:
           self._export_data()

   def _load_geographic_libraries(self):
       """Import optional vector-geometry dependencies on demand.

       Returns
       -------
       tuple
           ``(geopandas_module, shapely.geometry.Point)``.
       """
       try:
           import geopandas as gpd
           from shapely.geometry import Point
           return gpd, Point
       except ImportError:
           raise ImportError("Geographic functionality requires geopandas and shapely. Install with: pip install geopandas")

   def _load_raster_libraries(self):
       """Import optional raster dependencies on demand.

       Returns
       -------
       tuple
           ``(rasterio_module, rasterio.features.shapes, shapely.shape)``.
       """
       try:
           import rasterio
           from rasterio.features import shapes
           from shapely.geometry import shape
           return rasterio, shapes, shape
       except ImportError:
           raise ImportError("Raster functionality requires rasterio. Install with: pip install rasterio")

   def _is_raster_file(self, file_path):
       """Return ``True`` when the mask path looks like a raster dataset."""
       raster_extensions = {'.tif', '.tiff', '.img', '.nc', '.grd', '.asc', '.bil', '.hdr'}
       return Path(file_path).suffix.lower() in raster_extensions

   def _get_stations_from_mask(self, mask_path):
       """Select stations located inside a mask geometry.

       The method dispatches station filtering according to ``source_mode``:
       API-based station catalogue lookup or local station catalogue lookup.
       """
       print(f"Loading geographic mask from: {mask_path}")
       mask_gdf = self._load_mask_geometry(mask_path)
       if self.source_mode == "api":
           return self._filter_stations_with_geometry_api(mask_gdf)
       if self.source_mode == "local":
           return self._filter_stations_with_geometry_local(mask_gdf)
       raise ValueError(f"Unsupported source_mode: {self.source_mode}")

   def _load_mask_geometry(self, mask_path):
       """Load mask geometry from vector or raster path in EPSG:4326."""
       if self._is_raster_file(mask_path):
           return self._load_mask_from_raster(mask_path)
       return self._load_mask_from_vector(mask_path)

   def _load_mask_from_vector(self, mask_path):
       """Read a vector mask and reproject it to WGS84 (EPSG:4326)."""
       gpd, Point = self._load_geographic_libraries()

       try:
           # Load and reproject mask
           mask_gdf = gpd.read_file(mask_path)
           if mask_gdf.crs != 'EPSG:4326':
               mask_gdf = mask_gdf.to_crs('EPSG:4326')

           return mask_gdf

       except Exception as e:
           raise ValueError(f"Failed to load vector file {mask_path}: {e}")

   def _load_mask_from_raster(self, mask_path):
       """Convert a raster mask to polygons in WGS84 (EPSG:4326).

       Non-zero and non-nodata pixels are vectorized, dissolved into one
       geometry layer, then returned as a GeoDataFrame.
       """
       rasterio, shapes, shape = self._load_raster_libraries()
       gpd, Point = self._load_geographic_libraries()

       try:
           # Read raster
           with rasterio.open(mask_path) as src:
               print(f"Raster info: {src.width}x{src.height}, CRS: {src.crs}")

               # Read the data
               data = src.read(1)  # Read first band
               transform = src.transform
               crs = src.crs

               # Create mask for non-zero/non-null values
               # Adjust this condition based on your raster values
               mask = (data != 0) & (~pd.isna(data)) & (data != src.nodata)

               if not mask.any():
                   raise ValueError("No valid (non-zero) pixels found in raster")

               print(f"Found {mask.sum()} valid pixels in raster")

               # Convert raster to vector polygons
               geoms = []
               for geom, value in shapes(data, mask=mask, transform=transform):
                   geoms.append(shape(geom))

               if not geoms:
                   raise ValueError("No geometries could be extracted from raster")

               # Create GeoDataFrame
               mask_gdf = gpd.GeoDataFrame(geometry=geoms, crs=crs)

               # Reproject to WGS84 if needed
               if mask_gdf.crs != 'EPSG:4326':
                   mask_gdf = mask_gdf.to_crs('EPSG:4326')

               # Dissolve all geometries into one
               mask_gdf = mask_gdf.dissolve()

               print(f"Created mask geometry with {len(mask_gdf)} polygon(s)")

               return mask_gdf

       except Exception as e:
           raise ValueError(f"Failed to process raster file {mask_path}: {e}")

   def _filter_stations_with_geometry_api(self, mask_gdf):
       """Filter Hub'Eau stations intersecting the provided mask geometry.

       A first query uses the mask bounding box; a spatial join then refines
       matches to the actual mask polygon(s).
       """
       gpd, Point = self._load_geographic_libraries()

       # Get bounding box
       bounds = mask_gdf.total_bounds  # [minx, miny, maxx, maxy]

       print(f"Searching stations in bounding box: {bounds}")

       # Query stations within bounding box
       url = f"{API_BASE_URL}hydrometrie/referentiel/stations"
       params = {
           'bbox': f"{bounds[0]},{bounds[1]},{bounds[2]},{bounds[3]}",
           'size': 10000,
           'format': 'json'
       }

       response = requests.get(url, params=params)
       if not self.__check_status_code(response.status_code):
           raise RuntimeError("Failed to retrieve stations from API")

       stations_data = response.json().get('data', [])

       if not stations_data:
           raise ValueError("No stations found in the specified geographic area")

       print(f"Found {len(stations_data)} stations in bounding box")

       # Create GeoDataFrame from stations
       stations_gdf = gpd.GeoDataFrame(
           stations_data,
           geometry=[Point(s['longitude_station'], s['latitude_station']) for s in stations_data],
           crs='EPSG:4326'
       )

       # Filter stations within mask geometry (not just bounding box)
       try:
           stations_in_mask = gpd.sjoin(stations_gdf, mask_gdf, how='inner', predicate='within')
       except Exception as e:
           print(f"Warning: Spatial join failed ({e}), using intersection instead")
           stations_in_mask = gpd.sjoin(stations_gdf, mask_gdf, how='inner', predicate='intersects')

       if stations_in_mask.empty:
           # Try with a buffer if no stations found
           print("No stations found within exact geometry, trying with small buffer...")
           mask_buffered = mask_gdf.copy()
           mask_buffered.geometry = mask_buffered.geometry.buffer(0.001)  # ~100m buffer

           try:
               stations_in_mask = gpd.sjoin(stations_gdf, mask_buffered, how='inner', predicate='within')
           except Exception:
               stations_in_mask = gpd.sjoin(stations_gdf, mask_buffered, how='inner', predicate='intersects')

           if stations_in_mask.empty:
               raise ValueError("No stations found within the specified geographic mask (even with buffer)")

       station_ids = stations_in_mask['code_station'].tolist()
       site_ids = [sid[:8] for sid in station_ids]

       print(f"Found {len(station_ids)} stations within geographic mask")

       return station_ids, site_ids

   def _load_local_station_catalog(self):
       """
       Load local station catalogue (station_id, lon, lat) for mask filtering.

       Requires local full export tables:
       - stations_info.csv (preferred), or
       - metadata.csv with x_wgs84/y_wgs84 columns.
       """
       if self.local_data_dir is None:
           raise ValueError("local_data_dir is required for local station catalogue.")

       stations_info_path = self.local_data_dir / "stations_info.csv"
       metadata_path = self.local_data_dir / "metadata.csv"

       if stations_info_path.exists():
           df = pd.read_csv(stations_info_path)
           station_col = "station_id" if "station_id" in df.columns else "code_station"
           lon_col = "longitude_station"
           lat_col = "latitude_station"
           if station_col not in df.columns or lon_col not in df.columns or lat_col not in df.columns:
               raise ValueError(
                   "stations_info.csv must contain station id and longitude/latitude columns."
               )
           out = df[[station_col, lon_col, lat_col]].copy()
           out.columns = ["station_id", "lon", "lat"]
       elif metadata_path.exists():
           df = pd.read_csv(metadata_path)
           if "station_id" not in df.columns or "x_wgs84" not in df.columns or "y_wgs84" not in df.columns:
               raise ValueError(
                   "metadata.csv must contain station_id, x_wgs84 and y_wgs84 columns."
               )
           out = df[["station_id", "x_wgs84", "y_wgs84"]].copy()
           out.columns = ["station_id", "lon", "lat"]
       else:
           raise FileNotFoundError(
               "Local mask mode requires stations_info.csv or metadata.csv in local_data_dir. "
               f"Missing in: {self.local_data_dir}"
           )

       out["station_id"] = out["station_id"].astype(str)
       out["lon"] = pd.to_numeric(out["lon"], errors="coerce")
       out["lat"] = pd.to_numeric(out["lat"], errors="coerce")
       out = out.dropna(subset=["lon", "lat"])
       if out.empty:
           raise ValueError("No valid station coordinates found in local catalogue.")
       return out

   def _filter_stations_with_geometry_local(self, mask_gdf):
       """Filter locally available stations intersecting the mask geometry."""
       gpd, Point = self._load_geographic_libraries()
       station_catalog = self._load_local_station_catalog()

       stations_gdf = gpd.GeoDataFrame(
           station_catalog.copy(),
           geometry=[Point(xy) for xy in zip(station_catalog["lon"], station_catalog["lat"])],
           crs="EPSG:4326",
       )

       try:
           stations_in_mask = gpd.sjoin(stations_gdf, mask_gdf, how='inner', predicate='within')
       except Exception:
           stations_in_mask = gpd.sjoin(stations_gdf, mask_gdf, how='inner', predicate='intersects')

       if stations_in_mask.empty:
           raise ValueError("No local stations found within the specified geographic mask.")

       station_ids = sorted(stations_in_mask["station_id"].astype(str).unique().tolist())
       site_ids = [sid[:8] for sid in station_ids]
       print(f"Found {len(station_ids)} local stations within geographic mask")
       return station_ids, site_ids

   def _process_ids(self, id):
       """Normalize station/site identifiers into parallel station/site lists.

       Input ids with 8 characters are treated as site ids and expanded to the
       default ``XX...01`` station id convention.
       """
       if isinstance(id, str):
           id = [id]

       station_id = []
       site_id = []

       for id_val in id:
           if len(id_val) == 10:
               station_id.append(id_val)
               site_id.append(id_val[:-2])
           elif len(id_val) == 8:
               station_id.append(id_val + "01")
               site_id.append(id_val)
               print(f"{id_val} is a site ID, by default, the station ID is {station_id[-1]}")
           else:
               raise ValueError(f"Invalid ID length: {id_val}. Expected 8 or 10 characters.")

       return station_id, site_id

   def __load_all_data(self):
       """Dispatch loading flow according to ``source_mode``."""
       if self.source_mode == "api":
           self._load_all_data_from_api()
       elif self.source_mode == "local":
           self._load_all_data_from_local()
       else:
           raise ValueError(f"Unsupported source_mode: {self.source_mode}")

   def _load_all_data_from_api(self):
       """Load all selected stations from Hub'Eau API."""
       loader = ApiStationLoader(
           variable=self.variable,
           display=self.display,
           date_start=self.date_start,
           date_end=self.date_end,
       )
       result = loader.load(
           station_ids=self.station_id,
           site_ids=self.site_id,
       )
       self._apply_load_result(result)
       self._print_load_summary(
           header="DATA LOADING SUMMARY",
           stations_processed=len(self.stations_info),
       )

   def _load_all_data_from_local(self):
       """Load all selected stations from local exported CSV files."""
       if self.local_data_dir is None:
           raise ValueError("local_data_dir is required when source_mode='local'.")
       loader = LocalStationLoader(
           variable=self.variable,
           local_data_dir=self.local_data_dir,
           date_start=self.date_start,
           date_end=self.date_end,
       )
       result = loader.load(station_ids=self.station_id)
       self._apply_load_result(result)
       self._print_load_summary(
           header="LOCAL DATA LOADING SUMMARY",
           stations_requested=len(self.station_id),
           stations_loaded=self.data["station_id"].nunique() if not self.data.empty else 0,
       )

   def _apply_load_result(self, result: Any):
       """Copy normalized loader payload into instance attributes."""
       self.stations_info = result.stations_info
       self.sites_info = result.sites_info
       self.metadata = result.metadata
       self.data = result.data
       self.missing_data_summary = result.missing_data_summary
       self.stations = result.stations

   def _print_load_summary(self, *, header: str, **extra_values):
       """Print a standardized loading summary block."""
       print(f"\n=== {header} ===")
       for key, value in extra_values.items():
           label = key.replace("_", " ").capitalize()
           print(f"{label}: {value}")
       print(f"Total observations: {len(self.data)}")
       if not self.missing_data_summary.empty and "missing_days" in self.missing_data_summary.columns:
           total_missing = self.missing_data_summary["missing_days"].sum()
           print(f"Total missing days across all stations: {total_missing}")


   def __check_status_code(self, status_code) -> bool:
       """Validate Hub'Eau HTTP status code and print readable diagnostics."""
       message = STATUS_MESSAGES.get(status_code, f"Unknown error {status_code}: Check the API documentation")
       is_success = status_code in (200, 206)

       if not is_success:
           print(f"Error {status_code}: {message}")

       return is_success

   def get_station(self, station_id: Union[str, int]) -> Station:
       """Return a loaded :class:`Station` for one station id.

       Raises
       ------
       KeyError
           If the station is not available in ``self.stations``.
       """
       sid = str(station_id)
       if sid not in self.stations:
           available = ", ".join(sorted(self.stations.keys())) if self.stations else "none"
           raise KeyError(f"Station {sid} not found in loaded stations. Available: {available}")
       return self.stations[sid]

   def _export_data(self):
       """Export loaded dataframes and station CSV files to disk.

       Supports "lite" mode (station files only) and "full" mode (station
       files + metadata/reference/diagnostic tables).
       """
       if not self.output:
           return

       # Determine export mode
       if isinstance(self.output, list) and len(self.output) == 2 and self.output[1].lower() == "full":
           export_path = Path(self.output[0])
           full_mode = True
       else:
           export_path = Path(self.output)
           full_mode = False

       export_path.mkdir(parents=True, exist_ok=True)

       print(f"\n=== EXPORTING DATA ===")
       print(f"Export mode: {'Full' if full_mode else 'Lite'}")
       print(f"Export path: {export_path}")
       metadata_available = (not self.metadata.empty and "station_id" in self.metadata.columns)

       # Export individual station data
       if not self.data.empty:
           for station_id in self.data['station_id'].unique():
               station_data = self.data[self.data['station_id'] == station_id].copy()

               # Get station name for filename
               filename = f"{station_id}.csv"
               if metadata_available:
                   station_meta = self.metadata[self.metadata['station_id'].astype(str) == str(station_id)]
                   if not station_meta.empty:
                       station_name = station_meta.iloc[0].get('station_name', station_id)
                       # Clean filename
                       safe_name = "".join(c for c in str(station_name) if c.isalnum() or c in (' ', '-', '_')).rstrip()
                       filename = f"{station_id}_{safe_name}.csv"

               # Remove station_id column for export
               export_data = station_data.drop('station_id', axis=1, errors='ignore')
               export_data.to_csv(export_path / filename, index=False)
               print(f"  Exported: {filename}")

       # Export summary tables
       if full_mode:
           if not self.metadata.empty:
               self.metadata.to_csv(export_path / "metadata.csv", index=False)
               print("  Exported: metadata.csv")

           if not self.stations_info.empty:
               self.stations_info.to_csv(export_path / "stations_info.csv", index=False)
               print("  Exported: stations_info.csv")

           if not self.sites_info.empty:
               self.sites_info.to_csv(export_path / "sites_info.csv", index=False)
               print("  Exported: sites_info.csv")

           if not self.missing_data_summary.empty:
               self.missing_data_summary.to_csv(export_path / "missing_data_summary.csv", index=False)
               print("  Exported: missing_data_summary.csv")

       # Create table of contents
       self._create_table_of_contents(export_path, full_mode)

   def _create_table_of_contents(self, export_path, full_mode):
       """Write ``README.txt`` summarizing exported content."""
       toc_content = []
       toc_content.append("# Hub'Eau Hydrometry Data Export")
       toc_content.append(f"# Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
       toc_content.append(f"# Variable: {self.variable} - {AVAILABLE_VARIABLES[self.variable]}")
       toc_content.append(f"# Export mode: {'Full' if full_mode else 'Lite'}")
       toc_content.append("")

       if self.date_start and self.date_end:
           toc_content.append(f"# Date range: {self.date_start.strftime('%Y-%m-%d')} to {self.date_end.strftime('%Y-%m-%d')}")
           toc_content.append("")

       # Station files
       toc_content.append("# Station Data Files:")
       metadata_available = (not self.metadata.empty and "station_id" in self.metadata.columns)
       if not self.data.empty:
           for station_id in self.data['station_id'].unique():
               filename = f"{station_id}.csv"
               if metadata_available:
                   station_meta = self.metadata[self.metadata['station_id'].astype(str) == str(station_id)]
                   if not station_meta.empty:
                       station_name = station_meta.iloc[0].get('station_name', 'Unknown')
                       safe_name = "".join(c for c in str(station_name) if c.isalnum() or c in (' ', '-', '_')).rstrip()
                       filename = f"{station_id}_{safe_name}.csv"

               # Get data stats
               station_data = self.data[self.data['station_id'] == station_id]
               record_count = len(station_data)
               if not station_data.empty and "date_obs_elab" in station_data.columns:
                   date_range = f"{station_data['date_obs_elab'].min()} to {station_data['date_obs_elab'].max()}"
               else:
                   date_range = "No data"

               toc_content.append(f"# {filename}: {record_count} records, {date_range}")

       if full_mode:
           toc_content.append("")
           toc_content.append("# Metadata Files:")
           toc_content.append("# metadata.csv: Station metadata and characteristics")
           toc_content.append("# stations_info.csv: Detailed station reference information")
           toc_content.append("# sites_info.csv: Site reference information")
           toc_content.append("# missing_data_summary.csv: Data completeness analysis")

       # Write table of contents
       with open(export_path / "README.txt", 'w', encoding='utf-8') as f:
           f.write('\n'.join(toc_content))

       print("  Exported: README.txt")

   def get_missing_data_summary(self):
       """Return the missing-data summary dataframe for loaded stations."""
       return self.missing_data_summary

   def plot_station(
       self,
       station_id: Optional[Union[str, List[str]]] = None,
       output_path: Optional[Union[str, Path]] = None,
       show: bool = True,
       figsize: tuple = (12, 4),
   ):
       """
       Plot loaded hydrometric station series.

       Parameters
       ----------
       station_id : str or list of str, optional
           Restrict plot to one or multiple station IDs. If None, plot all
           loaded stations.
       output_path : str or Path, optional
           If provided, save the figure to this path (PNG, PDF, ...).
       show : bool, default True
           Whether to display the figure interactively.
       figsize : tuple, default (12, 4)
           Matplotlib figure size.

       Returns
       -------
       (fig, ax)
           Matplotlib figure and axes objects.
       """
       if not self.stations:
           raise ValueError("No loaded station data available to plot.")

       # Single station request: delegate to station-level class.
       if isinstance(station_id, str):
           return self.get_station(station_id).plot(
               output_path=output_path,
               show=show,
               block=True,
               figsize=figsize,
           )

       if station_id is None:
           station_order = sorted(self.stations.keys())
       else:
           station_order = [str(sid) for sid in station_id]
           missing = [sid for sid in station_order if sid not in self.stations]
           if missing:
               raise ValueError(f"No station data found for station_id={missing}.")
           if len(station_order) == 1:
               return self.get_station(station_order[0]).plot(
                   output_path=output_path,
                   show=show,
                   block=True,
                   figsize=figsize,
               )

       try:
           import matplotlib.pyplot as plt
       except ImportError as exc:
           raise ImportError(
               "Matplotlib is required to plot station data. "
               "Install with: pip install matplotlib"
           ) from exc

       fig, ax = plt.subplots(1, 1, figsize=figsize, dpi=140)
       plotted_count = 0

       for sid in station_order:
           station_obj = self.get_station(sid)
           sdf = station_obj.data.copy()
           if "date_obs_elab" not in sdf.columns or "resultat_obs_elab" not in sdf.columns:
               continue
           sdf["date_obs_elab"] = pd.to_datetime(sdf["date_obs_elab"], errors="coerce")
           sdf["resultat_obs_elab"] = pd.to_numeric(sdf["resultat_obs_elab"], errors="coerce")
           sdf = sdf.dropna(subset=["date_obs_elab", "resultat_obs_elab"]).sort_values("date_obs_elab")
           if sdf.empty:
               continue

           ax.plot(
               sdf["date_obs_elab"].to_numpy(),
               sdf["resultat_obs_elab"].to_numpy(dtype=float),
               linewidth=1.2,
               label=station_obj.build_label(),
           )
           plotted_count += 1

       if plotted_count == 0:
           raise ValueError("No valid station points available after cleaning.")

       y_label = "Observed value"
       if self.variable in ["QmnJ", "QmM", "QINM", "QINnJ", "QixM", "QIXnJ"]:
           y_label = "Discharge [m3/s]"
       elif self.variable in ["HIXM", "HIXnJ"]:
           y_label = "Water level [m]"

       ax.set_title(f"Loaded station series - {self.variable}")
       ax.set_xlabel("Date")
       ax.set_ylabel(y_label)
       ax.grid(True, alpha=0.3)

       if plotted_count > 1:
           ax.legend(loc="best", fontsize=8)

       fig.tight_layout()

       if output_path is not None:
           output_path = Path(output_path)
           output_path.parent.mkdir(parents=True, exist_ok=True)
           fig.savefig(output_path, bbox_inches="tight")
           print(f"Station figure exported to: {output_path}")

       backend = plt.get_backend().lower()
       if show:
           if "agg" in backend:
               print("Figure backend is non-interactive (Agg): closing figure without display.")
               plt.close(fig)
           else:
               plt.show(block=True)
       else:
           plt.close(fig)

       return fig, ax

   def get_completeness_report(self):
       """Print a human-readable completeness report across stations."""
       if self.missing_data_summary.empty:
           print("No missing data analysis available.")
           return

       print("\n=== DATA COMPLETENESS REPORT ===")
       total_stations = len(self.missing_data_summary)

       # Overall statistics
       avg_completeness = self.missing_data_summary['completeness_pct'].mean()
       total_missing = self.missing_data_summary['missing_days'].sum()
       total_expected = self.missing_data_summary['expected_days'].sum()

       print(f"Total stations: {total_stations}")
       print(f"Average completeness: {avg_completeness:.1f}%")
       print(f"Total missing days: {total_missing:,} out of {total_expected:,} expected")

       # Completeness categories
       complete = (self.missing_data_summary['completeness_pct'] == 100).sum()
       mostly_complete = ((self.missing_data_summary['completeness_pct'] >= 90) &
                         (self.missing_data_summary['completeness_pct'] < 100)).sum()
       partial = ((self.missing_data_summary['completeness_pct'] >= 50) &
                 (self.missing_data_summary['completeness_pct'] < 90)).sum()
       incomplete = (self.missing_data_summary['completeness_pct'] < 50).sum()

       print(f"\nCompleteness breakdown:")
       print(f"  Complete (100%): {complete} stations")
       print(f"  Mostly complete (90-99%): {mostly_complete} stations")
       print(f"  Partial (50-89%): {partial} stations")
       print(f"  Incomplete (<50%): {incomplete} stations")

       # Worst performers
       if incomplete > 0 or partial > 0:
           print(f"\nStations with most missing data:")
           worst = self.missing_data_summary.nsmallest(5, 'completeness_pct')[['station_id', 'completeness_pct', 'missing_days']]
           print(worst.to_string(index=False))

