"""Shared transient multi-layer LAK geometry, parsed once from ``metadata.toml``.

The HMP runtime reads its DISV grid, the two-layer lake footprint, the per-period
forcings and the stage-volume-area abacus from this single typed view. The model
runs in meters/seconds, so every rate is converted from the metadata's per-day
declaration into SI on demand.

The abacus is the real "Plainfield" lake stage-area-volume table from USGS
modflow-setup (see ``data/SOURCE.txt``); it is read from the committed CSV copy so
the test never touches the gitignored ``modflow/`` tree.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from validation_cases.shared import load_case_metadata

CASE_DIR = Path(__file__).resolve().parent
CASE_ID = "lak_pleasant_transient"
DATA_DIR = CASE_DIR / "data"

# Small depression depth that smooths the dry/wet LAK behaviour for Newton.
_SURFDEP_M = 0.1


@dataclass(frozen=True, slots=True)
class PleasantTransientGeometry:
    """Typed view of the transient multi-layer LAK grid, lake and forcings (SI)."""

    nlay: int
    nrow: int
    ncol: int
    cell_size_m: float
    top_m: float
    botm_m: tuple[float, ...]
    occupied_layers: int
    row_start: int
    row_stop: int
    col_start: int
    col_stop: int
    bedleak_per_day: float
    stage_init_m: float
    k11_m_per_day: float
    k33_m_per_day: tuple[float, ...]
    specific_storage_per_m: float
    specific_yield: float
    strt_m: float
    head_left_m: float
    head_right_m: float
    recharge_m_per_day: float
    steady_period_length_days: float
    steady_n_steps: int
    transient_period_length_days: float
    transient_n_steps: int
    n_transient_periods: int
    rainfall_m_per_day: tuple[float, ...]
    evaporation_m_per_day: tuple[float, ...]
    runoff_m3_per_day: tuple[float, ...]
    outer_maximum: int
    inner_maximum: int
    outer_dvclose: float
    inner_dvclose: float
    rclose: float
    seconds_per_day: float
    abacus_rows: tuple[tuple[float, float, float], ...]

    # -- Plain derived quantities --------------------------------------------

    @property
    def n_cells(self) -> int:
        return self.nrow * self.ncol

    @property
    def n_periods(self) -> int:
        return 1 + self.n_transient_periods

    @property
    def surfdep_m(self) -> float:
        return _SURFDEP_M

    @property
    def bed_elevation_m(self) -> float:
        """Bottom of the deepest occupied layer (the lake bed)."""
        return float(self.botm_m[self.occupied_layers - 1])

    @property
    def lake_cell_ids(self) -> list[int]:
        """Flat row-major cell2d ids of the lake footprint."""
        return [
            r * self.ncol + c
            for r in range(self.row_start, self.row_stop)
            for c in range(self.col_start, self.col_stop)
        ]

    @property
    def delr_m(self) -> np.ndarray:
        return np.full(self.ncol, self.cell_size_m, dtype=float)

    @property
    def delc_m(self) -> np.ndarray:
        return np.full(self.nrow, self.cell_size_m, dtype=float)

    # -- SI helpers (HMP runs in meters/seconds) -----------------------------

    def _per_day_to_per_s(self, value: float) -> float:
        return float(value) / self.seconds_per_day

    @property
    def k11_m_per_s(self) -> float:
        return self._per_day_to_per_s(self.k11_m_per_day)

    @property
    def k33_m_per_s(self) -> tuple[float, ...]:
        return tuple(self._per_day_to_per_s(k) for k in self.k33_m_per_day)

    @property
    def specific_storage_per_s(self) -> float:
        # Ss is 1/L (storage per unit length), independent of the time unit.
        return float(self.specific_storage_per_m)

    @property
    def recharge_m_per_s(self) -> float:
        return self._per_day_to_per_s(self.recharge_m_per_day)

    @property
    def bedleak_per_s(self) -> float:
        return self._per_day_to_per_s(self.bedleak_per_day)

    @property
    def rainfall_m_per_s(self) -> tuple[float, ...]:
        return tuple(self._per_day_to_per_s(r) for r in self.rainfall_m_per_day)

    @property
    def evaporation_m_per_s(self) -> tuple[float, ...]:
        return tuple(self._per_day_to_per_s(e) for e in self.evaporation_m_per_day)

    @property
    def runoff_m3_per_s(self) -> tuple[float, ...]:
        return tuple(self._per_day_to_per_s(q) for q in self.runoff_m3_per_day)

    @property
    def tdis_perioddata(self) -> list[tuple[float, int, float]]:
        """``(perlen, nstp, tsmult)`` rows: steady first, then the transient ones."""
        rows: list[tuple[float, int, float]] = [
            (self.steady_period_length_days * self.seconds_per_day, self.steady_n_steps, 1.0)
        ]
        for _ in range(self.n_transient_periods):
            rows.append(
                (
                    self.transient_period_length_days * self.seconds_per_day,
                    self.transient_n_steps,
                    1.0,
                )
            )
        return rows

    @property
    def steady_state_flags(self) -> dict[int, bool]:
        """STO ``steady_state`` per period: only the first period is steady."""
        return {0: True, **{p: False for p in range(1, self.n_periods)}}

    @property
    def transient_flags(self) -> dict[int, bool]:
        """STO ``transient`` per period: every period after the first."""
        return {p: p >= 1 for p in range(self.n_periods)}


def _read_abacus_csv(
    *,
    csv_path: Path,
    lake_name: str,
    stage_column: str,
    volume_column: str,
    area_column: str,
    row_stride: int,
) -> tuple[tuple[float, float, float], ...]:
    """Read one lake's ``(stage, volume, sarea)`` abacus from the committed CSV.

    The USGS Plainfield Lakes CSV (data/SOURCE.txt) has one row per stage with a
    ``name`` column selecting the lake. Columns are already in meters / m3 / m2.
    Rows are thinned by ``row_stride`` and sorted by stage.
    """
    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if r["name"] == lake_name]
    if not rows:
        raise ValueError(f"No abacus rows for lake {lake_name!r} in {csv_path}.")
    rows.sort(key=lambda r: float(r[stage_column]))
    selected = rows[::row_stride]
    if rows[-1] not in selected:
        selected.append(rows[-1])
    return tuple(
        (float(r[stage_column]), float(r[volume_column]), float(r[area_column])) for r in selected
    )


def load_geometry() -> PleasantTransientGeometry:
    """Parse ``metadata.toml`` and the abacus CSV into the typed geometry view."""
    meta = load_case_metadata(CASE_DIR)
    units = dict(meta["units"])
    abacus_cfg = dict(meta["abacus"])
    geom = dict(meta["geometry"])
    lake = dict(meta["lake"])
    aquifer = dict(meta["aquifer"])
    time_cfg = dict(meta["time"])
    forcing = dict(meta["forcing"])
    solver = dict(meta["solver"])

    abacus_rows = _read_abacus_csv(
        csv_path=DATA_DIR / str(abacus_cfg["csv_name"]),
        lake_name=str(abacus_cfg["lake_name"]),
        stage_column=str(abacus_cfg["stage_column"]),
        volume_column=str(abacus_cfg["volume_column"]),
        area_column=str(abacus_cfg["area_column"]),
        row_stride=int(abacus_cfg["row_stride"]),
    )

    return PleasantTransientGeometry(
        nlay=int(geom["nlay"]),
        nrow=int(geom["nrow"]),
        ncol=int(geom["ncol"]),
        cell_size_m=float(geom["cell_size_m"]),
        top_m=float(geom["top_m"]),
        botm_m=tuple(float(b) for b in geom["botm_m"]),
        occupied_layers=int(geom["occupied_layers"]),
        row_start=int(lake["row_start"]),
        row_stop=int(lake["row_stop"]),
        col_start=int(lake["col_start"]),
        col_stop=int(lake["col_stop"]),
        bedleak_per_day=float(lake["bedleak_per_day"]),
        stage_init_m=float(lake["stage_init_m"]),
        k11_m_per_day=float(aquifer["k11_m_per_day"]),
        k33_m_per_day=tuple(float(k) for k in aquifer["k33_m_per_day"]),
        specific_storage_per_m=float(aquifer["specific_storage_per_m"]),
        specific_yield=float(aquifer["specific_yield"]),
        strt_m=float(aquifer["strt_m"]),
        head_left_m=float(aquifer["head_left_m"]),
        head_right_m=float(aquifer["head_right_m"]),
        recharge_m_per_day=float(aquifer["recharge_m_per_day"]),
        steady_period_length_days=float(time_cfg["steady_period_length_days"]),
        steady_n_steps=int(time_cfg["steady_n_steps"]),
        transient_period_length_days=float(time_cfg["transient_period_length_days"]),
        transient_n_steps=int(time_cfg["transient_n_steps"]),
        n_transient_periods=int(time_cfg["n_transient_periods"]),
        rainfall_m_per_day=tuple(float(r) for r in forcing["rainfall_m_per_day"]),
        evaporation_m_per_day=tuple(float(e) for e in forcing["evaporation_m_per_day"]),
        runoff_m3_per_day=tuple(float(q) for q in forcing["runoff_m3_per_day"]),
        outer_maximum=int(solver["outer_maximum"]),
        inner_maximum=int(solver["inner_maximum"]),
        outer_dvclose=float(solver["outer_dvclose"]),
        inner_dvclose=float(solver["inner_dvclose"]),
        rclose=float(solver["rclose"]),
        seconds_per_day=float(units["seconds_per_day"]),
        abacus_rows=abacus_rows,
    )


__all__ = ["CASE_DIR", "CASE_ID", "DATA_DIR", "PleasantTransientGeometry", "load_geometry"]
