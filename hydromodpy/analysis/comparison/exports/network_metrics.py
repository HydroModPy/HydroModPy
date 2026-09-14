"""Hydrographic-network and active-cell-field network metrics CSV exports."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.logging import get_logger
from hydromodpy.results.derive.config_flags import log_missing_field

from .base import (
    CELL_FIELD_ACTIVE_METRICS_FIELDS,
    CELL_FIELD_NETWORK_DISTANCE_METRICS_FIELDS,
    CELL_FIELD_NETWORK_OVERLAP_METRICS_FIELDS,
    HYDROGRAPHIC_NETWORK_METRICS_FIELDS,
    RELEASE_FLUX_NETWORK_DISTANCE_METRICS_FIELDS,
    RELEASE_FLUX_NETWORK_OVERLAP_METRICS_FIELDS,
    _completed_simulation_summaries,
    _write_csv,
)

if TYPE_CHECKING:
    from hydromodpy.results.catalog import Catalog

logger = get_logger(__name__)


def write_hydrographic_network_metrics_export(
    *,
    comparison_id: str,
    comparison_root: Path,
    simulation_summaries: Iterable[Mapping[str, Any]],
    tolerance_m: float = 50.0,
    reference_role: str = "reference",
    candidate_role: str = "generated",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Write one flat CSV of per-run hydrographic-network comparison metrics."""
    from hydromodpy.analysis.comparison.runtime.metadata import discover_result_store

    rows: list[dict[str, Any]] = []
    skipped_simulations: list[dict[str, Any]] = []
    reference_feature_name: str | None = None
    candidate_feature_name: str | None = None

    for summary in _completed_simulation_summaries(simulation_summaries):
        simulation_id = str(summary.get("id", ""))
        config_path_raw = summary.get("config_path")
        config_path = None if config_path_raw in (None, "") else Path(str(config_path_raw))
        preferred_sim_id = summary.get("sim_id")
        preferred_run_name = summary.get("run_name")
        store, sim_id = discover_result_store(
            config_path,
            preferred_sim_id=(None if preferred_sim_id in (None, "") else str(preferred_sim_id)),
            preferred_name=(None if preferred_run_name in (None, "") else str(preferred_run_name)),
        )
        if store is None or sim_id in (None, ""):
            skipped_simulations.append(
                {
                    "simulation_id": simulation_id,
                    "reason": "result_store_unavailable",
                    "available_roles": [],
                }
            )
            continue
        try:
            run = store[str(sim_id)]
            reference_contract = run.hydrographic_network_naming(reference_role)
            candidate_contract = run.hydrographic_network_naming(candidate_role)
            reference_feature_name = reference_contract.get("canonical_feature_name")
            candidate_feature_name = candidate_contract.get("canonical_feature_name")
            available_roles = run.available_hydrographic_network_roles()
            if not {reference_role, candidate_role}.issubset(set(available_roles)):
                skipped_simulations.append(
                    {
                        "simulation_id": simulation_id,
                        "reason": "missing_required_roles",
                        "available_roles": available_roles,
                    }
                )
                continue
            row = run.hydrographic_network_comparison_metrics(
                reference_role=reference_role,
                candidate_role=candidate_role,
                tolerance_m=tolerance_m,
                comparison_id=comparison_id,
                simulation_id=simulation_id,
                simulation_label=str(summary.get("label", summary.get("id", ""))),
                solver=str(summary.get("solver", "")),
                mesh_label=str(summary.get("mesh_label", "")),
                mesh_mode=str(summary.get("mesh_mode", "")),
                sim_id=str(sim_id),
                run_name=str(summary.get("run_name", "")),
                run_folder=str(summary.get("run_folder", "")),
                reference_feature_name=reference_feature_name,
                candidate_feature_name=candidate_feature_name,
            )
            rows.append(row)
        except Exception as exc:
            skipped_simulations.append(
                {
                    "simulation_id": simulation_id,
                    "reason": "comparison_metrics_failed",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                }
            )
            logger.debug(
                "Skipping hydrographic-network metrics export for simulation '%s'.",
                simulation_id,
                exc_info=True,
            )
        finally:
            try:
                store.close()
            except Exception:
                pass

    artifacts: list[dict[str, Any]] = []
    if skipped_simulations:
        skipped_path = comparison_root / "hydrographic_network_metrics_skipped.json"
        skipped_payload = {
            "comparison_id": comparison_id,
            "reference_role": reference_role,
            "candidate_role": candidate_role,
            "reference_feature_name": reference_feature_name,
            "candidate_feature_name": candidate_feature_name,
            "tolerance_m": float(tolerance_m),
            "skipped_simulations": skipped_simulations,
        }
        skipped_path.parent.mkdir(parents=True, exist_ok=True)
        skipped_path.write_text(
            json.dumps(skipped_payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        artifacts.append(
            {
                "kind": "hydrographic_network_metrics_skipped_json",
                "path": str(skipped_path),
                "note": (
                    f"{len(skipped_simulations)} simulation(s) skipped for hydrographic-network "
                    "metrics export."
                ),
            }
        )
        logger.info(
            "Hydrographic-network metrics export skipped %d simulation(s): %s",
            len(skipped_simulations),
            ", ".join(str(item.get("simulation_id", "")) for item in skipped_simulations),
        )
    if not rows:
        return artifacts, rows

    path = comparison_root / "hydrographic_network_metrics.csv"
    _write_csv(path, rows, HYDROGRAPHIC_NETWORK_METRICS_FIELDS)
    artifacts.append({"kind": "hydrographic_network_metrics_csv", "path": str(path)})
    logger.info(
        "Wrote hydrographic-network metrics export for %d simulation(s) to %s",
        len(rows),
        path,
    )
    return artifacts, rows


def write_simulated_active_network_metrics_export(
    *,
    comparison_id: str,
    comparison_root: Path,
    simulation_summaries: Iterable[Mapping[str, Any]],
    variable: str = "accumulation_flux",
    threshold: float = 0.0,
    persistence_threshold: float = 0.5,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Write scalar metrics for the simulated active drainage network."""
    from hydromodpy.analysis.comparison.runtime.metadata import discover_result_store
    from hydromodpy.results.derive import views

    rows: list[dict[str, Any]] = []
    skipped_simulations: list[dict[str, Any]] = []
    for summary in _completed_simulation_summaries(simulation_summaries):
        simulation_id = str(summary.get("id", ""))
        config_path_raw = summary.get("config_path")
        config_path = None if config_path_raw in (None, "") else Path(str(config_path_raw))
        preferred_sim_id = summary.get("sim_id")
        preferred_run_name = summary.get("run_name")
        store, sim_id = discover_result_store(
            config_path,
            preferred_sim_id=(None if preferred_sim_id in (None, "") else str(preferred_sim_id)),
            preferred_name=(None if preferred_run_name in (None, "") else str(preferred_run_name)),
        )
        if store is None or sim_id in (None, ""):
            skipped_simulations.append(
                {
                    "simulation_id": simulation_id,
                    "reason": "result_store_unavailable",
                    "source_variable": variable,
                }
            )
            continue
        try:
            run = store[str(sim_id)]
            if not run.has_field(variable):
                log_missing_field(
                    logger, run, variable, f"active cell-field metrics for {simulation_id}"
                )
                skipped_simulations.append(
                    {
                        "simulation_id": simulation_id,
                        "reason": "missing_simulated_active_field",
                        "source_variable": variable,
                    }
                )
                continue
            metrics = views.cell_field_active_metrics(
                run,
                variable=variable,
                threshold=threshold,
                persistence_threshold=persistence_threshold,
            )
            row = {
                "comparison_id": comparison_id,
                "simulation_id": simulation_id,
                "simulation_label": str(summary.get("label", summary.get("id", ""))),
                "solver": str(summary.get("solver", "")),
                "mesh_label": str(summary.get("mesh_label", "")),
                "mesh_mode": str(summary.get("mesh_mode", "")),
                "sim_id": str(sim_id),
                "run_name": str(summary.get("run_name", "")),
                "run_folder": str(summary.get("run_folder", "")),
            }
            row.update(metrics)
            rows.append(row)
        except Exception as exc:
            skipped_simulations.append(
                {
                    "simulation_id": simulation_id,
                    "reason": "simulated_active_metrics_failed",
                    "source_variable": variable,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                }
            )
            logger.debug(
                "Skipping simulated-active network metrics export for simulation '%s'.",
                simulation_id,
                exc_info=True,
            )
        finally:
            try:
                store.close()
            except Exception:
                pass

    artifacts: list[dict[str, Any]] = []
    if skipped_simulations:
        skipped_path = comparison_root / "simulated_active_network_metrics_skipped.json"
        skipped_payload = {
            "comparison_id": comparison_id,
            "source_variable": variable,
            "threshold": float(threshold),
            "persistence_threshold": float(persistence_threshold),
            "skipped_simulations": skipped_simulations,
        }
        skipped_path.parent.mkdir(parents=True, exist_ok=True)
        skipped_path.write_text(
            json.dumps(skipped_payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        artifacts.append(
            {
                "kind": "simulated_active_network_metrics_skipped_json",
                "path": str(skipped_path),
                "note": (
                    f"{len(skipped_simulations)} simulation(s) skipped for simulated-active "
                    "network metrics export."
                ),
            }
        )
        logger.info(
            "Simulated-active network metrics export skipped %d simulation(s): %s",
            len(skipped_simulations),
            ", ".join(str(item.get("simulation_id", "")) for item in skipped_simulations),
        )
    if not rows:
        return artifacts, rows

    path = comparison_root / "simulated_active_network_metrics.csv"
    _write_csv(path, rows, CELL_FIELD_ACTIVE_METRICS_FIELDS)
    artifacts.append({"kind": "simulated_active_network_metrics_csv", "path": str(path)})
    logger.info(
        "Wrote simulated-active network metrics export for %d simulation(s) to %s",
        len(rows),
        path,
    )
    return artifacts, rows


def _simulation_metric_row_base(
    *,
    comparison_id: str,
    summary: Mapping[str, Any],
    sim_id: str,
) -> dict[str, Any]:
    return {
        "comparison_id": comparison_id,
        "simulation_id": str(summary.get("id", "")),
        "simulation_label": str(summary.get("label", summary.get("id", ""))),
        "solver": str(summary.get("solver", "")),
        "mesh_label": str(summary.get("mesh_label", "")),
        "mesh_mode": str(summary.get("mesh_mode", "")),
        "sim_id": str(sim_id),
        "run_name": str(summary.get("run_name", "")),
        "run_folder": str(summary.get("run_folder", "")),
    }


def _has_plottable_mesh(store: Catalog, sim_id: str) -> bool:
    zarr = store.open_zarr(str(sim_id))
    try:
        mesh = zarr.root.get("mesh")
        return bool(mesh is not None and "vertices" in mesh and "face_node_connectivity" in mesh)
    finally:
        zarr.close()


def _write_cell_field_network_metrics_export(
    *,
    comparison_id: str,
    comparison_root: Path,
    simulation_summaries: Iterable[Mapping[str, Any]],
    network_role: str,
    variable: str,
    metric_callable: Callable[..., dict[str, Any]],
    metric_kwargs: dict[str, Any],
    payload_parameters: dict[str, Any],
    csv_stem: str,
    csv_fields: list[str],
    missing_field_reason: str,
    failure_reason: str,
    log_label: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Shared export loop for cell-field/network comparison metrics."""
    from hydromodpy.analysis.comparison.runtime.metadata import discover_result_store

    rows: list[dict[str, Any]] = []
    skipped_simulations: list[dict[str, Any]] = []
    for summary in _completed_simulation_summaries(simulation_summaries):
        simulation_id = str(summary.get("id", ""))
        config_path_raw = summary.get("config_path")
        config_path = None if config_path_raw in (None, "") else Path(str(config_path_raw))
        preferred_sim_id = summary.get("sim_id")
        preferred_run_name = summary.get("run_name")
        store, sim_id = discover_result_store(
            config_path,
            preferred_sim_id=(None if preferred_sim_id in (None, "") else str(preferred_sim_id)),
            preferred_name=(None if preferred_run_name in (None, "") else str(preferred_run_name)),
        )
        if store is None or sim_id in (None, ""):
            skipped_simulations.append(
                {
                    "simulation_id": simulation_id,
                    "reason": "result_store_unavailable",
                    "source_variable": variable,
                    "network_role": network_role,
                }
            )
            continue

        try:
            run = store[str(sim_id)]
            if not run.has_hydrographic_network(network_role):
                skipped_simulations.append(
                    {
                        "simulation_id": simulation_id,
                        "reason": "missing_vector_network_role",
                        "network_role": network_role,
                        "available_roles": run.available_hydrographic_network_roles(),
                        "source_variable": variable,
                    }
                )
                continue
            if not run.has_field(variable):
                log_missing_field(logger, run, variable, f"network metrics for {simulation_id}")
                skipped_simulations.append(
                    {
                        "simulation_id": simulation_id,
                        "reason": missing_field_reason,
                        "network_role": network_role,
                        "source_variable": variable,
                    }
                )
                continue
            if not _has_plottable_mesh(store, str(sim_id)):
                skipped_simulations.append(
                    {
                        "simulation_id": simulation_id,
                        "reason": "missing_plottable_mesh",
                        "network_role": network_role,
                        "source_variable": variable,
                    }
                )
                continue

            metrics = metric_callable(run, **metric_kwargs)
            row = _simulation_metric_row_base(
                comparison_id=comparison_id,
                summary=summary,
                sim_id=str(sim_id),
            )
            row.update(metrics)
            rows.append(row)
        except Exception as exc:
            skipped_simulations.append(
                {
                    "simulation_id": simulation_id,
                    "reason": failure_reason,
                    "source_variable": variable,
                    "network_role": network_role,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                }
            )
            logger.debug(
                "Skipping %s export for simulation '%s'.",
                log_label,
                simulation_id,
                exc_info=True,
            )
        finally:
            try:
                store.close()
            except Exception:
                pass

    artifacts: list[dict[str, Any]] = []
    if skipped_simulations:
        skipped_path = comparison_root / f"{csv_stem}_skipped.json"
        skipped_payload = {
            "comparison_id": comparison_id,
            "network_role": network_role,
            "source_variable": variable,
            **payload_parameters,
            "skipped_simulations": skipped_simulations,
        }
        skipped_path.parent.mkdir(parents=True, exist_ok=True)
        skipped_path.write_text(
            json.dumps(skipped_payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        artifacts.append(
            {
                "kind": f"{csv_stem}_skipped_json",
                "path": str(skipped_path),
                "note": f"{len(skipped_simulations)} simulation(s) skipped for {log_label} export.",
            }
        )
        logger.info(
            "%s export skipped %d simulation(s): %s",
            log_label.capitalize(),
            len(skipped_simulations),
            ", ".join(str(item.get("simulation_id", "")) for item in skipped_simulations),
        )
    if not rows:
        return artifacts, rows

    path = comparison_root / f"{csv_stem}.csv"
    _write_csv(path, rows, csv_fields)
    artifacts.append({"kind": f"{csv_stem}_csv", "path": str(path)})
    logger.info("Wrote %s export for %d simulation(s) to %s", log_label, len(rows), path)
    return artifacts, rows


def write_simulated_active_network_overlap_metrics_export(
    *,
    comparison_id: str,
    comparison_root: Path,
    simulation_summaries: Iterable[Mapping[str, Any]],
    network_role: str = "reference",
    variable: str = "accumulation_flux",
    threshold: float = 0.0,
    mode: str | None = None,
    persistence_threshold: float = 0.5,
    timestep: int | None = None,
    buffer_m: float = 0.0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Write cell-overlap metrics between simulated-active cells and a vector role.

    The default mode is resolved from each run flow regime.
    """
    from hydromodpy.results.derive import views

    return _write_cell_field_network_metrics_export(
        comparison_id=comparison_id,
        comparison_root=comparison_root,
        simulation_summaries=simulation_summaries,
        network_role=network_role,
        variable=variable,
        metric_callable=views.cell_field_network_overlap_metrics,
        metric_kwargs={
            "network_role": network_role,
            "variable": variable,
            "threshold": threshold,
            "mode": mode,
            "persistence_threshold": persistence_threshold,
            "timestep": timestep,
            "buffer_m": buffer_m,
        },
        payload_parameters={
            "threshold": float(threshold),
            "mode": mode,
            "persistence_threshold": float(persistence_threshold),
            "timestep": timestep,
            "buffer_m": float(buffer_m),
        },
        csv_stem="simulated_active_network_overlap_metrics",
        csv_fields=CELL_FIELD_NETWORK_OVERLAP_METRICS_FIELDS,
        missing_field_reason="missing_simulated_active_field",
        failure_reason="simulated_active_overlap_metrics_failed",
        log_label="simulated-active network overlap metrics",
    )


def write_simulated_active_network_distance_metrics_export(
    *,
    comparison_id: str,
    comparison_root: Path,
    simulation_summaries: Iterable[Mapping[str, Any]],
    network_role: str = "reference",
    variable: str = "accumulation_flux",
    threshold: float = 0.0,
    mode: str | None = None,
    persistence_threshold: float = 0.5,
    timestep: int | None = None,
    network_buffer_m: float = 0.0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Write planar distance metrics between active cells and a vector role.

    The export complements overlap metrics. It is intentionally explicit about
    its ``distance_method`` because it is not the DEM-downslope criterion from
    Abherve et al.; it only uses currently persisted mesh, field and reference
    linework artifacts.
    """
    from hydromodpy.results.derive import views

    return _write_cell_field_network_metrics_export(
        comparison_id=comparison_id,
        comparison_root=comparison_root,
        simulation_summaries=simulation_summaries,
        network_role=network_role,
        variable=variable,
        metric_callable=views.cell_field_network_distance_metrics,
        metric_kwargs={
            "network_role": network_role,
            "variable": variable,
            "threshold": threshold,
            "mode": mode,
            "persistence_threshold": persistence_threshold,
            "timestep": timestep,
            "network_buffer_m": network_buffer_m,
        },
        payload_parameters={
            "threshold": float(threshold),
            "mode": mode or "auto",
            "persistence_threshold": float(persistence_threshold),
            "timestep": timestep,
            "network_buffer_m": float(network_buffer_m),
        },
        csv_stem="simulated_active_network_distance_metrics",
        csv_fields=CELL_FIELD_NETWORK_DISTANCE_METRICS_FIELDS,
        missing_field_reason="missing_simulated_active_field",
        failure_reason="simulated_active_distance_metrics_failed",
        log_label="simulated-active network distance metrics",
    )


def write_release_flux_network_overlap_metrics_export(
    *,
    comparison_id: str,
    comparison_root: Path,
    simulation_summaries: Iterable[Mapping[str, Any]],
    network_role: str = "reference",
    variable: str = "release_flux",
    threshold: float = 0.0,
    mode: str | None = None,
    persistence_threshold: float = 0.5,
    timestep: int | None = None,
    buffer_m: float = 0.0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Write cell-overlap metrics between direct release cells and a vector role."""
    from hydromodpy.results.derive import views

    return _write_cell_field_network_metrics_export(
        comparison_id=comparison_id,
        comparison_root=comparison_root,
        simulation_summaries=simulation_summaries,
        network_role=network_role,
        variable=variable,
        metric_callable=views.cell_field_network_overlap_metrics,
        metric_kwargs={
            "network_role": network_role,
            "variable": variable,
            "threshold": threshold,
            "mode": mode,
            "persistence_threshold": persistence_threshold,
            "timestep": timestep,
            "buffer_m": buffer_m,
        },
        payload_parameters={
            "threshold": float(threshold),
            "mode": mode,
            "persistence_threshold": float(persistence_threshold),
            "timestep": timestep,
            "buffer_m": float(buffer_m),
        },
        csv_stem="release_flux_network_overlap_metrics",
        csv_fields=RELEASE_FLUX_NETWORK_OVERLAP_METRICS_FIELDS,
        missing_field_reason="missing_release_flux_field",
        failure_reason="release_flux_network_overlap_metrics_failed",
        log_label="release-flux network overlap metrics",
    )


def write_release_flux_network_distance_metrics_export(
    *,
    comparison_id: str,
    comparison_root: Path,
    simulation_summaries: Iterable[Mapping[str, Any]],
    network_role: str = "reference",
    variable: str = "release_flux",
    threshold: float = 0.0,
    mode: str | None = None,
    persistence_threshold: float = 0.5,
    timestep: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Write raw planar distance metrics between release cells and a vector role."""
    from hydromodpy.results.derive import views

    return _write_cell_field_network_metrics_export(
        comparison_id=comparison_id,
        comparison_root=comparison_root,
        simulation_summaries=simulation_summaries,
        network_role=network_role,
        variable=variable,
        metric_callable=views.cell_field_network_distance_metrics,
        metric_kwargs={
            "network_role": network_role,
            "variable": variable,
            "threshold": threshold,
            "mode": mode,
            "persistence_threshold": persistence_threshold,
            "timestep": timestep,
            "network_buffer_m": 0.0,
            "distance_method": "raw_planar_cell_centroid_to_network",
        },
        payload_parameters={
            "threshold": float(threshold),
            "mode": mode or "auto",
            "persistence_threshold": float(persistence_threshold),
            "timestep": timestep,
            "network_buffer_m": 0.0,
        },
        csv_stem="release_flux_network_distance_metrics",
        csv_fields=RELEASE_FLUX_NETWORK_DISTANCE_METRICS_FIELDS,
        missing_field_reason="missing_release_flux_field",
        failure_reason="release_flux_network_distance_metrics_failed",
        log_label="release-flux network distance metrics",
    )


def write_release_accumulation_network_overlap_metrics_export(
    *,
    comparison_id: str,
    comparison_root: Path,
    simulation_summaries: Iterable[Mapping[str, Any]],
    network_role: str = "reference",
    variable: str = "release_accumulation_flux",
    threshold: float = 0.0,
    mode: str | None = None,
    persistence_threshold: float = 0.5,
    timestep: int | None = None,
    buffer_m: float = 0.0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Write overlap metrics for downstream-routed release cells."""
    from hydromodpy.results.derive import views

    return _write_cell_field_network_metrics_export(
        comparison_id=comparison_id,
        comparison_root=comparison_root,
        simulation_summaries=simulation_summaries,
        network_role=network_role,
        variable=variable,
        metric_callable=views.cell_field_network_overlap_metrics,
        metric_kwargs={
            "network_role": network_role,
            "variable": variable,
            "threshold": threshold,
            "mode": mode,
            "persistence_threshold": persistence_threshold,
            "timestep": timestep,
            "buffer_m": buffer_m,
        },
        payload_parameters={
            "threshold": float(threshold),
            "mode": mode,
            "persistence_threshold": float(persistence_threshold),
            "timestep": timestep,
            "buffer_m": float(buffer_m),
        },
        csv_stem="release_accumulation_network_overlap_metrics",
        csv_fields=RELEASE_FLUX_NETWORK_OVERLAP_METRICS_FIELDS,
        missing_field_reason="missing_release_accumulation_field",
        failure_reason="release_accumulation_network_overlap_metrics_failed",
        log_label="release-accumulation network overlap metrics",
    )


def write_release_accumulation_network_distance_metrics_export(
    *,
    comparison_id: str,
    comparison_root: Path,
    simulation_summaries: Iterable[Mapping[str, Any]],
    network_role: str = "reference",
    variable: str = "release_accumulation_flux",
    threshold: float = 0.0,
    mode: str | None = None,
    persistence_threshold: float = 0.5,
    timestep: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Write raw planar distance metrics for downstream-routed release cells."""
    from hydromodpy.results.derive import views

    return _write_cell_field_network_metrics_export(
        comparison_id=comparison_id,
        comparison_root=comparison_root,
        simulation_summaries=simulation_summaries,
        network_role=network_role,
        variable=variable,
        metric_callable=views.cell_field_network_distance_metrics,
        metric_kwargs={
            "network_role": network_role,
            "variable": variable,
            "threshold": threshold,
            "mode": mode,
            "persistence_threshold": persistence_threshold,
            "timestep": timestep,
            "network_buffer_m": 0.0,
            "distance_method": "raw_planar_cell_centroid_to_network",
        },
        payload_parameters={
            "threshold": float(threshold),
            "mode": mode or "auto",
            "persistence_threshold": float(persistence_threshold),
            "timestep": timestep,
            "network_buffer_m": 0.0,
        },
        csv_stem="release_accumulation_network_distance_metrics",
        csv_fields=RELEASE_FLUX_NETWORK_DISTANCE_METRICS_FIELDS,
        missing_field_reason="missing_release_accumulation_field",
        failure_reason="release_accumulation_network_distance_metrics_failed",
        log_label="release-accumulation network distance metrics",
    )
