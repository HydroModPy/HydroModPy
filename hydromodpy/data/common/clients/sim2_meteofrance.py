"""Canonical SIM2 (Meteo-France SAFRAN-ISBA surface reanalysis) EDR client.

The SIM2 reanalysis is produced by Meteo-France. It is exposed as a
CF-compliant EDR endpoint:

    https://api.geosas.fr/edr/collections/safran-isba/

This hosting has no rate limit, no API key requirement, and exposes
NetCDF4 directly. It is the canonical source for HydroModPy.

`Sim2EDRClient` performs raw HTTP queries; `Sim2MeteoFranceClient` adds
the user-friendly variable naming used by the rest of the codebase.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from hydromodpy.core.logging import get_logger
# SIM2 data distributed via geosas.fr
from hydromodpy.data.common.clients.sim2_edr import BASE_URL, Sim2EDRClient

logger = get_logger(__name__)

SIM2_BASE_URL = BASE_URL

VAR_MAPPING: dict[str, str] = {
    "DLI_Q": "solarradiation",
    "DRAINC_Q": "recharge",
    "ETP_Q": "potentialevapotranspiration",
    "FF_Q": "wind",
    "HU_Q": "relative_moisture",
    "PRELIQ_Q": "liquidprecipitation",
    "PRENEI_Q": "solidprecipitation",
    "SSI_Q": "visibleradiation",
    "SWI_Q": "soilmoistureindex",
    "TINF_H_Q": "min_temperature",
    "TSUP_H_Q": "max_temperature",
    "T_Q": "temperature",
}

REVERSE_VAR_MAPPING: dict[str, str] = {v: k for k, v in VAR_MAPPING.items()}


def user_names_to_sim2(names: str | list[str]) -> list[str]:
    """Convert user-friendly variable names to SIM2 API variable names.

    ``'solarradiation' -> 'DLI_Q'``. Unknown names pass through unchanged.
    """
    if isinstance(names, str):
        items = [v.strip() for v in names.split(",")]
    else:
        items = [str(v).strip() for v in names]
    return [REVERSE_VAR_MAPPING.get(v, v) for v in items if v]


def sim2_to_user_names(names: str | list[str]) -> list[str]:
    """Inverse of :func:`user_names_to_sim2`."""
    if isinstance(names, str):
        items = [v.strip() for v in names.split(",")]
    else:
        items = [str(v).strip() for v in names]
    return [VAR_MAPPING.get(v, v) for v in items if v]


class Sim2MeteoFranceClient(Sim2EDRClient):
    """Canonical SIM2 (Meteo-France) client accepting user-friendly variable names.

    Thin wrapper around :class:`Sim2EDRClient` that translates
    user-friendly variable names (``recharge``, ``temperature``, ...)
    into the SIM2 codes (``DRAINC_Q``, ``T_Q``, ...) expected by the API.
    """

    def fetch_cube(self, *, parameters: list[str]) -> Any:
        return super().fetch_cube(parameters=user_names_to_sim2(parameters))

    def fetch_point(
        self,
        *,
        x: float,
        y: float,
        parameters: list[str],
    ) -> dict:
        return super().fetch_point(
            x=x,
            y=y,
            parameters=user_names_to_sim2(parameters),
        )


def fetch_sim2_cube(
    *,
    bbox: tuple[float, float, float, float],
    date_range: str,
    variables: list[str],
    crs: str = "EPSG:2154",
    output_format: str = "Netcdf4",
    save_dir: Optional[str | Path] = None,
) -> Any:
    """Fetch a SIM2 (Meteo-France) data cube.

    Convenience helper returning an ``xarray.Dataset`` when
    ``output_format='Netcdf4'``, or a CoverageJSON dict otherwise.
    """
    client = Sim2MeteoFranceClient(
        bbox=bbox, crs=crs, date_range=date_range, output_format=output_format,
    )
    result = client.fetch_cube(parameters=variables)
    if save_dir is not None and output_format == "Netcdf4":
        save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)
        start, end = [s.strip().replace("-", "") for s in date_range.split("/")]
        for sim2_var in user_names_to_sim2(variables):
            if hasattr(result, "data_vars") and sim2_var in result.data_vars:
                user_name = VAR_MAPPING.get(sim2_var, sim2_var)
                out = save_dir / f"{user_name}_SIM2_ID_{start}_{end}_D.nc"
                result[[sim2_var]].to_netcdf(out)
                logger.info("Saved %s to %s", sim2_var, out)
    return result
