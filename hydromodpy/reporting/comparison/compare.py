"""``hmp report compare``: compare N sealed runs and render the page.

The references are resolved to run directories, grouped (one group, or one
per site under ``by_site``), each group is checked as one case and compared by
:func:`hydromodpy.analysis.comparison.run_comparison.run_comparison`, then the
page is rendered from the comparison folder. The output lives under
``summary/report/compare/<name>/`` of the project, or under ``out``; under
``by_site`` each site gets its own sub-folder. Nothing is written into a run.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from pathlib import Path

from hydromodpy.analysis.comparison.run_comparison import run_comparison
from hydromodpy.analysis.comparison.runs import (
    ComparisonCaseError,
    group_runs,
    resolve_references,
)
from hydromodpy.core.state.paths import summary_dir_for
from hydromodpy.reporting.comparison.render import write_comparison_web_report
from hydromodpy.results.storage.contract import RUN_REPORT_DIRNAME

COMPARE_DIRNAME = "compare"
"""Folder of the comparisons under ``summary/report/`` of a project."""

NO_SITE_DIRNAME = "no_site"
"""Sub-folder of the runs that declare no site, under ``by_site``."""

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
) -> list[Path]:
    """Compare the runs *refs* name and return the ``index.html`` of each comparison.

    Raises :class:`~hydromodpy.analysis.comparison.runs.ComparisonReferenceError`
    for a reference that names no sealed run, and
    :class:`~hydromodpy.analysis.comparison.runs.ComparisonCaseError` when the
    runs are not one case.
    """
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
        )
        pages.append(
            write_comparison_web_report(
                comparison_root=outcome.comparison_root, manifest=outcome.manifest
            )
        )
    return pages


__all__ = ("COMPARE_DIRNAME", "compare_runs", "comparison_name", "default_compare_root")
