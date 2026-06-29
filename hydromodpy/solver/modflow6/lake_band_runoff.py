"""Stage-dependent exposed-lakebed (marnage) runoff, injected via the MF6 BMI API.

For an active-littoral lake the shoreline retreats as the stage drops, exposing a
band of former lakebed. Rain on that band infiltrates (recharge, handled by MF6's
per-cell IWETLAKE toggle) but its overland-runoff fraction should shed directly
to the remaining pool. MF6 cannot size that band itself (the LAK ``RUNOFF`` input
is stage-independent), so we drive it through the BMI API: at each timestep start
we read the (previous step's) lake stage, size the exposed band, and set the lake
``RUNOFF`` to ``base_runoff + runoff_rate * exposed_area``.

The coupling is explicit (one-timestep lag), which is the standard, stable choice
for this kind of surface-to-lake feedback. The exposed-area math is a pure
function so it is unit-tested without a live solver.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

from hydromodpy.solver.modflow6.api_runner import Mf6ApiContext, Mf6ApiStep

__all__ = [
    "LakeBandRunoffSpec",
    "exposed_band_area",
    "make_exposed_band_runoff_callback",
]


def exposed_band_area(bed: np.ndarray, area: np.ndarray, stage: float) -> float:
    """Plan area of lake cells whose bed sits at/above ``stage`` (the dry band)."""
    bed = np.asarray(bed, dtype=float)
    area = np.asarray(area, dtype=float)
    return float(np.sum(area[bed >= float(stage)]))


@dataclass(frozen=True)
class LakeBandRunoffSpec:
    """One lake's exposed-band runoff coupling inputs.

    ``lake_index`` is the 0-based ``ifno`` of the lake within its LAK package.
    ``rate_per_period`` is the watershed-mean runoff rate ``[L/T]`` per stress
    period; ``base_runoff_per_period`` is the lake's existing (catchment) runoff
    ``[L^3/T]`` per period that the band term adds onto.
    """

    pkg: str | None
    lake_index: int
    bed: np.ndarray
    area: np.ndarray
    rate_per_period: Sequence[float]
    base_runoff_per_period: Sequence[float] = ()

    def _per_period(self, values: Sequence[float], kper: int) -> float:
        if not values:
            return 0.0
        return float(values[min(int(kper), len(values) - 1)])

    def runoff_at(self, stage: float, kper: int) -> float:
        """Return ``base_runoff + rate * exposed_area`` for stress period ``kper``."""
        rate = self._per_period(self.rate_per_period, kper)
        base = self._per_period(self.base_runoff_per_period, kper)
        band = max(0.0, rate * exposed_band_area(self.bed, self.area, stage))
        return base + band


def make_exposed_band_runoff_callback(
    specs: Sequence[LakeBandRunoffSpec],
) -> Callable[[Mf6ApiContext], None]:
    """Build a BMI callback that injects the exposed-band runoff each timestep.

    At ``timestep_start`` it reads each lake's stage, sizes the exposed band, and
    writes the lake ``RUNOFF`` to ``base + rate * exposed_area``. Lakes not listed
    in ``specs`` keep whatever ``RUNOFF`` the LAK package already holds.
    """
    by_pkg: dict[str | None, list[LakeBandRunoffSpec]] = {}
    for spec in specs:
        by_pkg.setdefault(spec.pkg, []).append(spec)

    def callback(ctx: Mf6ApiContext) -> None:
        if ctx.step is not Mf6ApiStep.timestep_start:
            return
        for pkg, pkg_specs in by_pkg.items():
            pkg_name = pkg or "LAK"
            stage = ctx.lak_get("XNEWPAK", pkg=pkg_name)  # solved stage, raw path
            runoff = np.array(ctx.read_lake_runoff(pkg=pkg_name), dtype=float)
            for spec in pkg_specs:
                idx = int(spec.lake_index)
                runoff[idx] = spec.runoff_at(float(stage[idx]), ctx.kper)
            ctx.write_lake_runoff(runoff, pkg=pkg_name)

    return callback
