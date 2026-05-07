"""Optional hydraulic-property tables keyed by geology zones."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile

_SUPPORTED_HYDRAULIC_VALUE_SOURCES = {"inline", "csv"}


def _validate_hydraulic_scalar(
    value: object,
    *,
    label: str,
) -> float | str | None:
    """Normalize one hydraulic-property scalar coming from TOML or CSV."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError(f"{label} must be numeric or a non-empty string.")
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text == "":
        raise ValueError(f"{label} cannot be empty when provided.")
    return text


class MeshCatchmentHydraulicPropertyMapping(HydroModelBase):
    """Zone-key to property mapping contract used by bundle export."""

    values_source: Annotated[str, Profile.USER] = Field(
        default="inline",
        description=(
            "Source of the geology-key to property mapping. "
            "Use 'inline' for TOML dictionaries or 'csv' for an external table."
        ),
    )
    values: Annotated[dict[str, object] | None, Profile.USER] = Field(
        default=None,
        description=(
            "Inline mapping from geology zone key to property value. "
            "Keys must match the normalized `zone_key` values exported by the geology loader."
        ),
    )
    values_csv_file: Annotated[str | None, Profile.DEV] = Field(
        default=None,
        description=(
            "CSV file used when values_source='csv'. "
            "Relative paths are resolved from the launcher TOML directory."
        ),
    )
    csv_key_column: Annotated[str, Profile.DEV] = Field(
        default="zone_key",
        description="CSV column containing geology zone keys.",
    )
    csv_value_column: Annotated[str, Profile.DEV] = Field(
        default="value",
        description="CSV column containing numeric property values.",
    )
    default_value: Annotated[object | None, Profile.USER] = Field(
        default=None,
        description=(
            "Fallback value applied when one geology zone has no explicit mapping. "
            "Leave empty to keep exported cell values undefined for unmapped zones."
        ),
    )

    @field_validator("values_source")
    @classmethod
    def _validate_values_source(cls, value: object) -> str:
        token = str(value).strip().lower()
        if token not in _SUPPORTED_HYDRAULIC_VALUE_SOURCES:
            allowed = ", ".join(sorted(_SUPPORTED_HYDRAULIC_VALUE_SOURCES))
            raise ValueError(f"values_source must be one of: {allowed}.")
        return token

    @field_validator("values")
    @classmethod
    def _validate_values(cls, value: object) -> dict[str, float | str] | None:
        if value is None:
            return None
        mapping = dict(value)
        if len(mapping) == 0:
            raise ValueError("values cannot be empty when provided.")
        out: dict[str, float | str] = {}
        for raw_key, raw_value in mapping.items():
            key = str(raw_key).strip()
            if key == "":
                raise ValueError("values cannot contain empty geology keys.")
            normalized = _validate_hydraulic_scalar(
                raw_value,
                label=f"values[{key!r}]",
            )
            if normalized is None:
                raise ValueError(f"values[{key!r}] cannot be null.")
            out[key] = normalized
        return out

    @field_validator("values_csv_file")
    @classmethod
    def _validate_values_csv_file(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if text == "":
            raise ValueError("values_csv_file cannot be empty when provided.")
        return text

    @field_validator("csv_key_column", "csv_value_column")
    @classmethod
    def _validate_csv_column(cls, value: object) -> str:
        text = str(value).strip()
        if text == "":
            raise ValueError("CSV column names cannot be empty.")
        return text

    @field_validator("default_value")
    @classmethod
    def _validate_default_value(cls, value: object) -> float | str | None:
        return _validate_hydraulic_scalar(value, label="default_value")

    @model_validator(mode="after")
    def _validate_mapping_payload(self) -> MeshCatchmentHydraulicPropertyMapping:
        if self.values_source == "inline":
            if self.values is None and self.default_value is None:
                raise ValueError("values or default_value is required when values_source='inline'.")
            return self
        if self.values_csv_file is None:
            raise ValueError("values_csv_file is required when values_source='csv'.")
        return self


class MeshCatchmentHydraulicConductivity(MeshCatchmentHydraulicPropertyMapping):
    """Conductivity mapping exported on mesh cells."""

    unit: Annotated[str, Profile.DEV] = Field(
        default="m/s",
        min_length=1,
        description=(
            "Input unit used by conductivity values. "
            "Exported bundle values are always converted to `m/s`."
        ),
    )


class MeshCatchmentStorageCoefficient(MeshCatchmentHydraulicPropertyMapping):
    """Storage-coefficient mapping exported on mesh cells."""


class MeshCatchmentHydraulicPropertiesConfig(HydroModelBase):
    """Optional hydraulic properties derived from the geology zonation."""

    conductivity: Annotated[MeshCatchmentHydraulicConductivity | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional hydraulic-conductivity mapping by geology key. "
            "When provided, the bundle exports one `hydraulic_conductivity_m_s` value per cell."
        ),
    )
    storage_coefficient: Annotated[MeshCatchmentStorageCoefficient | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional storage-coefficient mapping by geology key. "
            "When provided, the bundle exports one `storage_coefficient` value per cell."
        ),
    )

    @model_validator(mode="after")
    def _validate_at_least_one_property(
        self,
    ) -> MeshCatchmentHydraulicPropertiesConfig:
        if self.conductivity is None and self.storage_coefficient is None:
            raise ValueError(
                "hydraulic_properties must define conductivity and/or storage_coefficient."
            )
        return self


__all__ = [
    "MeshCatchmentHydraulicConductivity",
    "MeshCatchmentHydraulicPropertiesConfig",
    "MeshCatchmentHydraulicPropertyMapping",
    "MeshCatchmentStorageCoefficient",
]
