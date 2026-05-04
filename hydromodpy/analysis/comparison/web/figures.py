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
        "Cartes, triptyques, differences et series temporelles de charge.",
        20,
    ),
    "fluxes": (
        "Flux, drainage et suintement",
        "Flux de sortie, drainage, surface excess, seepage et cartes associees.",
        30,
    ),
    "budgets": (
        "Bilans et budgets",
        "Diagnostics de budget et bilans par solveur.",
        40,
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
        category_id = _figure_category_id(item)
        grouped.setdefault(category_id, []).append(item)
    categories: list[FigureCategory] = []
    for category_id, items in grouped.items():
        title, description, priority = _CATEGORY_META.get(
            category_id, _CATEGORY_META["other"]
        )
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
    return [item for item in figures if _figure_category_id(item) == "configuration"]


def _figure_category_id(item: Mapping[str, Any]) -> str:
    text = _figure_text(item)
    if any(token in text for token in ("case_configuration", "configuration")):
        return "configuration"
    if any(
        token in text
        for token in (
            "budget",
            "mass_balance",
            "storage",
            "water_balance",
        )
    ):
        return "budgets"
    if any(
        token in text
        for token in (
            "comparable_outflow",
            "flux",
            "outflow",
            "drain",
            "seepage",
            "surface_excess",
            "recharge",
            "discharge",
        )
    ):
        return "fluxes"
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


__all__ = ("FigureCategory", "categorize_figures", "configuration_figures")
