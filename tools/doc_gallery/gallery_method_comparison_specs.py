"""Method-comparison gallery family extracted from the main manifest."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .gallery_schema import GalleryCaseSpec, GalleryImageAsset

_DEFAULT_METHOD_COMPARISON_NEXT_STEPS = (
    "Use :doc:`the gallery and validation reading guide </getting_started/reading-results-pages>` to distinguish example pages, method-comparison pages, and validation pages.",
    "Go back to :doc:`the simulation walkthrough </getting_started/simulation-walkthrough>` when you need to inspect one contributing run in isolation.",
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
        reproduction_command=(f"python -m hydromodpy run {comparison_config_path}"),
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


def build_method_comparison_specs() -> tuple[GalleryCaseSpec, ...]:
    return (
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
                "python -m hydromodpy run "
                "examples_legacy_2/projects/launcher_simulation/run_method_comparison_example12_map_existing.toml"
            ),
            source_paths=_augment_method_comparison_source_paths(
                "examples_legacy_2/projects/launcher_simulation/run_method_comparison_example12_map_existing.toml",
                (
                    "examples_legacy_2/projects/launcher_simulation/run_fast_mf6_mesh_catchment.toml",
                    "examples_legacy_2/projects/launcher_simulation/run_fast_boussinesq_precomputed_mesh_input.toml",
                    "examples_legacy_2/projects/launcher_simulation/method_comparison/example12_map_method_comparison/comparison_manifest.json",
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
                "comparison_config_path": "examples_legacy_2/projects/launcher_simulation/run_method_comparison_example12_map_existing.toml",
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
            comparison_config_path="examples_legacy_2/projects/launcher_simulation/run_method_comparison_mf6_vs_nwt_same_regular_mesh_moderate.toml",
            source_paths=(
                "examples_legacy_2/projects/launcher_simulation/run_demonstrative_annual_moderate_mf6_structured.toml",
                "examples_legacy_2/projects/launcher_simulation/run_demonstrative_annual_moderate_nwt.toml",
                "examples_legacy_2/projects/launcher_simulation/method_comparison/ex12_mf6_nwt_moderate_same_s60/comparison_manifest.json",
            ),
            case_setup=(
                "Reference variant: MODFLOW 6 on the 60x60 structured grid.",
                "Candidate variant: MODFLOW-NWT on the same 60x60 structured grid.",
                "Compared observables mix full maps (`head`, `depth`, `outflow_drain`), three head probes, one outlet-flux chronicle, native flux panels, and execution-time bars.",
            ),
            key_parameters=(
                'Support equality is the main control knob here: both variants use the same `mesh_label = "sgrid_60x60"`, so disagreements are not attributable to a mesh-family change.',
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
            comparison_config_path="examples_legacy_2/projects/launcher_simulation/run_method_comparison_mf6_vs_nwt_different_meshes_moderate.toml",
            source_paths=(
                "examples_legacy_2/projects/launcher_simulation/run_demonstrative_annual_moderate_mf6_precomputed_mesh_input.toml",
                "examples_legacy_2/projects/launcher_simulation/run_demonstrative_annual_moderate_nwt.toml",
                "examples_legacy_2/projects/launcher_simulation/method_comparison/ex12_mf6_nwt_moderate/comparison_manifest.json",
            ),
            case_setup=(
                "Reference variant: MODFLOW 6 on the committed triangular mesh.",
                "Candidate variant: MODFLOW-NWT on the 60x60 structured grid.",
                "Map observables are resampled on a shared fine raster over the support intersection before parity metrics are computed.",
            ),
            key_parameters=(
                "`[method_comparison.fine_raster] enabled = true` is essential here because the compared meshes are not natively aligned cell by cell.",
                '`extent_mode = "intersection"` keeps the comparison on the spatial footprint both supports actually share.',
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
            comparison_config_path="examples_legacy_2/projects/launcher_simulation/run_method_comparison_mf6_vs_nwt_different_meshes_demonstrative.toml",
            source_paths=(
                "examples_legacy_2/projects/launcher_simulation/run_demonstrative_annual_mf6_precomputed_mesh_input.toml",
                "examples_legacy_2/projects/launcher_simulation/run_demonstrative_annual_nwt.toml",
                "examples_legacy_2/projects/launcher_simulation/method_comparison/example12_mf6_vs_nwt_different_meshes_demonstrative/comparison_manifest.json",
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
                "Do not read the demonstrative label as â€˜more correctâ€™; it is a more expressive scenario, not a stronger validation claim.",
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
            comparison_config_path="examples_legacy_2/projects/launcher_simulation/run_method_comparison_example12_multi_method_moderate.toml",
            source_paths=(
                "examples_legacy_2/projects/launcher_simulation/run_demonstrative_annual_moderate_mf6_structured.toml",
                "examples_legacy_2/projects/launcher_simulation/run_demonstrative_annual_moderate_nwt.toml",
                "examples_legacy_2/projects/launcher_simulation/run_demonstrative_annual_moderate_mf6_precomputed_mesh_input.toml",
                "examples_legacy_2/projects/launcher_simulation/run_demonstrative_annual_moderate_boussinesq_precomputed_mesh_input.toml",
                "examples_legacy_2/projects/launcher_simulation/method_comparison/ex12_multi_method_moderate/comparison_manifest.json",
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
            comparison_config_path="examples_legacy_2/projects/launcher_simulation/.__runtime_method_comparison_example12_multi_method_moderate_causes.toml",
            source_paths=(
                "examples_legacy_2/projects/launcher_simulation/run_method_comparison_example12_multi_method_moderate.toml",
                "examples_legacy_2/projects/launcher_simulation/.__runtime_method_comparison_example12_multi_method_moderate_causes.toml",
                "examples_legacy_2/projects/launcher_simulation/method_comparison/ex12_multi_method_moderate_causes/comparison_manifest.json",
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
    )


__all__ = ["build_method_comparison_specs"]
