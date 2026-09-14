"""Two-level comparison of the HMP LAK build against ex-gwf-lak-p01.

Level (a) STRUCTURAL: deterministic, no solver run. The home-grown DISV
CONNECTIONDATA must reproduce the upstream ``get_lak_connections`` connection
count and claktype split (25 VERTICAL + 20 HORIZONTAL) for the shared
single-layer footprint.

Level (b) NUMERICAL: run both models and compare the final lake stage, the gross
lake-aquifer exchange and each build's budget closure. The reference runs in
feet/days and the HMP build in meters/seconds, so both are converted to a common
basis (meters, m^3/s) before the stage / exchange metrics are computed.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from validation_cases.shared import load_case_tolerances

from .geometry import CASE_DIR, LakeP01Geometry, load_geometry
from .reference import LakeRunResult, run_reference
from .runtime_lak import build_hmp_connectiondata, run_hmp

_FEET_TO_METER = 0.3048


def _stage_in_meters(result: LakeRunResult) -> float:
    if result.length_unit == "feet":
        return result.final_stage * _FEET_TO_METER
    return result.final_stage


def _gross_exchange_m3_per_s(result: LakeRunResult) -> float:
    """Gross lake-aquifer flux on a common m^3/s basis.

    The reference budget is ft^3/day; the HMP budget m^3/s. We compare the GROSS
    magnitude (in + out) rather than the net: at steady state the net is a tiny
    difference of two large, near-equal terms and is dominated by the staircased
    lake perimeter, whereas the gross flux is a stable physical signal.
    """
    if result.length_unit == "feet":
        return result.lake_gwf_gross_exchange * (_FEET_TO_METER**3) / 86400.0
    return result.lake_gwf_gross_exchange


@dataclass(frozen=True, slots=True)
class StructuralComparison:
    """Deterministic CONNECTIONDATA structure of the home-grown DISV build."""

    n_connections: int
    n_vertical: int
    n_horizontal: int


@dataclass(frozen=True, slots=True)
class LakeP01Scenario:
    """Numerical + structural comparison of the HMP LAK build vs the reference."""

    metadata: dict
    geometry: LakeP01Geometry
    reference: LakeRunResult
    hmp: LakeRunResult
    structural: StructuralComparison

    # Numerical metrics, all on a common metres / m3-per-s basis.

    @property
    def reference_stage_m(self) -> float:
        return _stage_in_meters(self.reference)

    @property
    def hmp_stage_m(self) -> float:
        return _stage_in_meters(self.hmp)

    @property
    def final_stage_abs_error_m(self) -> float:
        return abs(self.hmp_stage_m - self.reference_stage_m)

    @property
    def rmse_stage_m(self) -> float:
        # A single steady stage per build; the RMSE collapses to the abs error but
        # the metric name matches the documented contract.
        return self.final_stage_abs_error_m

    @property
    def lake_gwf_exchange_rel_err(self) -> float:
        ref = _gross_exchange_m3_per_s(self.reference)
        hmp = _gross_exchange_m3_per_s(self.hmp)
        denom = max(abs(ref), 1.0e-12)
        return abs(hmp - ref) / denom

    @property
    def max_budget_percent_discrepancy(self) -> float:
        return max(
            abs(self.reference.budget_percent_discrepancy),
            abs(self.hmp.budget_percent_discrepancy),
        )


def build_structural_comparison(
    geometry: LakeP01Geometry | None = None,
) -> StructuralComparison:
    """Build the structural comparison from the home-grown CONNECTIONDATA only."""
    rows = build_hmp_connectiondata(geometry)
    counts = Counter(str(row[3]).upper() for row in rows)
    return StructuralComparison(
        n_connections=len(rows),
        n_vertical=int(counts.get("VERTICAL", 0)),
        n_horizontal=int(counts.get("HORIZONTAL", 0)),
    )


def run_lake_p01_scenario(*, workspace: Path) -> LakeP01Scenario:
    """Run both builds and assemble the full p01 comparison scenario."""
    from validation_cases.shared import load_case_metadata

    geometry = load_geometry()
    metadata = load_case_metadata(CASE_DIR)
    reference_ws = workspace / "reference"
    hmp_ws = workspace / "hmp"
    reference_ws.mkdir(parents=True, exist_ok=True)
    hmp_ws.mkdir(parents=True, exist_ok=True)

    reference = run_reference(reference_ws, geometry=geometry)
    hmp = run_hmp(hmp_ws, geometry=geometry)
    structural = build_structural_comparison(geometry)
    return LakeP01Scenario(
        metadata=metadata,
        geometry=geometry,
        reference=reference,
        hmp=hmp,
        structural=structural,
    )


def load_tolerances() -> dict:
    """Load the case tolerances."""
    return load_case_tolerances(CASE_DIR)


__all__ = [
    "LakeP01Scenario",
    "StructuralComparison",
    "build_structural_comparison",
    "load_tolerances",
    "run_lake_p01_scenario",
]
