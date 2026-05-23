"""Tabular CSV/JSONL exports for site-selection results."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from hydromodpy.spatial.site_selection.delineation import DelineatedCatchment
from hydromodpy.spatial.site_selection.schemas import (
    SELECTED_SITES_FIELDS,
    site_record_from_catchment,
)
from hydromodpy.spatial.site_selection.selection import SelectionDecision


def write_selected_sites_csv(
    path: str | Path,
    catchments: Iterable[DelineatedCatchment],
    *,
    selection_id: str,
    region_id: str = "",
) -> Path:
    """Write ``selected_sites.csv``."""

    rows = [
        site_record_from_catchment(
            catchment,
            selection_id=selection_id,
            region_id=region_id,
        )
        for catchment in catchments
    ]
    return write_csv(path, rows, fieldnames=SELECTED_SITES_FIELDS)


def write_regional_lab_sites_csv(
    path: str | Path,
    catchments: Iterable[DelineatedCatchment],
    *,
    selection_id: str,
    region_id: str = "",
) -> Path:
    """Write a CSV directly consumable by the regional-lab catalog loader."""

    return write_selected_sites_csv(
        path,
        catchments,
        selection_id=selection_id,
        region_id=region_id,
    )


def write_decisions_jsonl(path: str | Path, decisions: Iterable[SelectionDecision]) -> Path:
    """Write selection decisions as JSON Lines."""

    return write_jsonl(path, [decision.to_record() for decision in decisions])


def write_criteria_components_jsonl(
    path: str | Path,
    components: Iterable[object],
) -> Path:
    """Write criteria components as JSON Lines."""

    rows = [
        component.to_record() if hasattr(component, "to_record") else dict(component)
        for component in components
    ]
    return write_jsonl(path, rows)


def write_csv(
    path: str | Path,
    rows: Iterable[Mapping[str, Any]],
    *,
    fieldnames: list[str] | None = None,
) -> Path:
    """Write a CSV file with stable field ordering when provided."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    materialized = [dict(row) for row in rows]
    names = fieldnames or _fieldnames_from_rows(materialized)
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=names, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(materialized)
    return destination


def write_jsonl(path: str | Path, rows: Iterable[Mapping[str, Any]]) -> Path:
    """Write mappings as JSON Lines."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), ensure_ascii=True, sort_keys=True) + "\n")
    return destination


def _fieldnames_from_rows(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["site_id"]
    names: list[str] = []
    for row in rows:
        for key in row:
            if key not in names:
                names.append(key)
    return names


__all__ = [
    "write_criteria_components_jsonl",
    "write_csv",
    "write_decisions_jsonl",
    "write_jsonl",
    "write_regional_lab_sites_csv",
    "write_selected_sites_csv",
]
