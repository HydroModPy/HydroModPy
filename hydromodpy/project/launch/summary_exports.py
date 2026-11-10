"""Write the ``[[sites.export]]`` requests of a project under ``summary/exports/``.

A request copies a table of ``summary/`` (``by_case``, ``by_site``, the site
``catalog``) or exports the series of the best case of each site to csv. Each
file is recorded in the ledger of ``summary/exports/`` under
:data:`COLLECT_PRODUCER`.
"""

from __future__ import annotations

import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from hydromodpy.display.cohort import record_collected_file
from hydromodpy.project.launch.summary_tables import SummaryError
from hydromodpy.results.export.campaign_summary import BY_CASE_STEM, BY_SITE_STEM
from hydromodpy.results.run.ranking import clean_cell
from hydromodpy.results.storage.contract import PARQUET_FILE_SUFFIX, TABLES_DIRNAME

if TYPE_CHECKING:
    import pandas as pd

    from hydromodpy.config.sites import SitesExportRequest

BEST_EXPORTS_DIRNAME: Final[str] = "best"
"""Folder of ``summary/exports/`` holding the series of the best case of each site."""

COLLECT_PRODUCER: Final[str] = "project.summary"
"""Producer the ledgers of ``summary/`` name for an export."""

_TIMESERIES_FILE: Final[str] = f"timeseries{PARQUET_FILE_SUFFIX}"
"""The series payload of a run, under ``tables.parquet/``."""

_TABLE_FORMATS: Final[dict[str, tuple[str, ...]]] = {
    BY_CASE_STEM: ("csv", "parquet"),
    BY_SITE_STEM: ("csv", "parquet", "gpkg"),
    "catalog": ("csv",),
}
"""Formats a ``[[sites.export]] table`` may ask for, per table."""

_FORMAT_SUFFIX: Final[dict[str, str]] = {"csv": ".csv", "parquet": ".parquet", "gpkg": ".gpkg"}


def check_exports(requests: Sequence[SitesExportRequest]) -> None:
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


def write_exports(
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
    record_collected_file(exports_dir, target, producer=COLLECT_PRODUCER, options=options)


def _export_best_runs(
    root: Path,
    request: SitesExportRequest,
    by_site: pd.DataFrame,
    exports_dir: Path,
    options: Mapping[str, Any],
) -> None:
    from hydromodpy.results.exporters.csv import export_csv
    from hydromodpy.results.ledger import record_derived_file
    from hydromodpy.results.record.label import labelled_identity, read_sealed_manifest

    folder = exports_dir / (request.file or BEST_EXPORTS_DIRNAME)
    _inside(exports_dir, folder)
    for record in by_site.to_dict("records"):
        if clean_cell(record.get("rel_dir")) is None:
            continue
        run_dir = root / str(record["rel_dir"])
        manifest = read_sealed_manifest(run_dir)
        if manifest is None:
            continue
        identity = labelled_identity(manifest, run_dir)
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


__all__ = ["BEST_EXPORTS_DIRNAME", "COLLECT_PRODUCER", "check_exports", "write_exports"]
