"""Catalog-wide dataset for model training.

Joins the scalar tables (``simulations``, ``parameters``, ``metrics``,
``runs_environment``) of a cohort with optional Zarr field arrays into one
:class:`xarray.Dataset` indexed by ``sim_id``. The cohort is a
:class:`~hydromodpy.results.run.group.RunSet`: its parameter pivot and its
lazy field stack are the ones of the set, so the fields stay dask-backed and
the loader scales to a thousand runs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd

from hydromodpy.results.catalog.constants import SIMULATIONS_FROM
from hydromodpy.results.metric_rule import HEADLINE_WINDOW
from hydromodpy.results.run.group import stack_fields

if TYPE_CHECKING:
    import xarray as xr

    from hydromodpy.results.catalog.facade import Catalog


_SIM_META_SELECT = (
    "s.sim_id, s.name, s.project, s.site, s.case_id, s.rel_dir, s.label, "
    "sv.code AS solver, sv.category AS solver_category, "
    "fr.code AS flow_regime, st.code AS status, "
    "s.n_cells, s.n_layers, s.n_timesteps, "
    "s.solution_key, s.request_id, s.scientific_objective, s.nse, s.score_station, "
    "s.score_variable, "
    "s.created_at, s.duration_s"
)

_ENV_META_COLUMNS: tuple[str, ...] = (
    "python_version",
    "hydromodpy_version",
    "platform",
    "hostname",
    "git_commit",
    "project_git_commit",
    "solver_name",
    "solver_binary_sha256",
    "solver_version_text",
    "conda_env_hash",
    "rng_seed",
)


def load_dataset(
    catalog: Catalog,
    filters: dict[str, Any] | None = None,
    *,
    fields: list[str] | None = None,
    include_params: bool = True,
    include_metrics: bool = True,
    include_env: bool = True,
) -> xr.Dataset:
    """Return one ``xr.Dataset`` of the runs that ``catalog.find(**filters)`` matches.

    ``fields`` names the Zarr fields to attach lazily, ``None`` gives a
    scalar-only dataset. The ``include_*`` flags merge the parameters
    (``param_<name>``), the headline metrics (``metric_<name>``) and the
    environment (``env_<column>``) as variables on ``sim_id``.
    """
    import xarray as xr

    group = catalog.find(**(filters or {}))
    sim_ids = group.sim_ids
    if not sim_ids:
        return xr.Dataset(coords={"sim_id": []})

    placeholders = ", ".join(["?"] * len(sim_ids))
    frame = catalog.backend.query(
        f"SELECT {_SIM_META_SELECT} {SIMULATIONS_FROM} WHERE s.sim_id IN ({placeholders})",
        sim_ids,
    )
    extras: list[pd.DataFrame] = []
    if include_params:
        extras.append(_prefixed(group.parameters, "param_"))
    if include_metrics:
        extras.append(_metrics_at_rule_station(catalog, sim_ids, placeholders))
    if include_env:
        env = catalog.backend.query(
            f"SELECT sim_id, {', '.join(_ENV_META_COLUMNS)} "
            f"FROM runs_environment WHERE sim_id IN ({placeholders})",
            sim_ids,
        )
        extras.append(_prefixed(env, "env_"))
    frame["sim_id"] = frame["sim_id"].astype(str)
    for extra in extras:
        if not extra.empty:
            extra["sim_id"] = extra["sim_id"].astype(str)
            frame = frame.merge(extra, on="sim_id", how="left")
    dataset = frame.set_index("sim_id").to_xarray()

    if fields:
        field_ds = xr.Dataset(stack_fields(catalog, sim_ids, fields, dim="sim_id"))
        if field_ds.data_vars:
            dataset = xr.merge([dataset, field_ds], compat="override", join="outer")
    return dataset


def _prefixed(frame: pd.DataFrame, prefix: str) -> pd.DataFrame:
    """``frame`` with every column but ``sim_id`` renamed ``<prefix><name>``."""
    if frame.empty:
        return frame
    return frame.rename(columns={c: f"{prefix}{c}" for c in frame.columns if c != "sim_id"})


def _metrics_at_rule_station(
    catalog: Catalog, sim_ids: list[str], placeholders: str
) -> pd.DataFrame:
    """One ``metric_<name>`` column per metric, read at the station of the run's rule."""
    frame = catalog.backend.query(
        f"SELECT m.sim_id, m.metric, m.value "
        f"FROM metrics m JOIN simulations s ON s.sim_id = m.sim_id "
        f"WHERE m.sim_id IN ({placeholders}) "
        f"AND m.window_name = ? "
        f"AND m.station_id IS NOT DISTINCT FROM s.score_station "
        f"AND m.variable IS NOT DISTINCT FROM s.score_variable",
        [*sim_ids, HEADLINE_WINDOW],
    )
    if frame.empty:
        return frame
    wide = frame.pivot_table(
        index="sim_id", columns="metric", values="value", aggfunc="first"
    ).reset_index()
    return _prefixed(wide, "metric_")


__all__ = ["load_dataset"]
