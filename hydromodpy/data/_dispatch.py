"""Single source of truth for ``variable_name -> (config, manager)`` dispatch.

Used by both the user-facing :class:`DataStore` facade (``store.py``) and the
plan-driven :class:`DataManagersRuntimeLoader` (``loader.py``). Adding a new
variable means adding one entry to :data:`VARIABLE_SPECS` and nothing else.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class VariableSpec:
    """Declarative spec for a data variable.

    ``period_source`` picks how to resolve ``project_period``:
    - ``"config"``: read ``cfg.date_start`` / ``cfg.date_end``.
    - ``"simulation_or_overview"``: try the simulation window first, then
      fall back to ``[overview]`` dates (water_quality).

    ``export_stable_subdir`` triggers a post-load ``manager.export`` into
    ``<workspace>/<PREPROCESSING_DIR>/<subdir>/`` (currently intermittency).

    ``loader_method`` names a dedicated method on
    :class:`DataManagersRuntimeLoader` for variables with unique side-effects
    (``dem``, ``geology``, ``hydrography``). Generic variables leave it
    ``None`` and go through the standard generic load path.
    """

    config_module: str
    config_class: str
    manager_module: str
    manager_class: str
    apply_simulation_window: bool = True
    period_source: str = "config"
    export_stable_subdir: str | None = None
    loader_method: str | None = None


VARIABLE_SPECS: dict[str, VariableSpec] = {
    "dem": VariableSpec(
        config_module="hydromodpy.data.variables.dem.config",
        config_class="DemConfig",
        manager_module="hydromodpy.data.variables.dem.manager",
        manager_class="DemManager",
        loader_method="_load_dem_data",
    ),
    "geology": VariableSpec(
        config_module="hydromodpy.data.variables.geology.config",
        config_class="GeologyConfig",
        manager_module="hydromodpy.data.variables.geology.manager",
        manager_class="GeologyManager",
        loader_method="_load_geology_data",
    ),
    "hydrography": VariableSpec(
        config_module="hydromodpy.data.variables.hydrography.config",
        config_class="HydrographyConfig",
        manager_module="hydromodpy.data.variables.hydrography.manager",
        manager_class="HydrographyManager",
        loader_method="_load_hydrography_data",
    ),
    "oceanic": VariableSpec(
        config_module="hydromodpy.data.variables.oceanic.config",
        config_class="OceanicConfig",
        manager_module="hydromodpy.data.variables.oceanic.manager",
        manager_class="OceanicManager",
    ),
    "intermittency": VariableSpec(
        config_module="hydromodpy.data.variables.intermittency.config",
        config_class="IntermittencyConfig",
        manager_module="hydromodpy.data.variables.intermittency.manager",
        manager_class="IntermittencyManager",
        export_stable_subdir="intermittency",
    ),
    "hydrometry": VariableSpec(
        config_module="hydromodpy.data.variables.hydrometry.config",
        config_class="HydrometryConfig",
        manager_module="hydromodpy.data.variables.hydrometry.manager",
        manager_class="HydrometryManager",
    ),
    "piezometry": VariableSpec(
        config_module="hydromodpy.data.variables.piezometry.config",
        config_class="PiezometryConfig",
        manager_module="hydromodpy.data.variables.piezometry.manager",
        manager_class="PiezometryManager",
    ),
    "water_quality": VariableSpec(
        config_module="hydromodpy.data.variables.water_quality.config",
        config_class="WaterQualityConfig",
        manager_module="hydromodpy.data.variables.water_quality.manager",
        manager_class="WaterQualityManager",
        apply_simulation_window=False,
        period_source="simulation_or_overview",
    ),
    "recharge": VariableSpec(
        config_module="hydromodpy.data.variables.recharge.config",
        config_class="RechargeConfig",
        manager_module="hydromodpy.data.variables.recharge.manager",
        manager_class="RechargeManager",
    ),
    "runoff": VariableSpec(
        config_module="hydromodpy.data.variables.runoff.config",
        config_class="RunoffConfig",
        manager_module="hydromodpy.data.variables.runoff.manager",
        manager_class="RunoffManager",
    ),
    "precipitation": VariableSpec(
        config_module="hydromodpy.data.variables.precipitation.config",
        config_class="PrecipitationConfig",
        manager_module="hydromodpy.data.variables.precipitation.manager",
        manager_class="PrecipitationManager",
    ),
    "etp": VariableSpec(
        config_module="hydromodpy.data.variables.etp.config",
        config_class="EtpConfig",
        manager_module="hydromodpy.data.variables.etp.manager",
        manager_class="EtpManager",
    ),
    "temperature": VariableSpec(
        config_module="hydromodpy.data.variables.temperature.config",
        config_class="TemperatureConfig",
        manager_module="hydromodpy.data.variables.temperature.manager",
        manager_class="TemperatureManager",
    ),
    "wind": VariableSpec(
        config_module="hydromodpy.data.variables.wind.config",
        config_class="WindConfig",
        manager_module="hydromodpy.data.variables.wind.manager",
        manager_class="WindManager",
    ),
    "humidity": VariableSpec(
        config_module="hydromodpy.data.variables.humidity.config",
        config_class="HumidityConfig",
        manager_module="hydromodpy.data.variables.humidity.manager",
        manager_class="HumidityManager",
    ),
    "radiation": VariableSpec(
        config_module="hydromodpy.data.variables.radiation.config",
        config_class="RadiationConfig",
        manager_module="hydromodpy.data.variables.radiation.manager",
        manager_class="RadiationManager",
    ),
    "soil_moisture": VariableSpec(
        config_module="hydromodpy.data.variables.soil_moisture.config",
        config_class="SoilMoistureConfig",
        manager_module="hydromodpy.data.variables.soil_moisture.manager",
        manager_class="SoilMoistureManager",
    ),
}


def get_spec(variable_name: str) -> VariableSpec:
    """Return the spec for ``variable_name``. Raise ``KeyError`` if unknown."""
    spec = VARIABLE_SPECS.get(variable_name)
    if spec is None:
        raise KeyError(f"Unknown variable: {variable_name!r}")
    return spec


def get_manager_class(variable_name: str) -> Any:
    """Resolve and return the manager class for ``variable_name``."""
    spec = get_spec(variable_name)
    mod = importlib.import_module(spec.manager_module)
    return getattr(mod, spec.manager_class)


def get_config_class(variable_name: str) -> Any:
    """Resolve and return the config class for ``variable_name``."""
    spec = get_spec(variable_name)
    mod = importlib.import_module(spec.config_module)
    return getattr(mod, spec.config_class)
