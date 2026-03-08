"""
File Name: station_set.py
Author: Bastien Boivin
Email: bastien.boivin@univ-rennes.fr | @proton.me
Creation Date: 2025-04-08
Description: Station set wrapper for Hub'Eau hydrometry API and local files.
"""
#%% Import libraries
import pandas as pd
from datetime import datetime
from typing import Dict, List, Union, Optional, Mapping, Any
from pathlib import Path

try:
   from ..common.base_station_set import BaseStationSet
   from .discovery import (
       discover_station_ids as discover_station_ids_in_area,
       normalize_station_ids,
       select_station_ids_from_mask,
   )
   from .station import Station
   from .loaders_api import ApiStationLoader
   from .loaders_local import LocalStationLoader
   from hydromodpy.units import parse_length_to_m
except ImportError:
   import sys
   _manager_root = Path(__file__).resolve().parents[1]
   _this_dir = Path(__file__).resolve().parent
   _repo_root = Path(__file__).resolve().parents[3]
   for _path in (str(_manager_root), str(_this_dir), str(_repo_root)):
       if _path not in sys.path:
           sys.path.insert(0, _path)
   from common.base_station_set import BaseStationSet
   from discovery import (
       discover_station_ids as discover_station_ids_in_area,
       normalize_station_ids,
       select_station_ids_from_mask,
   )
   from station import Station
   from loaders_api import ApiStationLoader
   from loaders_local import LocalStationLoader
   from hydromodpy.units import parse_length_to_m

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
class StationSet(BaseStationSet):
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
       fallback_search_radius_m = selection_cfg.get("fallback_search_radius")
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
           fallback_search_radius_m=fallback_search_radius_m,
       )

   @classmethod
   def discover_station_ids(
       cls,
       *,
       bbox: Optional[tuple[float, float, float, float]] = None,
       mask_path: Optional[Union[str, Path]] = None,
       center_point: Optional[tuple[float, float]] = None,
       fallback_search_radius_m: Optional[Any] = None,
       fallback_search_radius_km: Optional[Any] = None,
       require_observations: bool = False,
       date_start: Optional[str] = None,
       date_end: Optional[str] = None,
       max_ids: Optional[int] = 20,
       timeout: int = 30,
   ) -> List[str]:
       """Discover valid Hub'Eau hydrometric station identifiers in a geographic area."""
       if fallback_search_radius_m is not None and fallback_search_radius_km is not None:
           raise ValueError("Use either fallback_search_radius_m or fallback_search_radius_km, not both.")
       if fallback_search_radius_m is None and fallback_search_radius_km is None:
           fallback_search_radius_km = 10.0
       if fallback_search_radius_m is None:
           radius_m = parse_length_to_m(
               fallback_search_radius_km,
               default_unit="km",
               label="fallback_search_radius_km",
           )
       else:
           radius_m = parse_length_to_m(
               fallback_search_radius_m,
               default_unit="m",
               label="fallback_search_radius_m",
           )
       return discover_station_ids_in_area(
           bbox=bbox,
           mask_path=mask_path,
           center_point=center_point,
           fallback_search_radius_m=radius_m,
           require_observations=require_observations,
           date_start=date_start,
           date_end=date_end,
           max_ids=max_ids,
           timeout=timeout,
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
                fallback_search_radius_m: Optional[Any] = None,
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
       if fallback_search_radius_m is None:
           self.fallback_search_radius_m = float(
               parse_length_to_m(10.0, default_unit="km", label="fallback_search_radius_default")
           )
       else:
           self.fallback_search_radius_m = float(
               parse_length_to_m(
                   fallback_search_radius_m,
                   default_unit="m",
                   label="fallback_search_radius_m",
               )
           )
       if self.fallback_search_radius_m < 0.0:
           raise ValueError("fallback_search_radius_m must be >= 0.")

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
           self.station_id, self.site_id = self._get_stations_from_mask(
               mask,
               fallback_search_radius_m=self.fallback_search_radius_m,
           )
       elif id is not None:
           self.station_id, self.site_id = self._process_ids(id)
       else:
           raise ValueError("Either 'id' or 'mask' parameter must be provided")

       # Load all data
       self.__load_all_data()

       # Export if output specified
       if self.output:
           self._export_data()

   def _get_stations_from_mask(
       self,
       mask_path,
       *,
       fallback_search_radius_m: Optional[float] = None,
   ):
       """Select stations located inside a mask geometry.

       The method dispatches station filtering according to ``source_mode``:
       API-based station catalogue lookup or local station catalogue lookup.
       """
       radius_m = (
           self.fallback_search_radius_m
           if fallback_search_radius_m is None
           else float(fallback_search_radius_m)
       )
       try:
           return select_station_ids_from_mask(
               mask_path=mask_path,
               source_mode=self.source_mode,
               local_data_dir=self.local_data_dir,
               fallback_search_radius_m=radius_m,
           )
       except TypeError as exc:
           # Backward-compatibility path for call sites/tests still exposing
           # the legacy kilometer keyword.
           if "unexpected keyword argument 'fallback_search_radius_m'" not in str(exc):
               raise
           return select_station_ids_from_mask(
               mask_path=mask_path,
               source_mode=self.source_mode,
               local_data_dir=self.local_data_dir,
               fallback_search_radius_km=float(radius_m) / 1000.0,
           )

   def _process_ids(self, id):
       """Normalize station/site identifiers into parallel station/site lists.

       Input ids with 8 characters are treated as site ids and expanded to the
       default ``XX...01`` station id convention.
       """
       return normalize_station_ids(id)

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
       super()._apply_load_result(result)

   def _print_load_summary(self, *, header: str, **extra_values):
       """Print a standardized loading summary block."""
       super()._print_load_summary(header=header, **extra_values)
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

   def _infer_frequency(self, data: pd.DataFrame) -> str:
       """Infer data frequency from timestamp differences.

       Parameters
       ----------
       data : pd.DataFrame
           DataFrame with 'timestamp' column (or similar date index)

       Returns
       -------
       str
           Frequency code: 'D' (daily), 'M' (monthly), 'Y' (yearly), etc.
       """
       if data.empty:
           return "U"  # Unknown
       
       # Try to find timestamp column or index
       date_col = None
       if 'timestamp' in data.columns:
           date_col = 'timestamp'
       elif 'date' in data.columns:
           date_col = 'date'
       elif hasattr(data.index, 'name') and 'date' in str(data.index.name).lower():
           date_col = data.index
       else:
           # Try first datetime column
           for col in data.columns:
               if pd.api.types.is_datetime64_any_dtype(data[col]):
                   date_col = col
                   break
       
       if date_col is None:
           return "U"  # Unknown
       
       # Get dates
       if isinstance(date_col, str):
           dates = pd.to_datetime(data[date_col]).sort_values()
       else:
           dates = pd.to_datetime(date_col).sort_values()
       
       if len(dates) < 2:
           return "U"
       
       # Calculate median interval
       deltas = dates.diff().dropna()
       if len(deltas) == 0:
           return "U"
       
       median_delta = deltas.median()
       days = median_delta.days
       
       # Map intervals to frequency codes
       if days < 2:
           return "D"  # Daily
       elif 20 <= days <= 35:
           return "ME"  # Monthly
       elif 80 <= days <= 100:
           return "Q"  # Quarterly
       elif 350 <= days <= 370:
           return "YE"  # Yearly
       else:
           return "U"  # Unknown

   def _build_standardized_filename(self, station_id: str, station_data: pd.DataFrame) -> str:
       """Build standardized filename: hydrometry_{nomapi}_{id}_{startdate}_{enddate}_{freq}.csv

       Parameters
       ----------
       station_id : str
           Station identifier
       station_data : pd.DataFrame
           Station data with timestamps

       Returns
       -------
       str
           Standardized CSV filename
       """
       # Determine API name
       api_name = "HUBEAU" if self.source_mode == "api" else "custom"
       
       # Get frequency
       freq = self._infer_frequency(station_data)
       
       # Get date range from data
       date_col = None
       if 'timestamp' in station_data.columns:
           date_col = 'timestamp'
       elif 'date' in station_data.columns:
           date_col = 'date'
       else:
           # Try first datetime column
           for col in station_data.columns:
               if pd.api.types.is_datetime64_any_dtype(station_data[col]):
                   date_col = col
                   break
       
       if date_col is not None:
           dates = pd.to_datetime(station_data[date_col])
           start_date = dates.min().strftime("%Y%m%d")
           end_date = dates.max().strftime("%Y%m%d")
       else:
           start_date = "00000000"
           end_date = "00000000"
       
       # Make station_id filesystem-safe by replacing slash and backslash with underscore
       safe_id = str(station_id).replace("/", "_").replace("\\", "_")
       
       # Build filename
       filename = f"hydrometry_{api_name}_{safe_id}_{start_date}_{end_date}_{freq}.csv"
       return filename

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
       print(f"Export path: {export_path.resolve()}")  # Show absolute path
       metadata_available = (not self.metadata.empty and "station_id" in self.metadata.columns)

       # Export individual station data
       if not self.data.empty:
           for station_id in self.data['station_id'].unique():
               station_data = self.data[self.data['station_id'] == station_id].copy()

               # Use standardized filename format
               filename = self._build_standardized_filename(station_id, station_data)

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

