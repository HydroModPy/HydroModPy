"""Parse MODFLOW 6 SFR outputs into per-reach timeseries and budget records.

Per-reach scalar series (stage, depth, downstream-flow, reach-aquifer exchange,
ext-inflow / ext-outflow, to-mvr / from-mvr) come from the SFR package's own
observation CSV, keyed by ``totim``, re-keyed by ``(reach_ifno, totim)`` through
the build-time ``{stem}.sfr.meta.json`` sidecar (:class:`SfrObsSpec`). The GWF
``.cbc`` ``SFR`` record carries the spatially-resolved per-aquifer-cell seepage
and is handled by the generic ``_extract_budget`` path (Zarr ``budget/sfr``).

Sign conventions stored (stream point of view):

* ``downstream_flow`` / ``ext_outflow`` / ``to_mvr`` are reported NEGATIVE by MF6
  (water leaving the reach); they are negated so the stored series is a positive
  streamflow.
* the ``sfr`` obs is positive when the stream LOSES water to the aquifer; it is
  negated so ``gw_exchange`` is positive when the reach gains baseflow, matching
  the lake ``gwf_exchange`` convention (positive = water arriving from the
  aquifer).
* ``ext_inflow``, ``from_mvr`` and ``runoff`` are incoming terms and stay as
  reported.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.solver.modflow6.extractors.obs_common import (
    read_obs_csv,
    rows_matrix,
    verify_obs_time_alignment,
)

logger = get_logger(__name__)

__all__ = [
    "SfrObsEntry",
    "SfrObsSpec",
    "build_sfr_columns",
    "read_sfr_meta",
    "sfr_station_id",
]

# Reach quantities reported as a volumetric RATE (m3 per TDIS time unit) that
# must be divided by seconds_per_time_unit to reach m3/s. Stage and depth are
# states (m) and are NOT scaled.
_RATE_QUANTITIES = frozenset(
    {
        "downstream_flow",
        "ext_inflow",
        "ext_outflow",
        "gw_exchange",
        "to_mvr",
        "from_mvr",
        "runoff",
    }
)

# Outflow-side quantities MF6 reports negative; negated to a positive flow.
# gw_exchange is negated for the sign convention, not as an outflow (see module
# docstring).
_NEGATED_QUANTITIES = frozenset({"downstream_flow", "ext_outflow", "to_mvr", "gw_exchange"})

# Output unit per stored quantity (SI; rates land in m3/s after scaling).
_UNIT_BY_QUANTITY: dict[str, str] = {
    "stage": "m",
    "depth": "m",
}


def sfr_station_id(network_id: str, reach_ifno: int) -> str:
    """Return the timeseries ``station_id`` for one reach (``sfr:<net>:<ifno>``)."""
    return f"sfr:{network_id}:{int(reach_ifno)}"


@dataclass(frozen=True)
class SfrObsEntry:
    """One SFR observation: which obs column maps to which reach quantity.

    ``obsname`` is the column header in the SFR obs CSV (MF6 upper-cases it).
    ``reach`` is the 0-based reach ``ifno``; ``quantity`` the HMP-side series name.
    """

    obsname: str
    network_id: str
    reach: int
    quantity: str


@dataclass(frozen=True)
class SfrObsSpec:
    """Build-time description of the SFR outputs, persisted as a JSON sidecar."""

    obs_csv: str
    network_id: str
    reach_count: int
    entries: list[SfrObsEntry] = field(default_factory=list)
    budgetcsv: str | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> SfrObsSpec:
        """Rebuild a spec from a parsed JSON mapping."""
        entries = [
            SfrObsEntry(
                obsname=str(item["obsname"]),
                network_id=str(item["network_id"]),
                reach=int(item["reach"]),
                quantity=str(item["quantity"]),
            )
            for item in payload.get("entries", [])
        ]
        budgetcsv = payload.get("budgetcsv")
        return cls(
            obs_csv=str(payload["obs_csv"]),
            network_id=str(payload.get("network_id", "")),
            reach_count=int(payload.get("reach_count", 0)),
            entries=entries,
            budgetcsv=None if budgetcsv is None else str(budgetcsv),
        )


def read_sfr_meta(meta_path: Path) -> SfrObsSpec | None:
    """Load the SFR output sidecar, or ``None`` when it is absent / unreadable."""
    if not meta_path.is_file():
        return None
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.debug("Could not read SFR output meta %s", meta_path, exc_info=True)
        return None
    return SfrObsSpec.from_mapping(payload)


def build_sfr_columns(
    spec: SfrObsSpec,
    obs_path: Path,
    *,
    times: Sequence[float],
    seconds_per_time_unit: float,
    calendar_times: Sequence[Any] | None = None,
) -> tuple[dict[str, np.ndarray], list[dict[str, Any]]]:
    """Parse the SFR obs CSV into ``(timeseries_columns, budget_records)``.

    ``times`` are the solver output ``totim`` values (TDIS time unit); the obs CSV
    must align with them by row order. RATE quantities are divided by
    ``seconds_per_time_unit`` to reach m3/s; stage / depth stay in meters. A
    budget row per network sums the reach-aquifer exchange (stream point of view)
    so the water-balance tables carry the stream-aquifer flux.

    The timeseries land as TIMESERIES_SCHEMA column arrays (one column entry per
    obs column x timestep), consumed by ``store.write_timeseries_columns``; a
    chronicle-size obs CSV holds millions of points, so per-point record dicts
    are too slow.
    """
    if not obs_path.is_file():
        logger.debug("SFR obs CSV %s is missing; no per-reach series extracted", obs_path)
        return {}, []

    header, rows = read_obs_csv(obs_path)
    if not rows:
        return {}, []
    col_index = {name: pos for pos, name in enumerate(header)}

    n_steps = min(len(rows), len(times))
    spt = float(seconds_per_time_unit) if seconds_per_time_unit else 1.0
    verify_obs_time_alignment(rows, times, col_index, n_steps, obs_path)

    # NaN marks the cells short rows do not cover; those points are skipped.
    matrix = rows_matrix(rows, n_steps)
    calendar: np.ndarray | None = None
    if calendar_times is not None:
        calendar = np.asarray(calendar_times[:n_steps], dtype="datetime64[ms]")

    station_parts: list[np.ndarray] = []
    variable_parts: list[np.ndarray] = []
    timestep_parts: list[np.ndarray] = []
    time_parts: list[np.ndarray] = []
    value_parts: list[np.ndarray] = []
    unit_parts: list[np.ndarray] = []
    for entry in spec.entries:
        pos = col_index.get(entry.obsname.upper())
        if pos is None or pos >= matrix.shape[1]:
            continue
        column = matrix[:, pos]
        steps = np.flatnonzero(~np.isnan(column))
        if steps.size == 0:
            continue
        values = column[steps]
        if entry.quantity in _RATE_QUANTITIES:
            values = values / spt
        if entry.quantity in _NEGATED_QUANTITIES:
            values = -values
        station_parts.append(
            np.full(steps.size, sfr_station_id(entry.network_id, entry.reach), dtype=object)
        )
        variable_parts.append(np.full(steps.size, entry.quantity, dtype=object))
        timestep_parts.append(steps.astype("int64"))
        value_parts.append(values.astype("float64"))
        unit_parts.append(
            np.full(steps.size, _UNIT_BY_QUANTITY.get(entry.quantity, "m3/s"), dtype=object)
        )
        if calendar is not None:
            time_parts.append(calendar[steps])

    columns: dict[str, np.ndarray] = {}
    if value_parts:
        columns = {
            "station_id": np.concatenate(station_parts),
            "variable": np.concatenate(variable_parts),
            "timestep": np.concatenate(timestep_parts),
            "value": np.concatenate(value_parts),
            "unit": np.concatenate(unit_parts),
        }
        if calendar is not None:
            columns["time"] = np.concatenate(time_parts)

    budgets: list[dict[str, Any]] = []
    exchange_positions = [
        pos
        for entry in spec.entries
        if entry.quantity == "gw_exchange"
        and (pos := col_index.get(entry.obsname.upper())) is not None
        and pos < matrix.shape[1]
    ]
    has_exchange_entries = any(entry.quantity == "gw_exchange" for entry in spec.entries)
    if has_exchange_entries:
        # Negated to the stream POV: positive = the network gains baseflow.
        # nansum: cells missing from short rows contribute zero, like the
        # historical per-row skip did.
        totals = -np.nansum(matrix[:, exchange_positions], axis=1) / spt
        for t in range(n_steps):
            total = float(totals[t])
            budgets.append(
                {
                    "timestep": t,
                    "zone_id": f"sfr:{spec.network_id}",
                    "component": "sfr_gwf",
                    "flux_in": max(total, 0.0),
                    "flux_out": abs(min(total, 0.0)),
                    "unit": "m3/s",
                }
            )

    return columns, budgets
