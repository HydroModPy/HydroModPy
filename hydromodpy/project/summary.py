"""Collect a project of N cases into ``summary/``: tables, figures, exports, a page.

Why
---
A project of 100 catchments, two recipes and one calibration per site is read
through one directory. ``summary/by_site.csv`` is the table "best K and NSE
by catchment", ``summary/by_site.gpkg`` its map, ``summary/README.md`` says
what was collected, when, under which versions, and how many of the planned
cases completed. Everything under ``summary/`` is derived: ``hmp project
collect`` writes it again from the index and the run directories.

What ``summary/`` holds
-----------------------
``by_case.parquet`` and ``by_case.csv``: one row per case of the plan (or per
case found on disk without a plan): status, label, checks, score and window,
the objective of its session beside it, the metrics of ``[sites.summary]``,
every global parameter of the seal under its own name (``K``, ``Sy``), the
``overrides`` of the case (the ``set`` of its recipe, then what ``--set``
changed), the dotted ``columns`` read from the manifest.
``by_site.parquet``, ``by_site.csv``, ``by_site.gpkg``: one row per site, its
best case, or in ``best_reason`` why it has none. ``catalog.csv`` (``write_sites``): the sites as
:class:`~hydromodpy.core.site.row.SiteRow` lines, replayable as a site table.
``figures/`` and ``exports/``, each with its ledger ``index.json``, drawn in a
staging folder and moved into place once complete; ``report/index.html``;
``README.md``; ``ro-crate-metadata.json``. ``summary/report/compare/`` belongs
to ``hmp report compare`` and is kept.

Rules
-----
- The best case of a site ranks ``[sites.summary] rank_by`` (default
  ``nse``) by its direction; ``best = "calibrated"`` keeps the calibrated
  cases only, the evaluated ones included (scored out of their calibration
  window). A site without a best case says why in ``best_reason``.
- ``[sites.summary] parameters`` orders the parameter columns and warns when
  no sealed run carries one; every other global parameter follows. A
  parameter whose name is a column of the summary is left out with a warning:
  read it through ``columns = ["parameters.<name>"]``.
- Scores computed under different rules (variable, window, rule version, or
  station inside one site) are not ranked together unless ``mixed_windows``
  is true.
- A dotted path of ``columns`` reads ``manifest.json`` of the run, in which
  ``metrics`` is a table metric -> value at the station of the headline score
  and ``parameters`` a table name -> value of the global zone.
- A sealed run or session whose seal does not read under this version stops
  the collect, by name: its row would otherwise be missing without a word.
- A cohort figure that cannot be drawn is named in :attr:`SummaryPaths.skipped`
  and on the page; the figures of the previous collect are only replaced once
  the new ones are drawn.
"""

from __future__ import annotations

import html
import json
import math
import os
import shutil
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from pydantic import ValidationError

from hydromodpy.core.exceptions import ConfigError, DataError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import (
    PROJECT_MARKER_FILENAME,
    parse_rel_dir,
    summary_dir_for,
)
from hydromodpy.core.toml_io.paths import lookup
from hydromodpy.core.version import __version__ as HYDROMODPY_VERSION
from hydromodpy.results.catalog.constants import GLOBAL_ZONE, UnrankedMetricError, metric_sense
from hydromodpy.results.catalog.registration import split_stem_version
from hydromodpy.results.publication import redact
from hydromodpy.results.run.sealed import INDEX_RULE, check_one_rule, rule_cell
from hydromodpy.results.storage.contract import (
    PARQUET_FILE_SUFFIX,
    REPORT_INDEX_FILENAME,
    RUN_EXPORTS_DIRNAME,
    RUN_FIGURES_DIRNAME,
    RUN_REPORT_DIRNAME,
    TABLES_DIRNAME,
)
from hydromodpy.results.validity_rules import CALIBRATED_LABELS
from hydromodpy.schema.media_types import (
    GEOPACKAGE_MEDIA_TYPE,
    JSON_MEDIA_TYPE,
    OCTET_STREAM_MEDIA_TYPE,
    PARQUET_MEDIA_TYPE,
)

if TYPE_CHECKING:
    import pandas as pd

    from hydromodpy.config.publication_config import PublicationConfig
    from hydromodpy.config.sites.models import SitesExportRequest, SitesSummaryConfig
    from hydromodpy.results.manifest import Manifest

logger = get_logger(__name__)

BY_CASE_STEM: Final[str] = "by_case"
BY_SITE_STEM: Final[str] = "by_site"
CATALOG_CSV_FILENAME: Final[str] = "catalog.csv"
RO_CRATE_FILENAME: Final[str] = "ro-crate-metadata.json"
BEST_EXPORTS_DIRNAME: Final[str] = "best"
"""Folder of ``summary/exports/`` holding the series of the best case of each site."""

COHORT_FIGURE_MODULE_PREFIX: Final[str] = "hydromodpy.display.figures.cohort_"
"""A figure of ``[sites.summary] figures`` draws the cohort table; it lives in such a module."""

COLLECT_PRODUCER: Final[str] = "project.summary"
"""Producer the ledgers of ``summary/`` name for an export."""

PLANNED_STATUS: Final[str] = "planned"
"""Status of a case of the plan that has no directory yet."""

DATE_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "label_date",
        "nse_window_start",
        "nse_window_end",
        "objective_window_start",
        "objective_window_end",
    }
)
"""Columns that hold a day, written as ``YYYY-MM-DD``."""

INTEGER_COLUMNS: Final[frozenset[str]] = frozenset(
    {"version", "attempt", "nse_n", "n_cases", "n_completed"}
)
"""Columns that hold a count, kept integer when a cell is missing."""

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
    "nse_window_start",
    "nse_window_end",
    "nse_n",
    "nse_station",
    "nse_variable",
    "metric_rule_version",
    "objective_name",
    "objective_value",
    "objective_window_start",
    "objective_window_end",
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
    "nse_window_start",
    "nse_window_end",
    "nse_n",
    "nse_station",
    "nse_variable",
    "metric_rule_version",
    "objective_name",
    "objective_value",
    "objective_window_start",
    "objective_window_end",
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
    "nse_window_start",
    "nse_window_end",
    "nse_n",
    "nse_station",
    "nse_variable",
    "metric_rule_version",
    "objective_name",
    "objective_value",
    "objective_window_start",
    "objective_window_end",
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

_MEDIA_TYPES: Final[dict[str, str]] = {
    ".gpkg": GEOPACKAGE_MEDIA_TYPE,
    ".json": JSON_MEDIA_TYPE,
    ".parquet": PARQUET_MEDIA_TYPE,
}
"""Suffixes of ``summary/`` whose type the shared table names; any other file is an octet
stream, as in the views of a run."""

_TIMESERIES_FILE: Final[str] = f"timeseries{PARQUET_FILE_SUFFIX}"
"""The series payload of a run, under ``tables.parquet/``."""

_TABLE_FORMATS: Final[dict[str, tuple[str, ...]]] = {
    BY_CASE_STEM: ("csv", "parquet"),
    BY_SITE_STEM: ("csv", "parquet", "gpkg"),
    "catalog": ("csv",),
}
"""Formats a ``[[sites.export]] table`` may ask for, per table."""

_FORMAT_SUFFIX: Final[dict[str, str]] = {"csv": ".csv", "parquet": ".parquet", "gpkg": ".gpkg"}


class SummaryError(ConfigError):
    """``[sites.summary]`` or ``[[sites.export]]`` asks for something the collect cannot give."""


class UnreadableManifestError(DataError):
    """A sealed run or session whose seal does not read under this version."""


@dataclass(frozen=True, slots=True)
class SummaryPaths:
    """What one collect wrote under ``summary/``."""

    by_case: Path
    by_site: Path
    catalog: Path | None
    figures: Path
    exports: Path
    report: Path
    readme: Path
    rocrate: Path
    skipped: tuple[str, ...] = ()
    """Cohort figures not drawn, each as ``<figure> of <variable>: <reason>``."""


@dataclass(frozen=True, slots=True)
class RunFacts:
    """What the seal of one run says, in the shapes the summary reads."""

    manifest: Manifest
    metrics: dict[str, float | None]
    parameters: dict[str, float | None]
    document: dict[str, Any]

    @property
    def overrides(self) -> dict[str, Any]:
        """Dotted paths ``--set`` or ``--overlay`` changed, as the seal recorded them."""
        return dict(self.manifest.lineage.overrides)


def read_run_facts(run_dir: str | Path) -> RunFacts | None:
    """Return the facts of a sealed run directory, ``None`` when it carries no manifest.

    Raises
    ------
    UnreadableManifestError
        When ``manifest.json`` does not read under the current schema.
    """
    from hydromodpy.results.export.run_identity import read_sealed_manifest

    try:
        manifest = read_sealed_manifest(run_dir)
    except ValidationError as exc:
        raise UnreadableManifestError(
            f"{run_dir}: manifest.json does not read under HydroModPy {HYDROMODPY_VERSION} "
            f"({exc.error_count()} error(s), first: {exc.errors()[0]['msg']}). Read the run "
            "with the version that sealed it, or move it to the trash with hmp catalog delete."
        ) from exc
    if manifest is None:
        return None
    metrics = _headline_metrics(manifest)
    parameters = {row.name: row.value for row in manifest.parameters if row.zone == GLOBAL_ZONE}
    document = manifest.model_dump(mode="json")
    document["metrics"] = dict(metrics)
    document["parameters"] = dict(parameters)
    return RunFacts(manifest=manifest, metrics=metrics, parameters=parameters, document=document)


def _headline_metrics(manifest: Manifest) -> dict[str, float | None]:
    """Return metric -> value at the station and variable of the headline score."""
    score = manifest.score
    rows = list(manifest.metrics)
    if score is not None:
        rows = [
            row for row in rows if row.station == score.station and row.variable == score.variable
        ]
    elif len({(row.station, row.variable) for row in rows}) > 1:
        rows = []
    values: dict[str, float | None] = {row.metric: row.value for row in rows}
    if score is not None and score.metric not in values:
        values[score.metric] = score.value
    return values


def overrides_text(overrides: Mapping[str, Any]) -> str:
    """Return ``path=value`` pairs joined by ``, ``, sorted by path; empty without any."""
    return ", ".join(f"{path}={_value_text(overrides[path])}" for path in sorted(overrides))


def _value_text(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, default=str)
    return str(value)


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


def _finite(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def rank_key(value: float, metric: str) -> float:
    """Return a key under which the smaller is the better value of ``metric``."""
    sense = metric_sense(metric)
    number = float(value)
    if sense == "max":
        return -number
    if sense == "min":
        return number
    if sense == "zero":
        return abs(number)
    return abs(number - 1.0)


def rank_rows(
    frame: pd.DataFrame, metric: str, *, by: str | None = None, mixed_windows: bool = False
) -> pd.DataFrame:
    """Return the rows of ``frame`` with a finite ``metric``, best first.

    Under ``by``, only the best row of each group is kept, groups in name
    order. Ties keep the first row of ``frame``. Rows scored under different rules
    are refused (:func:`~hydromodpy.results.run.sealed.check_one_rule`).
    """
    metric_sense(metric)
    if frame.empty or metric not in frame.columns:
        return frame.iloc[0:0]
    scored = frame[[_finite(value) for value in frame[metric]]].copy()
    if not mixed_windows:
        check_one_rule(
            scored.to_dict("records"),
            metric,
            names=[
                str(record.get("case_id") or record.get("name"))
                for record in scored.to_dict("records")
            ],
            columns=INDEX_RULE,
            groups=None if by is None else list(scored[by]),
            group_name=by or "group",
        )
    scored["_rank"] = [rank_key(value, metric) for value in scored[metric]]
    scored = scored.sort_values("_rank", kind="stable")
    if by is not None:
        scored = scored.drop_duplicates(subset=[by], keep="first").sort_values(by, kind="stable")
    return scored.drop(columns="_rank")


# ---------------------------------------------------------------------------
# The collect
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Settings:
    summary: SitesSummaryConfig
    exports: tuple[SitesExportRequest, ...]
    publication: PublicationConfig
    recipe_sets: Mapping[str, Mapping[str, Any]]
    """The ``set`` of each inline recipe of ``[sites.recipes]``, by recipe name."""


def collect_project(
    project_root: str | Path, *, write_sites: bool = False, mixed_windows: bool = False
) -> SummaryPaths:
    """Write ``summary/`` of a project from its index and its run directories.

    The index is brought up to date first (``index_new_runs``). ``write_sites``
    also writes ``summary/catalog.csv``, the sites as a site table.
    ``mixed_windows`` ranks scores computed under different rules together.

    Raises
    ------
    FileNotFoundError
        Without ``project.toml`` at ``project_root``.
    SummaryError
        For a figure, a column, a parameter name or an export the collect
        cannot give.
    hydromodpy.results.run.sealed.MixedWindowsError
        For scores under different rules, without ``mixed_windows``.
    """
    from hydromodpy.results.catalog import Catalog
    from hydromodpy.results.catalog.indexer import index_new_runs

    root = Path(project_root).expanduser().resolve()
    if not (root / PROJECT_MARKER_FILENAME).is_file():
        raise FileNotFoundError(f"No {PROJECT_MARKER_FILENAME} in {root}: not a project root.")
    settings = _read_settings(root)
    planned = _planned_cases(root)
    _refuse_left_out(index_new_runs(root).skipped)
    with Catalog(root) as catalog:
        cases = catalog.cases
    facts = _facts_of_runs(root, cases)
    parameters = _parameter_names(settings.summary, facts)
    by_case = _relative_paths(
        _by_case(
            cases,
            planned,
            facts,
            settings.summary,
            parameters=parameters,
            recipe_sets=settings.recipe_sets,
        ),
        root,
    )
    by_site, site_rows = _by_site(
        by_case, facts, settings.summary, parameters=parameters, mixed_windows=mixed_windows
    )
    by_site = _relative_paths(by_site, root)
    _figure_requests(settings.summary, by_site.columns)
    _check_exports(settings.exports)
    collected_at = datetime.now(UTC)

    from hydromodpy.data.sites.catalog import write_site_rows

    summary = summary_dir_for(root)
    summary.mkdir(parents=True, exist_ok=True)
    figures_dir = summary / RUN_FIGURES_DIRNAME
    exports_dir = summary / RUN_EXPORTS_DIRNAME
    metadata = {
        "hmp.summary": json.dumps(
            {
                "project": root.name,
                "collected_at": collected_at.isoformat(),
                "hydromodpy_version": HYDROMODPY_VERSION,
            }
        )
    }
    by_case_path = _write_table(by_case, summary / f"{BY_CASE_STEM}{PARQUET_FILE_SUFFIX}", metadata)
    _write_csv(by_case, summary / f"{BY_CASE_STEM}.csv")
    by_site_path = _write_table(by_site, summary / f"{BY_SITE_STEM}{PARQUET_FILE_SUFFIX}", metadata)
    _write_csv(by_site, summary / f"{BY_SITE_STEM}.csv")
    map_frame = _in_one_crs(by_site)
    _write_gpkg(map_frame, summary / f"{BY_SITE_STEM}.gpkg")
    catalog_path = (
        write_site_rows(summary / CATALOG_CSV_FILENAME, site_rows) if write_sites else None
    )

    # Figures and exports are drawn aside and replace the previous ones only
    # once complete: a collect that stops half way leaves the last summary whole.
    staging = Path(tempfile.mkdtemp(prefix=".collect-", dir=summary))
    try:
        new_figures, new_exports = staging / RUN_FIGURES_DIRNAME, staging / RUN_EXPORTS_DIRNAME
        for directory in (new_figures, new_exports):
            directory.mkdir()
            _write_empty_ledger(directory)
        drawn, skipped = _draw_figures(map_frame, settings.summary, new_figures)
        _write_exports(root, summary, settings.exports, by_site, site_rows, new_exports)
        _move_into_place(new_figures, figures_dir)
        _move_into_place(new_exports, exports_dir)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    figures = [figures_dir / path.name for path in drawn]

    n_planned, n_completed = _counts(by_case, planned)
    report = _write_report(
        summary,
        project=root.name,
        collected_at=collected_at,
        n_planned=n_planned,
        n_completed=n_completed,
        by_site=by_site,
        figures=figures,
        skipped=skipped,
    )
    readme = _write_readme(
        summary,
        project=root.name,
        by_case=by_case,
        n_planned=n_planned,
        n_completed=n_completed,
        collected_at=collected_at,
        best=settings.summary.best,
        catalog_written=catalog_path is not None,
    )
    rocrate = _write_rocrate(
        summary,
        project=root.name,
        by_case=by_case,
        publication=settings.publication,
        collected_at=collected_at,
    )
    return SummaryPaths(
        by_case=by_case_path,
        by_site=by_site_path,
        catalog=catalog_path,
        figures=figures_dir,
        exports=exports_dir,
        report=report,
        readme=readme,
        rocrate=rocrate,
        skipped=tuple(skipped),
    )


def _move_into_place(staged: Path, target: Path) -> None:
    """Replace the directory *target* with *staged*."""
    shutil.rmtree(target, ignore_errors=True)
    os.replace(staged, target)


def _refuse_left_out(skipped: Sequence[Any]) -> None:
    """Stop on a directory the index left out: its row would be missing without a word."""
    if not skipped:
        return
    listed = "; ".join(f"{entry.rel_dir}: {entry.reason}" for entry in skipped[:3])
    more = f" and {len(skipped) - 3} more" if len(skipped) > 3 else ""
    raise UnreadableManifestError(
        f"{len(skipped)} sealed directory(ies) do not read under HydroModPy "
        f"{HYDROMODPY_VERSION}: {listed}{more}. Read them with the version that sealed them, "
        "or move them to the trash with hmp catalog delete."
    )


def _counts(by_case: pd.DataFrame, planned: Sequence[Any]) -> tuple[int, int]:
    """Return the planned and completed counts: of the plan when there is one, else of the disk."""
    completed = by_case["status"] == "completed"
    if not planned:
        return len(by_case), int(completed.sum())
    in_plan = by_case["case_id"].isin([case.case_id for case in planned])
    return len(planned), int((completed & in_plan).sum())


def _read_settings(root: Path) -> _Settings:
    """Read ``[sites.summary]``, ``[[sites.export]]`` and ``[publication]`` of ``project.toml``."""
    from hydromodpy.config.publication_config import PublicationConfig
    from hydromodpy.config.sites.expansion import declares_sites
    from hydromodpy.config.sites.models import RecipeSpec, SitesConfig, SitesSummaryConfig
    from hydromodpy.core.toml_io.loader import merge_toml_chain, read_toml_chain

    document = merge_toml_chain(read_toml_chain(root / PROJECT_MARKER_FILENAME))
    summary, exports = SitesSummaryConfig(), ()
    recipe_sets: dict[str, Mapping[str, Any]] = {}
    if declares_sites(document):
        try:
            sites = SitesConfig.model_validate(document["sites"])
        except ValidationError as exc:
            raise SummaryError(f"{PROJECT_MARKER_FILENAME}: [sites] {exc}") from exc
        summary, exports = sites.summary, tuple(sites.export)
        recipe_sets = {
            name: dict(decl.set)
            for name, decl in sites.recipes.items()
            if isinstance(decl, RecipeSpec) and decl.set
        }
    try:
        publication = PublicationConfig.model_validate(document.get("publication") or {})
    except ValidationError as exc:
        raise SummaryError(f"{PROJECT_MARKER_FILENAME}: [publication] {exc}") from exc
    return _Settings(
        summary=summary, exports=exports, publication=publication, recipe_sets=recipe_sets
    )


def _planned_cases(root: Path) -> tuple[Any, ...]:
    """Return the cases of the current plan, none without a plan."""
    from hydromodpy.results.plan_store import current_plan_hash, read_plan

    if current_plan_hash(root) is None:
        return ()
    return read_plan(root).cases


def _version_of(rel_dir: str) -> int:
    return split_stem_version(parse_rel_dir(rel_dir).name)[1] or 1


def _facts_of_runs(root: Path, cases: pd.DataFrame) -> dict[str, RunFacts]:
    """Return the facts of every sealed run directory the index lists, by ``rel_dir``."""
    facts: dict[str, RunFacts] = {}
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


def _parameter_names(summary: SitesSummaryConfig, facts: Mapping[str, RunFacts]) -> list[str]:
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


def _by_case(
    cases: pd.DataFrame,
    planned: Sequence[Any],
    facts: Mapping[str, RunFacts],
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
        row["site"] = _first(getattr(case, "site", None), main.get("site"))
        row["recipe"] = _first(getattr(case, "recipe", None), main.get("recipe"))
        row["kind"] = "calibration" if session is not None else "run"
        row["status"] = main.get("status") or PLANNED_STATUS
        for column in _FROM_INDEX:
            value = _clean(main.get(column))
            row[column] = _as_date(value) if column in DATE_COLUMNS else value
        if run is not None:
            row["rel_dir"], row["version"] = run["rel_dir"], run["version"]
        if session is not None:
            row["session_rel_dir"] = session["rel_dir"]
            row["session_status"] = session.get("status")
            # A calibration took the time of its session, not of the promoted run.
            for column in _FROM_SESSION:
                row[column] = _clean(session.get(column))
            row["duration_s"] = _seconds_between(row["started_at"], row["ended_at"])
        fact = facts.get(str(row["rel_dir"])) if row["rel_dir"] else None
        if fact is not None:
            row["mesh_engine"] = _first(fact.manifest.geometry.mesh_engine, row["mesh_engine"])
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


def _first(*values: Any) -> Any:
    return next((value for value in values if _clean(value) is not None), None)


def _clean(value: Any) -> Any:
    """Return ``None`` for a missing cell (NaN, NaT, NA), the value otherwise."""
    if value is None:
        return None
    try:
        import pandas as pd

        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        return value
    return value


def _column_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, default=str)
    return value


def _by_site(
    by_case: pd.DataFrame,
    facts: Mapping[str, RunFacts],
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
    sites = sorted({str(site) for site in by_case["site"] if _clean(site) is not None})
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
                row[column] = _clean(chosen.get(column))
        else:
            row["best_reason"] = _no_best_reason(site, of_site, ranked_by, summary.best)
        if block is not None:
            row["site_label"], row["gauge"], row["uri"] = block.label, block.gauge, block.uri
            row["x_outlet"], row["y_outlet"], row["crs"] = block.x_outlet, block.y_outlet, block.crs
            row.update(_place_of(fact.manifest))
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
    if metric not in completed.columns or not any(_finite(v) for v in completed[metric]):
        return unscored_reason(site, completed, metric)
    if best == "calibrated":
        return f'no calibrated case of {site} is scored; best = "any" ranks every case'
    return f"no case of {site} has a {metric} comparable with the others"


def unscored_reason(name: str, frame: pd.DataFrame, metric: str) -> str:
    """Say why no sealed run of *name* in *frame* has a finite *metric*.

    A run without a score window carries no score at all: that is the reason
    named first. *frame* holds the ``nse_window_start`` column of the index.
    """
    windows = frame["nse_window_start"] if "nse_window_start" in frame.columns else ()
    if not any(_clean(value) is not None for value in windows):
        return f"no sealed run of {name} is scored: declare [metrics] window"
    return f"no sealed run of {name} has a {metric}"


def names_text(names: Sequence[str], shown: int = 5) -> str:
    """Return the first *shown* names of a list, then how many more."""
    more = f" and {len(names) - shown} more" if len(names) > shown else ""
    return ", ".join(names[:shown]) + more


def _any_sited_fact(of_site: pd.DataFrame, facts: Mapping[str, RunFacts]) -> RunFacts | None:
    """Return the facts of the newest sealed run of a site that declares it, ``None`` without one."""
    for rel_dir in reversed([str(value) for value in of_site["rel_dir"] if _clean(value)]):
        fact = facts.get(rel_dir)
        if fact is not None and fact.manifest.site is not None:
            return fact
    return None


_CATCHMENT_AREA_KEYS: Final[tuple[str, ...]] = ("catch_area", "catchment_area_km2")
"""Keys of ``geometry.catchment`` holding the delineated area, km2."""


def _place_of(manifest: Manifest) -> dict[str, float | None]:
    """Return the area, the DEM cell and the snapped outlet of a run.

    The site block of the seal first, then the catchment metadata of its
    geometry (``catch_area``, ``dem_res``, ``x_outlet_snapped``), which the
    delineation writes.
    """
    site, catchment = manifest.site, manifest.geometry.catchment
    snapped = site.snapped_outlet if site is not None else None
    if snapped is None:
        x, y = (
            _number(catchment.get("x_outlet_snapped")),
            _number(catchment.get("y_outlet_snapped")),
        )
        snapped = (x, y) if x is not None and y is not None else None
    return {
        "area_km2": _first(
            site.area_km2 if site is not None else None,
            *(_number(catchment.get(key)) for key in _CATCHMENT_AREA_KEYS),
        ),
        "dem_resolution_m": _first(
            site.dem_resolution_m if site is not None else None,
            _number(catchment.get("dem_res")),
        ),
        "snapped_x": None if snapped is None else snapped[0],
        "snapped_y": None if snapped is None else snapped[1],
    }


def _number(value: Any) -> float | None:
    """Return a metadata value as a finite float, ``None`` when it is not one."""
    return float(value) if _finite(value) else None


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------


def _write_table(frame: pd.DataFrame, target: Path, metadata: Mapping[str, str]) -> Path:
    import pyarrow as pa

    from hydromodpy.results.storage.parquet_io import write_table_atomic

    table = pa.Table.from_pandas(_portable(frame), preserve_index=False)
    return write_table_atomic(table, target, kv_metadata=metadata)


def _relative_paths(frame: pd.DataFrame, root: Path) -> pd.DataFrame:
    """Return the frame with every absolute path of a text cell written from the project root.

    A path outside the project becomes ``<absolute path>``. The summary is
    published as it is, and its Parquet tables are never rewritten on the way
    out. The full error of a failed case stays in its ``outcome.json``.
    """
    out = frame.copy()
    for column in out.columns:
        if out[column].dtype == object:
            out[column] = redact({"cells": list(out[column])}, project_root=root)["cells"]
    return out


def _portable(frame: pd.DataFrame) -> pd.DataFrame:
    """Return the frame with every date or instant as ISO text, so each column has one type.

    Counts stay integers where a cell is missing (``Int64``).
    """
    import pandas as pd

    out = frame.copy()
    for column in out.columns:
        values = out[column]
        if column in INTEGER_COLUMNS:
            out[column] = pd.to_numeric(values, errors="coerce").astype("Int64")
            continue
        if values.dtype == object or str(values.dtype).startswith("datetime"):
            out[column] = [_portable_cell(value) for value in values]
    return out


def _portable_cell(value: Any) -> Any:
    value = _clean(value)
    if value is None:
        return None
    if isinstance(value, datetime):
        return (value.astimezone(UTC) if value.tzinfo is not None else value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _write_csv(frame: pd.DataFrame, target: Path) -> Path:
    from hydromodpy.core.io.atomic_replace import staged_path

    with staged_path(target) as staged:
        _portable(frame).to_csv(staged, index=False)
    return target


def _in_one_crs(by_site: pd.DataFrame) -> pd.DataFrame:
    """Return ``by_site`` with every outlet in one CRS; several CRS give ``EPSG:4326``."""
    known = {
        str(crs)
        for crs, x in zip(by_site["crs"], by_site["x_outlet"], strict=True)
        if _clean(crs) is not None and _clean(x) is not None
    }
    if len(known) <= 1:
        return by_site
    from pyproj import Transformer

    out = by_site.copy()
    xs, ys = [], []
    for crs, x, y in zip(by_site["crs"], by_site["x_outlet"], by_site["y_outlet"], strict=True):
        if _clean(crs) is None or _clean(x) is None or _clean(y) is None:
            xs.append(None)
            ys.append(None)
            continue
        lon, lat = Transformer.from_crs(str(crs), "EPSG:4326", always_xy=True).transform(x, y)
        xs.append(lon)
        ys.append(lat)
    out["x_outlet"], out["y_outlet"], out["crs"] = xs, ys, "EPSG:4326"
    return out


def _write_gpkg(map_frame: pd.DataFrame, target: Path) -> Path:
    """Write the sites as points at their declared outlet."""
    import geopandas as gpd
    from shapely.geometry import Point

    from hydromodpy.core.io.atomic_replace import staged_path

    crs = next((str(c) for c in map_frame["crs"] if _clean(c) is not None), None)
    geometry = [
        Point(float(x), float(y)) if _clean(x) is not None and _clean(y) is not None else None
        for x, y in zip(map_frame["x_outlet"], map_frame["y_outlet"], strict=True)
    ]
    frame = gpd.GeoDataFrame(_portable(map_frame), geometry=geometry, crs=crs)
    with staged_path(target) as staged:
        frame.to_file(staged, driver="GPKG", layer=BY_SITE_STEM)
    return target


def _write_empty_ledger(directory: Path) -> None:
    from hydromodpy.results.ledger import Ledger

    Ledger().write(directory)


def _draw_figures(
    map_frame: pd.DataFrame, summary: SitesSummaryConfig, figures_dir: Path
) -> tuple[list[Path], list[str]]:
    """Draw each cohort figure for each variable; return the files written and those skipped.

    A figure the cohort cannot give (a variable without a finite value, a
    table without outlets) is skipped and named, ``<figure> of <variable>:
    <reason>``; the others are drawn.
    """
    if not summary.figures:
        return [], []
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from hydromodpy.display import figure_registry

    names, variables = _figure_requests(summary, map_frame.columns)
    written: list[Path] = []
    skipped: list[str] = []
    for name in names:
        figure = figure_registry.get(name)
        for variable in variables:
            target = figures_dir / f"{name}_{variable}.png"
            try:
                fig = figure.plot(map_frame, variable=variable, save_path=target)
            except ValueError as exc:
                skipped.append(f"{name} of {variable}: {exc}")
                logger.warning("summary figure %s of %s skipped: %s", name, variable, exc)
                continue
            plt.close(fig)
            _record(
                figures_dir,
                target,
                producer=f"display.figures.{name}",
                options={"variable": variable},
            )
            written.append(target)
    return written, skipped


def _figure_requests(
    summary: SitesSummaryConfig, columns: Iterable[str]
) -> tuple[list[str], list[str]]:
    """Return the cohort figures and the variables to draw, refused when unknown."""
    from hydromodpy.display import figure_registry

    names = list(dict.fromkeys(summary.figures))
    variables = list(dict.fromkeys(summary.variables)) or ["nse"]
    if not names:
        return [], variables
    cohort = sorted(name for name in figure_registry.names() if _is_cohort_figure(name))
    for name in names:
        if name not in cohort:
            raise SummaryError(
                f"[sites.summary] figures: {name!r} is not a cohort figure; the figures of "
                f"summary/ draw the table of the sites: {', '.join(cohort)}."
            )
    known = set(columns)
    unknown = [variable for variable in variables if variable not in known]
    if unknown:
        raise SummaryError(
            f"[sites.summary] variables: {', '.join(unknown)} is not a column of by_site; "
            "name a metric of metrics or a parameter of parameters."
        )
    return names, variables


def _check_exports(requests: Sequence[SitesExportRequest]) -> None:
    """Refuse an export the collect cannot write, before anything is written."""
    for request in requests:
        if request.table is not None:
            allowed = _TABLE_FORMATS[str(request.table)]
            if request.format not in allowed:
                raise SummaryError(
                    f"[[sites.export]] table = {request.table!r}: format {request.format!r} "
                    f"is not one of {', '.join(allowed)}."
                )
            continue
        if request.format != "csv":
            raise SummaryError(
                f"[[sites.export]] runs = 'best': format {request.format!r} is not written; "
                "the series of the best cases go to csv."
            )
        if not request.variables:
            raise SummaryError("[[sites.export]] runs = 'best': name the variables to export.")


def _is_cohort_figure(name: str) -> bool:
    """Whether the registered figure ``name`` draws the cohort table."""
    from hydromodpy.display import figure_registry

    return type(figure_registry.get(name)).__module__.startswith(COHORT_FIGURE_MODULE_PREFIX)


def _record(directory: Path, path: Path, *, producer: str, options: Mapping[str, Any]) -> None:
    """Add a file of the summary, drawn from many runs, to the ledger of its directory."""
    from hydromodpy.results.ledger import Ledger, LedgerEntry, sha256_of

    entry = LedgerEntry(
        file=path.relative_to(directory).as_posix(),
        producer=producer,
        options=dict(options),
        hydromodpy_version=HYDROMODPY_VERSION,
        at=datetime.now(UTC),
        sha256=sha256_of(path),
        identity=None,
    )
    ledger = Ledger.read(directory)
    ledger.append(entry)
    ledger.write(directory)


def _write_exports(
    root: Path,
    summary: Path,
    requests: Sequence[SitesExportRequest],
    by_site: pd.DataFrame,
    site_rows: Sequence[Any],
    exports_dir: Path,
) -> None:
    """Write every ``[[sites.export]]`` request under ``summary/exports/``."""
    for request in requests:
        options = request.model_dump(mode="json", exclude_defaults=True)
        if request.table is not None:
            _export_table(summary, request, site_rows, exports_dir, options)
        else:
            _export_best_runs(root, request, by_site, exports_dir, options)


def _export_table(
    summary: Path,
    request: SitesExportRequest,
    site_rows: Sequence[Any],
    exports_dir: Path,
    options: Mapping[str, Any],
) -> None:
    table = str(request.table)
    target = exports_dir / (request.file or f"{table}{_FORMAT_SUFFIX[request.format]}")
    _inside(exports_dir, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if table == "catalog":
        from hydromodpy.data.sites.catalog import write_site_rows

        write_site_rows(target, site_rows)
    else:
        shutil.copyfile(summary / f"{table}{_FORMAT_SUFFIX[request.format]}", target)
    _record(exports_dir, target, producer=COLLECT_PRODUCER, options=options)


def _export_best_runs(
    root: Path,
    request: SitesExportRequest,
    by_site: pd.DataFrame,
    exports_dir: Path,
    options: Mapping[str, Any],
) -> None:
    from hydromodpy.results.export.ledgers import record_derived_file
    from hydromodpy.results.export.run_identity import labelled_identity, read_sealed_manifest
    from hydromodpy.results.exporters.csv import export_csv

    folder = exports_dir / (request.file or BEST_EXPORTS_DIRNAME)
    _inside(exports_dir, folder)
    for record in by_site.to_dict("records"):
        if _clean(record.get("rel_dir")) is None:
            continue
        run_dir = root / str(record["rel_dir"])
        manifest = read_sealed_manifest(run_dir)
        if manifest is None:
            continue
        identity = labelled_identity(manifest)
        for variable in request.variables:
            target = folder / f"{record['site']}_{variable}.csv"
            export_csv(
                run_dir / TABLES_DIRNAME / _TIMESERIES_FILE,
                manifest.run.sim_id,
                target,
                identity=identity,
                variables=[variable],
            )
            identity.write_meta_json(target)
            record_derived_file(
                exports_dir,
                target,
                producer=COLLECT_PRODUCER,
                options={**options, "variables": [variable], "case_id": record["best_case"]},
                identity=identity,
            )


def _inside(directory: Path, target: Path) -> None:
    if not target.resolve().is_relative_to(directory.resolve()):
        raise SummaryError(f"[[sites.export]] file {target.name!r} leaves summary/exports/.")


def _write_report(
    summary: Path,
    *,
    project: str,
    collected_at: datetime,
    n_planned: int,
    n_completed: int,
    by_site: pd.DataFrame,
    figures: Sequence[Path],
    skipped: Sequence[str] = (),
) -> Path:
    """Write ``summary/report/index.html``: the counts, the sites, the figures, the comparisons."""
    from hydromodpy.core.io.atomic_replace import staged_path

    report_dir = summary / RUN_REPORT_DIRNAME
    report_dir.mkdir(parents=True, exist_ok=True)
    title = f"Summary of {project}"
    parts = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{html.escape(title)}</title>",
        "<style>body{font-family:sans-serif;margin:2rem;}table{border-collapse:collapse;}"
        "td,th{border:1px solid #ccc;padding:2px 6px;font-size:0.85rem;}"
        "img{max-width:48%;margin:4px;}</style>",
        "</head><body>",
        f"<h1>{html.escape(title)}</h1>",
        f"<p>Collected {html.escape(collected_at.isoformat(timespec='seconds'))}: "
        f"{n_completed} completed of {n_planned} cases, {len(by_site)} sites, "
        f"HydroModPy {html.escape(HYDROMODPY_VERSION)}.</p>",
        '<p>Tables: <a href="../by_site.csv">by_site.csv</a>, '
        '<a href="../by_case.csv">by_case.csv</a>, <a href="../by_site.gpkg">by_site.gpkg</a>.</p>',
        "<h2>Best case of each site</h2>",
        _portable(by_site).to_html(index=False, na_rep="", escape=True),
    ]
    if figures:
        parts.append("<h2>Figures</h2>")
        parts.extend(
            f'<img src="../{RUN_FIGURES_DIRNAME}/{html.escape(path.name)}" '
            f'alt="{html.escape(path.stem)}">'
            for path in figures
        )
    if skipped:
        parts.append("<h2>Figures not drawn</h2><ul>")
        parts.extend(f"<li>{html.escape(line)}</li>" for line in skipped)
        parts.append("</ul>")
    compare_dir = report_dir / "compare"
    pages = sorted(compare_dir.glob(f"**/{REPORT_INDEX_FILENAME}")) if compare_dir.is_dir() else []
    if pages:
        parts.append("<h2>Comparisons</h2><ul>")
        for page in pages:
            relative = page.relative_to(report_dir).as_posix()
            parts.append(f'<li><a href="{html.escape(relative)}">{html.escape(relative)}</a></li>')
        parts.append("</ul>")
    parts.append("</body></html>")
    target = report_dir / REPORT_INDEX_FILENAME
    with staged_path(target) as staged:
        staged.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return target


def _write_readme(
    summary: Path,
    *,
    project: str,
    by_case: pd.DataFrame,
    n_planned: int,
    n_completed: int,
    collected_at: datetime,
    best: str,
    catalog_written: bool,
) -> Path:
    from hydromodpy.results.ledger import sha256_of
    from hydromodpy.results.metric_rule import DateWindow
    from hydromodpy.results.readme import SummaryFacts, render_summary_readme, write_readme
    from hydromodpy.results.validity_rules import RULE_VERSION

    completed = by_case[by_case["status"] == "completed"]
    windows = {
        (rule_cell(start), rule_cell(end))
        for start, end in zip(
            completed["nse_window_start"], completed["nse_window_end"], strict=True
        )
    }
    period = None
    if len(windows) == 1:
        start, end = next(iter(windows))
        if start and end:
            period = DateWindow(start=date.fromisoformat(start), end=date.fromisoformat(end))
    versions = sorted({str(v) for v in completed["hydromodpy_version"] if _clean(v) is not None})
    facts = SummaryFacts(
        project=project,
        n_planned=n_planned,
        n_completed=n_completed,
        sites=tuple(sorted({str(s) for s in by_case["site"] if _clean(s) is not None})),
        versions=tuple(versions),
        collected_at=collected_at,
        period=period,
        label_date=collected_at.date(),
        rule_version=RULE_VERSION,
        best=best,
        catalog_written=catalog_written,
    )
    digests = {
        name: sha256_of(summary / name)
        for name in (
            f"{BY_CASE_STEM}{PARQUET_FILE_SUFFIX}",
            f"{BY_SITE_STEM}{PARQUET_FILE_SUFFIX}",
        )
    }
    return write_readme(summary, render_summary_readme(facts, digests=digests))


def _write_rocrate(
    summary: Path,
    *,
    project: str,
    by_case: pd.DataFrame,
    publication: PublicationConfig,
    collected_at: datetime,
) -> Path:
    """Write ``summary/ro-crate-metadata.json``: every file, its digest, the runs it reads."""
    from hydromodpy.results.export.rocrate import RO_CRATE_CONFORMS, RO_CRATE_CONTEXT
    from hydromodpy.results.ledger import sha256_of
    from hydromodpy.results.storage.json_io import write_json_atomic

    files = sorted(
        path
        for path in summary.rglob("*")
        if path.is_file()
        and path.name != RO_CRATE_FILENAME
        and not path.relative_to(summary).as_posix().startswith(f"{RUN_REPORT_DIRNAME}/compare/")
    )
    file_nodes = [
        {
            "@id": path.relative_to(summary).as_posix(),
            "@type": "File",
            "name": path.name,
            "encodingFormat": _MEDIA_TYPES.get(path.suffix.lower(), OCTET_STREAM_MEDIA_TYPE),
            "contentSize": path.stat().st_size,
            "sha256": sha256_of(path),
        }
        for path in files
    ]
    run_nodes = [
        {"@id": f"#{rel_dir}", "@type": "Dataset", "name": rel_dir, "identifier": sim_id}
        for rel_dir, sim_id in zip(by_case["rel_dir"], by_case["sim_id"], strict=True)
        if _clean(rel_dir) is not None
    ]
    people = [
        {"@id": f"#person/{index}", "@type": "Person", "name": name}
        for index, name in enumerate(publication.creators, start=1)
    ]
    dataset: dict[str, Any] = {
        "@id": "./",
        "@type": "Dataset",
        "name": f"Summary of {project}",
        "description": (
            f"Tables, figures and exports collected from the runs of the project {project} "
            "by hmp project collect."
        ),
        "dateCreated": collected_at.isoformat(),
        "hasPart": [{"@id": node["@id"]} for node in file_nodes],
        "isBasedOn": [{"@id": node["@id"]} for node in run_nodes],
        "creator": [{"@id": person["@id"]} for person in people],
        "publisher": {"@id": "#hydromodpy"},
    }
    if publication.license:
        dataset["license"] = publication.license
    if publication.attribution:
        dataset["creditText"] = publication.attribution
    graph = [
        {
            "@id": RO_CRATE_FILENAME,
            "@type": "CreativeWork",
            "conformsTo": {"@id": RO_CRATE_CONFORMS},
            "about": {"@id": "./"},
        },
        dataset,
        {
            "@id": "#hydromodpy",
            "@type": "SoftwareApplication",
            "name": "HydroModPy",
            "version": HYDROMODPY_VERSION,
        },
        *file_nodes,
        *run_nodes,
        *people,
    ]
    return write_json_atomic(
        summary / RO_CRATE_FILENAME, {"@context": RO_CRATE_CONTEXT, "@graph": graph}
    )


__all__ = [
    "BEST_EXPORTS_DIRNAME",
    "BY_CASE_STEM",
    "BY_SITE_STEM",
    "CASE_COLUMNS",
    "CATALOG_CSV_FILENAME",
    "COHORT_FIGURE_MODULE_PREFIX",
    "RO_CRATE_FILENAME",
    "RunFacts",
    "SummaryError",
    "SummaryPaths",
    "UnreadableManifestError",
    "collect_project",
    "names_text",
    "overrides_text",
    "rank_key",
    "rank_rows",
    "read_run_facts",
    "unscored_reason",
]
