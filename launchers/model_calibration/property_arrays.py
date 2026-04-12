"""Hydraulic property array contracts for model-calibration candidates.

This module is launcher-local and deliberately independent from solver internals.
It provides the vectorized representation needed to move from scalar TOML
overrides toward `prepare -> actualize` workflows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from launchers.model_calibration.config import ModelCalibrationConfig


@dataclass(frozen=True, slots=True)
class HydraulicPropertyArray:
    """One hydraulic property represented as an external numeric array."""

    property_name: str
    values: np.ndarray
    parameter_names: tuple[str, ...] = ()
    labels: tuple[str, ...] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        values = np.asarray(self.values, dtype=float).copy()
        if values.ndim != 1:
            values = values.ravel()
        if values.size == 0:
            raise ValueError("HydraulicPropertyArray.values cannot be empty")
        object.__setattr__(self, "property_name", str(self.property_name).strip())
        object.__setattr__(self, "values", values)
        object.__setattr__(
            self,
            "parameter_names",
            tuple(str(name) for name in self.parameter_names),
        )
        if self.labels is not None:
            labels = tuple(str(label) for label in self.labels)
            if len(labels) != values.size:
                raise ValueError("HydraulicPropertyArray.labels length mismatch")
            object.__setattr__(self, "labels", labels)
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_summary(self) -> dict[str, Any]:
        """Return a JSON-friendly diagnostic summary."""
        finite = self.values[np.isfinite(self.values)]
        stats = {
            "count": int(self.values.size),
            "finite_count": int(finite.size),
            "min": None if finite.size == 0 else float(np.min(finite)),
            "mean": None if finite.size == 0 else float(np.mean(finite)),
            "max": None if finite.size == 0 else float(np.max(finite)),
        }
        return {
            "property_name": self.property_name,
            "parameter_names": list(self.parameter_names),
            "stats": stats,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class PropertyArraySet:
    """Collection of hydraulic property arrays for one candidate model."""

    arrays: dict[str, HydraulicPropertyArray]

    def get(self, property_name: str) -> HydraulicPropertyArray:
        """Return one property array by name."""
        key = str(property_name).strip()
        if key not in self.arrays:
            raise KeyError(f"Unknown hydraulic property array '{key}'")
        return self.arrays[key]

    def to_summary(self) -> dict[str, Any]:
        """Return one JSON-friendly diagnostic summary."""
        return {
            "properties": {
                name: array.to_summary()
                for name, array in sorted(self.arrays.items())
            }
        }


def _vector_from_params(
    *,
    cfg: ModelCalibrationConfig,
    params: dict[str, float] | tuple[float, ...] | list[float],
) -> dict[str, float]:
    """Normalize candidate parameters to a named mapping."""
    parameter_names = tuple(cfg.parameter_names)
    if isinstance(params, dict):
        missing = [name for name in parameter_names if name not in params]
        if missing:
            raise KeyError(f"Missing candidate parameters: {missing}")
        return {name: float(params[name]) for name in parameter_names}

    vector = tuple(float(value) for value in params)
    if len(vector) != len(parameter_names):
        raise ValueError(
            f"Expected {len(parameter_names)} parameters, got {len(vector)}"
        )
    return {
        name: float(value)
        for name, value in zip(parameter_names, vector, strict=True)
    }


def _base_array(
    *,
    property_name: str,
    base_property_arrays: dict[str, Any] | None,
    n_cells: int,
    fill_value: float,
) -> np.ndarray:
    """Return a base array for one hydraulic property."""
    if base_property_arrays is None or property_name not in base_property_arrays:
        return np.full(n_cells, float(fill_value), dtype=float)
    arr = np.asarray(base_property_arrays[property_name], dtype=float).ravel()
    if arr.size == 1:
        return np.full(n_cells, float(arr[0]), dtype=float)
    if arr.size != n_cells:
        raise ValueError(
            f"Base array for property '{property_name}' has size {arr.size}, "
            f"expected {n_cells}"
        )
    return arr.copy()


def _infer_lithology_key(parameter_cfg: Any) -> str | None:
    """Infer a lithology key from an explicit field or a dotted target path."""
    explicit = getattr(parameter_cfg, "lithology_key", None)
    if explicit is not None:
        text = str(explicit).strip()
        return text or None
    target = str(parameter_cfg.target)
    marker = ".values_by_key."
    if marker in target:
        return target.split(marker, maxsplit=1)[1].split(".", maxsplit=1)[0]
    return None


def _candidate_array_for_parameter(
    *,
    parameter_cfg: Any,
    candidate_value: float,
    base_values: np.ndarray,
    lithology_labels: tuple[str, ...] | None,
) -> np.ndarray:
    """Return one candidate contribution for a calibrated parameter."""
    parameterization = str(parameter_cfg.parameterization)
    mode = str(parameter_cfg.mode)

    if parameterization in {"global_value", "global_factor"}:
        if mode == "replace" or parameterization == "global_value":
            return np.full(base_values.size, float(candidate_value), dtype=float)
        if mode == "scale" or parameterization == "global_factor":
            return base_values * float(candidate_value)

    if parameterization == "lithology_value":
        if lithology_labels is None:
            raise ValueError(
                f"Parameter '{parameter_cfg.name}' requires lithology labels"
            )
        lithology_key = _infer_lithology_key(parameter_cfg)
        if lithology_key is None:
            raise ValueError(
                f"Parameter '{parameter_cfg.name}' requires lithology_key or "
                "a target containing '.values_by_key.<key>'"
            )
        labels = np.asarray(lithology_labels, dtype=str)
        if labels.size != base_values.size:
            raise ValueError("lithology_labels length must match base arrays")
        updated = base_values.copy()
        mask = labels == str(lithology_key)
        if not np.any(mask):
            raise ValueError(
                f"Parameter '{parameter_cfg.name}' references unknown lithology "
                f"'{lithology_key}'"
            )
        if mode == "replace":
            updated[mask] = float(candidate_value)
            return updated
        if mode == "scale":
            updated[mask] = updated[mask] * float(candidate_value)
            return updated

    raise ValueError(
        f"Unsupported parameterization/mode for '{parameter_cfg.name}': "
        f"{parameterization}/{mode}"
    )


def build_property_array_set(
    *,
    cfg: ModelCalibrationConfig,
    params: dict[str, float] | tuple[float, ...] | list[float],
    base_property_arrays: dict[str, Any] | None = None,
    lithology_labels: tuple[str, ...] | list[str] | np.ndarray | None = None,
    default_cell_count: int = 1,
) -> PropertyArraySet:
    """Build vectorized hydraulic property arrays for one candidate.

    Parameters without a `property` are ignored. When no base array is supplied,
    global parameters produce one-cell arrays; lithology parameters require
    explicit `lithology_labels`.
    """
    params_named = _vector_from_params(cfg=cfg, params=params)
    labels_tuple = (
        None
        if lithology_labels is None
        else tuple(str(label) for label in np.asarray(lithology_labels).ravel())
    )
    n_cells = int(default_cell_count)
    if labels_tuple is not None:
        n_cells = len(labels_tuple)
    if base_property_arrays:
        for values in base_property_arrays.values():
            arr = np.asarray(values, dtype=float).ravel()
            if arr.size > 1:
                n_cells = int(arr.size)
                break
    if n_cells <= 0:
        raise ValueError("default_cell_count must be > 0")

    arrays_by_property: dict[str, np.ndarray] = {}
    parameter_names_by_property: dict[str, list[str]] = {}
    metadata_by_property: dict[str, dict[str, Any]] = {}
    for parameter_cfg in cfg.model_calibration.parameter:
        property_name = parameter_cfg.property
        if property_name is None:
            continue
        needs_explicit_base = (
            str(parameter_cfg.parameterization) == "global_factor"
            or str(parameter_cfg.mode) == "scale"
        )
        has_declared_base = bool(
            base_property_arrays is not None and property_name in base_property_arrays
        )
        if (
            property_name not in arrays_by_property
            and needs_explicit_base
            and not has_declared_base
        ):
            raise ValueError(
                f"Parameter '{parameter_cfg.name}' requires one base array for "
                f"property '{property_name}' because it uses multiplicative "
                "parameterization."
            )
        base_values = _base_array(
            property_name=property_name,
            base_property_arrays=base_property_arrays,
            n_cells=n_cells,
            fill_value=params_named[parameter_cfg.name],
        )
        if property_name in arrays_by_property:
            base_values = arrays_by_property[property_name]
        arrays_by_property[property_name] = _candidate_array_for_parameter(
            parameter_cfg=parameter_cfg,
            candidate_value=params_named[parameter_cfg.name],
            base_values=base_values,
            lithology_labels=labels_tuple,
        )
        parameter_names_by_property.setdefault(property_name, []).append(
            parameter_cfg.name
        )
        metadata_by_property.setdefault(property_name, {})[
            parameter_cfg.name
        ] = {
            "mode": parameter_cfg.mode,
            "parameterization": parameter_cfg.parameterization,
            "lithology_key": _infer_lithology_key(parameter_cfg),
        }

    return PropertyArraySet(
        arrays={
            property_name: HydraulicPropertyArray(
                property_name=property_name,
                values=values,
                parameter_names=tuple(parameter_names_by_property[property_name]),
                labels=labels_tuple,
                metadata=metadata_by_property.get(property_name, {}),
            )
            for property_name, values in arrays_by_property.items()
        }
    )


__all__ = (
    "HydraulicPropertyArray",
    "PropertyArraySet",
    "build_property_array_set",
)
