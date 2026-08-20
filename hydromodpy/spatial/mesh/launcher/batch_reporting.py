"""Manifest and summary contracts for the mesh-catchment batch launcher."""

from __future__ import annotations

import csv
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MeshCatchmentBatchResultRow:
    """One typed manifest row summarizing one outlet execution."""

    outlet_id: str
    catch_name: str
    status: str
    x_outlet: float
    y_outlet: float
    output_mesh: str = ""
    output_summary_json: str = ""
    output_figure: str = ""
    output_figure_regional: str = ""
    error: str = ""

    def to_mapping(self) -> dict[str, Any]:
        """Serialize one result row to the CSV/JSON-friendly legacy payload."""
        return {
            "outlet_id": self.outlet_id,
            "catch_name": self.catch_name,
            "status": self.status,
            "x_outlet": float(self.x_outlet),
            "y_outlet": float(self.y_outlet),
            "output_mesh": self.output_mesh,
            "output_summary_json": self.output_summary_json,
            "output_figure": self.output_figure,
            "output_figure_regional": self.output_figure_regional,
            "error": self.error,
        }


@dataclass(frozen=True)
class MeshCatchmentBatchSummary:
    """Typed summary returned after one batch run finishes."""

    manifest_csv: str
    results: tuple[MeshCatchmentBatchResultRow, ...]

    def to_mapping(self) -> dict[str, Any]:
        """Serialize one batch summary to the public launcher payload."""
        succeeded = [row for row in self.results if row.status == "ok"]
        failed = [row for row in self.results if row.status != "ok"]
        return {
            "mode": "batch",
            "summary_schema_version": "mesh_catchment_batch_v1",
            "manifest_csv": self.manifest_csv,
            "outlets_total": int(len(self.results)),
            "outlets_succeeded": int(len(succeeded)),
            "outlets_failed": int(len(failed)),
            "results": [row.to_mapping() for row in self.results],
        }


def write_mesh_catchment_batch_manifest(
    path: Path,
    rows: Sequence[MeshCatchmentBatchResultRow],
) -> None:
    """Persist the current batch progress to one CSV manifest."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "outlet_id",
        "catch_name",
        "status",
        "x_outlet",
        "y_outlet",
        "output_mesh",
        "output_summary_json",
        "output_figure",
        "output_figure_regional",
        "error",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            payload = row.to_mapping()
            writer.writerow({name: payload.get(name, "") for name in fieldnames})


__all__ = [
    "MeshCatchmentBatchResultRow",
    "MeshCatchmentBatchSummary",
    "write_mesh_catchment_batch_manifest",
]
