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
from hydromodpy.core.time.period_aggregation import observed_on_periods
from hydromodpy.core.time.time_method import observable_time_method

logger = get_logger(__name__)

OBSERVED_SUFFIX = "_obs"
"""Suffix the ingestion appends to an observed variable (``discharge_obs``)."""

_SCALAR_METRICS = ("nse", "log_nse", "rmse", "mae", "bias", "pbias", "correlation")


def write_fit_metrics(sim_id: str, store: Any) -> int:
    """Score every simulated series against its observed twin. Returns the count.

    Pairs are made on the variable name: a simulated ``discharge`` meets the
    ``discharge_obs`` the ingestion wrote, whatever station each sits under. Each
    simulated period takes the observations it covers, so a three-year
    simulation scored against a forty-year gauge keeps the overlap and says how
    many periods that was.
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
    paired = _pair_on_time(simulated, reference, method=observable_time_method(variable))
    if len(paired) < 2:
        # A steady run holds one value: there is no series to score, and saying
        # so at warning level would cry wolf on every steady phase. A transient
        # run that still fails to pair IS an anomaly, and keeps the warning.
        level = logger.debug if len(simulated) < 2 else logger.warning
        level(
            "Not scoring '%s' for sim %s: the simulated series (%d step(s)) and "
            "the %s observations share %d period(s).",
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


def _pair_on_time(simulated: pd.DataFrame, reference: pd.DataFrame, *, method: str) -> pd.DataFrame:
    """Put the observations on the periods the simulated stamps close.

    A simulated stamp is the END of its stress period and an observation is
    stamped at the start of what it averages, whatever its hour: a gauge
    stamped at noon still falls in its day. Joining the two on equal
    timestamps compared a monthly run with the one gauge day that opens the
    NEXT month. The rule is the one the calibration scores with,
    :func:`hydromodpy.core.time.period_aggregation.observed_on_periods`:
    ``method`` is ``"mean"`` for a discharge, averaged over the period, and
    ``"point"`` for a head or a lake level, read at the stamp.

    The method comes from the core table
    :data:`hydromodpy.core.time.time_method.OBSERVABLE_TIME_METHODS`, not from
    the field registry: this layer may not import ``results``.
    """
    sim = pd.Series(
        simulated["value"].to_numpy(dtype=float),
        index=pd.DatetimeIndex(pd.to_datetime(simulated["time"], utc=True)),
    ).sort_index()
    obs = pd.Series(
        reference["value"].to_numpy(dtype=float),
        index=pd.DatetimeIndex(pd.to_datetime(reference["time"], utc=True)),
    )
    aligned = observed_on_periods(obs, sim.index, method=method)
    paired = pd.DataFrame(
        {"time": sim.index, "sim": sim.to_numpy(), "obs": aligned.to_numpy(dtype=float)}
    )
    return paired.dropna().reset_index(drop=True)
