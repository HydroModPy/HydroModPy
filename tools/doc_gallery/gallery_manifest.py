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
    discovered_specs: list[GalleryCaseSpec] = []
    discovery_kwargs = {} if repo_root is None else {"repo_root": repo_root}
    for case_json_path in iter_mesh_case_json_paths(**discovery_kwargs):
        payload = load_mesh_case_metadata(case_json_path)
        slug = str(payload["slug"])
        title = str(payload["title"])
        discovered_specs.append(
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
                image_assets=(
                    GalleryImageAsset(
                        filename=f"{slug}_overview.png",
                        caption=str(
                            payload.get(
                                "image_caption",
                                f"Mesh overview rendered from the versioned bundle shipped with `{slug}`.",
                            )
                        ),
                        alt_text=str(payload.get("image_alt_text", f"{title} overview")),
                    ),
                ),
                metric_specs=_MESH_GALLERY_METRIC_SPECS,
                case_setup=tuple(str(item) for item in payload.get("case_setup", ())),
                reference_highlights=tuple(str(item) for item in payload.get("reference_highlights", ())),
                equations_rst=tuple(str(item) for item in payload.get("equations_rst", ())),
                metadata={
                    "scale": str(payload["scale"]),
                    "config_path": str(payload["config_path"]),
                },
            )
        )
    return tuple(
        sorted(
            discovered_specs,
            key=lambda spec: (
                scale_rank.get(str(spec.metadata.get("scale", "")), 999),
                spec.slug,
            ),
        )
    )


def build_gallery_specs() -> tuple[GalleryCaseSpec, ...]:
    """Return the v1 illustrated-gallery inventory."""

    static_specs = (
        GalleryCaseSpec(
            slug="mesh_sample_bundle",
            title="Mesh Sample Bundle",
            category="mesh",
            deck="Standalone overview of a tiny bundled mesh, with geology and topography panels.",
            summary=(
                "This sample bundle is the smallest self-contained mesh illustration shipped with "
                "the repository. It is stable enough for documentation and still exposes the main "
                "viewer concepts: cells, edges, rivers, geology interfaces, and topography rendering."
            ),
            what_it_shows=(
                "How the standalone bundle viewer turns one versioned mesh export into a didactic figure.",
                "How geology keys, river edges, and topographic information are surfaced in one compact layout.",
                "What a minimal bundle looks like when used as a reproducible documentation artifact.",
            ),
            reproduction_command=(
                "python -m tools.mesh_bundle_viewer --config examples/mesh_viewer/config_example.toml"
            ),
            source_paths=(
                "examples/mesh_viewer/config_example.toml",
                "examples/mesh_viewer/sample_bundle/README.md",
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
            slug="dupuit_fixed_head_1d",
            title="Dupuit Fixed-Head 1D",
            category="validation",
            deck="Lightweight 1D steady benchmark comparing a numerical profile to the Dupuit solution.",
            summary=(
                "This is the simplest analytical validation case in the current inventory. It is well "
                "suited to the documentation because the geometry, the reference solution, and the failure "
                "modes are all immediately readable on one figure."
            ),
            what_it_shows=(
                "How HydroModPy reproduces a steady unconfined profile between two imposed heads.",
                "How one validation page can combine the profile, the residual, and a few scalar metrics.",
                "What a minimal end-to-end scientific benchmark looks like in the current launcher workflow.",
            ),
            reproduction_command=(
                "python -m validation_cases.analytical.steady.dupuit_fixed_head_1d.run_case --no-show"
            ),
            source_paths=(
                "validation_cases/analytical/steady/dupuit_fixed_head_1d/README.md",
                "validation_cases/analytical/steady/dupuit_fixed_head_1d/reference.py",
                "validation_cases/analytical/steady/dupuit_fixed_head_1d/comparison.py",
                "validation_cases/analytical/steady/dupuit_fixed_head_1d/plotting.py",
                "validation_cases/analytical/steady/dupuit_fixed_head_1d/run_case.py",
                "validation_cases/analytical/steady/dupuit_fixed_head_1d/metadata.toml",
                "validation_cases/analytical/steady/dupuit_fixed_head_1d/tolerances.toml",
                "validation_cases/analytical/steady/dupuit_fixed_head_1d/config_modflownwt.toml",
            ),
            generator="validation_case",
            image_assets=(
                GalleryImageAsset(
                    filename="dupuit_fixed_head_1d_validation.png",
                    caption="Numerical mean profile, analytical Dupuit profile, and residual panel.",
                    alt_text="Dupuit fixed-head 1D validation plot",
                ),
            ),
            metric_specs=(
                GalleryMetricSpec("RMSE", "rms_error", _format_float("m", precision=4)),
                GalleryMetricSpec("Max abs error", "max_error", _format_float("m", precision=4)),
                GalleryMetricSpec("Cross-row spread", "row_spread", _format_scientific("m", precision=2)),
            ),
            case_setup=(
                "Homogeneous unconfined strip, 400 m long, discretized on a 5 x 40 grid.",
                "Fixed west head of 10.0 m and fixed east head of 5.0 m.",
                "No recharge, hydraulic conductivity 1e-4 m/s, aquifer thickness 20.0 m.",
            ),
            reference_highlights=(
                "The benchmark uses the steady 1D Dupuit approximation on a homogeneous aquifer with no recharge.",
                "The comparison is performed on the row-averaged numerical head profile along x.",
            ),
            equations_rst=(
                r"\frac{\mathrm{d}}{\mathrm{d}x}\left(K\,h\,\frac{\mathrm{d}h}{\mathrm{d}x}\right)=0",
                r"h(x)=\sqrt{h_w^2+\left(h_e^2-h_w^2\right)\frac{x-x_{\min}}{x_{\max}-x_{\min}}}",
            ),
            metadata={
                "comparison_import": (
                    "validation_cases.analytical.steady.dupuit_fixed_head_1d.comparison:"
                    "run_dupuit_fixed_head_comparison"
                ),
                "plotting_import": (
                    "validation_cases.analytical.steady.dupuit_fixed_head_1d.plotting:"
                    "plot_dupuit_fixed_head_comparison"
                ),
                "caller_file": "validation_cases/analytical/steady/dupuit_fixed_head_1d/run_case.py",
                "timeout": 600,
                "solver": "modflownwt",
            },
        ),
        GalleryCaseSpec(
            slug="dupuit_circular_island_ocean_2d",
            title="Dupuit Circular-Island Ocean 2D",
            category="validation",
            deck="2D coastal benchmark showing shoreline geometry, land heads, annular profile, and residuals.",
            summary=(
                "This benchmark is especially useful pedagogically because it validates both a boundary "
                "condition and a symmetry property. The figure is dense enough to teach with, while still "
                "remaining compact in a documentation page."
            ),
            what_it_shows=(
                "How the ocean boundary condition behaves on a radial-island synthetic geometry.",
                "How HydroModPy preserves radial symmetry on a Cartesian grid through annular averages.",
                "How a documentation figure can combine map views and profile-based validation in one page.",
            ),
            reproduction_command=(
                "python -m validation_cases.analytical.steady.dupuit_circular_island_ocean_2d.run_case --no-show"
            ),
            source_paths=(
                "validation_cases/analytical/steady/dupuit_circular_island_ocean_2d/README.md",
                "validation_cases/analytical/steady/dupuit_circular_island_ocean_2d/reference.py",
                "validation_cases/analytical/steady/dupuit_circular_island_ocean_2d/comparison.py",
                "validation_cases/analytical/steady/dupuit_circular_island_ocean_2d/plotting.py",
                "validation_cases/analytical/steady/dupuit_circular_island_ocean_2d/run_case.py",
                "validation_cases/analytical/steady/dupuit_circular_island_ocean_2d/metadata.toml",
                "validation_cases/analytical/steady/dupuit_circular_island_ocean_2d/tolerances.toml",
                "validation_cases/analytical/steady/dupuit_circular_island_ocean_2d/config_modflownwt.toml",
            ),
            generator="validation_case",
            image_assets=(
                GalleryImageAsset(
                    filename="dupuit_circular_island_ocean_2d_validation.png",
                    caption=(
                        "Synthetic DEM, final land heads, annular Dupuit profile, and radial residuals."
                    ),
                    alt_text="Dupuit circular island ocean 2D validation plot",
                ),
            ),
            metric_specs=(
                GalleryMetricSpec("RMSE", "rms_error", _format_float("m", precision=4)),
                GalleryMetricSpec("Max abs error", "max_error", _format_float("m", precision=4)),
                GalleryMetricSpec(
                    "Azimuthal spread", "azimuthal_spread", _format_float("m", precision=4)
                ),
                GalleryMetricSpec(
                    "Ocean head error", "ocean_head_max_error", _format_scientific("m", precision=2)
                ),
                GalleryMetricSpec(
                    "Min land freeboard", "land_clearance_min", _format_float("m", precision=4)
                ),
            ),
            case_setup=(
                "Synthetic circular island embedded in a 610 m x 610 m Cartesian grid sampled on 61 x 61 cells.",
                "Island radius 200 m, flat substratum at -5.0 m, sea level fixed at 0.0 m on the shoreline.",
                "Uniform recharge of 1.0 mm/day and hydraulic conductivity of 5e-6 m/s.",
            ),
            reference_highlights=(
                "The benchmark uses the steady radial Dupuit-Boussinesq equation on a flat substratum.",
                "HydroModPy's ocean boundary condition is checked against a fixed coastal head while the annular mean profile tests radial symmetry.",
            ),
            equations_rst=(
                r"\frac{1}{r}\frac{\mathrm{d}}{\mathrm{d}r}\left(r\,K\,H\,\frac{\mathrm{d}H}{\mathrm{d}r}\right)+R=0",
                r"H(r)^2=H(a)^2+\frac{R}{2K}\left(a^2-r^2\right)",
                r"h(r)=z_b+\sqrt{\left(h_{\mathrm{sea}}-z_b\right)^2+\frac{R}{2K}\left(a^2-r^2\right)}",
            ),
            metadata={
                "comparison_import": (
                    "validation_cases.analytical.steady.dupuit_circular_island_ocean_2d.comparison:"
                    "run_dupuit_circular_island_ocean_comparison"
                ),
                "plotting_import": (
                    "validation_cases.analytical.steady.dupuit_circular_island_ocean_2d.plotting:"
                    "plot_dupuit_circular_island_ocean_comparison"
                ),
                "caller_file": "validation_cases/analytical/steady/dupuit_circular_island_ocean_2d/run_case.py",
                "timeout": 900,
                "solver": "modflownwt",
            },
        ),
        GalleryCaseSpec(
            slug="late_time_unconfined_pumping_2d",
            title="Late-Time Unconfined Pumping 2D",
            category="validation",
            deck="Transient radial drawdown benchmark with late-time analytical comparison and symmetry checks.",
            summary=(
                "This transient case makes the gallery less static. It illustrates how HydroModPy compares "
                "an entire time-radius response surface to a late-time analytical proxy, while also checking "
                "azimuthal symmetry around the pumping well."
            ),
            what_it_shows=(
                "How one transient validation page can expose traces, residuals, and symmetry diagnostics together.",
                "How the late-time drawdown response is compared to a lightweight Theis-style proxy.",
                "How the validation inventory extends beyond steady profiles without requiring an interactive notebook.",
            ),
            reproduction_command=(
                "python -m validation_cases.analytical.transient.late_time_unconfined_pumping_2d.run_case --no-show"
            ),
            source_paths=(
                "validation_cases/analytical/transient/late_time_unconfined_pumping_2d/README.md",
                "validation_cases/analytical/transient/late_time_unconfined_pumping_2d/reference.py",
                "validation_cases/analytical/transient/late_time_unconfined_pumping_2d/comparison.py",
                "validation_cases/analytical/transient/late_time_unconfined_pumping_2d/plotting.py",
                "validation_cases/analytical/transient/late_time_unconfined_pumping_2d/run_case.py",
                "validation_cases/analytical/transient/late_time_unconfined_pumping_2d/metadata.toml",
                "validation_cases/analytical/transient/late_time_unconfined_pumping_2d/tolerances.toml",
                "validation_cases/analytical/transient/late_time_unconfined_pumping_2d/config_modflownwt.toml",
                "validation_cases/analytical/transient/common.py",
            ),
            generator="validation_case",
            image_assets=(
                GalleryImageAsset(
                    filename="late_time_unconfined_pumping_2d_validation.png",
                    caption=(
                        "Late-time drawdown traces, residual heatmap, and azimuthal-spread diagnostic."
                    ),
                    alt_text="Late-time unconfined pumping 2D validation plot",
                ),
            ),
            metric_specs=(
                GalleryMetricSpec(
                    "Space-time RMSE", "space_time_rmse", _format_float("m", precision=4)
                ),
                GalleryMetricSpec(
                    "Space-time max abs error",
                    "space_time_max_error",
                    _format_float("m", precision=4),
                ),
                GalleryMetricSpec(
                    "Final-time RMSE", "final_time_rmse", _format_float("m", precision=4)
                ),
                GalleryMetricSpec(
                    "Final-time max abs error",
                    "final_time_max_error",
                    _format_float("m", precision=4),
                ),
                GalleryMetricSpec(
                    "Azimuthal spread", "azimuthal_spread", _format_scientific("m", precision=2)
                ),
            ),
            case_setup=(
                "Transient unconfined flow on a 2000 m x 2000 m square domain discretized on a 101 x 101 grid.",
                "Uniform initial head of 30.0 m with all outer boundaries held at that same fixed head.",
                "One central pumping well at 1000 m3/day, hydraulic conductivity 1e-4 m/s, specific yield 0.15.",
                "The reference comparison starts after day 4.0 to target the late-time regime only.",
            ),
            reference_highlights=(
                "The benchmark is intentionally not a full Neuman solution; it uses a confined-equivalent late-time proxy for one unconfined pumping response.",
                "HydroModPy is checked both against the radial drawdown scaling and against azimuthal symmetry around the well.",
            ),
            equations_rst=(
                r"s(r,t)=\frac{Q}{4\pi T}E_1(u)",
                r"u=\frac{r^2S}{4Tt}",
                r"T=K\,h_{\mathrm{ref}},\qquad S=S_y",
            ),
            metadata={
                "comparison_import": (
                    "validation_cases.analytical.transient.late_time_unconfined_pumping_2d.comparison:"
                    "run_late_time_unconfined_pumping_comparison"
                ),
                "plotting_import": (
                    "validation_cases.analytical.transient.late_time_unconfined_pumping_2d.plotting:"
                    "plot_late_time_unconfined_pumping_comparison"
                ),
                "caller_file": "validation_cases/analytical/transient/late_time_unconfined_pumping_2d/run_case.py",
                "timeout": 900,
                "solver": "modflownwt",
            },
        ),
    )
    return static_specs + build_repo_mesh_gallery_case_specs()


__all__ = [
    "CATEGORY_SPECS",
    "GalleryCaseSpec",
    "GalleryCategorySpec",
    "GalleryImageAsset",
    "GalleryMetricSpec",
    "build_gallery_specs",
]
