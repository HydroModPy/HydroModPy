"""
TOML/CSV factories for `FieldParam`.

Module-level loaders that turn TOML/CSV inputs into a fully-resolved mapping,
then build a `FieldParam` value-holder via `FieldParam.from_dict`.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hydromodpy.spatial.field.core._field_param_resolution import (
    _load_values_mapping_csv,
    _resolve_relative_to,
)
from hydromodpy.spatial.field.core.field_param import SUPPORTED_KINDS, FieldParam
from hydromodpy.spatial.field.core.field_param_config import (
    validate_field_param_toml_data,
    validate_resolved_field_param_data,
)


def _get_nested_section(payload: Mapping[str, Any], dotted_path: str) -> Mapping[str, Any]:
    """Resolve a nested TOML section from a dotted path."""
    current: Any = payload
    for token in str(dotted_path).split("."):
        if not isinstance(current, Mapping) or token not in current:
            raise KeyError(f"Missing TOML section '{dotted_path}'")
        current = current[token]
    if not isinstance(current, Mapping):
        raise ValueError(f"TOML section '{dotted_path}' must be a mapping")
    return current


def _optional_nested_section(
    payload: Mapping[str, Any], dotted_path: str
) -> Mapping[str, Any] | None:
    """Return section mapping if present, else None."""
    try:
        return _get_nested_section(payload, dotted_path)
    except (KeyError, ValueError):
        return None


def field_param_from_toml(toml_path: str | Path, section: str = "field") -> FieldParam:
    """
    Build `FieldParam` from a TOML file.

    Expected layouts:

    Single-section homogeneous:
        [field]
        id = "K"
        kind = "homogeneous"
        unit = "m/s"
        value = 10.0

    Single-section heterogeneous:
        [field]
        id = "S"
        kind = "heterogeneous"
        unit = "-"
        values = { granite = 10.0, micaschists = 3.5 }
        field_spatial_id = "field_square"

    Field with vertical profile:
        [field]
        id = "K"
        kind = "homogeneous"
        unit = "m/s"
        value = 12.5

        [field_vertical_profile]
        mode = "exponential"
        characteristic_depth = 30.0

    Heterogeneous values from CSV (for long geology-property tables):
        [field]
        id = "K"
        kind = "heterogeneous"
        values_source = "csv"
        values_csv_file = "geology_property_values.csv"
        csv_key_column = "zone_key"
        csv_value_column = "property_value"
        field_spatial_id = "field_geology"
    """
    path = Path(toml_path).resolve()
    with path.open("rb") as stream:
        payload = tomllib.load(stream)
    payload = validate_field_param_toml_data(payload)
    section_key = str(section).strip()
    section_cfg = _get_nested_section(payload, section_key)

    merged: dict[str, Any] = {}

    if "." in section_key:
        parent = section_key.rsplit(".", 1)[0]
        common_parent = _optional_nested_section(payload, f"{parent}.field_common")
        if common_parent is not None:
            raise ValueError(
                f"TOML section '{parent}.field_common' is no longer supported. "
                f"Move shared keys to '{parent}.field'."
            )
    common_root = _optional_nested_section(payload, "field_common")
    if common_root is not None:
        raise ValueError(
            "TOML section 'field_common' is no longer supported. Move shared keys to 'field'."
        )

    if section_key != "field":
        common_field = _optional_nested_section(payload, "field")
        if common_field is not None:
            merged.update(dict(common_field))

    merged.update(dict(section_cfg))

    leaf = section_key.rsplit(".", 1)[-1].strip().lower()
    if leaf == "homogeneous":
        merged["kind"] = "homogeneous"
    elif leaf == "heterogeneous":
        merged["kind"] = "heterogeneous"

    kind_raw = merged.get("kind")
    if kind_raw is not None:
        kind_key = str(kind_raw).strip().lower()
        if kind_key in SUPPORTED_KINDS:
            target_leaf = f"field_{kind_key}"
            if leaf not in {target_leaf, kind_key}:
                candidate_sections: list[str] = []
                if "." in section_key:
                    parent = section_key.rsplit(".", 1)[0]
                    candidate_sections.append(f"{parent}.{target_leaf}")
                candidate_sections.append(target_leaf)
                for candidate in candidate_sections:
                    specific_cfg = _optional_nested_section(payload, candidate)
                    if specific_cfg is not None:
                        merged.update(dict(specific_cfg))
                        break

    if leaf not in ("field_vertical_profile", "vertical_profile"):
        vertical_sections: list[str] = []
        if "." in section_key:
            parent = section_key.rsplit(".", 1)[0]
            vertical_sections.extend(
                [
                    f"{parent}.field_vertical_profile",
                    f"{parent}.vertical_profile",
                ]
            )
        vertical_sections.extend(("field_vertical_profile", "vertical_profile"))
        for candidate in vertical_sections:
            vertical_cfg = _optional_nested_section(payload, candidate)
            if vertical_cfg is not None:
                merged["vertical_profile"] = dict(vertical_cfg)
                break

    kind_raw = merged.get("kind")
    if kind_raw is not None and str(kind_raw).strip().lower() == "heterogeneous":
        value_source = str(merged.get("values_source", "inline")).strip().lower()
        if value_source == "csv":
            csv_file = merged.get("values_csv_file")
            if csv_file is None or str(csv_file).strip() == "":
                raise KeyError(
                    "Heterogeneous field with values_source='csv' requires 'values_csv_file'"
                )
            csv_path = _resolve_relative_to(csv_file, base_dir=path.parent)
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

    resolved = validate_resolved_field_param_data(merged)
    return FieldParam.from_dict(resolved)
