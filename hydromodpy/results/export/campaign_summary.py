"""Write the page, the README and the RO-Crate of a campaign summary under ``summary/``.

``hmp campaign collect`` (:func:`hydromodpy.project.launch.summary.collect_project`)
writes the tables ``by_case`` and ``by_site`` and the figures first; this module
describes them: ``summary/report/index.html`` shows the counts, the best case of
each site, the figures and the comparisons; ``summary/README.md`` says what was
collected, when and under which versions; ``summary/ro-crate-metadata.json`` lists
every file with its digest and the runs it reads.
"""

from __future__ import annotations

import html
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from hydromodpy.core.version import __version__ as HYDROMODPY_VERSION
from hydromodpy.results.export.summary_tables import portable
from hydromodpy.results.run.ranking import clean_cell
from hydromodpy.results.run.sealed import rule_cell
from hydromodpy.results.storage.contract import (
    PARQUET_FILE_SUFFIX,
    REPORT_INDEX_FILENAME,
    RUN_FIGURES_DIRNAME,
    RUN_REPORT_DIRNAME,
)
from hydromodpy.schema.media_types import (
    GEOPACKAGE_MEDIA_TYPE,
    JSON_MEDIA_TYPE,
    OCTET_STREAM_MEDIA_TYPE,
    PARQUET_MEDIA_TYPE,
)

if TYPE_CHECKING:
    import pandas as pd

    from hydromodpy.results.publication import PublicationConfig

BY_CASE_STEM: Final[str] = "by_case"
BY_SITE_STEM: Final[str] = "by_site"
RO_CRATE_FILENAME: Final[str] = "ro-crate-metadata.json"

_MEDIA_TYPES: Final[dict[str, str]] = {
    ".gpkg": GEOPACKAGE_MEDIA_TYPE,
    ".json": JSON_MEDIA_TYPE,
    ".parquet": PARQUET_MEDIA_TYPE,
}
"""Suffixes of ``summary/`` whose type the shared table names; any other file is an octet
stream, as in the views of a run."""


def write_summary_page(
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
        portable(by_site).to_html(index=False, na_rep="", escape=True),
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
    pages = sorted(compare_dir.glob("**/README.md")) if compare_dir.is_dir() else []
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


def write_summary_readme(
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
    """Write ``summary/README.md``: the counts, the sites, the versions, the scored period."""
    from hydromodpy.core.io.file_digest import sha256_of
    from hydromodpy.results.metric_rule import DateWindow
    from hydromodpy.results.readme import SummaryFacts, render_summary_readme, write_readme
    from hydromodpy.results.validity_rules import RULE_VERSION

    completed = by_case[by_case["status"] == "completed"]
    windows = {
        (rule_cell(start), rule_cell(end))
        for start, end in zip(
            completed["score_window_start"], completed["score_window_end"], strict=True
        )
    }
    period = None
    if len(windows) == 1:
        start, end = next(iter(windows))
        if start and end:
            period = DateWindow(start=date.fromisoformat(start), end=date.fromisoformat(end))
    versions = sorted(
        {str(v) for v in completed["hydromodpy_version"] if clean_cell(v) is not None}
    )
    facts = SummaryFacts(
        project=project,
        n_planned=n_planned,
        n_completed=n_completed,
        sites=tuple(sorted({str(s) for s in by_case["site"] if clean_cell(s) is not None})),
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


def write_summary_rocrate(
    summary: Path,
    *,
    project: str,
    by_case: pd.DataFrame,
    publication: PublicationConfig,
    collected_at: datetime,
) -> Path:
    """Write ``summary/ro-crate-metadata.json``: every file, its digest, the runs it reads."""
    from hydromodpy.results.export.rocrate import RO_CRATE_CONFORMS, RO_CRATE_CONTEXT
    from hydromodpy.results.storage.json_io import write_json_atomic

    file_nodes = _file_nodes(summary)
    run_nodes = [
        {"@id": f"#{rel_dir}", "@type": "Dataset", "name": rel_dir, "identifier": sim_id}
        for rel_dir, sim_id in zip(by_case["rel_dir"], by_case["sim_id"], strict=True)
        if clean_cell(rel_dir) is not None
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
            "by hmp campaign collect."
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


def _file_nodes(summary: Path) -> list[dict[str, Any]]:
    """Return a node per file of ``summary/``, its own crate and the comparisons left out."""
    from hydromodpy.core.io.file_digest import sha256_of

    files = sorted(
        path
        for path in summary.rglob("*")
        if path.is_file()
        and path.name != RO_CRATE_FILENAME
        and not path.relative_to(summary).as_posix().startswith(f"{RUN_REPORT_DIRNAME}/compare/")
    )
    return [
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


__all__ = [
    "BY_CASE_STEM",
    "BY_SITE_STEM",
    "RO_CRATE_FILENAME",
    "write_summary_page",
    "write_summary_readme",
    "write_summary_rocrate",
]
