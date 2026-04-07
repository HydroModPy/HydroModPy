"""Hydrometry station discovery helpers."""

from __future__ import annotations

import logging
from datetime import datetime
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from typing import Any, List, Optional, Union

import pandas as pd
import requests

logger = logging.getLogger(__name__)

try:
    from ..common.base_station_set import BaseStationSet
    from hydromodpy.core.units import parse_length_to_m
except ImportError:
    import sys

    _manager_root = Path(__file__).resolve().parents[1]
    _repo_root = Path(__file__).resolve().parents[3]
    for _path in (str(_manager_root), str(_repo_root)):
        if _path not in sys.path:
            sys.path.insert(0, _path)
    from common.base_station_set import BaseStationSet
    from hydromodpy.core.units import parse_length_to_m


API_BASE_URL = "https://hubeau.eaufrance.fr/api/v2/"

STATUS_MESSAGES = {
    200: "Success: All results present in the response",
    206: "Partial content: Some results may be missing",
    400: "Bad request: Check your request parameters",
    401: "Unauthorized: Check your credentials",
    403: "Forbidden: Check your permissions",
    404: "Not found: Check your URL",
    500: "Internal server error: Try again later",
}


class StationDiscovery(BaseStationSet):
    """Encapsulate hydrometric station discovery outside ``StationSet``."""

    def __init__(self, *, local_data_dir: Optional[Union[str, Path]] = None):
        self.local_data_dir = Path(local_data_dir).expanduser().resolve() if local_data_dir else None

    @staticmethod
    def _mask_centroid(mask_gdf: Any):
        """Return centroid of a (possibly multi-feature) mask GeoDataFrame."""
        try:
            # GeoPandas/Shapely modern path.
            return mask_gdf.union_all().centroid
        except Exception:
            # Backward-compatible fallback.
            return mask_gdf.unary_union.centroid

    @staticmethod
    def normalize_station_ids(id_values: Union[str, List[str]]) -> tuple[list[str], list[str]]:
        """Normalize station/site identifiers into parallel station/site lists."""
        if isinstance(id_values, str):
            id_values = [id_values]

        station_ids: list[str] = []
        site_ids: list[str] = []

        for raw_id in id_values:
            id_val = str(raw_id).strip()
            if len(id_val) == 10:
                station_ids.append(id_val)
                site_ids.append(id_val[:-2])
            elif len(id_val) == 8:
                station_ids.append(id_val + "01")
                site_ids.append(id_val)
                logger.info("%s is a site ID, by default, the station ID is %s", id_val, station_ids[-1])
            else:
                raise ValueError(f"Invalid ID length: {id_val}. Expected 8 or 10 characters.")

        return station_ids, site_ids

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
    ) -> list[str]:
        """Discover valid Hub'Eau hydrometric station identifiers in a geographic area."""
        if max_ids is not None and max_ids < 1:
            raise ValueError("max_ids must be None or >= 1")
        if fallback_search_radius_m is not None and fallback_search_radius_km is not None:
            raise ValueError(
                "Use either fallback_search_radius_m or fallback_search_radius_km, not both."
            )
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

        helper = cls()
        mask_gdf = None

        if mask_path is not None:
            mask_gdf = helper._load_mask_geometry(mask_path)
            if mask_gdf is None:
                raise ValueError("Failed to load mask geometry")

        if bbox is None:
            if mask_gdf is None:
                raise ValueError("Either 'bbox' or 'mask_path' must be provided")
            bounds = mask_gdf.total_bounds
        else:
            bounds = bbox

        try:
            minx, miny, maxx, maxy = [float(v) for v in bounds]
        except Exception as exc:
            raise ValueError(f"Invalid bbox format: {exc}") from exc

        if minx >= maxx or miny >= maxy:
            raise ValueError(f"Invalid bbox: minx={minx} >= maxx={maxx} or miny={miny} >= maxy={maxy}")

        reference_point = center_point
        if reference_point is None and mask_gdf is not None:
            centroid = helper._mask_centroid(mask_gdf)
            reference_point = (centroid.x, centroid.y)

        candidate_data = helper._search_stations_in_bbox(
            minx=minx,
            miny=miny,
            maxx=maxx,
            maxy=maxy,
            mask_gdf=mask_gdf,
            timeout=timeout,
        )

        if not candidate_data and radius_m > 0 and reference_point is not None:
            logger.info("No stations found in initial area. Trying with %.3f km buffer...", radius_m / 1000.0)
            lon, lat = reference_point
            lat_offset = radius_m / 111_000.0
            lon_offset = radius_m / (111_000.0 * cos(radians(lat)))
            candidate_data = helper._search_stations_in_bbox(
                minx=lon - lon_offset,
                miny=lat - lat_offset,
                maxx=lon + lon_offset,
                maxy=lat + lat_offset,
                mask_gdf=None,
                timeout=timeout,
            )

        if reference_point is not None and candidate_data and all(item["coords"] is not None for item in candidate_data):
            candidate_data.sort(
                key=lambda item: helper._haversine_distance(
                    reference_point[0],
                    reference_point[1],
                    item["coords"][0],
                    item["coords"][1],
                )
            )

        candidate_ids = [item["id"] for item in candidate_data]
        if not require_observations:
            return candidate_ids if max_ids is None else candidate_ids[:max_ids]

        return helper._filter_by_observations(
            candidate_ids=candidate_ids,
            date_start=date_start,
            date_end=date_end,
            max_ids=max_ids,
            timeout=timeout,
        )

    def select_station_ids_from_mask(
        self,
        mask_path: Union[str, Path],
        *,
        source_mode: str,
        fallback_search_radius_m: Optional[Any] = None,
        fallback_search_radius_km: Optional[Any] = None,
    ) -> tuple[list[str], list[str]]:
        """Select station identifiers located inside a mask geometry."""
        logger.info("Loading geographic mask from: %s", mask_path)
        mask_gdf = self._load_mask_geometry(mask_path)
        mode = str(source_mode).strip().lower()
        if fallback_search_radius_m is not None and fallback_search_radius_km is not None:
            raise ValueError(
                "Use either fallback_search_radius_m or fallback_search_radius_km, not both."
            )
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

        if mode == "api":
            return self._select_api_station_ids_from_mask(
                mask_gdf=mask_gdf,
                fallback_search_radius_m=radius_m,
            )
        if mode == "local":
            return self._filter_stations_with_geometry_local(mask_gdf)
        raise ValueError(f"Unsupported source_mode: {source_mode}")

    @staticmethod
    def _haversine_distance(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
        """Calculate distance in meters between two WGS84 points."""
        lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
        dlon = lon2 - lon1
        dlat = lat2 - lat1
        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        return 6_371_000.0 * 2 * asin(sqrt(a))

    @staticmethod
    def _normalize_api_date(value: Optional[str], *, default: str) -> str:
        """Normalize date string to API ``YYYY-MM-DD`` format."""
        if value is None:
            return default
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            return default
        return parsed.strftime("%Y-%m-%d")

    def _request_station_rows_bbox(
        self,
        *,
        minx: float,
        miny: float,
        maxx: float,
        maxy: float,
    ) -> list[dict[str, Any]]:
        params = {
            "bbox": f"{minx},{miny},{maxx},{maxy}",
            "size": 10000,
            "format": "json",
        }
        url = f"{API_BASE_URL}hydrometrie/referentiel/stations"

        try:
            response = requests.get(url, params=params, timeout=30)
        except requests.exceptions.RequestException as exc:
            raise RuntimeError(f"Failed to query Hub'Eau API: {exc}") from exc

        if response.status_code not in (200, 206):
            status_msg = STATUS_MESSAGES.get(response.status_code, f"Unknown error {response.status_code}")
            raise RuntimeError(f"API request failed: {status_msg}")

        try:
            return response.json().get("data", [])
        except ValueError as exc:
            raise RuntimeError(f"Invalid JSON payload returned by Hub'Eau API: {exc}") from exc

    def _search_stations_in_bbox(
        self,
        *,
        minx: float,
        miny: float,
        maxx: float,
        maxy: float,
        mask_gdf: Optional[Any] = None,
        timeout: int = 30,
    ) -> List[dict]:
        """Search for hydrometric stations in a bounding box."""
        station_rows = self._request_station_rows_bbox(
            minx=minx,
            miny=miny,
            maxx=maxx,
            maxy=maxy,
        )
        if not station_rows:
            return []

        if mask_gdf is not None:
            try:
                gpd, Point = self._load_geographic_libraries()
                points = []
                valid_rows = []
                for row in station_rows:
                    lon = row.get("longitude_station")
                    lat = row.get("latitude_station")
                    if lon is None or lat is None:
                        continue
                    try:
                        points.append(Point(float(lon), float(lat)))
                        valid_rows.append(row)
                    except (ValueError, TypeError):
                        continue

                if not valid_rows:
                    return []

                stations_gdf = gpd.GeoDataFrame(valid_rows, geometry=points, crs="EPSG:4326")
                try:
                    stations_in_mask = gpd.sjoin(stations_gdf, mask_gdf, how="inner", predicate="within")
                except Exception:
                    stations_in_mask = gpd.sjoin(stations_gdf, mask_gdf, how="inner", predicate="intersects")

                station_rows = stations_in_mask.to_dict("records")
            except ImportError:
                pass

        seen = set()
        candidate_data: List[dict] = []
        for row in station_rows:
            station_id = row.get("code_station")
            if station_id is None or station_id in seen:
                continue
            seen.add(station_id)

            coords = None
            lon = row.get("longitude_station")
            lat = row.get("latitude_station")
            if lon is not None and lat is not None:
                try:
                    coords = (float(lon), float(lat))
                except (ValueError, TypeError):
                    coords = None

            candidate_data.append({"id": str(station_id), "coords": coords, "row": row})

        return candidate_data

    def _filter_by_observations(
        self,
        *,
        candidate_ids: List[str],
        date_start: Optional[str],
        date_end: Optional[str],
        max_ids: Optional[int],
        timeout: int,
    ) -> list[str]:
        """Filter station IDs by observation availability in a date range."""
        start = self._normalize_api_date(date_start, default="1900-01-01")
        end = self._normalize_api_date(date_end, default=datetime.now().strftime("%Y-%m-%d"))
        discovered: list[str] = []

        for station_id in candidate_ids:
            params = {
                "code_station": station_id,
                "date_debut_obs": start,
                "date_fin_obs": end,
                "size": 1,
                "format": "json",
            }
            url = f"{API_BASE_URL}hydrometrie/obs_elab"

            try:
                response = requests.get(url, params=params, timeout=timeout)
            except requests.exceptions.RequestException:
                continue

            if response.status_code in (200, 206) and response.json().get("data", []):
                discovered.append(station_id)

            if max_ids is not None and len(discovered) >= max_ids:
                break

        return discovered

    def _select_api_station_ids_from_mask(
        self,
        *,
        mask_gdf: Any,
        fallback_search_radius_m: float,
    ) -> tuple[list[str], list[str]]:
        bounds = mask_gdf.total_bounds
        logger.info("Searching stations in bounding box: %s", bounds)

        try:
            candidate_data = self._search_stations_in_bbox(
                minx=float(bounds[0]),
                miny=float(bounds[1]),
                maxx=float(bounds[2]),
                maxy=float(bounds[3]),
                mask_gdf=mask_gdf,
            )
        except RuntimeError as exc:
            logger.warning("Failed to retrieve stations from API on initial bbox: %s", exc)
            return [], []

        if not candidate_data:
            logger.info("No stations found within the mask polygon.")
            logger.info(
                "Activating automatic fallback search: %.3f km radius buffer...",
                fallback_search_radius_m / 1000.0,
            )

            centroid = self._mask_centroid(mask_gdf)
            ref_lon, ref_lat = centroid.x, centroid.y
            lat_offset = fallback_search_radius_m / 111_000.0
            lon_offset = fallback_search_radius_m / (111_000.0 * cos(radians(ref_lat)))

            try:
                candidate_data = self._search_stations_in_bbox(
                    minx=ref_lon - lon_offset,
                    miny=ref_lat - lat_offset,
                    maxx=ref_lon + lon_offset,
                    maxy=ref_lat + lat_offset,
                    mask_gdf=None,
                )
            except RuntimeError as exc:
                logger.warning("Fallback station API request failed: %s", exc)
                candidate_data = []

            if candidate_data:
                candidate_data.sort(
                    key=lambda item: float("inf")
                    if item["coords"] is None
                    else self._haversine_distance(ref_lon, ref_lat, item["coords"][0], item["coords"][1])
                )
                logger.info("Using all %d stations from fallback search (sorted by distance)", len(candidate_data))
            else:
                logger.warning(
                    "No stations found within the specified geographic mask "
                    "or in %.3f km fallback radius.",
                    fallback_search_radius_m / 1000.0,
                )
                return [], []

        station_ids = [item["id"] for item in candidate_data]
        site_ids = [station_id[:8] for station_id in station_ids]
        logger.info("Found %d stations within geographic mask", len(station_ids))
        return station_ids, site_ids

    def _load_local_station_catalog(self) -> pd.DataFrame:
        """Load local station catalogue for mask filtering."""
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
                raise ValueError("stations_info.csv must contain station id and longitude/latitude columns.")
            out = df[[station_col, lon_col, lat_col]].copy()
            out.columns = ["station_id", "lon", "lat"]
        elif metadata_path.exists():
            df = pd.read_csv(metadata_path)
            if "station_id" not in df.columns or "x_wgs84" not in df.columns or "y_wgs84" not in df.columns:
                raise ValueError("metadata.csv must contain station_id, x_wgs84 and y_wgs84 columns.")
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

    def _filter_stations_with_geometry_local(self, mask_gdf: Any) -> tuple[list[str], list[str]]:
        """Filter locally available stations intersecting a mask geometry."""
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
            raise ValueError("No local stations found within the specified geographic mask.")

        station_ids = sorted(stations_in_mask["station_id"].astype(str).unique().tolist())
        site_ids = [station_id[:8] for station_id in station_ids]
        logger.info("Found %d local stations within geographic mask", len(station_ids))
        return station_ids, site_ids


def discover_station_ids(**kwargs) -> list[str]:
    """Module-level wrapper around :class:`StationDiscovery`."""
    return StationDiscovery.discover_station_ids(**kwargs)


def select_station_ids_from_mask(
    mask_path: Union[str, Path],
    *,
    source_mode: str,
    local_data_dir: Optional[Union[str, Path]] = None,
    fallback_search_radius_m: Optional[Any] = None,
    fallback_search_radius_km: Optional[Any] = None,
) -> tuple[list[str], list[str]]:
    """Module-level wrapper used by :class:`StationSet`."""
    helper = StationDiscovery(local_data_dir=local_data_dir)
    return helper.select_station_ids_from_mask(
        mask_path=mask_path,
        source_mode=source_mode,
        fallback_search_radius_m=fallback_search_radius_m,
        fallback_search_radius_km=fallback_search_radius_km,
    )


def normalize_station_ids(id_values: Union[str, List[str]]) -> tuple[list[str], list[str]]:
    """Module-level wrapper for explicit station-id normalization."""
    return StationDiscovery.normalize_station_ids(id_values)
