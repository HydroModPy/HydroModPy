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
to ``hmp diff`` and is kept.

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

import json
import os
import shutil
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from pydantic import ValidationError

from hydromodpy.core.state.layout import PROJECT_MARKER_FILENAME, summary_dir_for
from hydromodpy.core.version import __version__ as HYDROMODPY_VERSION
from hydromodpy.display.cohort import cohort_figure_names, draw_cohort_figures
from hydromodpy.project.launch.summary_exports import check_exports, write_exports
from hydromodpy.project.launch.summary_tables import (
    SummaryError,
    by_case_table,
    by_site_table,
    facts_of_runs,
    parameter_names,
)
from hydromodpy.results.export.campaign_summary import (
    BY_CASE_STEM,
    BY_SITE_STEM,
    write_summary_page,
    write_summary_readme,
    write_summary_rocrate,
)
from hydromodpy.results.export.summary_tables import (
    in_one_crs,
    relative_paths,
    write_csv,
    write_gpkg,
    write_table,
)
from hydromodpy.results.run.sealed_facts import UnreadableManifestError
from hydromodpy.results.storage.contract import (
    PARQUET_FILE_SUFFIX,
    RUN_EXPORTS_DIRNAME,
    RUN_FIGURES_DIRNAME,
)

if TYPE_CHECKING:
    import pandas as pd

    from hydromodpy.config.sites import SitesExportRequest, SitesSummaryConfig
    from hydromodpy.results.publication import PublicationConfig

CATALOG_CSV_FILENAME: Final[str] = "catalog.csv"


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
    by_case, by_site, site_rows = _tables(
        root, cases, planned, settings, mixed_windows=mixed_windows
    )
    figure_names, variables = _figure_requests(settings.summary, by_site.columns)
    check_exports(settings.exports)
    collected_at = datetime.now(UTC)

    from hydromodpy.data.sites.catalog import write_site_rows

    summary = summary_dir_for(root)
    summary.mkdir(parents=True, exist_ok=True)
    by_case_path, by_site_path, map_frame = _write_tables(
        summary, root.name, by_case, by_site, collected_at
    )
    catalog_path = (
        write_site_rows(summary / CATALOG_CSV_FILENAME, site_rows) if write_sites else None
    )
    drawn, skipped = _replace_figures_and_exports(
        root,
        summary,
        settings.exports,
        map_frame=map_frame,
        figure_names=figure_names,
        variables=variables,
        by_site=by_site,
        site_rows=site_rows,
    )
    figures = [summary / RUN_FIGURES_DIRNAME / path.name for path in drawn]

    n_planned, n_completed = _counts(by_case, planned)
    report = write_summary_page(
        summary,
        project=root.name,
        collected_at=collected_at,
        n_planned=n_planned,
        n_completed=n_completed,
        by_site=by_site,
        figures=figures,
        skipped=skipped,
    )
    readme = write_summary_readme(
        summary,
        project=root.name,
        by_case=by_case,
        n_planned=n_planned,
        n_completed=n_completed,
        collected_at=collected_at,
        best=settings.summary.best,
        catalog_written=catalog_path is not None,
    )
    rocrate = write_summary_rocrate(
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
        figures=summary / RUN_FIGURES_DIRNAME,
        exports=summary / RUN_EXPORTS_DIRNAME,
        report=report,
        readme=readme,
        rocrate=rocrate,
        skipped=tuple(skipped),
    )


def _write_tables(
    summary: Path,
    project: str,
    by_case: pd.DataFrame,
    by_site: pd.DataFrame,
    collected_at: datetime,
) -> tuple[Path, Path, pd.DataFrame]:
    """Write the two tables as Parquet and CSV and the sites as a map; return the paths and the map frame."""
    metadata = {
        "hmp.summary": json.dumps(
            {
                "project": project,
                "collected_at": collected_at.isoformat(),
                "hydromodpy_version": HYDROMODPY_VERSION,
            }
        )
    }
    by_case_path = write_table(by_case, summary / f"{BY_CASE_STEM}{PARQUET_FILE_SUFFIX}", metadata)
    write_csv(by_case, summary / f"{BY_CASE_STEM}.csv")
    by_site_path = write_table(by_site, summary / f"{BY_SITE_STEM}{PARQUET_FILE_SUFFIX}", metadata)
    write_csv(by_site, summary / f"{BY_SITE_STEM}.csv")
    map_frame = in_one_crs(by_site)
    write_gpkg(map_frame, summary / f"{BY_SITE_STEM}.gpkg", layer=BY_SITE_STEM)
    return by_case_path, by_site_path, map_frame


def _tables(
    root: Path,
    cases: pd.DataFrame,
    planned: Sequence[Any],
    settings: _Settings,
    *,
    mixed_windows: bool,
) -> tuple[pd.DataFrame, pd.DataFrame, list[Any]]:
    """Return ``by_case`` and ``by_site``, paths relative to *root*, and the sites as site rows."""
    facts = facts_of_runs(root, cases)
    parameters = parameter_names(settings.summary, facts)
    by_case = relative_paths(
        by_case_table(
            cases,
            planned,
            facts,
            settings.summary,
            parameters=parameters,
            recipe_sets=settings.recipe_sets,
            root=root,
        ),
        root,
    )
    by_site, site_rows = by_site_table(
        by_case, facts, settings.summary, parameters=parameters, mixed_windows=mixed_windows
    )
    return by_case, relative_paths(by_site, root), site_rows


def _replace_figures_and_exports(
    root: Path,
    summary: Path,
    exports: Sequence[SitesExportRequest],
    *,
    map_frame: pd.DataFrame,
    figure_names: Sequence[str],
    variables: Sequence[str],
    by_site: pd.DataFrame,
    site_rows: Sequence[Any],
) -> tuple[list[Path], list[str]]:
    """Draw the figures and write the exports aside, then move them into ``summary/``.

    The previous ones are replaced only once complete: a collect that stops
    half way leaves the last summary whole. Return the figures drawn (in the
    staging folder) and those skipped.
    """
    staging = Path(tempfile.mkdtemp(prefix=".collect-", dir=summary))
    try:
        new_figures, new_exports = staging / RUN_FIGURES_DIRNAME, staging / RUN_EXPORTS_DIRNAME
        for directory in (new_figures, new_exports):
            directory.mkdir()
            _write_empty_ledger(directory)
        drawn, skipped = draw_cohort_figures(map_frame, figure_names, variables, new_figures)
        write_exports(root, summary, exports, by_site, site_rows, new_exports)
        _move_into_place(new_figures, summary / RUN_FIGURES_DIRNAME)
        _move_into_place(new_exports, summary / RUN_EXPORTS_DIRNAME)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return drawn, skipped


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
        f"{HYDROMODPY_VERSION}: {listed}{more}. A summary states every case, so it stops here: "
        "upgrade HydroModPy if a newer version sealed them, or move them to the trash with "
        "hmp catalog delete."
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
    from hydromodpy.config.hydromodpy_config import ROOT_CONFIG
    from hydromodpy.config.sites import RecipeSpec, SitesConfig, SitesSummaryConfig
    from hydromodpy.core.toml_io.loader import merge_toml_chain, read_toml_chain
    from hydromodpy.project.launch.plan import declares_sites
    from hydromodpy.results.publication import PublicationConfig

    document = merge_toml_chain(
        read_toml_chain(root / PROJECT_MARKER_FILENAME, root=ROOT_CONFIG),
        root=ROOT_CONFIG,
    )
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
    from hydromodpy.results.storage.json_io import readable

    stored = readable(read_plan, root) if current_plan_hash(root) is not None else None
    return () if stored is None else stored.cases


def _write_empty_ledger(directory: Path) -> None:
    from hydromodpy.results.ledger import Ledger

    Ledger().write(directory)


def _figure_requests(
    summary: SitesSummaryConfig, columns: Iterable[str]
) -> tuple[list[str], list[str]]:
    """Return the cohort figures and the variables to draw, refused when unknown."""
    names = list(dict.fromkeys(summary.figures))
    variables = list(dict.fromkeys(summary.variables)) or ["nse"]
    if not names:
        return [], variables
    cohort = cohort_figure_names()
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


__all__ = [
    "CATALOG_CSV_FILENAME",
    "SummaryPaths",
    "collect_project",
]
