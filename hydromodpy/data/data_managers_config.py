"""Validated schema for the top-level ``[data]`` TOML section.

The role of this module is strictly declarative:

- normalize and validate ``data.types``,
- validate nested sections of active manager families,
- validate dedicated typed sections (currently ``data.geology`` and
  ``data.oceanic``).

Inference rules (domain/process-driven activation) are intentionally
implemented elsewhere in ``data_managers.planner``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hydromodpy.core.config.param_level import ParamLevel
from hydromodpy.data.variables.dem.config import DemConfig
from hydromodpy.data.variables.geology.config import GeologyConfig


SUPPORTED_DATA_MANAGER_TYPES = (
    "dem",
    "etp",
    "geology",
    "humidity",
    "hydrography",
    "hydrometry",
    "intermittency",
    "oceanic",
    "piezometry",
    "precipitation",
    "radiation",
    "recharge",
    "runoff",
    "soil_moisture",
    "temperature",
    "water_quality",
    "wind",
)


from hydromodpy.data.variables.oceanic.config import OceanicConfig  # noqa: E402


class DataManagersConfig(BaseModel):
    """
    Top-level configuration for data-manager families.

    The `types` list declares user-requested data families. The effective
    active set can also include planner-inferred families deduced from other
    sections (domain, flow) depending on `inference_mode`.

    For each active type, the matching nested section can be validated dynamically:
    - `geology` already uses its dedicated Pydantic model (`GeologyConfig`),
    - `oceanic` uses `OceanicConfig`,
    - the other data families are kept as validated mappings for now.
    """

    model_config = ConfigDict(extra="forbid")

    types: Annotated[list[str], ParamLevel("user")] = Field(
        default_factory=list,
        description=(
            "Ordered list of data-manager types explicitly requested in [data]. "
            "The launcher may append inferred types deduced from other sections "
            "(for example domain.zone_ids, flow.active_bc). "
            "Allowed values: "
            + ", ".join(f"'{t}'" for t in SUPPORTED_DATA_MANAGER_TYPES) + "."
        ),
    )
    inference_mode: Annotated[Literal["warn", "strict"], ParamLevel("dev")] = Field(
        default="warn",
        description=(
            "Policy applied when the planner infers types not explicitly listed "
            "in data.types. "
            "'warn': keep inferred types and continue even if data.<type> is missing. "
            "'strict': raise when an inferred type has no explicit data.<type> section "
            "(except geology, which can use its default typed config)."
        ),
    )
    dem: Annotated[DemConfig | None, ParamLevel("user")] = Field(
        default=None,
        description="DEM configuration used when 'dem' is listed in data.types.",
    )
    geology: Annotated[GeologyConfig | None, ParamLevel("user")] = Field(
        default=None,
        description="Geology configuration used when 'geology' is listed in data.types.",
    )
    hydrography: Annotated["HydrographyConfig | None", ParamLevel("user")] = Field(
        default=None,
        description="Hydrography configuration (stream network vector data).",
    )
    hydrometry: Annotated["HydrometryConfig | None", ParamLevel("user")] = Field(
        default=None,
        description="Hydrometry configuration (discharge time-series).",
    )
    intermittency: Annotated["IntermittencyConfig | None", ParamLevel("user")] = Field(
        default=None,
        description="Intermittency configuration (ONDE stream flow-state observations).",
    )
    oceanic: Annotated[OceanicConfig | None, ParamLevel("user")] = Field(
        default=None,
        description=(
            "Oceanic configuration used when 'oceanic' is listed in data.types."
        ),
    )
    piezometry: Annotated["PiezometryConfig | None", ParamLevel("user")] = Field(
        default=None,
        description="Piezometry configuration (groundwater level time-series).",
    )
    water_quality: Annotated["WaterQualityConfig | None", ParamLevel("user")] = Field(
        default=None,
        description="Water quality configuration (physico-chemical parameters).",
    )
    recharge: Annotated["RechargeConfig | None", ParamLevel("user")] = Field(
        default=None,
        description="Recharge configuration (drainage / soil infiltration time series).",
    )
    runoff: Annotated["RunoffConfig | None", ParamLevel("user")] = Field(
        default=None,
        description="Runoff configuration (surface runoff time series).",
    )
    precipitation: Annotated["PrecipitationConfig | None", ParamLevel("user")] = Field(
        default=None,
        description="Precipitation configuration (liquid and solid precipitation).",
    )
    etp: Annotated["EtpConfig | None", ParamLevel("user")] = Field(
        default=None,
        description="ETP configuration (potential evapotranspiration).",
    )
    temperature: Annotated["TemperatureConfig | None", ParamLevel("user")] = Field(
        default=None,
        description="Temperature configuration (air temperature time series).",
    )
    wind: Annotated["WindConfig | None", ParamLevel("user")] = Field(
        default=None,
        description="Wind configuration (wind speed time series).",
    )
    humidity: Annotated["HumidityConfig | None", ParamLevel("user")] = Field(
        default=None,
        description="Humidity configuration (relative humidity time series).",
    )
    radiation: Annotated["RadiationConfig | None", ParamLevel("user")] = Field(
        default=None,
        description="Radiation configuration (atmospheric and visible radiation).",
    )
    soil_moisture: Annotated["SoilMoistureConfig | None", ParamLevel("user")] = Field(
        default=None,
        description="Soil moisture configuration (soil moisture index).",
    )

    @field_validator("types", mode="before")
    @classmethod
    def _validate_types_list(cls, value):
        # Accept explicit omission as "no type declared".
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("data.types must be a list of strings")
        return value

    @field_validator("types")
    @classmethod
    def _normalize_types(cls, value: list[str]) -> list[str]:
        # Canonicalization policy: trim/lowercase + keep first occurrence order.
        out: list[str] = []
        seen: set[str] = set()
        for raw_item in value:
            type_name = str(raw_item).strip().lower()
            if type_name == "":
                raise ValueError("data.types cannot contain empty values")
            if type_name not in SUPPORTED_DATA_MANAGER_TYPES:
                allowed = ", ".join(SUPPORTED_DATA_MANAGER_TYPES)
                raise ValueError(
                    f"Unsupported data type '{type_name}'. Allowed values: {allowed}"
                )
            if type_name in seen:
                continue
            seen.add(type_name)
            out.append(type_name)
        return out

    @field_validator("inference_mode", mode="before")
    @classmethod
    def _normalize_inference_mode(cls, value):
        if value is None:
            return "warn"
        text = str(value).strip().lower()
        if text not in {"warn", "strict"}:
            raise ValueError(
                "data.inference_mode must be 'warn' or 'strict'. "
                "'warn' keeps inferred types even when data.<type> is missing; "
                "'strict' requires explicit data.<type> sections."
            )
        return text

    @model_validator(mode="after")
    def _validate_declared_sections(self) -> "DataManagersConfig":
        # Post-validation coherence:
        # - active geology always has a typed config object (default if omitted),
        # - typed configs (oceanic, hydrometry, piezometry, water_quality) are
        #   accepted as BaseModel instances,
        # - remaining untyped families must be mappings.
        for type_name in self.types:
            if type_name == "geology":
                if self.geology is None:
                    self.geology = GeologyConfig()
                continue
            section_value = getattr(self, type_name, None)
            if section_value is None:
                continue
            if isinstance(section_value, BaseModel):
                continue
            if not isinstance(section_value, dict):
                raise ValueError(f"data.{type_name} must be a mapping when provided")
        return self

    def with_resolved_types(
        self,
        resolved_types: Sequence[str],
    ) -> "DataManagersConfig":
        """Return a validated copy using planner-resolved active types.

        This helper is used by the launcher after inference so downstream code
        can continue reading ``cfg.data`` only, without carrying a separate
        unresolved/partial variant.
        """
        normalized_types = self._normalize_types(
            self._validate_types_list(list(resolved_types))
        )
        payload = self.model_dump(mode="python")
        payload["types"] = normalized_types
        # Keep geology behavior symmetrical with declarative path: if geology is
        # activated by inference, ensure a default typed section exists.
        if "geology" in normalized_types and payload.get("geology") is None:
            payload["geology"] = GeologyConfig()
        return type(self).model_validate(payload)

    @classmethod
    def from_toml_section(
        cls,
        section_data: Any,
        *,
        base_dir: Path,
    ) -> "DataManagersConfig":
        """
        Load one `[data]` TOML section and validate nested active sub-sections.

        Dynamic validation rule:
        - if a type is listed in `data.types` and has a dedicated Pydantic
          model, that model is applied here,
        - otherwise the section is validated as a plain mapping for now.
        """
        if section_data is None:
            section_data = {}
        if not isinstance(section_data, Mapping):
            raise ValueError("TOML section must be a mapping for DataManagersConfig")

        payload = dict(section_data)
        raw_types = payload.get("types", [])
        normalized_types = cls._normalize_types(cls._validate_types_list(raw_types))
        payload["types"] = normalized_types

        # Typed config models for data families that have dedicated schemas.
        from hydromodpy.data.variables.hydrography.config import HydrographyConfig
        from hydromodpy.data.variables.hydrometry.config import HydrometryConfig
        from hydromodpy.data.variables.intermittency.config import IntermittencyConfig
        from hydromodpy.data.variables.piezometry.config import PiezometryConfig
        from hydromodpy.data.variables.water_quality.config import WaterQualityConfig
        from hydromodpy.data.variables.recharge.config import RechargeConfig
        from hydromodpy.data.variables.runoff.config import RunoffConfig
        from hydromodpy.data.variables.precipitation.config import PrecipitationConfig
        from hydromodpy.data.variables.etp.config import EtpConfig
        from hydromodpy.data.variables.temperature.config import TemperatureConfig
        from hydromodpy.data.variables.wind.config import WindConfig
        from hydromodpy.data.variables.humidity.config import HumidityConfig
        from hydromodpy.data.variables.radiation.config import RadiationConfig
        from hydromodpy.data.variables.soil_moisture.config import SoilMoistureConfig

        _TYPED_SECTIONS: dict[str, type[BaseModel]] = {
            "dem": DemConfig,
            "geology": GeologyConfig,
            "hydrography": HydrographyConfig,
            "oceanic": OceanicConfig,
            "hydrometry": HydrometryConfig,
            "intermittency": IntermittencyConfig,
            "piezometry": PiezometryConfig,
            "water_quality": WaterQualityConfig,
            "recharge": RechargeConfig,
            "runoff": RunoffConfig,
            "precipitation": PrecipitationConfig,
            "etp": EtpConfig,
            "temperature": TemperatureConfig,
            "wind": WindConfig,
            "humidity": HumidityConfig,
            "radiation": RadiationConfig,
            "soil_moisture": SoilMoistureConfig,
        }

        # Validate/normalize only active families to keep config permissive for
        # inactive optional sections.
        for type_name in normalized_types:
            section_payload = payload.get(type_name)

            if type_name == "geology" and section_payload is None:
                payload["geology"] = GeologyConfig()
                continue

            if section_payload is None:
                continue
            if not isinstance(section_payload, Mapping):
                raise ValueError(f"TOML section 'data.{type_name}' must be a mapping")

            section_dict = dict(section_payload)
            model_cls = _TYPED_SECTIONS.get(type_name)

            if model_cls is not None:
                _resolve_section_paths(section_dict, model_cls, base_dir)
                payload[type_name] = model_cls.model_validate(section_dict)
            else:
                payload[type_name] = section_dict

        # Also validate typed sections that are present even if not in types
        # (e.g. user provides [data.hydrometry] without adding "hydrometry" to types).
        for type_name, model_cls in _TYPED_SECTIONS.items():
            if type_name in normalized_types:
                continue
            section_payload = payload.get(type_name)
            if section_payload is None or isinstance(section_payload, BaseModel):
                continue
            if isinstance(section_payload, Mapping):
                section_dict = dict(section_payload)
                _resolve_section_paths(section_dict, model_cls, base_dir)
                payload[type_name] = model_cls.model_validate(section_dict)

        return cls.model_validate(payload)


def _rebuild_forward_refs() -> None:
    """Resolve forward references for typed data-manager config fields."""
    from hydromodpy.data.variables.hydrography.config import HydrographyConfig
    from hydromodpy.data.variables.hydrometry.config import HydrometryConfig
    from hydromodpy.data.variables.intermittency.config import IntermittencyConfig
    from hydromodpy.data.variables.piezometry.config import PiezometryConfig
    from hydromodpy.data.variables.water_quality.config import WaterQualityConfig
    from hydromodpy.data.variables.recharge.config import RechargeConfig
    from hydromodpy.data.variables.runoff.config import RunoffConfig
    from hydromodpy.data.variables.precipitation.config import PrecipitationConfig
    from hydromodpy.data.variables.etp.config import EtpConfig
    from hydromodpy.data.variables.temperature.config import TemperatureConfig
    from hydromodpy.data.variables.wind.config import WindConfig
    from hydromodpy.data.variables.humidity.config import HumidityConfig
    from hydromodpy.data.variables.radiation.config import RadiationConfig
    from hydromodpy.data.variables.soil_moisture.config import SoilMoistureConfig

    DataManagersConfig.model_rebuild(
        _types_namespace={
            "HydrographyConfig": HydrographyConfig,
            "HydrometryConfig": HydrometryConfig,
            "IntermittencyConfig": IntermittencyConfig,
            "PiezometryConfig": PiezometryConfig,
            "WaterQualityConfig": WaterQualityConfig,
            "RechargeConfig": RechargeConfig,
            "RunoffConfig": RunoffConfig,
            "PrecipitationConfig": PrecipitationConfig,
            "EtpConfig": EtpConfig,
            "TemperatureConfig": TemperatureConfig,
            "WindConfig": WindConfig,
            "HumidityConfig": HumidityConfig,
            "RadiationConfig": RadiationConfig,
            "SoilMoistureConfig": SoilMoistureConfig,
        }
    )


_rebuild_forward_refs()


def _is_path_field(annotation) -> bool:
    """Return ``True`` for ``Path`` or ``Optional[Path]`` annotations."""
    if annotation is Path:
        return True
    return Path in getattr(annotation, "__args__", ())


def _inner_model_type(annotation) -> type[BaseModel] | None:
    """Return the inner BaseModel type for ``list[SomeModel]`` annotations."""
    args = getattr(annotation, "__args__", ())
    for arg in args:
        if isinstance(arg, type) and issubclass(arg, BaseModel):
            return arg
    origin = getattr(annotation, "__origin__", None)
    if origin is list and args:
        inner = args[0]
        if isinstance(inner, type) and issubclass(inner, BaseModel):
            return inner
    return None


def _resolve_section_paths(
    data: dict[str, Any],
    model_cls: type[BaseModel],
    base: Path,
) -> None:
    """Resolve relative paths and `~` in one config section dict (in-place).

    Recurses into ``list[BaseModel]`` fields to resolve paths in nested
    sub-models (e.g. ``sources`` lists containing ``path`` fields).
    """
    for field_name, field_info in model_cls.model_fields.items():
        value = data.get(field_name)
        if _is_path_field(field_info.annotation):
            if isinstance(value, str) and value:
                p = Path(value).expanduser()
                if not p.is_absolute():
                    p = (base / p).resolve()
                data[field_name] = str(p)
            continue

        # Recurse into list[BaseModel] fields (e.g. sources).
        inner_cls = _inner_model_type(field_info.annotation)
        if inner_cls is not None and isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _resolve_section_paths(item, inner_cls, base)
