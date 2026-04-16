"""Declarative manifest for the illustrated capability gallery."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from .mesh_case_registry import (
    MESH_GALLERY_SCALE_ORDER,
    iter_mesh_case_json_paths,
    load_mesh_case_metadata,
)


Formatter = Callable[[Any], str]
_MANIFESTS_DIR = Path(__file__).resolve().parent / "manifests"


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


def _coerce_str_tuple(value: Any, *, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raise TypeError(f"{field_name} must be a sequence of strings, not one string.")
    return tuple(str(item) for item in value)


def _metric_formatter_from_payload(payload: Any) -> Formatter:
    if payload == "int":
        return _format_int
    if not isinstance(payload, dict):
        raise TypeError("metric formatter payload must be 'int' or a mapping.")

    kind = str(payload.get("kind", "")).strip().lower()
    unit = str(payload.get("unit", "")).strip()
    if kind == "float":
        return _format_float(unit, precision=int(payload.get("precision", 4)))
    if kind == "scientific":
        return _format_scientific(unit, precision=int(payload.get("precision", 2)))
    raise ValueError(f"Unsupported metric formatter kind: {kind!r}")


def _load_json_gallery_case_specs(manifest_name: str) -> tuple[GalleryCaseSpec, ...]:
    """Load one small declarative gallery inventory from ``tools/doc_gallery/manifests``."""

    manifest_path = _MANIFESTS_DIR / manifest_name
    manifest_repo_path = (Path("tools") / "doc_gallery" / "manifests" / manifest_name).as_posix()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    defaults = dict(payload.get("defaults", {}))
    raw_cases = payload.get("cases", ())
    if not isinstance(raw_cases, list):
        raise TypeError(f"{manifest_path.as_posix()} must define a top-level 'cases' list.")

    specs: list[GalleryCaseSpec] = []
    for raw_case in raw_cases:
        if not isinstance(raw_case, dict):
            raise TypeError(f"{manifest_path.as_posix()} case entries must be mappings.")
        merged_case = {**defaults, **raw_case}
        default_metadata = dict(defaults.get("metadata", {}))
        merged_metadata = {**default_metadata, **dict(raw_case.get("metadata", {}))}
        merged_case["metadata"] = merged_metadata

        image_assets = tuple(
            GalleryImageAsset(
                filename=str(asset["filename"]),
                caption=str(asset["caption"]),
                alt_text=str(asset["alt_text"]),
                source_path=(
                    str(asset["source_path"])
                    if asset.get("source_path")
                    else None
                ),
            )
            for asset in merged_case.get("image_assets", ())
        )
        metric_specs = tuple(
            GalleryMetricSpec(
                label=str(metric["label"]),
                key=str(metric["key"]),
                formatter=_metric_formatter_from_payload(metric["formatter"]),
            )
            for metric in merged_case.get("metric_specs", ())
        )
        specs.append(
            GalleryCaseSpec(
                slug=str(merged_case["slug"]),
                title=str(merged_case["title"]),
                category=str(merged_case["category"]),
                deck=str(merged_case["deck"]),
                summary=str(merged_case["summary"]),
                what_it_shows=_coerce_str_tuple(
                    merged_case.get("what_it_shows", ()),
                    field_name="what_it_shows",
                ),
                reproduction_command=str(merged_case["reproduction_command"]),
                source_paths=(
                    manifest_repo_path,
                    *_coerce_str_tuple(
                        merged_case.get("source_paths", ()),
                        field_name="source_paths",
                    ),
                ),
                generator=str(merged_case["generator"]),
                image_assets=image_assets,
                metric_specs=metric_specs,
                case_setup=_coerce_str_tuple(
                    merged_case.get("case_setup", ()),
                    field_name="case_setup",
                ),
                key_parameters=_coerce_str_tuple(
                    merged_case.get("key_parameters", ()),
                    field_name="key_parameters",
                ),
                how_to_read=_coerce_str_tuple(
                    merged_case.get("how_to_read", ()),
                    field_name="how_to_read",
                ),
                next_steps=_coerce_str_tuple(
                    merged_case.get("next_steps", ()),
                    field_name="next_steps",
                ),
                reference_highlights=_coerce_str_tuple(
                    merged_case.get("reference_highlights", ()),
                    field_name="reference_highlights",
                ),
                equations_rst=_coerce_str_tuple(
                    merged_case.get("equations_rst", ()),
                    field_name="equations_rst",
                ),
                walkthrough_doc=(
                    str(merged_case["walkthrough_doc"])
                    if merged_case.get("walkthrough_doc")
                    else None
                ),
                walkthrough_title=(
                    str(merged_case["walkthrough_title"])
                    if merged_case.get("walkthrough_title")
                    else None
                ),
                metadata=merged_metadata,
            )
        )
    return tuple(specs)


_MESH_GALLERY_METRIC_SPECS = (
    GalleryMetricSpec("Nodes", "node_count", _format_int),
    GalleryMetricSpec("Cells", "cell_count", _format_int),
    GalleryMetricSpec("River edges", "river_edge_count", _format_int),
    GalleryMetricSpec("Geology interfaces", "geology_interface_edge_count", _format_int),
)

_HYDRAULIC_PROPERTY_SQUARE_METRIC_SPECS = (
    GalleryMetricSpec("Structured cells", "structured_cell_count", _format_int),
    GalleryMetricSpec("Triangular cells", "triangular_cell_count", _format_int),
    GalleryMetricSpec("Minimum K", "k_min_m_per_day", _format_float("m/day", precision=1)),
    GalleryMetricSpec("Maximum K", "k_max_m_per_day", _format_float("m/day", precision=1)),
)

_HYDRAULIC_PROPERTY_GEOLOGY_METRIC_SPECS = (
    GalleryMetricSpec("Polygons", "n_polygons", _format_int),
    GalleryMetricSpec("Unique zones", "n_unique_zones", _format_int),
    GalleryMetricSpec("Mesh cells", "n_mesh_cells", _format_int),
    GalleryMetricSpec("Maximum K", "property_max", _format_scientific("m/s")),
)

_HYDRAULIC_PROPERTY_IRREGULAR_METRIC_SPECS = (
    GalleryMetricSpec("Structured cells", "structured_cell_count", _format_int),
    GalleryMetricSpec("Irregular cells", "irregular_cell_count", _format_int),
    GalleryMetricSpec("Minimum K", "k_min_m_per_day", _format_float("m/day", precision=1)),
    GalleryMetricSpec("Maximum K", "k_max_m_per_day", _format_float("m/day", precision=1)),
)

_HYDRAULIC_PROPERTY_DEPTH_METRIC_SPECS = (
    GalleryMetricSpec("Mesh cells", "mesh_cell_count", _format_int),
    GalleryMetricSpec("Surface K", "k_surface_m_per_day", _format_float("m/day", precision=1)),
    GalleryMetricSpec("Deep K", "k_deep_m_per_day", _format_float("m/day", precision=1)),
    GalleryMetricSpec("Depth", "depth_m", _format_float("m", precision=0)),
)

_MESH_DIAGNOSTIC_METRIC_SPECS = (
    GalleryMetricSpec("Triangle cells", "triangle_cell_count", _format_int),
    GalleryMetricSpec("Min angle (p05)", "min_angle_p05_deg", _format_float("deg", precision=1)),
    GalleryMetricSpec("Aspect ratio (p95)", "aspect_ratio_p95", _format_float("", precision=2)),
    GalleryMetricSpec("Area (p05)", "area_p05_m2", _format_scientific("m2", precision=2)),
)

_GEOMETRY_CONSTRAINT_METRIC_SPECS = (
    GalleryMetricSpec("Boundary area", "boundary_area_km2", _format_float("km2", precision=1)),
    GalleryMetricSpec("River length", "river_length_km", _format_float("km", precision=1)),
    GalleryMetricSpec("Geology units", "geology_unit_count", _format_int),
)

_GEOMETRY_TOPO_METRIC_SPECS = (
    GalleryMetricSpec("Boundary area", "boundary_area_km2", _format_float("km2", precision=1)),
    GalleryMetricSpec("River length", "river_length_km", _format_float("km", precision=1)),
    GalleryMetricSpec("DEM min", "dem_min_m", _format_float("m", precision=0)),
    GalleryMetricSpec("DEM max", "dem_max_m", _format_float("m", precision=0)),
)

_MESH_CONSTRAINT_BALANCE_METRIC_SPECS = (
    GalleryMetricSpec("River edges", "river_edge_count", _format_int),
    GalleryMetricSpec("Geology interfaces", "geology_interface_edge_count", _format_int),
    GalleryMetricSpec("Boundary edges", "boundary_edge_count", _format_int),
    GalleryMetricSpec("Cells", "cell_count", _format_int),
)

_MESH_RESOLUTION_METRIC_SPECS = (
    GalleryMetricSpec("Cells", "cell_count", _format_int),
    GalleryMetricSpec("Area p10", "area_p10_m2", _format_scientific("m2", precision=2)),
    GalleryMetricSpec("Area median", "area_median_m2", _format_scientific("m2", precision=2)),
    GalleryMetricSpec("Area p90", "area_p90_m2", _format_scientific("m2", precision=2)),
)

_MESH_ZOOM_METRIC_SPECS = (
    GalleryMetricSpec("River edges", "river_edge_count", _format_int),
    GalleryMetricSpec("Interface edges", "interface_edge_count", _format_int),
    GalleryMetricSpec("Zoom span", "zoom_span_m", _format_float("m", precision=0)),
)

_GEOMETRY_INDICATOR_METRIC_SPECS = (
    GalleryMetricSpec("Boundary area", "boundary_area_km2", _format_float("km2", precision=1)),
    GalleryMetricSpec("Mean slope", "slope_mean_deg", _format_float("deg", precision=1)),
    GalleryMetricSpec("Slope p90", "slope_p90_deg", _format_float("deg", precision=1)),
    GalleryMetricSpec("DEM range", "dem_range_m", _format_float("m", precision=0)),
)

_REGIONAL_LAB_METRIC_SPECS = (
    GalleryMetricSpec("Selected sites", "selected_site_count", _format_int),
    GalleryMetricSpec("Planned cases", "planned_case_count", _format_int),
    GalleryMetricSpec("Skipped cases", "skipped_case_count", _format_int),
    GalleryMetricSpec("Pending cases", "pending_case_count", _format_int),
)

_REGIONAL_LAB_RECIPE_METRIC_SPECS = (
    GalleryMetricSpec("Candidate sites", "candidate_site_count", _format_int),
    GalleryMetricSpec("Planned cases", "planned_case_count", _format_int),
    GalleryMetricSpec("Coverage gaps", "skipped_case_count", _format_int),
    GalleryMetricSpec("Pending cases", "pending_case_count", _format_int),
)


def build_repo_mesh_gallery_case_specs(*, repo_root=None) -> tuple[GalleryCaseSpec, ...]:
    """Discover versioned mesh-gallery cases imported under ``examples/mesh_gallery``."""

    scale_rank = {scale: index for index, scale in enumerate(MESH_GALLERY_SCALE_ORDER)}
    optional_metadata_keys = (
        "case_family_key",
        "case_family_label",
        "case_family_order",
        "comparison_group",
        "comparison_group_title",
        "site_tabs_group_key",
        "site_tabs_group_title",
        "site_tabs_label",
        "site_tabs_order",
        "source_results_family_dir",
        "source_results_manifest_path",
    )
    discovered_specs: list[tuple[tuple[Any, ...], GalleryCaseSpec]] = []
    discovery_kwargs = {} if repo_root is None else {"repo_root": repo_root}
    for case_json_path in iter_mesh_case_json_paths(**discovery_kwargs):
        payload = load_mesh_case_metadata(case_json_path)
        slug = str(payload["slug"])
        title = str(payload["title"])
        scale = str(payload["scale"])
        scale_label = str(payload.get("scale_label", scale))
        outlet_id = str(payload["outlet_id"])
        variant = str(payload["variant"])
        variant_label = str(payload.get("variant_label", variant))
        family_order = int(payload.get("case_family_order", scale_rank.get(scale, 999)))
        site_tabs_order = int(payload.get("site_tabs_order", 999))
        preferred_doc_figure_path = str(payload.get("preferred_doc_figure_path", "")).strip()
        preferred_doc_regional_figure_path = str(
            payload.get("preferred_doc_regional_figure_path", "")
        ).strip()
        image_assets = []
        if preferred_doc_figure_path:
            image_assets.append(
                GalleryImageAsset(
                    filename=f"{slug}_overview.png",
                    caption=str(
                        payload.get(
                            "image_caption",
                            "Original mesh figure copied from the imported meshing run.",
                        )
                    ),
                    alt_text=str(payload.get("image_alt_text", f"{title} overview")),
                    source_path=preferred_doc_figure_path,
                )
            )
            if preferred_doc_regional_figure_path:
                image_assets.append(
                    GalleryImageAsset(
                        filename=f"{slug}_regional.png",
                        caption=str(
                            payload.get(
                                "regional_image_caption",
                                "Regional framing figure copied from the imported meshing run.",
                            )
                        ),
                        alt_text=str(payload.get("regional_image_alt_text", f"{title} regional context")),
                        source_path=preferred_doc_regional_figure_path,
                    )
                )
        else:
            image_assets.append(
                GalleryImageAsset(
                    filename=f"{slug}_overview.png",
                    caption=str(
                        payload.get(
                            "image_caption",
                            f"Mesh overview rendered from the versioned bundle shipped with `{slug}`.",
                        )
                    ),
                    alt_text=str(payload.get("image_alt_text", f"{title} overview")),
                )
            )
        family_key = str(payload.get("case_family_key", "")).strip()
        family_label = str(payload.get("case_family_label", "")).strip()
        comparison_group = str(payload.get("comparison_group", "")).strip()
        comparison_group_title = str(payload.get("comparison_group_title", "")).strip()
        if comparison_group == "":
            if family_key != "":
                comparison_group = f"{family_key}::outlet::{outlet_id}"
                comparison_group_title = (
                    comparison_group_title
                    or f"{family_label or scale_label}, outlet {outlet_id}"
                )
            else:
                comparison_group = f"{scale}::outlet::{outlet_id}"
                comparison_group_title = (
                    comparison_group_title
                    or f"{scale_label}, outlet {outlet_id}"
                )

        metadata = {
            "scale": scale,
            "scale_label": scale_label,
            "variant": variant,
            "variant_label": variant_label,
            "outlet_id": outlet_id,
            "comparison_group": comparison_group,
            "comparison_group_title": comparison_group_title,
            "config_path": str(payload["config_path"]),
            "constraints_mode": str(payload.get("constraints_mode", "")),
        }
        for key in optional_metadata_keys:
            if key in payload:
                metadata[key] = payload[key]

        discovered_specs.append(
            (
                (
                    family_order,
                    scale_rank.get(scale, 999),
                    site_tabs_order,
                    int(outlet_id) if outlet_id.isdigit() else outlet_id,
                    slug,
                ),
                GalleryCaseSpec(
                    slug=slug,
                    title=title,
                    category="mesh",
                    deck=str(payload["deck"]),
                    summary=str(payload["summary"]),
                    what_it_shows=tuple(str(item) for item in payload["what_it_shows"]),
                    reproduction_command=str(payload["reproduction_command"]),
                    source_paths=tuple(str(item) for item in payload["source_paths"]),
                    generator="mesh_viewer",
                    image_assets=tuple(image_assets),
                    metric_specs=_MESH_GALLERY_METRIC_SPECS,
                    case_setup=tuple(str(item) for item in payload.get("case_setup", ())),
                    key_parameters=tuple(str(item) for item in payload.get("key_parameters", ())),
                    how_to_read=tuple(str(item) for item in payload.get("how_to_read", ())),
                    next_steps=tuple(str(item) for item in payload.get("next_steps", ())),
                    reference_highlights=tuple(str(item) for item in payload.get("reference_highlights", ())),
                    equations_rst=tuple(str(item) for item in payload.get("equations_rst", ())),
                    walkthrough_doc=(
                        str(payload["walkthrough_doc"])
                        if payload.get("walkthrough_doc")
                        else None
                    ),
                    walkthrough_title=(
                        str(payload["walkthrough_title"])
                        if payload.get("walkthrough_title")
                        else None
                    ),
                    metadata=metadata,
                ),
            )
        )
    return tuple(spec for _, spec in sorted(discovered_specs, key=lambda item: item[0]))


_DEFAULT_METHOD_COMPARISON_NEXT_STEPS = (
    "Use :doc:`the gallery and validation reading guide </getting_started/reading-results-pages>` to distinguish example pages, method-comparison pages, and validation pages.",
    "Go back to :doc:`the simulation walkthrough </getting_started/simulation-walkthrough>` when you need to inspect one contributing run in isolation.",
)

_DEFAULT_REGIONAL_LAB_NEXT_STEPS = (
    "Switch `execute = true` in the focused overlay config when the dry plan looks correct and you want to launch the child workflow.",
    "Use these orchestration pages as the planning complement to the individual simulation and method-comparison cases already exposed elsewhere in the gallery.",
)


def _augment_method_comparison_source_paths(
    comparison_config_path: str,
    source_paths: tuple[str, ...],
) -> tuple[str, ...]:
    """Track the committed comparison artifacts reused by gallery generation."""

    expanded_paths: list[str] = [comparison_config_path, *source_paths]
    for source_path in source_paths:
        if not source_path.endswith("/comparison_manifest.json"):
            continue
        comparison_root = Path(source_path).parent.as_posix()
        for extra_name in ("comparison_metrics.json", "observables.csv"):
            extra_path = f"{comparison_root}/{extra_name}"
            if extra_path not in expanded_paths:
                expanded_paths.append(extra_path)
    return tuple(expanded_paths)


def _build_method_comparison_case_spec(
    *,
    slug: str,
    title: str,
    deck: str,
    summary: str,
    what_it_shows: tuple[str, ...],
    comparison_config_path: str,
    source_paths: tuple[str, ...],
    case_setup: tuple[str, ...],
    key_parameters: tuple[str, ...],
    how_to_read: tuple[str, ...],
    study_area: str,
    focus_variant_id: str,
    comparison_family_key: str,
    comparison_family_label: str,
    comparison_family_deck: str,
    comparison_family_order: int,
    comparison_case_order: int,
    next_steps: tuple[str, ...] = _DEFAULT_METHOD_COMPARISON_NEXT_STEPS,
    metadata: dict[str, Any] | None = None,
) -> GalleryCaseSpec:
    """Build one method-comparison gallery spec with shared defaults."""

    return GalleryCaseSpec(
        slug=slug,
        title=title,
        category="method_comparison",
        deck=deck,
        summary=summary,
        what_it_shows=what_it_shows,
        reproduction_command=(
            "python -m launchers method-comparison run "
            f"{comparison_config_path}"
        ),
        source_paths=_augment_method_comparison_source_paths(
            comparison_config_path,
            source_paths,
        ),
        generator="method_comparison_case",
        image_assets=(
            GalleryImageAsset(
                filename=f"{slug}.png",
                caption=f"Summary comparison figure for {title.lower()}.",
                alt_text=f"Method comparison summary for {title}",
            ),
        ),
        case_setup=case_setup,
        key_parameters=key_parameters,
        how_to_read=how_to_read,
        next_steps=next_steps,
        walkthrough_doc="getting_started/reading-results-pages",
        walkthrough_title="the gallery and validation reading guide",
        metadata={
            "comparison_config_path": comparison_config_path,
            "study_area": study_area,
            "focus_variant_id": focus_variant_id,
            "comparison_family_key": comparison_family_key,
            "comparison_family_label": comparison_family_label,
            "comparison_family_deck": comparison_family_deck,
            "comparison_family_order": comparison_family_order,
            "comparison_case_order": comparison_case_order,
            **dict(metadata or {}),
        },
    )


def _build_regional_lab_case_spec(
    *,
    slug: str,
    title: str,
    deck: str,
    summary: str,
    what_it_shows: tuple[str, ...],
    regional_lab_config_path: str,
    source_paths: tuple[str, ...],
    case_setup: tuple[str, ...],
    key_parameters: tuple[str, ...],
    how_to_read: tuple[str, ...],
    process_families: tuple[str, ...],
    workflow_case_order: int,
    metric_specs: tuple[GalleryMetricSpec, ...] = _REGIONAL_LAB_METRIC_SPECS,
    next_steps: tuple[str, ...] = _DEFAULT_REGIONAL_LAB_NEXT_STEPS,
    metadata: dict[str, Any] | None = None,
) -> GalleryCaseSpec:
    """Build one regional-lab gallery spec with shared defaults."""

    return GalleryCaseSpec(
        slug=slug,
        title=title,
        category="simulation",
        deck=deck,
        summary=summary,
        what_it_shows=what_it_shows,
        reproduction_command=(
            "python -m launchers regional-lab run "
            f"{regional_lab_config_path}"
        ),
        source_paths=(regional_lab_config_path, *source_paths),
        generator="regional_lab_case",
        image_assets=(
            GalleryImageAsset(
                filename=f"{slug}.png",
                caption=(
                    f"Dry-plan synthesis for {title.lower()}: site or candidate coverage, "
                    "recipe summary, and planning metrics."
                ),
                alt_text=f"Regional lab dry-plan synthesis for {title}",
            ),
        ),
        metric_specs=metric_specs,
        case_setup=case_setup,
        key_parameters=key_parameters,
        how_to_read=how_to_read,
        next_steps=next_steps,
        walkthrough_doc="getting_started/simulation-walkthrough",
        walkthrough_title="the Simulation walkthrough",
        metadata={
            "regional_lab_config_path": regional_lab_config_path,
            "study_area": "Brittany regional laboratory",
            "process_families": list(process_families),
            "workflow_family_key": "regional_orchestration",
            "workflow_family_label": "Regional Orchestration",
            "workflow_family_deck": (
                "These cases do not focus on one child solver run. They document how one "
                "population of sites and reusable recipes expands into a coordinated study plan."
            ),
            "workflow_family_order": 30,
            "workflow_case_order": workflow_case_order,
            "postprocess_outputs": [
                "site_recipe_matrix",
                "recipe_coverage_summary",
                "coverage_gap_summary",
            ],
            **dict(metadata or {}),
        },
    )


def build_gallery_specs() -> tuple[GalleryCaseSpec, ...]:
    """Return the v1 illustrated-gallery inventory."""
    from .calibration_case_registry import build_calibration_case_records
    from .validation_case_registry import build_validation_case_records

    static_specs = (
        GalleryCaseSpec(
            slug="mesh_sample_bundle",
            title="Mesh Sample Bundle",
            category="mesh",
            deck="Standalone overview of one bundled catchment mesh, with geology and topography panels.",
            summary=(
                "This sample bundle is a versioned catchment mesh illustration shipped with the "
                "repository. It is stable enough for documentation and exposes the main viewer "
                "concepts: cells, edges, rivers, geology interfaces, and topography rendering."
            ),
            what_it_shows=(
                "How the standalone bundle viewer turns one versioned mesh export into a didactic figure.",
                "How geology keys, river edges, and topographic information are surfaced in one compact layout.",
                "What one real exported bundle looks like when used as a reproducible documentation artifact.",
            ),
            reproduction_command=(
                "python -m tools.mesh_bundle_viewer --config examples/mesh_viewer/config_example.toml"
            ),
            source_paths=(
                "examples/mesh_viewer/config_example.toml",
                "examples/mesh_viewer/default_bundle/README.md",
                "tools/mesh_bundle_viewer/README.md",
                "tools/mesh_bundle_viewer/runner/visualization_runner.py",
                "tools/mesh_bundle_viewer/display/figure.py",
                "tools/mesh_bundle_viewer/display/summary.py",
            ),
            generator="mesh_viewer",
            image_assets=(
                GalleryImageAsset(
                    filename="mesh_sample_bundle_overview.png",
                    caption=(
                        "Standalone mesh overview generated from the shipped sample bundle and viewer TOML."
                    ),
                    alt_text="Mesh sample bundle overview with geology and topography panels",
                ),
            ),
            metric_specs=(
                GalleryMetricSpec("Nodes", "node_count", _format_int),
                GalleryMetricSpec("Cells", "cell_count", _format_int),
                GalleryMetricSpec("River edges", "river_edge_count", _format_int),
                GalleryMetricSpec("Geology interfaces", "geology_interface_edge_count", _format_int),
            ),
            metadata={
                "config_path": "examples/mesh_viewer/config_example.toml",
            },
        ),
        GalleryCaseSpec(
            slug="mesh_quality_diagnostics_naizin_10km2",
            title="Mesh Quality Diagnostics (10 km2)",
            category="mesh",
            deck="Aspect ratio and minimum-angle diagnostics computed directly from one mesh bundle.",
            summary=(
                "This case computes basic triangle-shape diagnostics from the versioned bundle and "
                "renders compact maps plus histograms. It targets mesh-quality checks that can be "
                "shared in documentation without re-running a mesh generation pipeline."
            ),
            what_it_shows=(
                "Where the smallest angles and largest aspect ratios concentrate on the mesh.",
                "How triangle areas distribute across one catchment-scale mesh.",
                "What percentile-based quality summaries look like for documentation use.",
            ),
            reproduction_command="python -m tools.doc_gallery",
            source_paths=(
                "examples/mesh_gallery/10km2/mesh_s3_10km2_outlet_1_geology_rivers_buffer30/bundle/nodes.csv",
                "examples/mesh_gallery/10km2/mesh_s3_10km2_outlet_1_geology_rivers_buffer30/bundle/cells.csv",
                "examples/mesh_gallery/10km2/mesh_s3_10km2_outlet_1_geology_rivers_buffer30/bundle/mesh_summary.json",
                "tools/doc_gallery/update_gallery.py",
            ),
            generator="mesh_diagnostics_case",
            image_assets=(
                GalleryImageAsset(
                    filename="mesh_quality_diagnostics_naizin_10km2.png",
                    caption="Triangle quality diagnostics for the 10 km2 Naizin mesh bundle.",
                    alt_text="Mesh quality diagnostics for the 10 km2 catchment mesh",
                ),
            ),
            metric_specs=_MESH_DIAGNOSTIC_METRIC_SPECS,
            case_setup=(
                "Bundle: 10 km2 Strahler-3 outlet 1 with geology + river constraints.",
                "Triangle-based quality diagnostics computed directly from nodes/cells CSVs.",
                "Percentiles summarized to keep the figure readable in docs.",
            ),
            metadata={
                "bundle_path": (
                    "examples/mesh_gallery/10km2/"
                    "mesh_s3_10km2_outlet_1_geology_rivers_buffer30/bundle"
                ),
            },
        ),
        GalleryCaseSpec(
            slug="mesh_constraint_balance_scale_ladder",
            title="Constraint Balance Across Scales",
            category="mesh",
            deck="Relative contributions of river, geology, and boundary constraints across three scales.",
            summary=(
                "This case compares how linear constraints contribute to mesh structure across "
                "the 10, 100, and 1000 km2 bundles. It uses the committed bundle summaries to "
                "compute the breakdown without regenerating any mesh."
            ),
            what_it_shows=(
                "How river-edge density compares to geology-interface edges at different scales.",
                "How boundary edges contribute to the overall constraint mix.",
                "How a compact bar chart can summarize constraints across multiple bundles.",
            ),
            reproduction_command="python -m tools.doc_gallery",
            source_paths=(
                "examples/mesh_gallery/10km2/mesh_s3_10km2_outlet_1_geology_rivers_buffer30/bundle/mesh_summary.json",
                "examples/mesh_gallery/100km2/mesh_headwater_100km2_outlet_1_geology_rivers_buffer30/bundle/mesh_summary.json",
                "examples/mesh_gallery/1000km2/mesh_1000km2_outlet_2_geology_rivers_buffer30/bundle/mesh_summary.json",
                "tools/doc_gallery/update_gallery.py",
            ),
            generator="mesh_constraint_balance_case",
            image_assets=(
                GalleryImageAsset(
                    filename="mesh_constraint_balance_scale_ladder.png",
                    caption="Constraint-edge balance across 10, 100, and 1000 km2 mesh bundles.",
                    alt_text="Constraint balance across mesh scales",
                ),
            ),
            metric_specs=_MESH_CONSTRAINT_BALANCE_METRIC_SPECS,
            case_setup=(
                "Three committed bundles (10, 100, 1000 km2) with geology + rivers constraints.",
                "Counts extracted from mesh_summary.json for consistency.",
                "Focus on linear-constraint balance rather than solver outputs.",
            ),
            metadata={
                "bundle_entries": [
                    {
                        "label": "10 km2 outlet 1",
                        "bundle_path": (
                            "examples/mesh_gallery/10km2/"
                            "mesh_s3_10km2_outlet_1_geology_rivers_buffer30/bundle"
                        ),
                    },
                    {
                        "label": "100 km2 outlet 1",
                        "bundle_path": (
                            "examples/mesh_gallery/100km2/"
                            "mesh_headwater_100km2_outlet_1_geology_rivers_buffer30/bundle"
                        ),
                    },
                    {
                        "label": "1000 km2 outlet 2",
                        "bundle_path": (
                            "examples/mesh_gallery/1000km2/"
                            "mesh_1000km2_outlet_2_geology_rivers_buffer30/bundle"
                        ),
                    },
                ],
            },
        ),
        GalleryCaseSpec(
            slug="mesh_resolution_sensitivity_scale_ladder",
            title="Resolution Sensitivity Across Scales",
            category="mesh",
            deck="Cell-area distributions compared across 10, 100, and 1000 km2 bundles.",
            summary=(
                "This case compares how mesh cell areas distribute across the three committed "
                "scales. It provides a compact resolution ladder without generating new meshes."
            ),
            what_it_shows=(
                "How cell-area distributions shift with scale.",
                "How to summarize resolution sensitivity using percentiles.",
                "A reusable template for comparing mesh density across bundles.",
            ),
            reproduction_command="python -m tools.doc_gallery",
            source_paths=(
                "examples/mesh_gallery/10km2/mesh_s3_10km2_outlet_1_geology_rivers_buffer30/bundle/cells.csv",
                "examples/mesh_gallery/100km2/mesh_headwater_100km2_outlet_1_geology_rivers_buffer30/bundle/cells.csv",
                "examples/mesh_gallery/1000km2/mesh_1000km2_outlet_2_geology_rivers_buffer30/bundle/cells.csv",
                "tools/doc_gallery/update_gallery.py",
            ),
            generator="mesh_resolution_case",
            image_assets=(
                GalleryImageAsset(
                    filename="mesh_resolution_sensitivity_scale_ladder.png",
                    caption="Cell-area distributions across the 10, 100, and 1000 km2 bundles.",
                    alt_text="Mesh resolution sensitivity across scales",
                ),
            ),
            metric_specs=_MESH_RESOLUTION_METRIC_SPECS,
            case_setup=(
                "Cell areas read directly from bundle CSVs.",
                "Log-scale histograms to compare heterogeneous resolution.",
                "Percentile table to summarize each scale.",
            ),
            metadata={
                "bundle_entries": [
                    {
                        "label": "10 km2 outlet 1",
                        "bundle_path": (
                            "examples/mesh_gallery/10km2/"
                            "mesh_s3_10km2_outlet_1_geology_rivers_buffer30/bundle"
                        ),
                    },
                    {
                        "label": "100 km2 outlet 1",
                        "bundle_path": (
                            "examples/mesh_gallery/100km2/"
                            "mesh_headwater_100km2_outlet_1_geology_rivers_buffer30/bundle"
                        ),
                    },
                    {
                        "label": "1000 km2 outlet 2",
                        "bundle_path": (
                            "examples/mesh_gallery/1000km2/"
                            "mesh_1000km2_outlet_2_geology_rivers_buffer30/bundle"
                        ),
                    },
                ],
            },
        ),
        GalleryCaseSpec(
            slug="mesh_zoom_panels_naizin_10km2",
            title="Mesh Zoom Panels (10 km2)",
            category="mesh",
            deck="Full mesh view plus three zoom panels around river-rich areas.",
            summary=(
                "This case renders a full mesh overview and three deterministic zoom panels "
                "centered on dense river segments. It highlights local mesh structure without "
                "requiring new outputs."
            ),
            what_it_shows=(
                "Where rivers impose additional refinement on the mesh.",
                "How local mesh density compares to the global view.",
                "How fixed zooms can provide repeatable visual inspection points.",
            ),
            reproduction_command="python -m tools.doc_gallery",
            source_paths=(
                "examples/mesh_gallery/10km2/mesh_s3_10km2_outlet_1_geology_rivers_buffer30/bundle/nodes.csv",
                "examples/mesh_gallery/10km2/mesh_s3_10km2_outlet_1_geology_rivers_buffer30/bundle/cells.csv",
                "examples/mesh_gallery/10km2/mesh_s3_10km2_outlet_1_geology_rivers_buffer30/bundle/edges.csv",
                "tools/doc_gallery/update_gallery.py",
            ),
            generator="mesh_zoom_case",
            image_assets=(
                GalleryImageAsset(
                    filename="mesh_zoom_panels_naizin_10km2.png",
                    caption="Full mesh view with three river-focused zoom panels.",
                    alt_text="Mesh zoom panels for the 10 km2 catchment",
                ),
            ),
            metric_specs=_MESH_ZOOM_METRIC_SPECS,
            case_setup=(
                "Zoom centers chosen from river-edge density bins.",
                "Mesh edges and river edges rendered for local inspection.",
                "Deterministic selection ensures reproducible figures.",
            ),
            metadata={
                "bundle_path": (
                    "examples/mesh_gallery/10km2/"
                    "mesh_s3_10km2_outlet_1_geology_rivers_buffer30/bundle"
                ),
                "zoom_fraction": 0.22,
            },
        ),
        *_load_json_gallery_case_specs("geographic_cases.json"),
        GalleryCaseSpec(
            slug="geometry_constraints_canut",
            title="Catchment Geometry Constraints",
            category="geometry",
            deck="Basin outline, hydro network, geology units, and regional context rendered without mesh overlays.",
            summary=(
                "This case focuses on geometry only: a catchment mask, the clipped river network, "
                "geology units inside the boundary, and a regional DEM backdrop. It documents the "
                "inputs that drive meshing and solver setup before any discretization happens."
            ),
            what_it_shows=(
                "How the river network, geology units, and boundary align on the same domain.",
                "How geometry layers are clipped and contextualized before any mesh is generated.",
                "Where the catchment sits relative to the regional DEM backdrop.",
            ),
            reproduction_command="python -m tools.doc_gallery",
            source_paths=(
                "examples/data/masks/canut.shp",
                "examples/data/hydrography/regional_stream_network.shp",
                "examples/data/geology/GEO1M_brittany.shp",
                "tools/doc_gallery/update_gallery.py",
            ),
            generator="geometry_case",
            image_assets=(
                GalleryImageAsset(
                    filename="geometry_constraints_canut.png",
                    caption="Boundary, hydro network, and geology units clipped to the same domain.",
                    alt_text="Catchment geometry constraints map",
                ),
            ),
            metric_specs=_GEOMETRY_CONSTRAINT_METRIC_SPECS,
            case_setup=(
                "Domain mask sourced from the shipped `canut` polygon.",
                "Hydrography and geology layers clipped to the same boundary.",
                "Regional DEM added for context; no mesh data used.",
            ),
            metadata={
                "geometry_case_kind": "constraints_overview",
                "boundary_path": "examples/data/masks/canut.shp",
                "rivers_path": "examples/data/hydrography/regional_stream_network.shp",
                "geology_path": "examples/data/geology/GEO1M_brittany.shp",
                "dem_path": "examples/data/dem/regional_dem_naizin.tif",
            },
        ),
        GalleryCaseSpec(
            slug="geometry_topography_canut",
            title="Catchment Topography Context",
            category="geometry",
            deck="Topography and slope diagnostics shown alongside the catchment boundary.",
            summary=(
                "This case adds relief and slope context to the same geometry stack using the "
                "regional DEM. It stays mesh-free while providing visual context for elevation "
                "and terrain gradients."
            ),
            what_it_shows=(
                "Where the catchment sits on the DEM relief.",
                "How slope patterns complement elevation context.",
                "What elevation range is covered by the selected mask.",
            ),
            reproduction_command="python -m tools.doc_gallery",
            source_paths=(
                "examples/data/masks/canut.shp",
                "examples/data/hydrography/regional_stream_network.shp",
                "examples/data/dem/regional_dem_naizin.tif",
                "tools/doc_gallery/update_gallery.py",
            ),
            generator="geometry_case",
            image_assets=(
                GalleryImageAsset(
                    filename="geometry_topography_canut.png",
                    caption="Regional DEM with catchment boundary and river network overlays.",
                    alt_text="Catchment topography context map",
                ),
            ),
            metric_specs=_GEOMETRY_TOPO_METRIC_SPECS,
            case_setup=(
                "Regional DEM background (Naizin).",
                "Catchment boundary clipped to the same extent.",
                "Mesh-free visualization to document geometry inputs.",
            ),
            metadata={
                "geometry_case_kind": "topography_context",
                "boundary_path": "examples/data/masks/canut.shp",
                "rivers_path": "examples/data/hydrography/regional_stream_network.shp",
                "dem_path": "examples/data/dem/regional_dem_naizin.tif",
            },
        ),
        GalleryCaseSpec(
            slug="geometry_indicators_canut",
            title="Catchment Geometry Indicators",
            category="geometry",
            deck="Hypsometry and slope diagnostics derived from the regional DEM and catchment mask.",
            summary=(
                "This case focuses on geometry metrics that do not require meshing: elevation "
                "distribution, slope statistics, and a hypsometric curve computed on the masked DEM."
            ),
            what_it_shows=(
                "How elevation is distributed inside the catchment boundary.",
                "How slope metrics provide a geometry-only proxy for terrain complexity.",
                "A compact hypsometric curve suitable for documentation pages.",
            ),
            reproduction_command="python -m tools.doc_gallery",
            source_paths=(
                "examples/data/masks/canut.shp",
                "examples/data/dem/regional_dem_naizin.tif",
                "tools/doc_gallery/update_gallery.py",
            ),
            generator="geometry_case",
            image_assets=(
                GalleryImageAsset(
                    filename="geometry_indicators_canut.png",
                    caption="Hypsometric curve and slope diagnostics for the Canut mask.",
                    alt_text="Geometry indicators based on DEM and catchment mask",
                ),
            ),
            metric_specs=_GEOMETRY_INDICATOR_METRIC_SPECS,
            case_setup=(
                "Regional DEM masked by the Canut boundary.",
                "Slope estimated from DEM gradients.",
                "Hypsometric curve derived from masked elevations.",
            ),
            metadata={
                "geometry_case_kind": "hypsometry_indicators",
                "boundary_path": "examples/data/masks/canut.shp",
                "dem_path": "examples/data/dem/regional_dem_naizin.tif",
            },
        ),
        GalleryCaseSpec(
            slug="modflow6_gmsh_mesh_catchment",
            title="MODFLOW 6 on a Gmsh Catchment Mesh",
            category="simulation",
            deck="End-to-end launcher run with embedded Gmsh meshing, MODFLOW 6 flow, and GWT transport.",
            summary=(
                "This case keeps the standard process_simulation launcher while using "
                "mesh_catchment to build a triangular Gmsh mesh before MODFLOW 6. "
                "Only selected synthesis figures are committed to the gallery; the full "
                "solver workspace remains a reproducible run artifact."
            ),
            what_it_shows=(
                "How MODFLOW 6 consumes the same runtime Gmsh mesh contract used by other solvers.",
                "How the flow-state triptych relates topography, hydraulic head, and water-table depth.",
                "How cumulative recharge and discharge can be inspected without committing a full run folder.",
            ),
            reproduction_command=(
                "python -m hydromodpy run examples/projects/launcher_simulation/"
                "run_fast_mf6_mesh_catchment.toml"
            ),
            source_paths=(
                "examples/projects/launcher_simulation/run_fast_mf6_mesh_catchment.toml",
                "examples/projects/launcher_simulation/config_mf6_mesh_catchment_common.toml",
                "examples/capability_gallery/launcher_simulation/modflow6_gmsh_mesh_catchment/manifest.json",
                "hydromodpy/analysis/display/figures/flow_synthesis.py",
                "hydromodpy/analysis/capability_gallery.py",
            ),
            generator="copy_assets",
            image_assets=(
                GalleryImageAsset(
                    filename="modflow6_gmsh_flow_state_triptych.png",
                    caption=(
                        "Solver-agnostic flow-state synthesis: topography, hydraulic head, "
                        "and water-table depth on the same triangular mesh."
                    ),
                    alt_text="Triptych showing topography, hydraulic head, and water-table depth on a Gmsh mesh",
                    source_path=(
                        "examples/capability_gallery/launcher_simulation/"
                        "modflow6_gmsh_mesh_catchment/flow_state_triptych.png"
                    ),
                ),
                GalleryImageAsset(
                    filename="modflow6_gmsh_recharge_discharge_cumulative.png",
                    caption="Cumulative recharge and discharge curves from the same launcher run.",
                    alt_text="Cumulative recharge and discharge curves",
                    source_path=(
                        "examples/capability_gallery/launcher_simulation/"
                        "modflow6_gmsh_mesh_catchment/recharge_discharge_cumulative.png"
                    ),
                ),
                GalleryImageAsset(
                    filename="modflow6_gmsh_support_overview.png",
                    caption=(
                        "Runtime support diagnostic showing mesh supports, stream support, "
                        "boundary labels, and resolved wells."
                    ),
                    alt_text="Runtime Gmsh support overview used by MODFLOW 6",
                    source_path=(
                        "examples/capability_gallery/launcher_simulation/"
                        "modflow6_gmsh_mesh_catchment/flow_support_overview.png"
                    ),
                ),
            ),
            case_setup=(
                "Entry config: `run_fast_mf6_mesh_catchment.toml` overlays one shared base profile and adds the fast-run forcing, timeline, and solver choices.",
                "Execution chain: geographic setup -> `mesh_catchment` -> runtime triangular mesh -> MODFLOW 6 flow -> MODFLOW 6 transport -> postprocess/display.",
                "Only selected synthesis figures are republished into `examples/capability_gallery/`; the full run workspace stays outside the doc tree.",
            ),
            key_parameters=(
                "`[simulation.time] step_value`, `start_datetime`, and `end_datetime` define the time support of the run and the interpretation of the recharge chronology.",
                "`[data.recharge.sources] values`, `freq`, and `runoff_ratio` control the synthetic forcing that drives the cumulative recharge/discharge figure.",
                "`[flow.param.K.field_homogeneous]` and `[flow.param.Sy.field_homogeneous]` are the first groundwater parameters to modify when learning how heads and depths react.",
                "`[mesh_catchment.zone_meshing] global_size`, `min_size`, and `max_size` in the shared base config change the mesh density and therefore the support overview.",
                "`[mesh_catchment] constraints_mode` and the river/geology source sections decide which spatial structures are enforced in the runtime mesh.",
                "`[capability_gallery] assets` only selects which figures are copied into the docs; it does not change the physics of the run.",
            ),
            how_to_read=(
                "Start with the support overview to confirm which mesh, streams, and labels the solver actually consumed.",
                "Read the flow-state triptych next: topography gives the structural context, hydraulic head shows the state variable, and water-table depth highlights near-surface response.",
                "Use the cumulative recharge/discharge figure last to understand whether the forcing and drainage behaviour stay coherent over the chosen time window.",
                "If one output looks surprising, first map it back to the config layer that controls it: forcing, mesh, or flow parameters.",
            ),
            next_steps=(
                "Read :doc:`the simulation walkthrough </getting_started/simulation-walkthrough>` for a guided mapping between config sections and displayed figures.",
                "Then open :doc:`the shared-mesh method comparison case </capability_gallery/cases/example12_map_method_comparison>` to compare two solver families on the same support.",
            ),
            walkthrough_doc="getting_started/simulation-walkthrough",
            walkthrough_title="the Simulation walkthrough",
            metadata={
                "study_area": "Naizin catchment",
                "process_families": ["flow", "transport", "postprocess", "display"],
                "mesh_supports": ["runtime_gmsh_triangular_mesh"],
                "flow_solvers": ["MODFLOW 6"],
                "transport_solvers": ["MODFLOW 6 GWT"],
                "workflow_family_key": "runtime_mesh_build",
                "workflow_family_label": "Runtime Mesh Build",
                "workflow_family_deck": (
                    "These cases build the spatial support during the run, then surface the "
                    "minimum set of solver and postprocess figures needed to understand what "
                    "the runtime pipeline produced."
                ),
                "workflow_family_order": 10,
                "workflow_case_order": 10,
                "postprocess_outputs": [
                    "flow_state_triptych",
                    "recharge_discharge_cumulative",
                    "support_overview",
                ],
            },
        ),
        GalleryCaseSpec(
            slug="headwater_100km2_outlet_2_mf6_transient_reference",
            title="Headwater 100 km2 MF6 Transient Reference",
            category="simulation",
            deck="Committed-mesh MODFLOW 6 replay on the 100 km2 outlet-2 basin, published as stable transient postprocess figures.",
            summary=(
                "This case reuses the committed 100 km2 outlet-2 triangular mesh instead of "
                "meshing at runtime. It exposes the reference three-year MODFLOW 6 replay used "
                "as the baseline for the newer realistic-scenario family, with a compact set of "
                "flow-state, support, and cumulative budget figures copied into the gallery."
            ),
            what_it_shows=(
                "How a committed mesh-input workflow differs from the runtime-meshed simulation pages.",
                "How monthly synthetic recharge drives three years of cumulative recharge and discharge on a real basin support.",
                "How the same run can surface both global synthesis figures and direct water-table maps without shipping the full solver workspace.",
            ),
            reproduction_command=(
                "python -m hydromodpy run examples/projects/launcher_simulation/"
                "run_headwater_100km2_outlet_2_mf6_transient_reference.toml"
            ),
            source_paths=(
                "examples/projects/launcher_simulation/run_headwater_100km2_outlet_2_mf6_transient_reference.toml",
                "examples/projects/launcher_simulation/config_headwater_100km2_mf6_transient_common.toml",
                "examples/projects/launcher_simulation/README.md",
                "examples/capability_gallery/launcher_simulation/headwater_100km2_outlet_2_mf6_transient_reference/manifest.json",
                "hydromodpy/analysis/display/figures/flow_synthesis.py",
                "hydromodpy/analysis/capability_gallery.py",
            ),
            generator="copy_assets",
            image_assets=(
                GalleryImageAsset(
                    filename="headwater_100km2_outlet_2_mf6_transient_reference_flow_state_triptych.png",
                    caption=(
                        "Topography, hydraulic head, and water-table depth on the committed "
                        "100 km2 outlet-2 support."
                    ),
                    alt_text="Flow-state triptych for the committed 100 km2 outlet-2 mesh",
                    source_path=(
                        "examples/capability_gallery/launcher_simulation/"
                        "headwater_100km2_outlet_2_mf6_transient_reference/flow_state_triptych.png"
                    ),
                ),
                GalleryImageAsset(
                    filename="headwater_100km2_outlet_2_mf6_transient_reference_recharge_discharge_cumulative.png",
                    caption="Three-year cumulative recharge and discharge curves for the committed-mesh MF6 replay.",
                    alt_text="Cumulative recharge and discharge on the committed 100 km2 outlet-2 replay",
                    source_path=(
                        "examples/capability_gallery/launcher_simulation/"
                        "headwater_100km2_outlet_2_mf6_transient_reference/recharge_discharge_cumulative.png"
                    ),
                ),
                GalleryImageAsset(
                    filename="headwater_100km2_outlet_2_mf6_transient_reference_watertable_elevation.png",
                    caption="Water-table elevation map from the reference transient replay.",
                    alt_text="Water-table elevation map for the committed 100 km2 outlet-2 replay",
                    source_path=(
                        "examples/capability_gallery/launcher_simulation/"
                        "headwater_100km2_outlet_2_mf6_transient_reference/watertable_elevation.png"
                    ),
                ),
                GalleryImageAsset(
                    filename="headwater_100km2_outlet_2_mf6_transient_reference_watertable_depth.png",
                    caption="Water-table depth map from the reference transient replay.",
                    alt_text="Water-table depth map for the committed 100 km2 outlet-2 replay",
                    source_path=(
                        "examples/capability_gallery/launcher_simulation/"
                        "headwater_100km2_outlet_2_mf6_transient_reference/watertable_depth.png"
                    ),
                ),
                GalleryImageAsset(
                    filename="headwater_100km2_outlet_2_mf6_transient_reference_support_overview.png",
                    caption=(
                        "Support overview confirming the committed mesh bundle, top/bottom sampling, "
                        "and active support labels used by the transient replay."
                    ),
                    alt_text="Support overview for the committed 100 km2 outlet-2 replay",
                    source_path=(
                        "examples/capability_gallery/launcher_simulation/"
                        "headwater_100km2_outlet_2_mf6_transient_reference/flow_support_overview.png"
                    ),
                ),
            ),
            case_setup=(
                "Base config: `config_headwater_100km2_mf6_transient_common.toml` keeps the committed triangular mesh, the flow-only process chain, and the common postprocess/display switches.",
                "Overlay config: `run_headwater_100km2_outlet_2_mf6_transient_reference.toml` injects the three-year monthly recharge chronology and homogeneous K/Sy/Ss values.",
                "Execution chain: committed `mesh_input` bundle -> MODFLOW 6 transient flow -> postprocess rasters and synthesis figures -> gallery publication.",
            ),
            key_parameters=(
                "`[mesh_input] mesh_path` and `bundle_dir` lock the support to the versioned 100 km2 outlet-2 mesh, which makes this page a support-reuse workflow rather than a meshing example.",
                "`[simulation.time] start_datetime`, `end_datetime`, and `step_value` define the three-year monthly replay window shown in the cumulative curves.",
                "`[[data.recharge.sources]] values`, `freq`, and `runoff_ratio` define the synthetic forcing chronology that drives the transient response.",
                "`[flow.param.K.field_homogeneous]`, `[flow.param.Sy.field_homogeneous]`, and `[flow.param.Ss.field_homogeneous]` are the main parameters to perturb when comparing this reference run against the more complex scenario overlays.",
            ),
            how_to_read=(
                "Open the support overview first to verify that the run reused the committed mesh bundle and sampled the structural surfaces as expected.",
                "Read the flow-state triptych next for the compact basin-wide synthesis, then use the direct water-table maps when you need one variable isolated.",
                "Use the cumulative recharge/discharge panel last to judge whether the imposed forcing and the integrated basin response remain coherent over the three-year window.",
            ),
            next_steps=(
                "Read :doc:`the simulation walkthrough </getting_started/simulation-walkthrough>` for the general mapping between config sections and displayed figures.",
                "Use the committed-mesh comparison pages in :doc:`the method-comparison section </capability_gallery/method_comparison>` when you want to compare this style of replay against other supports or solver families.",
            ),
            walkthrough_doc="getting_started/simulation-walkthrough",
            walkthrough_title="the Simulation walkthrough",
            metadata={
                "study_area": "Headwater 100 km2 outlet 2",
                "process_families": ["flow", "postprocess", "display"],
                "mesh_supports": ["committed_triangular_mesh_input"],
                "flow_solvers": ["MODFLOW 6"],
                "workflow_family_key": "committed_mesh_replays",
                "workflow_family_label": "Committed Mesh Replays",
                "workflow_family_deck": (
                    "These cases keep the spatial support fixed and focus on how forcing, "
                    "hydraulic parameters, and solver settings shape the replay on an already "
                    "versioned basin mesh."
                ),
                "workflow_family_order": 20,
                "workflow_case_order": 10,
                "postprocess_outputs": [
                    "flow_state_triptych",
                    "recharge_discharge_cumulative",
                    "watertable_elevation_map",
                    "watertable_depth_map",
                    "support_overview",
                ],
            },
        ),
        GalleryCaseSpec(
            slug="regional_lab_headwater_100km2_dry_plan",
            title="Regional Lab Dry Plan on Headwater 100 km2",
            category="simulation",
            deck="Dry-run orchestration example showing how one regional site catalog expands into simulation and method-comparison recipes.",
            summary=(
                "This case documents the orchestration layer rather than one child run. It uses the "
                "first committed `regional_lab` example in dry-plan mode to show how a small site "
                "catalog is filtered, clustered, expanded into recipes, and reported as runnable cases "
                "or explicit coverage gaps."
            ),
            what_it_shows=(
                "How `regional_lab` separates site inventory, recipe definitions, and execution/reporting layers.",
                "How one selected site population expands into planned child runs plus explicit coverage gaps when required configs are missing.",
                "How a dry-run can be used as a planning and coverage-audit tool before any child simulation is actually launched.",
            ),
            reproduction_command=(
                "python -m launchers regional-lab run "
                "examples/projects/launcher_simulation/regional_lab/config_headwater_100km2_lab.toml"
            ),
            source_paths=(
                "launchers/regional_lab/README.md",
                "launchers/regional_lab/config.py",
                "launchers/regional_lab/launcher.py",
                "examples/projects/launcher_simulation/regional_lab/README.md",
                "examples/projects/launcher_simulation/regional_lab/config_headwater_100km2_lab.toml",
                "examples/projects/launcher_simulation/regional_lab/site_catalog.csv",
            ),
            generator="regional_lab_case",
            image_assets=(
                GalleryImageAsset(
                    filename="regional_lab_headwater_100km2_dry_plan.png",
                    caption=(
                        "Dry-plan synthesis for the committed regional-lab example: site/recipe "
                        "matrix, recipe coverage, and planning summary."
                    ),
                    alt_text="Regional lab dry-plan synthesis for the headwater 100 km2 example",
                ),
            ),
            metric_specs=_REGIONAL_LAB_METRIC_SPECS,
            case_setup=(
                "Launcher family: `regional_lab`, sitting above child `simulation` and `method-comparison` launchers.",
                "Example scope: one small Brittany site catalog with one fully runnable headwater site and several inventory-only or screening sites.",
                "The committed example starts with `execute = false`, so the page documents planning, selection, and reporting rather than child-run results.",
            ),
            key_parameters=(
                "`[regional_lab.catalog]` defines how site metadata and path-like config references are loaded from the catalog.",
                "`[regional_lab.selection] tags = [\"mesh_ready\"]` filters the population before any recipe expansion happens.",
                "`[[regional_lab.cluster_rule]]` enriches catalog rows into reusable clusters/families/scales instead of relying only on static columns.",
                "`[[regional_lab.recipe]]` turns one selected site population into concrete child launcher plans, with `required_fields` making coverage gaps explicit.",
                "`execute = false` keeps the example in dry-plan mode, which is exactly what this page documents.",
            ),
            how_to_read=(
                "Start with the site-by-recipe matrix to see which sites are runnable and which ones remain coverage gaps.",
                "Use the recipe bars next to understand how much of the selected population each recipe actually covers.",
                "Read the text summary last: it explains why the example is valuable even with zero executed child runs.",
            ),
            next_steps=(
                "Switch `execute = true` in the example config when the dry plan looks correct and you want to launch the child workflows.",
                "Use this page as the orchestration complement to the individual simulation and method-comparison cases already exposed elsewhere in the gallery.",
            ),
            walkthrough_doc="getting_started/simulation-walkthrough",
            walkthrough_title="the Simulation walkthrough",
            metadata={
                "regional_lab_config_path": "examples/projects/launcher_simulation/regional_lab/config_headwater_100km2_lab.toml",
                "study_area": "Brittany regional laboratory",
                "process_families": ["planning", "simulation", "method_comparison", "reporting"],
                "workflow_family_key": "regional_orchestration",
                "workflow_family_label": "Regional Orchestration",
                "workflow_family_deck": (
                    "These cases do not focus on one child solver run. They document how one "
                    "population of sites and reusable recipes expands into a coordinated study plan."
                ),
                "workflow_family_order": 30,
                "workflow_case_order": 10,
                "postprocess_outputs": [
                    "site_recipe_matrix",
                    "recipe_coverage_summary",
                    "coverage_gap_summary",
                ],
            },
        ),
        _build_regional_lab_case_spec(
            slug="regional_lab_headwater_100km2_mf6_reference_recipe",
            title="Regional Lab MF6 Reference Recipe on Headwater 100 km2",
            deck=(
                "Recipe-focused orchestration view isolating the committed MF6 replay workflow "
                "across the selected headwater population."
            ),
            summary=(
                "This page narrows the committed `regional_lab` example to the `mf6_reference` "
                "recipe. It shows how one simulation recipe consumes one catalog field, expands "
                "only across the compatible headwater sites, and keeps missing child configs visible "
                "as explicit coverage gaps."
            ),
            what_it_shows=(
                "How one reusable simulation recipe is expanded from the regional site catalog instead of hard-coding one child config path per case page.",
                "How `required_fields = [\"simulation_reference_config\"]` turns missing references into explicit recipe-level gaps.",
                "How recipe-specific overlay configs keep the reproduction command precise without duplicating the whole laboratory definition.",
            ),
            regional_lab_config_path=(
                "examples/projects/launcher_simulation/regional_lab/"
                "config_headwater_100km2_lab_mf6_reference.toml"
            ),
            source_paths=(
                "launchers/regional_lab/README.md",
                "launchers/regional_lab/config.py",
                "launchers/regional_lab/launcher.py",
                "examples/projects/launcher_simulation/regional_lab/README.md",
                "examples/projects/launcher_simulation/regional_lab/config_headwater_100km2_lab.toml",
                "examples/projects/launcher_simulation/regional_lab/site_catalog.csv",
                "examples/projects/launcher_simulation/run_headwater_100km2_outlet_2_mf6_transient_reference.toml",
            ),
            metric_specs=_REGIONAL_LAB_RECIPE_METRIC_SPECS,
            case_setup=(
                "Base lab config: `config_headwater_100km2_lab.toml` selects `mesh_ready` sites, enriches the headwater cluster through rules, and defines three reusable recipes.",
                "Overlay config: `config_headwater_100km2_lab_mf6_reference.toml` keeps only the `mf6_reference` recipe enabled and writes to a dedicated output directory.",
                "Child-run contract: the recipe reads `simulation_reference_config` from each candidate site row rather than deriving one path from naming conventions alone.",
            ),
            key_parameters=(
                "`[[regional_lab.recipe]] id = \"mf6_reference\"` plus the overlay `enabled` flags define the focused orchestration slice documented by this page.",
                "`families = [\"headwater\"]` and `scales = [\"100km2\"]` scope the recipe before any child config path is resolved.",
                "`required_fields = [\"simulation_reference_config\"]` is the gate that separates the one runnable outlet from the two inventory-only headwater sites.",
                "`config_path_template = \"{simulation_reference_config}\"` delegates the concrete simulation config choice to the catalog row.",
            ),
            how_to_read=(
                "Read the matrix first: it shows one runnable headwater outlet and two recipe-level gaps on the same selected population.",
                "Use the coverage bar next to judge how far the committed catalog already goes for this replay workflow before adding more child configs.",
                "Finish with the planning summary to connect the remaining gaps to site maturity and cluster scope.",
            ),
            process_families=("planning", "simulation", "reporting"),
            workflow_case_order=20,
            metadata={
                "regional_lab_view_kind": "recipe",
                "regional_lab_recipe_id": "mf6_reference",
                "regional_lab_recipe_label": "MF6 reference replay",
                "mesh_supports": ["committed_triangular_mesh_input"],
                "flow_solvers": ["MODFLOW 6"],
            },
        ),
        _build_regional_lab_case_spec(
            slug="regional_lab_headwater_100km2_backend_compare_recipe",
            title="Regional Lab Backend Comparison Recipe on Headwater 100 km2",
            deck=(
                "Recipe-focused orchestration view isolating the committed backend-comparison "
                "workflow across the headwater screening population."
            ),
            summary=(
                "This page narrows the committed `regional_lab` example to the `backend_compare` "
                "recipe. It shows how one method-comparison workflow is carried as a reusable recipe, "
                "planned only where the catalog exposes one backend-comparison config, and reported "
                "with explicit gaps on the remaining headwater sites."
            ),
            what_it_shows=(
                "How `regional_lab` can orchestrate `method-comparison` launchers, not only single-run simulations.",
                "How one comparison recipe reuses the same headwater site selection while depending on a different catalog field than the MF6 replay recipe.",
                "How the dry plan remains useful even when only one site is currently comparison-ready.",
            ),
            regional_lab_config_path=(
                "examples/projects/launcher_simulation/regional_lab/"
                "config_headwater_100km2_lab_backend_compare.toml"
            ),
            source_paths=(
                "launchers/regional_lab/README.md",
                "launchers/regional_lab/config.py",
                "launchers/regional_lab/launcher.py",
                "examples/projects/launcher_simulation/regional_lab/README.md",
                "examples/projects/launcher_simulation/regional_lab/config_headwater_100km2_lab.toml",
                "examples/projects/launcher_simulation/regional_lab/site_catalog.csv",
                "examples/projects/launcher_simulation/run_method_comparison_headwater_100km2_outlet_2_backends.toml",
            ),
            metric_specs=_REGIONAL_LAB_RECIPE_METRIC_SPECS,
            case_setup=(
                "Base lab config: the same selected headwater population is reused, so the page isolates recipe logic rather than changing the site inventory.",
                "Overlay config: `config_headwater_100km2_lab_backend_compare.toml` keeps only the `backend_compare` recipe enabled and writes to its own output root.",
                "Child-run contract: the recipe reads `backend_comparison_config` from each site row and expands into `method-comparison` child runs.",
            ),
            key_parameters=(
                "`launcher = \"method-comparison\"` shows that `regional_lab` can plan solver-comparison suites as first-class child workflows.",
                "`required_fields = [\"backend_comparison_config\"]` is what turns the two inventory-only headwater sites into visible comparison gaps.",
                "`config_path_template = \"{backend_comparison_config}\"` keeps the recipe generic while the site catalog remains the source of truth for child inputs.",
                "The overlay keeps the other recipes disabled so the page documents one comparison workflow rather than the full laboratory at once.",
            ),
            how_to_read=(
                "Start with the matrix to confirm that the backend-comparison recipe currently lands on one validated outlet only.",
                "Use the coverage summary to separate recipe reach from recipe quality: one planned case can still be valuable if the gaps stay explicit.",
                "Read the text panel last to connect those gaps to catalog maturity rather than to launcher failure.",
            ),
            process_families=("planning", "method_comparison", "reporting"),
            workflow_case_order=30,
            metadata={
                "regional_lab_view_kind": "recipe",
                "regional_lab_recipe_id": "backend_compare",
                "regional_lab_recipe_label": "Backend comparison",
                "mesh_supports": ["committed_triangular_mesh_input"],
            },
        ),
        _build_regional_lab_case_spec(
            slug="regional_lab_headwater_100km2_transient_backend_compare_recipe",
            title="Regional Lab Transient Backend Comparison Recipe on Headwater 100 km2",
            deck=(
                "Recipe-focused orchestration view isolating the transient pulsed-recharge "
                "backend-comparison workflow across the committed headwater population."
            ),
            summary=(
                "This page narrows the committed `regional_lab` example to the "
                "`transient_backend_compare` recipe. It documents the same site population as the "
                "steady backend comparison, but with a transient comparison contract that depends on "
                "its own child config field and remains explicit about current coverage gaps."
            ),
            what_it_shows=(
                "How two method-comparison recipes can coexist in one laboratory while pointing to different child configs and modelling questions.",
                "How the transient backend-comparison recipe stays separate from the simpler backend-comparison recipe instead of overloading one flat page.",
                "How recipe overlays can document a more specific transient workflow without cloning the site catalog or cluster rules.",
            ),
            regional_lab_config_path=(
                "examples/projects/launcher_simulation/regional_lab/"
                "config_headwater_100km2_lab_transient_backend_compare.toml"
            ),
            source_paths=(
                "launchers/regional_lab/README.md",
                "launchers/regional_lab/config.py",
                "launchers/regional_lab/launcher.py",
                "examples/projects/launcher_simulation/regional_lab/README.md",
                "examples/projects/launcher_simulation/regional_lab/config_headwater_100km2_lab.toml",
                "examples/projects/launcher_simulation/regional_lab/site_catalog.csv",
                "examples/projects/launcher_simulation/run_method_comparison_headwater_100km2_outlet_2_transient_pulsed_recharge_backends.toml",
            ),
            metric_specs=_REGIONAL_LAB_RECIPE_METRIC_SPECS,
            case_setup=(
                "Base lab config: the selected headwater sites and cluster rules are unchanged so the page isolates the transient recipe, not the site population.",
                "Overlay config: `config_headwater_100km2_lab_transient_backend_compare.toml` keeps only the `transient_backend_compare` recipe enabled.",
                "Child-run contract: the recipe reads `transient_backend_comparison_config` from each site row and expands into the transient pulsed-recharge comparison suite.",
            ),
            key_parameters=(
                "`id = \"transient_backend_compare\"` keeps the transient question separate from the simpler backend-comparison recipe instead of collapsing both into one card.",
                "`required_fields = [\"transient_backend_comparison_config\"]` makes the missing transient child configs visible as coverage gaps rather than silent filtering.",
                "`launcher = \"method-comparison\"` plus the recipe-specific config path field is what lets one lab coordinate several comparison families in parallel.",
                "The overlay config gives this page one exact reproduction command while preserving the shared base laboratory definition.",
            ),
            how_to_read=(
                "Read the matrix first to see that the transient comparison recipe currently has the same one runnable outlet and two explicit gaps.",
                "Use the coverage bar next to compare this transient slice with the simpler backend-comparison slice: same population, different child contract.",
                "Use the planning summary last to keep the interpretation at the orchestration level before diving into the child comparison page itself.",
            ),
            process_families=("planning", "method_comparison", "reporting"),
            workflow_case_order=40,
            metadata={
                "regional_lab_view_kind": "recipe",
                "regional_lab_recipe_id": "transient_backend_compare",
                "regional_lab_recipe_label": "Transient backend comparison",
                "mesh_supports": ["committed_triangular_mesh_input"],
            },
        ),
        GalleryCaseSpec(
            slug="hydraulic_conductivity_square_parameterizations",
            title="Square Field Parameterizations",
            category="hydraulic_properties",
            deck=(
                "Synthetic conductivity and storage examples comparing structured and triangular supports, "
                "inline units, and vertical profiles."
            ),
            summary=(
                "This case builds one compact two-zone square domain and maps the same conductivity field "
                "onto structured and triangular meshes. It also illustrates how inline units and depth-profile "
                "modes are normalized before the solver stage."
            ),
            what_it_shows=(
                "How the same heterogeneous K field maps onto structured and triangular meshes.",
                "How inline values such as `m/day` and `mm/day` are normalized to HydroModPy's SI internals.",
                "How `none`, `exponential`, and `tabulated` depth profiles modify conductivity with depth.",
            ),
            reproduction_command="python -m tools.doc_gallery",
            source_paths=(
                "hydromodpy/spatial/field/core/field_param.py",
                "hydromodpy/spatial/field/core/field_param_config.py",
                "hydromodpy/spatial/field/cases/square/field_mesh_square.py",
                "hydromodpy/spatial/field/cases/square/field_spatial_square.py",
                "hydromodpy/spatial/field/cases/square/field_param_config.toml",
                "tests/unit/field/test_field_param.py",
                "tests/unit/field/test_field_param_config.py",
            ),
            generator="property_case",
            image_assets=(
                GalleryImageAsset(
                    filename="hydraulic_conductivity_square_parameterizations.png",
                    caption=(
                        "Structured and triangular conductivity maps alongside depth-profile "
                        "and inline-unit examples."
                    ),
                    alt_text="Hydraulic conductivity parameterizations on square synthetic meshes",
                ),
            ),
            metric_specs=_HYDRAULIC_PROPERTY_SQUARE_METRIC_SPECS,
            case_setup=(
                "Unit-square domain split by one diagonal into granite and micaschist zones.",
                "Structured and triangular meshes generated from the same target cell count.",
                "Depth dependence illustrated with `none`, `exponential`, and `tabulated` profiles.",
            ),
            metadata={
                "property_case_kind": "square_parameterizations",
                "parameter_ids": ["K", "Sy", "Ss"],
                "parameterization_modes": ["inline", "heterogeneous", "exponential", "tabulated"],
                "supports": ["structured", "triangular_structured"],
            },
        ),
        GalleryCaseSpec(
            slug="hydraulic_conductivity_irregular_mesh",
            title="Irregular Mesh Conductivity Mapping",
            category="hydraulic_properties",
            deck="Conductivity transfer on a synthetic square domain using a stochastic unstructured mesh.",
            summary=(
                "This case reuses the synthetic square field but maps it onto an irregular "
                "triangular mesh alongside a structured baseline. The comparison highlights how "
                "the same property definition behaves on irregular supports."
            ),
            what_it_shows=(
                "How heterogeneous K values transfer onto an irregular triangular mesh.",
                "How the same field looks on a structured baseline for visual comparison.",
                "How irregular supports preserve zone contrasts while adapting to stochastic cell layout.",
            ),
            reproduction_command="python -m tools.doc_gallery",
            source_paths=(
                "hydromodpy/spatial/field/core/field_param.py",
                "hydromodpy/spatial/field/cases/square/field_mesh_square.py",
                "hydromodpy/spatial/field/cases/square/field_spatial_square.py",
                "tests/unit/field/test_field_param.py",
            ),
            generator="property_case",
            image_assets=(
                GalleryImageAsset(
                    filename="hydraulic_conductivity_irregular_mesh.png",
                    caption="Structured versus irregular triangular conductivity maps for the same field.",
                    alt_text="Hydraulic conductivity mapped on structured and irregular triangular meshes",
                ),
            ),
            metric_specs=_HYDRAULIC_PROPERTY_IRREGULAR_METRIC_SPECS,
            case_setup=(
                "Unit-square domain split into granite and micaschist zones.",
                "Structured baseline generated with 64 target cells.",
                "Irregular triangular mesh generated with a fixed random seed.",
            ),
            metadata={
                "property_case_kind": "irregular_mesh",
                "parameter_ids": ["K"],
                "parameterization_modes": ["heterogeneous"],
                "supports": ["structured", "triangular_unstructured"],
            },
        ),
        GalleryCaseSpec(
            slug="hydraulic_conductivity_depth_dependence",
            title="Depth-Dependent Conductivity",
            category="hydraulic_properties",
            deck="Depth-profiled conductivity maps and profiles rendered on a synthetic square mesh.",
            summary=(
                "This case focuses on vertical attenuation. It renders the same heterogeneous field "
                "at the surface and at depth, alongside profile curves that explain the depth scaling."
            ),
            what_it_shows=(
                "How depth profiles rescale conductivity for a given mesh support.",
                "How surface and deep maps diverge while preserving zone geometry.",
                "How exponential and tabulated profiles compare on the same depth axis.",
            ),
            reproduction_command="python -m tools.doc_gallery",
            source_paths=(
                "hydromodpy/spatial/field/core/field_param.py",
                "hydromodpy/spatial/field/cases/square/field_mesh_square.py",
                "hydromodpy/spatial/field/cases/square/field_spatial_square.py",
                "tests/unit/field/test_field_param.py",
            ),
            generator="property_case",
            image_assets=(
                GalleryImageAsset(
                    filename="hydraulic_conductivity_depth_dependence.png",
                    caption="Surface versus deep conductivity maps with depth-profile curves.",
                    alt_text="Depth-dependent conductivity maps and profiles",
                ),
            ),
            metric_specs=_HYDRAULIC_PROPERTY_DEPTH_METRIC_SPECS,
            case_setup=(
                "Unit-square two-zone field mapped onto a structured mesh.",
                "Depth profile applied using exponential and tabulated modes.",
                "Surface (0 m) and deep (40 m) maps rendered for comparison.",
            ),
            metadata={
                "property_case_kind": "depth_dependence",
                "parameter_ids": ["K"],
                "parameterization_modes": ["exponential", "tabulated", "depth_profile"],
                "supports": ["structured"],
                "depth_m": 40.0,
            },
        ),
        GalleryCaseSpec(
            slug="hydraulic_conductivity_geology_transfer_brittany",
            title="Geology-Driven Conductivity Transfer",
            category="hydraulic_properties",
            deck="Conductivity mapping from vector geology polygons onto a local structured mesh using FieldParam.",
            summary=(
                "This case reuses the Brittany geology subset shipped with the repository and the generic "
                "geology-to-field pipeline. A compact figure shows geology zones, the value table keyed by zone, "
                "and the mapped conductivity field."
            ),
            what_it_shows=(
                "How one CSV keyed by geology codes turns into a mesh-ready K field.",
                "How HydroModPy keeps the zone legend and the mapped property view aligned on the same local window.",
                "What a deterministic geology-driven property transfer looks like on versioned demo data.",
            ),
            reproduction_command=(
                "python -m hydromodpy.data.variables.geology.cases.run_geology_property_case "
                "--geology-config-file gallery_geology_config_brittany.toml "
                "--field-param-config-file gallery_field_param_brittany.toml "
                "--no-show-plot"
            ),
            source_paths=(
                "hydromodpy/data/variables/geology/cases/run_geology_property_case.py",
                "hydromodpy/data/variables/geology/cases/gallery_geology_config_brittany.toml",
                "hydromodpy/data/variables/geology/cases/gallery_field_param_brittany.toml",
                "examples/data/geology/GEO1M_brittany.shp",
                "examples/data/geology/GEO1M_brittany.dbf",
                "examples/data/geology/GEO1M_brittany.shx",
                "examples/data/geology/GEO1M_brittany.prj",
                "examples/data/geology/geology_K_dummy_demo.csv",
                "examples/data/dem/regional_dem_naizin.tif",
                "tests/unit/data_managers/geology/test_geology_property_demo.py",
            ),
            generator="property_case",
            image_assets=(
                GalleryImageAsset(
                    filename="hydraulic_conductivity_geology_transfer_brittany.png",
                    caption=(
                        "Geology zones, zone-value mapping, and resulting conductivity field on a local mesh."
                    ),
                    alt_text="Geology-driven conductivity transfer on the Brittany subset",
                ),
            ),
            metric_specs=_HYDRAULIC_PROPERTY_GEOLOGY_METRIC_SPECS,
            case_setup=(
                "Local Brittany window extracted from the committed GEO1M subset.",
                "Heterogeneous K values loaded from a versioned CSV keyed by geology codes.",
                "Property transfer computed on a compact structured mesh for documentation stability.",
            ),
            metadata={
                "property_case_kind": "geology_transfer_demo",
                "geology_config_path": "hydromodpy/data/variables/geology/cases/gallery_geology_config_brittany.toml",
                "field_param_config_path": "hydromodpy/data/variables/geology/cases/gallery_field_param_brittany.toml",
                "parameter_ids": ["K"],
                "parameterization_modes": ["csv", "heterogeneous"],
                "supports": ["vector_local", "structured"],
            },
        ),
        GalleryCaseSpec(
            slug="hydraulic_conductivity_geology_transfer_variants",
            title="Geology-Driven Conductivity Variants",
            category="hydraulic_properties",
            deck="Multiple geology-driven conductivity cases compared in tabbed panels.",
            summary=(
                "This case groups several geology-driven conductivity maps, mixing the "
                "structured Brittany demo and triangular mesh bundles from different basins. "
                "Tabs keep the variants compact while emphasizing differences in geography and support."
            ),
            what_it_shows=(
                "How geology-driven conductivity looks on structured and triangular supports.",
                "How different basin contexts change the mapped conductivity patterns.",
                "How a tabbed layout keeps multiple variants readable in the docs.",
            ),
            reproduction_command="python -m tools.doc_gallery",
            source_paths=(
                "hydromodpy/data/variables/geology/cases/run_geology_property_case.py",
                "hydromodpy/data/variables/geology/cases/gallery_geology_config_brittany.toml",
                "hydromodpy/data/variables/geology/cases/gallery_field_param_brittany.toml",
                "examples/mesh_gallery/10km2/mesh_s3_10km2_outlet_1_geology_rivers_buffer30/bundle/cells.csv",
                "examples/mesh_gallery/100km2/mesh_headwater_100km2_outlet_1_geology_rivers_buffer30/bundle/cells.csv",
                "tools/doc_gallery/update_gallery.py",
            ),
            generator="property_case",
            image_assets=(
                GalleryImageAsset(
                    filename="hydraulic_conductivity_geology_variant_brittany.png",
                    caption="Structured Brittany geology transfer (local window).",
                    alt_text="Structured geology transfer in Brittany",
                ),
                GalleryImageAsset(
                    filename="hydraulic_conductivity_geology_variant_10km2.png",
                    caption="Triangular 10 km2 catchment bundle with geology-driven conductivity.",
                    alt_text="Triangular geology transfer on 10 km2 catchment",
                ),
                GalleryImageAsset(
                    filename="hydraulic_conductivity_geology_variant_100km2.png",
                    caption="Triangular 100 km2 catchment bundle with geology-driven conductivity.",
                    alt_text="Triangular geology transfer on 100 km2 catchment",
                ),
            ),
            metric_specs=_HYDRAULIC_PROPERTY_GEOLOGY_METRIC_SPECS,
            case_setup=(
                "One structured geology transfer (Brittany window).",
                "Two triangular mesh bundles with geology-driven conductivity.",
                "Tabbed display to compare variants without page clutter.",
            ),
            metadata={
                "property_case_kind": "geology_transfer_variants",
                "variant_specs": [
                    {
                        "title": "Structured Brittany",
                        "kind": "brittany",
                        "geology_config_path": "hydromodpy/data/variables/geology/cases/gallery_geology_config_brittany.toml",
                        "field_param_config_path": "hydromodpy/data/variables/geology/cases/gallery_field_param_brittany.toml",
                    },
                    {
                        "title": "Triangular 10 km2",
                        "kind": "bundle",
                        "bundle_path": (
                            "examples/mesh_gallery/10km2/"
                            "mesh_s3_10km2_outlet_1_geology_rivers_buffer30/bundle"
                        ),
                    },
                    {
                        "title": "Triangular 100 km2",
                        "kind": "bundle",
                        "bundle_path": (
                            "examples/mesh_gallery/100km2/"
                            "mesh_headwater_100km2_outlet_1_geology_rivers_buffer30/bundle"
                        ),
                    },
                ],
                "parameter_ids": ["K"],
                "parameterization_modes": ["csv", "heterogeneous", "bundle"],
                "supports": ["structured", "triangular"],
                "tabbed_variants": True,
            },
        ),
        GalleryCaseSpec(
            slug="example12_map_method_comparison",
            title="Shared-Mesh Solver Comparison on Naizin",
            category="method_comparison",
            deck="Shared-mesh comparison of MODFLOW 6 and Boussinesq on Naizin, combining map snapshots and three head chronicle probes.",
            summary=(
                "This case reuses two committed run folders for the same Naizin catchment mesh. It compares full "
                "water-table elevation and water-table depth maps at the last saved time step, plus head chronicle "
                "comparisons at three contrasted probe locations, then renders parity plots and compact error bars."
            ),
            what_it_shows=(
                "How two solver families can be compared on exactly the same triangular support.",
                "How map-wide parity plots complement scalar metrics such as MAE and RMSE.",
                "How three point chronicle comparisons expose outlet, mid-basin, and upstream response differences.",
                "How comparison figures can be regenerated from committed run folders without rerunning the solvers.",
            ),
            reproduction_command=(
                "python -m launchers method-comparison run "
                "examples/projects/launcher_simulation/run_method_comparison_example12_map_existing.toml"
            ),
            source_paths=_augment_method_comparison_source_paths(
                "examples/projects/launcher_simulation/run_method_comparison_example12_map_existing.toml",
                (
                    "examples/projects/launcher_simulation/run_fast_mf6_mesh_catchment.toml",
                    "examples/projects/launcher_simulation/run_fast_boussinesq_precomputed_mesh_input.toml",
                    "examples/projects/launcher_simulation/method_comparison/example12_map_method_comparison/comparison_manifest.json",
                ),
            ),
            generator="method_comparison_case",
            image_assets=(
                GalleryImageAsset(
                    filename="example12_map_method_comparison.png",
                    caption=(
                        "Parity plots and error bars comparing the committed MODFLOW 6 and Boussinesq "
                        "runs on the shared Naizin mesh."
                    ),
                    alt_text="Method comparison figure for the shared Naizin mesh",
                ),
            ),
            case_setup=(
                "Reference variant: MODFLOW 6 on the committed Gmsh catchment mesh.",
                "Candidate variant: Boussinesq reusing the exact same mesh bundle.",
                "Compared observables: full `watertable_elevation` and `watertable_depth` maps at the last saved time step.",
                "Three head probes sample contrasted response zones: outlet lowland, mid-basin storage, and upstream ridge.",
            ),
            key_parameters=(
                "The most important modelling choice is not a scalar parameter but support equality: both runs must use the same saved mesh if you want a fair map-wide comparison.",
                "`run_method_comparison_example12_map_existing.toml` defines which run folders are compared and which observables are sampled from them.",
                "The compared observables (`watertable_elevation`, `watertable_depth`) determine whether the figure emphasizes absolute state mismatch or near-surface response mismatch.",
                "The three point observables reuse anchors from `method_comparison_points.toml` so the same physical locations are compared across methods.",
                "Interpret RMSE and MAE together: RMSE highlights stronger local mismatches while MAE gives the typical cell-wise discrepancy.",
            ),
            how_to_read=(
                "Check first that the comparison is support-consistent: same mesh, same spatial observable, same saved time step.",
                "Then read the parity cloud shape. A tight cloud around the 1:1 line means the two solvers agree across most cells.",
                "Use the error bars and scalar metrics to judge whether disagreement is diffuse or concentrated in specific ranges of the state variable.",
                "Do not read this page as a validation benchmark: it is a solver-to-solver comparison, not a comparison against an analytical truth.",
            ),
            next_steps=(
                "Use :doc:`the gallery and validation reading guide </getting_started/reading-results-pages>` to distinguish example pages, method-comparison pages, and validation pages.",
                "If you need to understand the reference MODFLOW 6 run itself, go back to :doc:`the simulation walkthrough </getting_started/simulation-walkthrough>`.",
            ),
            walkthrough_doc="getting_started/reading-results-pages",
            walkthrough_title="the gallery and validation reading guide",
            metadata={
                "comparison_config_path": "examples/projects/launcher_simulation/run_method_comparison_example12_map_existing.toml",
                "study_area": "Naizin catchment",
                "focus_variant_id": "boussinesq_reused_gmsh",
                "comparison_family_key": "shared_support_cross_solver",
                "comparison_family_label": "Same Support, Different Solvers",
                "comparison_family_deck": (
                    "These cases keep the spatial support fixed so the main signal comes from "
                    "solver-family differences rather than from a support change."
                ),
                "comparison_family_order": 10,
                "comparison_case_order": 10,
                "observable_names": ["watertable_elevation", "watertable_depth", "head_timeseries"],
                "variant_labels": {
                    "mf6_reference_gmsh": "MODFLOW 6 on committed Gmsh mesh",
                    "boussinesq_reused_gmsh": "Boussinesq reusing the same mesh",
                },
            },
        ),
        _build_method_comparison_case_spec(
            slug="ex12_mf6_nwt_moderate_same_s60",
            title="MF6 vs NWT on the Same 60x60 Grid",
            deck="Annual moderate comparison on one shared structured grid, isolating MODFLOW-family differences from mesh effects.",
            summary=(
                "This case compares MODFLOW 6 and MODFLOW-NWT on the exact same 60x60 structured "
                "support. It keeps the more readable annual moderate forcing while removing the mesh "
                "family difference, so the page focuses on solver behaviour, native flux diagnostics, "
                "and execution-time spread."
            ),
            what_it_shows=(
                "How MODFLOW 6 and MODFLOW-NWT diverge when the spatial support is held strictly constant.",
                "How point chronicles, outlet flux, map snapshots, and native flux panels complement one another on the same benchmark.",
                "How execution-time bars look when the comparison does not mix structured and triangular supports.",
            ),
            comparison_config_path="examples/projects/launcher_simulation/run_method_comparison_mf6_vs_nwt_same_regular_mesh_moderate.toml",
            source_paths=(
                "examples/projects/launcher_simulation/run_demonstrative_annual_moderate_mf6_structured.toml",
                "examples/projects/launcher_simulation/run_demonstrative_annual_moderate_nwt.toml",
                "examples/projects/launcher_simulation/method_comparison/ex12_mf6_nwt_moderate_same_s60/comparison_manifest.json",
            ),
            case_setup=(
                "Reference variant: MODFLOW 6 on the 60x60 structured grid.",
                "Candidate variant: MODFLOW-NWT on the same 60x60 structured grid.",
                "Compared observables mix full maps (`head`, `depth`, `outflow_drain`), three head probes, one outlet-flux chronicle, native flux panels, and execution-time bars.",
            ),
            key_parameters=(
                "Support equality is the main control knob here: both variants use the same `mesh_label = \"sgrid_60x60\"`, so disagreements are not attributable to a mesh-family change.",
                "`run_method_comparison_mf6_vs_nwt_same_regular_mesh_moderate.toml` selects the observables that stay comparable across the two MODFLOW families.",
                "Use the outlet-flux and native-flux observables together: the outlet curve shows integrated export, while the native panels reveal how each code reports internal drainage/accumulation terms.",
            ),
            how_to_read=(
                "Start with the map and point metrics because this is the cleanest solver-only comparison in the section.",
                "Then inspect the flux and execution-time observables to see whether numerical agreement and runtime cost move together or not.",
                "If a discrepancy looks large, do not blame the mesh first: this page is intentionally built to remove that degree of freedom.",
            ),
            study_area="Example12 / Naizin",
            focus_variant_id="nwt_mod_s60",
            comparison_family_key="shared_support_cross_solver",
            comparison_family_label="Same Support, Different Solvers",
            comparison_family_deck=(
                "These cases keep the spatial support fixed so the main signal comes from "
                "solver-family differences rather than from a support change."
            ),
            comparison_family_order=10,
            comparison_case_order=20,
        ),
        _build_method_comparison_case_spec(
            slug="ex12_mf6_nwt_moderate",
            title="MF6 Triangular vs NWT Structured on Moderate Forcing",
            deck="Annual moderate comparison where both solver family and mesh family change, with a common fine raster used for map alignment.",
            summary=(
                "This case compares a MODFLOW 6 run on the committed triangular support against a "
                "MODFLOW-NWT run on the historical 60x60 structured grid. It keeps the same moderate "
                "annual forcing as the shared-grid comparison but now mixes support families, so the "
                "page documents the combined effect of solver choice and spatial discretization."
            ),
            what_it_shows=(
                "How solver and support differences accumulate when the comparison no longer uses one identical mesh.",
                "How a fine common raster and an intersection extent make map comparisons possible across incompatible supports.",
                "How point chronicles and outlet flux help decide whether disagreement is local, diffuse, or tied to basin export.",
            ),
            comparison_config_path="examples/projects/launcher_simulation/run_method_comparison_mf6_vs_nwt_different_meshes_moderate.toml",
            source_paths=(
                "examples/projects/launcher_simulation/run_demonstrative_annual_moderate_mf6_precomputed_mesh_input.toml",
                "examples/projects/launcher_simulation/run_demonstrative_annual_moderate_nwt.toml",
                "examples/projects/launcher_simulation/method_comparison/ex12_mf6_nwt_moderate/comparison_manifest.json",
            ),
            case_setup=(
                "Reference variant: MODFLOW 6 on the committed triangular mesh.",
                "Candidate variant: MODFLOW-NWT on the 60x60 structured grid.",
                "Map observables are resampled on a shared fine raster over the support intersection before parity metrics are computed.",
            ),
            key_parameters=(
                "`[method_comparison.fine_raster] enabled = true` is essential here because the compared meshes are not natively aligned cell by cell.",
                "`extent_mode = \"intersection\"` keeps the comparison on the spatial footprint both supports actually share.",
                "Read outlet-flux differences with more caution than in the same-grid case: they now reflect both solver behaviour and support discretization.",
            ),
            how_to_read=(
                "Treat this page as a mixed solver-and-support comparison, not as a pure solver benchmark.",
                "Read the parity metrics after checking the support mismatch described in the case setup; otherwise the numbers look more absolute than they really are.",
                "Use this page to understand what changes when you leave the shared-support regime used by the tighter comparison cases.",
            ),
            study_area="Example12 / Naizin",
            focus_variant_id="nwt_mod_s60",
            comparison_family_key="mixed_support_regime",
            comparison_family_label="Different Supports, Same Regime",
            comparison_family_deck=(
                "These cases keep the forcing regime fixed but intentionally change the mesh family, "
                "so the page captures both solver differences and support-transfer effects."
            ),
            comparison_family_order=20,
            comparison_case_order=10,
        ),
        _build_method_comparison_case_spec(
            slug="example12_mf6_vs_nwt_different_meshes_demonstrative",
            title="MF6 Triangular vs NWT Structured on Demonstrative Forcing",
            deck="Different-support comparison on the more expressive demonstrative annual setup, including flux and timing diagnostics.",
            summary=(
                "This case reuses the demonstrative annual forcing chosen to make temporal head changes "
                "and drainage signatures easier to read. It compares the committed triangular MODFLOW 6 "
                "run against the structured MODFLOW-NWT baseline, again through a shared fine raster, but "
                "with a forcing regime designed for stronger visual contrast than the moderate case."
            ),
            what_it_shows=(
                "How the different-support MF6/NWT comparison behaves when the forcing regime is tuned for stronger visible contrast.",
                "How the same observable set can be reused across moderate and demonstrative regimes to separate regime effects from support effects.",
                "How execution-time bars and flux panels behave on a more showcase-oriented scenario.",
            ),
            comparison_config_path="examples/projects/launcher_simulation/run_method_comparison_mf6_vs_nwt_different_meshes_demonstrative.toml",
            source_paths=(
                "examples/projects/launcher_simulation/run_demonstrative_annual_mf6_precomputed_mesh_input.toml",
                "examples/projects/launcher_simulation/run_demonstrative_annual_nwt.toml",
                "examples/projects/launcher_simulation/method_comparison/example12_mf6_vs_nwt_different_meshes_demonstrative/comparison_manifest.json",
            ),
            case_setup=(
                "Reference variant: MODFLOW 6 on the committed triangular support.",
                "Candidate variant: MODFLOW-NWT on the 60x60 structured support.",
                "Compared observables mirror the moderate different-support case so the main reading change is the forcing regime, not the observable list.",
            ),
            key_parameters=(
                "The demonstrative forcing/hydraulic setup is chosen to make temporal and drainage signatures easier to read than in the softened moderate case.",
                "The fine-raster comparison remains active, so map metrics are still computed after resampling onto a common grid.",
                "Use this page alongside the moderate different-support case to separate regime sensitivity from mesh-family sensitivity.",
            ),
            how_to_read=(
                "Compare this page to the moderate different-support case before drawing conclusions about the mesh effect alone.",
                "If a mismatch grows mainly here, the forcing regime is amplifying it; if it stays similar, the support transfer is probably the dominant cause.",
                "Do not read the demonstrative label as ‘more correct’; it is a more expressive scenario, not a stronger validation claim.",
            ),
            study_area="Example12 / Naizin",
            focus_variant_id="nwt_demo_structured",
            comparison_family_key="mixed_support_regime",
            comparison_family_label="Different Supports, Same Regime",
            comparison_family_deck=(
                "These cases keep the forcing regime fixed but intentionally change the mesh family, "
                "so the page captures both solver differences and support-transfer effects."
            ),
            comparison_family_order=20,
            comparison_case_order=20,
        ),
        _build_method_comparison_case_spec(
            slug="ex12_multi_method_moderate",
            title="Four-Method Moderate Suite on Example12",
            deck="One annual moderate suite spanning MF6 and NWT on structured support plus MF6 and Boussinesq on committed triangles.",
            summary=(
                "This case expands the comparison from two variants to four. It combines one same-grid "
                "solver comparison (MF6 vs NWT on 60x60) with one same-solver support comparison "
                "(MF6 structured vs MF6 triangular), then adds Boussinesq on the committed triangular "
                "mesh to expose a broader method family spread under the same moderate forcing."
            ),
            what_it_shows=(
                "How one page can separate solver-family effects, support-family effects, and a broader method-family spread.",
                "How multi-variant map comparisons and point chronicles stay interpretable when one reference variant is kept explicit.",
                "How outlet flux, native flux panels, and execution times complement the map-based metrics in a four-variant suite.",
            ),
            comparison_config_path="examples/projects/launcher_simulation/run_method_comparison_example12_multi_method_moderate.toml",
            source_paths=(
                "examples/projects/launcher_simulation/run_demonstrative_annual_moderate_mf6_structured.toml",
                "examples/projects/launcher_simulation/run_demonstrative_annual_moderate_nwt.toml",
                "examples/projects/launcher_simulation/run_demonstrative_annual_moderate_mf6_precomputed_mesh_input.toml",
                "examples/projects/launcher_simulation/run_demonstrative_annual_moderate_boussinesq_precomputed_mesh_input.toml",
                "examples/projects/launcher_simulation/method_comparison/ex12_multi_method_moderate/comparison_manifest.json",
            ),
            case_setup=(
                "Reference variant: MODFLOW 6 on the 60x60 structured grid.",
                "Additional variants: MODFLOW-NWT on the same grid, MODFLOW 6 on committed triangles, and Boussinesq on the same committed triangles.",
                "The case keeps one observable family across all variants so the page can separate solver and support effects without changing the reading frame.",
            ),
            key_parameters=(
                "The chosen reference variant matters more here than in the two-variant pages because every metric is read relative to `mf6_mod_s60`.",
                "The two triangular variants share the same committed support, which helps isolate the solver-family jump from MF6 to Boussinesq once you are already off the structured grid.",
                "Use the execution-time bars as a complement, not a ranking by itself: the suite mixes different support families and solver implementations on purpose.",
            ),
            how_to_read=(
                "Start with the same-grid MF6/NWT interpretation, then move to the same-solver MF6 structured-vs-triangular shift, then read the Boussinesq triangular variant last.",
                "This page is not meant to collapse everything into one scalar ranking; it is meant to show which comparison axis explains each mismatch.",
                "If the suite feels dense, use the dedicated two-variant cases first and come back here for synthesis.",
            ),
            study_area="Example12 / Naizin",
            focus_variant_id="bouss_mod_tri",
            comparison_family_key="multi_method_suites",
            comparison_family_label="Multi-Method Suites",
            comparison_family_deck=(
                "These cases keep more than two variants on one page so the reader can separate "
                "solver-family, support-family, and runtime-family effects without opening several "
                "independent comparisons."
            ),
            comparison_family_order=30,
            comparison_case_order=10,
        ),
        _build_method_comparison_case_spec(
            slug="ex12_multi_method_moderate_causes",
            title="Four-Method Moderate Suite with Surface-Excess Diagnostics",
            deck="Diagnostic extension of the four-method moderate suite, adding surface-excess observables and Boussinesq budget diagnostics.",
            summary=(
                "This case keeps the same four variants as the moderate suite but adds observables "
                "that only make sense for the triangular/Boussinesq side of the comparison: surface-"
                "excess time series, a surface-excess map, and an explicit budget-diagnostics figure. "
                "It is the diagnostic companion page for understanding where the multi-method spread comes from."
            ),
            what_it_shows=(
                "How a multi-method suite can be extended with targeted diagnostic observables instead of only repeating the same state metrics.",
                "How Boussinesq-specific surface-excess and budget views help explain disagreements seen in the more generic four-method page.",
                "How the same comparison backbone can support both a compact synthesis page and a more causal diagnostic page.",
            ),
            comparison_config_path="examples/projects/launcher_simulation/.__runtime_method_comparison_example12_multi_method_moderate_causes.toml",
            source_paths=(
                "examples/projects/launcher_simulation/run_method_comparison_example12_multi_method_moderate.toml",
                "examples/projects/launcher_simulation/.__runtime_method_comparison_example12_multi_method_moderate_causes.toml",
                "examples/projects/launcher_simulation/method_comparison/ex12_multi_method_moderate_causes/comparison_manifest.json",
            ),
            case_setup=(
                "Base variants are identical to the four-method moderate suite: MF6 structured, NWT structured, MF6 triangular, and Boussinesq triangular.",
                "Additional observables expose surface-excess response and Boussinesq budget structure rather than only the shared state variables.",
                "The page is intentionally denser because it is meant for diagnosis after reading the simpler synthesis page.",
            ),
            key_parameters=(
                "This config keeps the multi-method backbone but adds observables that are diagnostic rather than universally shared across all methods.",
                "Use the surface-excess series and map to explain why the Boussinesq triangular variant departs from the MODFLOW variants under moderate forcing.",
                "The budget diagnostics are explanatory aids, not a replacement for the comparable cross-variant metrics shown on the simpler suite page.",
            ),
            how_to_read=(
                "Read this page after the simpler four-method suite, not before it.",
                "Use it when you need a causal explanation for one mismatch, especially on the Boussinesq triangular branch, rather than a first-pass comparison overview.",
                "Keep in mind that not every diagnostic observable exists for every method, so this page is partly asymmetric by design.",
            ),
            study_area="Example12 / Naizin",
            focus_variant_id="bouss_mod_tri",
            comparison_family_key="multi_method_suites",
            comparison_family_label="Multi-Method Suites",
            comparison_family_deck=(
                "These cases keep more than two variants on one page so the reader can separate "
                "solver-family, support-family, and runtime-family effects without opening several "
                "independent comparisons."
            ),
            comparison_family_order=30,
            comparison_case_order=20,
        ),
        *_load_json_gallery_case_specs("code_comparison_cases.json"),
    )
    validation_specs = tuple(
        GalleryCaseSpec(
            slug=record.slug,
            title=record.title,
            category="validation",
            deck=record.deck,
            summary=record.summary,
            what_it_shows=record.what_it_shows,
            reproduction_command=record.reproduction_command,
            source_paths=record.source_paths,
            generator="validation_case",
            image_assets=(),
            case_setup=record.case_setup,
            reference_highlights=record.reference_highlights,
            equations_rst=record.equations_rst,
            metadata=record.metadata,
        )
        for record in build_validation_case_records()
    )
    calibration_specs = tuple(
        GalleryCaseSpec(
            slug=record.slug,
            title=record.title,
            category="calibration",
            deck=record.deck,
            summary=record.summary,
            what_it_shows=record.what_it_shows,
            reproduction_command=record.reproduction_command,
            source_paths=record.source_paths,
            generator="calibration_case",
            image_assets=(),
            case_setup=record.case_setup,
            key_parameters=record.key_parameters,
            how_to_read=record.how_to_read,
            next_steps=record.next_steps,
            metadata=record.metadata,
        )
        for record in build_calibration_case_records()
    )
    return (
        static_specs
        + validation_specs
        + calibration_specs
        + build_repo_mesh_gallery_case_specs()
    )


__all__ = [
    "CATEGORY_SPECS",
    "GalleryCaseSpec",
    "GalleryCategorySpec",
    "GalleryImageAsset",
    "GalleryMetricSpec",
    "build_gallery_specs",
]
