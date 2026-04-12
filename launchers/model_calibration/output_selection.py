"""Canonical output selection for model-calibration launchers.

The calibration launcher needs a stable boundary between heterogeneous
simulation run states and objective-ready observables. This module owns that
boundary locally to `launchers.model_calibration`:

`run_state -> CanonicalOutputBundle -> selected observable arrays`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from launchers.model_calibration.config import ModelCalibrationConfig


@dataclass(frozen=True, slots=True)
class CanonicalOutputVariable:
    """One canonical simulation output variable."""

    name: str
    payload: Any
    source_key: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CanonicalOutputBundle:
    """Canonical view of outputs exposed by one candidate simulation run."""

    variables: dict[str, CanonicalOutputVariable]
    aliases: dict[str, str] = field(default_factory=dict)

    def get(self, key: str) -> Any:
        """Return a variable payload by canonical name or alias."""
        if key in self.variables:
            return self.variables[key].payload
        alias = self.aliases.get(key)
        if alias is not None and alias in self.variables:
            return self.variables[alias].payload
        raise KeyError(f"Unknown canonical output '{key}'")


def _candidate_output_containers(run_state: Any) -> tuple[tuple[str, Any], ...]:
    """Return possible output containers in lookup priority order."""
    containers: list[tuple[str, Any]] = []
    if isinstance(run_state, dict):
        for key in ("calibration_outputs", "outputs"):
            value = run_state.get(key)
            if value is not None:
                containers.append((key, value))
        containers.append(("run_state", run_state))
        return tuple(containers)

    for attr in ("calibration_outputs", "outputs"):
        value = getattr(run_state, attr, None)
        if value is not None:
            containers.append((attr, value))
    execution = getattr(run_state, "execution", None)
    if execution is not None:
        for attr in ("calibration_outputs", "outputs"):
            value = getattr(execution, attr, None)
            if value is not None:
                containers.append((f"execution.{attr}", value))
    return tuple(containers)


def _lookup_value_in_container(container: Any, key: str) -> tuple[bool, Any]:
    """Lookup one value by key in a dict-like or attribute container."""
    if isinstance(container, dict) and key in container:
        return True, container[key]
    if hasattr(container, key):
        return True, getattr(container, key)
    return False, None


def _iter_container_items(container: Any) -> list[tuple[str, Any]]:
    """Return string-keyed items exposed by one output container."""
    if isinstance(container, dict):
        return [(str(key), value) for key, value in container.items()]
    if hasattr(container, "__dict__"):
        return [
            (str(key), value)
            for key, value in vars(container).items()
            if not str(key).startswith("_")
        ]
    return []


def canonicalize_run_outputs(run_state: Any) -> CanonicalOutputBundle:
    """Build a canonical output bundle from a heterogeneous run state."""
    variables: dict[str, CanonicalOutputVariable] = {}
    aliases: dict[str, str] = {}
    for source_name, container in _candidate_output_containers(run_state):
        for key, value in _iter_container_items(container):
            if key not in variables:
                variables[key] = CanonicalOutputVariable(
                    name=key,
                    payload=value,
                    source_key=source_name,
                )
            aliases.setdefault(key, key)

    return CanonicalOutputBundle(variables=variables, aliases=aliases)


def _lookup_bundle_or_run_state(
    *,
    bundle: CanonicalOutputBundle,
    run_state: Any,
    key: str,
) -> Any:
    """Lookup one key first in the canonical bundle, then by direct container."""
    try:
        return bundle.get(key)
    except KeyError:
        pass
    for _, container in _candidate_output_containers(run_state):
        found, value = _lookup_value_in_container(container, key)
        if found:
            return value
    raise KeyError(f"Could not find calibration output key '{key}'")


def _output_variable_keys(output_cfg: Any) -> tuple[str, ...]:
    """Return variable lookup keys from most semantic to compatibility aliases."""
    keys: list[str] = []
    variable = str(output_cfg.variable).strip()
    if variable:
        keys.append(variable)
    boundary_id = getattr(output_cfg, "boundary_id", None)
    if variable == "outlet_discharge" and boundary_id is not None:
        keys.append(f"outlet_discharge_{boundary_id}_m3_s")
    return tuple(dict.fromkeys(keys))


def _is_spatial_sample_mapping(payload: Any) -> bool:
    """Return True for `{x, y, values}` or `{coordinates, values}` payloads."""
    if not isinstance(payload, dict) or "values" not in payload:
        return False
    return ("x" in payload and "y" in payload) or "coordinates" in payload


def _as_1d_float_tuple(values: Any, *, label: str) -> tuple[float, ...]:
    """Normalize one selected observable payload to a non-empty float tuple."""
    arr = np.asarray(values, dtype=float).ravel()
    if arr.size == 0:
        raise ValueError(f"{label} cannot be empty")
    return tuple(float(value) for value in arr)


def _reduce_numeric_values(
    values: Any,
    *,
    reducer: str | None,
    label: str,
) -> tuple[float, ...]:
    """Apply a scalar reducer or return all numeric values."""
    arr = np.asarray(values, dtype=float).ravel()
    if arr.size == 0:
        raise ValueError(f"{label} cannot be empty")
    reducer_key = "identity" if reducer is None else str(reducer).strip().lower()
    if reducer_key in {"identity", "all", "none"}:
        return tuple(float(value) for value in arr)
    if reducer_key == "sum":
        return (float(np.nansum(arr)),)
    if reducer_key == "mean":
        return (float(np.nanmean(arr)),)
    if reducer_key == "min":
        return (float(np.nanmin(arr)),)
    if reducer_key == "max":
        return (float(np.nanmax(arr)),)
    raise ValueError(f"Unsupported reducer '{reducer}' for {label}")


def _weighted_point_interpolation(
    payload: dict[str, Any],
    *,
    x: float,
    y: float,
    reducer: str | None,
    label: str,
) -> tuple[float, ...]:
    """Interpolate spatial samples at one point using inverse-distance weights."""
    values = np.asarray(payload["values"], dtype=float).ravel()
    if "coordinates" in payload:
        coordinates = np.asarray(payload["coordinates"], dtype=float)
        if coordinates.ndim != 2 or coordinates.shape[1] < 2:
            raise ValueError(f"{label}.coordinates must be a Nx2 array")
        xs = coordinates[:, 0].ravel()
        ys = coordinates[:, 1].ravel()
    else:
        xs = np.asarray(payload["x"], dtype=float).ravel()
        ys = np.asarray(payload["y"], dtype=float).ravel()

    if xs.size != ys.size or xs.size != values.size:
        raise ValueError(f"{label} x/y/value arrays must have the same length")
    if values.size == 0:
        raise ValueError(f"{label} cannot be empty")

    distances = np.hypot(xs - float(x), ys - float(y))
    finite_mask = np.isfinite(distances) & np.isfinite(values)
    if not np.any(finite_mask):
        raise ValueError(f"{label} contains no finite interpolation samples")
    distances = distances[finite_mask]
    values = values[finite_mask]

    exact_mask = distances == 0.0
    if np.any(exact_mask):
        return _reduce_numeric_values(
            values[exact_mask],
            reducer="mean",
            label=label,
        )

    reducer_key = "weighted_interpolation" if reducer is None else str(reducer)
    if reducer_key.strip().lower() == "nearest":
        return (float(values[int(np.argmin(distances))]),)
    if reducer_key.strip().lower() != "weighted_interpolation":
        return _reduce_numeric_values(values, reducer=reducer, label=label)

    weights = 1.0 / distances
    return (float(np.average(values, weights=weights)),)


def _mapping_lookup(mapping: dict[Any, Any], key: Any) -> tuple[bool, Any]:
    """Lookup a mapping key by raw value first, then by string representation."""
    if key in mapping:
        return True, mapping[key]
    text_key = str(key)
    for candidate_key, value in mapping.items():
        if str(candidate_key) == text_key:
            return True, value
    return False, None


def _time_selected_payloads(output_cfg: Any, payload: Any) -> list[Any]:
    """Resolve optional time selection over a variable payload."""
    if not isinstance(payload, dict) or _is_spatial_sample_mapping(payload):
        return [payload]
    if output_cfg.support == "boundary" and output_cfg.boundary_id in payload:
        return [payload]

    if output_cfg.time_window is not None:
        start, end = output_cfg.time_window
        selected = [
            value
            for key, value in payload.items()
            if str(start) <= str(key) <= str(end)
        ]
        return selected or list(payload.values())

    if output_cfg.time not in {None, "all"}:
        found, value = _mapping_lookup(payload, output_cfg.time)
        if found:
            return [value]

    return list(payload.values())


def _select_support_value(output_cfg: Any, payload: Any) -> tuple[float, ...]:
    """Apply the configured spatial support and reducer to a variable payload."""
    label = f"simulated variable '{output_cfg.variable}'"
    if output_cfg.support == "point":
        if not _is_spatial_sample_mapping(payload):
            reducer = (
                "identity"
                if str(output_cfg.reducer).strip().lower()
                == "weighted_interpolation"
                else output_cfg.reducer
            )
            return _reduce_numeric_values(payload, reducer=reducer, label=label)
        return _weighted_point_interpolation(
            payload,
            x=output_cfg.x,
            y=output_cfg.y,
            reducer=output_cfg.reducer,
            label=label,
        )
    if output_cfg.support == "boundary":
        values = payload
        if isinstance(payload, dict) and output_cfg.boundary_id is not None:
            found, boundary_values = _mapping_lookup(payload, output_cfg.boundary_id)
            if found:
                values = boundary_values
            elif "values" in payload:
                values = payload["values"]
        return _reduce_numeric_values(values, reducer=output_cfg.reducer, label=label)
    if output_cfg.support == "cell_mask":
        values = (
            payload["values"]
            if isinstance(payload, dict) and "values" in payload
            else payload
        )
        return _reduce_numeric_values(values, reducer=output_cfg.reducer, label=label)
    if output_cfg.support == "map":
        values = (
            payload["values"]
            if isinstance(payload, dict) and "values" in payload
            else payload
        )
        return _reduce_numeric_values(values, reducer="identity", label=label)
    raise KeyError(
        f"Unsupported output support '{output_cfg.support}' for '{output_cfg.name}'"
    )


def _select_variable_output_value(
    *,
    bundle: CanonicalOutputBundle,
    run_state: Any,
    output_cfg: Any,
) -> tuple[float, ...]:
    """Select one observable by variable/support when no explicit name exists."""
    last_error: Exception | None = None
    for variable_key in _output_variable_keys(output_cfg):
        try:
            payload = _lookup_bundle_or_run_state(
                bundle=bundle,
                run_state=run_state,
                key=variable_key,
            )
        except KeyError as exc:
            last_error = exc
            continue
        selected_parts: list[float] = []
        for time_payload in _time_selected_payloads(output_cfg, payload):
            selected_parts.extend(_select_support_value(output_cfg, time_payload))
        return _reduce_numeric_values(
            selected_parts,
            reducer=output_cfg.time_reducer,
            label=f"simulated output '{output_cfg.name}'",
        )

    if last_error is not None:
        raise KeyError(
            "Could not find calibration output "
            f"'{output_cfg.name}' or variable '{output_cfg.variable}'"
        ) from last_error
    raise KeyError(f"Could not resolve output '{output_cfg.name}'")


def select_candidate_outputs(
    *,
    cfg: ModelCalibrationConfig,
    run_state: Any,
) -> dict[str, tuple[float, ...]]:
    """Select configured simulated observables from one run-state payload."""
    bundle = canonicalize_run_outputs(run_state)
    selected: dict[str, tuple[float, ...]] = {}
    for output_cfg in cfg.model_calibration.output:
        try:
            value = _lookup_bundle_or_run_state(
                bundle=bundle,
                run_state=run_state,
                key=output_cfg.name,
            )
            selected[output_cfg.name] = _as_1d_float_tuple(
                value,
                label=f"simulated output '{output_cfg.name}'",
            )
        except KeyError:
            selected[output_cfg.name] = _select_variable_output_value(
                bundle=bundle,
                run_state=run_state,
                output_cfg=output_cfg,
            )
    return selected


__all__ = (
    "CanonicalOutputBundle",
    "CanonicalOutputVariable",
    "canonicalize_run_outputs",
    "select_candidate_outputs",
)
