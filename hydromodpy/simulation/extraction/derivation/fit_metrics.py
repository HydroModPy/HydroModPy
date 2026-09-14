"""Goodness of fit of a run against the observations ingested beside it.

A run calibrated against a gauge used to carry no fit metric at all. The cost
lived in the calibration session, under the one objective the phase optimised,
and the promoted run itself said nothing: ``hmp catalog show`` reported the
solver runtime and stopped there. Reading how well a run matched meant opening
the session, and comparing two runs meant trusting that both had been scored the
same way.

The panel written here is the run's own answer, computed once from the series it
already persists, so it travels with the run, survives the session, and is the
same for every run whatever calibrated it.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from hydromodpy.core import metrics as core_metrics
from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

OBSERVED_SUFFIX = "_obs"
"""Suffix the ingestion appends to an observed variable (``discharge_obs``)."""

_SCALAR_METRICS = ("nse", "log_nse", "rmse", "mae", "bias", "pbias", "correlation")


def write_fit_metrics(sim_id: str, store: Any) -> int:
    """Score every simulated series against its observed twin. Returns the count.

    Pairs are made on the variable name: a simulated ``discharge`` meets the
    ``discharge_obs`` the ingestion wrote, whatever station each sits under. The
    two are joined on their timestamps, so a three-year simulation scored against
    a forty-year gauge keeps the overlap and says how many samples that was.
    """
    try:
        frame = _read_timeseries(store, sim_id)
    except Exception:
        logger.debug("No timeseries to score for sim %s", sim_id, exc_info=True)
        return 0
    if frame.empty:
        return 0

    observed = {
        str(name)[: -len(OBSERVED_SUFFIX)]
        for name in frame["variable"].unique()
        if str(name).endswith(OBSERVED_SUFFIX)
    }
    written = 0
    for variable in sorted(observed):
        simulated = frame[frame["variable"] == variable]
        reference = frame[frame["variable"] == variable + OBSERVED_SUFFIX]
        if simulated.empty or reference.empty:
            continue
        written += _score_one(store, sim_id, variable, simulated, reference)
    if written:
        logger.info("Wrote %d fit metric(s) for sim %s", written, sim_id)
    return written


def _read_timeseries(store: Any, sim_id: str) -> pd.DataFrame:
    """Every persisted series of one run, as one frame."""
    return store.connection.execute(
        "SELECT station_id, variable, time, value FROM timeseries WHERE sim_id = ?",
        [str(sim_id)],
    ).df()


def _score_one(
    store: Any,
    sim_id: str,
    variable: str,
    simulated: pd.DataFrame,
    reference: pd.DataFrame,
) -> int:
    """Write the panel for one variable, or nothing when the two never overlap."""
    station = str(reference["station_id"].iloc[0])
    paired = _pair_on_time(simulated, reference)
    if len(paired) < 2:
        # A steady run holds one value: there is no series to score, and saying
        # so at warning level would cry wolf on every steady phase. A transient
        # run that still fails to pair IS an anomaly, and keeps the warning.
        level = logger.debug if len(simulated) < 2 else logger.warning
        level(
            "Not scoring '%s' for sim %s: the simulated series (%d step(s)) and "
            "the %s observations share %d timestamp(s).",
            variable,
            sim_id,
            len(simulated),
            station,
            len(paired),
        )
        return 0

    sim = paired["sim"].to_numpy(dtype=float)
    obs = paired["obs"].to_numpy(dtype=float)
    values: dict[str, float] = {
        name: getattr(core_metrics, name)(sim, obs) for name in _SCALAR_METRICS
    }
    # kge returns its decomposition too: r tells timing from amplitude (alpha)
    # and from volume (beta), which is what a bare score cannot separate.
    values.update(
        {
            f"kge_{key}" if key != "kge" else "kge": v
            for key, v in core_metrics.kge(sim, obs).items()
        }
    )

    start, end = paired["time"].min(), paired["time"].max()
    written = 0
    for name, value in values.items():
        try:
            store.write_metric(
                sim_id,
                station_id=station,
                metric_name=name,
                value=float(value),
                variable=variable,
                n_samples=int(len(paired)),
                period_start=start,
                period_end=end,
            )
            written += 1
        except Exception:
            logger.debug("Could not persist metric %s for sim %s", name, sim_id, exc_info=True)
    return written


def _pair_on_time(simulated: pd.DataFrame, reference: pd.DataFrame) -> pd.DataFrame:
    """Join the two series on their timestamps, falling back to the calendar day.

    A daily run stamped at midnight and a gauge stamped at noon share no exact
    timestamp, and an empty overlap would read as "no observation" when the two
    cover the same years. The day is the resolution both are published at, so it
    is the honest fallback; anything coarser would pair samples that are not.
    """
    left = simulated[["time", "value"]].rename(columns={"value": "sim"})
    right = reference[["time", "value"]].rename(columns={"value": "obs"})
    exact = left.merge(right, on="time", how="inner").dropna()
    if len(exact) >= 2:
        return exact

    left = left.assign(day=pd.to_datetime(left["time"], utc=True).dt.date)
    right = right.assign(day=pd.to_datetime(right["time"], utc=True).dt.date)
    daily = left.merge(right.drop(columns="time"), on="day", how="inner").dropna()
    return daily.drop(columns="day")
