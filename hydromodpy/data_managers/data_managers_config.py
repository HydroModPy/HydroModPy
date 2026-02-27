from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hydromodpy.config.param_level import ParamLevel
from hydromodpy.watershed.geology_config import GeologyConfig


SUPPORTED_DATA_MANAGER_TYPES = (
    "geology",
    "hydrography",
    "hydrometry",
    "intermittency",
    "oceanic",
    "piezometry",
)


class DataManagersConfig(BaseModel):
    """
    Top-level configuration for data-manager families.

    The `types` list declares which data families are active. For each active
    type, the matching nested section can be validated dynamically:
    - `geology` already uses its dedicated Pydantic model (`GeologyConfig`),
    - the other data families are kept as validated mappings for now, until
      their dedicated schemas are introduced.
    """

    model_config = ConfigDict(extra="forbid")

    types: Annotated[list[str], ParamLevel("user")] = Field(
        default_factory=list,
        description=(
            "Ordered list of active data-manager types. Allowed values: "
            "'geology', 'hydrography', 'hydrometry', 'intermittency', "
            "'oceanic', 'piezometry'."
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
    oceanic: Annotated[dict[str, Any] | None, ParamLevel("dev")] = Field(
        default=None,
        description="Reserved configuration mapping for oceanic data-manager.",
    )
    piezometry: Annotated[dict[str, Any] | None, ParamLevel("dev")] = Field(
        default=None,
        description="Reserved configuration mapping for piezometry data-manager.",
    )

    @field_validator("types", mode="before")
    @classmethod
    def _validate_types_list(cls, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("data.types must be a list of strings")
        return value

    @field_validator("types")
    @classmethod
    def _normalize_types(cls, value: list[str]) -> list[str]:
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

    @model_validator(mode="after")
    def _validate_declared_sections(self) -> "DataManagersConfig":
        for type_name in self.types:
            if type_name == "geology":
                if self.geology is None:
                    self.geology = GeologyConfig()
                continue
            section_value = getattr(self, type_name)
            if section_value is not None and not isinstance(section_value, dict):
                raise ValueError(f"data.{type_name} must be a mapping when provided")
        return self

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

            section_value = payload.get(type_name)
            if section_value is None:
                continue
            if not isinstance(section_value, Mapping):
                raise ValueError(f"TOML section 'data.{type_name}' must be a mapping")
            payload[type_name] = dict(section_value)

        return cls.model_validate(payload)


def _is_path_field(annotation) -> bool:
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
