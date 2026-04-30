"""Hydraulic property mapping helpers used by the catchment mesh bundle export.

These helpers parse inline or CSV-driven property mappings, average values onto
each mesh cell using geology fractions and produce the
``HydraulicPropertiesPayload`` consumed by the bundle orchestrator.
"""

from __future__ import annotations

import csv
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from hydromodpy.core.units.hydraulic_conductivity import parse_to_m_per_s
from hydromodpy.spatial.mesh.gmsh_grid._geology_bundle_export import _build_fractions_by_cell
from hydromodpy.spatial.mesh.gmsh_grid.bundle_export_contracts import (
    CatchmentBundleHydraulicPropertiesConfig,
    CatchmentBundleHydraulicPropertyConfig,
    GeologyFractionRow,
    GeologyProjectionPayload,
    HydraulicPropertiesPayload,
    HydraulicPropertyPayload,
)
from hydromodpy.spatial.protocols import get_geology_data_source


def _resolve_config_relative_path(
    raw_path: str | Path,
    *,
    config_path: str | Path | None,
) -> Path:
    """Resolve one possibly config-relative path to an absolute filesystem path."""
    path = Path(str(raw_path)).expanduser()
    if path.is_absolute():
        return path.resolve()
    if config_path is None:
        return path.resolve()
    base_path = Path(config_path).resolve()
    base_dir = base_path.parent if base_path.suffix != "" else base_path
    return (base_dir / path).resolve()


def _load_zone_value_mapping_csv(
    csv_path: str | Path,
    *,
    key_column: str = "zone_key",
    value_column: str = "value",
) -> dict[str, float]:
    """Load one zone-key to numeric-value mapping from CSV."""
    key_col = str(key_column).strip()
    val_col = str(value_column).strip()
    if key_col == "" or val_col == "":
        raise ValueError("CSV key/value column names cannot be empty.")

    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV values file not found: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        headers = [str(header).strip() for header in (reader.fieldnames or [])]
        if key_col not in headers:
            raise KeyError(
                f"CSV values file '{path}' is missing key column '{key_col}'. "
                f"Available columns: {headers}"
            )
        if val_col not in headers:
            raise KeyError(
                f"CSV values file '{path}' is missing value column '{val_col}'. "
                f"Available columns: {headers}"
            )

        values: dict[str, float] = {}
        for line_number, row in enumerate(reader, start=2):
            key = get_geology_data_source().normalize_zone_key(row.get(key_col, ""))
            if key == "":
                continue
            if key in values:
                raise ValueError(
                    f"Duplicate key '{key}' in CSV mapping '{path}' at line {line_number}."
                )
            raw_value = row.get(val_col, "")
            try:
                values[key] = float(raw_value)
            except Exception as exc:
                raise ValueError(
                    f"Invalid numeric value in CSV mapping '{path}' line {line_number}: "
                    f"column '{val_col}' -> {raw_value!r}"
                ) from exc

    if len(values) == 0:
        raise ValueError(f"CSV values file '{path}' does not define any key/value pair.")
    return values


def _parse_storage_coefficient_value(
    raw_value: object,
    *,
    label: str,
) -> float:
    if isinstance(raw_value, bool):
        raise TypeError(f"{label} must be numeric.")
    try:
        return float(raw_value)
    except Exception as exc:
        raise ValueError(f"{label} must be numeric, got {raw_value!r}.") from exc


def _normalize_property_mapping_values(
    raw_values: Mapping[str, object],
    *,
    value_parser,
    label_prefix: str,
) -> dict[str, float]:
    """Normalize one inline or CSV-derived mapping keyed by geology zone."""
    out: dict[str, float] = {}
    for raw_key, raw_value in dict(raw_values).items():
        key = get_geology_data_source().normalize_zone_key(raw_key)
        if key == "":
            raise ValueError(f"{label_prefix} contains one empty geology key.")
        if key in out:
            raise ValueError(
                f"{label_prefix} contains duplicate geology key '{key}' after normalization."
            )
        out[key] = float(value_parser(raw_value, label=f"{label_prefix}[{key!r}]"))
    return out


def _resolve_hydraulic_property_mapping(
    property_cfg: CatchmentBundleHydraulicPropertyConfig | None,
    *,
    property_name: str,
    config_path: str | Path | None,
    value_parser,
) -> HydraulicPropertyPayload:
    """Resolve one optional hydraulic property mapping section.

    The returned payload is summary-oriented: it carries parsed values together
    with provenance information useful in `metadata.json`.
    """
    if property_cfg is None:
        return HydraulicPropertyPayload(
            property_name=property_name,
            available=False,
        )

    values_source = str(property_cfg.values_source).strip().lower()
    if values_source == "csv":
        values_csv_path = _resolve_config_relative_path(
            str(property_cfg.values_csv_file),
            config_path=config_path,
        )
        raw_values = _load_zone_value_mapping_csv(
            values_csv_path,
            key_column=str(property_cfg.csv_key_column),
            value_column=str(property_cfg.csv_value_column),
        )
    else:
        values_csv_path = None
        raw_values = dict(property_cfg.values)

    values_by_zone_key = _normalize_property_mapping_values(
        raw_values,
        value_parser=value_parser,
        label_prefix=f"{property_name}.values",
    )
    raw_default_value = property_cfg.default_value
    default_value = (
        None
        if raw_default_value is None
        else float(value_parser(raw_default_value, label=f"{property_name}.default_value"))
    )
    return HydraulicPropertyPayload(
        property_name=property_name,
        available=bool(values_by_zone_key) or default_value is not None,
        values_by_zone_key=values_by_zone_key,
        default_value=default_value,
        values_source=values_source,
        values_csv_file=None if values_csv_path is None else str(values_csv_path),
        zone_keys_defined=tuple(sorted(values_by_zone_key)),
    )


def _compute_weighted_cell_property_values(
    *,
    n_cells: int,
    cell_zone_keys: tuple[str, ...],
    fraction_rows: tuple[GeologyFractionRow, ...],
    property_payload: HydraulicPropertyPayload,
) -> tuple[tuple[float | None, ...], list[str]]:
    """Average per-zone property values onto cells using geology fractions."""
    if not property_payload.available:
        return tuple(None for _ in range(int(n_cells))), []

    values_by_zone_key = {
        get_geology_data_source().normalize_zone_key(key): float(value)
        for key, value in dict(property_payload.values_by_zone_key).items()
    }
    default_value = property_payload.default_value
    default_float = None if default_value is None else float(default_value)
    fractions_by_cell = _build_fractions_by_cell(fraction_rows)
    missing_zone_keys: set[str] = set()
    cell_values: list[float | None] = []

    for cell_idx in range(int(n_cells)):
        fractions = fractions_by_cell.get(int(cell_idx))
        if not fractions:
            dominant_key = (
                ""
                if cell_idx >= len(cell_zone_keys)
                else get_geology_data_source().normalize_zone_key(cell_zone_keys[cell_idx])
            )
            fractions = [] if dominant_key == "" else [(dominant_key, 1.0)]

        if not fractions:
            cell_values.append(None)
            continue

        weighted_sum = 0.0
        total_fraction = 0.0
        unresolved = False
        for zone_key, fraction in fractions:
            value = values_by_zone_key.get(zone_key, default_float)
            if value is None:
                missing_zone_keys.add(zone_key)
                unresolved = True
                break
            weighted_sum += float(fraction) * float(value)
            total_fraction += float(fraction)
        if unresolved or total_fraction <= 0.0:
            cell_values.append(None)
            continue
        cell_values.append(weighted_sum / total_fraction)

    return tuple(cell_values), sorted(missing_zone_keys)


def _build_hydraulic_properties_payload(
    *,
    mesh,
    geology_payload: GeologyProjectionPayload,
    hydraulic_properties_cfg: CatchmentBundleHydraulicPropertiesConfig | None,
    config_path: str | Path | None,
) -> HydraulicPropertiesPayload:
    """Build conductivity/storage payloads summarized at the cell scale."""
    conductivity_cfg = (
        None if hydraulic_properties_cfg is None else hydraulic_properties_cfg.conductivity
    )
    storage_cfg = (
        None if hydraulic_properties_cfg is None else hydraulic_properties_cfg.storage_coefficient
    )

    conductivity_unit = "m/s"
    if conductivity_cfg is not None and conductivity_cfg.unit is not None:
        conductivity_unit = str(conductivity_cfg.unit).strip() or "m/s"

    conductivity = _resolve_hydraulic_property_mapping(
        conductivity_cfg,
        property_name="conductivity",
        config_path=config_path,
        value_parser=lambda raw, label: parse_to_m_per_s(
            raw,
            location=label,
            default_unit=conductivity_unit,
        )[0],
    )
    storage = _resolve_hydraulic_property_mapping(
        storage_cfg,
        property_name="storage_coefficient",
        config_path=config_path,
        value_parser=_parse_storage_coefficient_value,
    )

    cell_zone_keys = tuple(str(v) for v in geology_payload.cell_zone_keys)
    fraction_rows = tuple(geology_payload.fraction_rows)
    conductivity_values, conductivity_missing = _compute_weighted_cell_property_values(
        n_cells=int(mesh.n_cells),
        cell_zone_keys=cell_zone_keys,
        fraction_rows=fraction_rows,
        property_payload=conductivity,
    )
    storage_values, storage_missing = _compute_weighted_cell_property_values(
        n_cells=int(mesh.n_cells),
        cell_zone_keys=cell_zone_keys,
        fraction_rows=fraction_rows,
        property_payload=storage,
    )

    conductivity_payload = replace(
        conductivity,
        output_field="hydraulic_conductivity_m_s",
        unit="m/s",
        cell_values=conductivity_values,
        missing_zone_keys=tuple(conductivity_missing),
    )
    storage_payload = replace(
        storage,
        output_field="storage_coefficient",
        unit="-",
        cell_values=storage_values,
        missing_zone_keys=tuple(storage_missing),
    )
    return HydraulicPropertiesPayload(
        available=bool(conductivity.available or storage.available),
        averaging="weighted_by_geology_fraction",
        conductivity=conductivity_payload,
        storage_coefficient=storage_payload,
    )
