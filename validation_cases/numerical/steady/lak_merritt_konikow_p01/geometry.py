"""Shared p01 geometry, parsed once from ``metadata.toml``.

Both the upstream reference (feet/days) and the HMP runtime (meters/seconds) read
their grid, lake footprint and forcings from this single typed view so the two
builds stay in lock-step. The feet/days values are the published example values;
SI accessors convert them on demand for the HMP DISV build.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from validation_cases.shared import load_case_metadata

CASE_DIR = Path(__file__).resolve().parent
CASE_ID = "lak_merritt_konikow_p01"

# Small depression depth that smooths the dry/wet LAK behaviour for Newton; the
# upstream example uses a comparable value. Kept tiny relative to lake stages.
_SURFDEP_FT = 0.1


@dataclass(frozen=True, slots=True)
class LakeP01Geometry:
    """Typed view of the p01 grid, lake and forcings (feet/days, with SI helpers)."""

    nlay: int
    nrow: int
    ncol: int
    top_ft: float
    botm_ft: tuple[float, ...]
    delr_ft: np.ndarray
    delc_ft: np.ndarray
    row_start: int
    row_stop: int
    col_start: int
    col_stop: int
    bed_elevation_ft: float
    stage_init_ft: float
    bedleak_per_day: float
    abacus_stage_ft: tuple[float, ...]
    rainfall_ft_per_day: float
    evaporation_ft_per_day: float
    k11_ft_per_day: float
    k33_ft_per_day: tuple[float, ...]
    specific_storage_per_day: float
    specific_yield: float
    strt_ft: float
    head_left_ft: float
    head_right_ft: float
    recharge_ft_per_day: float
    period_length_days: float
    n_steps: int
    ts_multiplier: float
    outer_maximum: int
    inner_maximum: int
    outer_dvclose: float
    inner_dvclose: float
    rclose: float
    feet_to_meter: float
    seconds_per_day: float

    # -- Plain derived quantities --------------------------------------------

    @property
    def surfdep_ft(self) -> float:
        return _SURFDEP_FT

    @property
    def tdis_period_days(self) -> tuple[float, int, float]:
        return (self.period_length_days, self.n_steps, self.ts_multiplier)

    @property
    def lake_cell_ids(self) -> list[int]:
        """Flat row-major cell2d ids of the surface-lake footprint (layer 0)."""
        return [
            r * self.ncol + c
            for r in range(self.row_start, self.row_stop)
            for c in range(self.col_start, self.col_stop)
        ]

    @property
    def lake_footprint_area_ft2(self) -> float:
        return float(
            sum(
                self.delr_ft[c] * self.delc_ft[r]
                for r in range(self.row_start, self.row_stop)
                for c in range(self.col_start, self.col_stop)
            )
        )

    # -- SI helpers (HMP runs in meters/seconds) -----------------------------

    @property
    def n_cells(self) -> int:
        return self.nrow * self.ncol

    @property
    def delr_m(self) -> np.ndarray:
        return self.delr_ft * self.feet_to_meter

    @property
    def delc_m(self) -> np.ndarray:
        return self.delc_ft * self.feet_to_meter

    def _ft_to_m(self, value: float) -> float:
        return float(value) * self.feet_to_meter

    @property
    def top_m(self) -> float:
        return self._ft_to_m(self.top_ft)

    @property
    def botm_m(self) -> tuple[float, ...]:
        return tuple(self._ft_to_m(b) for b in self.botm_ft)

    @property
    def bed_elevation_m(self) -> float:
        return self._ft_to_m(self.bed_elevation_ft)

    @property
    def stage_init_m(self) -> float:
        return self._ft_to_m(self.stage_init_ft)

    @property
    def strt_m(self) -> float:
        return self._ft_to_m(self.strt_ft)

    @property
    def head_left_m(self) -> float:
        return self._ft_to_m(self.head_left_ft)

    @property
    def head_right_m(self) -> float:
        return self._ft_to_m(self.head_right_ft)

    @property
    def k11_m_per_s(self) -> float:
        return self.k11_ft_per_day * self.feet_to_meter / self.seconds_per_day

    @property
    def k33_m_per_s(self) -> tuple[float, ...]:
        factor = self.feet_to_meter / self.seconds_per_day
        return tuple(k * factor for k in self.k33_ft_per_day)

    @property
    def specific_storage_per_s(self) -> float:
        return self.specific_storage_per_day / self.seconds_per_day

    @property
    def recharge_m_per_s(self) -> float:
        return self.recharge_ft_per_day * self.feet_to_meter / self.seconds_per_day

    @property
    def bedleak_per_s(self) -> float:
        return self.bedleak_per_day / self.seconds_per_day

    @property
    def rainfall_m_per_s(self) -> float:
        return self.rainfall_ft_per_day * self.feet_to_meter / self.seconds_per_day

    @property
    def evaporation_m_per_s(self) -> float:
        return self.evaporation_ft_per_day * self.feet_to_meter / self.seconds_per_day

    @property
    def period_length_seconds(self) -> float:
        return self.period_length_days * self.seconds_per_day

    @property
    def surfdep_m(self) -> float:
        return self._ft_to_m(_SURFDEP_FT)

    @property
    def abacus_stage_m(self) -> tuple[float, ...]:
        return tuple(self._ft_to_m(s) for s in self.abacus_stage_ft)

    def abacus_si_rows(self) -> list[tuple[float, float, float]]:
        """Vertical-walled (stage, volume, area) abacus rows in SI (m, m3, m2)."""
        area = self.lake_footprint_area_ft2 * self.feet_to_meter**2
        bed = self.bed_elevation_m
        return [
            (float(stage), float(area * (stage - bed)), float(area))
            for stage in self.abacus_stage_m
        ]


def load_geometry() -> LakeP01Geometry:
    """Parse ``metadata.toml`` into the typed p01 geometry view."""
    meta = load_case_metadata(CASE_DIR)
    units = dict(meta["units"])
    geom = dict(meta["geometry"])
    lake = dict(meta["lake"])
    aquifer = dict(meta["aquifer"])
    time_cfg = dict(meta["time"])
    solver = dict(meta["solver"])

    delr = np.asarray(geom["delr_ft"], dtype=float)
    return LakeP01Geometry(
        nlay=int(geom["nlay"]),
        nrow=int(geom["nrow"]),
        ncol=int(geom["ncol"]),
        top_ft=float(geom["top_ft"]),
        botm_ft=tuple(float(b) for b in geom["botm_ft"]),
        delr_ft=delr,
        delc_ft=delr.copy(),
        row_start=int(lake["row_start"]),
        row_stop=int(lake["row_stop"]),
        col_start=int(lake["col_start"]),
        col_stop=int(lake["col_stop"]),
        bed_elevation_ft=float(lake["bed_elevation_ft"]),
        stage_init_ft=float(lake["stage_init_ft"]),
        bedleak_per_day=float(lake["bedleak_per_day"]),
        abacus_stage_ft=tuple(float(s) for s in lake["abacus_stage_ft"]),
        rainfall_ft_per_day=float(lake["rainfall_ft_per_day"]),
        evaporation_ft_per_day=float(lake["evaporation_ft_per_day"]),
        k11_ft_per_day=float(aquifer["k11_ft_per_day"]),
        k33_ft_per_day=tuple(float(k) for k in aquifer["k33_ft_per_day"]),
        specific_storage_per_day=float(aquifer["specific_storage_per_day"]),
        specific_yield=float(aquifer["specific_yield"]),
        strt_ft=float(aquifer["strt_ft"]),
        head_left_ft=float(aquifer["head_left_ft"]),
        head_right_ft=float(aquifer["head_right_ft"]),
        recharge_ft_per_day=float(aquifer["recharge_ft_per_day"]),
        period_length_days=float(time_cfg["period_length_days"]),
        n_steps=int(time_cfg["n_steps"]),
        ts_multiplier=float(time_cfg["ts_multiplier"]),
        outer_maximum=int(solver["outer_maximum"]),
        inner_maximum=int(solver["inner_maximum"]),
        outer_dvclose=float(solver["outer_dvclose"]),
        inner_dvclose=float(solver["inner_dvclose"]),
        rclose=float(solver["rclose"]),
        feet_to_meter=float(units["feet_to_meter"]),
        seconds_per_day=float(units["seconds_per_day"]),
    )


__all__ = ["CASE_DIR", "CASE_ID", "LakeP01Geometry", "load_geometry"]
