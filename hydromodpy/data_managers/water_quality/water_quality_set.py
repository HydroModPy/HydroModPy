"""
File Name: water_quality_set.py
Description: Water quality wrapper for Hub'Eau water quality API (rivers or piezometers) and
local files.  This mirrors the structure used by `piezometer_set.py` but is generalized for
parameters that may come from either a river/stream measurement or a groundwater piezometer.
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
    from .water_quality import WaterQuality
    from .loaders_api import ApiWaterQualityLoader
    from .loaders_local import LocalWaterQualityLoader
except ImportError:  # pragma: no cover - adjust import path for standalone execution
    import sys

    _manager_root = Path(__file__).resolve().parents[1]
    _this_dir = Path(__file__).resolve().parent
    for _path in (str(_manager_root), str(_this_dir)):
        if _path not in sys.path:
            sys.path.insert(0, _path)
    from common.base_station_set import BaseStationSet
    from common.utils import safe_file_token
    from water_quality import WaterQuality
    from loaders_api import ApiWaterQualityLoader
    from loaders_local import LocalWaterQualityLoader


# two possible base URLs depending on the type of site
API_PZ_URL = "https://hubeau.eaufrance.fr/api/v1/qualite_nappes/analyses"
API_RIVER_URL = "https://hubeau.eaufrance.fr/api/v2/analyse_pc/"

STATUS_MESSAGES = {
    200: "Success: All results present in the response",
    206: "Partial content: Some results may be missing",
    400: "Bad request: Check your request parameters",
    401: "Unauthorized: Check your credentials",
    403: "Forbidden: Check your permissions",
    404: "Not found: Check your URL",
    500: "Internal server error: Try again later",
}


class WaterQualitySet(BaseStationSet):
    """Container orchestrating multi‑site water‑quality time series."""

    # ------------------------------------------------------------------
    # alternate constructors / discovery helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_toml(cls, config_path: Union[str, Path]):
        """Build a :class:`WaterQualitySet` from a TOML configuration file."""
        try:
            from .water_quality_config import load_water_quality_toml
        except ImportError:
            from water_quality_config import load_water_quality_toml

        cfg = load_water_quality_toml(config_path)
        return cls.from_config(cfg)

    @classmethod
    def from_config(cls, config_data: Mapping[str, Any]):
        """Build a :class:`WaterQualitySet` from normalized config sections."""
        wq_cfg = dict(config_data["water_quality"])
        source_cfg = dict(config_data["source"])
        selection_cfg = dict(config_data["selection"])
        output_cfg = dict(config_data["output"])

        site_ids = None
        mask_path = None
        if selection_cfg["mode"] == "sites":
            site_ids = selection_cfg["site_ids"]
        else:
            mask_path = selection_cfg["mask_path"]

        output_value = None
        if output_cfg["enabled"]:
            if output_cfg["export_mode"] == "full":
                output_value = [output_cfg["path"], "full"]
            else:
                output_value = output_cfg["path"]

        return cls(
            site_type=wq_cfg["site_type"],
            parameters=wq_cfg.get("parameters"),
            id=site_ids,
            mask=mask_path,
            display=wq_cfg.get("display", False),
            date_start=wq_cfg.get("date_start"),
            date_end=wq_cfg.get("date_end"),
            output=output_value,
            source_mode=source_cfg["mode"],
            local_data_dir=source_cfg.get("local_data_dir"),
        )

    @classmethod
    def discover_site_ids(
        cls,
        *,
        site_type: str = "river",  # or "piezometer"
        bbox: Optional[tuple[float, float, float, float]] = None,
        mask_path: Optional[Union[str, Path]] = None,
        require_observations: bool = False,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        max_ids: int = 20,
        timeout: int = 30,
    ) -> List[str]:
        """Discover valid Hub'Eau site identifiers in a geographic area.

        ``site_type`` selects between the river or piezometer quality endpoints.
        The rest of the arguments mirror :meth:`PiezometerSet.discover_piezometer_ids`.
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

        params = {"bbox": f"{minx},{miny},{maxx},{maxy}", "size": 10000, "format": "json"}
        url = API_RIVER_URL if site_type == "river" else API_PZ_URL
        try:
            response = requests.get(f"{url}stations", params=params, timeout=timeout)
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
            sid = str(row.get("code_bss", "") or row.get("id")).strip()
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
                "code_bss" if site_type == "piezometer" else "id": sid,
                "date_debut_mesure": start,
                "date_fin_mesure": end,
                "size": 1,
                "format": "json",
            }
            # the river endpoint may use different param names; adapt later
            try:
                resp = requests.get(f"{url}chroniques", params=chrono_params, timeout=timeout)
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

    # ------------------------------------------------------------------
    # initialization and data loading
    # ------------------------------------------------------------------

    def __init__(
        self,
        *,
        site_type: str = "river",
        parameters: Optional[List[str]] = None,
        id: Optional[Union[str, List[str], None]] = None,
        mask: Optional[Union[str, Path, None]] = None,
        display: bool = False,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        output: Optional[Union[str, List[str], None]] = None,
        source_mode: str = "api",
        local_data_dir: Optional[Union[str, Path, None]] = None,
    ):
        """Initialize instance.

        Parameters largely mirror :class:`PiezometerSet` but include ``site_type``
        ("river" or "piezometer") and an optional list of ``parameters`` to
        restrict the search (e.g. ["ph", "conductivite"]).
        """
        site_type = str(site_type).strip().lower()
        if site_type not in ("river", "piezometer"):
            raise ValueError("site_type must be 'river' or 'piezometer'.")
        self.site_type = site_type
        self.parameters = parameters[:] if parameters is not None else None

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
        self.samples: Dict[str, WaterQuality] = {}

        if mask is not None:
            self.site_ids = self._get_sites_from_mask(mask)
        elif id is not None:
            self.site_ids = self._process_ids(id)
        else:
            raise ValueError("Either 'id' or 'mask' parameter must be provided")

        self.__load_all_data()

        if self.output:
            self._export_data()

    # remaining methods would largely replicate those in PiezometerSet with
    # appropriate renaming (piezometers -> sites/samples, etc.).
    # for brevity the rest is omitted here – see piezometer_set.py for the full
    # pattern and adapt field names to the water quality API schema.

    # utility methods for spatial filtering, normalizing dates, checking API
    # status codes, exporting and plotting can be copied verbatim and adjusted
    # to the content of the water quality records.

    @staticmethod
    def _process_ids(id_values):
        """Normalize site identifiers into a list of strings."""
        if isinstance(id_values, str):
            id_values = [id_values]
        normalized = [str(v).strip() for v in id_values]
        if any(not sid for sid in normalized):
            raise ValueError("Site ids cannot contain empty values.")
        return normalized

    def _get_sites_from_mask(self, mask_path):
        """Select site identifiers located inside a geographic mask.

        Current implementation simply forwards to the API filter or local
        filter depending on ``source_mode``.  A full implementation should
        parallel :meth:`PiezometerSet._get_piezometers_from_mask`.
        """
        print(f"Loading geographic mask from: {mask_path}")
        mask_gdf = self._load_mask_geometry(mask_path)
        if self.source_mode == "api":
            return self._filter_sites_with_geometry_api(mask_gdf)
        if self.source_mode == "local":
            return self._filter_sites_with_geometry_local(mask_gdf)
        raise ValueError(f"Unsupported source_mode: {self.source_mode}")

    @staticmethod
    def _normalize_api_date(value: Optional[str], *, default: str) -> str:
        if value is None:
            return default
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            return default
        return parsed.strftime("%Y-%m-%d")

    def __check_status_code(self, status_code) -> bool:
        message = STATUS_MESSAGES.get(status_code, f"Unknown error {status_code}: Check the API documentation")
        is_success = status_code in (200, 206)
        if not is_success:
            print(f"Error {status_code}: {message}")
        return is_success

    # stub for _get_sites_from_mask, _filter_sites_with_geometry_api, etc.
    # ...

    # Export, plotting and completeness report logic may also be ported here.


# End of water_quality_set.py
