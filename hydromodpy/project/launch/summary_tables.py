"""Build the tables ``by_case`` and ``by_site`` of a campaign summary.

``by_case`` holds one row per case of the plan (or per case found on disk
without a plan): the latest run and session of the case, its scores, the
metrics, parameters and dotted columns of ``[sites.summary]``. ``by_site``
holds one row per site with its best case, or in ``best_reason`` why it has
none, and the sites as :class:`~hydromodpy.core.site.row.SiteRow` lines.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Final

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.result_dirs import parse_rel_dir
from hydromodpy.core.toml_io.paths import lookup
from hydromodpy.results.catalog.constants import UnrankedMetricError, metric_sense
from hydromodpy.results.catalog.registration import split_stem_version
from hydromodpy.results.run.ranking import (
    clean_cell,
    first_present,
    is_finite,
    rank_rows,
    unscored_reason,
)
from hydromodpy.results.run.sealed_facts import (
    SealedRunFacts,
    overrides_text,
    place_of,
    read_run_facts,
)
from hydromodpy.results.validity_rules import CALIBRATED_LABELS

if TYPE_CHECKING:
    from pathlib import Path

    import pandas as pd

    from hydromodpy.config.sites import SitesSummaryConfig
    from hydromodpy.results.manifest import Manifest

logger = get_logger(__name__)

PLANNED_STATUS: Final[str] = "planned"
"""Status of a case of the plan that has no directory yet."""

DATE_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "label_date",
        "score_window_start",
        "score_window_end",
        "calibrated_by_window_start",
        "calibrated_by_window_end",
    }
)
"""Columns that hold a day, written as ``YYYY-MM-DD``."""

CASE_COLUMNS: Final[tuple[str, ...]] = (
    "case_id",
    "site",
    "recipe",
    "kind",
    "status",
    "label",
    "label_date",
    "rule_version",
    "rel_dir",
    "version",
    "attempt",
    "sim_id",
    "session_rel_dir",
    "session_status",
    "solver",
    "mesh_engine",
    "config_hash",
    "hydromodpy_version",
    "started_at",
    "ended_at",
    "duration_s",
    "flow_solve_time_s",
    "nse",
    "score_window_start",
    "score_window_end",
    "n_samples",
    "score_station",
    "score_variable",
    "metric_rule_version",
    "calibrated_by_metric",
    "calibrated_by_cost",
    "calibrated_by_window_start",
    "calibrated_by_window_end",
    "budget_pct",
    "converged",
    "overrides",
    "error_type",
    "error_message",
)
"""Fixed columns of ``by_case``; metrics, parameters and dotted columns follow."""

_FROM_INDEX: Final[tuple[str, ...]] = (
    "label",
    "label_date",
    "rule_version",
    "attempt",
    "sim_id",
    "solver",
    "mesh_engine",
    "config_hash",
    "hydromodpy_version",
    "started_at",
    "ended_at",
    "duration_s",
    "nse",
    "score_window_start",
    "score_window_end",
    "n_samples",
    "score_station",
    "score_variable",
    "metric_rule_version",
    "calibrated_by_metric",
    "calibrated_by_cost",
    "calibrated_by_window_start",
    "calibrated_by_window_end",
    "budget_pct",
    "converged",
    "error_type",
    "error_message",
)
"""Columns of ``by_case`` copied from the ``v_cases`` row of the case."""

_FROM_SESSION: Final[tuple[str, ...]] = ("started_at", "ended_at")
"""Columns of a calibration row read from its session, not from the promoted run."""

FLOW_SOLVE_METRIC: Final[str] = "flow_solve_time_seconds"
"""Metric of the seal holding the wall time of the flow solve."""

SITE_HEAD_COLUMNS: Final[tuple[str, ...]] = (
    "site",
    "site_label",
    "gauge",
    "uri",
    "n_cases",
    "n_completed",
    "best_case",
    "best_reason",
    "recipe",
    "label",
    "rel_dir",
    "sim_id",
)
SITE_SCORE_COLUMNS: Final[tuple[str, ...]] = (
    "score_window_start",
    "score_window_end",
    "n_samples",
    "score_station",
    "score_variable",
    "metric_rule_version",
    "calibrated_by_metric",
    "calibrated_by_cost",
    "calibrated_by_window_start",
    "calibrated_by_window_end",
)
SITE_PLACE_COLUMNS: Final[tuple[str, ...]] = (
    "area_km2",
    "dem_resolution_m",
    "x_outlet",
    "y_outlet",
    "crs",
    "snapped_x",
    "snapped_y",
)
"""Columns of ``by_site``: who, its best case, its scores, the parameters, where."""


class SummaryError(ConfigError):
    """``[sites.summary]`` or ``[[sites.export]]`` asks for something the collect cannot give."""


def _version_of(rel_dir: str) -> int:
    return split_stem_version(parse_rel_dir(rel_dir).name)[1] or 1


def facts_of_runs(root: Path, cases: pd.DataFrame) -> dict[str, SealedRunFacts]:
    """Return the facts of every sealed run directory the index lists, by ``rel_dir``."""
    facts: dict[str, SealedRunFacts] = {}
    for record in cases.to_dict("records"):
        if record.get("kind") != "run" or record.get("status") != "completed":
            continue
        found = read_run_facts(root / str(record["rel_dir"]))
        if found is not None:
            facts[str(record["rel_dir"])] = found
    return facts


def _latest(cases: pd.DataFrame, kind: str) -> dict[str, dict[str, Any]]:
    """Return the highest version of each case of ``kind``, by ``case_id``."""
    latest: dict[str, dict[str, Any]] = {}
    for record in cases.to_dict("records"):
        if record.get("kind") != kind:
            continue
        record = dict(record)
        record["version"] = _version_of(str(record["rel_dir"]))
        held = latest.get(record["case_id"])
        if held is None or record["version"] > held["version"]:
            latest[record["case_id"]] = record
    return latest


def _extra_columns(summary: SitesSummaryConfig) -> tuple[list[str], list[str], list[str]]:
    """Return the metric, parameter and dotted columns of the summary, refused when they collide."""
    metrics = [name for name in dict.fromkeys(summary.metrics) if name != "nse"]
    for name in summary.metrics:
        try:
            metric_sense(name)
        except UnrankedMetricError as exc:
            raise SummaryError(f"[sites.summary] metrics: {exc}") from exc
    parameters = list(dict.fromkeys(summary.parameters))
    columns = list(dict.fromkeys(summary.columns))
    taken = set(CASE_COLUMNS) | set(SITE_HEAD_COLUMNS) | set(SITE_PLACE_COLUMNS)
    seen: set[str] = set()
    for name in [*metrics, *parameters, *columns]:
        if name in taken or name in seen:
            raise SummaryError(
                f"[sites.summary]: {name!r} names a column twice or a fixed column of the "
                "summary tables; rename the parameter or drop the entry."
            )
        seen.add(name)
    return metrics, parameters, columns


def parameter_names(summary: SitesSummaryConfig, facts: Mapping[str, SealedRunFacts]) -> list[str]:
    """Return the parameter columns: those of ``[sites.summary]``, then every other one sealed.

    A global parameter whose name is already a column of the summary is left
    out with a warning; ``columns = ["parameters.<name>"]`` reads it.
    """
    metrics, names, columns = _extra_columns(summary)
    taken = (
        set(CASE_COLUMNS)
        | set(SITE_HEAD_COLUMNS)
        | set(SITE_SCORE_COLUMNS)
        | set(SITE_PLACE_COLUMNS)
        | {*metrics, *columns}
    )
    clashes: set[str] = set()
    for fact in facts.values():
        for name in fact.parameters:
            if name in names:
                continue
            if name in taken:
                clashes.add(name)
                continue
            names.append(name)
    for name in sorted(clashes):
        logger.warning(
            "[sites.summary]: parameter %r is named like a column of the summary and is left "
            'out; add columns = ["parameters.%s"] to read it.',
            name,
            name,
        )
    return names


def by_case_table(
    cases: pd.DataFrame,
    planned: Sequence[Any],
    facts: Mapping[str, SealedRunFacts],
    summary: SitesSummaryConfig,
    *,
    parameters: Sequence[str],
    recipe_sets: Mapping[str, Mapping[str, Any]],
) -> pd.DataFrame:
    """Return one row per case: the plan joined to the latest run and session of each case.

    ``overrides`` is the ``set`` of the recipe of the case, with what
    ``--set`` changed in the run on top.
    """
    import pandas as pd

    metrics, listed, columns = _extra_columns(summary)
    runs = _latest(cases, "run")
    sessions = _latest(cases, "session")
    plan = {case.case_id: case for case in planned}
    order = list(plan) + sorted((set(runs) | set(sessions)) - set(plan))
    missing: dict[str, KeyError] = {}
    found: set[str] = set()
    rows: list[dict[str, Any]] = []
    for case_id in order:
        run, session, case = runs.get(case_id), sessions.get(case_id), plan.get(case_id)
        main = run or session or {}
        row: dict[str, Any] = dict.fromkeys(CASE_COLUMNS)
        row["case_id"] = case_id
        row["site"] = first_present(getattr(case, "site", None), main.get("site"))
        row["recipe"] = first_present(getattr(case, "recipe", None), main.get("recipe"))
        row["kind"] = "calibration" if session is not None else "run"
        row["status"] = main.get("status") or PLANNED_STATUS
        for column in _FROM_INDEX:
            value = clean_cell(main.get(column))
            row[column] = _as_date(value) if column in DATE_COLUMNS else value
        if run is not None:
            row["rel_dir"], row["version"] = run["rel_dir"], run["version"]
        if session is not None:
            row["session_rel_dir"] = session["rel_dir"]
            row["session_status"] = session.get("status")
            # A calibration took the time of its session, not of the promoted run.
            for column in _FROM_SESSION:
                row[column] = clean_cell(session.get(column))
            row["duration_s"] = _seconds_between(row["started_at"], row["ended_at"])
        fact = facts.get(str(row["rel_dir"])) if row["rel_dir"] else None
        if fact is not None:
            row["mesh_engine"] = first_present(
                fact.manifest.geometry.mesh_engine, row["mesh_engine"]
            )
            row["flow_solve_time_s"] = _flow_solve_time(fact.manifest)
        for name in metrics:
            row[name] = None if fact is None else fact.metrics.get(name)
        for name in parameters:
            row[name] = None if fact is None else fact.parameters.get(name)
            if fact is not None and name in fact.parameters:
                found.add(name)
        for path in columns:
            row[path] = None
            if fact is None:
                continue
            try:
                row[path] = _column_value(lookup(fact.document, path))
                found.add(path)
            except KeyError as exc:
                missing.setdefault(path, exc)
        applied = dict(recipe_sets.get(str(row["recipe"]), {}))
        if fact is not None:
            applied.update(fact.overrides)
        row["overrides"] = overrides_text(applied) or None
        rows.append(row)
    sealed = bool(facts)
    for path, exc in missing.items():
        if path not in found and sealed:
            raise SummaryError(f"[sites.summary] columns: no manifest has {path!r}: {exc}")
    for name in listed:
        if name not in found and sealed:
            logger.warning("[sites.summary] parameters: no sealed run has a parameter %r", name)
    return pd.DataFrame(rows, columns=[*CASE_COLUMNS, *metrics, *parameters, *columns])


def _seconds_between(start: Any, end: Any) -> float | None:
    """Return the seconds from *start* to *end*, ``None`` when one is missing."""
    import pandas as pd

    if start is None or end is None:
        return None
    return max(0.0, (pd.Timestamp(end) - pd.Timestamp(start)).total_seconds())


def _flow_solve_time(manifest: Manifest) -> float | None:
    """Return the wall time of the flow solve the seal recorded, in seconds."""
    return next(
        (row.value for row in manifest.metrics if row.metric == FLOW_SOLVE_METRIC),
        None,
    )


def _as_date(value: Any) -> date | None:
    """Return a day of the index (a DATE read back as an instant) as a date."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _column_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, default=str)
    return value


def by_site_table(
    by_case: pd.DataFrame,
    facts: Mapping[str, SealedRunFacts],
    summary: SitesSummaryConfig,
    *,
    parameters: Sequence[str],
    mixed_windows: bool,
) -> tuple[pd.DataFrame, list[Any]]:
    """Return one row per site with its best case, and the sites as site rows.

    A site without a best case says why in ``best_reason``.
    """
    import pandas as pd

    from hydromodpy.core.site.row import SiteRow

    metrics, _, columns = _extra_columns(summary)
    metric_columns = ["nse", *metrics]
    ranked_by = summary.rank_by
    candidates = by_case[by_case["status"] == "completed"]
    if summary.best == "calibrated":
        candidates = candidates[candidates["label"].isin(CALIBRATED_LABELS)]
    best = rank_rows(candidates, ranked_by, by="site", mixed_windows=mixed_windows)
    best_by_site = {record["site"]: record for record in best.to_dict("records")}
    sites = sorted({str(site) for site in by_case["site"] if clean_cell(site) is not None})
    rows: list[dict[str, Any]] = []
    site_rows: list[Any] = []
    for site in sites:
        of_site = by_case[by_case["site"] == site]
        chosen = best_by_site.get(site)
        fact = facts.get(str(chosen["rel_dir"])) if chosen else _any_sited_fact(of_site, facts)
        block = fact.manifest.site if fact is not None else None
        row: dict[str, Any] = dict.fromkeys(
            [*SITE_HEAD_COLUMNS, *metric_columns, *SITE_SCORE_COLUMNS, *parameters, *columns]
            + list(SITE_PLACE_COLUMNS)
        )
        row["site"] = site
        row["n_cases"] = len(of_site)
        row["n_completed"] = int((of_site["status"] == "completed").sum())
        if chosen is not None:
            row["best_case"] = chosen["case_id"]
            for column in ("recipe", "label", "rel_dir", "sim_id"):
                row[column] = chosen[column]
            for column in [*metric_columns, *SITE_SCORE_COLUMNS, *parameters, *columns]:
                row[column] = clean_cell(chosen.get(column))
        else:
            row["best_reason"] = _no_best_reason(site, of_site, ranked_by, summary.best)
        if block is not None:
            row["site_label"], row["gauge"], row["uri"] = block.label, block.gauge, block.uri
            row["x_outlet"], row["y_outlet"], row["crs"] = block.x_outlet, block.y_outlet, block.crs
            row.update(place_of(fact.manifest))
            site_rows.append(
                SiteRow(
                    site=site,
                    label=block.label,
                    gauge=block.gauge,
                    uri=block.uri,
                    x_outlet=block.x_outlet,
                    y_outlet=block.y_outlet,
                    crs=block.crs,
                )
            )
        else:
            site_rows.append(SiteRow(site=site))
        rows.append(row)
    ordered = [
        *SITE_HEAD_COLUMNS,
        *metric_columns,
        *SITE_SCORE_COLUMNS,
        *parameters,
        *columns,
        *SITE_PLACE_COLUMNS,
    ]
    return pd.DataFrame(rows, columns=ordered), site_rows


def _no_best_reason(site: str, of_site: pd.DataFrame, metric: str, best: str) -> str:
    """Say why a site has no best case: nothing completed, nothing scored, nothing calibrated."""
    completed = of_site[of_site["status"] == "completed"]
    if completed.empty:
        return f"no completed case of {site}"
    if metric not in completed.columns or not any(is_finite(v) for v in completed[metric]):
        return unscored_reason(site, completed, metric)
    if best == "calibrated":
        return f'no calibrated case of {site} is scored; best = "any" ranks every case'
    return f"no case of {site} has a {metric} comparable with the others"


def _any_sited_fact(
    of_site: pd.DataFrame, facts: Mapping[str, SealedRunFacts]
) -> SealedRunFacts | None:
    """Return the facts of the newest sealed run of a site that declares it, ``None`` without one."""
    for rel_dir in reversed([str(value) for value in of_site["rel_dir"] if clean_cell(value)]):
        fact = facts.get(rel_dir)
        if fact is not None and fact.manifest.site is not None:
            return fact
    return None


__all__ = [
    "CASE_COLUMNS",
    "DATE_COLUMNS",
    "FLOW_SOLVE_METRIC",
    "PLANNED_STATUS",
    "SITE_HEAD_COLUMNS",
    "SITE_PLACE_COLUMNS",
    "SITE_SCORE_COLUMNS",
    "SummaryError",
    "by_case_table",
    "by_site_table",
    "facts_of_runs",
    "parameter_names",
]
