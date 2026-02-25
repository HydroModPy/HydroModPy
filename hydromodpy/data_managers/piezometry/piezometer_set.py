"""
File Name: piezometer_set.py
Description: Piezometer set wrapper for Hub'Eau piezometry API and local files.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Union

import pandas as pd
import requests

try:
    from ..common.base_station_set import BaseStationSet
    from ..common.utils import safe_file_token
    from .piezometer import Piezometer
    from .loaders_api import ApiPiezometerLoader
    from .loaders_local import LocalPiezometerLoader
except ImportError:
    import sys

    _manager_root = Path(__file__).resolve().parents[1]
    _this_dir = Path(__file__).resolve().parent
    for _path in (str(_manager_root), str(_this_dir)):
        if _path not in sys.path:
            sys.path.insert(0, _path)
    from common.base_station_set import BaseStationSet
    from common.utils import safe_file_token
    from piezometer import Piezometer
    from loaders_api import ApiPiezometerLoader
    from loaders_local import LocalPiezometerLoader


API_BASE_URL = "https://hubeau.eaufrance.fr/api/v1/niveaux_nappes/"

AVAILABLE_MEASUREMENTS = {
    "level": "Groundwater level in meters",
    "depth": "Groundwater depth in meters",
    "both": "Groundwater level and depth",
}

STATUS_MESSAGES = {
    200: "Success: All results present in the response",
    206: "Partial content: Some results may be missing",
    400: "Bad request: Check your request parameters",
    401: "Unauthorized: Check your credentials",
    403: "Forbidden: Check your permissions",
    404: "Not found: Check your URL",
    500: "Internal server error: Try again later",
}


class PiezometerSet(BaseStationSet):
    """Container orchestrating multi-station piezometric series."""

    @classmethod
    def from_toml(cls, config_path: Union[str, Path]):
        """Build a :class:`PiezometerSet` from a TOML configuration file."""
        try:
            from .piezometry_config import load_piezometry_toml
        except ImportError:
            from piezometry_config import load_piezometry_toml

        cfg = load_piezometry_toml(config_path)
        return cls.from_config(cfg)

    @classmethod
    def from_config(cls, config_data: Mapping[str, Any]):
        """Build a :class:`PiezometerSet` from normalized config sections."""
        piezometry_cfg = dict(config_data["piezometry"])
        source_cfg = dict(config_data["source"])
        selection_cfg = dict(config_data["selection"])
        output_cfg = dict(config_data["output"])

        piezometer_ids = None
        mask_path = None
        if selection_cfg["mode"] == "stations":
            piezometer_ids = selection_cfg["piezometer_ids"]
        else:
            mask_path = selection_cfg["mask_path"]

        output_value = None
        if output_cfg["enabled"]:
            if output_cfg["export_mode"] == "full":
                output_value = [output_cfg["path"], "full"]
            else:
                output_value = output_cfg["path"]

        return cls(
            measurement=piezometry_cfg["measurement"],
            id=piezometer_ids,
            mask=mask_path,
            display=piezometry_cfg["display"],
            date_start=piezometry_cfg.get("date_start"),
            date_end=piezometry_cfg.get("date_end"),
            output=output_value,
            source_mode=source_cfg["mode"],
            local_data_dir=source_cfg.get("local_data_dir"),
        )

    @classmethod
    def discover_piezometer_ids(
        cls,
        *,
        bbox: Optional[tuple[float, float, float, float]] = None,
        mask_path: Optional[Union[str, Path]] = None,
        require_observations: bool = False,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        max_ids: int = 20,
        timeout: int = 30,
    ) -> List[str]:
        """
        Discover valid Hub'Eau piezometer identifiers in a geographic area.

        Parameters
        ----------
        bbox : tuple(float, float, float, float), optional
            Bounding box in EPSG:4326 as ``(minx, miny, maxx, maxy)``.
        mask_path : str or Path, optional
            Optional vector/raster mask. When provided, bounds are derived from
            this mask and candidates are spatially filtered by geometry.
        require_observations : bool, default False
            If True, keep only IDs with at least one chronicle observation in
            ``[date_start, date_end]``.
        date_start, date_end : str, optional
            Date filters used when ``require_observations=True``.
            Format: ``YYYY-MM-DD``.
        max_ids : int, default 20
            Maximum number of IDs returned.
        timeout : int, default 30
            HTTP timeout in seconds.

        Returns
        -------
        list[str]
            Discovered valid ``code_bss`` identifiers.
        """
        if max_ids < 1:
            raise ValueError("max_ids must be >= 1")

        helper = object.__new__(cls)
        mask_gdf = None
        if mask_path is not None:
            mask_gdf = helper._load_mask_geometry(mask_path)
            bounds = mask_gdf.total_bounds
            bbox = (float(bounds[0]), float(bounds[1]), float(bounds[2]), float(bounds[3]))

        if bbox is None:
            raise ValueError("Either bbox or mask_path must be provided.")

        try:
            minx, miny, maxx, maxy = [float(v) for v in bbox]
        except Exception as exc:
            raise ValueError("bbox must be a 4-float tuple: (minx, miny, maxx, maxy)") from exc
        if minx >= maxx or miny >= maxy:
            raise ValueError("Invalid bbox values: require minx < maxx and miny < maxy.")

        params = {
            "bbox": f"{minx},{miny},{maxx},{maxy}",
            "size": 10000,
            "format": "json",
        }
        try:
            response = requests.get(f"{API_BASE_URL}stations", params=params, timeout=timeout)
        except requests.exceptions.RequestException as exc:
            print(f"Warning: station discovery request failed: {exc}")
            return []
        if response.status_code not in (200, 206):
            message = STATUS_MESSAGES.get(response.status_code, "Unknown API error")
            print(f"Error {response.status_code}: {message}")
            return []

        station_rows = response.json().get("data", [])
        if not station_rows:
            return []

        if mask_gdf is not None:
            gpd, Point = helper._load_geographic_libraries()
            points = []
            valid_rows = []
            for row in station_rows:
                xy = cls._extract_wgs84_coordinates(row)
                if xy is None:
                    continue
                valid_rows.append(row)
                points.append(Point(float(xy[0]), float(xy[1])))

            if valid_rows:
                stations_gdf = gpd.GeoDataFrame(valid_rows, geometry=points, crs="EPSG:4326")
                try:
                    in_mask = gpd.sjoin(stations_gdf, mask_gdf, how="inner", predicate="within")
                except Exception:
                    in_mask = gpd.sjoin(stations_gdf, mask_gdf, how="inner", predicate="intersects")
                station_rows = in_mask.to_dict("records") if not in_mask.empty else []
            else:
                station_rows = []

        seen = set()
        candidate_ids: List[str] = []
        for row in station_rows:
            sid = str(row.get("code_bss", "")).strip()
            if sid and sid not in seen:
                seen.add(sid)
                candidate_ids.append(sid)

        if not require_observations:
            return candidate_ids[:max_ids]

        start = cls._normalize_api_date(date_start, default="1900-01-01")
        end = cls._normalize_api_date(date_end, default=datetime.now().strftime("%Y-%m-%d"))
        discovered: List[str] = []

        for sid in candidate_ids:
            chrono_params = {
                "code_bss": sid,
                "date_debut_mesure": start,
                "date_fin_mesure": end,
                "size": 1,
                "format": "json",
            }
            try:
                resp = requests.get(f"{API_BASE_URL}chroniques", params=chrono_params, timeout=timeout)
            except requests.exceptions.RequestException:
                continue
            if resp.status_code not in (200, 206):
                continue
            payload = resp.json()
            count = int(payload.get("count", 0) or 0)
            if count > 0:
                discovered.append(sid)
                if len(discovered) >= max_ids:
                    break

        return discovered

    def __init__(
        self,
        *,
        measurement: str = "both",
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
        Initialize PiezometerSet instance.

        Parameters
        ----------
        measurement : str, default "both"
            Measurement mode: "level", "depth", or "both".
        id : str or list of str, optional
            Piezometer ID(s) (Hub'Eau code_bss). Single string or list.
        mask : str or Path, optional
            Path to geographic mask file (.shp, .geojson, .tif...).
        display : bool, default False
            Whether to display raw JSON responses.
        date_start : str, optional
            Start date for filtering in format 'YYYY-MM-DD'.
        date_end : str, optional
            End date for filtering in format 'YYYY-MM-DD'.
        output : str or list, optional
            Output path for exports. If [path, "full"]: full mode.
        source_mode : str, default "api"
            Data source mode: "api" or "local".
        local_data_dir : str or Path, optional
            Directory containing local exported piezometry files used when
            source_mode="local".
        """
        if measurement not in AVAILABLE_MEASUREMENTS:
            available = ", ".join(AVAILABLE_MEASUREMENTS.keys())
            raise ValueError(f"Invalid measurement: {measurement}. Available: {available}")

        self.measurement = measurement
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

        self.stations_info = pd.DataFrame()
        self.data = pd.DataFrame()
        self.metadata = pd.DataFrame()
        self.missing_data_summary = pd.DataFrame()
        self.piezometers: Dict[str, Piezometer] = {}

        if mask is not None:
            self.piezometer_id = self._get_piezometers_from_mask(mask)
        elif id is not None:
            self.piezometer_id = self._process_ids(id)
        else:
            raise ValueError("Either 'id' or 'mask' parameter must be provided")

        self.__load_all_data()

        if self.output:
            self._export_data()

    def _load_geographic_libraries(self):
        """Import optional vector-geometry dependencies on demand."""
        return super()._load_geographic_libraries()

    def _load_raster_libraries(self):
        """Import optional raster dependencies on demand."""
        return super()._load_raster_libraries()

    @staticmethod
    def _is_raster_file(file_path):
        """Return ``True`` when the mask path looks like a raster dataset."""
        return BaseStationSet._is_raster_file(file_path)

    @staticmethod
    def _normalize_api_date(value: Optional[str], *, default: str) -> str:
        """Normalize date string to API ``YYYY-MM-DD`` format."""
        if value is None:
            return default
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            return default
        return parsed.strftime("%Y-%m-%d")

    @staticmethod
    def _extract_wgs84_coordinates(row: Mapping[str, Any]) -> Optional[tuple[float, float]]:
        """Extract WGS84 (lon, lat) from station payload, if available."""
        x = row.get("longitude_station")
        y = row.get("latitude_station")
        if x is None or y is None:
            geometry = row.get("geometry")
            if isinstance(geometry, Mapping):
                coords = geometry.get("coordinates")
                if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                    x = coords[0]
                    y = coords[1]
        try:
            if x is None or y is None:
                return None
            return float(x), float(y)
        except Exception:
            return None

    def _get_piezometers_from_mask(self, mask_path):
        """Select piezometers located inside a mask geometry."""
        print(f"Loading geographic mask from: {mask_path}")
        mask_gdf = self._load_mask_geometry(mask_path)
        if self.source_mode == "api":
            return self._filter_piezometers_with_geometry_api(mask_gdf)
        if self.source_mode == "local":
            return self._filter_piezometers_with_geometry_local(mask_gdf)
        raise ValueError(f"Unsupported source_mode: {self.source_mode}")

    def _load_mask_geometry(self, mask_path):
        """Load mask geometry from vector or raster path in EPSG:4326."""
        return super()._load_mask_geometry(mask_path)

    def _load_mask_from_vector(self, mask_path):
        """Read a vector mask and reproject it to WGS84 (EPSG:4326)."""
        return super()._load_mask_from_vector(mask_path)

    def _load_mask_from_raster(self, mask_path):
        """Convert a raster mask to polygons in WGS84 (EPSG:4326)."""
        return super()._load_mask_from_raster(mask_path)

    def _filter_piezometers_with_geometry_api(self, mask_gdf):
        """Filter API piezometers intersecting the provided mask geometry."""
        gpd, Point = self._load_geographic_libraries()

        bounds = mask_gdf.total_bounds
        params = {
            "bbox": f"{bounds[0]},{bounds[1]},{bounds[2]},{bounds[3]}",
            "size": 10000,
            "format": "json",
        }
        response = requests.get(f"{API_BASE_URL}stations", params=params, timeout=30)
        if not self.__check_status_code(response.status_code):
            raise RuntimeError("Failed to retrieve piezometers from API")

        stations_data = response.json().get("data", [])
        if not stations_data:
            raise ValueError("No piezometers found in the specified geographic area")

        points = []
        rows = []
        for row in stations_data:
            xy = self._extract_wgs84_coordinates(row)
            if xy is None:
                continue
            rows.append(row)
            points.append(Point(float(xy[0]), float(xy[1])))

        if not rows:
            raise ValueError("No georeferenced piezometers found in API response.")

        stations_gdf = gpd.GeoDataFrame(rows, geometry=points, crs="EPSG:4326")
        try:
            stations_in_mask = gpd.sjoin(stations_gdf, mask_gdf, how="inner", predicate="within")
        except Exception:
            stations_in_mask = gpd.sjoin(stations_gdf, mask_gdf, how="inner", predicate="intersects")

        if stations_in_mask.empty:
            raise ValueError("No piezometers found within the specified geographic mask.")

        ids = sorted(stations_in_mask["code_bss"].astype(str).unique().tolist())
        print(f"Found {len(ids)} piezometers within geographic mask")
        return ids

    def _load_local_station_catalog(self):
        """Load local piezometer catalogue (id, lon, lat) for mask filtering."""
        if self.local_data_dir is None:
            raise ValueError("local_data_dir is required for local station catalogue.")

        stations_info_path = self.local_data_dir / "stations_info.csv"
        metadata_path = self.local_data_dir / "metadata.csv"

        if stations_info_path.exists():
            df = pd.read_csv(stations_info_path)
            station_col = "piezometer_id" if "piezometer_id" in df.columns else "code_bss"
            lon_col = "longitude_station" if "longitude_station" in df.columns else "x_wgs84"
            lat_col = "latitude_station" if "latitude_station" in df.columns else "y_wgs84"
            if station_col not in df.columns or lon_col not in df.columns or lat_col not in df.columns:
                raise ValueError(
                    "stations_info.csv must contain piezometer id and longitude/latitude columns."
                )
            out = df[[station_col, lon_col, lat_col]].copy()
            out.columns = ["piezometer_id", "lon", "lat"]
        elif metadata_path.exists():
            df = pd.read_csv(metadata_path)
            station_col = "piezometer_id" if "piezometer_id" in df.columns else "code_bss"
            if station_col not in df.columns or "x_wgs84" not in df.columns or "y_wgs84" not in df.columns:
                raise ValueError(
                    "metadata.csv must contain piezometer_id (or code_bss), x_wgs84 and y_wgs84 columns."
                )
            out = df[[station_col, "x_wgs84", "y_wgs84"]].copy()
            out.columns = ["piezometer_id", "lon", "lat"]
        else:
            raise FileNotFoundError(
                "Local mask mode requires stations_info.csv or metadata.csv in local_data_dir. "
                f"Missing in: {self.local_data_dir}"
            )

        out["piezometer_id"] = out["piezometer_id"].astype(str)
        out["lon"] = pd.to_numeric(out["lon"], errors="coerce")
        out["lat"] = pd.to_numeric(out["lat"], errors="coerce")
        out = out.dropna(subset=["lon", "lat"])
        if out.empty:
            raise ValueError("No valid piezometer coordinates found in local catalogue.")
        return out

    def _filter_piezometers_with_geometry_local(self, mask_gdf):
        """Filter locally available piezometers intersecting the mask geometry."""
        gpd, Point = self._load_geographic_libraries()
        station_catalog = self._load_local_station_catalog()

        stations_gdf = gpd.GeoDataFrame(
            station_catalog.copy(),
            geometry=[Point(xy) for xy in zip(station_catalog["lon"], station_catalog["lat"])],
            crs="EPSG:4326",
        )

        try:
            stations_in_mask = gpd.sjoin(stations_gdf, mask_gdf, how="inner", predicate="within")
        except Exception:
            stations_in_mask = gpd.sjoin(stations_gdf, mask_gdf, how="inner", predicate="intersects")

        if stations_in_mask.empty:
            raise ValueError("No local piezometers found within the specified geographic mask.")

        ids = sorted(stations_in_mask["piezometer_id"].astype(str).unique().tolist())
        print(f"Found {len(ids)} local piezometers within geographic mask")
        return ids

    @staticmethod
    def _process_ids(id_values):
        """Normalize piezometer identifiers into a list of strings."""
        if isinstance(id_values, str):
            id_values = [id_values]
        normalized = [str(v).strip() for v in id_values]
        if any(not sid for sid in normalized):
            raise ValueError("Piezometer ids cannot contain empty values.")
        return normalized

    def __load_all_data(self):
        """Dispatch loading flow according to ``source_mode``."""
        if self.source_mode == "api":
            self._load_all_data_from_api()
        elif self.source_mode == "local":
            self._load_all_data_from_local()
        else:
            raise ValueError(f"Unsupported source_mode: {self.source_mode}")

    def _load_all_data_from_api(self):
        """Load all selected piezometers from Hub'Eau API."""
        loader = ApiPiezometerLoader(
            measurement=self.measurement,
            display=self.display,
            date_start=self.date_start,
            date_end=self.date_end,
        )
        result = loader.load(
            piezometer_ids=self.piezometer_id,
        )
        self._apply_load_result(result)
        self._print_load_summary(
            header="PIEZOMETRY DATA LOADING SUMMARY",
            stations_processed=len(self.stations_info),
        )

    def _load_all_data_from_local(self):
        """Load all selected piezometers from local exported CSV files."""
        if self.local_data_dir is None:
            raise ValueError("local_data_dir is required when source_mode='local'.")
        loader = LocalPiezometerLoader(
            measurement=self.measurement,
            local_data_dir=self.local_data_dir,
            date_start=self.date_start,
            date_end=self.date_end,
        )
        result = loader.load(piezometer_ids=self.piezometer_id)
        self._apply_load_result(result)
        self._print_load_summary(
            header="LOCAL PIEZOMETRY DATA LOADING SUMMARY",
            stations_requested=len(self.piezometer_id),
            stations_loaded=self.data["piezometer_id"].nunique() if not self.data.empty else 0,
        )

    def _apply_load_result(self, result: Any):
        """Copy normalized loader payload into instance attributes."""
        super()._apply_load_result(result)

    def _print_load_summary(self, *, header: str, **extra_values):
        """Print a standardized loading summary block."""
        super()._print_load_summary(
            header=header,
            missing_entity_label="piezometers",
            **extra_values,
        )

    def __check_status_code(self, status_code) -> bool:
        """Validate Hub'Eau HTTP status code and print readable diagnostics."""
        message = STATUS_MESSAGES.get(status_code, f"Unknown error {status_code}: Check the API documentation")
        is_success = status_code in (200, 206)
        if not is_success:
            print(f"Error {status_code}: {message}")
        return is_success

    def get_piezometer(self, piezometer_id: Union[str, int]) -> Piezometer:
        """Return a loaded :class:`Piezometer` for one piezometer id."""
        pid = str(piezometer_id)
        if pid not in self.piezometers:
            available = ", ".join(sorted(self.piezometers.keys())) if self.piezometers else "none"
            raise KeyError(f"Piezometer {pid} not found in loaded piezometers. Available: {available}")
        return self.piezometers[pid]

    @staticmethod
    def _safe_file_token(value: str) -> str:
        """Normalize values used in export filenames."""
        return safe_file_token(value)

    def _export_data(self):
        """Export loaded dataframes and piezometer CSV files to disk."""
        if not self.output:
            return

        if isinstance(self.output, list) and len(self.output) == 2 and self.output[1].lower() == "full":
            export_path = Path(self.output[0])
            full_mode = True
        else:
            export_path = Path(self.output)
            full_mode = False

        export_path.mkdir(parents=True, exist_ok=True)

        print("\n=== EXPORTING DATA ===")
        print(f"Export mode: {'Full' if full_mode else 'Lite'}")
        print(f"Export path: {export_path}")
        metadata_available = not self.metadata.empty and "piezometer_id" in self.metadata.columns

        if not self.data.empty:
            for piezometer_id in self.data["piezometer_id"].astype(str).unique():
                piezo_data = self.data[self.data["piezometer_id"].astype(str) == str(piezometer_id)].copy()
                safe_id = self._safe_file_token(piezometer_id)
                filename = f"{safe_id}.csv"
                if metadata_available:
                    station_meta = self.metadata[self.metadata["piezometer_id"].astype(str) == str(piezometer_id)]
                    if not station_meta.empty:
                        station_name = station_meta.iloc[0].get("station_name", piezometer_id)
                        safe_name = self._safe_file_token(station_name)
                        filename = f"{safe_id}_{safe_name}.csv"

                export_data = piezo_data.drop("piezometer_id", axis=1, errors="ignore")
                export_data.to_csv(export_path / filename, index=False)
                print(f"  Exported: {filename}")

        if full_mode:
            if not self.metadata.empty:
                self.metadata.to_csv(export_path / "metadata.csv", index=False)
                print("  Exported: metadata.csv")
            if not self.stations_info.empty:
                self.stations_info.to_csv(export_path / "stations_info.csv", index=False)
                print("  Exported: stations_info.csv")
            if not self.missing_data_summary.empty:
                self.missing_data_summary.to_csv(export_path / "missing_data_summary.csv", index=False)
                print("  Exported: missing_data_summary.csv")

        self._create_table_of_contents(export_path, full_mode)

    def _create_table_of_contents(self, export_path, full_mode):
        """Write ``README.txt`` summarizing exported content."""
        toc_content = []
        toc_content.append("# Hub'Eau Piezometry Data Export")
        toc_content.append(f"# Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        toc_content.append(f"# Measurement mode: {self.measurement} - {AVAILABLE_MEASUREMENTS[self.measurement]}")
        toc_content.append(f"# Export mode: {'Full' if full_mode else 'Lite'}")
        toc_content.append("")

        if self.date_start and self.date_end:
            toc_content.append(
                f"# Date range: {self.date_start.strftime('%Y-%m-%d')} to {self.date_end.strftime('%Y-%m-%d')}"
            )
            toc_content.append("")

        toc_content.append("# Piezometer Data Files:")
        metadata_available = not self.metadata.empty and "piezometer_id" in self.metadata.columns
        if not self.data.empty:
            for piezometer_id in self.data["piezometer_id"].astype(str).unique():
                safe_id = self._safe_file_token(piezometer_id)
                filename = f"{safe_id}.csv"
                if metadata_available:
                    station_meta = self.metadata[self.metadata["piezometer_id"].astype(str) == str(piezometer_id)]
                    if not station_meta.empty:
                        station_name = station_meta.iloc[0].get("station_name", piezometer_id)
                        filename = f"{safe_id}_{self._safe_file_token(station_name)}.csv"

                station_data = self.data[self.data["piezometer_id"].astype(str) == str(piezometer_id)]
                record_count = len(station_data)
                if not station_data.empty and "date_measure" in station_data.columns:
                    date_range = f"{station_data['date_measure'].min()} to {station_data['date_measure'].max()}"
                else:
                    date_range = "No data"
                toc_content.append(f"# {filename}: {record_count} records, {date_range}")

        if full_mode:
            toc_content.append("")
            toc_content.append("# Metadata Files:")
            toc_content.append("# metadata.csv: Piezometer metadata and characteristics")
            toc_content.append("# stations_info.csv: Detailed station reference information")
            toc_content.append("# missing_data_summary.csv: Data completeness analysis")

        with open(export_path / "README.txt", "w", encoding="utf-8") as stream:
            stream.write("\n".join(toc_content))
        print("  Exported: README.txt")

    def get_missing_data_summary(self):
        """Return the missing-data summary dataframe for loaded piezometers."""
        return self.missing_data_summary

    def _resolve_plot_column(self, value: Optional[str]) -> tuple[str, str]:
        """Resolve plot series and y-label from requested value selector."""
        selected = value
        if selected is None:
            selected = "depth" if self.measurement == "depth" else "level"
        if selected not in ("level", "depth"):
            raise ValueError("value must be 'level' or 'depth'.")
        if selected == "depth":
            return "groundwater_depth_m", "Depth to water table [m]"
        return "groundwater_level_m", "Groundwater level [m]"

    def plot_piezometer(
        self,
        piezometer_id: Optional[Union[str, List[str]]] = None,
        value: Optional[str] = None,
        output_path: Optional[Union[str, Path]] = None,
        show: bool = True,
        figsize: tuple = (12, 4),
    ):
        """Plot loaded piezometer station series."""
        if not self.piezometers:
            raise ValueError("No loaded piezometer data available to plot.")

        if isinstance(piezometer_id, str):
            return self.get_piezometer(piezometer_id).plot(
                value=value,
                output_path=output_path,
                show=show,
                block=True,
                figsize=figsize,
            )

        if piezometer_id is None:
            station_order = sorted(self.piezometers.keys())
        else:
            station_order = [str(pid) for pid in piezometer_id]
            missing = [pid for pid in station_order if pid not in self.piezometers]
            if missing:
                raise ValueError(f"No piezometer data found for piezometer_id={missing}.")
            if len(station_order) == 1:
                return self.get_piezometer(station_order[0]).plot(
                    value=value,
                    output_path=output_path,
                    show=show,
                    block=True,
                    figsize=figsize,
                )

        try:
            import matplotlib.pyplot as plt
        except ImportError as exc:
            raise ImportError(
                "Matplotlib is required to plot piezometer data. "
                "Install with: pip install matplotlib"
            ) from exc

        y_column, y_label = self._resolve_plot_column(value)
        fig, ax = plt.subplots(1, 1, figsize=figsize, dpi=140)
        plotted_count = 0

        for pid in station_order:
            piezometer_obj = self.get_piezometer(pid)
            sdf = piezometer_obj.data.copy()
            if "date_measure" not in sdf.columns or y_column not in sdf.columns:
                continue
            sdf["date_measure"] = pd.to_datetime(sdf["date_measure"], errors="coerce")
            sdf[y_column] = pd.to_numeric(sdf[y_column], errors="coerce")
            sdf = sdf.dropna(subset=["date_measure", y_column]).sort_values("date_measure")
            if sdf.empty:
                continue

            ax.plot(
                sdf["date_measure"].to_numpy(),
                sdf[y_column].to_numpy(dtype=float),
                linewidth=1.2,
                label=piezometer_obj.build_label(),
            )
            plotted_count += 1

        if plotted_count == 0:
            raise ValueError("No valid piezometer points available after cleaning.")

        ax.set_title(f"Loaded piezometer series - {self.measurement}")
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
            print(f"Piezometer figure exported to: {output_path}")

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
        """Print a human-readable completeness report across piezometers."""
        if self.missing_data_summary.empty:
            print("No missing data analysis available.")
            return

        print("\n=== DATA COMPLETENESS REPORT ===")
        total_stations = len(self.missing_data_summary)
        avg_completeness = self.missing_data_summary["completeness_pct"].mean()
        total_missing = self.missing_data_summary["missing_days"].sum()
        total_expected = self.missing_data_summary["expected_days"].sum()

        print(f"Total piezometers: {total_stations}")
        print(f"Average completeness: {avg_completeness:.1f}%")
        print(f"Total missing days: {total_missing:,} out of {total_expected:,} expected")

        complete = (self.missing_data_summary["completeness_pct"] == 100).sum()
        mostly_complete = (
            (self.missing_data_summary["completeness_pct"] >= 90)
            & (self.missing_data_summary["completeness_pct"] < 100)
        ).sum()
        partial = (
            (self.missing_data_summary["completeness_pct"] >= 50)
            & (self.missing_data_summary["completeness_pct"] < 90)
        ).sum()
        incomplete = (self.missing_data_summary["completeness_pct"] < 50).sum()

        print("\nCompleteness breakdown:")
        print(f"  Complete (100%): {complete} piezometers")
        print(f"  Mostly complete (90-99%): {mostly_complete} piezometers")
        print(f"  Partial (50-89%): {partial} piezometers")
        print(f"  Incomplete (<50%): {incomplete} piezometers")

        if incomplete > 0 or partial > 0:
            print("\nPiezometers with most missing data:")
            worst = self.missing_data_summary.nsmallest(
                5, "completeness_pct"
            )[["piezometer_id", "completeness_pct", "missing_days"]]
            print(worst.to_string(index=False))
