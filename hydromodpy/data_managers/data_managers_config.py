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

from hydromodpy.config.param_level import ParamLevel
from hydromodpy.watershed_legacy.geology_config import GeologyConfig


SUPPORTED_DATA_MANAGER_TYPES = (
    "geology",
    "hydrography",
    "hydrometry",
    "intermittency",
    "oceanic",
    "piezometry",
)


class OceanicConfig(BaseModel):
    """Configuration for oceanic support and mean sea-level acquisition."""

    model_config = ConfigDict(extra="forbid")

    oceanic_path: Annotated[str | None, ParamLevel("user")] = Field(
        default=None,
        description=(
            "Optional folder containing local oceanic support files used by "
            "Oceanic.extract_local_data. Relative paths are resolved from the "
            "TOML file directory."
        ),
    )
    msl_source: Annotated[Literal["auto", "local", "web"], ParamLevel("user")] = Field(
        default="auto",
        description=(
            "Mean sea-level source policy. "
            "'local' reads the CSV from msl_local_csv, "
            "'web' queries SHOM, "
            "'auto' tries local first then falls back to web."
        ),
    )
    msl_local_csv: Annotated[str | None, ParamLevel("user")] = Field(
        default=None,
        description=(
            "Path to a pre-downloaded SHOM CSV file used when msl_source is "
            "'local' or 'auto'. Relative paths are resolved from the TOML "
            "file directory."
        ),
    )
    msl_use_simulation_time_window: Annotated[bool, ParamLevel("user")] = Field(
        default=False,
        description=(
            "If true, derive msl_start_date and msl_end_date from "
            "[simulation.time] canonical window. With simulation.time.mode='explicit', "
            "the window comes from [simulation.time].start_datetime/end_datetime; "
            "with mode='from_modflow', it is resolved from flow solver tgrid settings. If "
            "[simulation.time] is missing or unresolved, fallback to the explicit "
            "msl_start_date/msl_end_date values below."
        ),
    )
    msl_start_date: Annotated[str, ParamLevel("user")] = Field(
        default="2003-01-01",
        description=(
            "Inclusive mean sea-level start date in ISO format (YYYY-MM-DD). "
            "Used directly when msl_use_simulation_time_window=false or as "
            "fallback otherwise."
        ),
    )
    msl_end_date: Annotated[str, ParamLevel("user")] = Field(
        default="2003-01-30",
        description=(
            "Inclusive mean sea-level end date in ISO format (YYYY-MM-DD). "
            "Used directly when msl_use_simulation_time_window=false or as "
            "fallback otherwise."
        ),
    )
    msl_default: Annotated[float, ParamLevel("user")] = Field(
        default=0.0,
        description=(
            "Fallback mean sea-level value used when acquisition fails "
            "(SI unit: meter)."
        ),
    )

    @field_validator("oceanic_path", "msl_local_csv", mode="before")
    @classmethod
    def _normalize_optional_paths(cls, value):
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("msl_source", mode="before")
    @classmethod
    def _normalize_msl_source(cls, value):
        if value is None:
            return "auto"
        text = str(value).strip().lower()
        if text not in {"auto", "local", "web"}:
            raise ValueError("data.oceanic.msl_source must be 'auto', 'local' or 'web'")
        return text

    @field_validator("msl_start_date", "msl_end_date", mode="before")
    @classmethod
    def _normalize_dates(cls, value):
        text = str(value).strip()
        if not text:
            raise ValueError("data.oceanic date values cannot be empty")
        return text


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
            "'geology', 'hydrography', 'hydrometry', 'intermittency', "
            "'oceanic', 'piezometry'."
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
    geology: Annotated[GeologyConfig | None, ParamLevel("user")] = Field(
        default=None,
        description="Geology configuration used when 'geology' is listed in data.types.",
    )
    hydrography: Annotated[dict[str, Any] | None, ParamLevel("dev")] = Field(
        default=None,
        description="Reserved configuration mapping for hydrography data-manager.",
    )
    hydrometry: Annotated[dict[str, Any] | None, ParamLevel("dev")] = Field(
        default=None,
        description="Reserved configuration mapping for hydrometry data-manager.",
    )
    intermittency: Annotated[dict[str, Any] | None, ParamLevel("dev")] = Field(
        default=None,
        description="Reserved configuration mapping for intermittency data-manager.",
    )
    oceanic: Annotated[OceanicConfig | None, ParamLevel("user")] = Field(
        default=None,
        description=(
            "Oceanic configuration used when 'oceanic' is listed in data.types."
        ),
    )
    piezometry: Annotated[dict[str, Any] | None, ParamLevel("dev")] = Field(
        default=None,
        description="Reserved configuration mapping for piezometry data-manager.",
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
        # - active oceanic uses its dedicated typed schema when provided,
        # - remaining active families must be mappings until typed schemas exist.
        for type_name in self.types:
            if type_name == "geology":
                if self.geology is None:
                    self.geology = GeologyConfig()
                continue
            if type_name == "oceanic":
                if self.oceanic is not None and not isinstance(self.oceanic, OceanicConfig):
                    raise ValueError("data.oceanic must follow OceanicConfig schema")
                continue
            section_value = getattr(self, type_name)
            if section_value is not None and not isinstance(section_value, dict):
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

        # Validate/normalize only active families to keep config permissive for
        # inactive optional sections.
        for type_name in normalized_types:
            if type_name == "geology":
                geology_payload = payload.get("geology")
                if geology_payload is None:
                    payload["geology"] = GeologyConfig()
                    continue
                if not isinstance(geology_payload, Mapping):
                    raise ValueError("TOML section 'data.geology' must be a mapping")
                geology_dict = dict(geology_payload)
                _resolve_section_paths(geology_dict, GeologyConfig, base_dir)
                payload["geology"] = GeologyConfig(**geology_dict)
                continue
            if type_name == "oceanic":
                oceanic_payload = payload.get("oceanic")
                if oceanic_payload is None:
                    continue
                if not isinstance(oceanic_payload, Mapping):
                    raise ValueError("TOML section 'data.oceanic' must be a mapping")
                payload["oceanic"] = OceanicConfig.model_validate(dict(oceanic_payload))
                continue

            section_value = payload.get(type_name)
            if section_value is None:
                continue
            if not isinstance(section_value, Mapping):
                raise ValueError(f"TOML section 'data.{type_name}' must be a mapping")
            payload[type_name] = dict(section_value)

        return cls.model_validate(payload)


def _is_path_field(annotation) -> bool:
    """Return ``True`` for ``Path`` or ``Optional[Path]`` annotations."""
    if annotation is Path:
        return True
    return Path in getattr(annotation, "__args__", ())


def _resolve_section_paths(
    data: dict[str, Any],
    model_cls: type[BaseModel],
    base: Path,
) -> None:
    """Resolve relative paths and `~` in one config section dict (in-place)."""
    for field_name, field_info in model_cls.model_fields.items():
        if not _is_path_field(field_info.annotation):
            continue
        value = data.get(field_name)
        if isinstance(value, str) and value:
            p = Path(value).expanduser()
            if not p.is_absolute():
                p = (base / p).resolve()
            data[field_name] = str(p)
