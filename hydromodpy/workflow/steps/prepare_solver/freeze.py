"""Concern 4 of PrepareSolverStep: freezing the configuration a run was built from.

``config.toml`` says what the run was given. It is written once, when the run
claims its directory (:func:`write_claim_config`), from the configuration and
the earlier runs it reads, before any input is resolved or any step runs, so a
run that fails early can still be resumed. ``config.resolved.toml`` says what it
resolved to, and is written by this step, in one rename, once the build is known.
The same documents are offered as text for callers that write them elsewhere.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.io.atomic_replace import staged_path
from hydromodpy.core.toml_io.writer import dumps
from hydromodpy.results.catalog.registration import split_stem_version
from hydromodpy.results.storage.contract import RUN_CONFIG_FILENAME, RUN_RESOLVED_CONFIG_FILENAME
from hydromodpy.workflow.steps.prepare_solver.facts import collect_effective_config_snapshot
from hydromodpy.workflow.steps.prepare_solver.resolved import (
    portable_config_payload,
    resolved_at_build,
    resolved_config_document,
)

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.results.storage.run_store import RunStore

_SEARCH_SECTION = "calibration"


def frozen_config_of(
    ctx: WorkflowContext,
    *,
    restart_sim_id: str | None = None,
    restart_path: str | None = None,
    zone_runs: Mapping[str, str] | None = None,
) -> Any:
    """Return the configuration a run freezes, as a replay reads it back.

    It holds what the run was given, not the defaults it took: a validator that
    tells a written key from its default (``values`` beside
    ``[flow.sinks_sources.recharge.soil]``, ``surface_offset`` of a soil ETP)
    answers on the replay as it did on the run. A hotstart whose source has a
    ``sim_id`` is written as the table ``{sim_id, path}``, the path being
    *restart_path* when the caller resolved the source, else the reference as the
    configuration holds it. A refinement zone that
    read an earlier run writes the ``sim_id`` of that run (*zone_runs*, by the
    reference the zone gave) in place of its name, so a replay reads the run the
    mesh came from and not a later ``.vN`` of it. ``simulation.name`` is the name of
    the run, so a replay of the file answers to that run, whatever name the file it
    came from gave. A run describes its own solve: a trial of a calibration writes
    the parameters it ran with and no ``[calibration]``, so a replay solves once and
    searches nothing. Its lineage and its checks name the session.
    """
    snapshot = collect_effective_config_snapshot(ctx)
    if ctx.run_dir is not None:
        snapshot.setdefault("simulation", {})["name"] = split_stem_version(ctx.run_dir.name)[0]
    if snapshot.pop(_SEARCH_SECTION, None) is not None:
        snapshot["workflow"] = {**(snapshot.get("workflow") or {}), "mode": "simulation"}
    flow = snapshot.get("flow")
    if restart_sim_id is not None and isinstance(flow, dict) and flow.get("restart_from"):
        flow["restart_from"] = {
            "sim_id": restart_sim_id,
            "path": restart_path if restart_path is not None else str(flow["restart_from"]),
        }
    mesh = snapshot.get("mesh")
    if zone_runs and isinstance(mesh, dict):
        for zone in mesh.get("refinement_zone") or ():
            if isinstance(zone, dict) and zone.get("run") in zone_runs:
                zone["run"] = zone_runs[zone["run"]]
    # A catchment of kind "dem" reads its DEM from [[data.dem.sources]], which
    # the geographic section validates only when the document declares one.
    dem = (snapshot.get("data") or {}).get("dem") or {}
    declares_dem = bool(isinstance(dem, dict) and dem.get("sources"))
    return type(ctx.cfg).model_validate(snapshot, context={"allow_dem_bootstrap": declares_dem})


def frozen_config_document(
    ctx: WorkflowContext,
    project_root: Path,
    *,
    restart_sim_id: str | None = None,
    zone_runs: Mapping[str, str] | None = None,
) -> str:
    """Return the configuration of the run as portable TOML text (:func:`frozen_config_of`)."""
    assert ctx.run_dir is not None
    cfg_effective = frozen_config_of(ctx, restart_sim_id=restart_sim_id, zone_runs=zone_runs)
    return portable_config_document(cfg_effective, ctx.run_dir, project_root)


def portable_config_document(cfg: Any, run_dir: Path, project_root: Path) -> str:
    """Return the fields *cfg* was given as the portable TOML text a run directory freezes."""
    return dumps(portable_config_payload(cfg, run_dir, project_root, written_only=True))


def search_of(cfg: Any, run_dir: Path, project_root: Path) -> Mapping[str, Any] | None:
    """Return the ``[calibration]`` section *cfg* was given, portable, or None without one."""
    if getattr(cfg, _SEARCH_SECTION, None) is None:
        return None
    written = portable_config_payload(cfg, run_dir, project_root, written_only=True)
    return written.get(_SEARCH_SECTION)


def write_claim_config(
    ctx: WorkflowContext,
    *,
    project_root: Path,
    restart_sim_id: str | None = None,
    restart_path: str | None = None,
    zone_runs: Mapping[str, str] | None = None,
) -> Path:
    """Write ``config.toml`` into ``ctx.run_dir``, the run this context claimed, in one rename.

    This is the document the run was given, frozen at the claim from the
    configuration of the context. *restart_sim_id*, *restart_path* and *zone_runs*
    pin the earlier runs the configuration reads (:func:`frozen_config_of`).
    """
    assert ctx.run_dir is not None
    frozen = frozen_config_of(
        ctx, restart_sim_id=restart_sim_id, restart_path=restart_path, zone_runs=zone_runs
    )
    target = ctx.run_dir / RUN_CONFIG_FILENAME
    with staged_path(target) as staged:
        staged.write_text(
            portable_config_document(frozen, ctx.run_dir, project_root), encoding="utf-8"
        )
    return target


def freeze_run_config(
    ctx: WorkflowContext, *, store: RunStore, restart_sim_id: str | None = None
) -> None:
    """Write ``config.resolved.toml`` of the run in one rename, and ``config.toml`` when it is absent.

    The claim of a run writes ``config.toml`` (:func:`write_claim_config`). A run
    that was claimed by other means, a kept trial of a calibration, has none yet
    and gets it here, so every run directory carries both.
    """
    project_root = Path(store.workspace_path or store.run_dir.parent.parent)
    summary = getattr(ctx.setup, "mesh_summary", None) or {}
    frozen = frozen_config_of(
        ctx, restart_sim_id=restart_sim_id, zone_runs=summary.get("zone_runs")
    )
    documents = {
        RUN_RESOLVED_CONFIG_FILENAME: resolved_config_document(
            frozen,
            project_root,
            build=resolved_at_build(ctx),
            search=search_of(ctx.cfg, store.run_dir, project_root),
        ),
    }
    if not (store.run_dir / RUN_CONFIG_FILENAME).is_file():
        documents[RUN_CONFIG_FILENAME] = portable_config_document(
            frozen, store.run_dir, project_root
        )
    for name, document in documents.items():
        with staged_path(store.run_dir / name) as staged:
            staged.write_text(document, encoding="utf-8")
    store.facts.config_file = RUN_CONFIG_FILENAME


__all__ = (
    "freeze_run_config",
    "frozen_config_document",
    "frozen_config_of",
    "portable_config_document",
    "search_of",
    "write_claim_config",
)
