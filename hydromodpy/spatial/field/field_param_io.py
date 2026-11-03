"""
TOML factory for `FieldParam`.

`field_param_from_toml` reads one field-parameter section of a TOML file,
resolves it like a project section and builds a `FieldParam` value-holder via
`FieldParam.from_dict`.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hydromodpy.core.exceptions import ConfigMissingError, ConfigValidationError
from hydromodpy.spatial.field.field_param import FieldParam
from hydromodpy.spatial.field.field_param_config import resolve_field_param_config_payload
from hydromodpy.spatial.field.field_spatial import get_nested_section


def field_param_from_toml(toml_path: str | Path, section: str = "field") -> FieldParam:
    """
    Build `FieldParam` from the `[field]` table that `section` names in a TOML file.

    `section` is the dotted path of a `[field]` table, `"field"` at the root of
    the file or `"flow.param.K.field"` in a project file. The table that holds
    it is the parameter payload: the `[field]` table and its optional
    `[field_vertical_profile]` sibling, nothing else. A nested `[field]` with
    no `id` takes the key of its parent table, as `[flow.param.<id>]` does in a
    project. A relative `values_csv_file` is read from the folder of the file.

    Homogeneous:
        [field]
        id = "K"
        kind = "homogeneous"
        unit = "m/s"
        value = 1e-5

    Heterogeneous, one value per zone of a spatial field:
        [field]
        id = "S"
        kind = "heterogeneous"
        unit = "-"
        values = { granite = 0.1, micaschists = 0.05 }
        field_spatial_id = "field_square"

    With a vertical profile, in a project file:
        [flow.param.K.field]
        kind = "homogeneous"
        unit = "m/s"
        value = 1e-5

        [flow.param.K.field_vertical_profile]
        kind = "exponential"
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
        document = tomllib.load(stream)
    section_key = str(section).strip()
    parent_key, _, leaf = section_key.rpartition(".")
    if leaf != "field":
        raise ConfigValidationError(
            f"Section '{section_key}' of {path} names no [field] table. Name the "
            "table that holds id, kind and the values, such as 'field' or "
            "'flow.param.K.field'."
        )
    payload = _section_payload(document, parent_key, section_key=section_key, path=path)
    field_table = payload["field"]
    param_id = None
    if isinstance(field_table, Mapping) and "id" not in field_table:
        if not parent_key:
            raise ConfigMissingError(
                f'[field] of {path} has no id. Write the parameter name in it, such as id = "K".'
            )
        param_id = parent_key.rsplit(".", 1)[-1]
    resolved = resolve_field_param_config_payload(
        payload,
        param_id=param_id,
        base_dir=path.parent,
        section_label=parent_key or "field",
    )
    return FieldParam.from_dict(resolved)


def _section_payload(
    document: Mapping[str, Any], parent_key: str, *, section_key: str, path: Path
) -> Mapping[str, Any]:
    """The table that holds the `[field]` table `section_key` names."""
    try:
        payload = get_nested_section(document, parent_key) if parent_key else document
    except (KeyError, ValueError):
        payload = {}
    if "field" not in payload:
        raise ConfigMissingError(f"{path} has no section [{section_key}]")
    return payload
