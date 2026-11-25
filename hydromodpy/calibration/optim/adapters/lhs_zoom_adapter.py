"""Latin hypercubes in turn, each one drawn in the zone the trials so far leave open.

Level 1 is a Latin hypercube over the bounds of the phase. Each next level is a
Latin hypercube in the zone read from every trial solved before it. The zone
runs over the trials whose cost stays within the margin of the best one, widened
to the solved trial just below and just above them, and by at least one stratum
of the level before on each side. It is clipped to the bounds of the phase
(:func:`~hydromodpy.calibration.optim.cost_margin.zone_of_the_trials`).

The margin is the width the phase reads its interval with, so the zoom and the
interval of ``cost_profile`` say the same thing at two moments. Everything is
read and drawn in the variable the search walks, in decades for a log parameter.

A single parameter is moved. The neighbors of the best trial frame the minimum of
a curve, and they frame nothing along a ridge of two parameters. Level ``k`` is
drawn on ``lot_seed(seed, k)``. With ``[calibration] seed`` written, a resumed
session draws the same points, finds them in the cache and reads the same zone.
Without it, as for ``lhs``, a resumed session draws new points.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Sequence
from typing import Any, Literal

from hydromodpy.calibration.optim.adapters.lhs_adapter import design_budget, stratified_column
from hydromodpy.calibration.optim.cost_margin import (
    IntervalWidth,
    Zone,
    cell_measured_by_the_criterion,
    choose_interval_width,
    zone_of_the_trials,
)
from hydromodpy.calibration.optim.design import draw_unit, lot_seed
from hydromodpy.calibration.optim.method_config import LhsOptions, LhsZoomMethodConfig
from hydromodpy.calibration.optim.optimizer import (
    EngineTraits,
    EvaluationResult,
    ParamSuggestion,
    best_completed,
)
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.optim.stopping import CountedBudget
from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)


class LhsZoomAdapter:
    """One Latin hypercube per level, each level after the first in the zone of the trials so far."""

    traits = EngineTraits(
        max_parameters=1,
        libraries=("numpy", "scipy"),
        draws_a_normal=False,
        restarts_explore_differently=True,
        fixed_plan=True,
        takes_interval_width=True,
    )

    name = "lhs_zoom"
    options = LhsZoomMethodConfig

    def __init__(
        self,
        space: ParameterSpace,
        *,
        levels: Sequence[int] = (24, 16),
        optimization: Literal["random-cd", "lloyd"] | None = None,
        seed: int | None = None,
        interval_width: IntervalWidth | None = None,
    ) -> None:
        if space.dim != 1:
            raise ValueError(
                f"lhs_zoom moves one parameter, got {space.dim}. Its zone is framed by the "
                "neighbors of the best trial along one axis. Use cma_es or gp_mapping for more."
            )
        if len(levels) < 2 or min(levels) < 2:
            raise ValueError(
                f"lhs_zoom needs at least two levels of at least two points, got {list(levels)}. "
                "For one level use lhs."
            )
        self.space = space
        self.levels = [int(n) for n in levels]
        self._parameter = space.parameters[0]
        self._optimization = optimization
        self._seed = seed
        self._width = interval_width if interval_width is not None else choose_interval_width(False)
        self._history: list[EvaluationResult] = []
        self._values: dict[int, float] = {}
        self._trial_id = 0
        self._level = 0
        self._queue: list[float] = []
        self._box = self._parameter
        self._records: list[dict[str, Any]] = []
        self._draw(self._parameter, None)

    @property
    def counted_budget(self) -> CountedBudget:
        """Every level, counted up front: ``"auto"`` budgets exactly their sum."""
        return design_budget(sum(self.levels))

    def _draw(self, box: CalibParameter, zone: Zone | None, margin: IntervalWidth | None = None):
        """Draw the points of the level in ``self._level`` over ``box`` and record it."""
        size = self.levels[self._level]
        seed = None if self._seed is None else lot_seed(self._seed, self._level + 1)
        unit = draw_unit("lhs", size, 1, seed, LhsOptions(optimization=self._optimization))
        column = stratified_column(box, unit[:, 0])
        self._box = box
        self._queue = [box.to_physical(float(y)) for y in column]
        self._records.append(self._record(size, box, zone, margin))

    def _record(
        self, size: int, box: CalibParameter, zone: Zone | None, margin: IntervalWidth | None
    ) -> dict[str, Any]:
        """Return what the report keeps of one level: its box and what it was read from."""
        return {
            "level": self._level + 1,
            "size": size,
            "low": float(box.lower),
            "high": float(box.upper),
            "low_end": "bound" if zone is None else zone.lower_end,
            "high_end": "bound" if zone is None else zone.upper_end,
            "best_cost": None if zone is None else zone.best_cost,
            "threshold": None if zone is None else zone.threshold,
            "n_within": 0 if zone is None else zone.n_within,
            "n_lost": 0 if zone is None else zone.n_lost,
            "narrowed": False if zone is None else zone.narrowed,
            "margin": None if margin is None else margin.margin,
            "margin_kind": None if margin is None else margin.kind,
        }

    def _zone(self) -> tuple[CalibParameter, Zone, IntervalWidth]:
        """Return the box of the next level, the zone it was read as and the margin used."""
        param = self._parameter
        width = self._width
        if width.margin is None:
            cell = cell_measured_by_the_criterion(self._history)
            if cell is not None:
                width = width.measured(cell)
        rows = [r for r in self._history if r.trial_id in self._values]
        zone = zone_of_the_trials(
            [param.to_transformed(self._values[r.trial_id]) for r in rows],
            [r.cost if r.status == "completed" else math.nan for r in rows],
            margin=width.margin,
            kind=width.kind,
            bounds=(param.lower_transformed, param.upper_transformed),
            stratum=(self._box.upper_transformed - self._box.lower_transformed)
            / self.levels[self._level],
        )
        box = dataclasses.replace(
            param, lower=param.to_physical(zone.lower), upper=param.to_physical(zone.upper)
        )
        return box, zone, width

    def _told_all(self) -> bool:
        return len(self._history) == self._trial_id

    def ask(self, n: int = 1) -> list[ParamSuggestion]:
        """Serve the points of the level in hand, and draw the next level once it is all told.

        Like a population search, it serves nothing between the last point of a level and the
        result of that point, and the engine tells every batch before it asks again.
        """
        if not self._queue and self._level + 1 < len(self.levels) and self._told_all():
            box, zone, width = self._zone()
            if not zone.narrowed:
                logger.warning(
                    "lhs_zoom level %d draws over the whole box again: the trials of the "
                    "levels before did not narrow it (flat cost, no solved trial or no margin "
                    "to read).",
                    self._level + 2,
                )
            self._level += 1
            self._draw(box, zone, width)
        out: list[ParamSuggestion] = []
        while self._queue and len(out) < n:
            value = self._queue.pop(0)
            self._trial_id += 1
            self._values[self._trial_id] = value
            out.append(
                ParamSuggestion(
                    trial_id=self._trial_id, values={self._parameter.name: value}, source="ask"
                )
            )
        return out

    def tell(self, results: list[EvaluationResult]) -> None:
        self._history.extend(results)

    def best(self) -> EvaluationResult | None:
        return best_completed(self._history)

    def converged(self) -> bool:
        """Whether the last level is drawn, served and told."""
        return self._level + 1 >= len(self.levels) and not self._queue and self._told_all()

    def progress_label(self) -> str:
        """What the live progress line shows: the level, then the best cost."""
        best = self.best()
        tail = "" if best is None else f", best {best.cost:.4g}"
        return f"level {self._level + 1} of {len(self.levels)}{tail}"

    def zone_record(self) -> list[dict[str, Any]]:
        """Return one record per level drawn: its size, its box and what it was read from."""
        return [dict(record) for record in self._records]


__all__ = ["LhsZoomAdapter"]
