"""Piezometry discovery helpers."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from hydromodpy.core.io.http_client import get_default_client

logger = logging.getLogger(__name__)

try:
    from hydromodpy.core.units import parse_length_to_m

    from ..common.base_station_set import BaseStationSet
except ImportError:
    import sys

    _manager_root = Path(__file__).resolve().parents[1]
    _repo_root = Path(__file__).resolve().parents[3]
    for _path in (str(_manager_root), str(_repo_root)):
        if _path not in sys.path:
            sys.path.insert(0, _path)
    from common.base_station_set import BaseStationSet

    from hydromodpy.core.units import parse_length_to_m


API_BASE_URL = "https://hubeau.eaufrance.fr/api/v1/niveaux_nappes/"

STATUS_MESSAGES = {
    200: "Success: All results present in the response",
    206: "Partial content: Some results may be missing",
    400: "Bad request: Check your request parameters",
    401: "Unauthorized: Check your credentials",
    403: "Forbidden: Check your permissions",
    404: "Not found: Check your URL",
    500: "Internal server error: Try again later",
}


class PiezometerDiscovery(BaseStationSet):
    """Encapsulate piezometer discovery outside ``PiezometerSet``."""

    def __init__(self, *, local_data_dir: str | Path | None = None):
        self.local_data_dir = (
            Path(local_data_dir).expanduser().resolve() if local_data_dir else None
        )

    @staticmethod
    def normalize_piezometer_ids(id_values: str | list[str]) -> list[str]:
        """Normalize piezometer identifiers into a list of strings."""
        if isinstance(id_values, str):
            id_values = [id_values]
        normalized = [str(value).strip() for value in id_values]
        if any(not piezometer_id for piezometer_id in normalized):
            raise ValueError("Piezometer ids cannot contain empty values.")
        return normalized

    @classmethod
    def discover_piezometer_ids(
        cls,
        *,
        bbox: tuple[float, float, float, float] | None = None,
        mask_path: str | Path | None = None,
        center_point: tuple[float, float] | None = None,
        fallback_search_radius_m: Any | None = None,
        fallback_search_radius_km: Any | None = None,
        require_observations: bool = False,
        date_start: str | None = None,
        date_end: str | None = None,
        max_ids: int | None = 20,
        timeout: int = 30,
    ) -> list[str]:
        """Discover valid Hub'Eau piezometer identifiers in a geographic area."""
        if max_ids is not None and max_ids < 1:
            raise ValueError("max_ids must be None or >= 1")
        if fallback_search_radius_m is not None and fallback_search_radius_km is not None:
            raise ValueError(
                "Use either fallback_search_radius_m or fallback_search_radius_km, not both."
            )
        if fallback_search_radius_m is None and fallback_search_radius_km is None:
            fallback_search_radius_km = 25.0
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

        reference_point = center_point
        if reference_point is None and mask_gdf is not None:
            bounds = mask_gdf.total_bounds
            reference_point = ((bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2)

        candidate_data = helper._search_piezometers_in_bbox(
            minx=minx,
            miny=miny,
            maxx=maxx,
            maxy=maxy,
            mask_gdf=mask_gdf,
            timeout=timeout,
            fail_silently=True,
        )

        if not candidate_data and radius_m > 0 and reference_point is not None:
            logger.info("No piezometers found in the initial search area.")
            logger.info("Searching in a %.3f km buffer around the area...", radius_m / 1000.0)
            buffer_deg = radius_m / 111_000.0
            candidate_data = helper._search_piezometers_in_bbox(
                minx=minx - buffer_deg,
                miny=miny - buffer_deg,
                maxx=maxx + buffer_deg,
                maxy=maxy + buffer_deg,
                mask_gdf=None,
                timeout=timeout,
                fail_silently=True,
            )
            if candidate_data:
                logger.info("Found %d piezometers in buffered search area.", len(candidate_data))

        if (
            reference_point is not None
            and candidate_data
            and all(item["coords"] is not None for item in candidate_data)
        ):
            ref_lon, ref_lat = reference_point
            distances = []
            for item in candidate_data:
                lon, lat = item["coords"]
                distances.append(
                    (item["id"], helper._haversine_distance(ref_lon, ref_lat, lon, lat))
                )
            distances.sort(key=lambda item: item[1])
            candidate_ids = [candidate_id for candidate_id, _ in distances[:max_ids]]
            logger.info(
                "Discovered %d closest piezometers sorted by distance to reference point",
                len(candidate_ids),
            )

            if require_observations:
                return helper._filter_by_observations(
                    candidate_ids=candidate_ids,
                    date_start=date_start,
                    date_end=date_end,
                    max_ids=max_ids,
                    timeout=timeout,
                )
            return candidate_ids

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

    def select_piezometer_ids_from_mask(
        self,
        mask_path: str | Path,
        *,
        source_mode: str,
        fallback_search_radius_m: Any | None = None,
        fallback_search_radius_km: Any | None = None,
    ) -> list[str]:
        """Select piezometer identifiers located inside a mask geometry."""
        logger.info("Loading geographic mask from: %s", mask_path)
        mask_gdf = self._load_mask_geometry(mask_path)
        mode = str(source_mode).strip().lower()
        if fallback_search_radius_m is not None and fallback_search_radius_km is not None:
            raise ValueError(
                "Use either fallback_search_radius_m or fallback_search_radius_km, not both."
            )
        if fallback_search_radius_m is None and fallback_search_radius_km is None:
            fallback_search_radius_km = 25.0
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
            return self._select_api_piezometer_ids_from_mask(
                mask_gdf=mask_gdf,
                fallback_search_radius_m=radius_m,
            )
        if mode == "local":
            return self._filter_piezometers_with_geometry_local(mask_gdf)
        raise ValueError(f"Unsupported source_mode: {source_mode}")

    @staticmethod
    def _normalize_api_date(value: str | None, *, default: str) -> str:
        """Normalize date string to API ``YYYY-MM-DD`` format."""
        if value is None:
            return default
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            return default
        return parsed.strftime("%Y-%m-%d")

    @staticmethod
    def _extract_wgs84_coordinates(row: Mapping[str, Any]) -> tuple[float, float] | None:
        """Extract WGS84 coordinates from a station payload."""
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

    @staticmethod
    def _haversine_distance(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
        """Calculate distance in meters between two WGS84 points."""
        lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
        dlon = lon2 - lon1
        dlat = lat2 - lat1
        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        return 6_371_000.0 * 2 * asin(sqrt(a))

    def _request_station_rows_bbox(
        self,
        *,
        minx: float,
        miny: float,
        maxx: float,
        maxy: float,
        timeout: int,
        fail_silently: bool,
    ) -> list[dict[str, Any]]:
        params = {
            "bbox": f"{minx},{miny},{maxx},{maxy}",
            "size": 10000,
            "format": "json",
        }
        url = f"{API_BASE_URL}stations"

        try:
            response = get_default_client().get(url, params=params, timeout=timeout)
        except requests.exceptions.RequestException as exc:
            if fail_silently:
                logger.warning("Station discovery request failed: %s", exc)
                return []
            raise RuntimeError(f"Failed to retrieve piezometers from API: {exc}") from exc

        if response.status_code not in (200, 206):
            message = STATUS_MESSAGES.get(response.status_code, "Unknown API error")
            if fail_silently:
                logger.error("API error %d: %s", response.status_code, message)
                return []
            raise RuntimeError(f"Failed to retrieve piezometers from API: {message}")

        try:
            return response.json().get("data", [])
        except ValueError as exc:
            if fail_silently:
                logger.warning("Invalid station discovery payload: %s", exc)
                return []
            raise RuntimeError(f"Invalid piezometer discovery payload: {exc}") from exc

    def _search_piezometers_in_bbox(
        self,
        *,
        minx: float,
        miny: float,
        maxx: float,
        maxy: float,
        mask_gdf: Any | None = None,
        timeout: int = 30,
        fail_silently: bool = True,
    ) -> list[dict]:
        """Search for piezometers in a bounding box."""
        station_rows = self._request_station_rows_bbox(
            minx=minx,
            miny=miny,
            maxx=maxx,
            maxy=maxy,
            timeout=timeout,
            fail_silently=fail_silently,
        )
        if not station_rows:
            return []

        if mask_gdf is not None:
            gpd, Point = self._load_geographic_libraries()
            points = []
            valid_rows = []
            for row in station_rows:
                xy = self._extract_wgs84_coordinates(row)
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
        candidate_data: list[dict] = []
        for row in station_rows:
            station_id = str(row.get("code_bss", "")).strip()
            if station_id and station_id not in seen:
                seen.add(station_id)
                candidate_data.append(
                    {
                        "id": station_id,
                        "coords": self._extract_wgs84_coordinates(row),
                        "row": row,
                    }
                )

        return candidate_data

    def _filter_by_observations(
        self,
        *,
        candidate_ids: list[str],
        date_start: str | None,
        date_end: str | None,
        max_ids: int | None,
        timeout: int,
    ) -> list[str]:
        """Filter piezometer IDs by chronicle availability in a date range."""
        start = self._normalize_api_date(date_start, default="1900-01-01")
        end = self._normalize_api_date(date_end, default=datetime.now().strftime("%Y-%m-%d"))
        discovered: list[str] = []

        for piezometer_id in candidate_ids:
            chrono_params = {
                "code_bss": piezometer_id,
                "date_debut_mesure": start,
                "date_fin_mesure": end,
                "size": 1,
                "format": "json",
            }
            try:
                response = get_default_client().get(
                    f"{API_BASE_URL}chroniques",
                    params=chrono_params,
                    timeout=timeout,
                )
            except requests.exceptions.RequestException:
                continue
            if response.status_code not in (200, 206):
                continue
            payload = response.json()
            if int(payload.get("count", 0) or 0) > 0:
                discovered.append(piezometer_id)
                if max_ids is not None and len(discovered) >= max_ids:
                    break

        return discovered

    def _select_api_piezometer_ids_from_mask(
        self,
        *,
        mask_gdf: Any,
        fallback_search_radius_m: float,
    ) -> list[str]:
        bounds = mask_gdf.total_bounds
        logger.info("Searching piezometers in bounding box: %s", bounds)

        candidate_data = self._search_piezometers_in_bbox(
            minx=float(bounds[0]),
            miny=float(bounds[1]),
            maxx=float(bounds[2]),
            maxy=float(bounds[3]),
            mask_gdf=mask_gdf,
            timeout=30,
            fail_silently=False,
        )

        if not candidate_data:
            logger.info("No piezometers found within the mask polygon.")
            logger.info(
                "Activating automatic fallback search: %.3f km radius buffer...",
                fallback_search_radius_m / 1000.0,
            )

            centroid = mask_gdf.unary_union.centroid
            ref_lon, ref_lat = centroid.x, centroid.y
            lat_offset = fallback_search_radius_m / 111_000.0
            lon_offset = fallback_search_radius_m / (111_000.0 * cos(radians(ref_lat)))

            candidate_data = self._search_piezometers_in_bbox(
                minx=ref_lon - lon_offset,
                miny=ref_lat - lat_offset,
                maxx=ref_lon + lon_offset,
                maxy=ref_lat + lat_offset,
                mask_gdf=None,
                timeout=30,
                fail_silently=False,
            )

            if candidate_data:
                candidate_data.sort(
                    key=lambda item: (
                        float("inf")
                        if item["coords"] is None
                        else self._haversine_distance(
                            ref_lon, ref_lat, item["coords"][0], item["coords"][1]
                        )
                    )
                )
                logger.info(
                    "Using all %d piezometers from fallback search (sorted by distance)",
                    len(candidate_data),
                )
            else:
                raise ValueError(
                    "No piezometers found within the specified geographic mask "
                    f"or in {fallback_search_radius_m / 1000.0:.3f} km fallback radius"
                )

        piezometer_ids = sorted({item["id"] for item in candidate_data})
        logger.info("Found %d piezometers within geographic mask", len(piezometer_ids))
        return piezometer_ids

    def _load_local_station_catalog(self) -> pd.DataFrame:
        """Load local piezometer catalogue for mask filtering."""
        if self.local_data_dir is None:
            raise ValueError("local_data_dir is required for local station catalogue.")

        stations_info_path = self.local_data_dir / "stations_info.csv"
        metadata_path = self.local_data_dir / "metadata.csv"

        if stations_info_path.exists():
            df = pd.read_csv(stations_info_path)
            station_col = "piezometer_id" if "piezometer_id" in df.columns else "code_bss"
            lon_col = "longitude_station" if "longitude_station" in df.columns else "x_wgs84"
            lat_col = "latitude_station" if "latitude_station" in df.columns else "y_wgs84"
            if (
                station_col not in df.columns
                or lon_col not in df.columns
                or lat_col not in df.columns
            ):
                raise ValueError(
                    "stations_info.csv must contain piezometer id and longitude/latitude columns."
                )
            out = df[[station_col, lon_col, lat_col]].copy()
            out.columns = ["piezometer_id", "lon", "lat"]
        elif metadata_path.exists():
            df = pd.read_csv(metadata_path)
            station_col = "piezometer_id" if "piezometer_id" in df.columns else "code_bss"
            if (
                station_col not in df.columns
                or "x_wgs84" not in df.columns
                or "y_wgs84" not in df.columns
            ):
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

    def _filter_piezometers_with_geometry_local(self, mask_gdf: Any) -> list[str]:
        """Filter locally available piezometers intersecting a mask geometry."""
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
            stations_in_mask = gpd.sjoin(
                stations_gdf, mask_gdf, how="inner", predicate="intersects"
            )

        if stations_in_mask.empty:
            raise ValueError("No local piezometers found within the specified geographic mask.")

        piezometer_ids = sorted(stations_in_mask["piezometer_id"].astype(str).unique().tolist())
        logger.info("Found %d local piezometers within geographic mask", len(piezometer_ids))
        return piezometer_ids


def discover_piezometer_ids(**kwargs) -> list[str]:
    """Module-level wrapper around :class:`PiezometerDiscovery`."""
    return PiezometerDiscovery.discover_piezometer_ids(**kwargs)


def select_piezometer_ids_from_mask(
    mask_path: str | Path,
    *,
    source_mode: str,
    local_data_dir: str | Path | None = None,
    fallback_search_radius_m: Any | None = None,
    fallback_search_radius_km: Any | None = None,
) -> list[str]:
    """Module-level wrapper used by :class:`PiezometerSet`."""
    helper = PiezometerDiscovery(local_data_dir=local_data_dir)
    return helper.select_piezometer_ids_from_mask(
        mask_path=mask_path,
        source_mode=source_mode,
        fallback_search_radius_m=fallback_search_radius_m,
        fallback_search_radius_km=fallback_search_radius_km,
    )


def normalize_piezometer_ids(id_values: str | list[str]) -> list[str]:
    """Module-level wrapper for explicit piezometer-id normalization."""
    return PiezometerDiscovery.normalize_piezometer_ids(id_values)
