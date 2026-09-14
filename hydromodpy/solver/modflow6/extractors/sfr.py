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
from dataclasses import dataclass, field, fields
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
    "routed_outflow_series",
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
class SfrReachGeometry:
    """Resolved geometry of one reach, as written into the MODFLOW package.

    ``cell2d`` is ``None`` for a reach that carries flow without exchanging with
    the aquifer. The connection threshold MODFLOW switches on is ``rtp - rbth``.
    """

    ifno: int
    layer: int | None
    cell2d: int | None
    rlen: float
    rwid: float
    rgrd: float
    rtp: float
    rbth: float
    rhk: float
    manning: float
    strahler: int
    ustrf: float

    _INTS = ("ifno", "strahler")
    _NULLABLE_INTS = ("layer", "cell2d")

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> SfrReachGeometry:
        """Rebuild one reach from its sidecar entry."""
        values: dict[str, Any] = {}
        for name in (f.name for f in fields(cls)):
            raw = item.get(name)
            if name in cls._NULLABLE_INTS:
                values[name] = None if raw is None else int(raw)
            elif name in cls._INTS:
                values[name] = int(raw)
            else:
                values[name] = float(raw)
        return cls(**values)


@dataclass(frozen=True)
class SfrObsSpec:
    """Build-time description of the SFR outputs, persisted as a JSON sidecar."""

    obs_csv: str
    network_id: str
    reach_count: int
    entries: list[SfrObsEntry] = field(default_factory=list)
    reaches: list[SfrReachGeometry] = field(default_factory=list)

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
        reaches = [SfrReachGeometry.from_mapping(item) for item in payload.get("reaches", [])]
        return cls(
            obs_csv=str(payload["obs_csv"]),
            network_id=str(payload.get("network_id", "")),
            reach_count=int(payload.get("reach_count", 0)),
            entries=entries,
            reaches=reaches,
        )


def read_sfr_meta(meta_path: Path) -> SfrObsSpec | None:
    """Load the SFR output sidecar, or ``None`` when it is absent / unreadable.

    Unreadable covers a payload that parses as JSON but does not describe a
    spec: ``from_mapping`` raises on it, and the callers sit inside blocks that
    would take unrelated work down with them.
    """
    if not meta_path.is_file():
        return None
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.debug("Could not read SFR output meta %s", meta_path, exc_info=True)
        return None
    try:
        return SfrObsSpec.from_mapping(payload)
    except (KeyError, TypeError, ValueError):
        logger.warning(
            "SFR output meta %s does not describe a spec; the reach series and "
            "geometry of this run are lost.",
            meta_path,
            exc_info=True,
        )
        return None


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


def reach_flow_by_cell(
    output_dir: Path,
    model_name: str,
    *,
    times: Sequence[float],
    seconds_per_time_unit: float,
) -> dict[int, np.ndarray] | None:
    """Streamflow leaving each reach, keyed by the mesh cell the reach sits in [m3/s].

    Under SFR nothing has to be accumulated to know the discharge at a gauge:
    MODFLOW routed the water itself, movers included, so the reach under the
    station already carries the simulated flow to compare. That flow is also
    truer than an accumulation of what entered the network, because it holds
    the channel storage and the diversions the routing applied.

    ``downstream_flow`` is reported NEGATIVE by MF6 and is sign-corrected here
    the way :func:`build_sfr_columns` does. Reaches that exchange with no cell
    (``cell2d is None``) are skipped: nothing can be looked up at them. When
    several reaches share a cell the most downstream one wins, which is the
    largest flow, because a gauge on a cell measures what leaves it.

    Returns ``None`` when the run carries no SFR observations, which is how the
    caller knows to fall back to routing the release itself.
    """
    spec = read_sfr_meta(output_dir / f"{model_name}.sfr.meta.json")
    if spec is None:
        return None
    obs_path = output_dir / f"{model_name}.sfr.obs.csv"
    if not obs_path.is_file():
        return None
    header, rows = read_obs_csv(obs_path)
    if not rows:
        return None
    col_index = {name: pos for pos, name in enumerate(header)}
    n_steps = min(len(rows), len(times))
    if n_steps == 0:
        return None
    matrix = rows_matrix(rows, n_steps)
    spt = float(seconds_per_time_unit) if seconds_per_time_unit else 1.0

    cell_by_reach = {reach.ifno: reach.cell2d for reach in spec.reaches if reach.cell2d is not None}
    by_cell: dict[int, np.ndarray] = {}
    for entry in spec.entries:
        if entry.quantity != "downstream_flow":
            continue
        cell = cell_by_reach.get(entry.reach)
        if cell is None:
            continue
        pos = col_index.get(entry.obsname.upper())
        if pos is None or pos >= matrix.shape[1]:
            continue
        series = -np.nan_to_num(matrix[:, pos], nan=0.0) / spt
        known = by_cell.get(int(cell))
        if known is None or float(np.nansum(series)) > float(np.nansum(known)):
            by_cell[int(cell)] = series
    if not by_cell:
        return None
    logger.info(
        "Per-cell discharge: read the routed SFR downstream flow of %d reach cell(s); "
        "nothing is accumulated, MODFLOW routed the water.",
        len(by_cell),
    )
    return by_cell


def routed_outflow_series(
    output_dir: Path,
    model_name: str,
    *,
    times: Sequence[float],
    seconds_per_time_unit: float,
) -> np.ndarray | None:
    """Surface water leaving the model through the SFR network, per timestep [m3/s].

    Summed over every reach's ``ext-outflow``, sign-corrected the same way
    :func:`build_sfr_columns` does, so the calibration scores the quantity the
    store persists rather than a second convention.

    This is the observable a routed network exposes. The plain DRAIN record
    cannot stand in for it: with ``route_drainage`` the in-catchment drainage
    has been moved into DRN-TO-MVR, so what is left in DRAIN is the buffer
    drainage of the neighbouring basins.

    Returns ``None`` when the run carries no SFR observations, which is how the
    caller knows to fall back to the drain sum.
    """
    spec = read_sfr_meta(output_dir / f"{model_name}.sfr.meta.json")
    if spec is None:
        return None
    obs_path = output_dir / f"{model_name}.sfr.obs.csv"
    if not obs_path.is_file():
        return None
    header, rows = read_obs_csv(obs_path)
    if not rows:
        return None
    col_index = {name: pos for pos, name in enumerate(header)}
    n_steps = min(len(rows), len(times))
    if n_steps == 0:
        return None
    matrix = rows_matrix(rows, n_steps)
    spt = float(seconds_per_time_unit) if seconds_per_time_unit else 1.0

    total = np.zeros(n_steps, dtype="float64")
    seen = 0
    for entry in spec.entries:
        if entry.quantity != "ext_outflow":
            continue
        pos = col_index.get(entry.obsname.upper())
        if pos is None or pos >= matrix.shape[1]:
            continue
        column = np.nan_to_num(matrix[:, pos], nan=0.0)
        total += -column / spt  # ext-outflow is reported NEGATIVE by MF6
        seen += 1
    if seen == 0:
        return None
    logger.info(
        "Discharge observable: routed SFR ext-outflow summed over %d reach(es); the "
        "plain DRAIN record is buffer drainage and is not added.",
        seen,
    )
    return total
