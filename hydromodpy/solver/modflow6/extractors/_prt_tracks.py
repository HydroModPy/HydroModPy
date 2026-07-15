"""Shared readers for MODFLOW 6 PRT track outputs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from hydromodpy.core.units.time import SECONDS_PER_DAY, factor_to_seconds


@dataclass(frozen=True)
class PrtTrackArrays:
    """Vectorized MODFLOW 6 PRT track arrays grouped by particle."""

    x: np.ndarray
    y: np.ndarray
    z: np.ndarray
    time: np.ndarray
    status: np.ndarray | None
    reason: np.ndarray | None
    source_file: Path
    source_time_units: str

    @property
    def n_particles(self) -> int:
        return int(self.x.shape[0])

    @property
    def max_steps(self) -> int:
        return int(self.x.shape[1])


def read_time_units_from_tdis(tdis_path: Path) -> str:
    """Read MODFLOW 6 TDIS time units, falling back to days."""

    if not tdis_path.is_file():
        return "DAYS"
    try:
        with tdis_path.open("r", encoding="utf-8") as handle:
            for raw in handle:
                tokens = raw.strip().split()
                if len(tokens) >= 2 and tokens[0].upper() == "TIME_UNITS":
                    return tokens[1].upper()
    except OSError:
        return "DAYS"
    return "DAYS"


def time_factor_to_days(time_units: str) -> float:
    """Return the factor that converts model time units to days."""

    token = (time_units or "").strip().upper()
    if token in ("", "UNKNOWN"):
        return 1.0
    try:
        return factor_to_seconds(token) / SECONDS_PER_DAY
    except ValueError:
        return 1.0


def normalise_prt_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize PRT CSV column names to snake-like lower-case names."""

    renamed = {
        col: str(col).strip().lower().replace(" ", "_").replace("-", "_") for col in frame.columns
    }
    return frame.rename(columns=renamed)


def first_matching_column(frame: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    """Return the first candidate column present in *frame*."""

    for name in candidates:
        if name in frame.columns:
            return name
    return None


def particle_group_columns(frame: pd.DataFrame) -> list[str]:
    """Choose stable particle grouping columns for MODFLOW 6 PRT CSV output."""

    combined = [name for name in ("iprp", "irpt", "irptno", "trelease") if name in frame.columns]
    if any(name in combined for name in ("irpt", "irptno")):
        return combined
    single = first_matching_column(
        frame,
        (
            "particleid",
            "particle_id",
            "particle",
            "iparticle",
            "particlenumber",
            "irpt",
            "irptno",
        ),
    )
    return [single] if single is not None else []


def read_prt_track_csv(csv_path: Path, *, time_units: str = "DAYS") -> PrtTrackArrays | None:
    """Read a MODFLOW 6 PRT track CSV into padded particle arrays.

    The returned arrays are shaped ``(n_particles, max_steps)`` and use NaN
    padding for particles with fewer stored tracking points.
    """

    csv_path = Path(csv_path)
    frame = normalise_prt_columns(pd.read_csv(csv_path))
    if frame.empty:
        return None

    x_col = first_matching_column(frame, ("x", "xloc", "x_location"))
    y_col = first_matching_column(frame, ("y", "yloc", "y_location"))
    z_col = first_matching_column(frame, ("z", "zloc", "z_location"))
    t_col = first_matching_column(frame, ("time", "totim", "t", "simulation_time"))
    if x_col is None or y_col is None:
        raise ValueError(f"PRT track CSV {csv_path} does not contain x/y columns.")
    if t_col is None:
        frame["_hm_time"] = np.arange(len(frame), dtype=float)
        t_col = "_hm_time"
    else:
        factor = time_factor_to_days(time_units)
        frame[t_col] = pd.to_numeric(frame[t_col], errors="coerce") * factor
        if "trelease" in frame.columns:
            frame["trelease"] = pd.to_numeric(frame["trelease"], errors="coerce") * factor

    group_cols = particle_group_columns(frame)
    if not group_cols:
        frame["_hm_particle"] = 0
        group_cols = ["_hm_particle"]

    sort_cols = [*group_cols, t_col]
    frame = frame.sort_values(sort_cols, kind="mergesort")
    grouped = list(frame.groupby(group_cols, sort=False, dropna=False))
    if not grouped:
        return None

    n_particles = len(grouped)
    max_steps = max(len(group) for _, group in grouped)
    x = np.full((n_particles, max_steps), np.nan, dtype="float64")
    y = np.full((n_particles, max_steps), np.nan, dtype="float64")
    z = np.full((n_particles, max_steps), np.nan, dtype="float64")
    t = np.full((n_particles, max_steps), np.nan, dtype="float64")

    status_col = first_matching_column(frame, ("istatus", "status"))
    reason_col = first_matching_column(frame, ("ireason", "reason", "termination_reason"))
    status = (
        np.full((n_particles, max_steps), np.nan, dtype="float64")
        if status_col is not None
        else None
    )
    reason = (
        np.full((n_particles, max_steps), np.nan, dtype="float64")
        if reason_col is not None and pd.api.types.is_numeric_dtype(frame[reason_col])
        else None
    )

    for i, (_, group) in enumerate(grouped):
        n = len(group)
        x[i, :n] = pd.to_numeric(group[x_col], errors="coerce").to_numpy(dtype="float64")
        y[i, :n] = pd.to_numeric(group[y_col], errors="coerce").to_numpy(dtype="float64")
        if z_col is not None:
            z[i, :n] = pd.to_numeric(group[z_col], errors="coerce").to_numpy(dtype="float64")
        t[i, :n] = pd.to_numeric(group[t_col], errors="coerce").to_numpy(dtype="float64")
        if status is not None and status_col is not None:
            status[i, :n] = pd.to_numeric(group[status_col], errors="coerce").to_numpy(
                dtype="float64"
            )
        if reason is not None and reason_col is not None:
            reason[i, :n] = pd.to_numeric(group[reason_col], errors="coerce").to_numpy(
                dtype="float64"
            )

    return PrtTrackArrays(
        x=x,
        y=y,
        z=z,
        time=t,
        status=status,
        reason=reason,
        source_file=csv_path,
        source_time_units=time_units.upper(),
    )
