"""Single source of truth for ``variable_name -> (config, manager)`` dispatch.

Used by both the user-facing :class:`DataStore` facade (``store.py``) and the
plan-driven :class:`DataLoader` (``loader.py``). Adding a new
variable means adding one entry to :data:`VARIABLE_SPECS`, then the lists that
``loading/README.md`` names.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class VariableSpec:
    """Declarative spec for a data variable.

    ``cfg.date_start`` / ``cfg.date_end`` always resolve ``project_period``
    when both are set. ``period_source`` picks the fallback when they are not:
    - ``"config"``: no fallback, ``project_period`` stays ``None`` and the
      manager uses the native coverage of its sources.
    - ``"simulation_or_overview"``: the simulation window first, then the
      ``[overview]`` dates (water_quality).

    ``export_stable_subdir`` triggers a post-load ``manager.export`` into
    ``core.state.scratch.preprocessing_dir(<workspace>) / <subdir>`` (currently intermittency).

    ``loader_method`` names a dedicated method on
    :class:`DataLoader` for variables with unique side-effects
    (``dem``, ``geology``, ``hydrography``). Generic variables leave it
    ``None`` and go through the standard generic load path.
    """

    config_module: str
    config_class: str
    variable_module: str
    variable_class: str
    apply_simulation_window: bool = True
    period_source: str = "config"
    export_stable_subdir: str | None = None
    loader_method: str | None = None


VARIABLE_SPECS: dict[str, VariableSpec] = {
    "dem": VariableSpec(
        config_module="hydromodpy.data.variables.dem.config",
        config_class="DemConfig",
        variable_module="hydromodpy.data.variables.dem.variable",
        variable_class="DemVariable",
        loader_method="_load_dem_data",
    ),
    "geology": VariableSpec(
        config_module="hydromodpy.data.variables.geology.config",
        config_class="GeologyConfig",
        variable_module="hydromodpy.data.variables.geology.variable",
        variable_class="GeologyVariable",
        loader_method="_load_geology_data",
    ),
    "hydrography": VariableSpec(
        config_module="hydromodpy.data.variables.hydrography.config",
        config_class="HydrographyConfig",
        variable_module="hydromodpy.data.variables.hydrography.variable",
        variable_class="HydrographyVariable",
        loader_method="_load_hydrography_data",
    ),
    "oceanic": VariableSpec(
        config_module="hydromodpy.data.variables.oceanic.config",
        config_class="OceanicConfig",
        variable_module="hydromodpy.data.variables.oceanic.variable",
        variable_class="OceanicVariable",
    ),
    "intermittency": VariableSpec(
        config_module="hydromodpy.data.variables.intermittency.config",
        config_class="IntermittencyConfig",
        variable_module="hydromodpy.data.variables.intermittency.variable",
        variable_class="IntermittencyVariable",
        export_stable_subdir="intermittency",
    ),
    "hydrometry": VariableSpec(
        config_module="hydromodpy.data.variables.hydrometry.config",
        config_class="HydrometryConfig",
        variable_module="hydromodpy.data.variables.hydrometry.variable",
        variable_class="HydrometryVariable",
    ),
    "piezometry": VariableSpec(
        config_module="hydromodpy.data.variables.piezometry.config",
        config_class="PiezometryConfig",
        variable_module="hydromodpy.data.variables.piezometry.variable",
        variable_class="PiezometryVariable",
    ),
    "water_quality": VariableSpec(
        config_module="hydromodpy.data.variables.water_quality.config",
        config_class="WaterQualityConfig",
        variable_module="hydromodpy.data.variables.water_quality.variable",
        variable_class="WaterQualityVariable",
        apply_simulation_window=False,
        period_source="simulation_or_overview",
    ),
    "recharge": VariableSpec(
        config_module="hydromodpy.data.variables.recharge.config",
        config_class="RechargeConfig",
        variable_module="hydromodpy.data.variables.recharge.variable",
        variable_class="RechargeVariable",
    ),
    "runoff": VariableSpec(
        config_module="hydromodpy.data.variables.runoff.config",
        config_class="RunoffConfig",
        variable_module="hydromodpy.data.variables.runoff.variable",
        variable_class="RunoffVariable",
    ),
    "precipitation": VariableSpec(
        config_module="hydromodpy.data.variables.precipitation.config",
        config_class="PrecipitationConfig",
        variable_module="hydromodpy.data.variables.precipitation.variable",
        variable_class="PrecipitationVariable",
    ),
    "etp": VariableSpec(
        config_module="hydromodpy.data.variables.etp.config",
        config_class="EtpConfig",
        variable_module="hydromodpy.data.variables.etp.variable",
        variable_class="EtpVariable",
    ),
    "temperature": VariableSpec(
        config_module="hydromodpy.data.variables.temperature.config",
        config_class="TemperatureConfig",
        variable_module="hydromodpy.data.variables.temperature.variable",
        variable_class="TemperatureVariable",
    ),
    "wind": VariableSpec(
        config_module="hydromodpy.data.variables.wind.config",
        config_class="WindConfig",
        variable_module="hydromodpy.data.variables.wind.variable",
        variable_class="WindVariable",
    ),
    "humidity": VariableSpec(
        config_module="hydromodpy.data.variables.humidity.config",
        config_class="HumidityConfig",
        variable_module="hydromodpy.data.variables.humidity.variable",
        variable_class="HumidityVariable",
    ),
    "radiation": VariableSpec(
        config_module="hydromodpy.data.variables.radiation.config",
        config_class="RadiationConfig",
        variable_module="hydromodpy.data.variables.radiation.variable",
        variable_class="RadiationVariable",
    ),
    "soil_moisture": VariableSpec(
        config_module="hydromodpy.data.variables.soil_moisture.config",
        config_class="SoilMoistureConfig",
        variable_module="hydromodpy.data.variables.soil_moisture.variable",
        variable_class="SoilMoistureVariable",
    ),
    "lake_geometry": VariableSpec(
        config_module="hydromodpy.data.variables.lake_geometry.config",
        config_class="LakeGeometryConfig",
        variable_module="hydromodpy.data.variables.lake_geometry.variable",
        variable_class="LakeGeometryVariable",
        apply_simulation_window=False,
    ),
    "lake_bathymetry": VariableSpec(
        config_module="hydromodpy.data.variables.lake_bathymetry.config",
        config_class="LakeBathymetryConfig",
        variable_module="hydromodpy.data.variables.lake_bathymetry.variable",
        variable_class="LakeBathymetryVariable",
        apply_simulation_window=False,
    ),
    "lake_abacus": VariableSpec(
        config_module="hydromodpy.data.variables.lake_abacus.config",
        config_class="LakeAbacusConfig",
        variable_module="hydromodpy.data.variables.lake_abacus.variable",
        variable_class="LakeAbacusVariable",
        apply_simulation_window=False,
    ),
    "lake_levels": VariableSpec(
        config_module="hydromodpy.data.variables.lake_levels.config",
        config_class="LakeLevelsConfig",
        variable_module="hydromodpy.data.variables.lake_levels.variable",
        variable_class="LakeLevelsVariable",
    ),
    "lake_inflow": VariableSpec(
        config_module="hydromodpy.data.variables.lake_inflow.config",
        config_class="LakeInflowConfig",
        variable_module="hydromodpy.data.variables.lake_inflow.variable",
        variable_class="LakeInflowVariable",
    ),
    "lake_outflow": VariableSpec(
        config_module="hydromodpy.data.variables.lake_outflow.config",
        config_class="LakeOutflowConfig",
        variable_module="hydromodpy.data.variables.lake_outflow.variable",
        variable_class="LakeOutflowVariable",
    ),
    "lake_withdrawal": VariableSpec(
        config_module="hydromodpy.data.variables.lake_withdrawal.config",
        config_class="LakeWithdrawalConfig",
        variable_module="hydromodpy.data.variables.lake_withdrawal.variable",
        variable_class="LakeWithdrawalVariable",
    ),
    "substratum": VariableSpec(
        config_module="hydromodpy.data.variables.substratum.config",
        config_class="SubstratumConfig",
        variable_module="hydromodpy.data.variables.substratum.variable",
        variable_class="SubstratumVariable",
        apply_simulation_window=False,
    ),
    "layer_base": VariableSpec(
        config_module="hydromodpy.data.variables.layer_base.config",
        config_class="LayerBaseConfig",
        variable_module="hydromodpy.data.variables.layer_base.variable",
        variable_class="LayerBaseVariable",
        apply_simulation_window=False,
    ),
    "soil_capacity": VariableSpec(
        config_module="hydromodpy.data.variables.soil_capacity.config",
        config_class="SoilCapacityConfig",
        variable_module="hydromodpy.data.variables.soil_capacity.variable",
        variable_class="SoilCapacityVariable",
        apply_simulation_window=False,
    ),
    "crossings": VariableSpec(
        config_module="hydromodpy.data.variables.crossings.config",
        config_class="CrossingsConfig",
        variable_module="hydromodpy.data.variables.crossings.variable",
        variable_class="CrossingsVariable",
        apply_simulation_window=False,
    ),
}


def get_spec(variable_name: str) -> VariableSpec:
    """Return the spec for ``variable_name``. Raise ``KeyError`` if unknown."""
    spec = VARIABLE_SPECS.get(variable_name)
    if spec is None:
        raise KeyError(f"Unknown variable: {variable_name!r}")
    return spec


def variable_class_for(variable_name: str) -> Any:
    """Resolve and return the manager class for ``variable_name``."""
    spec = get_spec(variable_name)
    mod = importlib.import_module(spec.variable_module)
    return getattr(mod, spec.variable_class)


def get_config_class(variable_name: str) -> Any:
    """Resolve and return the config class for ``variable_name``."""
    spec = get_spec(variable_name)
    mod = importlib.import_module(spec.config_module)
    return getattr(mod, spec.config_class)
