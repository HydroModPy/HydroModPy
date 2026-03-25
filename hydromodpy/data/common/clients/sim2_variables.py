"""SIM2 (SAFRAN-ISBA) variable registry.

Maps HydroModPy canonical variable names to SIM2 EDR API parameter codes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Sim2Variable:
    """Descriptor for one SIM2 (SAFRAN-ISBA) variable."""

    sim2_code: str
    hydromodpy_name: str
    unit: str
    description: str


SIM2_VARIABLES: dict[str, Sim2Variable] = {
    "recharge": Sim2Variable("DRAINC_Q", "recharge", "mm/day", "Drainage (daily cumul 06-06 UTC)"),
    "runoff": Sim2Variable("RUNC_Q", "runoff", "mm/day", "Runoff (daily cumul 06-06 UTC)"),
    "liquid_precipitation": Sim2Variable("PRELIQ_Q", "liquid_precipitation", "mm/day", "Liquid precipitation (daily cumul 06-06 UTC)"),
    "solid_precipitation": Sim2Variable("PRENEI_Q", "solid_precipitation", "mm/day", "Solid precipitation (daily cumul 06-06 UTC)"),
    "etp": Sim2Variable("ETP_Q", "etp", "mm/day", "Potential evapotranspiration (Penman-Monteith)"),
    "temperature": Sim2Variable("T_Q", "temperature", "degC", "Temperature (daily mean)"),
    "wind": Sim2Variable("FF_Q", "wind", "m/s", "Wind speed (daily mean)"),
    "humidity": Sim2Variable("HU_Q", "humidity", "%", "Relative humidity (daily mean)"),
    "atmospheric_radiation": Sim2Variable("DLI_Q", "atmospheric_radiation", "J/cm2", "Atmospheric radiation (daily cumul)"),
    "visible_radiation": Sim2Variable("SSI_Q", "visible_radiation", "J/cm2", "Visible radiation (daily cumul)"),
    "soil_moisture_index": Sim2Variable("SWI_Q", "soil_moisture_index", "%", "Soil moisture index (daily mean 06-06 UTC)"),
}


def sim2_codes_for(*hydromodpy_names: str) -> list[str]:
    """Return the SIM2 API parameter codes for given HydroModPy variable names."""
    codes = []
    for name in hydromodpy_names:
        var = SIM2_VARIABLES.get(name)
        if var is None:
            raise KeyError(f"Unknown SIM2 variable: {name!r}. Available: {sorted(SIM2_VARIABLES)}")
        codes.append(var.sim2_code)
    return codes
