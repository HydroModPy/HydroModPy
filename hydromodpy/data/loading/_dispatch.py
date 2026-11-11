"""The one registry of the ``[data]`` variables: ``variable_name -> VariableSpec``.

Used by the user-facing :class:`DataStore` facade (``store.py``), by the
plan-driven :class:`DataLoader` (``loader.py``), by the validation of ``[data]``
(``config_schema.py``) and by the workspace scaffold. Adding a variable means
adding one entry to :data:`VARIABLE_SPECS`, then the lists that ``loading/README.md``
names.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class VariableSpec:
    """Declarative spec for a data variable.

    ``config_module`` and ``variable_module`` name, as text, where the config
    class and the variable class live. A thin family shares one flat module
    (``sim2_series``, ``forcing_series``, ``lake_series``, ``user_rasters``), a rich
    variable has its own folder.

    The folder ``<workspace>/data/<variable>/`` is built from the other columns:
    ``category`` picks the README and the example files, ``kind`` is the scanner of
    the files (``"timeseries"``, ``"raster"``, ``"vector"`` or ``"table"``),
    ``unit`` and ``label`` say what the folder holds. The token in the file names is
    the variable name unless ``file_prefix`` says another.

    ``cfg.date_start`` / ``cfg.date_end`` always resolve ``project_period``
    when both are set. ``period_source`` picks the fallback when they are not:
    - ``"config"``: no fallback, ``project_period`` stays ``None`` and the
      variable uses the native coverage of its sources.
    - ``"simulation_or_overview"``: the simulation window first, then the
      ``[overview]`` dates (water_quality).

    ``export_stable_subdir`` triggers a post-load ``variable.export`` into
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
    category: str
    kind: str
    unit: str
    label: str
    file_prefix: str | None = None
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
        category="dem",
        kind="raster",
        unit="m",
        label="digital elevation model",
        loader_method="_load_dem_data",
    ),
    "geology": VariableSpec(
        config_module="hydromodpy.data.variables.geology.config",
        config_class="GeologyConfig",
        variable_module="hydromodpy.data.variables.geology.variable",
        variable_class="GeologyVariable",
        category="geology",
        kind="vector",
        unit="-",
        label="geological map",
        loader_method="_load_geology_data",
    ),
    "hydrography": VariableSpec(
        config_module="hydromodpy.data.variables.hydrography.config",
        config_class="HydrographyConfig",
        variable_module="hydromodpy.data.variables.hydrography.variable",
        variable_class="HydrographyVariable",
        category="hydrography",
        kind="vector",
        unit="-",
        label="river network",
        loader_method="_load_hydrography_data",
    ),
    "oceanic": VariableSpec(
        config_module="hydromodpy.data.variables.oceanic.config",
        config_class="OceanicConfig",
        variable_module="hydromodpy.data.variables.oceanic.variable",
        variable_class="OceanicVariable",
        category="grid",
        kind="timeseries",
        unit="m",
        label="sea level",
    ),
    "intermittency": VariableSpec(
        config_module="hydromodpy.data.variables.intermittency.config",
        config_class="IntermittencyConfig",
        variable_module="hydromodpy.data.variables.intermittency.variable",
        variable_class="IntermittencyVariable",
        category="point",
        kind="timeseries",
        unit="code",
        label="flow state (ONDE)",
        export_stable_subdir="intermittency",
    ),
    "hydrometry": VariableSpec(
        config_module="hydromodpy.data.variables.hydrometry.config",
        config_class="HydrometryConfig",
        variable_module="hydromodpy.data.variables.hydrometry.variable",
        variable_class="HydrometryVariable",
        category="point",
        kind="timeseries",
        unit="m3/s",
        label="river discharge",
    ),
    "piezometry": VariableSpec(
        config_module="hydromodpy.data.variables.piezometry.config",
        config_class="PiezometryConfig",
        variable_module="hydromodpy.data.variables.piezometry.variable",
        variable_class="PiezometryVariable",
        category="point",
        kind="timeseries",
        unit="m",
        label="groundwater levels",
    ),
    "water_quality": VariableSpec(
        config_module="hydromodpy.data.variables.water_quality.config",
        config_class="WaterQualityConfig",
        variable_module="hydromodpy.data.variables.water_quality.variable",
        variable_class="WaterQualityVariable",
        category="point",
        kind="timeseries",
        unit="mg/L",
        label="water quality",
        file_prefix="waterquality",
        apply_simulation_window=False,
        period_source="simulation_or_overview",
    ),
    "recharge": VariableSpec(
        config_module="hydromodpy.data.variables.recharge.config",
        config_class="RechargeConfig",
        variable_module="hydromodpy.data.variables.recharge.variable",
        variable_class="RechargeVariable",
        category="grid",
        kind="timeseries",
        unit="mm/day",
        label="recharge",
    ),
    "runoff": VariableSpec(
        config_module="hydromodpy.data.variables.sim2_series",
        config_class="RunoffConfig",
        variable_module="hydromodpy.data.variables.sim2_series",
        variable_class="RunoffVariable",
        category="grid",
        kind="timeseries",
        unit="mm/day",
        label="runoff",
    ),
    "precipitation": VariableSpec(
        config_module="hydromodpy.data.variables.forcing_series",
        config_class="PrecipitationConfig",
        variable_module="hydromodpy.data.variables.forcing_series",
        variable_class="PrecipitationVariable",
        category="grid",
        kind="timeseries",
        unit="mm/day",
        label="precipitation",
    ),
    "etp": VariableSpec(
        config_module="hydromodpy.data.variables.forcing_series",
        config_class="EtpConfig",
        variable_module="hydromodpy.data.variables.forcing_series",
        variable_class="EtpVariable",
        category="grid",
        kind="timeseries",
        unit="mm/day",
        label="evapotranspiration",
    ),
    "temperature": VariableSpec(
        config_module="hydromodpy.data.variables.sim2_series",
        config_class="TemperatureConfig",
        variable_module="hydromodpy.data.variables.sim2_series",
        variable_class="TemperatureVariable",
        category="grid",
        kind="timeseries",
        unit="degC",
        label="temperature",
    ),
    "wind": VariableSpec(
        config_module="hydromodpy.data.variables.sim2_series",
        config_class="WindConfig",
        variable_module="hydromodpy.data.variables.sim2_series",
        variable_class="WindVariable",
        category="grid",
        kind="timeseries",
        unit="m/s",
        label="wind",
    ),
    "humidity": VariableSpec(
        config_module="hydromodpy.data.variables.sim2_series",
        config_class="HumidityConfig",
        variable_module="hydromodpy.data.variables.sim2_series",
        variable_class="HumidityVariable",
        category="grid",
        kind="timeseries",
        unit="%",
        label="humidity",
    ),
    "radiation": VariableSpec(
        config_module="hydromodpy.data.variables.forcing_series",
        config_class="RadiationConfig",
        variable_module="hydromodpy.data.variables.forcing_series",
        variable_class="RadiationVariable",
        category="grid",
        kind="timeseries",
        unit="MJ/m2/j",
        label="radiation",
    ),
    "soil_moisture": VariableSpec(
        config_module="hydromodpy.data.variables.sim2_series",
        config_class="SoilMoistureConfig",
        variable_module="hydromodpy.data.variables.sim2_series",
        variable_class="SoilMoistureVariable",
        category="grid",
        kind="timeseries",
        unit="%",
        label="soil moisture",
    ),
    "lake_geometry": VariableSpec(
        config_module="hydromodpy.data.variables.lake_geometry.config",
        config_class="LakeGeometryConfig",
        variable_module="hydromodpy.data.variables.lake_geometry.variable",
        variable_class="LakeGeometryVariable",
        category="hydrography",
        kind="vector",
        unit="-",
        label="lake or reservoir outline",
        apply_simulation_window=False,
    ),
    "lake_bathymetry": VariableSpec(
        config_module="hydromodpy.data.variables.lake_bathymetry.config",
        config_class="LakeBathymetryConfig",
        variable_module="hydromodpy.data.variables.lake_bathymetry.variable",
        variable_class="LakeBathymetryVariable",
        category="raster",
        kind="raster",
        unit="m",
        label="lake bathymetry",
        apply_simulation_window=False,
    ),
    "lake_abacus": VariableSpec(
        config_module="hydromodpy.data.variables.lake_abacus.config",
        config_class="LakeAbacusConfig",
        variable_module="hydromodpy.data.variables.lake_abacus.variable",
        variable_class="LakeAbacusVariable",
        category="table",
        kind="table",
        unit="m|m3|m2",
        label="stage-volume-area table",
        apply_simulation_window=False,
    ),
    "lake_levels": VariableSpec(
        config_module="hydromodpy.data.variables.lake_series",
        config_class="LakeLevelsConfig",
        variable_module="hydromodpy.data.variables.lake_series",
        variable_class="LakeLevelsVariable",
        category="point",
        kind="timeseries",
        unit="m",
        label="observed lake levels",
    ),
    "lake_inflow": VariableSpec(
        config_module="hydromodpy.data.variables.lake_series",
        config_class="LakeInflowConfig",
        variable_module="hydromodpy.data.variables.lake_series",
        variable_class="LakeInflowVariable",
        category="point",
        kind="timeseries",
        unit="m3/s",
        label="inflow to the lake",
    ),
    "lake_outflow": VariableSpec(
        config_module="hydromodpy.data.variables.lake_series",
        config_class="LakeOutflowConfig",
        variable_module="hydromodpy.data.variables.lake_series",
        variable_class="LakeOutflowVariable",
        category="point",
        kind="timeseries",
        unit="m3/s",
        label="outflow from the lake",
    ),
    "lake_withdrawal": VariableSpec(
        config_module="hydromodpy.data.variables.lake_series",
        config_class="LakeWithdrawalConfig",
        variable_module="hydromodpy.data.variables.lake_series",
        variable_class="LakeWithdrawalVariable",
        category="point",
        kind="timeseries",
        unit="m3/s",
        label="withdrawals from the lake",
    ),
    "substratum": VariableSpec(
        config_module="hydromodpy.data.variables.user_rasters",
        config_class="SubstratumConfig",
        variable_module="hydromodpy.data.variables.user_rasters",
        variable_class="SubstratumVariable",
        category="raster",
        kind="raster",
        unit="m",
        label="substratum (base of the aquifer)",
        apply_simulation_window=False,
    ),
    "layer_base": VariableSpec(
        config_module="hydromodpy.data.variables.user_rasters",
        config_class="LayerBaseConfig",
        variable_module="hydromodpy.data.variables.user_rasters",
        variable_class="LayerBaseVariable",
        category="raster",
        kind="raster",
        unit="m",
        label="base of a layer (elevation)",
        apply_simulation_window=False,
    ),
    "soil_capacity": VariableSpec(
        config_module="hydromodpy.data.variables.user_rasters",
        config_class="SoilCapacityConfig",
        variable_module="hydromodpy.data.variables.user_rasters",
        variable_class="SoilCapacityVariable",
        category="raster",
        kind="raster",
        unit="mm",
        label="soil available water capacity",
        apply_simulation_window=False,
    ),
    "crossings": VariableSpec(
        config_module="hydromodpy.data.variables.crossings.config",
        config_class="CrossingsConfig",
        variable_module="hydromodpy.data.variables.crossings.variable",
        variable_class="CrossingsVariable",
        category="crossings",
        kind="vector",
        unit="-",
        label="river crossing structures",
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
    """Resolve and return the variable class for ``variable_name``."""
    spec = get_spec(variable_name)
    mod = importlib.import_module(spec.variable_module)
    return getattr(mod, spec.variable_class)


def get_config_class(variable_name: str) -> Any:
    """Resolve and return the config class for ``variable_name``."""
    spec = get_spec(variable_name)
    mod = importlib.import_module(spec.config_module)
    return getattr(mod, spec.config_class)
