"""Mesh gallery family extracted from the main manifest."""

from __future__ import annotations

from .gallery_schema import (
    GalleryCaseSpec,
    GalleryImageAsset,
    GalleryMetricSpec,
    _format_float,
    _format_int,
    _format_scientific,
)

MESH_GALLERY_METRIC_SPECS = (
    GalleryMetricSpec("Nodes", "node_count", _format_int),
    GalleryMetricSpec("Cells", "cell_count", _format_int),
    GalleryMetricSpec("River edges", "river_edge_count", _format_int),
    GalleryMetricSpec("Geology interfaces", "geology_interface_edge_count", _format_int),
)

_MESH_DIAGNOSTIC_METRIC_SPECS = (
    GalleryMetricSpec("Triangle cells", "triangle_cell_count", _format_int),
    GalleryMetricSpec("Min angle (p05)", "min_angle_p05_deg", _format_float("deg", precision=1)),
    GalleryMetricSpec("Aspect ratio (p95)", "aspect_ratio_p95", _format_float("", precision=2)),
    GalleryMetricSpec("Area (p05)", "area_p05_m2", _format_scientific("m2", precision=2)),
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


def build_mesh_static_specs() -> tuple[GalleryCaseSpec, ...]:
    return (
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
                "python -m tools.mesh_bundle_viewer --config examples/projects/08_mesh_viewer/config_example.toml"
            ),
            source_paths=(
                "examples/projects/08_mesh_viewer/config_example.toml",
                "examples/projects/08_mesh_viewer/default_bundle/README.md",
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
            metric_specs=MESH_GALLERY_METRIC_SPECS,
            metadata={"config_path": "examples/projects/08_mesh_viewer/config_example.toml"},
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
                "examples/projects/07_mesh_gallery/10km2/mesh_s3_10km2_outlet_1_geology_rivers_buffer30/bundle/nodes.csv",
                "examples/projects/07_mesh_gallery/10km2/mesh_s3_10km2_outlet_1_geology_rivers_buffer30/bundle/cells.csv",
                "examples/projects/07_mesh_gallery/10km2/mesh_s3_10km2_outlet_1_geology_rivers_buffer30/bundle/mesh_summary.json",
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
                    "examples/projects/07_mesh_gallery/10km2/"
                    "mesh_s3_10km2_outlet_1_geology_rivers_buffer30/bundle"
                )
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
                "examples/projects/07_mesh_gallery/10km2/mesh_s3_10km2_outlet_1_geology_rivers_buffer30/bundle/mesh_summary.json",
                "examples/projects/07_mesh_gallery/100km2/mesh_headwater_100km2_outlet_1_geology_rivers_buffer30/bundle/mesh_summary.json",
                "examples/projects/07_mesh_gallery/1000km2/mesh_1000km2_outlet_2_geology_rivers_buffer30/bundle/mesh_summary.json",
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
                            "examples/projects/07_mesh_gallery/10km2/"
                            "mesh_s3_10km2_outlet_1_geology_rivers_buffer30/bundle"
                        ),
                    },
                    {
                        "label": "100 km2 outlet 1",
                        "bundle_path": (
                            "examples/projects/07_mesh_gallery/100km2/"
                            "mesh_headwater_100km2_outlet_1_geology_rivers_buffer30/bundle"
                        ),
                    },
                    {
                        "label": "1000 km2 outlet 2",
                        "bundle_path": (
                            "examples/projects/07_mesh_gallery/1000km2/"
                            "mesh_1000km2_outlet_2_geology_rivers_buffer30/bundle"
                        ),
                    },
                ]
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
                "examples/projects/07_mesh_gallery/10km2/mesh_s3_10km2_outlet_1_geology_rivers_buffer30/bundle/cells.csv",
                "examples/projects/07_mesh_gallery/100km2/mesh_headwater_100km2_outlet_1_geology_rivers_buffer30/bundle/cells.csv",
                "examples/projects/07_mesh_gallery/1000km2/mesh_1000km2_outlet_2_geology_rivers_buffer30/bundle/cells.csv",
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
                            "examples/projects/07_mesh_gallery/10km2/"
                            "mesh_s3_10km2_outlet_1_geology_rivers_buffer30/bundle"
                        ),
                    },
                    {
                        "label": "100 km2 outlet 1",
                        "bundle_path": (
                            "examples/projects/07_mesh_gallery/100km2/"
                            "mesh_headwater_100km2_outlet_1_geology_rivers_buffer30/bundle"
                        ),
                    },
                    {
                        "label": "1000 km2 outlet 2",
                        "bundle_path": (
                            "examples/projects/07_mesh_gallery/1000km2/"
                            "mesh_1000km2_outlet_2_geology_rivers_buffer30/bundle"
                        ),
                    },
                ]
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
                "examples/projects/07_mesh_gallery/10km2/mesh_s3_10km2_outlet_1_geology_rivers_buffer30/bundle/nodes.csv",
                "examples/projects/07_mesh_gallery/10km2/mesh_s3_10km2_outlet_1_geology_rivers_buffer30/bundle/cells.csv",
                "examples/projects/07_mesh_gallery/10km2/mesh_s3_10km2_outlet_1_geology_rivers_buffer30/bundle/edges.csv",
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
                    "examples/projects/07_mesh_gallery/10km2/"
                    "mesh_s3_10km2_outlet_1_geology_rivers_buffer30/bundle"
                ),
                "zoom_fraction": 0.22,
            },
        ),
    )


__all__ = ["MESH_GALLERY_METRIC_SPECS", "build_mesh_static_specs"]
