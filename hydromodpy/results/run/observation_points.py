"""Sample the observation points a run declared, and keep them on disk.

What
----
:func:`sample_observation_points` takes the points declared in ``[observation]``
(as plain dicts, so no configuration type crosses into ``results``), resolves
each one to a cell, writes its series into the run's ``timeseries`` payload and
the declaration itself into ``tables.parquet/observation_points.parquet``.

Why the Parquet payload matters
-------------------------------
The index is rebuilt from the run directories, so state with no home on disk
would come back empty. Both halves of a declared point are run artifacts:
the series in ``timeseries.parquet`` and the declaration in
``observation_points.parquet``. The points are sampled by the run itself,
through its store, before the index knows it.

Station ids are prefixed with ``obs:`` in the timeseries table so a declared
probe never collides with a solver station (gauge, SFR reach, lake).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

import pandas as pd

from hydromodpy.core.logging import get_logger
from hydromodpy.core.scope import SIMULATED
from hydromodpy.results.run.point import PointRequest, read_point
from hydromodpy.results.storage.declared import refuse_unknown_series

if TYPE_CHECKING:
    from hydromodpy.results.storage.run_store import RunStore

logger = get_logger(__name__)

STATION_PREFIX = "obs:"
"""Prefix of the timeseries station id of a declared observation point."""


def station_id_for(point_id: str) -> str:
    """Return the timeseries station id of a declared observation point."""
    return f"{STATION_PREFIX}{point_id}"


def sample_observation_points(
    store: RunStore,
    sim_id: str,
    declarations: Sequence[Mapping[str, Any]],
) -> int:
    """Resolve and sample every declared point of one run.

    ``declarations`` carries one mapping per point with the keys ``id``, ``x``,
    ``y``, ``layer``, ``depth`` and ``variables``. Returns the number of series
    written. A point that cannot be sampled (outside the mesh, unknown field,
    a variable with no descriptor) is reported and skipped, and the points after
    it are still sampled: a declaration mistake must not lose the run.
    """
    from hydromodpy.results.run.view import Run

    if not declarations:
        return 0
    run = Run(str(sim_id), store)
    written = 0
    resolved: list[dict[str, Any]] = []
    for entry in declarations:
        point_id = str(entry["id"])
        variables = [str(name) for name in entry.get("variables") or ()]
        if not variables:
            continue
        request = PointRequest(
            x=float(entry["x"]),
            y=float(entry["y"]),
            layer=entry.get("layer"),
            depth=entry.get("depth"),
            label=point_id,
        )
        try:
            frame = read_point(run, variables, request)
            refuse_unknown_series(frame["variable"].unique())
        except Exception as exc:
            logger.warning("Observation point '%s' could not be sampled: %s", point_id, exc)
            continue
        written += _write_series(store, sim_id, point_id, frame)
        layer = frame["layer"].iloc[0]
        resolved.append(
            {
                "station_id": point_id,
                "x": float(entry["x"]),
                "y": float(entry["y"]),
                "cell_id": int(frame["cell"].iloc[0]),
                "layer": 0 if pd.isna(layer) else int(layer),
            }
        )
    if resolved:
        store.write_view(sim_id, "observation_points", resolved)
    logger.info("Sampled %d observation series for sim %s", written, sim_id)
    return written


def sample_declared_points(cfg: Any, *, store: RunStore) -> int:
    """Sample the ``[observation]`` points while the run still holds its fields.

    A point known in advance costs nothing to read later: its series lands in
    the timeseries table of the run and its declaration in
    ``observation_points.parquet``. A failure is logged, never fatal: the
    results of the run are already in.
    """
    observation = getattr(cfg, "observation", None)
    declarations = observation.declarations() if observation is not None else []
    if not declarations:
        return 0
    try:
        return sample_observation_points(store, store.sim_id, declarations)
    except Exception:
        logger.warning("Could not sample the declared observation points", exc_info=True)
        return 0


def _write_series(store: RunStore, sim_id: str, point_id: str, frame: pd.DataFrame) -> int:
    """Write one point's per-variable series into the timeseries payload."""
    station = station_id_for(point_id)
    written = 0
    for variable, chunk in frame.groupby("variable", sort=False):
        store.write_timeseries_columns(
            sim_id,
            {
                "station_id": station,
                "variable": str(variable),
                "timestep": chunk["timestep"].to_numpy(dtype="int64"),
                "time": pd.DatetimeIndex(chunk["time"]),
                "value": chunk["value"].to_numpy(dtype="float64"),
                "unit": str(chunk["unit"].iloc[0] or ""),
                "source": SIMULATED,
            },
        )
        written += 1
    return written


__all__ = [
    "STATION_PREFIX",
    "sample_declared_points",
    "sample_observation_points",
    "station_id_for",
]
