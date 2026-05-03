"""Shared client for the GéoSAS SIM2 (SAFRAN-ISBA) EDR API.

Provides cube (bbox) and position (point) queries against:
    https://api.geosas.fr/edr/collections/safran-isba/

Returns raw data as CoverageJSON dicts or xarray Datasets (when NetCDF4).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.exceptions import NetworkError
from hydromodpy.core.io.http_client import HTTPClient, get_default_client
from hydromodpy.data.common.api_client import check_status

if TYPE_CHECKING:
    import pandas as pd

BASE_URL = "https://api.geosas.fr/edr/collections/safran-isba"
DEFAULT_TIMEOUT = 120


class Sim2EDRClient:
    """Client for the GéoSAS SIM2 (SAFRAN-ISBA) EDR API.

    Parameters
    ----------
    bbox : tuple[float, float, float, float]
        Bounding box (xmin, ymin, xmax, ymax).
    crs : str
        Coordinate reference system (e.g. "EPSG:2154").
    date_range : str
        ISO date interval (e.g. "2020-01-01/2020-12-31").
    output_format : str
        Response format: "CoverageJSON", "Netcdf4", "CSV", "parquet".
    """

    def __init__(
        self,
        *,
        bbox: tuple[float, float, float, float],
        crs: str = "EPSG:2154",
        date_range: str,
        output_format: str = "CoverageJSON",
        http_client: HTTPClient | None = None,
    ):
        self.bbox = bbox
        self.crs = crs
        self.date_range = date_range
        self.output_format = output_format
        self._http = http_client or get_default_client()

    def fetch_cube(self, *, parameters: list[str]) -> Any:
        """Fetch gridded data for the bounding box.

        Returns a CoverageJSON dict (if format=CoverageJSON) or an
        xarray.Dataset (if format=Netcdf4).
        """
        params = {
            "bbox": f"{self.bbox[0]},{self.bbox[1]},{self.bbox[2]},{self.bbox[3]}",
            "crs": self.crs,
            "parameter-name": ",".join(parameters),
            "f": self.output_format,
            "datetime": self.date_range,
        }
        url = f"{BASE_URL}/cube"
        resp = self._http.get(url, params=params, timeout=DEFAULT_TIMEOUT)
        if not check_status(resp.status_code):
            raise NetworkError(
                f"SIM2 EDR API error {resp.status_code} for {url}: {resp.text[:500]}",
                url=url,
                status_code=resp.status_code,
            )
        if self.output_format == "Netcdf4":
            return self._load_netcdf_from_bytes(resp.content)
        return resp.json()

    def fetch_point(
        self,
        *,
        x: float,
        y: float,
        parameters: list[str],
    ) -> dict:
        """Fetch time series at a single point.

        Returns a CoverageJSON dict.
        """
        params = {
            "coords": f"POINT({x} {y})",
            "crs": self.crs,
            "parameter-name": ",".join(parameters),
            "f": "CoverageJSON",
            "datetime": self.date_range,
        }
        url = f"{BASE_URL}/position"
        resp = self._http.get(url, params=params, timeout=DEFAULT_TIMEOUT)
        if not check_status(resp.status_code):
            raise NetworkError(
                f"SIM2 EDR API error {resp.status_code} for {url}: {resp.text[:500]}",
                url=url,
                status_code=resp.status_code,
            )
        return resp.json()

    @staticmethod
    def _load_netcdf_from_bytes(content: bytes) -> Any:
        """Load NetCDF binary content into an xarray Dataset."""
        import xarray as xr

        with tempfile.NamedTemporaryFile(suffix=".nc", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            ds = xr.open_dataset(tmp_path)
            ds.load()
            return ds
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    @staticmethod
    def coverage_json_to_series(
        cov_json: dict,
        *,
        parameter: str,
    ) -> pd.Series:
        """Extract a 1D time series from a CoverageJSON point response.

        Returns a pandas Series indexed by datetime.
        """
        import pandas as pd

        axes = cov_json["domain"]["axes"]
        if "values" in axes["t"]:
            times = pd.to_datetime(
                [
                    t.replace("T", " ").replace("-00-00Z", " 00:00:00").rstrip("Z")
                    for t in axes["t"]["values"]
                ]
            )
        else:
            times = pd.date_range(
                start=axes["t"]["start"],
                periods=axes["t"]["num"],
                freq="D",
            )
        values = cov_json["ranges"][parameter]["values"]
        return pd.Series(values, index=times, dtype=float, name=parameter)

    @staticmethod
    def coverage_json_to_dataset(cov_json: dict) -> Any:
        """Convert a CoverageJSON cube response to an xarray Dataset."""
        import numpy as np
        import pandas as pd
        import xarray as xr

        axes = cov_json["domain"]["axes"]

        # Build coordinate arrays
        if "values" in axes.get("x", {}):
            x_coords = np.array(axes["x"]["values"], dtype=float)
        else:
            x_coords = np.linspace(axes["x"]["start"], axes["x"]["stop"], axes["x"]["num"])

        if "values" in axes.get("y", {}):
            y_coords = np.array(axes["y"]["values"], dtype=float)
        else:
            y_coords = np.linspace(axes["y"]["start"], axes["y"]["stop"], axes["y"]["num"])

        if "values" in axes.get("t", {}):
            t_coords = pd.to_datetime(
                [
                    t.replace("T", " ").replace("-00-00Z", " 00:00:00").rstrip("Z")
                    for t in axes["t"]["values"]
                ]
            )
        else:
            t_coords = pd.date_range(
                start=axes["t"]["start"],
                periods=axes["t"]["num"],
                freq="D",
            )

        data_vars = {}
        for param_name, range_info in cov_json["ranges"].items():
            shape = tuple(range_info["shape"])  # (ny, nx, nt)
            raw = np.array(range_info["values"], dtype=float).reshape(shape)
            # CoverageJSON axes order: y, x, t → transpose to (t, y, x) for xarray
            data_vars[param_name] = (["time", "y", "x"], np.moveaxis(raw, 2, 0))

        ds = xr.Dataset(
            data_vars,
            coords={"time": t_coords, "y": y_coords, "x": x_coords},
        )
        return ds

    @staticmethod
    def metadata() -> dict | None:
        """Fetch collection metadata from the API."""
        from hydromodpy.data.common.api_client import get_json

        return get_json(f"{BASE_URL}/")
