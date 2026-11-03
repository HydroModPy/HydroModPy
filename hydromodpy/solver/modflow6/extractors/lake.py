"""Parse MODFLOW 6 LAK outputs into per-lake timeseries and budget records.

Per-lake scalar series (stage, volume, surface-area, outlet / ext-outflow, the
rest of the lake water balance) come from the LAK package's own observation CSV,
keyed by ``totim``, not the GWF ``.cbc``. The GWF ``.cbc`` ``LAK`` record carries
the spatially-resolved per-aquifer-cell seepage and is handled by
``_extract_budget`` (Zarr ``budget/lak``); this module only handles the per-lake
scalars.

The lake-aquifer exchange is the one quantity NOT taken from the obs CSV. The
per-connection ``lak`` observation is not the flux MF6 applied: the two agree on a
connection with a wetted area and diverge on one whose reported ``FLOW-AREA`` is
zero, so their sum inflates the exchange as a lake draws down. The ``GWF`` record
of ``<stem>.lak.cbc`` holds the applied flux connection by connection, in
CONNECTIONDATA order, and its total matches the package-level ``budgetcsv``
exactly; ``read_applied_exchange`` reads it. Sign convention: positive = the lake
gains water from the aquifer, as in ``GWF_IN - GWF_OUT``.

A build-time JSON sidecar (``LakeObsSpec``) maps each observation name to its
lake, quantity and connection, and flags the VERTICAL connections of the lake
bed so their exchange can be summed into ``lake_bed_vertical_exchange``. That
series is the bed of the whole lake, not a flow under the dam.

The flow through a lake cutoff wall is ``cutoff_wall_flow``: ``FLOW-JA-FACE``
of the GWF budget summed over the faces of the wall, which the sidecar lists
lake side first, per layer (see :func:`read_cutoff_wall_flow`).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from hydromodpy.core.exceptions import ObservableNotAvailableError
from hydromodpy.core.logging import get_logger
from hydromodpy.solver.modflow6.extractors.cbc_reader import Mf6CellBudgetReader
from hydromodpy.solver.modflow6.extractors.obs_common import (
    obs_rows_on_stamps,
    ordered_unique,
    read_obs_csv,
    timeseries_record,
    verify_obs_time_alignment,
)
from hydromodpy.solver.modflow_common.period_steps import (
    group_ends_by_stamp,
    weighted_period_scalar,
)

logger = get_logger(__name__)

__all__ = [
    "CUTOFF_WALL_FLOW",
    "AppliedExchange",
    "LakeAbacusEntry",
    "LakeAbacusSpec",
    "LakeObsEntry",
    "LakeObsSpec",
    "build_lake_records",
    "extract_lake_series",
    "final_lake_stages",
    "lake_station_id",
    "read_applied_exchange",
    "read_cutoff_wall_flow",
    "read_lake_abacus",
    "read_lake_meta",
]

# Lake scalar states stored in native units (no time scaling). These are the
# quantities a calibration can target directly from the LAK obs CSV.
_STATE_QUANTITIES = frozenset({"stage", "volume", "surface_area"})

# Lake quantities reported as a volumetric/areal RATE (length^N / time-unit) that
# must be divided by seconds_per_time_unit to reach m3/s. Stage (m), volume (m3)
# and surface-area (m2) are states and are NOT scaled.
_RATE_QUANTITIES = frozenset(
    {
        "gwf_exchange",
        "lake_bed_vertical_exchange",
        "rainfall",
        "evaporation",
        "runoff",
        "inflow",
        "withdrawal",
        "ext_outflow",
        "storage",
        "outlet",
        "outlet_inflow",
        "to_mvr",
        "from_mvr",
        "lak_connection",
    }
)

# Outflow quantities negated to the positive-outflow convention shared with the
# SFR extractor (MF6 reports lake outflow negative).
_NEGATED_LAKE_QUANTITIES = frozenset({"ext_outflow", "outlet", "to_mvr"})

# MF6 writes its "no data" sentinel (3e30) for an observation that does not apply to a
# given outlet -- e.g. ext-outflow on an outlet that is a mover or routes to another lake
# (its flow leaves via to-mvr / the outlet, never externally). Treat it as zero flow so it
# does not poison the summed budget term.
_DNODATA_THRESHOLD = 1e29

# The flow across a lake cutoff wall, from the lake side to the downstream side.
CUTOFF_WALL_FLOW = "cutoff_wall_flow"

# Output unit per stored quantity (SI; rates land in m3/s after scaling).
_UNIT_BY_QUANTITY: dict[str, str] = {
    "stage": "m",
    "volume": "m3",
    "surface_area": "m2",
}


def _lake_rows_on_stamps(
    spec: LakeObsSpec,
    rows: list[list[float]],
    times: Sequence[float],
    col_index: Mapping[str, int],
) -> list[list[float]]:
    """One obs row per stamp: rates averaged over the period, states at its end."""
    rate_positions = [
        pos
        for entry in spec.entries
        if entry.quantity in _RATE_QUANTITIES
        and (pos := col_index.get(entry.obsname.upper())) is not None
    ]
    return obs_rows_on_stamps(rows, times, col_index, mean_positions=rate_positions)


def lake_station_id(lake_id: str) -> str:
    """Return the timeseries ``station_id`` for one lake (``lake:<id>``)."""
    return f"lake:{lake_id}"


@dataclass(frozen=True)
class LakeObsEntry:
    """One LAK observation: which obs column maps to which lake quantity.

    ``obsname`` is the column header in the LAK obs CSV (MF6 upper-cases it).
    ``quantity`` is the HMP-side series name (e.g. ``stage``, ``gwf_exchange``).
    ``iconn`` is the 0-based per-lake connection index for per-connection ``lak``
    observations, else ``None``. ``under_dam`` flags a VERTICAL connection of the
    lake bed so the extractor can sum it into ``lake_bed_vertical_exchange``.
    """

    obsname: str
    lake_id: str
    quantity: str
    iconn: int | None = None
    under_dam: bool = False


@dataclass(frozen=True)
class LakeObsSpec:
    """Build-time description of the LAK outputs, persisted as a JSON sidecar.

    ``obs_csv`` is a filename relative to the solver output directory.
    ``entries`` maps every obs column to its lake / quantity. ``budget_bin`` names
    the LAK package binary budget, whose ``GWF`` record carries the lake-aquifer
    flux MF6 actually applied, connection by connection; ``budgetcsv`` names the
    package-level budget CSV, used to cross-check that total.

    ``cutoff_walls`` lists, per lake with a cutoff wall, the ``(lake side,
    downstream side)`` cell2d pairs of the wall faces; ``gwf_budget_bin`` names
    the GWF budget whose ``FLOW-JA-FACE`` carries the flow across them.
    """

    obs_csv: str
    entries: list[LakeObsEntry] = field(default_factory=list)
    budgetcsv: str | None = None
    budget_bin: str | None = None
    cutoff_walls: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    gwf_budget_bin: str | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> LakeObsSpec:
        """Rebuild a spec from a parsed JSON mapping."""
        entries = [
            LakeObsEntry(
                obsname=str(item["obsname"]),
                lake_id=str(item["lake_id"]),
                quantity=str(item["quantity"]),
                iconn=None if item.get("iconn") is None else int(item["iconn"]),
                under_dam=bool(item.get("under_dam", False)),
            )
            for item in payload.get("entries", [])
        ]
        raw_budget = payload.get("budgetcsv")
        raw_bin = payload.get("budget_bin")
        raw_gwf = payload.get("gwf_budget_bin")
        walls = {
            str(lake_id): [(int(a), int(b)) for a, b in faces]
            for lake_id, faces in (payload.get("cutoff_walls") or {}).items()
        }
        return cls(
            obs_csv=str(payload["obs_csv"]),
            entries=entries,
            budgetcsv=None if raw_budget is None else str(raw_budget),
            budget_bin=None if raw_bin is None else str(raw_bin),
            cutoff_walls=walls,
            gwf_budget_bin=None if raw_gwf is None else str(raw_gwf),
        )


def read_lake_meta(meta_path: Path) -> LakeObsSpec | None:
    """Load the LAK output sidecar, or ``None`` when it is absent / unreadable."""
    if not meta_path.is_file():
        return None
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.debug("Could not read LAK output meta %s", meta_path, exc_info=True)
        return None
    return LakeObsSpec.from_mapping(payload)


@dataclass(frozen=True)
class LakeAbacusEntry:
    """One lake's reference vs simulated abacus curves (bed reconstruction QC)."""

    lake_id: str
    stage: list[float]
    real_volume: list[float]
    real_sarea: list[float]
    sim_volume: list[float]
    sim_sarea: list[float]
    stage_unit: str = "m"
    volume_unit: str = "m3"
    area_unit: str = "m2"


@dataclass(frozen=True)
class LakeAbacusSpec:
    """Build-time abacus comparison sidecar, persisted as JSON next to the model."""

    entries: list[LakeAbacusEntry] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> LakeAbacusSpec:
        entries = [
            LakeAbacusEntry(
                lake_id=str(item["lake_id"]),
                stage=[float(v) for v in item["stage"]],
                real_volume=[float(v) for v in item["real_volume"]],
                real_sarea=[float(v) for v in item["real_sarea"]],
                sim_volume=[float(v) for v in item["sim_volume"]],
                sim_sarea=[float(v) for v in item["sim_sarea"]],
                stage_unit=str(item.get("stage_unit", "m")),
                volume_unit=str(item.get("volume_unit", "m3")),
                area_unit=str(item.get("area_unit", "m2")),
            )
            for item in payload.get("entries", [])
        ]
        return cls(entries=entries)


def read_lake_abacus(meta_path: Path) -> LakeAbacusSpec | None:
    """Load the lake-abacus comparison sidecar, or ``None`` when absent/unreadable."""
    if not meta_path.is_file():
        return None
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.debug("Could not read lake abacus meta %s", meta_path, exc_info=True)
        return None
    return LakeAbacusSpec.from_mapping(payload)


def extract_lake_series(
    output_dir: Path,
    model_name: str,
    *,
    lake_id: str,
    times: Sequence[float],
    quantity: str = "stage",
    time_index: pd.DatetimeIndex | None = None,
) -> pd.Series:
    """Return one lake's simulated scalar series read from the LAK obs CSV.

    Reads ``{model_name}.lak.meta.json`` to locate the obs column for
    ``(lake_id, quantity)`` and pulls that column out of ``{model_name}.lak.obs.csv``.
    ``quantity`` defaults to ``"stage"`` (water level, m); ``volume`` (m3) and
    ``surface_area`` (m2) are also accepted. States are returned in native units,
    never time-scaled, one per stress period at its end: the obs CSV holds a row
    per time step, put on ``times``, the ``totim`` of the saved heads, one per
    stress period at its end. The series carries
    ``time_index`` when its length matches, else a positional index. Used by the
    calibration extraction path, where Parquet/Zarr writes are skipped.
    """
    if quantity not in _STATE_QUANTITIES:
        raise NotImplementedError(
            f"Lake calibration supports {sorted(_STATE_QUANTITIES)}, not {quantity!r}."
        )
    meta_path = output_dir / f"{model_name}.lak.meta.json"
    spec = read_lake_meta(meta_path)
    if spec is None:
        raise ObservableNotAvailableError(
            f"LAK output sidecar not found or unreadable: {meta_path}"
        )

    entry = next(
        (
            item
            for item in spec.entries
            if item.lake_id == lake_id and item.quantity == quantity and item.iconn is None
        ),
        None,
    )
    if entry is None:
        known = sorted({item.lake_id for item in spec.entries})
        raise ObservableNotAvailableError(
            f"No {quantity!r} observation for lake {lake_id!r} in {meta_path.name}. "
            f"Known lakes: {known}."
        )

    obs_path = output_dir / spec.obs_csv
    header, rows = read_obs_csv(obs_path)
    col_index = {name: pos for pos, name in enumerate(header)}
    rows = _lake_rows_on_stamps(spec, rows, times, col_index)
    pos = col_index.get(entry.obsname.upper())
    if pos is None:
        raise ObservableNotAvailableError(f"Column {entry.obsname!r} missing from {obs_path.name}.")

    values = [float(row[pos]) for row in rows if pos < len(row)]
    if time_index is not None and len(time_index) == len(values):
        return pd.Series(values, index=time_index, name=quantity)
    return pd.Series(values, name=quantity)


def build_lake_records(
    spec: LakeObsSpec,
    obs_path: Path,
    *,
    times: Sequence[float],
    seconds_per_time_unit: float,
    calendar_times: Sequence[Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse the LAK obs CSV into ``(timeseries_records, budget_records)``.

    ``times`` are the solver output ``totim`` values (TDIS time unit), one per
    stress period at its end. The obs CSV and the LAK binary budget hold one
    entry per time step: each stamp takes the mean of the rates over the steps
    it closes, weighted by their length, and the states at its end. RATE
    quantities are divided by
    ``seconds_per_time_unit`` to reach m3/s; stage / volume / surface-area stay in
    their native units. The lake-aquifer exchange (``gwf_exchange``) and the
    vertical lake-bed balance (``lake_bed_vertical_exchange``) come from the applied flux in the LAK
    binary budget (see :func:`read_applied_exchange`), not from the obs CSV, and
    read negative when the lake loses water to the aquifer. A budget row mirrors
    the exchange total per lake so the water-balance tables carry the flux.

    A lake with a cutoff wall also gets ``cutoff_wall_flow`` (m3/s, positive from
    the lake side to the downstream side), on ``lake:<id>:layer<k>`` per layer
    (1-based) and on ``lake:<id>`` for their sum (:func:`read_cutoff_wall_flow`).
    """
    if not obs_path.is_file():
        logger.debug("LAK obs CSV %s is missing; no per-lake series extracted", obs_path)
        return [], []

    header, rows = read_obs_csv(obs_path)
    if not rows:
        return [], []
    col_index = {name: pos for pos, name in enumerate(header)}
    rows = _lake_rows_on_stamps(spec, rows, times, col_index)

    n_steps = min(len(rows), len(times))
    spt = float(seconds_per_time_unit) if seconds_per_time_unit else 1.0
    verify_obs_time_alignment(rows, times, col_index, n_steps, obs_path)

    # lake_id -> ordered set of stored quantities (excluding the per-connection
    # detail, which is aggregated rather than stored on its own).
    lake_ids = ordered_unique(entry.lake_id for entry in spec.entries)
    exchange_by_lake = read_applied_exchange(spec, obs_path, times=list(times[:n_steps]))

    timeseries: list[dict[str, Any]] = []
    budgets: list[dict[str, Any]] = []

    for lake_id in lake_ids:
        station = lake_station_id(lake_id)
        scalar_entries = [
            entry
            for entry in spec.entries
            if entry.lake_id == lake_id
            and entry.iconn is None
            and entry.quantity != "lak_connection"
        ]

        for t in range(n_steps):
            row = rows[t]
            calendar = calendar_times[t] if calendar_times is not None else None

            # Aggregate scalar entries by quantity. A multi-outlet lake reports
            # outlet / ext_outflow / to_mvr once per outlet under the same
            # quantity, so the per-outlet columns are summed into one series
            # instead of colliding on the same primary key (last-write-wins).
            by_quantity: dict[str, float] = {}
            for entry in scalar_entries:
                pos = col_index.get(entry.obsname.upper())
                if pos is None or pos >= len(row):
                    continue
                value = float(row[pos])
                if abs(value) > _DNODATA_THRESHOLD:
                    value = 0.0  # MF6 no-data sentinel: obs not applicable = no flow
                if entry.quantity in _RATE_QUANTITIES:
                    value /= spt
                if entry.quantity in _NEGATED_LAKE_QUANTITIES:
                    # MF6 reports outflow negative; store it positive so LAK
                    # matches the SFR ext_outflow convention.
                    value = -value
                by_quantity[entry.quantity] = by_quantity.get(entry.quantity, 0.0) + value
            for quantity, value in by_quantity.items():
                timeseries.append(
                    timeseries_record(
                        station=station,
                        quantity=quantity,
                        timestep=t,
                        time=calendar,
                        value=value,
                        unit=_UNIT_BY_QUANTITY.get(quantity, "m3 s-1"),
                    )
                )

            # Lake-aquifer exchange, taken from the flux MF6 applied (LAK binary
            # budget), never from the per-connection obs. Under-dam = the VERTICAL
            # subset of the same record.
            applied = exchange_by_lake.get(lake_id)
            if applied is not None and t < len(applied.total):
                exchange_m3_s = applied.total[t] / spt
                timeseries.append(
                    timeseries_record(
                        station=station,
                        quantity="gwf_exchange",
                        timestep=t,
                        time=calendar,
                        value=exchange_m3_s,
                        unit="m3 s-1",
                    )
                )
                if applied.under_dam is not None:
                    timeseries.append(
                        timeseries_record(
                            station=station,
                            quantity="lake_bed_vertical_exchange",
                            timestep=t,
                            time=calendar,
                            value=applied.under_dam[t] / spt,
                            unit="m3 s-1",
                        )
                    )
                budgets.append(
                    {
                        "timestep": t,
                        "zone_id": station,
                        "component": "lak_gwf",
                        "flux_in": max(exchange_m3_s, 0.0),
                        "flux_out": abs(min(exchange_m3_s, 0.0)),
                        "unit": "m3 s-1",
                    }
                )

    wall_flow = read_cutoff_wall_flow(spec, obs_path.parent, times=list(times[:n_steps]))
    for lake_id, layers in wall_flow.items():
        station = lake_station_id(lake_id)
        for t in range(n_steps):
            calendar = calendar_times[t] if calendar_times is not None else None
            total = 0.0
            for layer, values in sorted(layers.items()):
                if t >= len(values):
                    continue
                total += values[t] / spt
                timeseries.append(
                    timeseries_record(
                        station=f"{station}:layer{layer}",
                        quantity=CUTOFF_WALL_FLOW,
                        timestep=t,
                        time=calendar,
                        value=values[t] / spt,
                        unit="m3 s-1",
                    )
                )
            timeseries.append(
                timeseries_record(
                    station=station,
                    quantity=CUTOFF_WALL_FLOW,
                    timestep=t,
                    time=calendar,
                    value=total,
                    unit="m3 s-1",
                )
            )

    return timeseries, budgets


def final_lake_stages(timeseries: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """Return each lake's last-step stage ``{lake_id: stage}`` (metres).

    Scans the records built by :func:`build_lake_records`, keeps the ``stage``
    value at the largest timestep per ``lake:<id>`` station, and strips the
    ``lake:`` prefix. Feeds the hotstart restart state persisted to the Zarr so a
    later ``[flow] restart_from`` run seeds each lake's initial stage.
    """
    best: dict[str, tuple[int, float]] = {}
    for record in timeseries:
        if record.get("variable") != "stage":
            continue
        station = str(record.get("station_id", ""))
        if not station.startswith("lake:"):
            continue
        step = int(record.get("timestep", 0))
        current = best.get(station)
        if current is None or step >= current[0]:
            best[station] = (step, float(record["value"]))
    return {station[len("lake:") :]: value for station, (_, value) in best.items()}


@dataclass(frozen=True)
class AppliedExchange:
    """Lake-aquifer flux MF6 applied, per stress period, in the TDIS time unit.

    Each value is the mean over the time steps of the period, weighted by
    their length.

    ``total`` is the whole lake, ``under_dam`` the VERTICAL subset, the lake bed
    (``None`` when the lake has no vertical connection). Positive = the lake gains water from the
    aquifer, which is the sign of the package budget's ``GWF_IN - GWF_OUT``.
    """

    total: list[float]
    under_dam: list[float] | None


def read_applied_exchange(
    spec: LakeObsSpec, obs_path: Path, *, times: Sequence[float]
) -> dict[str, AppliedExchange]:
    """Read the applied lake-aquifer flux from the LAK binary budget.

    The per-connection ``lak`` observation is NOT this flux. MF6 reports the two
    identically on a connection with a wetted area, and differently on one whose
    reported ``FLOW-AREA`` is zero, where the observation overstates the seepage.
    Summing the observations therefore inflates the exchange as a lake draws down:
    the gap grows as more connections dry out, which no
    downstream check catches because the model-wide balance is the GWF balance,
    not the lake's. The ``GWF`` record of ``<stem>.lak.cbc`` is the flux the
    groundwater equation received; it matches the package budget CSV exactly.

    The record lists one entry per connection in CONNECTIONDATA order, with the
    lake number in ``node``, so the per-lake and per-connection sums need no
    further mapping. The file holds one record per time step; ``times`` are the
    stamps, one per stress period at its end, and each takes the mean of the
    steps it closes, weighted by their length. Returns ``{}`` when the budget is
    absent or unusable, and the caller then publishes no exchange series rather
    than a wrong one.
    """
    if not spec.budget_bin:
        logger.warning(
            "The LAK obs sidecar does not name the package binary budget, so the "
            "lake-aquifer exchange series (gwf_exchange, lake_bed_vertical_exchange, lak_gwf) is "
            "not extracted. It cannot be rebuilt from the obs CSV: the per-connection lak "
            "obs is not the applied flux. Re-run the model to get the exchange back."
        )
        return {}
    budget_path = obs_path.parent / spec.budget_bin
    if not budget_path.is_file():
        logger.warning(
            "LAK binary budget %s is missing; the lake-aquifer exchange series "
            "(gwf_exchange, lake_bed_vertical_exchange, lak_gwf) is not extracted. It cannot be "
            "rebuilt from the obs CSV: the per-connection lak obs is not the applied flux.",
            budget_path.name,
        )
        return {}

    lake_ids = ordered_unique(entry.lake_id for entry in spec.entries)
    under_dam_mask: dict[str, list[bool]] = {}
    for lake_id in lake_ids:
        conns = sorted(
            (e for e in spec.entries if e.lake_id == lake_id and e.quantity == "lak_connection"),
            key=lambda e: int(e.iconn or 0),
        )
        under_dam_mask[lake_id] = [bool(e.under_dam) for e in conns]

    totals: dict[str, list[float]] = {lake: [] for lake in lake_ids}
    vertical: dict[str, list[float]] = {lake: [] for lake in lake_ids}
    masks = {lake: np.asarray(under_dam_mask[lake], dtype=bool) for lake in lake_ids}
    try:
        with Mf6CellBudgetReader(budget_path) as budget:
            steps = [i for i, record in enumerate(budget.records) if record.text == "GWF"]
            if not steps:
                raise ValueError("the budget carries no GWF record")
            groups = group_ends_by_stamp([budget.records[i].totim for i in steps], times)
            for group in groups:
                if not group.positions:
                    break
                step_totals: dict[str, list[float]] = {lake: [] for lake in lake_ids}
                step_vertical: dict[str, list[float]] = {lake: [] for lake in lake_ids}
                for step in group.positions:
                    record = budget.read_record(steps[step])
                    flux = np.asarray(record["q"], dtype=float)
                    lake_number = np.asarray(record["node"], dtype=int)
                    for index, lake_id in enumerate(lake_ids, start=1):
                        own = flux[lake_number == index]
                        mask = masks[lake_id]
                        if mask.size != own.size:
                            raise ValueError(
                                f"lake {lake_id}: the budget holds {own.size} connections "
                                f"where the obs sidecar declares {mask.size}"
                            )
                        step_totals[lake_id].append(float(own.sum()))
                        step_vertical[lake_id].append(float(own[mask].sum()))
                for lake_id in lake_ids:
                    totals[lake_id].append(
                        weighted_period_scalar(step_totals[lake_id], group.weights)
                    )
                    vertical[lake_id].append(
                        weighted_period_scalar(step_vertical[lake_id], group.weights)
                    )
    except (OSError, ValueError, KeyError, IndexError) as exc:
        logger.warning(
            "Could not read the applied lake-aquifer flux from %s (%s); the exchange "
            "series is not extracted.",
            budget_path.name,
            exc,
        )
        return {}

    return {
        lake_id: AppliedExchange(
            total=totals[lake_id],
            under_dam=vertical[lake_id] if any(under_dam_mask[lake_id]) else None,
        )
        for lake_id in lake_ids
    }


def _grid_connections(solver_dir: Path) -> tuple[np.ndarray, np.ndarray, int] | None:
    """Return ``(ia, ja, ncpl)`` of the GWF grid, 0-based, from its ``.grb``."""
    grb_files = sorted(solver_dir.glob("*.disv.grb")) + sorted(solver_dir.glob("*.dis.grb"))
    if not grb_files:
        return None
    from flopy.mf6.utils import MfGrdFile

    grid = MfGrdFile(str(grb_files[0]), verbose=False)
    ia = np.asarray(grid.ia, dtype=np.int64)
    ja = np.asarray(grid.ja, dtype=np.int64)
    ncpl = int(grid.ncpl) if grid.grid_type == "DISV" else int(grid.nrow) * int(grid.ncol)
    return ia, ja, ncpl


def _face_position(ia: np.ndarray, ja: np.ndarray, node: int, other: int) -> int | None:
    """Position of the ``node -> other`` connection in ``FLOW-JA-FACE``, or None."""
    if node + 1 >= ia.size:
        return None
    start, end = int(ia[node]), int(ia[node + 1])
    hits = np.flatnonzero(ja[start:end] == other)
    return int(start + hits[0]) if hits.size else None


def read_cutoff_wall_flow(
    spec: LakeObsSpec, solver_dir: Path, *, times: Sequence[float]
) -> dict[str, dict[int, list[float]]]:
    """Read the flow across each lake cutoff wall, per layer, from the GWF budget.

    The wall faces come from the sidecar, ``(lake side, downstream side)`` cell2d
    pairs: the faces the HFB bars. In each layer the flow of a face is
    ``FLOW-JA-FACE`` of the downstream cell from the lake-side cell (MF6 counts
    the flow into a cell positive), so a positive sum leaves the lake side. Every
    layer is read, barred or not: the flow under the wall is part of the answer.
    A face with an inactive cell in a layer carries no connection there and is
    skipped. Rates are in the TDIS unit per stamp, the mean of the steps it
    closes weighted by their length. Returns ``{lake_id: {layer (1-based):
    values}}``, ``{}`` when the model has no wall or the files are missing.
    """
    walls = {lake: faces for lake, faces in spec.cutoff_walls.items() if faces}
    if not walls:
        return {}
    budget_path = solver_dir / (spec.gwf_budget_bin or "")
    grid = _grid_connections(solver_dir)
    if not spec.gwf_budget_bin or not budget_path.is_file() or grid is None:
        logger.warning(
            "The GWF budget or the binary grid of %s is missing; the cutoff wall flow "
            "(cutoff_wall_flow) is not extracted.",
            solver_dir,
        )
        return {}
    ia, ja, ncpl = grid
    nlay = (ia.size - 1) // ncpl
    # positions[lake][layer] = FLOW-JA-FACE positions of the downstream cell from the lake side.
    positions: dict[str, dict[int, list[int]]] = {}
    for lake_id, faces in walls.items():
        per_layer: dict[int, list[int]] = {}
        for layer in range(nlay):
            hits = [
                pos
                for up, down in faces
                if (pos := _face_position(ia, ja, layer * ncpl + down, layer * ncpl + up))
                is not None
            ]
            if hits:
                per_layer[layer + 1] = hits
        positions[lake_id] = per_layer
    wanted = sorted({p for layers in positions.values() for hits in layers.values() for p in hits})
    if not wanted:
        return {}
    first = wanted[0]
    span = wanted[-1] - first + 1
    out: dict[str, dict[int, list[float]]] = {
        lake: {layer: [] for layer in layers} for lake, layers in positions.items()
    }
    try:
        with Mf6CellBudgetReader(budget_path) as budget, open(budget_path, "rb") as raw:
            steps = [r for r in budget.records if r.text == "FLOW-JA-FACE"]
            if not steps:
                raise ValueError("the budget carries no FLOW-JA-FACE record")
            groups = group_ends_by_stamp([r.totim for r in steps], times)
            for group in groups:
                if not group.positions:
                    break
                per_step: dict[tuple[str, int], list[float]] = {}
                for step in group.positions:
                    raw.seek(steps[step].data_pos + 8 * first)
                    flowja = np.fromfile(raw, dtype="<f8", count=span)
                    for lake_id, layers in positions.items():
                        for layer, hits in layers.items():
                            value = float(flowja[np.asarray(hits) - first].sum())
                            per_step.setdefault((lake_id, layer), []).append(value)
                for (lake_id, layer), values in per_step.items():
                    out[lake_id][layer].append(weighted_period_scalar(values, group.weights))
    except (OSError, ValueError, IndexError) as exc:
        logger.warning(
            "Could not read the cutoff wall flow from %s (%s); the series is not extracted.",
            budget_path.name,
            exc,
        )
        return {}
    return out
