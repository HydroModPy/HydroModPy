"""Regional-lab gallery family extracted from the main manifest."""

from __future__ import annotations

from typing import Any

from .gallery_schema import (
    GalleryCaseSpec,
    GalleryImageAsset,
    GalleryMetricSpec,
    _format_int,
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
_SIMULATION_STATIC_ROOT = "docs/readthedocs/source/_static/capability_gallery/simulation"

_DEFAULT_REGIONAL_LAB_NEXT_STEPS = (
    "Switch `execute = true` in the focused overlay config when the dry plan looks correct and you want to launch the child workflow.",
    "Use these orchestration pages as the planning complement to the individual simulation and comparison cases already exposed elsewhere in the gallery.",
)


def _static_regional_lab_assets(slug: str) -> tuple[str, ...]:
    root = f"{_SIMULATION_STATIC_ROOT}/{slug}"
    return (
        f"{root}_plan.json",
        f"{root}_report.json",
        f"{root}_summary.md",
        f"{root}_site_inventory.csv",
        f"{root}_recipe_summary.csv",
        f"{root}_cluster_summary.csv",
        f"{root}_case_matrix.csv",
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
        reproduction_command="python -m tools.doc_gallery",
        source_paths=_static_regional_lab_assets(slug) + source_paths,
        generator="copy_assets",
        image_assets=(
            GalleryImageAsset(
                filename=f"{slug}.png",
                caption=(
                    f"Dry-plan synthesis for {title.lower()}: site or candidate coverage, "
                    "recipe summary, and planning metrics."
                ),
                alt_text=f"Regional lab dry-plan synthesis for {title}",
                source_path=f"{_SIMULATION_STATIC_ROOT}/{slug}.png",
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
            "static_summary_path": f"{_SIMULATION_STATIC_ROOT}/{slug}_summary.json",
            "regional_lab_summary_path": f"{_SIMULATION_STATIC_ROOT}/{slug}_summary.json",
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


def build_regional_lab_specs() -> tuple[GalleryCaseSpec, ...]:
    return (
        GalleryCaseSpec(
            slug="regional_lab_headwater_100km2_dry_plan",
            title="Regional Lab Dry Plan on Headwater 100 km2",
            category="simulation",
            deck="Dry-run orchestration example showing how one regional site catalog expands into simulation and comparison recipes.",
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
            reproduction_command="python -m tools.doc_gallery",
            source_paths=(
                "hydromodpy/analysis/batch/__init__.py",
                "hydromodpy/analysis/batch/config.py",
                "hydromodpy/analysis/batch/runtime.py",
                *_static_regional_lab_assets("regional_lab_headwater_100km2_dry_plan"),
            ),
            generator="copy_assets",
            image_assets=(
                GalleryImageAsset(
                    filename="regional_lab_headwater_100km2_dry_plan.png",
                    caption=(
                        "Dry-plan synthesis for the committed regional-lab example: site/recipe "
                        "matrix, recipe coverage, and planning summary."
                    ),
                    alt_text="Regional lab dry-plan synthesis for the headwater 100 km2 example",
                    source_path=(
                        "docs/readthedocs/source/_static/capability_gallery/simulation/"
                        "regional_lab_headwater_100km2_dry_plan.png"
                    ),
                ),
            ),
            metric_specs=_REGIONAL_LAB_METRIC_SPECS,
            case_setup=(
                "Launcher family: `regional_lab`, sitting above child `simulation` and `comparison` launchers.",
                "Example scope: one small Brittany site catalog with one fully runnable headwater site and several inventory-only or screening sites.",
                "The committed example starts with `execute = false`, so the page documents planning, selection, and reporting rather than child-run results.",
            ),
            key_parameters=(
                "`[regional_lab.catalog]` defines how site metadata and path-like config references are loaded from the catalog.",
                '`[regional_lab.selection] tags = ["mesh_ready"]` filters the population before any recipe expansion happens.',
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
                "Use this page as the orchestration complement to the individual simulation and comparison cases already exposed elsewhere in the gallery.",
            ),
            walkthrough_doc="getting_started/simulation-walkthrough",
            walkthrough_title="the Simulation walkthrough",
            metadata={
                "static_summary_path": (
                    "docs/readthedocs/source/_static/capability_gallery/simulation/"
                    "regional_lab_headwater_100km2_dry_plan_summary.json"
                ),
                "regional_lab_summary_path": (
                    "docs/readthedocs/source/_static/capability_gallery/simulation/"
                    "regional_lab_headwater_100km2_dry_plan_summary.json"
                ),
                "study_area": "Brittany regional laboratory",
                "process_families": ["planning", "simulation", "comparison", "reporting"],
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
                'How `required_fields = ["simulation_reference_config"]` turns missing references into explicit recipe-level gaps.',
                "How recipe-specific overlay configs keep the reproduction command precise without duplicating the whole laboratory definition.",
            ),
            regional_lab_config_path=(
                f"{_SIMULATION_STATIC_ROOT}/regional_lab_headwater_100km2_mf6_reference_recipe_summary.json"
            ),
            source_paths=(
                "hydromodpy/analysis/batch/__init__.py",
                "hydromodpy/analysis/batch/config.py",
                "hydromodpy/analysis/batch/runtime.py",
            ),
            metric_specs=_REGIONAL_LAB_RECIPE_METRIC_SPECS,
            case_setup=(
                "Base lab config: `config_headwater_100km2_lab.toml` selects `mesh_ready` sites, enriches the headwater cluster through rules, and defines three reusable recipes.",
                "Overlay config: `config_headwater_100km2_lab_mf6_reference.toml` keeps only the `mf6_reference` recipe enabled and writes to a dedicated output directory.",
                "Child-run contract: the recipe reads `simulation_reference_config` from each candidate site row rather than deriving one path from naming conventions alone.",
            ),
            key_parameters=(
                '`[[regional_lab.recipe]] id = "mf6_reference"` plus the overlay `enabled` flags define the focused orchestration slice documented by this page.',
                '`families = ["headwater"]` and `scales = ["100km2"]` scope the recipe before any child config path is resolved.',
                '`required_fields = ["simulation_reference_config"]` is the gate that separates the one runnable outlet from the two inventory-only headwater sites.',
                '`config_path_template = "{simulation_reference_config}"` delegates the concrete simulation config choice to the catalog row.',
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
                "recipe. It shows how one comparison workflow is carried as a reusable recipe, "
                "planned only where the catalog exposes one backend-comparison config, and reported "
                "with explicit gaps on the remaining headwater sites."
            ),
            what_it_shows=(
                "How `regional_lab` can orchestrate `comparison` launchers, not only single-run simulations.",
                "How one comparison recipe reuses the same headwater site selection while depending on a different catalog field than the MF6 replay recipe.",
                "How the dry plan remains useful even when only one site is currently comparison-ready.",
            ),
            regional_lab_config_path=(
                f"{_SIMULATION_STATIC_ROOT}/regional_lab_headwater_100km2_backend_compare_recipe_summary.json"
            ),
            source_paths=(
                "hydromodpy/analysis/batch/__init__.py",
                "hydromodpy/analysis/batch/config.py",
                "hydromodpy/analysis/batch/runtime.py",
            ),
            metric_specs=_REGIONAL_LAB_RECIPE_METRIC_SPECS,
            case_setup=(
                "Base lab config: the same selected headwater population is reused, so the page isolates recipe logic rather than changing the site inventory.",
                "Overlay config: `config_headwater_100km2_lab_backend_compare.toml` keeps only the `backend_compare` recipe enabled and writes to its own output root.",
                "Child-run contract: the recipe reads `backend_comparison_config` from each site row and expands into `comparison` child runs.",
            ),
            key_parameters=(
                '`launcher = "comparison"` shows that `regional_lab` can plan solver-comparison suites as first-class child workflows.',
                '`required_fields = ["backend_comparison_config"]` is what turns the two inventory-only headwater sites into visible comparison gaps.',
                '`config_path_template = "{backend_comparison_config}"` keeps the recipe generic while the site catalog remains the source of truth for child inputs.',
                "The overlay keeps the other recipes disabled so the page documents one comparison workflow rather than the full laboratory at once.",
            ),
            how_to_read=(
                "Start with the matrix to confirm that the backend-comparison recipe currently lands on one validated outlet only.",
                "Use the coverage summary to separate recipe reach from recipe quality: one planned case can still be valuable if the gaps stay explicit.",
                "Read the text panel last to connect those gaps to catalog maturity rather than to launcher failure.",
            ),
            process_families=("planning", "comparison", "reporting"),
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
                "How two comparison recipes can coexist in one laboratory while pointing to different child configs and modelling questions.",
                "How the transient backend-comparison recipe stays separate from the simpler backend-comparison recipe instead of overloading one flat page.",
                "How recipe overlays can document a more specific transient workflow without cloning the site catalog or cluster rules.",
            ),
            regional_lab_config_path=(
                f"{_SIMULATION_STATIC_ROOT}/regional_lab_headwater_100km2_transient_backend_compare_recipe_summary.json"
            ),
            source_paths=(
                "hydromodpy/analysis/batch/__init__.py",
                "hydromodpy/analysis/batch/config.py",
                "hydromodpy/analysis/batch/runtime.py",
            ),
            metric_specs=_REGIONAL_LAB_RECIPE_METRIC_SPECS,
            case_setup=(
                "Base lab config: the selected headwater sites and cluster rules are unchanged so the page isolates the transient recipe, not the site population.",
                "Overlay config: `config_headwater_100km2_lab_transient_backend_compare.toml` keeps only the `transient_backend_compare` recipe enabled.",
                "Child-run contract: the recipe reads `transient_backend_comparison_config` from each site row and expands into the transient pulsed-recharge comparison suite.",
            ),
            key_parameters=(
                '`id = "transient_backend_compare"` keeps the transient question separate from the simpler backend-comparison recipe instead of collapsing both into one card.',
                '`required_fields = ["transient_backend_comparison_config"]` makes the missing transient child configs visible as coverage gaps rather than silent filtering.',
                '`launcher = "comparison"` plus the recipe-specific config path field is what lets one lab coordinate several comparison families in parallel.',
                "The overlay config gives this page one exact reproduction command while preserving the shared base laboratory definition.",
            ),
            how_to_read=(
                "Read the matrix first to see that the transient comparison recipe currently has the same one runnable outlet and two explicit gaps.",
                "Use the coverage bar next to compare this transient slice with the simpler backend-comparison slice: same population, different child contract.",
                "Use the planning summary last to keep the interpretation at the orchestration level before diving into the child comparison page itself.",
            ),
            process_families=("planning", "comparison", "reporting"),
            workflow_case_order=40,
            metadata={
                "regional_lab_view_kind": "recipe",
                "regional_lab_recipe_id": "transient_backend_compare",
                "regional_lab_recipe_label": "Transient backend comparison",
                "mesh_supports": ["committed_triangular_mesh_input"],
            },
        ),
    )


__all__ = ["build_regional_lab_specs"]
