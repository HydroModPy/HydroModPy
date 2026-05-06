"""Simulation gallery family extracted from the main manifest."""

from __future__ import annotations

from .gallery_schema import GalleryCaseSpec, GalleryImageAsset


def build_simulation_specs() -> tuple[GalleryCaseSpec, ...]:
    return (
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
            reproduction_command="python -m tools.doc_gallery",
            source_paths=(
                "examples/projects/09_capability_gallery/README.md",
                "examples/projects/09_capability_gallery/launcher_simulation/modflow6_gmsh_mesh_catchment/manifest.json",
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
                        "examples/projects/09_capability_gallery/launcher_simulation/"
                        "modflow6_gmsh_mesh_catchment/flow_state_triptych.png"
                    ),
                ),
                GalleryImageAsset(
                    filename="modflow6_gmsh_recharge_discharge_cumulative.png",
                    caption="Cumulative recharge and discharge curves from the same launcher run.",
                    alt_text="Cumulative recharge and discharge curves",
                    source_path=(
                        "examples/projects/09_capability_gallery/launcher_simulation/"
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
                        "examples/projects/09_capability_gallery/launcher_simulation/"
                        "modflow6_gmsh_mesh_catchment/flow_support_overview.png"
                    ),
                ),
            ),
            case_setup=(
                "Static gallery manifest: the committed capability-gallery manifest records the published assets and their generation context.",
                "Execution chain: geographic setup -> `mesh_catchment` -> runtime triangular mesh -> MODFLOW 6 flow -> MODFLOW 6 transport -> postprocess/display.",
                "Only selected synthesis figures are republished into `examples/projects/09_capability_gallery/`; the full run workspace stays outside the doc tree.",
            ),
            key_parameters=(
                "`[simulation.time] step_value`, `start_datetime`, and `end_datetime` define the time support of the run and the interpretation of the recharge chronology.",
                "`[data.recharge.sources] values`, `freq`, and `runoff_ratio` control the synthetic forcing that drives the cumulative recharge/discharge figure.",
                "`[flow.param.K.field]` and `[flow.param.Sy.field]` are the first groundwater parameters to modify when learning how heads and depths react.",
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
                "Then open :doc:`the shared-mesh simulation comparison case </capability_gallery/cases/example12_map_simulation_comparison>` to compare two solver families on the same support.",
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
            reproduction_command="python -m tools.doc_gallery",
            source_paths=(
                "examples/projects/09_capability_gallery/README.md",
                "examples/projects/09_capability_gallery/launcher_simulation/headwater_100km2_outlet_2_mf6_transient_reference/manifest.json",
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
                        "examples/projects/09_capability_gallery/launcher_simulation/"
                        "headwater_100km2_outlet_2_mf6_transient_reference/flow_state_triptych.png"
                    ),
                ),
                GalleryImageAsset(
                    filename="headwater_100km2_outlet_2_mf6_transient_reference_recharge_discharge_cumulative.png",
                    caption="Three-year cumulative recharge and discharge curves for the committed-mesh MF6 replay.",
                    alt_text="Cumulative recharge and discharge on the committed 100 km2 outlet-2 replay",
                    source_path=(
                        "examples/projects/09_capability_gallery/launcher_simulation/"
                        "headwater_100km2_outlet_2_mf6_transient_reference/recharge_discharge_cumulative.png"
                    ),
                ),
                GalleryImageAsset(
                    filename="headwater_100km2_outlet_2_mf6_transient_reference_watertable_elevation.png",
                    caption="Water-table elevation map from the reference transient replay.",
                    alt_text="Water-table elevation map for the committed 100 km2 outlet-2 replay",
                    source_path=(
                        "examples/projects/09_capability_gallery/launcher_simulation/"
                        "headwater_100km2_outlet_2_mf6_transient_reference/watertable_elevation.png"
                    ),
                ),
                GalleryImageAsset(
                    filename="headwater_100km2_outlet_2_mf6_transient_reference_watertable_depth.png",
                    caption="Water-table depth map from the reference transient replay.",
                    alt_text="Water-table depth map for the committed 100 km2 outlet-2 replay",
                    source_path=(
                        "examples/projects/09_capability_gallery/launcher_simulation/"
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
                        "examples/projects/09_capability_gallery/launcher_simulation/"
                        "headwater_100km2_outlet_2_mf6_transient_reference/flow_support_overview.png"
                    ),
                ),
            ),
            case_setup=(
                "Static gallery manifest: the committed capability-gallery manifest records the published assets and their generation context.",
                "The source run used a committed triangular mesh, the flow-only process chain, and common postprocess/display switches.",
                "Execution chain: committed `mesh_input` bundle -> MODFLOW 6 transient flow -> postprocess rasters and synthesis figures -> gallery publication.",
            ),
            key_parameters=(
                "`[mesh_input] mesh_path` and `bundle_dir` lock the support to the versioned 100 km2 outlet-2 mesh, which makes this page a support-reuse workflow rather than a meshing example.",
                "`[simulation.time] start_datetime`, `end_datetime`, and `step_value` define the three-year monthly replay window shown in the cumulative curves.",
                "`[[data.recharge.sources]] values`, `freq`, and `runoff_ratio` define the synthetic forcing chronology that drives the transient response.",
                "`[flow.param.K.field]`, `[flow.param.Sy.field]`, and `[flow.param.Ss.field]` are the main parameters to perturb when comparing this reference run against the more complex scenario overlays.",
            ),
            how_to_read=(
                "Open the support overview first to verify that the run reused the committed mesh bundle and sampled the structural surfaces as expected.",
                "Read the flow-state triptych next for the compact basin-wide synthesis, then use the direct water-table maps when you need one variable isolated.",
                "Use the cumulative recharge/discharge panel last to judge whether the imposed forcing and the integrated basin response remain coherent over the three-year window.",
            ),
            next_steps=(
                "Read :doc:`the simulation walkthrough </getting_started/simulation-walkthrough>` for the general mapping between config sections and displayed figures.",
                "Use the committed-mesh comparison pages in :doc:`the simulation-comparison section </capability_gallery/simulation_comparison>` when you want to compare this style of replay against other supports or solver families.",
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
    )


__all__ = ["build_simulation_specs"]
