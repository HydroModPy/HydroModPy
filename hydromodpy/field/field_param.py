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

from pathlib import Path
from typing import Any, Mapping

import numpy as np

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


class FieldParam:
    """
    Describe scalar field values (homogeneous or heterogeneous).

    Parameters
    ----------
    kind : str
        Either `"homogeneous"` or `"heterogeneous"`.
    value : float | None
        Single scalar value for homogeneous fields.
    values_by_key : mapping | None
        Per-key values for heterogeneous fields.
    field_id : str | None
        Identifier of the geometry field this heterogeneous parameter set must
        be mapped on (example: "field_square").

    Examples
    --------
    Homogeneous:
        >>> p = FieldParam(kind="homogeneous", value=10.0)
        >>> p.to_array(shape=(2, 2))
        array([[10., 10.],
               [10., 10.]])

    Heterogeneous:
        >>> p = FieldParam(
        ...     kind="heterogeneous",
        ...     values_by_key={"granite": 12.0, "micaschists": 4.0},
        ...     field_id="field_square",
        ... )
        >>> p.to_array(zone_ids=["micaschists", "granite"])
        array([ 4., 12.])
    """

    def __init__(
        self,
        *,
        kind: str,
        value: float | None = None,
        values_by_key: Mapping[str, float] | None = None,
        field_id: str | None = None,
    ):
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
            self.field_id = None
            return

        # Heterogeneous case: dictionary key -> value is required.
        if values_by_key is None:
            raise ValueError("Heterogeneous field requires 'values_by_key'")
        values = {str(k): float(v) for k, v in dict(values_by_key).items()}
        if len(values) == 0:
            raise ValueError("'values_by_key' cannot be empty")
        if field_id is None or str(field_id).strip() == "":
            raise ValueError("Heterogeneous field requires 'field_id'")
        self.value = None
        self.values_by_key = values
        self.field_id = str(field_id).strip()

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

    def to_mesh_field(self, field_discretization, *, label: str | None = None):
        """
        Convert field discretization into a value mesh field.

        Parameters
        ----------
        field_discretization :
            Object returned by `Field.on_mesh(mesh)`, exposing:
            - `mesh`,
            - `zone_keys`,
            - `fractions_by_zone`,
            - `aggregation`.
        label : str | None
            Optional label for the returned value field.
        """
        required = ("mesh", "zone_keys", "fractions_by_zone", "aggregation")
        if not all(hasattr(field_discretization, key) for key in required):
            raise TypeError(
                "field_discretization must expose: "
                "'mesh', 'zone_keys', 'fractions_by_zone', 'aggregation'"
            )

        if str(field_discretization.aggregation).strip().lower() != "weighted_average":
            raise ValueError(
                "Unsupported field discretization aggregation "
                f"'{field_discretization.aggregation}'"
            )

        mesh = field_discretization.mesh
        weighted = None
        missing: list[str] = []

        for zone_key in field_discretization.zone_keys:
            if zone_key not in self.values_by_key:
                missing.append(str(zone_key))
                continue
            frac = np.asarray(field_discretization.fractions_by_zone[zone_key], dtype=float)
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
                "kind": self.kind,
                "value": float(self.value),
            }
        else:
            payload = {
                "kind": self.kind,
                "values": dict(self.values_by_key),
                "field_id": str(self.field_id),
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
        - `kind` or `mode` for field mode,
        - `values` or `values_by_key` for heterogeneous values.
        """
        if not isinstance(config, Mapping):
            raise TypeError("config must be a mapping")

        kind = config.get("kind", config.get("mode"))
        if kind is None:
            raise KeyError("Missing required key 'kind' (or alias 'mode')")
        kind_key = str(kind).strip().lower()

        if kind_key == "homogeneous":
            if "value" not in config:
                raise KeyError("Homogeneous field requires key 'value'")
            return cls(
                kind=kind_key,
                value=float(config["value"]),
            )

        values_cfg = config.get("values", config.get("values_by_key"))
        if not isinstance(values_cfg, Mapping):
            raise KeyError("Heterogeneous field requires mapping key 'values'")
        if "field_id" not in config:
            raise KeyError("Heterogeneous field requires key 'field_id'")
        return cls(
            kind=kind_key,
            values_by_key=values_cfg,
            field_id=str(config["field_id"]),
        )

    @classmethod
    def from_toml(cls, toml_path: str | Path, section: str = "field") -> "FieldParam":
        """
        Build `FieldParam` from TOML section.

        Expected TOML examples:

        Homogeneous:
            [field]
            kind = "homogeneous"
            value = 10.0

        Heterogeneous:
            [field]
            kind = "heterogeneous"
            values = { granite = 10.0, micaschists = 3.5 }
            field_id = "field_square"

        Minimal workflow
        ----------------
        1) read TOML section,
        2) convert section to standard mapping,
        3) delegate validation/construction to `from_dict`.
        """
        path = Path(toml_path).resolve()
        with path.open("rb") as stream:
            payload = tomllib.load(stream)
        section_cfg = _get_nested_section(payload, section)
        return cls.from_dict(section_cfg)
