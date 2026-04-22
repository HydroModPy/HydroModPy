"""Shared temporal contract helpers for transient Boussinesq histories.

The transient runtime stores:

- snapshot histories on ``t0..tN`` for state-like variables,
- one stress-period duration per accepted step on ``dt1..dtN``.

Downstream code should avoid inferring this relationship ad hoc. These helpers
make the intended alignment explicit and reusable across exports, diagnostics
and validation tooling.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(frozen=True, slots=True)
class BoussinesqTransientTimeAxes:
    """Explicit time axes for one transient Boussinesq history payload."""

    period_lengths_seconds: np.ndarray
    snapshot_elapsed_seconds: np.ndarray
    step_end_elapsed_seconds: np.ndarray

    @property
    def n_steps(self) -> int:
        return int(self.step_end_elapsed_seconds.size)

    @property
    def n_snapshots(self) -> int:
        return int(self.snapshot_elapsed_seconds.size)


def _as_history_matrix(values: np.ndarray | Any, *, name: str) -> tuple[np.ndarray, bool]:
    array = np.asarray(values, dtype=float)
    if array.ndim == 1:
        return array.reshape(-1, 1), True
    if array.ndim == 2:
        return array, False
    raise ValueError(f"{name} must be a 1D or 2D transient history array.")


def build_transient_time_axes(
    period_lengths_seconds: np.ndarray | tuple[float, ...] | list[float],
) -> BoussinesqTransientTimeAxes:
    """Return the canonical snapshot and step-end axes for one transient run."""
    periods = np.asarray(period_lengths_seconds, dtype=float).reshape(-1)
    if periods.size == 0:
        snapshot_elapsed_seconds = np.asarray([0.0], dtype=float)
        step_end_elapsed_seconds = np.asarray([], dtype=float)
    else:
        step_end_elapsed_seconds = np.cumsum(periods, dtype=float)
        snapshot_elapsed_seconds = np.concatenate(
            (
                np.asarray([0.0], dtype=float),
                step_end_elapsed_seconds,
            )
        )
    return BoussinesqTransientTimeAxes(
        period_lengths_seconds=periods,
        snapshot_elapsed_seconds=np.asarray(snapshot_elapsed_seconds, dtype=float),
        step_end_elapsed_seconds=np.asarray(step_end_elapsed_seconds, dtype=float),
    )


def step_history_from_history(
    values: np.ndarray | Any,
    *,
    n_steps: int,
    name: str,
) -> np.ndarray:
    """Return one history aligned to one row per solved stress period.

    Accepted inputs are:
    - ``n_steps + 1`` rows: one snapshot-like history including ``t0``.
      The leading row is dropped.
    - ``n_steps`` rows: one already step-aligned history.
    """
    matrix, was_vector = _as_history_matrix(values, name=name)
    if matrix.shape[0] == int(n_steps) + 1:
        aligned = matrix[1:, :]
    elif matrix.shape[0] == int(n_steps):
        aligned = matrix
    else:
        raise ValueError(
            f"{name} has {matrix.shape[0]} rows, expected {n_steps} step rows "
            f"or {int(n_steps) + 1} snapshot rows."
        )
    if was_vector:
        return np.asarray(aligned[:, 0], dtype=float)
    return np.asarray(aligned, dtype=float)


def elapsed_seconds_for_time_keys(
    elapsed_axis_seconds: np.ndarray | Any,
    time_keys: np.ndarray | list[int] | tuple[int, ...],
    *,
    name: str = "history",
) -> np.ndarray:
    """Resolve explicit elapsed seconds for one exported time-key sequence."""
    axis = np.asarray(elapsed_axis_seconds, dtype=float).reshape(-1)
    keys = np.asarray(time_keys, dtype=int).reshape(-1)
    if keys.size == 0:
        return np.asarray([], dtype=float)
    if axis.size == 0:
        raise ValueError(f"{name} has no elapsed-time axis.")
    if np.any(keys < 0) or np.any(keys >= axis.size):
        raise ValueError(
            f"{name} time keys must stay within the elapsed-time axis bounds [0, {axis.size - 1}]."
        )
    return np.asarray(axis[keys], dtype=float)


def time_axis_sidecar_path(path: str | Path) -> Path:
    """Return the sidecar path storing explicit elapsed seconds for one `.npy` payload."""
    payload_path = Path(path)
    return payload_path.with_name(f"{payload_path.stem}__time_axis.npy")


def write_time_series_npy(
    path: str | Path,
    values: np.ndarray | Any,
    *,
    time_keys: np.ndarray | list[int] | tuple[int, ...],
    elapsed_seconds: np.ndarray | Any | None = None,
) -> None:
    """Write one `.npy` time-series mapping plus an optional elapsed-time sidecar."""
    array = np.asarray(values, dtype=float)
    if array.ndim == 0:
        raise ValueError(f"{path} must expose at least one time dimension.")
    if array.ndim == 1:
        rows = [np.asarray([float(value)], dtype=float) for value in array.tolist()]
    else:
        rows = [np.asarray(array[index], dtype=float) for index in range(array.shape[0])]
    keys = np.asarray(time_keys, dtype=int).reshape(-1)
    if len(rows) != keys.size:
        raise ValueError(f"{path} received {len(rows)} value rows but {keys.size} time keys.")

    payload = {int(time_key): rows[index] for index, time_key in enumerate(keys.tolist())}
    np.save(Path(path), payload)

    sidecar_path = time_axis_sidecar_path(path)
    if elapsed_seconds is None:
        if sidecar_path.exists():
            sidecar_path.unlink()
        return

    elapsed = np.asarray(elapsed_seconds, dtype=float).reshape(-1)
    if elapsed.size != keys.size:
        raise ValueError(
            f"{path} received {elapsed.size} elapsed-time values for {keys.size} time keys."
        )
    np.save(
        sidecar_path,
        {
            "time_keys": np.asarray(keys, dtype=int),
            "elapsed_seconds": np.asarray(elapsed, dtype=float),
        },
    )


def _payload_array(
    payload: dict[str, Any] | Any,
    key: str,
) -> np.ndarray | None:
    if key not in payload:
        return None
    values = np.asarray(payload[key], dtype=float).reshape(-1)
    if values.size == 0:
        return None
    return values


def step_end_elapsed_seconds_from_payload(
    payload: dict[str, Any] | Any,
    *,
    n_steps: int | None = None,
) -> np.ndarray | None:
    """Return one step-end elapsed-time axis from one history payload."""
    explicit = _payload_array(payload, "step_end_elapsed_seconds")
    if explicit is not None:
        if n_steps is not None and explicit.size != int(n_steps):
            raise ValueError(
                "step_end_elapsed_seconds length does not match the requested "
                f"step count ({explicit.size} vs {int(n_steps)})."
            )
        return explicit
    periods = _payload_array(payload, "period_lengths_seconds")
    if periods is None:
        return None
    axes = build_transient_time_axes(periods)
    if n_steps is not None and axes.n_steps != int(n_steps):
        return None
    return axes.step_end_elapsed_seconds


def snapshot_elapsed_seconds_from_payload(
    payload: dict[str, Any] | Any,
    *,
    n_snapshots: int | None = None,
) -> np.ndarray | None:
    """Return one snapshot elapsed-time axis from one history payload."""
    explicit = _payload_array(payload, "snapshot_elapsed_seconds")
    if explicit is not None:
        if n_snapshots is not None and explicit.size != int(n_snapshots):
            raise ValueError(
                "snapshot_elapsed_seconds length does not match the requested "
                f"snapshot count ({explicit.size} vs {int(n_snapshots)})."
            )
        return explicit
    periods = _payload_array(payload, "period_lengths_seconds")
    if periods is None:
        return None
    axes = build_transient_time_axes(periods)
    if n_snapshots is not None and axes.n_snapshots != int(n_snapshots):
        return None
    return axes.snapshot_elapsed_seconds


__all__ = [
    "BoussinesqTransientTimeAxes",
    "build_transient_time_axes",
    "elapsed_seconds_for_time_keys",
    "snapshot_elapsed_seconds_from_payload",
    "step_end_elapsed_seconds_from_payload",
    "step_history_from_history",
    "time_axis_sidecar_path",
    "write_time_series_npy",
]
