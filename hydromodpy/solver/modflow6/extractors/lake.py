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
lake, quantity and connection, and flags the under-dam (VERTICAL) connections so
their exchange can be summed into a localised under-dam leakage series.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from hydromodpy.core.logging import get_logger
from hydromodpy.solver.modflow6.extractors.cbc_reader import Mf6CellBudgetReader
from hydromodpy.solver.modflow6.extractors.obs_common import (
    ordered_unique,
    read_obs_csv,
    timeseries_record,
    verify_obs_time_alignment,
)

logger = get_logger(__name__)

__all__ = [
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
        "seepage_under_dam",
        "rainfall",
        "evaporation",
        "runoff",
        "inflow",
        "withdrawal",
        "ext_outflow",
        "storage",
        "outlet",
        "to_mvr",
        "from_mvr",
        "lak_connection",
    }
)

# Outflow quantities negated to the positive-outflow convention shared with the
# SFR extractor (MF6 reports lake outflow negative).
_NEGATED_LAKE_QUANTITIES = frozenset({"ext_outflow", "to_mvr"})

# MF6 writes its "no data" sentinel (3e30) for an observation that does not apply to a
# given outlet -- e.g. ext-outflow on an outlet that is a mover or routes to another lake
# (its flow leaves via to-mvr / the outlet, never externally). Treat it as zero flow so it
# does not poison the summed budget term.
_DNODATA_THRESHOLD = 1e29

# Output unit per stored quantity (SI; rates land in m3/s after scaling).
_UNIT_BY_QUANTITY: dict[str, str] = {
    "stage": "m",
    "volume": "m3",
    "surface_area": "m2",
}


def lake_station_id(lake_id: str) -> str:
    """Return the timeseries ``station_id`` for one lake (``lake:<id>``)."""
    return f"lake:{lake_id}"


@dataclass(frozen=True)
class LakeObsEntry:
    """One LAK observation: which obs column maps to which lake quantity.

    ``obsname`` is the column header in the LAK obs CSV (MF6 upper-cases it).
    ``quantity`` is the HMP-side series name (e.g. ``stage``, ``gwf_exchange``).
    ``iconn`` is the 0-based per-lake connection index for per-connection ``lak``
    observations, else ``None``. ``under_dam`` flags a VERTICAL under-footprint
    connection so the extractor can sum it into the under-dam leakage series.
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
    """

    obs_csv: str
    entries: list[LakeObsEntry] = field(default_factory=list)
    budgetcsv: str | None = None
    budget_bin: str | None = None

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
        return cls(
            obs_csv=str(payload["obs_csv"]),
            entries=entries,
            budgetcsv=None if raw_budget is None else str(raw_budget),
            budget_bin=None if raw_bin is None else str(raw_bin),
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
    quantity: str = "stage",
    time_index: pd.DatetimeIndex | None = None,
) -> pd.Series:
    """Return one lake's simulated scalar series read from the LAK obs CSV.

    Reads ``{model_name}.lak.meta.json`` to locate the obs column for
    ``(lake_id, quantity)`` and pulls that column out of ``{model_name}.lak.obs.csv``.
    ``quantity`` defaults to ``"stage"`` (water level, m); ``volume`` (m3) and
    ``surface_area`` (m2) are also accepted. States are returned in native units,
    never time-scaled. The series carries ``time_index`` when its length matches
    the obs rows, else a positional index. Used by the calibration extraction
    path, where Parquet/Zarr writes are skipped.
    """
    if quantity not in _STATE_QUANTITIES:
        raise NotImplementedError(
            f"Lake calibration supports {sorted(_STATE_QUANTITIES)}, not {quantity!r}."
        )
    meta_path = output_dir / f"{model_name}.lak.meta.json"
    spec = read_lake_meta(meta_path)
    if spec is None:
        raise FileNotFoundError(f"LAK output sidecar not found or unreadable: {meta_path}")

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
        raise KeyError(
            f"No {quantity!r} observation for lake {lake_id!r} in {meta_path.name}. "
            f"Known lakes: {known}."
        )

    obs_path = output_dir / spec.obs_csv
    header, rows = read_obs_csv(obs_path)
    col_index = {name: pos for pos, name in enumerate(header)}
    pos = col_index.get(entry.obsname.upper())
    if pos is None:
        raise KeyError(f"Column {entry.obsname!r} missing from {obs_path.name}.")

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

    ``times`` are the solver output ``totim`` values (TDIS time unit); the obs CSV
    must align with them by row order. RATE quantities are divided by
    ``seconds_per_time_unit`` to reach m3/s; stage / volume / surface-area stay in
    their native units. The lake-aquifer exchange (``gwf_exchange``) and the
    under-dam leakage (``seepage_under_dam``) come from the applied flux in the LAK
    binary budget (see :func:`read_applied_exchange`), not from the obs CSV, and
    read negative when the lake loses water to the aquifer. A budget row mirrors
    the exchange total per lake so the water-balance tables carry the flux.
    """
    if not obs_path.is_file():
        logger.debug("LAK obs CSV %s is missing; no per-lake series extracted", obs_path)
        return [], []

    header, rows = read_obs_csv(obs_path)
    if not rows:
        return [], []
    col_index = {name: pos for pos, name in enumerate(header)}

    n_steps = min(len(rows), len(times))
    spt = float(seconds_per_time_unit) if seconds_per_time_unit else 1.0
    verify_obs_time_alignment(rows, times, col_index, n_steps, obs_path)

    # lake_id -> ordered set of stored quantities (excluding the per-connection
    # detail, which is aggregated rather than stored on its own).
    lake_ids = ordered_unique(entry.lake_id for entry in spec.entries)
    exchange_by_lake = read_applied_exchange(spec, obs_path, n_steps=n_steps)

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
                        unit=_UNIT_BY_QUANTITY.get(quantity, "m3/s"),
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
                        unit="m3/s",
                    )
                )
                if applied.under_dam is not None:
                    timeseries.append(
                        timeseries_record(
                            station=station,
                            quantity="seepage_under_dam",
                            timestep=t,
                            time=calendar,
                            value=applied.under_dam[t] / spt,
                            unit="m3/s",
                        )
                    )
                budgets.append(
                    {
                        "timestep": t,
                        "zone_id": station,
                        "component": "lak_gwf",
                        "flux_in": max(exchange_m3_s, 0.0),
                        "flux_out": abs(min(exchange_m3_s, 0.0)),
                        "unit": "m3/s",
                    }
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
    """Lake-aquifer flux MF6 applied, per output step, in the TDIS time unit.

    ``total`` is the whole lake, ``under_dam`` the VERTICAL subset (``None`` when
    the lake has no vertical connection). Positive = the lake gains water from the
    aquifer, which is the sign of the package budget's ``GWF_IN - GWF_OUT``.
    """

    total: list[float]
    under_dam: list[float] | None


def read_applied_exchange(
    spec: LakeObsSpec, obs_path: Path, *, n_steps: int
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
    further mapping. Returns ``{}`` when the budget is absent or unusable, and the
    caller then publishes no exchange series rather than a wrong one.
    """
    if not spec.budget_bin:
        logger.warning(
            "The LAK obs sidecar does not name the package binary budget, so the "
            "lake-aquifer exchange series (gwf_exchange, seepage_under_dam, lak_gwf) is "
            "not extracted. It cannot be rebuilt from the obs CSV: the per-connection lak "
            "obs is not the applied flux. Re-run the model to get the exchange back."
        )
        return {}
    budget_path = obs_path.parent / spec.budget_bin
    if not budget_path.is_file():
        logger.warning(
            "LAK binary budget %s is missing; the lake-aquifer exchange series "
            "(gwf_exchange, seepage_under_dam, lak_gwf) is not extracted. It cannot be "
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
            for position in steps[:n_steps]:
                record = budget.read_record(position)
                flux = np.asarray(record["q"], dtype=float)
                lake_number = np.asarray(record["node"], dtype=int)
                for index, lake_id in enumerate(lake_ids, start=1):
                    own = flux[lake_number == index]
                    mask = masks[lake_id]
                    if mask.size != own.size:
                        raise ValueError(
                            f"lake {lake_id}: the budget holds {own.size} connections where "
                            f"the obs sidecar declares {mask.size}"
                        )
                    totals[lake_id].append(float(own.sum()))
                    vertical[lake_id].append(float(own[mask].sum()))
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
