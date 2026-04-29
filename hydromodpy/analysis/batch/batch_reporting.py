"""Persistence helpers (JSON, CSV, Markdown) for the regional-lab family."""

from __future__ import annotations

import csv
import json
import os
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hydromodpy.analysis.batch.batch_execution import _safe_float
from hydromodpy.analysis.batch.batch_planning import (
    build_run_command,
    filter_sites,
)
from hydromodpy.analysis.batch.batch_types import (
    RegionalLabExecution,
    RegionalLabPlannedCase,
    RegionalLabSiteRecord,
    RegionalLabSkippedCase,
    _normalize_text,
)
from hydromodpy.analysis.batch.config import RegionalLabConfig


def _atomic_write_text(path: Path, payload: str, *, encoding: str = "utf-8") -> None:
    """Write text content atomically via tmp + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(payload, encoding=encoding)
    os.replace(tmp_path, path)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write one JSON payload to disk atomically."""
    _atomic_write_text(
        path,
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
    )


def _csv_cell(value: object) -> str:
    """Serialize one CSV cell value."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, ensure_ascii=True)
    return str(value)


def _write_csv_rows(
    path: Path,
    *,
    fieldnames: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
) -> None:
    """Persist one flat CSV file atomically."""
    import io

    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(fieldnames))
    writer.writeheader()
    for row in rows:
        writer.writerow({field: _csv_cell(row.get(field)) for field in fieldnames})
    _atomic_write_text(path, buffer.getvalue())


def _collect_fieldnames(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """Collect CSV fieldnames in first-seen order across heterogeneous rows."""
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row.keys():
            text = str(key)
            if text in seen:
                continue
            seen.add(text)
            out.append(text)
    return out


def _build_plan_payload(
    *,
    cfg: RegionalLabConfig,
    selected_sites: list[RegionalLabSiteRecord],
    planned_cases: list[RegionalLabPlannedCase],
    skipped_cases: list[RegionalLabSkippedCase],
) -> dict[str, Any]:
    """Build one JSON-serializable execution plan."""
    return {
        "schema_version": "regional_lab_plan_v2",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "lab_id": cfg.lab_id,
        "config_path": str(cfg.config_path),
        "site_catalog_path": str(cfg.catalog.path),
        "output_root": str(cfg.output_root),
        "selected_site_count": len(selected_sites),
        "planned_case_count": len(planned_cases),
        "skipped_case_count": len(skipped_cases),
        "selected_sites": [site.to_summary_mapping() for site in selected_sites],
        "cluster_rules": [
            {
                "id": rule.id,
                "label": rule.label,
                "enabled": bool(rule.enabled),
                "priority": int(rule.priority),
                "field_equals": dict(rule.field_equals),
                "set_cluster_id": rule.set_cluster_id,
                "set_cluster_label": rule.set_cluster_label,
                "set_cluster_family": rule.set_cluster_family,
                "set_cluster_scale": rule.set_cluster_scale,
                "cluster_tags": list(rule.cluster_tags),
            }
            for rule in cfg.cluster_rules
        ],
        "recipes": [
            {
                "id": recipe.id,
                "label": recipe.label,
                "launcher": recipe.launcher,
                "enabled": bool(recipe.enabled),
                "config_path_template": recipe.config_path_template,
                "required_fields": list(recipe.required_fields),
                "allowed_platforms": list(recipe.allowed_platforms),
            }
            for recipe in cfg.recipes
        ],
        "cases": [case.to_summary_mapping() for case in planned_cases],
        "skipped_cases": [case.to_summary_mapping() for case in skipped_cases],
    }


def _execution_by_case_id(
    executions: Sequence[RegionalLabExecution],
) -> dict[str, RegionalLabExecution]:
    """Index execution rows by case identifier."""
    return {execution.case.case_id: execution for execution in executions}


def _build_recipe_summaries(
    *,
    cfg: RegionalLabConfig,
    selected_sites: Sequence[RegionalLabSiteRecord],
    planned_cases: Sequence[RegionalLabPlannedCase],
    skipped_cases: Sequence[RegionalLabSkippedCase],
    executions: Sequence[RegionalLabExecution],
) -> list[dict[str, Any]]:
    """Build one compact summary per recipe."""
    executions_by_case_id = _execution_by_case_id(executions)
    rows: list[dict[str, Any]] = []
    for recipe in cfg.recipes:
        if not recipe.enabled:
            continue
        candidate_sites = filter_sites(selected_sites, selection=recipe.selection)
        recipe_planned = [case for case in planned_cases if case.recipe_id == recipe.id]
        recipe_skipped = [case for case in skipped_cases if case.recipe_id == recipe.id]
        recipe_executions = [
            execution
            for case in recipe_planned
            if (execution := executions_by_case_id.get(case.case_id)) is not None
        ]
        execution_durations = [
            float(item.duration_seconds)
            for item in recipe_executions
            if item.duration_seconds is not None
        ]
        child_wall_times = [
            float(item.child_artifacts["child_wall_time_seconds"])
            for item in recipe_executions
            if _safe_float(item.child_artifacts.get("child_wall_time_seconds")) is not None
        ]
        executed_fresh = [item for item in recipe_executions if not item.reused_from_report]
        reused = [item for item in recipe_executions if item.reused_from_report]
        failed = [item for item in recipe_executions if item.status == "failed"]
        ok = [item for item in recipe_executions if item.status in {"ok", "skipped_existing_ok"}]
        pending_count = len(recipe_planned) - len(recipe_executions)
        rows.append(
            {
                "recipe_id": recipe.id,
                "recipe_label": recipe.label,
                "launcher": recipe.launcher,
                "candidate_site_count": len(candidate_sites),
                "planned_case_count": len(recipe_planned),
                "skipped_case_count": len(recipe_skipped),
                "executed_case_count": len(executed_fresh),
                "reused_case_count": len(reused),
                "successful_case_count": len(ok),
                "failed_case_count": len(failed),
                "pending_case_count": pending_count,
                "execution_duration_seconds_total": (
                    None if not execution_durations else round(sum(execution_durations), 6)
                ),
                "execution_duration_seconds_mean": (
                    None
                    if not execution_durations
                    else round(sum(execution_durations) / len(execution_durations), 6)
                ),
                "child_wall_time_seconds_total": (
                    None if not child_wall_times else round(sum(child_wall_times), 6)
                ),
                "coverage_ratio": (
                    0.0
                    if not candidate_sites
                    else round(len(recipe_planned) / len(candidate_sites), 6)
                ),
            }
        )
    return rows


def _build_group_summary(
    *,
    label: str,
    selected_sites: Sequence[RegionalLabSiteRecord],
    planned_cases: Sequence[RegionalLabPlannedCase],
    skipped_cases: Sequence[RegionalLabSkippedCase],
    executions: Sequence[RegionalLabExecution],
    extractor,
) -> list[dict[str, Any]]:
    """Build one compact summary by cluster, region, family, or scale."""
    execution_by_case_id = _execution_by_case_id(executions)
    groups: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            label: "",
            "site_count": 0,
            "planned_case_count": 0,
            "skipped_case_count": 0,
            "executed_case_count": 0,
            "reused_case_count": 0,
            "successful_case_count": 0,
            "failed_case_count": 0,
            "pending_case_count": 0,
        }
    )

    for site in selected_sites:
        key = extractor(site)
        row = groups[key]
        row[label] = key
        row["site_count"] += 1

    for case in planned_cases:
        key = extractor(case.site)
        row = groups[key]
        row[label] = key
        row["planned_case_count"] += 1
        execution = execution_by_case_id.get(case.case_id)
        if execution is None:
            row["pending_case_count"] += 1
            continue
        if execution.reused_from_report:
            row["reused_case_count"] += 1
        else:
            row["executed_case_count"] += 1
        duration_seconds = _safe_float(execution.duration_seconds)
        if duration_seconds is not None:
            row["execution_duration_seconds_total"] = round(
                float(row.get("execution_duration_seconds_total", 0.0)) + duration_seconds,
                6,
            )
        child_wall_time = _safe_float(execution.child_artifacts.get("child_wall_time_seconds"))
        if child_wall_time is not None:
            row["child_wall_time_seconds_total"] = round(
                float(row.get("child_wall_time_seconds_total", 0.0)) + child_wall_time,
                6,
            )
        if execution.status in {"ok", "skipped_existing_ok"}:
            row["successful_case_count"] += 1
        if execution.status == "failed":
            row["failed_case_count"] += 1

    for case in skipped_cases:
        key = extractor(case.site)
        row = groups[key]
        row[label] = key
        row["skipped_case_count"] += 1

    rows = list(groups.values())
    for row in rows:
        executed_count = int(row.get("executed_case_count", 0)) + int(
            row.get("reused_case_count", 0)
        )
        duration_total = _safe_float(row.get("execution_duration_seconds_total"))
        child_total = _safe_float(row.get("child_wall_time_seconds_total"))
        row["execution_duration_seconds_mean"] = (
            None
            if duration_total is None or executed_count <= 0
            else round(duration_total / executed_count, 6)
        )
        row["child_wall_time_seconds_mean"] = (
            None
            if child_total is None or executed_count <= 0
            else round(child_total / executed_count, 6)
        )
    rows.sort(key=lambda row: str(row[label]).lower())
    return rows


def _build_site_inventory_rows(
    *,
    selected_sites: Sequence[RegionalLabSiteRecord],
    planned_cases: Sequence[RegionalLabPlannedCase],
    skipped_cases: Sequence[RegionalLabSkippedCase],
    executions: Sequence[RegionalLabExecution],
) -> list[dict[str, Any]]:
    """Build one site inventory CSV."""
    execution_by_case_id = _execution_by_case_id(executions)
    rows: list[dict[str, Any]] = []
    for site in selected_sites:
        site_planned = [case for case in planned_cases if case.site.site_id == site.site_id]
        site_skipped = [case for case in skipped_cases if case.site.site_id == site.site_id]
        site_executions = [
            execution
            for case in site_planned
            if (execution := execution_by_case_id.get(case.case_id)) is not None
        ]
        row = site.to_inventory_mapping()
        row.update(
            {
                "planned_case_count": len(site_planned),
                "skipped_case_count": len(site_skipped),
                "executed_case_count": len(
                    [item for item in site_executions if not item.reused_from_report]
                ),
                "reused_case_count": len(
                    [item for item in site_executions if item.reused_from_report]
                ),
                "failed_case_count": len(
                    [item for item in site_executions if item.status == "failed"]
                ),
                "execution_duration_seconds_total": round(
                    sum(
                        float(item.duration_seconds)
                        for item in site_executions
                        if item.duration_seconds is not None
                    ),
                    6,
                )
                if site_executions
                else None,
                "recipes_planned": ";".join(case.recipe_id for case in site_planned),
                "recipes_skipped": ";".join(case.recipe_id for case in site_skipped),
            }
        )
        rows.append(row)
    rows.sort(key=lambda row: str(row["site_id"]).lower())
    return rows


def _build_case_rows(
    *,
    planned_cases: Sequence[RegionalLabPlannedCase],
    skipped_cases: Sequence[RegionalLabSkippedCase],
    executions: Sequence[RegionalLabExecution],
) -> list[dict[str, Any]]:
    """Build one case matrix CSV combining planned, skipped, and executed cases."""
    execution_by_case_id = _execution_by_case_id(executions)
    rows: list[dict[str, Any]] = []
    for case in planned_cases:
        execution = execution_by_case_id.get(case.case_id)
        row = case.to_summary_mapping()
        row["status"] = "planned" if execution is None else execution.status
        row["returncode"] = None if execution is None else execution.returncode
        row["duration_seconds"] = None if execution is None else execution.duration_seconds
        row["reused_from_report"] = False if execution is None else execution.reused_from_report
        row["child_artifacts_json"] = (
            "" if execution is None else json.dumps(execution.child_artifacts, ensure_ascii=True)
        )
        row["child_wall_time_seconds"] = (
            None
            if execution is None
            else _safe_float(execution.child_artifacts.get("child_wall_time_seconds"))
        )
        row["child_success"] = (
            None if execution is None else execution.child_artifacts.get("child_success")
        )
        row["reason"] = ""
        row["detail"] = ""
        rows.append(row)
    for skipped in skipped_cases:
        row = skipped.to_summary_mapping()
        row["status"] = f"skipped_{skipped.reason}"
        row["returncode"] = None
        row["duration_seconds"] = None
        row["reused_from_report"] = False
        row["child_artifacts_json"] = ""
        row["child_wall_time_seconds"] = None
        row["child_success"] = None
        rows.append(row)
    rows.sort(
        key=lambda row: (str(row.get("recipe_id", "")).lower(), str(row.get("site_id", "")).lower())
    )
    return rows


def _build_execution_metric_rows(
    *,
    executions: Sequence[RegionalLabExecution],
) -> list[dict[str, Any]]:
    """Build one flat per-execution CSV enriched with child artifacts."""
    rows: list[dict[str, Any]] = []
    for execution in executions:
        row = execution.case.to_summary_mapping()
        row.update(
            {
                "status": execution.status,
                "returncode": execution.returncode,
                "duration_seconds": execution.duration_seconds,
                "reused_from_report": execution.reused_from_report,
                "command_json": json.dumps(list(execution.command), ensure_ascii=True),
            }
        )
        row.update(execution.child_artifacts)
        rows.append(row)
    rows.sort(
        key=lambda row: (str(row.get("recipe_id", "")).lower(), str(row.get("site_id", "")).lower())
    )
    return rows


def _render_summary_markdown(
    *,
    cfg: RegionalLabConfig,
    selected_sites: Sequence[RegionalLabSiteRecord],
    planned_cases: Sequence[RegionalLabPlannedCase],
    skipped_cases: Sequence[RegionalLabSkippedCase],
    executions: Sequence[RegionalLabExecution],
    recipe_summary_rows: Sequence[Mapping[str, Any]],
    cluster_summary_rows: Sequence[Mapping[str, Any]],
    region_summary_rows: Sequence[Mapping[str, Any]],
) -> str:
    """Render one compact Markdown report for the regional lab."""
    executed_fresh = [item for item in executions if not item.reused_from_report]
    reused = [item for item in executions if item.reused_from_report]
    failed = [item for item in executions if item.status == "failed"]

    lines = [
        f"# Regional Lab Summary: {cfg.lab_id}",
        "",
        f"- Config: `{cfg.config_path}`",
        f"- Site catalog: `{cfg.catalog.path}`",
        f"- Selected sites: {len(selected_sites)}",
        f"- Planned cases: {len(planned_cases)}",
        f"- Skipped cases: {len(skipped_cases)}",
        f"- Executed cases: {len(executed_fresh)}",
        f"- Reused cases: {len(reused)}",
        f"- Failed cases: {len(failed)}",
        "",
        "## Recipes",
        "",
        "| Recipe | Candidate sites | Planned | Skipped | Executed | Reused | Failed | Pending |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in recipe_summary_rows:
        lines.append(
            "| {recipe_id} | {candidate_site_count} | {planned_case_count} | "
            "{skipped_case_count} | {executed_case_count} | {reused_case_count} | "
            "{failed_case_count} | {pending_case_count} |".format(**row)
        )

    lines.extend(
        [
            "",
            "## Clusters",
            "",
            "| Cluster | Sites | Planned | Skipped | Executed | Reused | Failed | Pending |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in cluster_summary_rows:
        lines.append(
            "| {cluster_id} | {site_count} | {planned_case_count} | "
            "{skipped_case_count} | {executed_case_count} | {reused_case_count} | "
            "{failed_case_count} | {pending_case_count} |".format(**row)
        )

    lines.extend(
        [
            "",
            "## Regions",
            "",
            "| Region | Sites | Planned | Skipped | Executed | Reused | Failed | Pending |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in region_summary_rows:
        lines.append(
            "| {region_id} | {site_count} | {planned_case_count} | "
            "{skipped_case_count} | {executed_case_count} | {reused_case_count} | "
            "{failed_case_count} | {pending_case_count} |".format(**row)
        )

    if skipped_cases:
        lines.extend(["", "## Coverage Gaps", ""])
        for skipped in skipped_cases:
            lines.append(
                f"- `{skipped.recipe_id}` / `{skipped.site.site_id}`: "
                f"{skipped.reason} ({skipped.detail})"
            )

    return "\n".join(lines) + "\n"


def _write_summary_artifacts(
    *,
    cfg: RegionalLabConfig,
    selected_sites: Sequence[RegionalLabSiteRecord],
    planned_cases: Sequence[RegionalLabPlannedCase],
    skipped_cases: Sequence[RegionalLabSkippedCase],
    executions: Sequence[RegionalLabExecution],
) -> dict[str, str]:
    """Persist compact synthesis artifacts for the current regional-lab state."""
    recipe_summary_rows = _build_recipe_summaries(
        cfg=cfg,
        selected_sites=selected_sites,
        planned_cases=planned_cases,
        skipped_cases=skipped_cases,
        executions=executions,
    )
    cluster_summary_rows = _build_group_summary(
        label="cluster_id",
        selected_sites=selected_sites,
        planned_cases=planned_cases,
        skipped_cases=skipped_cases,
        executions=executions,
        extractor=lambda site: site.cluster_id or "unassigned",
    )
    region_summary_rows = _build_group_summary(
        label="region_id",
        selected_sites=selected_sites,
        planned_cases=planned_cases,
        skipped_cases=skipped_cases,
        executions=executions,
        extractor=lambda site: site.region_id or "unassigned",
    )
    family_summary_rows = _build_group_summary(
        label="cluster_family",
        selected_sites=selected_sites,
        planned_cases=planned_cases,
        skipped_cases=skipped_cases,
        executions=executions,
        extractor=lambda site: site.cluster_family or "unassigned",
    )
    scale_summary_rows = _build_group_summary(
        label="cluster_scale",
        selected_sites=selected_sites,
        planned_cases=planned_cases,
        skipped_cases=skipped_cases,
        executions=executions,
        extractor=lambda site: site.cluster_scale or "unassigned",
    )
    site_inventory_rows = _build_site_inventory_rows(
        selected_sites=selected_sites,
        planned_cases=planned_cases,
        skipped_cases=skipped_cases,
        executions=executions,
    )
    case_rows = _build_case_rows(
        planned_cases=planned_cases,
        skipped_cases=skipped_cases,
        executions=executions,
    )
    execution_metric_rows = _build_execution_metric_rows(executions=executions)

    paths = {
        "site_inventory_csv": str((cfg.output_root / "regional_lab_site_inventory.csv").resolve()),
        "case_matrix_csv": str((cfg.output_root / "regional_lab_case_matrix.csv").resolve()),
        "execution_metrics_csv": str(
            (cfg.output_root / "regional_lab_execution_metrics.csv").resolve()
        ),
        "recipe_summary_csv": str((cfg.output_root / "regional_lab_recipe_summary.csv").resolve()),
        "cluster_summary_csv": str(
            (cfg.output_root / "regional_lab_cluster_summary.csv").resolve()
        ),
        "region_summary_csv": str((cfg.output_root / "regional_lab_region_summary.csv").resolve()),
        "family_summary_csv": str((cfg.output_root / "regional_lab_family_summary.csv").resolve()),
        "scale_summary_csv": str((cfg.output_root / "regional_lab_scale_summary.csv").resolve()),
        "summary_markdown": str((cfg.output_root / "regional_lab_summary.md").resolve()),
    }

    _write_csv_rows(
        Path(paths["site_inventory_csv"]),
        fieldnames=_collect_fieldnames(site_inventory_rows)
        if site_inventory_rows
        else [
            "site_id",
            "site_label",
            "cluster_id",
            "cluster_label",
            "cluster_family",
            "cluster_scale",
            "region_id",
            "source_selection_id",
            "site_status",
            "maturity",
            "enabled",
            "x",
            "y",
            "area_km2",
            "site_tags",
            "cluster_tags",
            "tags",
            "resolved_paths_json",
            "planned_case_count",
            "skipped_case_count",
            "executed_case_count",
            "reused_case_count",
            "failed_case_count",
            "recipes_planned",
            "recipes_skipped",
        ],
        rows=site_inventory_rows,
    )
    _write_csv_rows(
        Path(paths["case_matrix_csv"]),
        fieldnames=_collect_fieldnames(case_rows)
        if case_rows
        else [
            "case_id",
            "site_id",
            "recipe_id",
            "status",
        ],
        rows=case_rows,
    )
    _write_csv_rows(
        Path(paths["execution_metrics_csv"]),
        fieldnames=_collect_fieldnames(execution_metric_rows)
        if execution_metric_rows
        else ["case_id", "site_id", "recipe_id", "status"],
        rows=execution_metric_rows,
    )
    for key, rows in (
        ("recipe_summary_csv", recipe_summary_rows),
        ("cluster_summary_csv", cluster_summary_rows),
        ("region_summary_csv", region_summary_rows),
        ("family_summary_csv", family_summary_rows),
        ("scale_summary_csv", scale_summary_rows),
    ):
        fieldnames = _collect_fieldnames(rows) if rows else []
        if not fieldnames:
            continue
        _write_csv_rows(Path(paths[key]), fieldnames=fieldnames, rows=rows)

    _atomic_write_text(
        Path(paths["summary_markdown"]),
        _render_summary_markdown(
            cfg=cfg,
            selected_sites=selected_sites,
            planned_cases=planned_cases,
            skipped_cases=skipped_cases,
            executions=executions,
            recipe_summary_rows=recipe_summary_rows,
            cluster_summary_rows=cluster_summary_rows,
            region_summary_rows=region_summary_rows,
        ),
    )
    return paths


def _build_report_payload(
    *,
    cfg: RegionalLabConfig,
    selected_sites: list[RegionalLabSiteRecord],
    planned_cases: list[RegionalLabPlannedCase],
    skipped_cases: list[RegionalLabSkippedCase],
    executions: list[RegionalLabExecution],
    synthesis_paths: Mapping[str, str],
) -> dict[str, Any]:
    """Build one JSON-serializable execution report."""
    execution_by_case_id = _execution_by_case_id(executions)
    failed = [item for item in executions if item.status == "failed"]
    reused = [item for item in executions if item.reused_from_report]
    executed_fresh = [item for item in executions if not item.reused_from_report]
    pending_count = len(planned_cases) - len(executions)
    python_executable = cfg.python_executable or Path(sys.executable)

    cases_payload: list[dict[str, Any]] = []
    for case in planned_cases:
        execution = execution_by_case_id.get(case.case_id)
        command = build_run_command(case, python_executable=python_executable)
        payload = case.to_summary_mapping()
        payload["command"] = command
        if execution is None:
            payload["status"] = "planned"
            payload["returncode"] = None
            payload["duration_seconds"] = None
            payload["reused_from_report"] = False
        else:
            payload["status"] = execution.status
            payload["returncode"] = execution.returncode
            payload["duration_seconds"] = execution.duration_seconds
            payload["reused_from_report"] = execution.reused_from_report
            payload["child_artifacts"] = dict(execution.child_artifacts)
        if execution is None:
            payload["child_artifacts"] = {}
        cases_payload.append(payload)

    return {
        "schema_version": "regional_lab_report_v2",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "lab_id": cfg.lab_id,
        "config_path": str(cfg.config_path),
        "site_catalog_path": str(cfg.catalog.path),
        "output_root": str(cfg.output_root),
        "execute": bool(cfg.execute),
        "continue_on_error": bool(cfg.continue_on_error),
        "resume_from_report": bool(cfg.resume_from_report),
        "skip_completed_cases": bool(cfg.skip_completed_cases),
        "selected_site_count": len(selected_sites),
        "planned_case_count": len(planned_cases),
        "skipped_case_count": len(skipped_cases),
        "executed_case_count": len(executed_fresh),
        "reused_case_count": len(reused),
        "successful_case_count": len(
            [item for item in executions if item.status in {"ok", "skipped_existing_ok"}]
        ),
        "failed_case_count": len(failed),
        "pending_case_count": pending_count,
        "all_passed": len(failed) == 0 and pending_count == 0,
        "selected_sites": [site.to_summary_mapping() for site in selected_sites],
        "cases": cases_payload,
        "skipped_cases": [case.to_summary_mapping() for case in skipped_cases],
        "synthesis_paths": dict(synthesis_paths),
    }


def _load_previous_ok_case_ids(report_path: Path) -> set[str]:
    """Return case identifiers already marked as successful in one previous report."""
    if not report_path.is_file():
        return set()
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    cases = payload.get("cases", [])
    if not isinstance(cases, list):
        return set()
    out: set[str] = set()
    for case in cases:
        if not isinstance(case, Mapping):
            continue
        case_id = _normalize_text(case.get("case_id"))
        status = _normalize_text(case.get("status"))
        if case_id is None or status is None:
            continue
        if status.lower() in {"ok", "skipped_existing_ok"}:
            out.add(case_id)
    return out
