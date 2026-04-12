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
    reference_highlights: tuple[str, ...] = ()
    equations_rst: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GalleryCategorySpec:
    """High-level grouping shown on the gallery landing pages."""

    slug: str
    title: str
    deck: str
    intro: str


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
    ),
    "geographic": GalleryCategorySpec(
        slug="geographic",
        title="Geographic Diagnostics",
        deck="Pre-solver watershed and data-overview figures that explain how one domain is assembled.",
        intro=(
            "These cases highlight the geographic side of the workflow: watershed context, "
            "DEM-based views, and the local data overlays that feed later modelling steps."
        ),
    ),
    "simulation": GalleryCategorySpec(
        slug="simulation",
        title="Simulation Workflows",
        deck="End-to-end solver runs rendered as stable documentation artifacts.",
        intro=(
            "These cases show complete launcher workflows: preprocessing, solver execution, "
            "transport when relevant, and the compact figures used to inspect the result."
        ),
    ),
}


_MESH_GALLERY_METRIC_SPECS = (
    GalleryMetricSpec("Nodes", "node_count", _format_int),
    GalleryMetricSpec("Cells", "cell_count", _format_int),
    GalleryMetricSpec("River edges", "river_edge_count", _format_int),
    GalleryMetricSpec("Geology interfaces", "geology_interface_edge_count", _format_int),
)


def build_repo_mesh_gallery_case_specs(*, repo_root=None) -> tuple[GalleryCaseSpec, ...]:
    """Discover versioned mesh-gallery cases imported under ``examples/mesh_gallery``."""

    scale_rank = {scale: index for index, scale in enumerate(MESH_GALLERY_SCALE_ORDER)}
    optional_metadata_keys = (
        "case_family_key",
        "case_family_label",
        "case_family_order",
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
        metadata = {
            "scale": scale,
            "scale_label": scale_label,
            "variant": variant,
            "variant_label": variant_label,
            "outlet_id": outlet_id,
            "comparison_group": f"{scale}::outlet::{outlet_id}",
            "comparison_group_title": f"{scale_label}, outlet {outlet_id}",
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
                    reference_highlights=tuple(str(item) for item in payload.get("reference_highlights", ())),
                    equations_rst=tuple(str(item) for item in payload.get("equations_rst", ())),
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
    return static_specs + validation_specs + build_repo_mesh_gallery_case_specs()


__all__ = [
    "CATEGORY_SPECS",
    "GalleryCaseSpec",
    "GalleryCategorySpec",
    "GalleryImageAsset",
    "GalleryMetricSpec",
    "build_gallery_specs",
]
