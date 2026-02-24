"""
Field parameter container supporting homogeneous and heterogeneous values.

`FieldParam` can be built directly from Python mappings or from TOML.
For heterogeneous fields, values are indexed by keys and can be mapped onto an
independent zone-id array (for example produced by `Field.on_mesh(mesh)`).

Didactic overview
-----------------
A field can be described in two ways:

1) Homogeneous:
   - one scalar value everywhere.
   - example: hydraulic conductivity K = 1e-4 everywhere.

2) Heterogeneous:
   - one value per zone/material key.
   - example: {"alluvium": 2e-4, "bedrock": 1e-6}.
   - spatial assignment is handled outside this class.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Mapping

import numpy as np

try:
    from hydromodpy.field.core.field_param_config import (
        validate_field_param_toml_data,
        validate_resolved_field_param_data,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script fallback
    from field_param_config import (  # type: ignore
        validate_field_param_toml_data,
        validate_resolved_field_param_data,
    )

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - fallback for older Python
    import tomli as tomllib  # type: ignore[no-redef]


SUPPORTED_KINDS = ("homogeneous", "heterogeneous")


def _get_nested_section(payload: Mapping[str, Any], dotted_path: str) -> Mapping[str, Any]:
    """
    Resolve a nested TOML section from a dotted path.

    Example:
        dotted_path = "field"
        payload["field"] is returned.
    """
    current: Any = payload
    for token in str(dotted_path).split("."):
        # Move deeper level by level and fail with explicit message on missing key.
        if not isinstance(current, Mapping) or token not in current:
            raise KeyError(f"Missing TOML section '{dotted_path}'")
        current = current[token]
    if not isinstance(current, Mapping):
        raise ValueError(f"TOML section '{dotted_path}' must be a mapping")
    return current


def _optional_nested_section(payload: Mapping[str, Any], dotted_path: str) -> Mapping[str, Any] | None:
    """Return section mapping if present, else None."""
    try:
        return _get_nested_section(payload, dotted_path)
    except (KeyError, ValueError):
        return None


def _resolve_relative_to(path_like: str | Path, *, base_dir: Path) -> Path:
    """
    Resolve one path relative to a base directory if not absolute.
    """
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
    """
    Load one key->value mapping from CSV.

    The CSV must contain at least two columns:
    - one key column (`key_column`),
    - one numeric value column (`value_column`).

    Duplicate keys are rejected to avoid ambiguous parameter assignment.
    """
    key_col = str(key_column).strip()
    val_col = str(value_column).strip()
    if key_col == "" or val_col == "":
        raise ValueError("CSV key/value column names cannot be empty")

    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV values file not found: {path}")

    # `utf-8-sig` gracefully handles files saved with BOM.
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
                raise ValueError(
                    f"Duplicate key '{key}' in CSV mapping '{path}' at line {i}."
                )
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


class FieldParam:
    """
    Describe scalar field values (homogeneous or heterogeneous).

    Parameters
    ----------
    identifier : str
        Logical parameter identifier (examples: `"K"`, `"Sy"`).
    kind : str
        Either `"homogeneous"` or `"heterogeneous"`.
    value : float | None
        Single scalar value for homogeneous fields.
    values_by_key : mapping | None
        Per-key values for heterogeneous fields.
    field_spatial_id : str | None
        Identifier of the geometry field this heterogeneous parameter set must
        be mapped on (example: "field_square").

    Examples
    --------
    Homogeneous:
        >>> p = FieldParam(identifier="K", kind="homogeneous", value=10.0)
        >>> p.to_array(shape=(2, 2))
        array([[10., 10.],
               [10., 10.]])

    Heterogeneous:
        >>> p = FieldParam(
        ...     identifier="K",
        ...     kind="heterogeneous",
        ...     values_by_key={"granite": 12.0, "micaschists": 4.0},
        ...     field_spatial_id="field_square",
        ... )
        >>> p.to_array(zone_ids=["micaschists", "granite"])
        array([ 4., 12.])
    """

    def __init__(
        self,
        *,
        identifier: str,
        kind: str,
        value: float | None = None,
        values_by_key: Mapping[str, float] | None = None,
        field_spatial_id: str | None = None,
    ):
        ident = str(identifier).strip()
        if ident == "":
            raise ValueError("FieldParam requires a non-empty 'identifier'")
        self.identifier = ident

        # Normalize/validate mode first.
        kind_key = str(kind).strip().lower()
        if kind_key not in SUPPORTED_KINDS:
            allowed = ", ".join(SUPPORTED_KINDS)
            raise ValueError(f"Unsupported field kind '{kind}'. Allowed: {allowed}")

        self.kind = kind_key

        if self.kind == "homogeneous":
            # Homogeneous case: exactly one scalar value is required.
            if value is None:
                raise ValueError("Homogeneous field requires 'value'")
            self.value = float(value)
            self.values_by_key = None
            self.field_spatial_id = None
            return

        # Heterogeneous case: dictionary key -> value is required.
        if values_by_key is None:
            raise ValueError("Heterogeneous field requires 'values_by_key'")
        values = {str(k): float(v) for k, v in dict(values_by_key).items()}
        if len(values) == 0:
            raise ValueError("'values_by_key' cannot be empty")
        if field_spatial_id is None or str(field_spatial_id).strip() == "":
            raise ValueError("Heterogeneous field requires 'field_spatial_id'")
        self.value = None
        self.values_by_key = values
        self.field_spatial_id = str(field_spatial_id).strip()

    @property
    def is_homogeneous(self):
        return self.kind == "homogeneous"

    @property
    def is_heterogeneous(self):
        return self.kind == "heterogeneous"

    def to_array(
        self,
        *,
        shape=None,
        x=None,
        y=None,
        zone_ids=None,
        zone_field=None,
    ):
        """
        Materialize field values as a numeric array.

        For homogeneous fields:
        - if `shape` is provided: returns `np.full(shape, value)`,
        - if (`x`, `y`) are provided: uses their shape,
        - if `zone_ids` is provided: uses its shape,
        - else returns scalar `float(value)`.

        For heterogeneous fields:
        - requires `zone_ids`,
        - maps each zone id to its configured value.

        Practical rule
        --------------
        - homogeneous = value-driven,
        - heterogeneous = structure-driven.
        """
        if self.is_homogeneous:
            # If structure is available, fill it with one constant value.
            if x is not None or y is not None:
                if x is None or y is None:
                    raise ValueError("For homogeneous field with coordinates, provide both x and y")
                x_arr = np.asarray(x, dtype=float)
                y_arr = np.asarray(y, dtype=float)
                if x_arr.shape != y_arr.shape:
                    raise ValueError("x and y must have the same shape")
                return np.full(x_arr.shape, float(self.value), dtype=float)
            if zone_ids is not None:
                zone_arr = np.asarray(zone_ids)
                return np.full(zone_arr.shape, float(self.value), dtype=float)
            if shape is not None:
                shape_tuple = tuple(int(v) for v in shape)
                return np.full(shape_tuple, float(self.value), dtype=float)
            # No shape requested: return scalar.
            return float(self.value)

        # Heterogeneous values are mapped independently from geometry.
        if zone_field is not None:
            if not hasattr(zone_field, "cell_values"):
                raise TypeError("zone_field must expose 'cell_values'")
            zone_ids = zone_field.cell_values
        if zone_ids is None:
            raise ValueError("Heterogeneous field requires 'zone_ids'")
        return self.map_zone_ids(zone_ids)

    def to_mesh_field(
        self,
        field_discretization=None,
        *,
        mesh=None,
        label: str | None = None,
    ):
        """
        Convert parameter values into one value per mesh cell.

        Parameters
        ----------
        field_discretization :
            Discretization object returned by `Field.on_mesh(mesh)`.
            Required for heterogeneous fields.
        mesh :
            Target mesh. Required for homogeneous fields when no
            `field_discretization` is provided.
        label : str | None
            Optional label for the returned value field.
        """
        if self.is_homogeneous:
            # Homogeneous mode does not require any spatial field split:
            # one scalar value is assigned to every mesh cell directly.
            target_mesh = mesh
            if target_mesh is None and field_discretization is not None:
                target_mesh = getattr(field_discretization, "mesh", None)
            if target_mesh is None:
                raise ValueError(
                    "Homogeneous field requires 'mesh' "
                    "(or a field_discretization exposing '.mesh')"
                )
            values = np.full(int(target_mesh.n_cells), float(self.value), dtype=float)
            return target_mesh.attach_cell_values(
                values,
                label=label if label is not None else "homogeneous_value",
            )

        if field_discretization is None:
            raise ValueError("Heterogeneous field requires 'field_discretization'")

        required = ("mesh", "aggregation", "weighted_components")
        if not all(hasattr(field_discretization, key) for key in required):
            raise TypeError(
                "field_discretization must expose: "
                "'mesh', 'aggregation', 'weighted_components'"
            )

        if str(field_discretization.aggregation).strip().lower() != "weighted_average":
            raise ValueError(
                "Unsupported field discretization aggregation "
                f"'{field_discretization.aggregation}'"
            )

        mesh = field_discretization.mesh
        zone_keys, fractions_by_zone = field_discretization.weighted_components()
        weighted = None
        missing: list[str] = []

        for zone_key in zone_keys:
            if zone_key not in self.values_by_key:
                missing.append(str(zone_key))
                continue
            frac = np.asarray(fractions_by_zone[zone_key], dtype=float)
            frac = np.asarray(mesh.to_cell_values(frac), dtype=float)
            value = float(self.values_by_key[zone_key])
            contribution = frac * value
            weighted = contribution if weighted is None else (weighted + contribution)

        if missing:
            missing_txt = ", ".join(sorted(set(missing)))
            raise ValueError(f"Missing values for discretized field keys: {missing_txt}")

        if weighted is None:
            raise ValueError("Discretization did not produce any weighted contribution")

        values = np.asarray(mesh.to_cell_values(weighted), dtype=float)
        return mesh.attach_cell_values(
            values,
            label=label if label is not None else "heterogeneous_values",
        )

    @staticmethod
    def _normalize_zone_key(raw):
        if isinstance(raw, (int, np.integer)):
            return str(int(raw))
        if isinstance(raw, (float, np.floating)):
            value = float(raw)
            if np.isfinite(value) and value.is_integer():
                return str(int(value))
            return str(value)
        return str(raw)

    def map_zone_ids(self, zone_ids):
        """
        Map one value per zone key onto a zone-id array.

        Parameters
        ----------
        zone_ids : array-like
            Zone labels (int/float/string). Each unique label must be present
            in `values_by_key` after key normalization.
        """
        if not self.is_heterogeneous:
            raise ValueError("map_zone_ids is only valid for heterogeneous fields")

        zones = np.asarray(zone_ids)
        out = np.empty(zones.shape, dtype=float)

        missing: list[str] = []
        for raw in np.unique(zones):
            key = self._normalize_zone_key(raw.item() if hasattr(raw, "item") else raw)
            if key not in self.values_by_key:
                missing.append(key)
                continue
            out[zones == raw] = float(self.values_by_key[key])

        if missing:
            missing_txt = ", ".join(sorted(set(missing)))
            raise ValueError(f"Missing heterogeneous values for zone ids: {missing_txt}")
        return out

    def as_dict(self):
        """
        Serialize field parameters to a plain mapping.

        This is useful for:
        - debugging,
        - JSON/TOML export,
        - reproducibility logs.
        """
        if self.is_homogeneous:
            payload = {
                "id": str(self.identifier),
                "kind": self.kind,
                "value": float(self.value),
            }
        else:
            payload = {
                "id": str(self.identifier),
                "kind": self.kind,
                "values": dict(self.values_by_key),
                "field_spatial_id": str(self.field_spatial_id),
            }
        return payload

    @classmethod
    def from_dict(
        cls,
        config: Mapping[str, Any],
    ) -> "FieldParam":
        """
        Build `FieldParam` from a plain mapping.

        Accepted aliases
        ----------------
        - `id` or `identifier` for parameter id,
        - `kind` or `mode` for field mode,
        - `values` or `values_by_key` for heterogeneous values.
        - `field_spatial_id` for the target spatial field identifier.
        """
        if not isinstance(config, Mapping):
            raise TypeError("config must be a mapping")

        identifier = config.get("id", config.get("identifier"))
        if identifier is None or str(identifier).strip() == "":
            raise KeyError("Missing required key 'id' (or alias 'identifier')")

        kind = config.get("kind", config.get("mode"))
        if kind is None:
            raise KeyError("Missing required key 'kind' (or alias 'mode')")
        kind_key = str(kind).strip().lower()

        if kind_key == "homogeneous":
            if "value" not in config:
                raise KeyError("Homogeneous field requires key 'value'")
            return cls(
                identifier=str(identifier),
                kind=kind_key,
                value=float(config["value"]),
            )

        values_cfg = config.get("values", config.get("values_by_key"))
        if not isinstance(values_cfg, Mapping):
            raise KeyError("Heterogeneous field requires mapping key 'values'")
        if "field_spatial_id" not in config:
            raise KeyError("Heterogeneous field requires key 'field_spatial_id'")
        return cls(
            identifier=str(identifier),
            kind=kind_key,
            values_by_key=values_cfg,
            field_spatial_id=str(config["field_spatial_id"]),
        )

    @classmethod
    def from_toml(cls, toml_path: str | Path, section: str = "field") -> "FieldParam":
        """
        Build `FieldParam` from TOML section.

        Expected TOML examples:

        Single-section homogeneous:
            [field]
            id = "K"
            kind = "homogeneous"
            value = 10.0

        Single-section heterogeneous:
            [field]
            id = "S"
            kind = "heterogeneous"
            values = { granite = 10.0, micaschists = 3.5 }
            field_spatial_id = "field_square"

        Base + mode-specific sections (recommended):
            [field]
            id = "K"
            kind = "heterogeneous"

            [field_homogeneous]
            value = 12.5

            [field_heterogeneous]
            values = { granite = 10.0, micaschists = 2.0 }
            field_spatial_id = "field_square"

        Heterogeneous values from CSV (for long geology-property tables):
            [field]
            id = "K"
            kind = "heterogeneous"

            [field_heterogeneous]
            values_source = "csv"
            values_csv_file = "geology_property_values.csv"
            csv_key_column = "zone_key"
            csv_value_column = "property_value"
            field_spatial_id = "field_geology"

        Common+specific workflow
        ------------------------
        The loader supports:
        - a shared common section (`[field_common]`),
        - a base section (`[field]`) with `kind`,
        - mode-specific sections (`[field_homogeneous]`, `[field_heterogeneous]`).

        Data is merged as:

        1) optional common mapping,
        2) selected section mapping,
        3) optional mode-specific mapping selected from `kind`.
        """
        path = Path(toml_path).resolve()
        with path.open("rb") as stream:
            payload = tomllib.load(stream)
        payload = validate_field_param_toml_data(payload)
        section_key = str(section).strip()
        section_cfg = _get_nested_section(payload, section_key)

        merged: dict[str, Any] = {}

        # Shared common section at root level.
        common_root = _optional_nested_section(payload, "field_common")
        if common_root is not None and section_key != "field_common":
            merged.update(dict(common_root))

        # Optional parent-scoped common section for dotted paths.
        # Example: section="my_case.field_homogeneous" and
        # "my_case.field_common" or "my_case.common".
        if "." in section_key:
            parent = section_key.rsplit(".", 1)[0]
            for suffix in ("field_common", "common"):
                common_parent = _optional_nested_section(payload, f"{parent}.{suffix}")
                if common_parent is not None and f"{parent}.{suffix}" != section_key:
                    merged.update(dict(common_parent))

        # Backward-compatible root [field] common block (only when another
        # section is explicitly requested).
        if section_key != "field":
            common_field = _optional_nested_section(payload, "field")
            if common_field is not None:
                merged.update(dict(common_field))

        merged.update(dict(section_cfg))

        # Section name can imply the kind and should take precedence.
        leaf = section_key.rsplit(".", 1)[-1].strip().lower()
        if leaf in ("field_homogeneous", "homogeneous"):
            merged["kind"] = "homogeneous"
        elif leaf in ("field_heterogeneous", "heterogeneous"):
            merged["kind"] = "heterogeneous"

        # If kind is declared in the selected section (typically [field]),
        # enrich with a mode-specific section when available.
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

        # Resolve heterogeneous values source:
        # - inline: keep dictionary defined in TOML,
        # - csv: load key/value mapping from a CSV file.
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

        # Runtime-only helper keys are removed before schema validation and
        # object construction.
        for helper_key in (
            "values_source",
            "values_csv_file",
            "csv_key_column",
            "csv_value_column",
        ):
            merged.pop(helper_key, None)

        resolved = validate_resolved_field_param_data(merged)
        return cls.from_dict(resolved)
