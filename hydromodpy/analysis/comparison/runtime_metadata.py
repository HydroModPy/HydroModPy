"""Run-folder metadata and result-store discovery helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hydromodpy.core.logging import get_logger
from hydromodpy.core.toml_io.loader import load_toml_with_base_config

logger = get_logger(__name__)


def read_json_file(path: Path) -> dict[str, Any]:
    """Read one JSON object, returning an empty mapping when absent/invalid."""
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _resolve_recorded_output_path(
    raw_path: Any,
    *,
    base_dir: Path,
) -> Path | None:
    """Resolve one recorded output path, including WSL `/mnt/<drive>/...` forms."""
    if raw_path in (None, ""):
        return None
    text = str(raw_path).strip()
    if not text:
        return None

    normalized = text
    if len(text) > 7 and text.startswith("/mnt/") and text[5].isalpha() and text[6] == "/":
        drive = text[5].upper()
        tail = text[7:].replace("/", "\\")
        normalized = f"{drive}:\\{tail}"

    path = Path(normalized).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    else:
        path = path.resolve()
    return path


def _resolve_project_root_from_config(config_path: Path) -> Path | None:
    try:
        payload = load_toml_with_base_config(config_path)
    except Exception:
        return None
    workspace = payload.get("workspace")
    if not isinstance(workspace, Mapping):
        return None
    project_root = workspace.get("project_root")
    if project_root in (None, ""):
        return None
    resolved = Path(str(project_root)).expanduser()
    if not resolved.is_absolute():
        resolved = config_path.parent / resolved
    return resolved.resolve()


def compact_run_metrics(metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only comparison-relevant scalar/list metrics in manifests."""
    keys = (
        "wall_time_seconds",
        "solvers",
        "success",
        "mesh_constraints_mode",
        "mesh_output_mesh",
        "mesh_output_summary_json",
        "mesh_output_exchange_bundle_dir",
    )
    return {key: metrics.get(key) for key in keys if key in metrics}


def read_variant_run_metadata(run_folder: Path) -> dict[str, Any]:
    """Collect lightweight run metadata useful in comparison manifests."""
    metrics = read_json_file(run_folder / "_metrics.json")
    boussinesq_summary = read_json_file(run_folder / "_boussinesq_summary.json")
    payload: dict[str, Any] = {}

    if metrics:
        payload["metrics"] = compact_run_metrics(metrics)
        if "wall_time_seconds" in metrics:
            payload["wall_time_seconds"] = metrics.get("wall_time_seconds")
        if "solvers" in metrics:
            payload["solvers"] = metrics.get("solvers")

    if boussinesq_summary:
        payload["boussinesq_summary"] = {
            key: boussinesq_summary.get(key)
            for key in (
                "n_cells",
                "n_edges",
                "n_nodes",
                "runtime_backend",
                "runtime_solver_kind",
                "solve_stage",
                "last_termination_reason",
            )
            if key in boussinesq_summary
        }
        for key in ("n_cells", "n_edges", "n_nodes"):
            if key in boussinesq_summary:
                payload[key] = boussinesq_summary.get(key)

    bundle_dir_raw = metrics.get("mesh_output_exchange_bundle_dir") or boussinesq_summary.get(
        "bundle_dir"
    )
    if bundle_dir_raw:
        bundle_dir = _resolve_recorded_output_path(bundle_dir_raw, base_dir=run_folder)
        if bundle_dir is None:
            return payload
        bundle_metadata = read_json_file(bundle_dir / "metadata.json")
        if bundle_metadata:
            payload["mesh_bundle_metadata"] = {
                key: bundle_metadata.get(key)
                for key in (
                    "bundle_schema_version",
                    "mesh_kind",
                    "cell_type",
                    "crs",
                    "n_nodes",
                    "n_cells",
                    "n_edges",
                    "constraints_mode",
                )
                if key in bundle_metadata
            }
            for key in ("n_cells", "n_edges", "n_nodes"):
                if key in bundle_metadata:
                    payload[key] = bundle_metadata.get(key)

    return payload


def discover_result_store(
    config_path: Path | None,
) -> tuple[Any, str | None]:
    """Open a SimulationCatalog from the workspace root inferred from a config path.

    Returns ``(catalog, sim_id)`` on success, ``(None, None)`` when the
    catalog is unavailable.  The caller is responsible for closing the
    catalog via ``catalog.close()`` when finished.
    """
    if config_path is None:
        return None, None

    project_root = _resolve_project_root_from_config(config_path)
    if project_root is None:
        return None, None

    from hydromodpy.core.workspace.resolve import locate_workspace_root

    workspace_root = locate_workspace_root(project_root) or project_root

    try:
        from hydromodpy.results.catalog import SimulationCatalog

        catalog = SimulationCatalog(workspace_root)
        sims = catalog.list_simulations()
        if sims.empty:
            catalog.close()
            return None, None
        sim_id = str(sims.iloc[-1]["sim_id"])
        return catalog, sim_id
    except Exception:
        logger.debug("Could not open SimulationCatalog from %s", workspace_root, exc_info=True)
        return None, None


__all__ = (
    "compact_run_metrics",
    "discover_result_store",
    "read_json_file",
    "read_variant_run_metadata",
)
