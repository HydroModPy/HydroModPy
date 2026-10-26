"""``hmp report compare``: compare N sealed runs and render the page.

The references are resolved to run directories, grouped (one group, or one
per site under ``by_site``), each group is checked as one case and compared by
:func:`hydromodpy.analysis.comparison.run_comparison.run_comparison`, then the
page is rendered from the comparison folder. The output lives under
``summary/report/compare/<name>/`` of the project, or under ``out``; under
``by_site`` each site gets its own sub-folder, and the folder itself gets
``by_site.csv`` and ``index.html``: the references joined on the site, one row
per site, the run, label and score of each reference side by side, a link to
the page of the site. Nothing is written into a run.
"""

from __future__ import annotations

import hashlib
import html
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from hydromodpy.analysis.comparison.config import BudgetZone
from hydromodpy.analysis.comparison.run_comparison import run_comparison
from hydromodpy.analysis.comparison.runs import (
    ComparedRun,
    ComparisonCaseError,
    group_runs,
    resolve_references,
)
from hydromodpy.core.state.paths import summary_dir_for
from hydromodpy.reporting.comparison.render import write_comparison_web_report
from hydromodpy.results.export.run_identity import label_of
from hydromodpy.results.storage.contract import REPORT_INDEX_FILENAME, RUN_REPORT_DIRNAME

COMPARE_DIRNAME = "compare"
"""Folder of the comparisons under ``summary/report/`` of a project."""

NO_SITE_DIRNAME = "no_site"
"""Sub-folder of the runs that declare no site, under ``by_site``."""

SITES_TABLE_FILENAME = "by_site.csv"
"""Table of a comparison by site: the references joined on the site."""

_MAX_NAME_LENGTH = 96
_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def comparison_name(refs: Sequence[str]) -> str:
    """Return the folder name of a comparison: its references, or their hash when long."""
    slugs = [_UNSAFE.sub("_", Path(ref).name or ref).strip("_") for ref in refs]
    name = "-vs-".join(slug for slug in slugs if slug)
    if name and len(name) <= _MAX_NAME_LENGTH:
        return name
    return hashlib.sha256("\n".join(refs).encode("utf-8")).hexdigest()[:12]


def default_compare_root(project_root: Path, refs: Sequence[str]) -> Path:
    """Return ``summary/report/compare/<name>/`` of the project."""
    return (
        summary_dir_for(project_root) / RUN_REPORT_DIRNAME / COMPARE_DIRNAME / comparison_name(refs)
    )


def compare_runs(
    refs: Sequence[str],
    *,
    project_root: Path | None,
    out: Path | None = None,
    by_site: bool = False,
    variables: Sequence[str] | None = None,
    allow_different_mesh: bool = False,
    budget_zone: BudgetZone = "domain",
) -> list[Path]:
    """Compare the runs *refs* name and return the ``index.html`` of each comparison.

    Under ``by_site`` the last page returned is the index of the sites, which
    joins the references on the site.

    Raises :class:`~hydromodpy.analysis.comparison.runs.ComparisonReferenceError`
    for a reference that names no sealed run, and
    :class:`~hydromodpy.analysis.comparison.runs.ComparisonCaseError` when the
    runs are not one case.
    """
    reference_labels(refs)
    resolved = resolve_references(refs, project_root=project_root)
    groups = group_runs(resolved, by_site=by_site)
    if not groups:
        raise ComparisonCaseError("No site holds a run in two of the references.")
    if out is not None:
        root = Path(out).expanduser().resolve()
    elif project_root is not None:
        root = default_compare_root(project_root, refs)
    else:
        raise ComparisonCaseError(
            "No project around the runs to write the comparison into: pass --out DIR."
        )
    name = comparison_name(refs)
    pages: list[Path] = []
    for site, runs in groups.items():
        if by_site:
            folder = site or NO_SITE_DIRNAME
            comparison_root, comparison_id = root / folder, f"{name}-{folder}"
        else:
            comparison_root, comparison_id = root, name
        outcome = run_comparison(
            runs,
            comparison_root=comparison_root,
            comparison_id=comparison_id,
            variables=variables,
            allow_different_mesh=allow_different_mesh,
            budget_zone=budget_zone,
        )
        pages.append(
            write_comparison_web_report(
                comparison_root=outcome.comparison_root, manifest=outcome.manifest
            )
        )
    if by_site:
        pages.append(write_sites_index(root, refs, resolved, groups, pages))
    return pages


def _reference_label(ref: str) -> str:
    return Path(ref).name or ref


def reference_labels(refs: Sequence[str]) -> list[str]:
    """Return the column label of each reference.

    A label is the last part of the reference (``runs/base`` gives ``base``),
    or the whole reference when two references share that last part, so the
    columns of two projects' ``runs/base`` never overwrite each other.

    Raises :class:`~hydromodpy.analysis.comparison.runs.ComparisonCaseError`
    for a reference given twice.
    """
    twice = sorted({ref for ref in refs if list(refs).count(ref) > 1})
    if twice:
        raise ComparisonCaseError(f"{', '.join(twice)} is given twice; name each reference once.")
    names = [_reference_label(ref) for ref in refs]
    return [ref if names.count(name) > 1 else name for ref, name in zip(refs, names, strict=True)]


def sites_table(
    refs: Sequence[str],
    resolved: Sequence[Sequence[ComparedRun]],
    groups: Mapping[str | None, Sequence[ComparedRun]],
) -> list[dict[str, Any]]:
    """Return one row per compared site: the run, label, score and window of each reference."""
    labels = reference_labels(refs)
    owner = {
        run.run_dir: label for label, runs in zip(labels, resolved, strict=True) for run in runs
    }
    rows: list[dict[str, Any]] = []
    for site, runs in groups.items():
        row: dict[str, Any] = {"site": site or NO_SITE_DIRNAME}
        for label in labels:
            for column in ("run", "label", "score", "metric", "window"):
                row[f"{label}.{column}"] = None
        for run in runs:
            label, record = owner[run.run_dir], run.record
            score = record.score
            row[f"{label}.run"] = run.name
            row[f"{label}.label"] = label_of(record).label
            if score is not None:
                row[f"{label}.score"] = score.value
                row[f"{label}.metric"] = score.metric
                if score.nse_window_start is not None:
                    row[f"{label}.window"] = f"{score.nse_window_start}/{score.nse_window_end}"
        rows.append(row)
    return rows


def write_sites_index(
    root: Path,
    refs: Sequence[str],
    resolved: Sequence[Sequence[ComparedRun]],
    groups: Mapping[str | None, Sequence[ComparedRun]],
    pages: Sequence[Path],
) -> Path:
    """Write ``by_site.csv`` and ``index.html`` of a comparison by site; return the page."""
    import pandas as pd

    rows = sites_table(refs, resolved, groups)
    frame = pd.DataFrame(rows)
    root.mkdir(parents=True, exist_ok=True)
    frame.to_csv(root / SITES_TABLE_FILENAME, index=False)
    links = {page.relative_to(root).parts[0]: page.relative_to(root).as_posix() for page in pages}
    body = [
        "<tr>"
        + "".join(f"<th>{html.escape(str(column))}</th>" for column in frame.columns)
        + "</tr>"
    ]
    for row in rows:
        cells = []
        for column in frame.columns:
            value = row[column]
            text = "" if value is None else html.escape(str(value))
            if column == "site" and row["site"] in links:
                text = f'<a href="{html.escape(links[row["site"]])}">{text}</a>'
            cells.append(f"<td>{text}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    title = "Comparison by site: " + " vs ".join(reference_labels(refs))
    page = root / REPORT_INDEX_FILENAME
    page.write_text(
        "\n".join(
            [
                "<!doctype html>",
                '<html lang="en"><head><meta charset="utf-8">',
                f"<title>{html.escape(title)}</title>",
                "<style>body{font-family:sans-serif;margin:2rem;}table{border-collapse:collapse;}"
                "td,th{border:1px solid #ccc;padding:2px 6px;}</style>",
                "</head><body>",
                f"<h1>{html.escape(title)}</h1>",
                f"<p>{len(rows)} sites; table: "
                f'<a href="{SITES_TABLE_FILENAME}">{SITES_TABLE_FILENAME}</a>.</p>',
                "<table>",
                *body,
                "</table>",
                "</body></html>",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return page


__all__ = (
    "COMPARE_DIRNAME",
    "SITES_TABLE_FILENAME",
    "compare_runs",
    "comparison_name",
    "default_compare_root",
    "reference_labels",
    "sites_table",
    "write_sites_index",
)
