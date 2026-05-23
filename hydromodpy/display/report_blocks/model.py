"""Small data contracts for reusable static report blocks."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

DetailLevel = Literal["compact", "standard", "audit"]
BlockStatus = Literal["available", "partial", "empty", "not_applicable"]


@dataclass(frozen=True)
class ReportMetric:
    """One labelled value displayed in a report block."""

    label: str
    value: Any
    unit: str = ""
    note: str = ""


@dataclass(frozen=True)
class ReportFigure:
    """One figure expected by a report block."""

    figure_id: str
    title: str
    path: Path | None
    caption: str = ""
    required: bool = True

    @property
    def available(self) -> bool:
        """Return whether the figure path exists on disk."""
        return self.path is not None and self.path.exists()


@dataclass(frozen=True)
class ReportTable:
    """One flat table displayed in a report block."""

    table_id: str
    title: str
    columns: tuple[tuple[str, str], ...]
    rows: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    empty_message: str = "No rows."


@dataclass(frozen=True)
class ReportBlock:
    """Reusable report block with metrics, figures and tables."""

    block_id: str
    title: str
    level: DetailLevel = "standard"
    status: BlockStatus = "available"
    lead: str = ""
    metrics: tuple[ReportMetric, ...] = field(default_factory=tuple)
    figures: tuple[ReportFigure, ...] = field(default_factory=tuple)
    tables: tuple[ReportTable, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_applicable(self) -> bool:
        """Return whether the block applies to the current workflow."""
        return self.status != "not_applicable"
