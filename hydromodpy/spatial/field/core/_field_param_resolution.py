"""Resolve field-parameter TOML payloads into canonical mappings.

Encapsulates mode selection (`homogeneous`/`heterogeneous`), optional
vertical profile extraction, and optional CSV value loading.
"""

from __future__ import annotations

import csv
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hydromodpy.spatial.field.core._field_param_resolved import (
    validate_resolved_field_param_data,
)


def _resolve_relative_to(path_like: str | Path, *, base_dir: Path) -> Path:
    """Resolve one path relative to a base directory if not absolute."""
    raw = Path(str(path_like))
    if raw.is_absolute():
        return raw
    return (base_dir / raw).resolve()


def _load_values_mapping_csv(
    csv_path: str | Path,
    *,
    key_column: str = "zone_key",
    value_column: str = "value",
) -> dict[str, float]:
    """Load one heterogeneous key->value mapping from CSV."""
    key_col = str(key_column).strip()
    val_col = str(value_column).strip()
    if key_col == "" or val_col == "":
        raise ValueError("CSV key/value column names cannot be empty")

    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV values file not found: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        headers = [str(h).strip() for h in (reader.fieldnames or [])]
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
        for i, row in enumerate(reader, start=2):  # 1=header
            key_raw = row.get(key_col, "")
            key = str(key_raw).strip()
            if key == "":
                continue
            if key in values:
                raise ValueError(f"Duplicate key '{key}' in CSV mapping '{path}' at line {i}.")
            raw_value = row.get(val_col, "")
            try:
                value = float(raw_value)
            except Exception as exc:
                raise ValueError(
                    f"Invalid numeric value in CSV mapping '{path}' line {i}: "
                    f"column '{val_col}' -> {raw_value!r}"
                ) from exc
            values[key] = value

    if len(values) == 0:
        raise ValueError(f"CSV values file '{path}' does not define any key/value pair")
    return values


def resolve_field_param_config_payload(
    config_data: Mapping[str, Any],
    *,
    param_id: str | None = None,
    base_dir: Path | None = None,
    section_label: str = "field",
) -> dict[str, Any]:
    """Resolve one field-parameter TOML-like payload into canonical mapping."""
    from hydromodpy.spatial.field.core.field_param_config import (
        validate_field_param_toml_data,
    )

    validated = validate_field_param_toml_data(config_data)

    field_section = validated.get("field")
    if not isinstance(field_section, Mapping):
        raise KeyError(f"{section_label} requires section [{section_label}.field]")

    merged: dict[str, Any] = dict(field_section)
    field_id = str(merged.get("id", "")).strip()
    if param_id is not None:
        if field_id == "":
            merged["id"] = param_id
        elif field_id != param_id:
            raise ValueError(
                f"{section_label}.field.id must match section key '{param_id}', got '{field_id}'"
            )

    kind_raw = merged.get("kind")
    kind_key = str(kind_raw).strip().lower() if kind_raw is not None else None
    if kind_key in ("homogeneous", "heterogeneous"):
        specific_section = validated.get(f"field_{kind_key}")
        if isinstance(specific_section, Mapping):
            merged.update(dict(specific_section))

    vertical_section = validated.get("field_vertical_profile", validated.get("vertical_profile"))
    if isinstance(vertical_section, Mapping):
        merged["vertical_profile"] = dict(vertical_section)

    if kind_key == "heterogeneous":
        value_source = str(merged.get("values_source", "inline")).strip().lower()
        if value_source == "csv":
            csv_file = merged.get("values_csv_file")
            if csv_file is None or str(csv_file).strip() == "":
                raise KeyError(
                    "Heterogeneous field with values_source='csv' requires 'values_csv_file'"
                )
            if base_dir is None:
                raise ValueError(
                    "CSV heterogeneous payload requires 'base_dir' to resolve values_csv_file"
                )
            csv_path = _resolve_relative_to(csv_file, base_dir=base_dir)
            csv_key_column = str(merged.get("csv_key_column", "zone_key"))
            csv_value_column = str(merged.get("csv_value_column", "value"))
            merged["values"] = _load_values_mapping_csv(
                csv_path,
                key_column=csv_key_column,
                value_column=csv_value_column,
            )

    for helper_key in (
        "values_source",
        "values_csv_file",
        "csv_key_column",
        "csv_value_column",
    ):
        merged.pop(helper_key, None)

    return validate_resolved_field_param_data(merged)
