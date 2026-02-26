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
SUPPORTED_VERTICAL_PROFILE_MODES = ("none", "exponential", "tabulated")
SUPPORTED_VERTICAL_PROFILE_INTERPOLATIONS = ("linear", "step")


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
    vertical_profile : mapping | None
        Optional depth dependency shared across the full domain.
        Values defined in `value`/`values_by_key` are interpreted at surface
        (depth = 0). The vertical profile provides a multiplicative factor:

        `value(x, y, z) = value_surface(x, y) * f(z)`

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
        vertical_profile: Mapping[str, Any] | None = None,
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
            self.vertical_profile = self._normalize_vertical_profile(vertical_profile)
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
        self.vertical_profile = self._normalize_vertical_profile(vertical_profile)

    @property
    def is_homogeneous(self):
        return self.kind == "homogeneous"

    @property
    def is_heterogeneous(self):
        return self.kind == "heterogeneous"

    @property
    def has_vertical_variation(self):
        return str(self.vertical_profile.get("mode", "none")) != "none"

    @staticmethod
    def _normalize_vertical_profile(vertical_profile: Mapping[str, Any] | None) -> dict[str, Any]:
        if vertical_profile is None:
            return {"mode": "none"}
        if not isinstance(vertical_profile, Mapping):
            raise TypeError("vertical_profile must be a mapping when provided")

        mode = str(vertical_profile.get("mode", "none")).strip().lower()
        if mode not in SUPPORTED_VERTICAL_PROFILE_MODES:
            allowed = ", ".join(SUPPORTED_VERTICAL_PROFILE_MODES)
            raise ValueError(f"Unsupported vertical profile mode '{mode}'. Allowed: {allowed}")

        if mode == "none":
            return {"mode": "none"}

        if mode == "exponential":
            if "characteristic_depth" not in vertical_profile:
                raise KeyError(
                    "vertical_profile mode='exponential' requires 'characteristic_depth'"
                )
            characteristic_depth = float(vertical_profile["characteristic_depth"])
            if not np.isfinite(characteristic_depth) or characteristic_depth <= 0.0:
                raise ValueError("vertical_profile.characteristic_depth must be > 0")
            return {
                "mode": "exponential",
                "characteristic_depth": characteristic_depth,
            }

        if mode == "tabulated":
            if "depths" not in vertical_profile:
                raise KeyError("vertical_profile mode='tabulated' requires 'depths'")
            if "factors" not in vertical_profile:
                raise KeyError("vertical_profile mode='tabulated' requires 'factors'")

            depths = np.asarray(vertical_profile["depths"], dtype=float).reshape(-1)
            factors = np.asarray(vertical_profile["factors"], dtype=float).reshape(-1)
            if depths.size == 0 or factors.size == 0:
                raise ValueError("vertical_profile tabulated depths/factors cannot be empty")
            if depths.size != factors.size:
                raise ValueError(
                    "vertical_profile tabulated depths/factors must have the same length"
                )
            if np.any(~np.isfinite(depths)) or np.any(~np.isfinite(factors)):
                raise ValueError("vertical_profile tabulated depths/factors must be finite")
            if np.any(depths < 0.0):
                raise ValueError("vertical_profile depths must be >= 0")
            if np.any(np.diff(depths) <= 0.0):
                raise ValueError("vertical_profile depths must be strictly increasing")
            if not np.isclose(float(depths[0]), 0.0):
                raise ValueError("vertical_profile tabulated first depth must be 0.0")
            if not np.isclose(float(factors[0]), 1.0):
                raise ValueError("vertical_profile tabulated factor at depth 0.0 must be 1.0")

            interpolation = str(vertical_profile.get("interpolation", "linear")).strip().lower()
            if interpolation not in SUPPORTED_VERTICAL_PROFILE_INTERPOLATIONS:
                allowed = ", ".join(SUPPORTED_VERTICAL_PROFILE_INTERPOLATIONS)
                raise ValueError(
                    "Unsupported vertical_profile interpolation "
                    f"'{interpolation}'. Allowed: {allowed}"
                )

            return {
                "mode": "tabulated",
                "depths": depths.tolist(),
                "factors": factors.tolist(),
                "interpolation": interpolation,
            }

        raise ValueError(f"Unsupported vertical profile mode '{mode}'")

    @staticmethod
    def _normalize_depth(depth):
        depth_arr = np.asarray(0.0 if depth is None else depth, dtype=float)
        if np.any(~np.isfinite(depth_arr)):
            raise ValueError("depth must contain only finite numeric values")
        if np.any(depth_arr < 0.0):
            raise ValueError("depth values must be >= 0 (0 at surface, positive downward)")
        return depth_arr

    def vertical_factor(self, depth=0.0):
        depth_arr = self._normalize_depth(depth)
        mode = str(self.vertical_profile.get("mode", "none"))

        if mode == "none":
            out = np.ones_like(depth_arr, dtype=float)
        elif mode == "exponential":
            characteristic_depth = float(self.vertical_profile["characteristic_depth"])
            out = np.exp(-depth_arr / characteristic_depth)
        elif mode == "tabulated":
            depths = np.asarray(self.vertical_profile["depths"], dtype=float)
            factors = np.asarray(self.vertical_profile["factors"], dtype=float)
            interpolation = str(self.vertical_profile.get("interpolation", "linear"))
            if interpolation == "linear":
                out = np.interp(
                    depth_arr,
                    depths,
                    factors,
                    left=float(factors[0]),
                    right=float(factors[-1]),
                )
            else:
                indices = np.searchsorted(depths, depth_arr, side="right") - 1
                indices = np.clip(indices, 0, depths.size - 1)
                out = factors[indices]
        else:  # pragma: no cover - protected by validation in constructor
            raise ValueError(f"Unsupported vertical profile mode '{mode}'")

        if np.ndim(depth_arr) == 0:
            return float(np.asarray(out, dtype=float))
        return np.asarray(out, dtype=float)

    def _apply_vertical_profile(self, surface_values, *, depth=0.0):
        factor = self.vertical_factor(depth)
        if np.ndim(factor) == 0:
            scalar_factor = float(factor)
            values_arr = np.asarray(surface_values, dtype=float)
            if values_arr.ndim == 0:
                return float(values_arr) * scalar_factor
            return values_arr * scalar_factor
        try:
            return np.asarray(surface_values, dtype=float) * np.asarray(factor, dtype=float)
        except ValueError as exc:
            raise ValueError(
                "Depth shape is not broadcastable with surface values shape"
            ) from exc

    def _mesh_vertical_factor(self, mesh, *, depth=0.0):
        factor = self.vertical_factor(depth)
        if np.ndim(factor) == 0:
            return float(factor)
        return np.asarray(mesh.to_cell_values(factor), dtype=float)

    def to_array(
        self,
        *,
        shape=None,
        x=None,
        y=None,
        zone_ids=None,
        zone_field=None,
        depth=0.0,
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
        - optional `depth` applies vertical profile factors.

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
                surface_values = np.full(x_arr.shape, float(self.value), dtype=float)
                return self._apply_vertical_profile(surface_values, depth=depth)
            if zone_ids is not None:
                zone_arr = np.asarray(zone_ids)
                surface_values = np.full(zone_arr.shape, float(self.value), dtype=float)
                return self._apply_vertical_profile(surface_values, depth=depth)
            if shape is not None:
                shape_tuple = tuple(int(v) for v in shape)
                surface_values = np.full(shape_tuple, float(self.value), dtype=float)
                return self._apply_vertical_profile(surface_values, depth=depth)
            # No shape requested: return scalar.
            return self._apply_vertical_profile(float(self.value), depth=depth)

        # Heterogeneous values are mapped independently from geometry.
        if zone_field is not None:
            if not hasattr(zone_field, "cell_values"):
                raise TypeError("zone_field must expose 'cell_values'")
            zone_ids = zone_field.cell_values
        if zone_ids is None:
            raise ValueError("Heterogeneous field requires 'zone_ids'")
        surface_values = self.map_zone_ids(zone_ids)
        return self._apply_vertical_profile(surface_values, depth=depth)

    def to_mesh_field(
        self,
        field_discretization=None,
        *,
        mesh=None,
        label: str | None = None,
        depth=0.0,
    ):
        """
        Convert parameter values into one value per mesh cell.

        Important shape contract
        ------------------------
        This method always returns values on the provided mesh support
        (`MeshWithValues.cell_values`), i.e. one scalar per mesh cell.
        For the current structured SGrid bridge, that support is planar
        `(nrow, ncol)` and **not** a volumetric `(nlay, nrow, ncol)` tensor.

        In other words, depth-dependent correction is applied *on that 2D mesh*
        for the provided `depth` argument. A caller that needs a 3D tensor must
        call this method multiple times (for example one call per layer-depth)
        and stack the returned 2D maps.

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
        depth :
            Depth coordinate(s) where values are materialized.
            `0` corresponds to surface and positive values go downward.
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
            values = np.asarray(target_mesh.to_cell_values(values), dtype=float)
            vertical_factor = self._mesh_vertical_factor(target_mesh, depth=depth)
            values = values * vertical_factor
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
        vertical_factor = self._mesh_vertical_factor(mesh, depth=depth)
        values = values * vertical_factor
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
        if self.has_vertical_variation:
            payload["vertical_profile"] = dict(self.vertical_profile)
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
        - `vertical_profile` for depth-dependent global factor.
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
        vertical_profile = config.get(
            "vertical_profile",
            config.get("field_vertical_profile"),
        )

        if kind_key == "homogeneous":
            if "value" not in config:
                raise KeyError("Homogeneous field requires key 'value'")
            return cls(
                identifier=str(identifier),
                kind=kind_key,
                value=float(config["value"]),
                vertical_profile=vertical_profile,
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
            vertical_profile=vertical_profile,
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

            [field_vertical_profile]
            mode = "exponential"
            characteristic_depth = 30.0

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

        Loader workflow
        ---------------
        The loader uses:
        - a base section (`[field]`) with `kind`,
        - mode-specific sections (`[field_homogeneous]`, `[field_heterogeneous]`),
        - optional vertical section (`[field_vertical_profile]`).
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
                "TOML section 'field_common' is no longer supported. "
                "Move shared keys to 'field'."
            )

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

        # Optional vertical profile section:
        # - root: [field_vertical_profile] or [vertical_profile],
        # - parent-scoped for dotted sections.
        if leaf not in ("field_vertical_profile", "vertical_profile"):
            candidate_sections: list[str] = []
            if "." in section_key:
                parent = section_key.rsplit(".", 1)[0]
                candidate_sections.extend(
                    [
                        f"{parent}.field_vertical_profile",
                        f"{parent}.vertical_profile",
                    ]
                )
            candidate_sections.extend(("field_vertical_profile", "vertical_profile"))
            for candidate in candidate_sections:
                vertical_cfg = _optional_nested_section(payload, candidate)
                if vertical_cfg is not None:
                    merged["vertical_profile"] = dict(vertical_cfg)
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
