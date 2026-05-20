"""Lightweight readers for Boussinesq calibration trials.

During a calibration trial the Boussinesq solver writes a single
``_boussinesq_state_history.npz`` file to the scratch folder at the end of
``processing()``. The optimizer needs the simulated series ASAP to score one
trial - these helpers read the npz directly and return a ``pd.Series``
aligned with the simulation time grid.

Discharge is reconstructed from ``drainage_flux_history_m3_s`` summed over
all cells per timestep (positive sign convention, matching the MODFLOW
``extract_discharge_from_cbc`` helper). Heads are read at flattened cell
indices: the Boussinesq mesh is one-layer-unstructured so the ``(k, i, j)``
station tuple is interpreted as ``cell_id = j`` with ``k == 0`` and
``i == 0`` (other layouts raise).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pandas as pd

_STATE_HISTORY_FILENAME = "_boussinesq_state_history.npz"


def _load_state_history(output_dir: Path) -> np.lib.npyio.NpzFile:
    npz_path = output_dir / _STATE_HISTORY_FILENAME
    if not npz_path.is_file():
        raise FileNotFoundError(
            f"No {_STATE_HISTORY_FILENAME} in {output_dir} for Boussinesq calibration."
        )
    return np.load(npz_path)


def _coerce_history(values: np.ndarray | None) -> np.ndarray | None:
    if values is None:
        return None
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return None
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    return arr


def extract_discharge_history(
    output_dir: Path,
    *,
    time_index: pd.DatetimeIndex | None = None,
) -> pd.Series:
    """Sum drainage outflow per timestep and return a m3/s series.

    Mirrors :func:`extract_discharge_from_cbc` but reads the Boussinesq
    ``drainage_flux_history_m3_s`` array. The sign convention is the same:
    drain outflow is reported as a positive number.
    """
    with _load_state_history(output_dir) as payload:
        history = _coerce_history(payload.get("drainage_flux_history_m3_s"))
        if history is None:
            raise KeyError(
                f"Boussinesq state history at {output_dir} has no drainage_flux_history_m3_s."
            )
        per_step = np.maximum(history, 0.0).sum(axis=1).astype(float)

    if time_index is not None and len(time_index) == per_step.size:
        return pd.Series(per_step, index=time_index, name="discharge")
    return pd.Series(per_step, name="discharge")


def extract_head_history_at_cells(
    output_dir: Path,
    *,
    station_cells: Mapping[str, tuple[int, int, int]],
    time_index: pd.DatetimeIndex | None = None,
) -> dict[str, pd.Series]:
    """Return head timeseries keyed by station from the unstructured mesh.

    For each station the ``(k, i, j)`` tuple is interpreted as
    ``cell_id = j``. ``k`` and ``i`` are expected to be ``0`` because the
    Boussinesq mesh is single-layer and unstructured.
    """
    with _load_state_history(output_dir) as payload:
        head_history = _coerce_history(payload.get("head_history_m"))
        if head_history is None:
            final = payload.get("final_head_m")
            if final is None:
                raise KeyError(f"Boussinesq state history at {output_dir} has no head_history_m.")
            head_history = np.asarray(final, dtype=float).reshape(1, -1)

    n_timesteps, n_cells = head_history.shape
    out: dict[str, pd.Series] = {}
    for station_id, cell in station_cells.items():
        k, i, j = (int(v) for v in cell)
        if k != 0 or i != 0:
            raise ValueError(
                f"Boussinesq head extraction expects station cell (0, 0, cell_id); "
                f"station {station_id!r} got {cell!r}."
            )
        if j < 0 or j >= n_cells:
            raise IndexError(
                f"Station {station_id!r} cell_id {j} is outside the Boussinesq mesh "
                f"of {n_cells} cells."
            )
        values = head_history[:, j].astype(float)
        if time_index is not None and len(time_index) == n_timesteps:
            out[station_id] = pd.Series(values, index=time_index, name=f"head@{station_id}")
        else:
            out[station_id] = pd.Series(values, name=f"head@{station_id}")
    return out


__all__ = [
    "extract_discharge_history",
    "extract_head_history_at_cells",
]
