from __future__ import annotations

import csv
import json
from pathlib import Path


PILOT_DIR = Path(__file__).resolve().parent
CATALOG_PATH = PILOT_DIR / "site_catalog_pilot_20.csv"
REPORT_PATH = (
    PILOT_DIR
    / "outputs"
    / "regional_pilot_2026_04_12_execute"
    / "regional_lab_report.json"
)


def _merge_tags(raw_tags: str, *extra_tags: str) -> str:
    items = [item.strip() for item in str(raw_tags).split(";") if item.strip()]
    seen = {item.lower() for item in items}
    for tag in extra_tags:
        lowered = tag.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        items.append(tag)
    return ";".join(items)


def _remove_tag(raw_tags: str, tag_to_remove: str) -> str:
    lowered = str(tag_to_remove).strip().lower()
    items = [
        item.strip()
        for item in str(raw_tags).split(";")
        if item.strip() and item.strip().lower() != lowered
    ]
    return ";".join(items)


def _ensure_field(fieldnames: list[str], name: str) -> None:
    if name not in fieldnames:
        fieldnames.append(name)


def main() -> None:
    if not REPORT_PATH.is_file():
        raise FileNotFoundError(f"Regional-lab execute report not found: {REPORT_PATH}")

    with CATALOG_PATH.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    for field_name in (
        "runtime_smoke_status",
        "runtime_smoke_checked_at_utc",
        "runtime_smoke_recipe_id",
        "runtime_smoke_case_id",
        "runtime_smoke_wall_time_seconds",
        "runtime_smoke_metrics_json",
        "runtime_smoke_boussinesq_summary_json",
        "runtime_smoke_note",
    ):
        _ensure_field(fieldnames, field_name)

    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    generated_at = str(payload.get("generated_at_utc", "")).strip()
    cases = payload.get("cases", [])
    if not isinstance(cases, list):
        raise ValueError("regional_lab_report.json does not expose a valid cases list")

    latest_simulation_case_by_site: dict[str, dict[str, object]] = {}
    for case in cases:
        if not isinstance(case, dict):
            continue
        if str(case.get("launcher", "")).strip() != "simulation":
            continue
        site_id = str(case.get("site_id", "")).strip()
        if site_id == "":
            continue
        latest_simulation_case_by_site[site_id] = case

    updated_count = 0
    for row in rows:
        site_id = str(row.get("site_id", "")).strip()
        case = latest_simulation_case_by_site.get(site_id)
        if case is None:
            continue

        child_artifacts = case.get("child_artifacts")
        if not isinstance(child_artifacts, dict):
            child_artifacts = {}
        status = str(case.get("status", "")).strip()
        row["runtime_smoke_status"] = status
        row["runtime_smoke_checked_at_utc"] = generated_at
        row["runtime_smoke_recipe_id"] = str(case.get("recipe_id", "")).strip()
        row["runtime_smoke_case_id"] = str(case.get("case_id", "")).strip()
        wall_time = child_artifacts.get("child_wall_time_seconds", case.get("duration_seconds"))
        row["runtime_smoke_wall_time_seconds"] = "" if wall_time is None else str(wall_time)
        row["runtime_smoke_metrics_json"] = str(
            child_artifacts.get("child_metrics_json", "")
        ).strip()
        row["runtime_smoke_boussinesq_summary_json"] = str(
            child_artifacts.get("child_boussinesq_summary_json", "")
        ).strip()
        note = str(child_artifacts.get("child_artifact_error_message", "")).strip()
        row["runtime_smoke_note"] = note

        if status in {"ok", "skipped_existing_ok"}:
            row["tags"] = _remove_tag(row.get("tags", ""), "runtime_smoke_failed")
            row["tags"] = _merge_tags(row.get("tags", ""), "runtime_smoke_ready")
        elif status == "failed":
            row["tags"] = _remove_tag(row.get("tags", ""), "runtime_smoke_ready")
            row["tags"] = _merge_tags(row.get("tags", ""), "runtime_smoke_failed")
        updated_count += 1

    with CATALOG_PATH.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})

    print(f"Updated runtime smoke status for {updated_count} sites")
    print(f"Catalog synchronized: {CATALOG_PATH}")


if __name__ == "__main__":
    main()
