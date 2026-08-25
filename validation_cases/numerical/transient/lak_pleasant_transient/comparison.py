"""Scalar metrics for the transient multi-layer LAK regression.

The case has no external reference run: it pins the HMP DISV LAK build's own
behaviour. The comparison exposes a few robust scalars:

* STRUCTURAL: the home-grown CONNECTIONDATA carries HORIZONTAL bank seepage in
  BOTH occupied layers plus a VERTICAL leakage per lake column (deterministic, no
  solver run), proving the lake is incised across the top two layers.
* TRANSIENT: the lake stage at the end of each stress period (the stage responds
  to the per-period rainfall / evaporation / runoff), and the worst per-period LAK
  water-balance closure reported by MF6.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from validation_cases.shared import load_case_tolerances

from .geometry import CASE_DIR, PleasantTransientGeometry, load_geometry
from .runtime_lak import (
    TransientLakeRunResult,
    build_hmp_connectiondata,
    horizontal_connections_by_layer,
    run_hmp,
)


@dataclass(frozen=True, slots=True)
class StructuralComparison:
    """Deterministic CONNECTIONDATA structure of the multi-layer build."""

    n_connections: int
    n_vertical: int
    n_horizontal: int
    horizontal_by_layer: dict[int, int]
    occupied_layers: int

    @property
    def n_layers_with_horizontal(self) -> int:
        return len(self.horizontal_by_layer)

    @property
    def spans_occupied_layers(self) -> bool:
        """True when every occupied layer carries at least one HORIZONTAL link."""
        return all(self.horizontal_by_layer.get(lay, 0) > 0 for lay in range(self.occupied_layers))


@dataclass(frozen=True, slots=True)
class PleasantTransientScenario:
    """Transient + structural comparison of the multi-layer LAK build."""

    metadata: dict
    geometry: PleasantTransientGeometry
    hmp: TransientLakeRunResult
    structural: StructuralComparison

    @property
    def period_stages_m(self) -> tuple[float, ...]:
        return self.hmp.period_stages

    @property
    def n_periods(self) -> int:
        return len(self.hmp.period_stages)

    @property
    def stage_swing_m(self) -> float:
        """Max-minus-min lake stage across the stress periods.

        A meaningful swing proves the per-period forcings actually move the lake
        (a flat series would mean the transient drivers had no effect).
        """
        stages = self.hmp.period_stages
        return max(stages) - min(stages)

    @property
    def max_budget_percent_discrepancy(self) -> float:
        return max(abs(p) for p in self.hmp.period_budget_percent)


def build_structural_comparison(
    geometry: PleasantTransientGeometry | None = None,
) -> StructuralComparison:
    """Build the structural comparison from the multi-layer CONNECTIONDATA only."""
    geom = geometry if geometry is not None else load_geometry()
    rows = build_hmp_connectiondata(geom)
    horizontal_by_layer = horizontal_connections_by_layer(rows)
    n_vertical = sum(1 for row in rows if str(row[3]).upper() == "VERTICAL")
    n_horizontal = sum(horizontal_by_layer.values())
    return StructuralComparison(
        n_connections=len(rows),
        n_vertical=n_vertical,
        n_horizontal=n_horizontal,
        horizontal_by_layer=horizontal_by_layer,
        occupied_layers=geom.occupied_layers,
    )


def run_pleasant_transient_scenario(*, workspace: Path) -> PleasantTransientScenario:
    """Run the transient build and assemble the full comparison scenario."""
    from validation_cases.shared import load_case_metadata

    geometry = load_geometry()
    metadata = load_case_metadata(CASE_DIR)
    workspace.mkdir(parents=True, exist_ok=True)

    hmp = run_hmp(workspace, geometry=geometry)
    structural = build_structural_comparison(geometry)
    return PleasantTransientScenario(
        metadata=metadata,
        geometry=geometry,
        hmp=hmp,
        structural=structural,
    )


def load_tolerances() -> dict:
    """Load the case tolerances."""
    return load_case_tolerances(CASE_DIR)


__all__ = [
    "PleasantTransientScenario",
    "StructuralComparison",
    "build_structural_comparison",
    "load_tolerances",
    "run_pleasant_transient_scenario",
]
