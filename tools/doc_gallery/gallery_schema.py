"""Shared schema objects for the doc gallery inventory."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


Formatter = Callable[[Any], str]


@dataclass(frozen=True, slots=True)
class GalleryMetricSpec:
    """Describe one metric to expose on a gallery case page."""

    label: str
    key: str
    formatter: Formatter


@dataclass(frozen=True, slots=True)
class GalleryImageAsset:
    """Describe one image produced or copied for the gallery."""

    filename: str
    caption: str
    alt_text: str
    source_path: str | None = None


@dataclass(frozen=True, slots=True)
class GalleryCaseSpec:
    """Full manifest entry for one illustrated capability case."""

    slug: str
    title: str
    category: str
    deck: str
    summary: str
    what_it_shows: tuple[str, ...]
    reproduction_command: str
    source_paths: tuple[str, ...]
    generator: str
    image_assets: tuple[GalleryImageAsset, ...]
    metric_specs: tuple[GalleryMetricSpec, ...] = ()
    case_setup: tuple[str, ...] = ()
    key_parameters: tuple[str, ...] = ()
    how_to_read: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()
    reference_highlights: tuple[str, ...] = ()
    equations_rst: tuple[str, ...] = ()
    walkthrough_doc: str | None = None
    walkthrough_title: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GalleryCategorySpec:
    """High-level grouping shown on the gallery landing pages."""

    slug: str
    title: str
    deck: str
    intro: str
    guide_doc: str | None = None
    guide_title: str | None = None


def _format_int(value: Any) -> str:
    return f"{int(value)}"


def _format_float(unit: str, *, precision: int = 4) -> Formatter:
    def _render(value: Any) -> str:
        return f"{float(value):.{precision}f} {unit}".strip()

    return _render


def _format_scientific(unit: str, *, precision: int = 2) -> Formatter:
    def _render(value: Any) -> str:
        return f"{float(value):.{precision}e} {unit}".strip()

    return _render


CATEGORY_SPECS: dict[str, GalleryCategorySpec] = {
    "mesh": GalleryCategorySpec(
        slug="mesh",
        title="Mesh Gallery",
        deck="Static mesh and geology illustrations produced from versioned bundle inputs.",
        intro=(
            "These cases focus on the geometry side of HydroModPy: bundle reading, "
            "geology overlays, river constraints, and compact mesh summaries."
        ),
    ),
    "validation": GalleryCategorySpec(
        slug="validation",
        title="Validation Benchmarks",
        deck="Analytical and semi-analytical comparisons rendered as reproducible teaching figures.",
        intro=(
            "These cases show how HydroModPy validates numerical behaviour against "
            "lightweight analytical references, with metrics that stay readable in a doc page."
        ),
        guide_doc="getting_started/reading-results-pages",
        guide_title="How to read gallery, comparison, and validation pages",
    ),
    "calibration": GalleryCategorySpec(
        slug="calibration",
        title="Calibration Benchmarks",
        deck="Synthetic inverse problems used to inspect calibration workflows, search methods, and timing diagnostics.",
        intro=(
            "These cases focus on inverse modelling rather than forward validation: "
            "synthetic observations are generated first, then recovered with one or more "
            "calibration strategies on the same solver family."
        ),
        guide_doc="getting_started/reading-results-pages",
        guide_title="How to read gallery, comparison, and validation pages",
    ),
    "geographic": GalleryCategorySpec(
        slug="geographic",
        title="Data Overview",
        deck="Pre-solver watershed and hydrography figures that explain how one domain is assembled before solving.",
        intro=(
            "These cases group the `data-overview` workflow: watershed context, DEM-based "
            "views, and the local data overlays that feed later modelling steps."
        ),
        guide_doc="getting_started/data-overview-walkthrough",
        guide_title="Data Overview walkthrough",
    ),
    "geometry": GalleryCategorySpec(
        slug="geometry",
        title="Geometry Diagnostics",
        deck="Vector-only views of catchment geometry, hydrography, and geology layers.",
        intro=(
            "These cases focus on geometry independent of any mesh: basin outlines, hydro networks, "
            "and geological units clipped to the same domain."
        ),
    ),
    "hydraulic_properties": GalleryCategorySpec(
        slug="hydraulic_properties",
        title="Hydraulic Properties",
        deck="Hydraulic conductivity and storage parameterizations rendered on synthetic and geology-driven supports.",
        intro=(
            "These cases focus on how HydroModPy turns field definitions into mesh-ready "
            "properties: inline units, heterogeneous zoning, depth profiles, and geology-driven transfers."
        ),
    ),
    "method_comparison": GalleryCategorySpec(
        slug="method_comparison",
        title="Method Comparison",
        deck="Reusable solver comparisons built from committed run folders on shared supports.",
        intro=(
            "These cases compare multiple modelling methods on the same saved support. "
            "The figures stay lightweight enough for the docs while still exposing map-wide errors."
        ),
        guide_doc="getting_started/reading-results-pages",
        guide_title="How to read gallery, comparison, and validation pages",
    ),
    "code_comparison": GalleryCategorySpec(
        slug="code_comparison",
        title="Code Comparison",
        deck="Synthetic solver-to-solver benchmarks with no analytical truth claim.",
        intro=(
            "These pages compare code families on the same controlled synthetic setups. "
            "They focus on flux partitioning, storage response, and boundary-condition behaviour "
            "when the goal is cross-code diagnosis rather than validation against an analytical reference."
        ),
        guide_doc="getting_started/reading-results-pages",
        guide_title="How to read gallery, comparison, and validation pages",
    ),
    "simulation": GalleryCategorySpec(
        slug="simulation",
        title="Simulation Workflows",
        deck="End-to-end solver runs rendered as stable documentation artifacts.",
        intro=(
            "These cases show complete launcher workflows: preprocessing, solver execution, "
            "transport when relevant, and the compact figures used to inspect the result."
        ),
        guide_doc="getting_started/simulation-walkthrough",
        guide_title="Simulation walkthrough",
    ),
}


__all__ = [
    "CATEGORY_SPECS",
    "Formatter",
    "GalleryCaseSpec",
    "GalleryCategorySpec",
    "GalleryImageAsset",
    "GalleryMetricSpec",
    "_format_float",
    "_format_int",
    "_format_scientific",
]
