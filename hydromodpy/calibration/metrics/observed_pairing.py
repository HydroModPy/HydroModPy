"""Pair a weighted block's outputs with the records the project loaded.

A block scores value vectors, and until now those vectors could only be typed
into the file: positional, dateless, and impossible to reconcile with a gauge
whose record has its own sampling. So the one route that can weight several
targets against each other was also the one that could not read a real
observation.

``observes`` closes that. The output names a station, this module loads its
record, aligns it on the simulated timestamps, and hands both back as the plain
vectors a block already knows how to score. Alignment is where the honesty is:
what neither series covers is dropped from both, and a pair with nothing in
common is refused by name rather than scored on an empty overlap.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd

from hydromodpy.calibration.config import CalibOutputDecl
from hydromodpy.calibration.metrics.series import load_observed
from hydromodpy.results.derive.time_alignment import align_observed_simulated

OBSERVED_FAMILY_BY_VARIABLE: Mapping[str, str] = {
    "discharge": "discharge",
    "head": "head",
    "stage": "lake_level",
    "lake_level": "lake_level",
}
"""What ``load_observed`` calls the family behind an output's ``variable``."""


@dataclass(frozen=True)
class PairedOutputs:
    """Observed and simulated vectors, aligned index for index."""

    observed: dict[str, list[float]]
    simulated: dict[str, list[float]]
    n_paired: dict[str, int]

    def dates_scored(self) -> int:
        """Return the smallest number of samples any output contributed."""
        return min(self.n_paired.values(), default=0)


def observing_outputs(outputs: Mapping[str, CalibOutputDecl]) -> dict[str, str]:
    """Return, per output name, the station it is scored against."""
    return {
        str(name): str(decl.observes)
        for name, decl in outputs.items()
        if getattr(decl, "observes", None)
    }


def observed_series_for_outputs(
    outputs: Mapping[str, CalibOutputDecl],
    ctx: Any,
) -> dict[str, pd.Series]:
    """Return the loaded record behind every output that names a station.

    Loaded once per phase, outside the trial loop: an observed record does not
    change with a parameter. A station the project never loaded is refused by
    name, with what was loaded, because the alternative is a block scored on an
    empty vector and reported as an infinite cost.
    """
    wanted = observing_outputs(outputs)
    if not wanted:
        return {}

    by_variable: dict[str, dict[str, pd.Series]] = {}
    series_by_output: dict[str, pd.Series] = {}
    for output_name, station_id in wanted.items():
        variable = str(getattr(outputs[output_name], "variable", "") or "").strip()
        family = OBSERVED_FAMILY_BY_VARIABLE.get(variable)
        if family is None:
            known = ", ".join(sorted(OBSERVED_FAMILY_BY_VARIABLE))
            raise ValueError(
                f"output {output_name!r} observes {station_id!r} but its variable "
                f"{variable!r} names no observed family. Observable variables: {known}."
            )
        if family not in by_variable:
            by_variable[family] = {
                record.station_id: record.series for record in load_observed(ctx, family)
            }
        loaded = by_variable[family]
        if station_id not in loaded:
            available = ", ".join(sorted(loaded)) or "nothing"
            raise ValueError(
                f"output {output_name!r} observes station {station_id!r}, which the "
                f"{family!r} data family did not load. Loaded: {available}."
            )
        series_by_output[output_name] = loaded[station_id]
    return series_by_output


def pair_outputs_with_observations(
    *,
    observed: Mapping[str, pd.Series],
    simulated: Mapping[str, pd.Series],
    scoring_window: tuple[pd.Timestamp | None, pd.Timestamp | None] | None = None,
    min_samples: int = 1,
) -> PairedOutputs:
    """Align each observed record on its simulated series and return both.

    ``scoring_window`` bounds the dates kept. It is applicable here and nowhere
    else in the block route: these series carry timestamps, which is exactly
    what a window needs to cut on.

    ``min_samples`` is the fewest pairs a member may be scored on. An overlap
    that collapses to three days still produces a number, and a weight of 65 per
    cent resting on three days is not what the file says it is.
    """
    paired_observed: dict[str, list[float]] = {}
    paired_simulated: dict[str, list[float]] = {}
    counts: dict[str, int] = {}

    for name, record in observed.items():
        series = simulated.get(name)
        if series is None:
            raise ValueError(f"output {name!r} observes a station but produced no series")
        if not isinstance(series.index, pd.DatetimeIndex):
            raise ValueError(
                f"output {name!r} observes a station, so its simulated series has to "
                "carry timestamps to align on, and it carries none. The run's time grid "
                "did not reach the extraction."
            )
        frame = align_observed_simulated(record, series)
        if scoring_window is not None:
            start, end = scoring_window
            if start is not None:
                frame = frame.loc[frame.index >= pd.Timestamp(start)]
            if end is not None:
                frame = frame.loc[frame.index <= pd.Timestamp(end)]
        if frame.empty:
            window = ""
            if scoring_window is not None and any(bound is not None for bound in scoring_window):
                window = f" inside {scoring_window[0]} to {scoring_window[1]}"
            raise ValueError(
                f"output {name!r} and the record it observes share no timestamp{window}: "
                f"the record runs {_span(record)} and the run {_span(series)}."
            )
        if len(frame) < int(min_samples):
            raise ValueError(
                f"output {name!r} and the record it observes share {len(frame)} dated "
                f"sample(s), fewer than the {int(min_samples)} "
                "[calibration.aggregate].min_samples asks for. A cost on that few is "
                "not the cost the weights describe."
            )
        paired_observed[name] = [float(value) for value in frame["obs"]]
        paired_simulated[name] = [float(value) for value in frame["sim"]]
        counts[name] = len(frame)

    return PairedOutputs(observed=paired_observed, simulated=paired_simulated, n_paired=counts)


def _span(series: pd.Series) -> str:
    if series.empty or not isinstance(series.index, pd.DatetimeIndex):
        return "over no dated sample"
    return f"from {series.index.min().date()} to {series.index.max().date()}"


__all__ = [
    "OBSERVED_FAMILY_BY_VARIABLE",
    "PairedOutputs",
    "observed_series_for_outputs",
    "observing_outputs",
    "pair_outputs_with_observations",
]
