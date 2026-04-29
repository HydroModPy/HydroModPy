"""
Field parameter container supporting homogeneous and heterogeneous values.

A field can be described in two ways:

1) Homogeneous: one scalar value everywhere
   (example: hydraulic conductivity K = 1e-4 everywhere).
2) Heterogeneous: one value per zone/material key
   (example: {"alluvium": 2e-4, "bedrock": 1e-6}).

Values are always stored in SI internally; the user-provided unit string is
preserved on `original_unit` for round-trip introspection.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from hydromodpy.core.units.hydraulic_conductivity import (
    M_PER_S_CANONICAL_UNITS,
    factor_to_m_per_s,
    normalize_m_per_s_unit,
)
from hydromodpy.core.units.length import parse_length_to_m
from hydromodpy.core.units.scalar import parse_scalar_and_unit

SUPPORTED_KINDS = ("homogeneous", "heterogeneous")
SUPPORTED_VERTICAL_PROFILE_MODES = ("none", "exponential", "tabulated")
SUPPORTED_VERTICAL_PROFILE_INTERPOLATIONS = ("linear", "step")

# Unit conventions and conversion factors to SI.
# Values in this class are always stored in SI internally.
SUPPORTED_PARAM_UNITS = ("-", *M_PER_S_CANONICAL_UNITS, "m-1", "cm-1")
_UNIT_ALIASES = {
    "-": "-",
    "1": "-",
    "none": "-",
    "dimensionless": "-",
    "unitless": "-",
    "m-1": "m-1",
    "1/m": "m-1",
    "m^-1": "m-1",
    "cm-1": "cm-1",
    "1/cm": "cm-1",
    "cm^-1": "cm-1",
}
_UNIT_TO_SI_UNIT = {
    "-": "-",
    **{unit: "m/s" for unit in M_PER_S_CANONICAL_UNITS},
    "m-1": "m-1",
    "cm-1": "m-1",
}
_UNIT_TO_SI_FACTOR = {
    "-": 1.0,
    **{unit: factor_to_m_per_s(unit) for unit in M_PER_S_CANONICAL_UNITS},
    "m-1": 1.0,
    "cm-1": 100.0,
}
_DEFAULT_SI_UNIT_BY_PARAM_ID = {
    "k": "m/s",
    "sy": "-",
    "s": "-",
    "ss": "m-1",
}


class FieldParam:
    """Scalar field values (homogeneous or heterogeneous), stored in SI.

    `unit` exposes the canonical SI unit; `original_unit` preserves the raw
    user-provided unit string for round-trip introspection. `vertical_profile`
    introduces an optional depth-dependent multiplicative factor f(z).
    """

    @staticmethod
    def _normalize_unit(unit: str | None) -> str:
        """Normalize a unit token to a canonical representation."""
        if unit is None:
            return "-"
        token = str(unit).strip().lower().replace(" ", "")
        if token == "":
            raise ValueError("unit cannot be empty when provided")
        if token in _UNIT_ALIASES:
            return _UNIT_ALIASES[token]
        try:
            return normalize_m_per_s_unit(token)
        except ValueError:
            allowed = ", ".join(SUPPORTED_PARAM_UNITS)
            raise ValueError(f"Unsupported unit '{unit}'. Allowed units: {allowed}") from None

    @staticmethod
    def _expected_si_unit_for_identifier(identifier: str) -> str | None:
        """Return default SI unit expected for known parameter identifiers."""
        return _DEFAULT_SI_UNIT_BY_PARAM_ID.get(str(identifier).strip().lower())

    @classmethod
    def _resolve_unit_system(
        cls,
        *,
        identifier: str,
        unit: str | None,
    ) -> tuple[str, str, float]:
        """Resolve input unit, SI unit, and SI conversion factor."""
        expected_si = cls._expected_si_unit_for_identifier(identifier)
        input_unit = cls._normalize_unit(unit) if unit is not None else (expected_si or "-")
        if input_unit not in _UNIT_TO_SI_UNIT:
            allowed = ", ".join(SUPPORTED_PARAM_UNITS)
            raise ValueError(f"Unsupported unit '{input_unit}'. Allowed units: {allowed}")
        si_unit = _UNIT_TO_SI_UNIT[input_unit]
        if expected_si is not None and si_unit != expected_si:
            raise ValueError(
                f"Unit '{input_unit}' is inconsistent with parameter '{identifier}'. "
                f"Expected SI family '{expected_si}'."
            )
        return input_unit, si_unit, float(_UNIT_TO_SI_FACTOR[input_unit])

    def __init__(
        self,
        *,
        identifier: str,
        kind: str,
        unit: str | None = None,
        value: object | None = None,
        values_by_key: Mapping[str, object] | None = None,
        field_spatial_id: str | None = None,
        vertical_profile: Mapping[str, Any] | None = None,
    ):
        ident = str(identifier).strip()
        if ident == "":
            raise ValueError("FieldParam requires a non-empty 'identifier'")
        self.identifier = ident

        kind_key = str(kind).strip().lower()
        if kind_key not in SUPPORTED_KINDS:
            allowed = ", ".join(SUPPORTED_KINDS)
            raise ValueError(f"Unsupported field kind '{kind}'. Allowed: {allowed}")

        self.kind = kind_key
        (
            self.input_unit,
            self.unit,
            self._unit_factor_to_si,
        ) = self._resolve_unit_system(identifier=self.identifier, unit=unit)
        self.original_unit: str | None = None if unit is None else str(unit)
        self.value: float | None = None
        self.values_by_key: dict[str, float] | None = None
        self.field_spatial_id: str | None = None
        explicit_unit_is_set = unit is not None

        if self.kind == "homogeneous":
            if value is None:
                raise ValueError("Homogeneous field requires 'value'")
            self.value = self._convert_scalar_payload_to_si(
                value,
                location=f"{self.identifier}.value",
                enforce_explicit_unit=explicit_unit_is_set,
            )
            self.values_by_key = None
            self.field_spatial_id = None
            self.vertical_profile = self._normalize_vertical_profile(vertical_profile)
            return

        if values_by_key is None:
            raise ValueError("Heterogeneous field requires 'values_by_key'")
        values: dict[str, float] = {}
        for key, raw_value in dict(values_by_key).items():
            zone_key = str(key)
            values[zone_key] = self._convert_scalar_payload_to_si(
                raw_value,
                location=f"{self.identifier}.values[{zone_key}]",
                enforce_explicit_unit=explicit_unit_is_set,
            )
        if len(values) == 0:
            raise ValueError("'values_by_key' cannot be empty")
        if field_spatial_id is None or str(field_spatial_id).strip() == "":
            raise ValueError("Heterogeneous field requires 'field_spatial_id'")
        self.value = None
        self.values_by_key = values
        self.field_spatial_id = str(field_spatial_id).strip()
        self.vertical_profile = self._normalize_vertical_profile(vertical_profile)

    def _convert_scalar_payload_to_si(
        self,
        raw_value: object,
        *,
        location: str,
        enforce_explicit_unit: bool,
    ) -> float:
        """Parse one scalar payload with optional inline unit and convert to SI."""
        explicit_unit = self.input_unit if enforce_explicit_unit else None
        scalar, resolved_unit = parse_scalar_and_unit(
            raw_value,
            location=location,
            default_unit=self.input_unit,
            explicit_unit=explicit_unit,
        )
        canonical_unit = self._normalize_unit(resolved_unit)
        if canonical_unit not in _UNIT_TO_SI_UNIT:
            allowed = ", ".join(SUPPORTED_PARAM_UNITS)
            raise ValueError(f"Unsupported unit '{resolved_unit}'. Allowed units: {allowed}")
        resolved_si_unit = _UNIT_TO_SI_UNIT[canonical_unit]
        if resolved_si_unit != self.unit:
            raise ValueError(
                f"{location} unit '{resolved_unit}' is inconsistent with parameter "
                f"'{self.identifier}'. Expected SI family '{self.unit}'."
            )
        return float(scalar) * float(_UNIT_TO_SI_FACTOR[canonical_unit])

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
    def _normalize_vertical_profile(
        vertical_profile: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
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
            characteristic_depth = parse_length_to_m(
                vertical_profile["characteristic_depth"],
                default_unit="m",
                label="vertical_profile.characteristic_depth",
            )
            if not np.isfinite(characteristic_depth) or characteristic_depth <= 0.0:
                raise ValueError("vertical_profile.characteristic_depth must be > 0")

            min_factor = vertical_profile.get("min_factor")
            if min_factor is not None:
                min_factor = float(min_factor)
                if not np.isfinite(min_factor):
                    raise ValueError("vertical_profile.min_factor must be finite when provided")
                if min_factor < 0.0 or min_factor > 1.0:
                    raise ValueError("vertical_profile.min_factor must be in [0, 1]")

            normalized = {
                "mode": "exponential",
                "characteristic_depth": characteristic_depth,
            }
            if min_factor is not None:
                normalized["min_factor"] = float(min_factor)
            return normalized

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
            min_factor = self.vertical_profile.get("min_factor")
            if min_factor is not None:
                out = np.maximum(out, float(min_factor))
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
            raise ValueError("Depth shape is not broadcastable with surface values shape") from exc

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
        """Materialize field values as a numeric array (homogeneous = value-driven, heterogeneous = structure-driven; `depth` applies vertical factors)."""
        if self.is_homogeneous:
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
            return self._apply_vertical_profile(float(self.value), depth=depth)

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
        """Convert parameter values into one value per mesh cell on the planar 2D support; for a 3D tensor, stack results from multiple calls (one per depth layer)."""
        if self.is_homogeneous:
            target_mesh = mesh
            if target_mesh is None and field_discretization is not None:
                target_mesh = getattr(field_discretization, "mesh", None)
            if target_mesh is None:
                raise ValueError(
                    "Homogeneous field requires 'mesh' (or a field_discretization exposing '.mesh')"
                )
            scalar_value = self.value
            if scalar_value is None:
                raise RuntimeError("Internal state error: homogeneous field has no 'value'.")
            values = np.full(int(target_mesh.n_cells), float(scalar_value), dtype=float)
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
                "field_discretization must expose: 'mesh', 'aggregation', 'weighted_components'"
            )

        if str(field_discretization.aggregation).strip().lower() != "weighted_average":
            raise ValueError(
                f"Unsupported field discretization aggregation '{field_discretization.aggregation}'"
            )

        mesh = field_discretization.mesh
        zone_keys, fractions_by_zone = field_discretization.weighted_components()
        weighted = None
        missing: list[str] = []
        values_by_key = self.values_by_key
        if values_by_key is None:
            raise RuntimeError("Internal state error: heterogeneous field has no 'values_by_key'.")

        for zone_key in zone_keys:
            if zone_key not in values_by_key:
                missing.append(str(zone_key))
                continue
            frac = np.asarray(fractions_by_zone[zone_key], dtype=float)
            frac = np.asarray(mesh.to_cell_values(frac), dtype=float)
            value = float(values_by_key[zone_key])
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
        """Map one value per zone key onto a zone-id array."""
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
        """Serialize field parameters to a plain mapping."""
        if self.is_homogeneous:
            payload = {
                "id": str(self.identifier),
                "kind": self.kind,
                "unit": str(self.unit),
                "value": float(self.value),
            }
        else:
            payload = {
                "id": str(self.identifier),
                "kind": self.kind,
                "unit": str(self.unit),
                "values": dict(self.values_by_key),
                "field_spatial_id": str(self.field_spatial_id),
            }
        if self.original_unit is not None:
            payload["original_unit"] = str(self.original_unit)
        if self.has_vertical_variation:
            payload["vertical_profile"] = dict(self.vertical_profile)
        return payload

    @classmethod
    def from_dict(cls, config: Mapping[str, Any]) -> FieldParam:
        """
        Build `FieldParam` from a plain mapping.

        Accepted aliases: `id`/`identifier`, `kind`/`mode`, `unit`/`units`,
        `values`/`values_by_key`, `field_spatial_id`, `vertical_profile`.
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
        unit = config.get("unit", config.get("units"))
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
                unit=unit,
                value=config["value"],
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
            unit=unit,
            values_by_key=values_cfg,
            field_spatial_id=str(config["field_spatial_id"]),
            vertical_profile=vertical_profile,
        )
