"""Internal contracts used while exporting catchment mesh bundles."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from hydromodpy.data.variables.geology.config import validate_geology_config_data


def _optional_text(raw_value: object) -> str | None:
    """Return one stripped string or ``None`` when empty."""

    if raw_value is None:
        return None
    text = str(raw_value).strip()
    return None if text == "" else text


@dataclass(frozen=True)
class GeologyFractionRow:
    """One non-zero geology fraction attached to one exported cell."""

    cell_id: int
    geology_key: str
    fraction: float

    def to_mapping(self) -> dict[str, object]:
        return {
            "cell_id": int(self.cell_id),
            "geology_key": str(self.geology_key),
            "fraction": float(self.fraction),
        }


@dataclass(frozen=True)
class GeologyProjectionPayload:
    """Resolved geology payload projected from the source support onto the mesh."""

    available: bool
    field_id: str | None = None
    zone_keys: tuple[str, ...] = ()
    cell_zone_keys: tuple[str, ...] = ()
    cell_zone_codes: tuple[int, ...] = ()
    fraction_rows: tuple[GeologyFractionRow, ...] = ()
    source_kind: str | None = None
    cell_samples_per_axis: int | None = None


@dataclass(frozen=True)
class CatchmentBundleGeologySourceConfig:
    """Typed source block used by bundle geology export."""

    path: str
    kind: str
    code_field: str | None = None
    reference_raster_path: str | None = None


@dataclass(frozen=True)
class CatchmentBundleGeologyExportConfig:
    """Typed geology contract consumed by bundle export."""

    field_id: str | None
    source: CatchmentBundleGeologySourceConfig
    cell_samples_per_axis: int

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
    ) -> "CatchmentBundleGeologyExportConfig":
        normalized = validate_geology_config_data(dict(payload))
        source_raw = dict(normalized["source"])
        return cls(
            field_id=_optional_text(normalized.get("id")),
            source=CatchmentBundleGeologySourceConfig(
                path=str(source_raw["path"]),
                kind=str(source_raw["kind"]),
                code_field=_optional_text(source_raw.get("code_field")),
                reference_raster_path=_optional_text(
                    source_raw.get("reference_raster_path")
                ),
            ),
            cell_samples_per_axis=int(normalized.get("cell_samples_per_axis", 8)),
        )


@dataclass(frozen=True)
class HydraulicPropertyPayload:
    """Resolved hydraulic property mapped by geology zone and then by cell."""

    property_name: str
    available: bool
    values_by_zone_key: dict[str, float] = field(default_factory=dict)
    default_value: float | None = None
    values_source: str | None = None
    values_csv_file: str | None = None
    zone_keys_defined: tuple[str, ...] = ()
    output_field: str | None = None
    unit: str | None = None
    cell_values: tuple[float | None, ...] = ()
    missing_zone_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class HydraulicPropertiesPayload:
    """Resolved conductivity and storage payloads projected to cell values."""

    available: bool
    averaging: str
    conductivity: HydraulicPropertyPayload
    storage_coefficient: HydraulicPropertyPayload


@dataclass(frozen=True)
class CatchmentBundleHydraulicPropertyConfig:
    """Typed hydraulic property mapping consumed by bundle export."""

    values_source: str = "inline"
    values: dict[str, object] = field(default_factory=dict)
    values_csv_file: str | None = None
    csv_key_column: str = "zone_key"
    csv_value_column: str = "value"
    default_value: object | None = None
    unit: str | None = None

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
    ) -> "CatchmentBundleHydraulicPropertyConfig":
        return cls(
            values_source=str(payload.get("values_source", "inline")).strip().lower()
            or "inline",
            values=dict(payload.get("values") or {}),
            values_csv_file=_optional_text(payload.get("values_csv_file")),
            csv_key_column=str(payload.get("csv_key_column", "zone_key")).strip()
            or "zone_key",
            csv_value_column=str(payload.get("csv_value_column", "value")).strip()
            or "value",
            default_value=payload.get("default_value"),
            unit=_optional_text(payload.get("unit")),
        )


@dataclass(frozen=True)
class CatchmentBundleHydraulicPropertiesConfig:
    """Typed hydraulic-properties block consumed by bundle export."""

    conductivity: CatchmentBundleHydraulicPropertyConfig | None = None
    storage_coefficient: CatchmentBundleHydraulicPropertyConfig | None = None

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
    ) -> "CatchmentBundleHydraulicPropertiesConfig":
        conductivity_raw = payload.get("conductivity")
        storage_raw = payload.get("storage_coefficient")
        return cls(
            conductivity=(
                None
                if not isinstance(conductivity_raw, Mapping)
                else CatchmentBundleHydraulicPropertyConfig.from_mapping(
                    conductivity_raw
                )
            ),
            storage_coefficient=(
                None
                if not isinstance(storage_raw, Mapping)
                else CatchmentBundleHydraulicPropertyConfig.from_mapping(storage_raw)
            ),
        )


@dataclass(frozen=True)
class CatchmentBundleSummaryReference:
    """Typed summary fields consulted by bundle export."""

    constraints_mode: str | None = None
    output_summary_json: str | None = None

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
    ) -> "CatchmentBundleSummaryReference":
        return cls(
            constraints_mode=_optional_text(payload.get("constraints_mode")),
            output_summary_json=_optional_text(payload.get("output_summary_json")),
        )


@dataclass(frozen=True)
class CatchmentBundleMetadata:
    """Top-level metadata sidecar written next to one exported mesh bundle."""

    payload: dict[str, Any]

    def to_mapping(self) -> dict[str, Any]:
        return dict(self.payload)


__all__ = [
    "CatchmentBundleMetadata",
    "CatchmentBundleGeologyExportConfig",
    "CatchmentBundleGeologySourceConfig",
    "CatchmentBundleHydraulicPropertiesConfig",
    "CatchmentBundleHydraulicPropertyConfig",
    "CatchmentBundleSummaryReference",
    "GeologyFractionRow",
    "GeologyProjectionPayload",
    "HydraulicPropertiesPayload",
    "HydraulicPropertyPayload",
]
