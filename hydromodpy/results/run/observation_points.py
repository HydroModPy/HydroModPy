"""Sample the observation points a run declared, and keep them on disk.

What
----
:func:`sample_observation_points` takes the points declared in ``[observation]``
(as plain dicts, so no configuration type crosses into ``results``), resolves
each one to a cell, writes its series into the run's ``timeseries`` payload and
the declaration itself into ``tables.parquet/observation_points.parquet``.

Why the Parquet payload matters
-------------------------------
A declared point that lived only in the index would not survive
``hmp catalog reindex``: the index is rebuilt from the run directories, so
state with no home on disk comes back empty. Both halves of a declared point
are therefore run artefacts: the series in ``timeseries.parquet`` and the
declaration in ``observation_points.parquet``, both exposed as Parquet-backed
views that a rebuild finds with the files themselves.

Station ids are prefixed with ``obs:`` in the timeseries table so a declared
probe never collides with a solver station (gauge, SFR reach, lake).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

import pandas as pd

from hydromodpy.core.logging import get_logger
from hydromodpy.results.run.point import PointRequest, read_point

if TYPE_CHECKING:
    from hydromodpy.results.catalog import Catalog

logger = get_logger(__name__)

STATION_PREFIX = "obs:"
"""Prefix of the timeseries station id of a declared observation point."""


def station_id_for(point_id: str) -> str:
    """Return the timeseries station id of a declared observation point."""
    return f"{STATION_PREFIX}{point_id}"


def sample_observation_points(
    catalog: Catalog,
    sim_id: str,
    declarations: Sequence[Mapping[str, Any]],
) -> int:
    """Resolve and sample every declared point of one run.

    ``declarations`` carries one mapping per point with the keys ``id``, ``x``,
    ``y``, ``layer``, ``depth`` and ``variables``. Returns the number of series
    written. A point that cannot be sampled (outside the mesh, unknown field)
    is reported and skipped: a declaration mistake must not lose the run.
    """
    if not declarations:
        return 0
    run = catalog[str(sim_id)]
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
        except Exception as exc:
            logger.warning("Observation point '%s' could not be sampled: %s", point_id, exc)
            continue
        written += _write_series(catalog, sim_id, point_id, frame)
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
        catalog.write_observation_points(sim_id, resolved)
    logger.info("Sampled %d observation series for sim %s", written, sim_id)
    return written


def _write_series(catalog: Catalog, sim_id: str, point_id: str, frame: pd.DataFrame) -> int:
    """Write one point's per-variable series into the timeseries payload."""
    station = station_id_for(point_id)
    written = 0
    for variable, chunk in frame.groupby("variable", sort=False):
        catalog.write_timeseries_columns(
            sim_id,
            {
                "station_id": station,
                "variable": str(variable),
                "timestep": chunk["timestep"].to_numpy(dtype="int64"),
                "time": pd.DatetimeIndex(chunk["time"]),
                "value": chunk["value"].to_numpy(dtype="float64"),
                "unit": str(chunk["unit"].iloc[0] or ""),
                "qflag": "simulated",
            },
        )
        written += 1
    return written


__all__ = ["STATION_PREFIX", "sample_observation_points", "station_id_for"]
