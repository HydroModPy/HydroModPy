"""Figure categorization for static comparison web reports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FigureCategory:
    """A display category for comparison report figures."""

    category_id: str
    title: str
    description: str
    priority: int
    figures: list[dict[str, Any]]


_CATEGORY_META: dict[str, tuple[str, str, int]] = {
    "configuration": (
        "Configuration",
        "Support de calcul, topographie, limites, points et forcages.",
        10,
    ),
    "heads": (
        "Charges hydrauliques",
        "Un champ de charge representatif et les chroniques ponctuelles.",
        20,
    ),
    "water_balance": (
        "Stockage et bilan externe",
        "Stockage global et sommes d'entrees/sorties externes.",
        30,
    ),
    "networks": (
        "Reseaux et diagnostics spatiaux",
        "Hydrographie, reseau actif simule et diagnostics geometriques.",
        50,
    ),
    "performance": (
        "Performance",
        "Temps de calcul et indicateurs de cout numerique.",
        60,
    ),
    "other": (
        "Autres figures",
        "Figures non classees par les regles standards.",
        90,
    ),
}


def categorize_figures(figures: list[dict[str, Any]]) -> list[FigureCategory]:
    """Group figures into stable semantic categories for the HTML report."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in sorted(figures, key=_figure_sort_key):
        if not include_in_comparison_report(item):
            continue
        category_id = _figure_category_id(item)
        grouped.setdefault(category_id, []).append(item)
    categories: list[FigureCategory] = []
    for category_id, items in grouped.items():
        title, description, priority = _CATEGORY_META.get(category_id, _CATEGORY_META["other"])
        categories.append(
            FigureCategory(
                category_id=category_id,
                title=title,
                description=description,
                priority=priority,
                figures=items,
            )
        )
    return sorted(categories, key=lambda item: (item.priority, item.title))


def configuration_figures(figures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return figures that describe the case setup rather than solver results."""
    return [
        item
        for item in figures
        if include_in_comparison_report(item) and _figure_category_id(item) == "configuration"
    ]


def include_in_comparison_report(item: Mapping[str, Any]) -> bool:
    """Return whether a figure belongs in the compact comparison HTML view."""
    text = _figure_text(item)
    kind = str(item.get("kind", "")).lower()
    observable = str(item.get("observable", "")).lower()
    if "case_configuration" in text:
        return True
    if (
        kind == "fine_raster_map_comparison" and observable == "head_map_wet_year1"
    ) or (
        "head_map_wet_year1" in text and "fine_raster_map_comparison" in text
    ):
        return True
    if (kind == "timeseries" and observable.startswith("head_") and observable.endswith("_series")) or (
        name := Path(str(item.get("path", ""))).name.lower()
    ).startswith("head_") and name.endswith("__timeseries.png"):
        return True
    if kind in {"storage_comparison_dashboard", "total_inputs_outputs_dashboard"}:
        return True
    if any(
        token in text
        for token in (
            "storage_comparison_dashboard",
            "total_inputs_outputs_dashboard",
        )
    ):
        return True
    return False


def _figure_category_id(item: Mapping[str, Any]) -> str:
    text = _figure_text(item)
    if any(token in text for token in ("case_configuration", "configuration")):
        return "configuration"
    if any(
        token in text
        for token in (
            "storage_comparison",
            "total_inputs_outputs",
            "total_inputs",
            "total_outputs",
        )
    ):
        return "water_balance"
    if any(
        token in text
        for token in (
            "head",
            "watertable",
            "piezometric",
            "charge",
            "hydraulic_head",
        )
    ):
        return "heads"
    if any(
        token in text
        for token in (
            "hydrographic",
            "network",
            "active_network",
            "distance",
            "overlap",
        )
    ):
        return "networks"
    if any(token in text for token in ("execution", "runtime", "wall_time", "time_comparison")):
        return "performance"
    return "other"


def _figure_text(item: Mapping[str, Any]) -> str:
    parts = [
        Path(str(item.get("path", ""))).name,
        str(item.get("kind", "")),
        str(item.get("observable", "")),
    ]
    return " ".join(parts).lower()


def _figure_sort_key(item: Mapping[str, Any]) -> tuple[int, str]:
    name = Path(str(item.get("path", ""))).name
    score = 100
    if "case_configuration" in name:
        score = 0
    elif "dashboard" in name:
        score = 5
    elif "comparable_outflow" in name:
        score = 8
    elif "fine_raster_triptych" in name:
        score = 10
    elif "triptych" in name:
        score = 20
    elif "fine_raster_difference" in name:
        score = 30
    elif "difference" in name:
        score = 40
    elif "timeseries" in name:
        score = 50
    elif "diagnostics" in name:
        score = 60
    return score, name


__all__ = (
    "FigureCategory",
    "categorize_figures",
    "configuration_figures",
    "include_in_comparison_report",
)
