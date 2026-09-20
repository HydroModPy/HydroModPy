"""Score model observables without a live workflow context."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from hydromodpy.calibration.metrics.observed_pairing import (
    observing_outputs,
    pair_outputs_with_observations,
)
from hydromodpy.calibration.optim.objective import build_objective_from_config
from hydromodpy.core.contracts.observables import ObservableResult
from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from hydromodpy.calibration.config import CalibObjectiveBlockDecl, CalibOutputDecl, OutputTime
    from hydromodpy.calibration.optim.objective import Objective

logger = get_logger(__name__)


def slice_time(values: np.ndarray, time: Any, reducer: str) -> list[float]:
    """Apply ``time`` selector and ``reducer`` to a 1D array of simulated values."""
    arr = np.asarray(values, dtype=float).ravel()
    if arr.size == 0:
        return []
    if time == "first":
        arr = arr[:1]
    elif time == "last":
        arr = arr[-1:]
    if reducer == "mean":
        return [float(np.nanmean(arr))]
    if reducer == "sum":
        return [float(np.nansum(arr))]
    if reducer == "last":
        return [float(arr[-1])]
    return [float(v) for v in arr]


def select_observable_times(result: ObservableResult, time: OutputTime) -> ObservableResult:
    """Select first or last values with their timestamps before pairing."""
    if time == "all" or isinstance(time, list):
        return result
    values = np.asarray(result.values).reshape(-1)
    times = None if result.times is None else pd.DatetimeIndex(result.times)
    if times is not None and len(times) != values.size:
        raise ValueError(f"Output {result.request_id!r} has mismatched timestamps and values")
    if time == "first":
        selected = np.arange(min(1, values.size))
    else:
        selected = np.arange(max(0, values.size - 1), values.size)
    return replace(
        result,
        values=values[selected],
        times=None if times is None else times[selected],
    )


def dated_series(result: ObservableResult) -> pd.Series | None:
    """Return the result as a timestamped series, or ``None`` when it is not one."""
    times = getattr(result, "times", None)
    if times is None:
        return None
    values = np.asarray(result.values, dtype=float).ravel()
    index = pd.DatetimeIndex(times)
    if values.size == 0 or len(index) != values.size:
        return None
    return pd.Series(values, index=index)


def refuse_window_without_dates(
    outputs: Mapping[str, CalibOutputDecl],
    objective_blocks: list[CalibObjectiveBlockDecl],
    scoring_window: tuple[pd.Timestamp | None, pd.Timestamp | None] | None,
    observing: Mapping[str, str],
) -> None:
    """Refuse a window on the blocks whose outputs carry no dates to cut on.

    An output that names a station is aligned on the simulated timestamps, so a
    window applies to it exactly. One scored positionally has no date to compare
    a bound against: honouring the window is impossible, and dropping it would
    report a cost over the whole run under the name of a windowed one.
    """
    if scoring_window is None or not any(bound is not None for bound in scoring_window):
        return
    dateless_by_block: dict[str, list[str]] = {}
    for block in objective_blocks:
        dateless = sorted(
            str(name)
            for name in block.uses_outputs
            if str(name) in outputs and str(name) not in observing
        )
        if dateless:
            dateless_by_block[str(block.name)] = dateless
    if not dateless_by_block:
        return
    start, end = scoring_window
    listed = "; ".join(
        f"block {name!r} on output(s) {outputs_}" for name, outputs_ in dateless_by_block.items()
    )
    raise ValueError(
        f"scoring_window {start} to {end} cannot be applied to {listed}: those outputs "
        "are scored on extracted value vectors, which carry no time axis to cut on. "
        "Point them at a loaded record with 'observes', use warmup_periods, which "
        "counts samples, or score on a single variable."
    )


class ObservableScorer:
    """Score comparable series and separately prepared network distances.

    Producers own spatial extraction and runoff corrections. Network values
    are prepared distance pairs, never raw release fields. Observations are
    keyed by output name and are loaded before this scorer is built.
    """

    def __init__(
        self,
        outputs: Mapping[str, CalibOutputDecl],
        objective_blocks: list[CalibObjectiveBlockDecl],
        *,
        observed_records: Mapping[str, pd.Series] | None = None,
        warmup_periods: int = 0,
        scoring_window: tuple[pd.Timestamp | None, pd.Timestamp | None] | None = None,
        min_samples: int = 1,
    ) -> None:
        refuse_window_without_dates(
            outputs, objective_blocks, scoring_window, observing_outputs(outputs)
        )
        self._outputs: dict[str, CalibOutputDecl] = dict(outputs)
        self._cfg: SimpleNamespace = SimpleNamespace(
            outputs=dict(outputs),
            objective_blocks=list(objective_blocks),
            warmup_periods=int(warmup_periods),
        )
        self._observed: dict[str, pd.Series] = dict(observed_records or {})
        self._scoring_window: tuple[pd.Timestamp | None, pd.Timestamp | None] | None = (
            scoring_window
        )
        self._min_samples: int = min_samples
        self._composite: Objective | None = (
            None if self._observed else build_objective_from_config(self._cfg)
        )

    def score(
        self,
        observables: Mapping[str, ObservableResult],
        *,
        network_values: Mapping[str, Sequence[float]] | None = None,
        diagnostics: Mapping[str, float] | None = None,
    ) -> tuple[float, dict[str, float]]:
        """Return the cost and components from one model's outputs."""
        simulated: dict[str, Sequence[float]] = {}
        series: dict[str, pd.Series] = {}
        for name, output in self._outputs.items():
            if output.support == "network":
                if network_values is None or name not in network_values:
                    raise ValueError(f"Output {name!r} needs prepared network distances")
                simulated[name] = network_values[name]
                continue
            result = observables.get(name)
            if result is None or np.asarray(result.values).size == 0:
                raise NotImplementedError(
                    f"Model returned no calibration values for output {name!r}"
                )
            result = select_observable_times(result, output.time)
            simulated[name] = slice_time(result.values, "all", output.reducer)
            dated = dated_series(result)
            if dated is not None:
                series[name] = dated

        objective = self._composite
        paired_counts: dict[str, int] = {}
        if self._observed:
            paired = pair_outputs_with_observations(
                observed=self._observed,
                simulated={name: series[name] for name in self._observed if name in series},
                scoring_window=self._scoring_window,
                min_samples=self._min_samples,
            )
            simulated.update(paired.simulated)
            paired_counts = dict(paired.n_paired)
            objective = build_objective_from_config(self._cfg, observed_by_output=paired.observed)
        try:
            value = objective.evaluate(simulated)
        except Exception as exc:
            logger.exception("Composite objective evaluation failed")
            raise RuntimeError(
                f"Composite objective evaluation failed: {type(exc).__name__}: {exc}"
            ) from exc
        components = {key: float(val) for key, val in value.components.items()}
        components.update({key: float(val) for key, val in (diagnostics or {}).items()})
        components.update(
            {f"{name}.n_paired": float(count) for name, count in paired_counts.items()}
        )
        return float(value.total), components
