"""Mesh step - optional catchment meshing or external mesh loading."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.core.exceptions import ConfigError, MeshError
from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.mesh.gmsh_grid import load_planar_mesh
from hydromodpy.spatial.mesh.gmsh_grid.catchment_mesh_bundle_reader import (
    load_catchment_mesh_bundle,
)
from hydromodpy.spatial.mesh.gmsh_grid.runtime_support import (
    build_gmsh_support_metadata,
)
from hydromodpy.workflow.internals.state import LoadedState, MeshedState, PipelineState

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.spatial.mesh.config import MeshCatchmentConfig

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Optional mesh section resolution
# ---------------------------------------------------------------------------


def resolve_optional_mesh_section(
    raw_toml: Mapping[str, object],
) -> MeshCatchmentConfig | None:
    """Extract and validate the optional [mesh_catchment] section from raw TOML."""
    from hydromodpy.spatial.mesh.config import parse_mesh_catchment_batch_config_data
    from hydromodpy.spatial.mesh.launcher.runtime import get_optional_mesh_section

    section = get_optional_mesh_section(raw_toml)
    batch_section = raw_toml.get("mesh_catchment_batch")
    if batch_section is None:
        return section
    batch_cfg = parse_mesh_catchment_batch_config_data(batch_section)
    if batch_cfg.enabled:
        raise ConfigError(
            "Embedded [mesh_catchment_batch] is not supported in process_simulation. "
            "Use the dedicated mesh-catchment launcher for batch runs."
        )
    return section


def resolve_optional_mesh_input(
    raw_toml: Mapping[str, object],
    config_path: str | Path,
) -> dict[str, str] | None:
    """Resolve one optional external mesh-input block from raw launcher TOML."""
    from hydromodpy.core.config_kit.mesh_input import MeshInputConfig

    section = raw_toml.get("mesh_input")
    if section is None:
        return None
    if not isinstance(section, Mapping):
        raise ConfigError("[mesh_input] configuration must be a mapping when provided.")

    try:
        mesh_input = MeshInputConfig.model_validate(dict(section))
    except Exception as exc:
        raise ConfigError(str(exc)) from exc

    config_path = Path(config_path)

    def _resolve_optional_path(raw_value: Path | None) -> str:
        if raw_value is None:
            return ""
        path = Path(raw_value).expanduser()
        if not path.is_absolute():
            path = (config_path.parent / path).resolve()
        return str(path)

    mesh_path = _resolve_optional_path(mesh_input.mesh_path)
    bundle_dir = _resolve_optional_path(mesh_input.bundle_dir)
    return {
        "mesh_path": mesh_path,
        "bundle_dir": bundle_dir,
    }


# ---------------------------------------------------------------------------
# Mesh phases
# ---------------------------------------------------------------------------


def _resolve_setup_lake_polygon(setup_state: object):
    """Union of the lake footprints bound on the flow payload, or None."""
    flow = getattr(setup_state, "flow", None)
    if flow is None:
        return None
    lakes = getattr(flow, "sinks_sources", {}).get("lakes", {})
    polygons = [
        payload["polygon"]
        for payload in lakes.values()
        if isinstance(payload, dict) and payload.get("polygon") is not None
    ]
    if not polygons:
        return None
    if len(polygons) == 1:
        return polygons[0]
    from shapely.ops import unary_union

    return unary_union(polygons)


def _hydraulic_feature_geometries(setup_state: object, lr_cfg: object) -> list:
    """Collect (label, geometry, target_size, zone_buffer) refinement targets.

    So each structure resolves cleanly on the mesh: the dam cutoff wall (voile)
    line at ``dam_cell_size``, dilated by ``hfb_buffer`` into a zone wide enough
    to cover the lake outlet, and the sill between every pair of coupled lakes
    (the shortest segment between the two footprints). The SILL size is forced
    BELOW the lake-to-lake gap (0.4 * gap), else a single cell straddles both
    lakes and MF6 LAK rejects the model (one lake per cell). Outlet / SFR-entry
    points can be appended later.
    """
    flow = getattr(setup_state, "flow", None)
    if flow is None:
        return []
    lakes = getattr(flow, "sinks_sources", {}).get("lakes", {})
    if not isinstance(lakes, dict):
        return []
    dam_cell_size = float(getattr(lr_cfg, "dam_cell_size", 30.0))
    dam_buffer = float(getattr(lr_cfg, "dam_buffer", 150.0))
    hfb_buffer = getattr(lr_cfg, "hfb_buffer", None)
    hfb_width = float(hfb_buffer) if hfb_buffer is not None else 2.0 * dam_buffer
    features: list = []
    # dam cutoff walls (voile): the resolved trace line, one per lake that has one
    for lake_id, payload in lakes.items():
        if not isinstance(payload, dict):
            continue
        line = payload.get("cutoff_wall_line")
        if line is not None and not line.is_empty:
            features.append((f"voile:{lake_id}", line, dam_cell_size, hfb_width))
    # sill between every pair of lakes: refine the WHOLE proximity ZONE (not just the
    # single nearest point) to below the gap, so no cell anywhere along the sill
    # straddles both footprints. The lakes can run close over a long stretch.
    from itertools import combinations

    polys = {
        lid: payload["polygon"]
        for lid, payload in lakes.items()
        if isinstance(payload, dict) and payload.get("polygon") is not None
    }
    for (ida, pa), (idb, pb) in combinations(polys.items(), 2):
        gap = float(pa.distance(pb))
        if gap <= 0.0:
            continue  # overlapping/touching footprints cannot be separated by refinement
        sill_size = max(5.0, min(dam_cell_size, 0.4 * gap))
        margin = max(1.5 * gap, dam_cell_size)
        sill_zone = pa.buffer(margin).intersection(pb.buffer(margin))
        if not sill_zone.is_empty:
            features.append((f"sill:{ida}-{idb}", sill_zone, sill_size, margin))
    return features


def _build_lake_mesh_refinement(
    *, cfg: object, section_data: MeshCatchmentConfig, setup_state: object
) -> tuple:
    """Build the lake/dam/feature GMSH regional size fields for local refinement, or ()."""
    lr = getattr(section_data, "lake_refinement", None)
    if lr is None or not getattr(lr, "enabled", False):
        return ()
    from hydromodpy.spatial.mesh.refinement.lake_refinement import build_lake_refinement_size_fields

    dam_xy = None
    geographic = getattr(cfg, "geographic", None)
    x_outlet = getattr(geographic, "x_outlet", None)
    y_outlet = getattr(geographic, "y_outlet", None)
    if x_outlet is not None and y_outlet is not None:
        dam_xy = (float(x_outlet), float(y_outlet))
    feature_geometries = _hydraulic_feature_geometries(setup_state, lr)
    # The dam-outlet disk is redundant only when a cutoff-wall zone actually
    # reaches the outlet: the wall zone (radius = its zone_buffer) must overlap
    # the would-be disk (radius = dam_buffer). A wall on another lake far from
    # the outlet must not suppress the under-dam refinement.
    has_cutoff_wall = False
    if dam_xy is not None:
        from shapely.geometry import Point

        outlet = Point(dam_xy)
        has_cutoff_wall = any(
            label.startswith("voile:")
            and float(geom.distance(outlet)) <= float(width) + float(lr.dam_buffer)
            for label, geom, _size, width in feature_geometries
        )
    return build_lake_refinement_size_fields(
        lake_polygon=_resolve_setup_lake_polygon(setup_state),
        dam_xy=dam_xy,
        cfg=lr,
        global_size=float(section_data.zone_meshing.global_size),
        feature_geometries=feature_geometries,
        has_cutoff_wall=has_cutoff_wall,
    )


def run_mesh_phase(
    config_path: str | Path,
    cfg: object,
    run_state: WorkflowContext,
    mesh_section_data: MeshCatchmentConfig | None,
    constraints_mode: str | None,
) -> None:
    """Run the optional catchment meshing phase embedded in simulation TOML."""
    if mesh_section_data is None or constraints_mode is None:
        return

    from hydromodpy.spatial.mesh.launcher.runtime import (
        run_single_mesh_catchment_workflow_with_runtime_artifacts,
    )
    from hydromodpy.spatial.mesh.mesh_cache import (
        cached_mesh_paths,
        compute_mesh_cache_key,
        mesh_cache_is_valid,
        write_mesh_cache_key,
    )

    setup_state = run_state.setup
    extra_size_fields = _build_lake_mesh_refinement(
        cfg=cfg, section_data=mesh_section_data, setup_state=setup_state
    )

    # Gmsh is not reproducible run to run (see mesh_cache), so when caching is enabled
    # reuse a previously generated mesh whose inputs are unchanged instead of
    # regenerating. Fail-safe: a key mismatch or any missing file regenerates.
    mesh_dir = Path(getattr(setup_state.workspace, "project_root", ".")) / "mesh"
    cache_key: str | None = None
    if bool(getattr(mesh_section_data, "cache", False)):
        cache_key = compute_mesh_cache_key(
            section_data=mesh_section_data,
            geographic_cfg=cfg.geographic,
            domain_cfg=getattr(cfg, "domain", None),
            constraints_mode=constraints_mode,
            extra_size_fields=extra_size_fields,
            domain_geographic=setup_state.domain_geographic,
        )
        if mesh_cache_is_valid(mesh_dir, cache_key):
            cached_msh, cached_bundle, _ = cached_mesh_paths(mesh_dir)
            run_mesh_input_phase(
                run_state,
                {"mesh_path": str(cached_msh), "bundle_dir": str(cached_bundle)},
            )
            return

    mesh_runtime = run_single_mesh_catchment_workflow_with_runtime_artifacts(
        config_path=config_path,
        section_data=mesh_section_data,
        workspace_cfg=cfg.workspace,
        geographic_cfg=cfg.geographic,
        domain_cfg=cfg.domain,
        constraints_mode=constraints_mode,
        workspace=setup_state.workspace,
        geographic_features=setup_state.geographic_features,
        domain_geographic=setup_state.domain_geographic,
        extra_size_fields=extra_size_fields,
    )
    setup_state.mesh_summary = mesh_runtime.summary
    setup_state.mesh_planar = mesh_runtime.mesh_planar
    load_mesh_artifacts_from_summary(run_state, strict=False, preserve_preloaded=True)
    if cache_key is not None:
        write_mesh_cache_key(mesh_dir, cache_key)


def run_mesh_input_phase(
    run_state: WorkflowContext,
    external_mesh_input: dict[str, str] | None,
) -> None:
    """Load one pre-existing external mesh declared in ``[mesh_input]``."""
    if external_mesh_input is None:
        return

    mesh_summary: dict[str, str] = {
        "mesh_source": "external_input",
    }
    mesh_path = str(external_mesh_input.get("mesh_path", "")).strip()
    bundle_dir = str(external_mesh_input.get("bundle_dir", "")).strip()
    if mesh_path != "":
        mesh_summary["output_mesh"] = mesh_path
    if bundle_dir != "":
        mesh_summary["output_exchange_bundle_dir"] = bundle_dir

    run_state.setup.mesh_summary = mesh_summary
    load_mesh_artifacts_from_summary(run_state, strict=True)


# ---------------------------------------------------------------------------
# Mesh artifact loading
# ---------------------------------------------------------------------------


def load_mesh_artifacts_from_summary(
    run_state: WorkflowContext,
    *,
    strict: bool,
    preserve_preloaded: bool = False,
) -> None:
    """Populate runtime mesh objects from ``setup.mesh_summary`` when available."""
    setup_state = run_state.setup
    if not preserve_preloaded:
        setup_state.mesh_bundle = None
        setup_state.mesh_planar = None

    mesh_summary = setup_state.mesh_summary
    if not isinstance(mesh_summary, Mapping):
        if strict:
            raise MeshError("Mesh loading requires setup.mesh_summary to be a mapping.")
        return

    bundle_dir = str(mesh_summary.get("output_exchange_bundle_dir", "")).strip()
    if bundle_dir != "" and setup_state.mesh_bundle is None:
        setup_state.mesh_bundle = load_catchment_mesh_bundle(bundle_dir)
        if isinstance(mesh_summary, dict):
            mesh_summary.setdefault(
                "output_mesh",
                str(setup_state.mesh_bundle.mesh_path),
            )

    mesh_path = str(mesh_summary.get("output_mesh", "")).strip()
    if mesh_path == "":
        if strict and setup_state.mesh_bundle is None and setup_state.mesh_planar is None:
            raise MeshError(
                "Mesh loading requires one 'output_mesh' path or "
                "'output_exchange_bundle_dir' in setup.mesh_summary."
            )
        return

    mesh_path_obj = Path(mesh_path).expanduser()
    if not strict and not mesh_path_obj.exists():
        return
    if setup_state.mesh_planar is None:
        setup_state.mesh_planar = load_planar_mesh(mesh_path_obj)

    if setup_state.mesh_support is None and setup_state.mesh_bundle is not None:
        setup_state.mesh_support = build_gmsh_support_metadata(setup_state.mesh_bundle)


# ---------------------------------------------------------------------------
# Step entry points (unified signature for workflow pipelines)
# ---------------------------------------------------------------------------


def step_mesh(
    ctx: WorkflowContext,
    *,
    mesh_section_data: MeshCatchmentConfig | None = None,
    constraints_mode: str | None = None,
) -> None:
    """Run the optional catchment meshing phase embedded in simulation TOML."""
    run_mesh_phase(
        config_path=ctx.config_path,
        cfg=ctx.cfg,
        run_state=ctx,
        mesh_section_data=mesh_section_data,
        constraints_mode=constraints_mode,
    )


def step_mesh_input(
    ctx: WorkflowContext,
    *,
    external_mesh_input: dict[str, str] | None = None,
) -> None:
    """Load one pre-existing external mesh declared in ``[mesh_input]``."""
    run_mesh_input_phase(ctx, external_mesh_input)


# ---------------------------------------------------------------------------
# Pipeline step
# ---------------------------------------------------------------------------


class BuildMeshStep:
    """Build / import the mesh and complete the spatial supports."""

    name = "build_mesh"
    tin: ClassVar[type] = LoadedState
    tout: ClassVar[type] = MeshedState
    config_sections: ClassVar[tuple[str, ...]] = ("domain.supports",)

    def depends_on(self) -> tuple[str, ...]:
        return ("load_data",)

    def run(self, state: PipelineState) -> PipelineState:
        from hydromodpy.workflow.steps.setup import step_spatial_supports

        ctx = state.get("ctx")
        if ctx is None:
            raise ConfigError("BuildMeshStep requires 'ctx' in state.data")

        requested_supports = state.get("requested_domain_supports") or {}
        registry = state.get("spatial_support_registry")

        step_spatial_supports(
            ctx,
            phase="data",
            requested_domain_supports=requested_supports,
            registry=registry,
        )
        step_mesh(
            ctx,
            mesh_section_data=state.get("mesh_section_data"),
            constraints_mode=state.get("constraints_mode"),
        )
        step_mesh_input(ctx, external_mesh_input=state.get("external_mesh_input"))

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )

    def rebuild_state(
        self,
        *,
        prior_state: PipelineState,
        workspace: Path,
        run_id: str,
    ) -> PipelineState:
        """Reload the mesh from disk artefacts when present, fallback to re-run."""
        ctx = prior_state.get("ctx")
        if ctx is None:
            raise ConfigError("BuildMeshStep.rebuild_state requires 'ctx' in state.data")
        try:
            load_mesh_artifacts_from_summary(ctx, strict=False, preserve_preloaded=True)
        except Exception:
            return self.run(prior_state)
        if getattr(ctx.setup, "mesh_planar", None) is None:
            return self.run(prior_state)
        return prior_state.advance(
            step_index=prior_state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )

    def is_prebuilt(self, state: PipelineState) -> bool:
        """True when the in-memory ctx already carries the mesh."""
        ctx = state.get("ctx")
        return ctx is not None and getattr(ctx.setup, "mesh_planar", None) is not None
