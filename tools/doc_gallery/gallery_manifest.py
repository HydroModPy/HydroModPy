"""Declarative manifest for the illustrated capability gallery."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .mesh_case_registry import (
    MESH_GALLERY_SCALE_ORDER,
    iter_mesh_case_json_paths,
    load_mesh_case_metadata,
)
from .calibration_case_registry import build_calibration_case_records
from .validation_case_registry import build_validation_case_records


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
        title="Geographic Diagnostics",
        deck="Pre-solver watershed and data-overview figures that explain how one domain is assembled.",
        intro=(
            "These cases highlight the geographic side of the workflow: watershed context, "
            "DEM-based views, and the local data overlays that feed later modelling steps."
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


def build_gallery_specs() -> tuple[GalleryCaseSpec, ...]:
    """Return the v1 illustrated-gallery inventory."""

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
        GalleryCaseSpec(
            slug="geographic_watershed_overview",
            title="Watershed Data Overview",
            category="geographic",
            deck="Versioned watershed context figures copied into the documentation as stable teaching assets.",
            summary=(
                "This pair of figures documents the pre-solver side of HydroModPy. It shows how one "
                "watershed is contextualized before any flow run: local framing, DEM, and overlay-ready "
                "geographic inputs."
            ),
            what_it_shows=(
                "How a watershed can be documented before any groundwater solve, using only setup and data loading.",
                "How HydroModPy distinguishes a local watershed view from a broader DEM-oriented overview.",
                "How versioned example outputs can feed static documentation without executing notebooks during the build.",
            ),
            reproduction_command="python examples/projects/data_overview/run_data_overview.py",
            source_paths=(
                "examples/projects/data_overview/run_data_overview.py",
                "examples/projects/data_overview/project.toml",
                "examples/results/example13data/results_stable/_figures/watershed_dem.png",
                "examples/results/example13data/results_stable/_figures/watershed_local.png",
            ),
            generator="copy_assets",
            image_assets=(
                GalleryImageAsset(
                    filename="geographic_watershed_dem.png",
                    caption="DEM-oriented watershed overview copied from versioned example outputs.",
                    alt_text="Watershed DEM overview",
                    source_path="examples/results/example13data/results_stable/_figures/watershed_dem.png",
                ),
                GalleryImageAsset(
                    filename="geographic_watershed_local.png",
                    caption="Local watershed framing copied from versioned example outputs.",
                    alt_text="Watershed local overview",
                    source_path="examples/results/example13data/results_stable/_figures/watershed_local.png",
                ),
            ),
            case_setup=(
                "Launcher family: `data-overview`, so the workflow stops after setup, domain assembly, and data loading.",
                "Primary editable file: `examples/projects/data_overview/project.toml`.",
                "Committed figures are reused as stable teaching assets instead of rerunning the full example during doc builds.",
            ),
            key_parameters=(
                "`[geographic] catch_def`, `x_outlet`, and `y_outlet` decide where the watershed is extracted from.",
                "`[geographic] buff_area` controls how much regional context stays visible around the basin in the overview figures.",
                "`[domain] zone_ids` and `[domain.depth_model]` define the spatial support that later workflows would reuse.",
                "`[data] types` selects which thematic layers are loaded and therefore which overlays can appear on the basin.",
                "Date windows in `[data.hydrometry]`, `[data.intermittency]`, and `[data.oceanic]` change the queried observation horizon without changing the basin geometry.",
            ),
            how_to_read=(
                "Read the DEM-oriented figure first to understand the broader terrain setting and outlet placement.",
                "Read the local overview second to inspect which basin-scale overlays are available before any meshing or solving happens.",
                "If the basin outline looks wrong, check outlet coordinates and snap distance before changing downstream modelling options.",
            ),
            next_steps=(
                "Continue with :doc:`the data-overview walkthrough </getting_started/data-overview-walkthrough>` for a parameter-by-parameter reading strategy.",
                "When the watershed framing looks correct, move to :doc:`the simulation walkthrough </getting_started/simulation-walkthrough>` to add meshing and solving.",
            ),
            walkthrough_doc="getting_started/data-overview-walkthrough",
            walkthrough_title="the Data Overview walkthrough",
        ),
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
            deck="Map-wide comparison of MODFLOW 6 and Boussinesq on the same committed triangular catchment mesh.",
            summary=(
                "This case reuses two committed run folders for the same Naizin catchment mesh. It compares full "
                "water-table elevation and water-table depth maps at the last saved time step, then renders parity "
                "plots and compact error bars."
            ),
            what_it_shows=(
                "How two solver families can be compared on exactly the same triangular support.",
                "How map-wide parity plots complement scalar metrics such as MAE and RMSE.",
                "How comparison figures can be regenerated from committed run folders without rerunning the solvers.",
            ),
            reproduction_command=(
                "python -m launchers method-comparison run "
                "examples/projects/launcher_simulation/run_method_comparison_example12_map_existing.toml"
            ),
            source_paths=(
                "examples/projects/launcher_simulation/run_method_comparison_example12_map_existing.toml",
                "examples/projects/launcher_simulation/run_fast_mf6_mesh_catchment.toml",
                "examples/projects/launcher_simulation/run_fast_boussinesq_precomputed_mesh_input.toml",
                "examples/projects/launcher_simulation/results_simulations/example12_fast_mf6_mesh_catchment/_metrics.json",
                "examples/projects/launcher_simulation/results_simulations/example12_fast_mf6_mesh_catchment/_postprocess/watertable_elevation.npy",
                "examples/projects/launcher_simulation/results_simulations/example12_fast_mf6_mesh_catchment/_postprocess/watertable_depth.npy",
                "examples/projects/launcher_simulation/results_reused_real_meshes/example12_fast/results_simulations/flow_main__boussinesq/_boussinesq_summary.json",
                "examples/projects/launcher_simulation/results_reused_real_meshes/example12_fast/results_simulations/flow_main__boussinesq/_postprocess/watertable_elevation.npy",
                "examples/projects/launcher_simulation/results_reused_real_meshes/example12_fast/results_simulations/flow_main__boussinesq/_postprocess/watertable_depth.npy",
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
            ),
            key_parameters=(
                "The most important modelling choice is not a scalar parameter but support equality: both runs must use the same saved mesh if you want a fair map-wide comparison.",
                "`run_method_comparison_example12_map_existing.toml` defines which run folders are compared and which observables are sampled from them.",
                "The compared observables (`watertable_elevation`, `watertable_depth`) determine whether the figure emphasizes absolute state mismatch or near-surface response mismatch.",
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
            },
        ),
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
