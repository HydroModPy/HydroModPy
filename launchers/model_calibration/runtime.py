"""Prepared runtime helpers for the model-calibration launcher."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

import numpy as np

from hydromodpy.analysis.calibration.core.composite_objective import (
    CompositeBlockEvaluation,
    CompositeObjective,
    CompositeObjectiveBlock,
    CompositeObjectiveEvaluation,
)
from hydromodpy.core.config.toml_loader import load_toml_with_base_config
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.core.workspace.path_registry import WorkspacePathRegistry
from hydromodpy.solver.utils.mesh.gmsh_grid.catchment_mesh_bundle import (
    resolve_default_catchment_mesh_bundle_dir,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.catchment_mesh_bundle_reader import (
    load_catchment_mesh_bundle,
)

from launchers.model_calibration.config import ModelCalibrationConfig
from launchers.model_calibration.output_selection import (
    PreparedOutputSelector,
    prepare_output_selectors,
    select_candidate_outputs as _select_candidate_outputs_from_bundle,
    select_candidate_outputs_from_selectors,
)
from launchers.model_calibration.property_arrays import build_property_array_set
from launchers.model_calibration.property_arrays import PropertyArraySet


_NUMERIC_WITH_SUFFIX_RE = re.compile(
    r"^\s*(?P<number>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(?P<suffix>.*\S)?\s*$"
)
_POSTERIOR_DISTRIBUTION_METHODS = frozenset({"gp_mapping", "da_mh_gp"})
_EMPIRICAL_ENSEMBLE_METHODS = frozenset({"random_search"})


def resolve_workspace_config(
    raw_simulation_toml: dict[str, Any],
    *,
    simulation_config_path: Path,
) -> WorkspaceConfig:
    """Resolve the simulation-side workspace config without loading the full runtime."""
    workspace_section = dict(raw_simulation_toml.get("workspace", {}))
    if "project_root" not in workspace_section:
        workspace_section["project_root"] = simulation_config_path.parent.resolve()
    else:
        project_root = Path(workspace_section["project_root"]).expanduser()
        if not project_root.is_absolute():
            project_root = (simulation_config_path.parent / project_root).resolve()
        workspace_section["project_root"] = project_root

    output_root = workspace_section.get("output_root")
    if output_root is not None:
        output_root_path = Path(output_root).expanduser()
        if not output_root_path.is_absolute():
            output_root_path = (simulation_config_path.parent / output_root_path).resolve()
        workspace_section["output_root"] = output_root_path

    workspace_root = workspace_section.get("workspace_root")
    if workspace_root is not None:
        workspace_root_path = Path(workspace_root).expanduser()
        if not workspace_root_path.is_absolute():
            workspace_root_path = (
                simulation_config_path.parent / workspace_root_path
            ).resolve()
        workspace_section["workspace_root"] = workspace_root_path

    return WorkspaceConfig(**workspace_section)


def detect_solver_families(raw_simulation_toml: dict[str, Any]) -> tuple[str, ...]:
    """Extract unique solver names from the simulation process plan."""
    simulation_section = raw_simulation_toml.get("simulation", {})
    processes = simulation_section.get("process", [])
    solvers: list[str] = []
    for process in processes:
        if not isinstance(process, dict):
            continue
        for solver in process.get("solvers", []):
            token = str(solver).strip().lower()
            if token and token not in solvers:
                solvers.append(token)
    return tuple(solvers)


def _select_runtime_preparation_flow_solver(
    *,
    solver_families: tuple[str, ...],
) -> str | None:
    """Choose the preferred flow solver used to prepare runtime hydraulic support."""
    normalized = [str(name).strip().lower() for name in solver_families if str(name).strip()]
    for candidate in ("modflow6", "modflownwt"):
        if candidate in normalized:
            return candidate
    return None


def _prepared_numeric_array_summary(values: tuple[float, ...]) -> dict[str, Any]:
    """Return one compact summary plus a stable signature for numeric support arrays."""
    arr = np.asarray(values, dtype=np.float64).reshape(-1)
    if arr.size == 0:
        return {
            "count": 0,
            "min": None,
            "mean": None,
            "max": None,
            "signature": hashlib.sha256(b"").hexdigest(),
        }
    return {
        "count": int(arr.size),
        "min": float(np.min(arr)),
        "mean": float(np.mean(arr)),
        "max": float(np.max(arr)),
        "signature": hashlib.sha256(arr.astype("<f8", copy=False).tobytes()).hexdigest(),
    }


def _prepared_labels_summary(labels: tuple[str, ...] | None) -> dict[str, Any] | None:
    """Return one compact summary plus a stable signature for lithology labels."""
    if labels is None:
        return None
    normalized = tuple(str(label) for label in labels)
    serialized = json.dumps(normalized, ensure_ascii=True).encode("utf-8")
    return {
        "count": int(len(normalized)),
        "unique_labels": sorted({label for label in normalized if label != ""}),
        "signature": hashlib.sha256(serialized).hexdigest(),
    }


@dataclass(frozen=True, slots=True)
class PreparedCalibrationSession:
    """Prepared runtime context resolved once for one calibration launcher session."""

    config_path: Path
    simulation_config_path: Path
    raw_simulation_toml: dict[str, Any]
    simulation_workspace: WorkspaceConfig
    calibration_id: str
    calibration_root: Path
    session_manifest_path: Path
    iteration_history_path: Path
    solver_families: tuple[str, ...]
    primary_solver: str | None
    supported_v1_backend: bool
    core_settings: dict[str, Any]
    contract_signature: str
    parameter_names: tuple[str, ...]
    output_names: tuple[str, ...]
    objective_block_names: tuple[str, ...]
    prepare_time_seconds: float | None = None
    prepared_hydraulic_support: "PreparedHydraulicPropertySupport | None" = None
    prepared_output_selectors: tuple[PreparedOutputSelector, ...] = ()
    candidates_root: Path | None = None
    runtime_launcher_cache: dict[str, Any] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )

    def to_summary(self) -> dict[str, Any]:
        """Return one launcher summary derived from the prepared session."""
        return {
            "mode": "model_calibration",
            "status": "prepared",
            "config_path": str(self.config_path),
            "simulation_config": str(self.simulation_config_path),
            "calibration_id": self.calibration_id,
            "calibration_root": str(self.calibration_root),
            "session_manifest_path": str(self.session_manifest_path),
            "iteration_history_path": str(self.iteration_history_path),
            "candidates_root": (
                None if self.candidates_root is None else str(self.candidates_root)
            ),
            "primary_solver": self.primary_solver,
            "solver_families": list(self.solver_families),
            "supported_v1_backend": self.supported_v1_backend,
            "method": self.core_settings["method"],
            "session_contract_signature": self.contract_signature,
            "parameter_names": list(self.parameter_names),
            "n_parameters": len(self.parameter_names),
            "output_names": list(self.output_names),
            "n_outputs": len(self.output_names),
            "n_prepared_output_selectors": len(self.prepared_output_selectors),
            "objective_block_names": list(self.objective_block_names),
            "n_objective_blocks": len(self.objective_block_names),
            "prepare_time_seconds": self.prepare_time_seconds,
            "prepared_hydraulic_support": (
                None
                if self.prepared_hydraulic_support is None
                else self.prepared_hydraulic_support.to_summary()
            ),
        }


@dataclass(frozen=True, slots=True)
class PreparedHydraulicPropertySupport:
    """Prepared support reused to actualize hydraulic parameter arrays quickly."""

    n_cells: int
    lithology_labels: tuple[str, ...] | None = None
    base_property_arrays: dict[str, tuple[float, ...]] = field(default_factory=dict)
    zone_fractions_by_property: dict[str, dict[str, tuple[float, ...]]] = field(
        default_factory=dict
    )
    zone_fractions_by_key: dict[str, tuple[float, ...]] = field(default_factory=dict)
    base_property_values_by_key: dict[str, dict[str, float]] = field(default_factory=dict)
    support_id_by_property: dict[str, str] = field(default_factory=dict)
    source: str = "config_scalar"
    mesh_bundle_dir: Path | None = None
    mesh_path: Path | None = None
    mesh_summary_path: Path | None = None

    def to_summary(self) -> dict[str, Any]:
        """Return one concise JSON-friendly summary."""
        return {
            "n_cells": int(self.n_cells),
            "has_lithology_labels": self.lithology_labels is not None,
            "base_properties": sorted(self.base_property_arrays.keys()),
            "base_property_details": {
                name: _prepared_numeric_array_summary(values)
                for name, values in sorted(self.base_property_arrays.items())
            },
            "zone_keys": sorted(self.zone_fractions_by_key.keys()),
            "zone_supports_by_property": {
                name: {
                    "support_id": self.support_id_by_property.get(name),
                    "zone_keys": sorted(values.keys()),
                }
                for name, values in sorted(self.zone_fractions_by_property.items())
            },
            "base_property_values_by_key": {
                name: {
                    str(key): float(value)
                    for key, value in sorted(values.items())
                }
                for name, values in sorted(self.base_property_values_by_key.items())
            },
            "lithology_labels": _prepared_labels_summary(self.lithology_labels),
            "source": str(self.source),
            "mesh_bundle_dir": (
                None if self.mesh_bundle_dir is None else str(self.mesh_bundle_dir)
            ),
            "mesh_path": None if self.mesh_path is None else str(self.mesh_path),
            "mesh_summary_path": (
                None
                if self.mesh_summary_path is None
                else str(self.mesh_summary_path)
            ),
        }


@dataclass(frozen=True, slots=True)
class _ResolvedHydraulicSupportPaths:
    """Resolved file-system anchors used to prepare hydraulic support."""

    source: str = "config_scalar"
    bundle_dir: Path | None = None
    mesh_path: Path | None = None
    mesh_summary_path: Path | None = None


def _surface_property_vector(values: object, *, solver_mesh: object) -> tuple[float, ...]:
    """Normalize one surface diagnostic payload to the 1D cell support used by calibration."""
    arr = np.asarray(values, dtype=float)
    flattened = np.asarray(
        solver_mesh.flatten_from_grid(arr),
        dtype=float,
    ).reshape(-1)
    return tuple(float(value) for value in flattened)


def _setup_mesh_paths_from_runtime(setup_state: object) -> tuple[Path | None, Path | None, Path | None]:
    """Resolve bundle, mesh and summary paths from one prepared process-simulation setup."""
    bundle_dir: Path | None = None
    mesh_path: Path | None = None
    mesh_summary_path: Path | None = None

    mesh_summary = getattr(setup_state, "mesh_summary", None)
    if isinstance(mesh_summary, Mapping):
        raw_bundle_dir = str(mesh_summary.get("output_exchange_bundle_dir", "")).strip()
        if raw_bundle_dir != "":
            bundle_dir = Path(raw_bundle_dir).expanduser().resolve()
        raw_mesh_path = str(mesh_summary.get("output_mesh", "")).strip()
        if raw_mesh_path != "":
            mesh_path = Path(raw_mesh_path).expanduser().resolve()
        raw_summary_path = str(mesh_summary.get("output_summary_json", "")).strip()
        if raw_summary_path != "":
            mesh_summary_path = Path(raw_summary_path).expanduser().resolve()

    mesh_bundle = getattr(setup_state, "mesh_bundle", None)
    if mesh_bundle is not None:
        runtime_bundle_dir = getattr(mesh_bundle, "bundle_dir", None)
        if bundle_dir is None and runtime_bundle_dir is not None:
            bundle_dir = Path(runtime_bundle_dir).resolve()
        runtime_mesh_path = getattr(mesh_bundle, "mesh_path", None)
        if mesh_path is None and runtime_mesh_path is not None:
            mesh_path = Path(runtime_mesh_path).resolve()
        if mesh_summary_path is None and bundle_dir is not None:
            candidate_summary = bundle_dir / "mesh_summary.json"
            if candidate_summary.is_file():
                mesh_summary_path = candidate_summary.resolve()

    if mesh_path is None:
        mesh_planar = getattr(setup_state, "mesh_planar", None)
        mesh_planar_path = getattr(mesh_planar, "path", None)
        if mesh_planar_path is not None:
            mesh_path = Path(mesh_planar_path).expanduser().resolve()

    return bundle_dir, mesh_path, mesh_summary_path


def _path_exists(mapping: dict[str, Any], path: tuple[str, ...]) -> bool:
    """Return True when one nested path exists in a mapping payload."""
    current: Any = mapping
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return False
        current = current[key]
    return True


def _resolve_target_path_alias(
    mapping: dict[str, Any],
    path: tuple[str, ...],
) -> tuple[str, ...]:
    """Resolve one user-facing calibration target path to the raw TOML payload path."""
    if len(path) < 4 or path[0] != "flow" or path[1] != "param":
        return path

    property_name = path[2]
    property_cfg = _resolve_flow_property_config(
        raw_simulation_toml=mapping,
        property_name=property_name,
    )
    if property_cfg is None:
        return path

    leaf = path[3]
    if leaf == "value":
        candidate = ("flow", "param", property_name, "field_homogeneous", "value", *path[4:])
        if _path_exists(mapping, candidate):
            return candidate
    if leaf == "values_by_key":
        candidate = (
            "flow",
            "param",
            property_name,
            "field_heterogeneous",
            "values",
            *path[4:],
        )
        if _path_exists(mapping, candidate):
            return candidate
    if leaf == "field_spatial_id":
        candidate = (
            "flow",
            "param",
            property_name,
            "field_heterogeneous",
            "field_spatial_id",
            *path[4:],
        )
        if _path_exists(mapping, candidate):
            return candidate
    return path


def _parse_property_values_by_key(
    property_cfg: dict[str, Any] | None,
) -> dict[str, float]:
    """Parse one heterogeneous values-by-key mapping from a raw flow property block."""
    if property_cfg is None:
        return {}
    candidate_mappings: list[object] = []
    field_heterogeneous = property_cfg.get("field_heterogeneous")
    if isinstance(field_heterogeneous, dict):
        candidate_mappings.append(field_heterogeneous.get("values"))
    candidate_mappings.append(property_cfg.get("values_by_key"))

    for raw_mapping in candidate_mappings:
        if not isinstance(raw_mapping, dict):
            continue
        parsed: dict[str, float] = {}
        for key, raw_value in raw_mapping.items():
            numeric = _parse_optional_numeric_value(raw_value)
            if numeric is None:
                continue
            parsed[str(key).strip()] = float(numeric)
        if parsed:
            return parsed
    return {}


def _parse_property_support_id(
    property_cfg: dict[str, Any] | None,
) -> str | None:
    """Return the spatial-support id declared for one heterogeneous property."""
    if property_cfg is None:
        return None
    field_heterogeneous = property_cfg.get("field_heterogeneous")
    if not isinstance(field_heterogeneous, dict):
        return None
    support_id = str(field_heterogeneous.get("field_spatial_id", "")).strip()
    return None if support_id == "" else support_id


def _bundle_zone_fractions(
    bundle: object,
    *,
    n_cells: int,
) -> dict[str, tuple[float, ...]]:
    """Return per-zone fractions from one bundle, falling back to one-hot cell labels."""
    fractions: dict[str, np.ndarray] = {}
    for record in getattr(bundle, "geology_fractions", ()):
        key = str(getattr(record, "geology_key", "")).strip()
        cell_id = int(getattr(record, "cell_id"))
        fraction = float(getattr(record, "fraction"))
        if key == "" or not 0 <= cell_id < int(n_cells):
            continue
        fractions.setdefault(key, np.zeros(int(n_cells), dtype=float))[cell_id] = fraction

    if fractions:
        return {
            key: tuple(float(value) for value in values.reshape(-1))
            for key, values in sorted(fractions.items())
        }

    labels = tuple(str(getattr(cell, "geology_key", "") or "").strip() for cell in getattr(bundle, "cells", ()))
    if not any(labels):
        return {}
    fallback: dict[str, np.ndarray] = {}
    for index, key in enumerate(labels):
        if key == "":
            continue
        fallback.setdefault(key, np.zeros(int(n_cells), dtype=float))[index] = 1.0
    return {
        key: tuple(float(value) for value in values.reshape(-1))
        for key, values in sorted(fallback.items())
    }


def _labels_from_zone_fractions(
    zone_fractions_by_key: dict[str, tuple[float, ...]],
) -> tuple[str, ...] | None:
    """Return dominant per-cell labels from one per-zone fraction mapping."""
    if not zone_fractions_by_key:
        return None
    zone_keys = tuple(zone_fractions_by_key.keys())
    stacked = np.vstack(
        [
            np.asarray(zone_fractions_by_key[key], dtype=float).reshape(-1)
            for key in zone_keys
        ]
    )
    if stacked.size == 0:
        return None
    dominant_idx = np.argmax(stacked, axis=0)
    dominant_values = np.max(stacked, axis=0)
    labels = tuple(
        zone_keys[int(index)] if float(value) > 0.0 else ""
        for index, value in zip(dominant_idx, dominant_values, strict=True)
    )
    return labels if any(label != "" for label in labels) else None


def _prepare_runtime_hydraulic_property_support(
    *,
    simulation_config_path: Path,
    raw_simulation_toml: dict[str, Any],
    solver_families: tuple[str, ...],
    property_names: tuple[str, ...],
) -> PreparedHydraulicPropertySupport | None:
    """Prepare hydraulic support directly from the process-simulation runtime when possible."""
    selected_solver = _select_runtime_preparation_flow_solver(
        solver_families=solver_families,
    )
    if selected_solver is None:
        return None

    from hydromodpy.solver.modflow_common.discretization_spatial import (
        build_spatial_discretization,
    )
    from launchers.process_simulation.launcher import HydroModPyLauncher

    launcher = HydroModPyLauncher(simulation_config_path)
    plan = launcher._create_simulation_plan()
    launcher._validate_runtime_mesh_solver_compatibility(plan)
    launcher.run_state.execution.simulation_plan = plan
    launcher.run_state.execution.process_runs_by_id = {
        run.id: run for run in plan.runs
    }

    launcher._run_setup()
    launcher._build_domain_spatial_supports(phase="setup")
    launcher._run_data()
    launcher._build_domain_spatial_supports(phase="data")
    launcher._run_mesh_phase()
    launcher._run_mesh_input_phase()

    setup_state = launcher.run_state.setup
    if setup_state.flow is None or setup_state.domain is None:
        return None

    if selected_solver == "modflow6":
        from hydromodpy.solver.modflow6.property_mapping import (
            resolve_flow_property_arrays as resolve_runtime_property_arrays,
        )

        sgrid_config = launcher.cfg.modflow6.sgrid
    elif selected_solver == "modflownwt":
        from hydromodpy.solver.modflow_nwt.modflow.property_mapping import (
            resolve_flow_property_arrays as resolve_runtime_property_arrays,
        )

        sgrid_config = launcher.cfg.modflownwt.sgrid
    else:
        return None

    grid_ctx = build_spatial_discretization(
        domain=setup_state.domain,
        sgrid_config=sgrid_config,
        runtime_planar_mesh=getattr(setup_state, "mesh_planar", None),
        runtime_mesh_support=getattr(setup_state, "mesh_support", None),
    )
    solver_mesh = grid_ctx.solver_mesh
    required_properties = {
        name
        for name in property_names
        if str(name).strip() in {"K", "Sy"}
    }
    if not required_properties:
        required_properties = {"K"}

    runtime_arrays = resolve_runtime_property_arrays(
        flow=setup_state.flow,
        domain=setup_state.domain,
        solver_mesh=solver_mesh,
        planar_mesh=getattr(setup_state, "mesh_planar", None),
        required_properties=required_properties,
        optional_fill_values={"Sy": 0.0},
    )

    base_property_arrays: dict[str, tuple[float, ...]] = {}
    if "hk_value" in runtime_arrays:
        base_property_arrays["K"] = _surface_property_vector(
            runtime_arrays["hk_value"],
            solver_mesh=solver_mesh,
        )
    if "sy_value" in runtime_arrays:
        base_property_arrays["Sy"] = _surface_property_vector(
            runtime_arrays["sy_value"],
            solver_mesh=solver_mesh,
        )

    lithology_labels: tuple[str, ...] | None = None
    bundle_has_labels = False
    zone_fractions_by_property: dict[str, dict[str, tuple[float, ...]]] = {}
    zone_fractions_by_key: dict[str, tuple[float, ...]] = {}
    base_property_values_by_key: dict[str, dict[str, float]] = {}
    support_id_by_property: dict[str, str] = {}
    mesh_bundle = getattr(setup_state, "mesh_bundle", None)
    if mesh_bundle is not None:
        bundle_labels = tuple(
            str(getattr(cell, "geology_key", "") or "").strip()
            for cell in getattr(mesh_bundle, "cells", ())
        )
        if any(bundle_labels):
            lithology_labels = bundle_labels
            bundle_has_labels = True
        zone_fractions_by_key = _bundle_zone_fractions(
            mesh_bundle,
            n_cells=max(1, int(getattr(solver_mesh, "n_cells", 1))),
        )
        if zone_fractions_by_key:
            for property_name in sorted(required_properties):
                zone_fractions_by_property[str(property_name)] = dict(
                    zone_fractions_by_key
                )

    domain = setup_state.domain
    mesh_for_support = getattr(setup_state, "mesh_planar", None)
    if mesh_for_support is None and bool(getattr(solver_mesh, "is_structured", False)):
        try:
            from hydromodpy.solver.utils import build_field_mesh_from_sgrid

            mesh_for_support = build_field_mesh_from_sgrid(solver_mesh)
        except Exception:
            mesh_for_support = None
    if mesh_for_support is None:
        solver_planar_mesh = getattr(solver_mesh, "planar_mesh", None)
        if hasattr(solver_planar_mesh, "cells"):
            mesh_for_support = solver_planar_mesh
    if mesh_for_support is None and hasattr(solver_mesh, "cells"):
        mesh_for_support = solver_mesh
    support_id_used: str | None = None
    mixed_support_ids = False
    if domain is not None and mesh_for_support is not None:
        for property_name in sorted(required_properties):
            property_name = str(property_name)
            property_cfg = _resolve_flow_property_config(
                raw_simulation_toml=raw_simulation_toml,
                property_name=property_name,
            )
            zone_values = _parse_property_values_by_key(property_cfg)
            if zone_values:
                base_property_values_by_key[property_name] = zone_values

            support_id = _parse_property_support_id(property_cfg)
            if support_id is None:
                continue
            resolver = getattr(domain, "resolve_spatial_support", None)
            if not callable(resolver):
                continue
            try:
                support_field = resolver(support_id)
            except Exception:
                continue
            if support_field is None or not hasattr(support_field, "on_mesh"):
                continue
            try:
                discretization = support_field.on_mesh(mesh_for_support)
                zone_keys, fractions_by_zone = discretization.weighted_components()
            except Exception:
                continue
            normalized_fractions = {
                str(zone_key).strip(): tuple(
                    float(value)
                    for value in np.asarray(
                        fractions_by_zone[zone_key],
                        dtype=float,
                    ).reshape(-1)
                )
                for zone_key in zone_keys
                if str(zone_key).strip() != ""
            }
            if not normalized_fractions:
                continue

            support_id_by_property[property_name] = str(support_id)
            zone_fractions_by_property[property_name] = normalized_fractions

            if support_id_used is None:
                support_id_used = str(support_id)
                if not zone_fractions_by_key:
                    zone_fractions_by_key = normalized_fractions
            elif str(support_id) != support_id_used:
                mixed_support_ids = True
                if not bundle_has_labels:
                    zone_fractions_by_key = {}

            if property_name in base_property_arrays:
                continue
            if not zone_values:
                continue
            if not all(zone_key in zone_values for zone_key in normalized_fractions):
                continue
            weighted = np.zeros(max(1, int(getattr(solver_mesh, "n_cells", 1))), dtype=float)
            for zone_key, fractions in normalized_fractions.items():
                weighted += np.asarray(fractions, dtype=float) * float(zone_values[zone_key])
            base_property_arrays[str(property_name)] = tuple(float(value) for value in weighted)

    if zone_fractions_by_key and not mixed_support_ids and lithology_labels is None:
        lithology_labels = _labels_from_zone_fractions(zone_fractions_by_key)

    source = f"runtime_prepared_{selected_solver}"
    if bundle_has_labels:
        source += "_geology"
    elif (
        zone_fractions_by_property
        or zone_fractions_by_key
        or lithology_labels is not None
    ):
        source += "_zones"
    mesh_bundle_dir, mesh_path, mesh_summary_path = _setup_mesh_paths_from_runtime(
        setup_state
    )
    return PreparedHydraulicPropertySupport(
        n_cells=max(1, int(getattr(solver_mesh, "n_cells", 1))),
        lithology_labels=lithology_labels,
        base_property_arrays=base_property_arrays,
        zone_fractions_by_property=zone_fractions_by_property,
        zone_fractions_by_key=zone_fractions_by_key,
        base_property_values_by_key=base_property_values_by_key,
        support_id_by_property=support_id_by_property,
        source=source,
        mesh_bundle_dir=mesh_bundle_dir,
        mesh_path=mesh_path,
        mesh_summary_path=mesh_summary_path,
    )


@dataclass(frozen=True, slots=True)
class IterationRecord:
    """Minimal persisted record for one calibration iteration."""

    iteration_id: str
    params_vector: tuple[float, ...]
    params_named: dict[str, float]
    objective_total: float | None
    block_costs: dict[str, float] = field(default_factory=dict)
    status: str = "ok"
    failure_reason: str | None = None
    objective_score: float | None = None
    block_details: tuple[dict[str, Any], ...] = ()
    objective_metadata: dict[str, Any] = field(default_factory=dict)
    candidate_run_id: str | None = None
    candidate_config_path: str | None = None

    def to_mapping(self, *, detail_level: str = "minimal") -> dict[str, Any]:
        """Return one JSON-serializable view of the iteration record."""
        detail_key = str(detail_level).strip().lower()
        payload = {
            "iteration_id": str(self.iteration_id),
            "params_vector": [float(value) for value in self.params_vector],
            "params_named": {
                str(name): float(value) for name, value in self.params_named.items()
            },
            "objective_total": (
                None if self.objective_total is None else float(self.objective_total)
            ),
            "block_costs": {
                str(name): float(value) for name, value in self.block_costs.items()
            },
            "status": str(self.status),
            "failure_reason": (
                None if self.failure_reason is None else str(self.failure_reason)
            ),
        }
        if detail_key in {"diagnostic", "full"}:
            payload.update(
                {
                    "objective_score": (
                        None
                        if self.objective_score is None
                        else float(self.objective_score)
                    ),
                    "block_details": _jsonable(list(self.block_details)),
                    "candidate_run_id": self.candidate_run_id,
                    "candidate_config_path": self.candidate_config_path,
                }
            )
        if detail_key == "full":
            payload["objective_metadata"] = _jsonable(self.objective_metadata)
        return payload


@dataclass(frozen=True, slots=True)
class CandidateRunRequest:
    """One materialized candidate derived from a prepared calibration session."""

    session: PreparedCalibrationSession
    iteration_id: str
    candidate_run_id: str
    candidate_root: Path
    candidate_config_path: Path
    params_vector: tuple[float, ...]
    params_named: dict[str, float]
    override_payload: dict[str, Any]
    property_array_set: PropertyArraySet | None = None
    property_array_summary: dict[str, Any] | None = None
    property_array_error: str | None = None
    actualize_seconds: float | None = None

    def to_summary(self) -> dict[str, Any]:
        """Return one concise summary of the candidate runtime request."""
        return {
            "iteration_id": self.iteration_id,
            "candidate_run_id": self.candidate_run_id,
            "candidate_root": str(self.candidate_root),
            "candidate_config_path": str(self.candidate_config_path),
            "params_vector": [float(value) for value in self.params_vector],
            "params_named": {
                str(name): float(value) for name, value in self.params_named.items()
            },
            "property_array_set": (
                None
                if self.property_array_set is None
                else self.property_array_set.to_summary()
            ),
            "property_array_summary": self.property_array_summary,
            "property_array_error": self.property_array_error,
            "actualize_seconds": self.actualize_seconds,
        }


@dataclass(frozen=True, slots=True)
class CandidateRunOutcome:
    """Outcome of one candidate execution attempt."""

    request: CandidateRunRequest
    status: str
    run_state: Any | None = None
    objective_evaluation: CompositeObjectiveEvaluation | None = None
    error_type: str | None = None
    error_message: str | None = None
    launcher_prepare_seconds: float | None = None
    runtime_patch_seconds: float | None = None
    simulation_seconds: float | None = None
    objective_seconds: float | None = None
    total_seconds: float | None = None

    def to_iteration_record(self) -> IterationRecord:
        """Convert one run outcome into the persisted minimal iteration record."""
        failure_reason = self.error_message
        objective_total: float | None = None
        objective_score: float | None = None
        block_costs: dict[str, float] = {}
        block_details: tuple[dict[str, Any], ...] = ()
        objective_metadata: dict[str, Any] = {}
        if self.objective_evaluation is not None:
            objective_total = float(self.objective_evaluation.total_cost)
            objective_score = float(self.objective_evaluation.total_score)
            block_costs = {
                block.name: float(block.normalized_cost)
                for block in self.objective_evaluation.blocks
            }
            block_details = tuple(
                block.to_mapping()
                for block in self.objective_evaluation.blocks
            )
            objective_metadata = dict(self.objective_evaluation.metadata)
        elif self.status in {"solver_run_failed", "objective_evaluation_failed"}:
            objective_total = math.inf
        timing_payload = {
            "actualize_seconds": (
                None
                if self.request.actualize_seconds is None
                else float(self.request.actualize_seconds)
            ),
            "launcher_prepare_seconds": self.launcher_prepare_seconds,
            "runtime_patch_seconds": self.runtime_patch_seconds,
            "simulation_seconds": self.simulation_seconds,
            "objective_seconds": self.objective_seconds,
            "total_seconds": self.total_seconds,
            "preparation_seconds": (
                None
                if (
                    self.request.actualize_seconds is None
                    and self.launcher_prepare_seconds is None
                    and self.runtime_patch_seconds is None
                )
                else float(self.request.actualize_seconds or 0.0)
                + float(self.launcher_prepare_seconds or 0.0)
                + float(self.runtime_patch_seconds or 0.0)
            ),
        }
        if any(value is not None for value in timing_payload.values()):
            objective_metadata = dict(objective_metadata)
            objective_metadata["timing"] = timing_payload
        return IterationRecord(
            iteration_id=self.request.iteration_id,
            params_vector=self.request.params_vector,
            params_named=self.request.params_named,
            objective_total=objective_total,
            block_costs=block_costs,
            status=self.status,
            failure_reason=failure_reason,
            objective_score=objective_score,
            block_details=block_details,
            objective_metadata=objective_metadata,
            candidate_run_id=self.request.candidate_run_id,
            candidate_config_path=str(self.request.candidate_config_path),
        )


def _jsonable(value: Any) -> Any:
    """Convert common runtime values to JSON-friendly Python values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return [_jsonable(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        return _jsonable(value.item())
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    try:
        json.dumps(value)
    except TypeError:
        return repr(value)
    return value


def _session_contract_payload(
    *,
    session: PreparedCalibrationSession | None = None,
    cfg: ModelCalibrationConfig,
    raw_simulation_toml: dict[str, Any] | None = None,
    simulation_config_path: Path | None = None,
    primary_solver: str | None = None,
    solver_families: tuple[str, ...] | None = None,
    prepared_hydraulic_support: PreparedHydraulicPropertySupport | None = None,
) -> dict[str, Any]:
    """Build the stable calibration contract persisted for session reuse checks."""
    if session is not None:
        raw_simulation_toml = dict(session.raw_simulation_toml)
        simulation_config_path = session.simulation_config_path
        primary_solver = session.primary_solver
        solver_families = session.solver_families
        prepared_hydraulic_support = session.prepared_hydraulic_support
    return {
        "schema": "model_calibration_session_contract_v1",
        "simulation_config_path": (
            None if simulation_config_path is None else str(simulation_config_path)
        ),
        "raw_simulation_toml": _jsonable(raw_simulation_toml or {}),
        "primary_solver": primary_solver,
        "solver_families": list(solver_families or ()),
        "bounds": {
            str(name): [float(pair[0]), float(pair[1])]
            for name, pair in cfg.bounds.items()
        },
        "calibration": {
            "objective_metric": str(cfg.calibration.objective_metric),
            "global_method": str(cfg.calibration.global_method),
        },
        "objective": _jsonable(cfg.objective.model_dump(mode="python")),
        "parameters": [
            _jsonable(item.model_dump(mode="python"))
            for item in cfg.model_calibration.parameter
        ],
        "outputs": [
            _jsonable(item.model_dump(mode="python"))
            for item in cfg.model_calibration.output
        ],
        "objective_blocks": [
            _jsonable(item.model_dump(mode="python"))
            for item in cfg.model_calibration.objective_block
        ],
        "prepared_hydraulic_support": (
            None
            if prepared_hydraulic_support is None
            else prepared_hydraulic_support.to_summary()
        ),
    }


def _session_contract_signature(
    *,
    session: PreparedCalibrationSession | None = None,
    cfg: ModelCalibrationConfig,
    raw_simulation_toml: dict[str, Any] | None = None,
    simulation_config_path: Path | None = None,
    primary_solver: str | None = None,
    solver_families: tuple[str, ...] | None = None,
    prepared_hydraulic_support: PreparedHydraulicPropertySupport | None = None,
) -> str:
    """Hash the stable calibration contract used to validate session reuse."""
    payload = _session_contract_payload(
        session=session,
        cfg=cfg,
        raw_simulation_toml=raw_simulation_toml,
        simulation_config_path=simulation_config_path,
        primary_solver=primary_solver,
        solver_families=solver_families,
        prepared_hydraulic_support=prepared_hydraulic_support,
    )
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _parameter_statistics(
    *,
    samples: np.ndarray,
    parameter_names: tuple[str, ...],
) -> dict[str, dict[str, float]]:
    """Summarize one parameter sample matrix by named marginal statistics."""
    if samples.size == 0:
        return {}
    stats: dict[str, dict[str, float]] = {}
    quantiles = np.nanpercentile(samples, [5.0, 50.0, 95.0], axis=0)
    for index, name in enumerate(parameter_names):
        values = samples[:, index]
        stats[str(name)] = {
            "mean": float(np.nanmean(values)),
            "std": float(np.nanstd(values, ddof=1)) if values.size > 1 else 0.0,
            "min": float(np.nanmin(values)),
            "q05": float(quantiles[0, index]),
            "q50": float(quantiles[1, index]),
            "q95": float(quantiles[2, index]),
            "max": float(np.nanmax(values)),
        }
    return stats


def _params_named_from_vector(
    *,
    session: PreparedCalibrationSession,
    vector: Any,
) -> dict[str, float]:
    """Map one ordered vector to calibrated parameter names."""
    parameter_set = session.core_settings["parameter_set"]
    return {
        str(name): float(value)
        for name, value in parameter_set.mapping_from(vector).items()
    }


def _safe_params_named_from_vector(
    *,
    session: PreparedCalibrationSession,
    vector: Any,
) -> dict[str, float]:
    """Map a vector to names, falling back to positional names on bad payloads."""
    try:
        return _params_named_from_vector(session=session, vector=vector)
    except Exception:
        values = tuple(float(value) for value in np.asarray(vector, dtype=float).ravel())
        return {
            str(name): float(value)
            for name, value in zip(session.parameter_names, values, strict=False)
        }


def _sample_rows_from_matrix(
    *,
    session: PreparedCalibrationSession,
    samples: np.ndarray,
) -> list[dict[str, Any]]:
    """Serialize a parameter sample matrix as model-distribution rows."""
    rows: list[dict[str, Any]] = []
    for index, vector in enumerate(samples, start=1):
        params_vector = tuple(float(value) for value in np.asarray(vector).ravel())
        rows.append(
            {
                "sample_id": f"sample_{index:06d}",
                "params_vector": list(params_vector),
                "params_named": _params_named_from_vector(
                    session=session,
                    vector=params_vector,
                ),
            }
        )
    return rows


def _sample_rows_from_iteration_records(
    records: tuple[IterationRecord, ...],
) -> list[dict[str, Any]]:
    """Serialize persisted or current records as an empirical ensemble."""
    rows: list[dict[str, Any]] = []
    for record in records:
        rows.append(
            {
                "sample_id": record.iteration_id,
                "candidate_run_id": record.candidate_run_id,
                "candidate_config_path": record.candidate_config_path,
                "params_vector": list(record.params_vector),
                "params_named": dict(record.params_named),
                "objective_total": record.objective_total,
                "block_costs": dict(record.block_costs),
                "status": record.status,
                "failure_reason": record.failure_reason,
            }
        )
    return rows


def build_model_distribution_payload(
    *,
    session: PreparedCalibrationSession,
    result: Any,
    evaluator: ModelCalibrationObjectiveEvaluator,
) -> dict[str, Any] | None:
    """Build a persisted parameter/model distribution payload when available."""
    method = str(result.method).strip().lower()
    parameter_names = tuple(session.parameter_names)
    result_samples = getattr(result, "samples", None)
    if result_samples is not None:
        samples = np.asarray(result_samples, dtype=float)
        if samples.ndim == 2 and samples.shape[0] > 0:
            return {
                "role": (
                    "posterior_parameter_distribution"
                    if method in _POSTERIOR_DISTRIBUTION_METHODS
                    else "parameter_sample_distribution"
                ),
                "method": method,
                "source": "CalibrationResults.samples",
                "parameter_names": list(parameter_names),
                "sample_count": int(samples.shape[0]),
                "model_semantics": (
                    "Each row defines one parameterized model. Full model "
                    "outputs are obtained by materializing and running that "
                    "parameter set as a candidate."
                ),
                "statistics": _parameter_statistics(
                    samples=samples,
                    parameter_names=parameter_names,
                ),
                "samples": _sample_rows_from_matrix(
                    session=session,
                    samples=samples,
                ),
            }

    if method not in _EMPIRICAL_ENSEMBLE_METHODS:
        return None

    records = evaluator.empirical_iteration_records
    if not records:
        return None
    samples = np.asarray(
        [record.params_vector for record in records],
        dtype=float,
    )
    return {
        "role": "empirical_evaluated_model_ensemble",
        "method": method,
        "source": (
            "persisted_and_evaluated_candidates"
            if evaluator.restored_evaluation_count > 0
            else "evaluated_candidates"
        ),
        "parameter_names": list(parameter_names),
        "sample_count": int(samples.shape[0]),
        "model_semantics": (
            "Each row is a model candidate already evaluated during the "
            "stochastic search, with its objective value when available."
        ),
        "statistics": _parameter_statistics(
            samples=samples,
            parameter_names=parameter_names,
        ),
        "samples": _sample_rows_from_iteration_records(records),
    }


def _sample_objective_total(sample: dict[str, Any]) -> float | None:
    """Return one finite objective value when a sample carries one."""
    value = sample.get("objective_total")
    if value is None:
        return None
    try:
        objective = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(objective):
        return None
    return objective


def _unique_limited(indices: list[int], *, max_count: int) -> tuple[int, ...]:
    """Keep first-seen unique indices up to `max_count`."""
    selected: list[int] = []
    seen: set[int] = set()
    for index in indices:
        if index in seen:
            continue
        selected.append(int(index))
        seen.add(int(index))
        if len(selected) >= max_count:
            break
    return tuple(selected)


def _evenly_spaced_indices(total_count: int, *, max_count: int) -> tuple[int, ...]:
    """Return stable row indices spread over `[0, total_count)`."""
    if total_count <= 0 or max_count <= 0:
        return ()
    if total_count <= max_count:
        return tuple(range(total_count))
    raw_indices = [
        int(round(float(value)))
        for value in np.linspace(0, total_count - 1, num=max_count)
    ]
    if len(set(raw_indices)) < max_count:
        raw_indices.extend(range(total_count))
    return _unique_limited(raw_indices, max_count=max_count)


def _finite_objective_rank_indices(
    samples: list[dict[str, Any]],
) -> tuple[int, ...]:
    """Return sample row indices sorted from best to worst finite objective."""
    ranked: list[tuple[float, int]] = []
    for index, sample in enumerate(samples):
        objective = _sample_objective_total(sample)
        if objective is not None:
            ranked.append((objective, index))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return tuple(index for _, index in ranked)


def _representative_parameter_indices(
    samples: list[dict[str, Any]],
    *,
    max_count: int,
) -> tuple[int, ...]:
    """Select sample rows closest to marginal parameter quantile vectors."""
    if max_count <= 0:
        return ()

    vectors: list[np.ndarray] = []
    row_indices: list[int] = []
    for index, sample in enumerate(samples):
        try:
            vector = np.asarray(sample["params_vector"], dtype=float).ravel()
        except (KeyError, TypeError, ValueError):
            continue
        if vector.size == 0 or not np.all(np.isfinite(vector)):
            continue
        vectors.append(vector)
        row_indices.append(index)

    if not vectors:
        return _evenly_spaced_indices(len(samples), max_count=max_count)
    if len(vectors) <= max_count:
        return tuple(row_indices)

    matrix = np.vstack(vectors)
    probabilities = (
        np.asarray([0.5], dtype=float)
        if max_count == 1
        else np.linspace(0.05, 0.95, num=max_count)
    )
    targets = np.nanquantile(matrix, probabilities, axis=0)
    scale = np.nanstd(matrix, axis=0)
    scale = np.where(np.isfinite(scale) & (scale > 0.0), scale, 1.0)

    selected: list[int] = []
    for target in np.atleast_2d(targets):
        distances = np.linalg.norm((matrix - target) / scale, axis=1)
        selected.append(row_indices[int(np.nanargmin(distances))])
    selected.extend(_evenly_spaced_indices(len(samples), max_count=max_count))
    return _unique_limited(selected, max_count=max_count)


def select_model_distribution_samples(
    *,
    payload: dict[str, Any],
    max_count: int,
    selection: str,
) -> list[tuple[int, dict[str, Any]]]:
    """Select model-distribution rows for optional full-output reruns."""
    if max_count <= 0:
        return []
    raw_samples = payload.get("samples")
    if not isinstance(raw_samples, list) or not raw_samples:
        return []
    indexed_samples = [
        (index, sample)
        for index, sample in enumerate(raw_samples)
        if isinstance(sample, dict)
    ]
    samples = [sample for _, sample in indexed_samples]
    max_count = min(int(max_count), len(samples))
    if max_count <= 0:
        return []

    selection_mode = str(selection).strip().lower()
    if selection_mode == "evenly_spaced":
        selected_indices = _evenly_spaced_indices(len(samples), max_count=max_count)
    elif selection_mode == "best":
        ranked = list(_finite_objective_rank_indices(samples))
        ranked.extend(range(len(samples)))
        selected_indices = _unique_limited(ranked, max_count=max_count)
    else:
        ranked = _finite_objective_rank_indices(samples)
        if ranked:
            rank_positions = _evenly_spaced_indices(
                len(ranked),
                max_count=max_count,
            )
            selected_indices = tuple(ranked[position] for position in rank_positions)
        else:
            selected_indices = _representative_parameter_indices(
                samples,
                max_count=max_count,
            )

    return [
        (indexed_samples[index][0], samples[index])
        for index in selected_indices
    ]


def persist_model_distribution(
    *,
    session: PreparedCalibrationSession,
    result: Any | None = None,
    evaluator: ModelCalibrationObjectiveEvaluator | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Write `model_distribution.json` when the method exposes an ensemble."""
    if payload is None:
        if result is None or evaluator is None:
            raise ValueError(
                "persist_model_distribution requires either payload or "
                "result/evaluator"
            )
        payload = build_model_distribution_payload(
            session=session,
            result=result,
            evaluator=evaluator,
        )
    if payload is None:
        return None

    distribution_path = session.calibration_root / "model_distribution.json"
    distribution_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return {
        "path": str(distribution_path),
        "role": payload["role"],
        "method": payload["method"],
        "source": payload["source"],
        "sample_count": payload["sample_count"],
    }


def execute_model_distribution_reruns(
    *,
    session: PreparedCalibrationSession,
    cfg: ModelCalibrationConfig,
    distribution_payload: dict[str, Any] | None,
    launcher_factory: Any,
    max_reruns: int,
    selection: str,
) -> dict[str, Any] | None:
    """Run a selected subset of model-distribution samples with full outputs."""
    if distribution_payload is None:
        return {
            "status": "skipped",
            "reason": "no_model_distribution",
            "selected_count": 0,
        }

    selected_samples = select_model_distribution_samples(
        payload=distribution_payload,
        max_count=max_reruns,
        selection=selection,
    )
    manifest_path = session.calibration_root / "model_distribution_reruns.json"
    rerun_rows: list[dict[str, Any]] = []
    for ordinal, (sample_index, sample) in enumerate(selected_samples, start=1):
        sample_id = str(sample.get("sample_id", f"sample_{sample_index + 1:06d}"))
        params_vector = tuple(float(value) for value in sample["params_vector"])
        try:
            request = actualize_candidate(
                session=session,
                cfg=cfg,
                params=params_vector,
                candidate_label=f"ensemble_{ordinal:04d}_{sample_id}",
                disable_display=False,
                disable_postprocess=False,
            )
        except Exception as exc:
            rerun_rows.append(
                {
                    "rerun_id": f"ensemble_{ordinal:04d}",
                    "sample_index": int(sample_index),
                    "sample_id": sample_id,
                    "source_objective_total": sample.get("objective_total"),
                    "source_block_costs": sample.get("block_costs"),
                    "status": "parameter_injection_failed",
                    "candidate_run_id": None,
                    "candidate_config_path": None,
                    "params_vector": list(params_vector),
                    "params_named": _safe_params_named_from_vector(
                        session=session,
                        vector=params_vector,
                    ),
                    "error_type": type(exc).__name__,
                    "error_message": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        outcome = execute_candidate_run(
            request=request,
            launcher_factory=launcher_factory,
            cfg=None,
        )
        rerun_rows.append(
            {
                "rerun_id": f"ensemble_{ordinal:04d}",
                "sample_index": int(sample_index),
                "sample_id": sample_id,
                "source_objective_total": sample.get("objective_total"),
                "source_block_costs": sample.get("block_costs"),
                "status": outcome.status,
                "candidate_run_id": outcome.request.candidate_run_id,
                "candidate_config_path": str(outcome.request.candidate_config_path),
                "params_vector": list(outcome.request.params_vector),
                "params_named": dict(outcome.request.params_named),
                "error_type": outcome.error_type,
                "error_message": outcome.error_message,
            }
        )

    status = (
        "completed"
        if all(row["status"] == "solver_run_succeeded" for row in rerun_rows)
        else "completed_with_failures"
    )
    if not rerun_rows:
        status = "skipped"
    manifest_payload = {
        "role": "model_distribution_output_reruns",
        "source_model_distribution_role": distribution_payload.get("role"),
        "source_model_distribution_method": distribution_payload.get("method"),
        "selection": str(selection),
        "requested_max_reruns": int(max_reruns),
        "selected_count": len(rerun_rows),
        "status": status,
        "reruns": rerun_rows,
    }
    manifest_path.write_text(
        json.dumps(manifest_payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return {
        "path": str(manifest_path),
        "status": status,
        "selection": str(selection),
        "requested_max_reruns": int(max_reruns),
        "selected_count": len(rerun_rows),
    }


def serialize_calibration_result(result: Any) -> dict[str, Any]:
    """Return one JSON-serializable summary of a core calibration result."""
    payload = {
        "method": str(result.method),
        "x_best": _jsonable(result.x_best),
        "params_best": _jsonable(result.params_best),
        "cost_best": float(result.cost_best),
        "score_best": (
            None if result.score_best is None else float(result.score_best)
        ),
        "n_evaluations": int(result.n_evaluations),
        "metadata": _jsonable(getattr(result, "metadata", {})),
    }
    samples = getattr(result, "samples", None)
    if samples is not None:
        payload["samples"] = _jsonable(samples)
    return payload


def _failed_objective_evaluation(
    outcome: CandidateRunOutcome,
) -> CompositeObjectiveEvaluation:
    """Represent a failed candidate as an infinite objective evaluation."""
    return CompositeObjectiveEvaluation(
        total_cost=math.inf,
        total_score=-math.inf,
        blocks=(),
        metadata={
            "status": outcome.status,
            "error_type": outcome.error_type,
            "error_message": outcome.error_message,
            "iteration_id": outcome.request.iteration_id,
            "candidate_run_id": outcome.request.candidate_run_id,
            "candidate_config_path": str(outcome.request.candidate_config_path),
        },
    )


def _failed_parameter_injection_evaluation(
    *,
    iteration_id: str,
    params_vector: tuple[float, ...],
    error: Exception,
) -> CompositeObjectiveEvaluation:
    """Represent a failed parameter injection as an infinite objective value."""
    return CompositeObjectiveEvaluation(
        total_cost=math.inf,
        total_score=-math.inf,
        blocks=(),
        metadata={
            "status": "parameter_injection_failed",
            "error_type": type(error).__name__,
            "error_message": f"{type(error).__name__}: {error}",
            "iteration_id": iteration_id,
            "params_vector": list(params_vector),
        },
    )


def _sanitize_candidate_label(label: str) -> str:
    """Return one filesystem-safe candidate label."""
    text = str(label).strip().lower()
    if not text:
        raise ValueError("candidate_label cannot be empty")
    return re.sub(r"[^a-z0-9_.-]+", "_", text)


def validate_objective_ready_for_calibration(
    cfg: ModelCalibrationConfig,
) -> None:
    """Reject calibration runs whose composite objective cannot yet be evaluated."""
    outputs_by_name = {
        output_cfg.name: output_cfg for output_cfg in cfg.model_calibration.output
    }
    missing_observations: list[str] = []
    direct_cost_blocks: list[str] = []
    for block_cfg in cfg.model_calibration.objective_block:
        if block_cfg.metric == "direct_cost":
            direct_cost_blocks.append(block_cfg.name)
        for output_name in block_cfg.uses_outputs:
            output_cfg = outputs_by_name[output_name]
            if output_cfg.observed_values is None:
                missing_observations.append(f"{block_cfg.name}:{output_name}")

    if direct_cost_blocks:
        raise NotImplementedError(
            "direct_cost objective blocks are reserved for future map comparisons: "
            f"{direct_cost_blocks}"
        )
    if missing_observations:
        raise ValueError(
            "Full model calibration requires observed_values for every output used "
            f"by objective blocks. Missing: {missing_observations}"
        )


def _load_persisted_iteration_rows(history_path: Path) -> list[dict[str, Any]]:
    """Load persisted iteration JSONL rows when available."""
    if not history_path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in history_path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        rows.append(json.loads(text))
    return rows


def _manifest_allows_persisted_iteration_reuse(
    session: PreparedCalibrationSession,
) -> bool:
    """Return True when the on-disk manifest matches the current session contract."""
    manifest_path = session.session_manifest_path
    if not manifest_path.is_file():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    signature = manifest.get("session_contract_signature")
    reuse_allowed = manifest.get("persisted_iteration_reuse_allowed", True)
    if not bool(reuse_allowed) or signature is None:
        return False
    return str(signature) == str(session.contract_signature)


def _iteration_record_from_history_row(row: dict[str, Any]) -> IterationRecord | None:
    """Rehydrate one persisted JSONL row into an iteration record."""
    if not isinstance(row, dict):
        return None
    params_vector_raw = row.get("params_vector")
    params_named_raw = row.get("params_named")
    objective_total = row.get("objective_total")
    if not isinstance(params_vector_raw, list) or not isinstance(params_named_raw, dict):
        return None
    try:
        params_vector = tuple(float(value) for value in params_vector_raw)
        params_named = {
            str(name): float(value) for name, value in params_named_raw.items()
        }
    except (TypeError, ValueError):
        return None
    objective_value = None if objective_total is None else float(objective_total)
    block_costs_raw = row.get("block_costs", {})
    block_costs = (
        {
            str(name): float(value)
            for name, value in block_costs_raw.items()
        }
        if isinstance(block_costs_raw, dict)
        else {}
    )
    block_details_raw = row.get("block_details", ())
    block_details = (
        tuple(item for item in block_details_raw if isinstance(item, dict))
        if isinstance(block_details_raw, list)
        else ()
    )
    objective_metadata = row.get("objective_metadata", {})
    if not isinstance(objective_metadata, dict):
        objective_metadata = {}
    return IterationRecord(
        iteration_id=str(row.get("iteration_id", "")),
        params_vector=params_vector,
        params_named=params_named,
        objective_total=objective_value,
        block_costs=block_costs,
        status=str(row.get("status", "unknown")),
        failure_reason=(
            None
            if row.get("failure_reason") is None
            else str(row.get("failure_reason"))
        ),
        objective_score=(
            None
            if row.get("objective_score") is None
            else float(row.get("objective_score"))
        ),
        block_details=block_details,
        objective_metadata=objective_metadata,
        candidate_run_id=(
            None
            if row.get("candidate_run_id") is None
            else str(row.get("candidate_run_id"))
        ),
        candidate_config_path=(
            None
            if row.get("candidate_config_path") is None
            else str(row.get("candidate_config_path"))
        ),
    )


def _block_weight_map(cfg: ModelCalibrationConfig) -> dict[str, float]:
    """Return normalized objective-block weights."""
    raw_weights = {
        str(block_cfg.name): float(block_cfg.weight)
        for block_cfg in cfg.model_calibration.objective_block
    }
    total_weight = sum(raw_weights.values())
    if total_weight <= 0.0:
        return {name: 0.0 for name in raw_weights}
    return {
        name: float(weight / total_weight) for name, weight in raw_weights.items()
    }


def _block_n_values_map(cfg: ModelCalibrationConfig) -> dict[str, int]:
    """Infer observed-value counts by objective block when available."""
    outputs_by_name = {
        output_cfg.name: output_cfg for output_cfg in cfg.model_calibration.output
    }
    counts: dict[str, int] = {}
    for block_cfg in cfg.model_calibration.objective_block:
        total = 0
        for output_name in block_cfg.uses_outputs:
            observed_values = outputs_by_name[output_name].observed_values
            total += 0 if observed_values is None else len(observed_values)
        counts[str(block_cfg.name)] = int(total)
    return counts


def _rehydrate_block_evaluations(
    *,
    cfg: ModelCalibrationConfig,
    record: IterationRecord,
) -> tuple[CompositeBlockEvaluation, ...]:
    """Rebuild block evaluations from persisted iteration history."""
    if record.block_details:
        blocks: list[CompositeBlockEvaluation] = []
        for payload in record.block_details:
            blocks.append(
                CompositeBlockEvaluation(
                    name=str(payload.get("name", "")),
                    metric=str(payload.get("metric", "rmse")),
                    weight_raw=float(payload.get("weight_raw", 1.0)),
                    weight_normalized=float(payload.get("weight_normalized", 1.0)),
                    score=float(
                        payload.get(
                            "score",
                            -float(payload.get("normalized_cost", 0.0)),
                        )
                    ),
                    raw_cost=float(
                        payload.get(
                            "raw_cost",
                            payload.get("normalized_cost", 0.0),
                        )
                    ),
                    normalized_cost=float(payload.get("normalized_cost", 0.0)),
                    reference_scale=float(payload.get("reference_scale", 1.0)),
                    n_values=int(payload.get("n_values", 0)),
                    metadata=dict(payload.get("metadata", {})),
                )
            )
        return tuple(blocks)

    if not record.block_costs:
        return ()

    block_cfg_by_name = {
        str(block_cfg.name): block_cfg
        for block_cfg in cfg.model_calibration.objective_block
    }
    normalized_weights = _block_weight_map(cfg)
    n_values_by_block = _block_n_values_map(cfg)
    blocks = []
    for block_name, normalized_cost in record.block_costs.items():
        block_cfg = block_cfg_by_name.get(block_name)
        if block_cfg is None:
            continue
        blocks.append(
            CompositeBlockEvaluation(
                name=block_name,
                metric=str(block_cfg.metric),
                weight_raw=float(block_cfg.weight),
                weight_normalized=float(normalized_weights.get(block_name, 0.0)),
                score=-float(normalized_cost),
                raw_cost=float(normalized_cost),
                normalized_cost=float(normalized_cost),
                reference_scale=1.0,
                n_values=int(n_values_by_block.get(block_name, 0)),
                metadata={
                    "rehydrated_from_history": True,
                    "uses_outputs": tuple(block_cfg.uses_outputs),
                },
            )
        )
    return tuple(blocks)


def _rehydrate_objective_evaluation(
    *,
    cfg: ModelCalibrationConfig,
    record: IterationRecord,
) -> CompositeObjectiveEvaluation | None:
    """Rebuild one objective evaluation from persisted iteration history."""
    if record.objective_total is None:
        return None
    total_cost = float(record.objective_total)
    metadata = dict(record.objective_metadata)
    metadata.setdefault("rehydrated_from_history", True)
    metadata.setdefault("status", record.status)
    metadata.setdefault("iteration_id", record.iteration_id)
    metadata.setdefault("candidate_run_id", record.candidate_run_id)
    return CompositeObjectiveEvaluation(
        total_cost=total_cost,
        total_score=record.objective_score,
        blocks=_rehydrate_block_evaluations(cfg=cfg, record=record),
        metadata=metadata,
    )


@dataclass
class ModelCalibrationObjectiveEvaluator:
    """Objective evaluator that lets CalibrationEngine drive launcher candidates."""

    session: PreparedCalibrationSession
    cfg: ModelCalibrationConfig
    launcher_factory: Any
    iteration_start: int = 1
    record_callback: Callable[[IterationRecord], None] | None = None
    _next_iteration_index: int = field(init=False, repr=False)
    _evaluations_by_key: dict[tuple[float, ...], CompositeObjectiveEvaluation] = (
        field(default_factory=dict, init=False, repr=False)
    )
    _outcomes_by_key: dict[tuple[float, ...], CandidateRunOutcome] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    _persisted_records_by_key: dict[tuple[float, ...], IterationRecord] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    cache_hit_count: int = field(default=0, init=False)
    candidate_run_count: int = field(default=0, init=False)
    restored_evaluation_count: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        validate_objective_ready_for_calibration(self.cfg)
        if (
            self.cfg.model_calibration.reuse_persisted_iterations
            and _manifest_allows_persisted_iteration_reuse(self.session)
        ):
            self._restore_persisted_evaluations()
        self._next_iteration_index = int(self.iteration_start)

    def _restore_persisted_evaluations(self) -> None:
        """Warm the evaluator cache from persisted iteration history."""
        for row in _load_persisted_iteration_rows(self.session.iteration_history_path):
            record = _iteration_record_from_history_row(row)
            if record is None:
                continue
            evaluation = _rehydrate_objective_evaluation(cfg=self.cfg, record=record)
            if evaluation is None:
                continue
            key = tuple(float(value) for value in record.params_vector)
            self._evaluations_by_key[key] = evaluation
            self._persisted_records_by_key[key] = record
        self.restored_evaluation_count = int(len(self._persisted_records_by_key))

    def _cache_key(
        self,
        params: dict[str, float] | tuple[float, ...],
    ) -> tuple[float, ...]:
        parameter_set = self.session.core_settings["parameter_set"]
        return tuple(float(value) for value in parameter_set.vector_from(params))

    def evaluate(self, params: dict[str, float]) -> CompositeObjectiveEvaluation:
        """Run or reuse one candidate objective evaluation."""
        key = self._cache_key(params)
        cached = self._evaluations_by_key.get(key)
        if cached is not None:
            self.cache_hit_count += 1
            return cached

        iteration_index = self._next_iteration_index
        self._next_iteration_index += 1
        iteration_id = f"iter_{int(iteration_index):04d}"
        try:
            actualize_start = time.perf_counter()
            request = actualize_candidate(
                session=self.session,
                cfg=self.cfg,
                params=key,
                iteration_index=iteration_index,
            )
            request = replace(
                request,
                actualize_seconds=float(time.perf_counter() - actualize_start),
            )
        except Exception as exc:
            params_named = _safe_params_named_from_vector(
                session=self.session,
                vector=key,
            )
            record = IterationRecord(
                iteration_id=iteration_id,
                params_vector=key,
                params_named=params_named,
                objective_total=math.inf,
                block_costs={},
                status="parameter_injection_failed",
                failure_reason=f"{type(exc).__name__}: {exc}",
                objective_score=-math.inf,
                objective_metadata={
                    "status": "parameter_injection_failed",
                    "error_type": type(exc).__name__,
                    "error_message": f"{type(exc).__name__}: {exc}",
                },
            )
            if self.record_callback is not None:
                self.record_callback(record)
            evaluation = _failed_parameter_injection_evaluation(
                iteration_id=iteration_id,
                params_vector=key,
                error=exc,
            )
            self._evaluations_by_key[key] = evaluation
            return evaluation
        outcome = execute_candidate_run(
            request=request,
            launcher_factory=self.launcher_factory,
            cfg=self.cfg,
        )
        self.candidate_run_count += 1
        if self.record_callback is not None:
            self.record_callback(outcome.to_iteration_record())

        evaluation = (
            outcome.objective_evaluation
            if outcome.objective_evaluation is not None
            else _failed_objective_evaluation(outcome)
        )
        self._outcomes_by_key[key] = outcome
        self._evaluations_by_key[key] = evaluation
        return evaluation

    @property
    def outcomes(self) -> tuple[CandidateRunOutcome, ...]:
        """Return unique executed candidate outcomes in evaluation order."""
        return tuple(self._outcomes_by_key.values())

    @property
    def empirical_iteration_records(self) -> tuple[IterationRecord, ...]:
        """Return persisted plus newly evaluated records keyed by parameter vector."""
        combined = dict(self._persisted_records_by_key)
        for key, outcome in self._outcomes_by_key.items():
            combined[key] = outcome.to_iteration_record()
        return tuple(combined.values())


def _summarize_candidate_run_timings(
    outcomes: tuple[CandidateRunOutcome, ...],
) -> dict[str, Any]:
    """Aggregate candidate timing diagnostics across executed outcomes."""
    if not outcomes:
        return {
            "count": 0,
            "prepare_time_seconds": None,
            "simulation_time_seconds": None,
            "objective_time_seconds": None,
            "total_time_seconds": None,
        }

    def _series(values: list[float]) -> dict[str, float] | None:
        if not values:
            return None
        arr = np.asarray(values, dtype=float)
        return {
            "mean": float(np.mean(arr)),
            "median": float(np.median(arr)),
            "max": float(np.max(arr)),
            "sum": float(np.sum(arr)),
        }

    prepare_values: list[float] = []
    simulation_values: list[float] = []
    objective_values: list[float] = []
    total_values: list[float] = []
    for outcome in outcomes:
        prepare_seconds = (
            float(outcome.request.actualize_seconds or 0.0)
            + float(outcome.launcher_prepare_seconds or 0.0)
            + float(outcome.runtime_patch_seconds or 0.0)
        )
        if prepare_seconds > 0.0:
            prepare_values.append(prepare_seconds)
        if outcome.simulation_seconds is not None:
            simulation_values.append(float(outcome.simulation_seconds))
        if outcome.objective_seconds is not None and float(outcome.objective_seconds) > 0.0:
            objective_values.append(float(outcome.objective_seconds))
        if outcome.total_seconds is not None:
            total_values.append(float(outcome.total_seconds))
    return {
        "count": int(len(outcomes)),
        "prepare_time_seconds": _series(prepare_values),
        "simulation_time_seconds": _series(simulation_values),
        "objective_time_seconds": _series(objective_values),
        "total_time_seconds": _series(total_values),
    }


def _split_target_path(target: str) -> tuple[str, ...]:
    """Split one dotted target path into validated segments."""
    parts = tuple(str(token).strip() for token in str(target).split("."))
    if not parts or any(not part for part in parts):
        raise ValueError(f"Invalid empty target path segment in '{target}'")
    return parts


def _lookup_nested_value(mapping: dict[str, Any], path: tuple[str, ...]) -> Any:
    """Resolve one dotted target path inside a nested mapping."""
    current: Any = mapping
    current_path: list[str] = []
    for key in path:
        current_path.append(key)
        if not isinstance(current, dict):
            raise KeyError(
                "Cannot descend into non-mapping value at "
                f"{'.'.join(current_path[:-1]) or '<root>'}"
            )
        if key not in current:
            raise KeyError(f"Missing target path '{'.'.join(current_path)}'")
        current = current[key]
    return current


def _assign_nested_value(mapping: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    """Assign one value inside a nested mapping, creating intermediate dicts."""
    current = mapping
    for key in path[:-1]:
        existing = current.get(key)
        if existing is None:
            current[key] = {}
            existing = current[key]
        elif not isinstance(existing, dict):
            raise ValueError(
                f"Cannot create nested path under non-mapping key '{key}'"
            )
        current = existing
    current[path[-1]] = value


def _parse_numeric_with_optional_suffix(value: Any) -> tuple[float, str | None] | None:
    """Return `(number, suffix)` for scalars or numeric-with-unit strings."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value), None
    if not isinstance(value, str):
        return None
    match = _NUMERIC_WITH_SUFFIX_RE.match(value)
    if match is None:
        return None
    number = float(match.group("number"))
    suffix = match.group("suffix")
    return number, (None if suffix is None else str(suffix).strip())


def _format_numeric_like(value: float, *, suffix: str | None) -> Any:
    """Format one numeric value, optionally preserving a unit suffix."""
    number_text = format(float(value), ".12g")
    if suffix is None or suffix == "":
        return float(number_text)
    return f"{number_text} {suffix}"


def _apply_parameter_override(
    *,
    base_value: Any,
    candidate_value: float,
    mode: str,
) -> Any:
    """Apply one calibrated candidate value onto the current target payload."""
    parsed = _parse_numeric_with_optional_suffix(base_value)
    if parsed is None:
        raise TypeError(
            "Path-based parameter injection currently supports only numeric "
            "targets or numeric strings with optional unit suffixes"
        )
    base_number, suffix = parsed
    candidate_number = float(candidate_value)

    if mode == "replace":
        return _format_numeric_like(candidate_number, suffix=suffix)
    if mode == "scale":
        return _format_numeric_like(base_number * candidate_number, suffix=suffix)
    raise ValueError(f"Unsupported parameter injection mode '{mode}'")


def _format_toml_scalar(value: Any) -> str:
    """Format one supported scalar as a TOML literal."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("TOML writer does not support NaN/Inf values")
        return format(value, ".12g")
    if isinstance(value, Path):
        return json.dumps(str(value), ensure_ascii=True)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_format_toml_scalar(item) for item in value) + "]"
    raise TypeError(f"Unsupported TOML scalar value: {type(value)!r}")


def _render_toml_mapping(mapping: dict[str, Any], *, prefix: tuple[str, ...] = ()) -> list[str]:
    """Render a nested mapping into a minimal TOML document."""
    lines: list[str] = []
    scalars: list[tuple[str, Any]] = []
    subtables: list[tuple[str, dict[str, Any]]] = []

    for key, value in mapping.items():
        if isinstance(value, dict):
            subtables.append((str(key), value))
        else:
            scalars.append((str(key), value))

    if prefix:
        lines.append(f"[{'.'.join(prefix)}]")
    for key, value in scalars:
        lines.append(f"{key} = {_format_toml_scalar(value)}")
    if prefix and (scalars or subtables):
        lines.append("")

    for key, value in subtables:
        lines.extend(_render_toml_mapping(value, prefix=(*prefix, key)))

    return lines


def _write_override_toml(path: Path, payload: dict[str, Any]) -> None:
    """Write one minimal override TOML payload to disk."""
    lines = _render_toml_mapping(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _resolve_optional_config_path(
    raw_value: object,
    *,
    simulation_config_path: Path,
) -> Path | None:
    """Resolve one optional path relative to the simulation config when needed."""
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    if text == "":
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = (simulation_config_path.parent / path).resolve()
    return path


def _resolve_mesh_input_bundle_dir(
    *,
    raw_simulation_toml: dict[str, Any],
    simulation_config_path: Path,
) -> Path | None:
    """Resolve an optional external mesh bundle declared in the simulation config."""
    section = raw_simulation_toml.get("mesh_input")
    if not isinstance(section, dict):
        return None
    return _resolve_optional_config_path(
        section.get("bundle_dir"),
        simulation_config_path=simulation_config_path,
    )


def _resolve_mesh_input_mesh_path(
    *,
    raw_simulation_toml: dict[str, Any],
    simulation_config_path: Path,
) -> Path | None:
    """Resolve an optional external mesh path declared in the simulation config."""
    section = raw_simulation_toml.get("mesh_input")
    if not isinstance(section, dict):
        return None
    return _resolve_optional_config_path(
        section.get("mesh_path"),
        simulation_config_path=simulation_config_path,
    )


def _resolve_summary_relative_path(
    raw_value: object,
    *,
    summary_path: Path,
) -> Path | None:
    """Resolve one optional path stored inside one mesh summary payload."""
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    if text == "":
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = (summary_path.parent / path).resolve()
    return path


def _load_mesh_summary_payload(summary_path: Path) -> dict[str, Any] | None:
    """Load one mesh summary JSON payload when it exists and is valid."""
    if not summary_path.is_file():
        return None
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _resolve_bundle_paths_from_mesh_summary(
    summary_path: Path,
) -> tuple[Path | None, Path | None]:
    """Resolve bundle and mesh paths declared inside one mesh summary JSON."""
    payload = _load_mesh_summary_payload(summary_path)
    if payload is None:
        return None, None
    return (
        _resolve_summary_relative_path(
            payload.get("output_exchange_bundle_dir"),
            summary_path=summary_path,
        ),
        _resolve_summary_relative_path(
            payload.get("output_mesh"),
            summary_path=summary_path,
        ),
    )


def _mesh_catchment_output_dir(
    *,
    raw_simulation_toml: dict[str, Any],
    simulation_workspace: WorkspaceConfig,
) -> Path | None:
    """Return the expected mesh-catchment final output directory."""
    section = raw_simulation_toml.get("mesh_catchment")
    if not isinstance(section, dict):
        return None
    output_layout = str(section.get("output_layout", "standard")).strip().lower()
    workspace_paths = WorkspacePathRegistry.from_config(simulation_workspace)
    if output_layout == "flat":
        return workspace_paths.project_root
    return workspace_paths.stable_folder / "mesh"


def _candidate_mesh_catchment_summary_paths(
    *,
    raw_simulation_toml: dict[str, Any],
    simulation_config_path: Path,
    simulation_workspace: WorkspaceConfig,
) -> tuple[tuple[str, Path], ...]:
    """Return configured and default mesh-catchment summary candidates."""
    section = raw_simulation_toml.get("mesh_catchment")
    if not isinstance(section, dict):
        return ()
    candidates: list[tuple[str, Path]] = []
    explicit_path = _resolve_optional_config_path(
        section.get("output_summary_json"),
        simulation_config_path=simulation_config_path,
    )
    if explicit_path is not None:
        candidates.append(("mesh_catchment_output_summary_json_bundle", explicit_path))
    output_dir = _mesh_catchment_output_dir(
        raw_simulation_toml=raw_simulation_toml,
        simulation_workspace=simulation_workspace,
    )
    if output_dir is not None:
        candidates.append(
            (
                "mesh_catchment_default_summary_bundle",
                output_dir / "mesh_catchment_summary.json",
            )
        )
    deduped: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for source, path in candidates:
        resolved = Path(path).resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append((source, resolved))
    return tuple(deduped)


def _candidate_mesh_catchment_mesh_paths(
    *,
    raw_simulation_toml: dict[str, Any],
    simulation_config_path: Path,
    simulation_workspace: WorkspaceConfig,
) -> tuple[tuple[str, Path], ...]:
    """Return configured and default mesh-catchment mesh candidates."""
    section = raw_simulation_toml.get("mesh_catchment")
    if not isinstance(section, dict):
        return ()
    candidates: list[tuple[str, Path]] = []
    explicit_path = _resolve_optional_config_path(
        section.get("output_mesh"),
        simulation_config_path=simulation_config_path,
    )
    if explicit_path is not None:
        candidates.append(("mesh_catchment_output_mesh_default_bundle", explicit_path))
    output_dir = _mesh_catchment_output_dir(
        raw_simulation_toml=raw_simulation_toml,
        simulation_workspace=simulation_workspace,
    )
    if output_dir is not None:
        candidates.append(
            (
                "mesh_catchment_default_mesh_default_bundle",
                output_dir / "mesh_catchment.msh",
            )
        )
    deduped: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for source, path in candidates:
        resolved = Path(path).resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append((source, resolved))
    return tuple(deduped)


def _discover_hydraulic_support_paths(
    *,
    raw_simulation_toml: dict[str, Any],
    simulation_config_path: Path,
    simulation_workspace: WorkspaceConfig,
) -> _ResolvedHydraulicSupportPaths:
    """Discover the best reusable mesh/bundle support already materialized on disk."""
    bundle_dir = _resolve_mesh_input_bundle_dir(
        raw_simulation_toml=raw_simulation_toml,
        simulation_config_path=simulation_config_path,
    )
    if bundle_dir is not None:
        return _ResolvedHydraulicSupportPaths(
            source="mesh_input_bundle_dir",
            bundle_dir=bundle_dir,
        )

    mesh_path = _resolve_mesh_input_mesh_path(
        raw_simulation_toml=raw_simulation_toml,
        simulation_config_path=simulation_config_path,
    )
    if mesh_path is not None:
        return _ResolvedHydraulicSupportPaths(
            source="mesh_input_mesh_path_default_bundle",
            bundle_dir=resolve_default_catchment_mesh_bundle_dir(mesh_path),
            mesh_path=mesh_path,
        )

    for source, summary_path in _candidate_mesh_catchment_summary_paths(
        raw_simulation_toml=raw_simulation_toml,
        simulation_config_path=simulation_config_path,
        simulation_workspace=simulation_workspace,
    ):
        bundle_dir, mesh_path_from_summary = _resolve_bundle_paths_from_mesh_summary(
            summary_path
        )
        if bundle_dir is None:
            continue
        return _ResolvedHydraulicSupportPaths(
            source=source,
            bundle_dir=bundle_dir,
            mesh_path=mesh_path_from_summary,
            mesh_summary_path=summary_path,
        )

    for source, candidate_mesh_path in _candidate_mesh_catchment_mesh_paths(
        raw_simulation_toml=raw_simulation_toml,
        simulation_config_path=simulation_config_path,
        simulation_workspace=simulation_workspace,
    ):
        bundle_dir = resolve_default_catchment_mesh_bundle_dir(candidate_mesh_path)
        if candidate_mesh_path.exists() or bundle_dir.exists():
            return _ResolvedHydraulicSupportPaths(
                source=source,
                bundle_dir=bundle_dir,
                mesh_path=candidate_mesh_path,
            )

    return _ResolvedHydraulicSupportPaths()



def _resolve_flow_property_config(
    *,
    raw_simulation_toml: dict[str, Any],
    property_name: str,
) -> dict[str, Any] | None:
    """Return the raw flow-parameter config block for one hydraulic property."""
    flow_section = raw_simulation_toml.get("flow")
    if not isinstance(flow_section, dict):
        return None
    param_section = flow_section.get("param")
    if not isinstance(param_section, dict):
        return None
    for alias in (property_name, property_name.lower(), property_name.upper()):
        payload = param_section.get(alias)
        if isinstance(payload, dict):
            return dict(payload)
    return None


def _parse_optional_numeric_value(raw_value: object) -> float | None:
    parsed = _parse_numeric_with_optional_suffix(raw_value)
    if parsed is None:
        return None
    value, _suffix = parsed
    return float(value)


def _build_property_array_from_config(
    *,
    raw_simulation_toml: dict[str, Any],
    property_name: str,
    n_cells: int,
    lithology_labels: tuple[str, ...] | None,
) -> tuple[float, ...] | None:
    """Infer one base property array from the reference flow configuration."""
    property_cfg = _resolve_flow_property_config(
        raw_simulation_toml=raw_simulation_toml,
        property_name=property_name,
    )
    if property_cfg is None:
        return None

    field_homogeneous = property_cfg.get("field_homogeneous")
    if isinstance(field_homogeneous, dict):
        scalar = _parse_optional_numeric_value(field_homogeneous.get("value"))
        if scalar is not None:
            return tuple(float(scalar) for _ in range(int(n_cells)))

    parsed_by_key = _parse_property_values_by_key(property_cfg)
    if parsed_by_key and lithology_labels is not None:
        if parsed_by_key and all(label in parsed_by_key for label in lithology_labels):
            return tuple(float(parsed_by_key[label]) for label in lithology_labels)

    return None


def _infer_target_scalar_base_arrays(
    *,
    raw_simulation_toml: dict[str, Any],
    cfg: ModelCalibrationConfig,
) -> dict[str, tuple[float, ...]]:
    """Infer scalar fallback arrays from the configured target paths."""
    base_arrays: dict[str, tuple[float, ...]] = {}
    for parameter_cfg in cfg.model_calibration.parameter:
        property_name = parameter_cfg.property
        if property_name is None or property_name in base_arrays:
            continue
        try:
            target_path = _resolve_target_path_alias(
                raw_simulation_toml,
                _split_target_path(parameter_cfg.target),
            )
            base_value = _lookup_nested_value(
                raw_simulation_toml,
                target_path,
            )
        except Exception:
            continue
        scalar = _parse_optional_numeric_value(base_value)
        if scalar is None:
            continue
        base_arrays[property_name] = (float(scalar),)
    return base_arrays


def prepare_hydraulic_property_support(
    *,
    simulation_config_path: Path,
    raw_simulation_toml: dict[str, Any],
    simulation_workspace: WorkspaceConfig,
    cfg: ModelCalibrationConfig,
) -> PreparedHydraulicPropertySupport:
    """Prepare reusable hydraulic support for calibration actualization."""
    calibrated_properties = {
        str(parameter_cfg.property).strip()
        for parameter_cfg in cfg.model_calibration.parameter
        if parameter_cfg.property is not None
    }
    runtime_prepared: PreparedHydraulicPropertySupport | None = None
    try:
        runtime_prepared = _prepare_runtime_hydraulic_property_support(
            simulation_config_path=simulation_config_path,
            raw_simulation_toml=raw_simulation_toml,
            solver_families=detect_solver_families(raw_simulation_toml),
            property_names=tuple(
                str(parameter_cfg.property).strip()
                for parameter_cfg in cfg.model_calibration.parameter
                if parameter_cfg.property is not None
            ),
        )
    except Exception:
        runtime_prepared = None

    if runtime_prepared is not None:
        n_cells = int(runtime_prepared.n_cells)
        lithology_labels = runtime_prepared.lithology_labels
        base_property_arrays = dict(runtime_prepared.base_property_arrays)
        zone_fractions_by_property = {
            str(name): {
                str(zone_key): tuple(float(value) for value in values)
                for zone_key, values in fractions.items()
            }
            for name, fractions in runtime_prepared.zone_fractions_by_property.items()
        }
        zone_fractions_by_key = dict(runtime_prepared.zone_fractions_by_key)
        base_property_values_by_key = {
            str(name): {str(key): float(value) for key, value in values.items()}
            for name, values in runtime_prepared.base_property_values_by_key.items()
        }
        support_id_by_property = {
            str(name): str(support_id)
            for name, support_id in runtime_prepared.support_id_by_property.items()
        }
        source = str(runtime_prepared.source)
        bundle_dir = runtime_prepared.mesh_bundle_dir
        mesh_path = runtime_prepared.mesh_path
        mesh_summary_path = runtime_prepared.mesh_summary_path
    else:
        resolved_paths = _discover_hydraulic_support_paths(
            raw_simulation_toml=raw_simulation_toml,
            simulation_config_path=simulation_config_path,
            simulation_workspace=simulation_workspace,
        )
        bundle_dir = resolved_paths.bundle_dir
        mesh_path = resolved_paths.mesh_path
        mesh_summary_path = resolved_paths.mesh_summary_path
        n_cells = 1
        lithology_labels: tuple[str, ...] | None = None
        base_property_arrays: dict[str, tuple[float, ...]] = {}
        zone_fractions_by_property: dict[str, dict[str, tuple[float, ...]]] = {}
        zone_fractions_by_key: dict[str, tuple[float, ...]] = {}
        base_property_values_by_key: dict[str, dict[str, float]] = {}
        support_id_by_property: dict[str, str] = {}
        source = "config_scalar"

        if bundle_dir is not None and bundle_dir.exists():
            try:
                bundle = load_catchment_mesh_bundle(bundle_dir)
            except Exception:
                bundle = None
            if bundle is not None:
                n_cells = int(bundle.n_cells)
                bundle_labels = tuple(
                    str(cell.geology_key or "").strip() for cell in bundle.cells
                )
                if any(bundle_labels):
                    lithology_labels = bundle_labels
                    source = f"{resolved_paths.source}_geology"
                else:
                    source = str(resolved_paths.source)

                conductivity_values = tuple(
                    float(cell.hydraulic_conductivity_m_s)
                    for cell in bundle.cells
                    if cell.hydraulic_conductivity_m_s is not None
                )
                if len(conductivity_values) == n_cells:
                    base_property_arrays["K"] = conductivity_values
                zone_fractions_by_key = _bundle_zone_fractions(
                    bundle,
                    n_cells=n_cells,
                )
                if zone_fractions_by_key:
                    for property_name in sorted(calibrated_properties):
                        zone_fractions_by_property[property_name] = dict(
                            zone_fractions_by_key
                        )

        for property_name in sorted(calibrated_properties):
            parsed_zone_values = _parse_property_values_by_key(
                _resolve_flow_property_config(
                    raw_simulation_toml=raw_simulation_toml,
                    property_name=property_name,
                )
            )
            if parsed_zone_values:
                base_property_values_by_key[str(property_name)] = parsed_zone_values
    for property_name in sorted(calibrated_properties):
        if property_name in base_property_arrays:
            continue
        config_array = _build_property_array_from_config(
            raw_simulation_toml=raw_simulation_toml,
            property_name=property_name,
            n_cells=n_cells,
            lithology_labels=lithology_labels,
        )
        if config_array is not None:
            base_property_arrays[property_name] = config_array

    fallback_base_arrays = _infer_target_scalar_base_arrays(
        raw_simulation_toml=raw_simulation_toml,
        cfg=cfg,
    )
    for property_name, values in fallback_base_arrays.items():
        base_property_arrays.setdefault(property_name, values)

    return PreparedHydraulicPropertySupport(
        n_cells=max(1, int(n_cells)),
        lithology_labels=lithology_labels,
        base_property_arrays=base_property_arrays,
        zone_fractions_by_property=zone_fractions_by_property,
        zone_fractions_by_key=zone_fractions_by_key,
        base_property_values_by_key=base_property_values_by_key,
        support_id_by_property=support_id_by_property,
        source=source,
        mesh_bundle_dir=bundle_dir,
        mesh_path=mesh_path,
        mesh_summary_path=mesh_summary_path,
    )


def _build_candidate_property_array_preview(
    *,
    session: PreparedCalibrationSession,
    cfg: ModelCalibrationConfig,
    params_named: dict[str, float],
) -> tuple[PropertyArraySet | None, dict[str, Any] | None, str | None]:
    """Build one vectorized property payload plus its diagnostic summary."""
    support = session.prepared_hydraulic_support
    try:
        property_set = build_property_array_set(
            cfg=cfg,
            params=params_named,
            base_property_arrays=(
                None if support is None else support.base_property_arrays
            ),
            lithology_labels=(
                None if support is None else support.lithology_labels
            ),
            zone_fractions_by_property=(
                None if support is None else support.zone_fractions_by_property
            ),
            zone_fractions_by_key=(
                None if support is None else support.zone_fractions_by_key
            ),
            base_property_values_by_key=(
                None if support is None else support.base_property_values_by_key
            ),
            default_cell_count=1 if support is None else int(support.n_cells),
        )
    except Exception as exc:
        return None, None, f"{type(exc).__name__}: {exc}"
    return property_set, property_set.to_summary(), None


def prepare_calibration_session(
    *,
    config_path: Path,
    cfg: ModelCalibrationConfig,
) -> PreparedCalibrationSession:
    """Resolve one prepared calibration session from launcher config plus target simulation."""
    t_start = time.perf_counter()
    raw_simulation_toml = load_toml_with_base_config(cfg.simulation_config_path)
    simulation_workspace = resolve_workspace_config(
        raw_simulation_toml,
        simulation_config_path=cfg.simulation_config_path,
    )
    core_settings = cfg.resolve_core_settings()
    calibration_id = cfg.model_calibration.calibration_id or config_path.stem
    calibration_root = simulation_workspace.calibration_folder / calibration_id
    solver_families = detect_solver_families(raw_simulation_toml)
    primary_solver = solver_families[0] if solver_families else None
    prepared_output_selectors = prepare_output_selectors(cfg)
    prepared_hydraulic_support = prepare_hydraulic_property_support(
        simulation_config_path=cfg.simulation_config_path,
        raw_simulation_toml=dict(raw_simulation_toml),
        simulation_workspace=simulation_workspace,
        cfg=cfg,
    )
    contract_signature = _session_contract_signature(
        cfg=cfg,
        raw_simulation_toml=dict(raw_simulation_toml),
        simulation_config_path=cfg.simulation_config_path,
        primary_solver=primary_solver,
        solver_families=solver_families,
        prepared_hydraulic_support=prepared_hydraulic_support,
    )
    prepare_time_seconds = float(time.perf_counter() - t_start)

    return PreparedCalibrationSession(
        config_path=config_path,
        simulation_config_path=cfg.simulation_config_path,
        raw_simulation_toml=dict(raw_simulation_toml),
        simulation_workspace=simulation_workspace,
        calibration_id=calibration_id,
        calibration_root=calibration_root,
        session_manifest_path=calibration_root / "session_manifest.json",
        iteration_history_path=calibration_root / "iteration_history.jsonl",
        candidates_root=calibration_root / "runtime_candidates",
        solver_families=solver_families,
        primary_solver=primary_solver,
        supported_v1_backend=primary_solver == "modflow6",
        core_settings=dict(core_settings),
        contract_signature=contract_signature,
        parameter_names=cfg.parameter_names,
        output_names=cfg.output_names,
        objective_block_names=cfg.objective_block_names,
        prepare_time_seconds=prepare_time_seconds,
        prepared_hydraulic_support=prepared_hydraulic_support,
        prepared_output_selectors=prepared_output_selectors,
    )


def initialize_calibration_session(
    session: PreparedCalibrationSession,
    *,
    cfg: ModelCalibrationConfig,
) -> dict[str, Any]:
    """Materialize one prepared session on disk and return the written manifest payload."""
    session.calibration_root.mkdir(parents=True, exist_ok=True)
    manifest = {
        **session.to_summary(),
        "disable_display": cfg.model_calibration.disable_display,
        "disable_postprocess": cfg.model_calibration.disable_postprocess,
        "rerun_best_with_outputs": cfg.model_calibration.rerun_best_with_outputs,
        "persist_model_distribution": (
            cfg.model_calibration.persist_model_distribution
        ),
        "rerun_model_distribution_with_outputs": (
            cfg.model_calibration.rerun_model_distribution_with_outputs
        ),
        "model_distribution_max_reruns": (
            cfg.model_calibration.model_distribution_max_reruns
        ),
        "model_distribution_rerun_selection": (
            cfg.model_calibration.model_distribution_rerun_selection
        ),
        "persist_iteration_history": cfg.model_calibration.persist_iteration_history,
        "persist_iteration_detail_level": (
            cfg.model_calibration.persist_iteration_detail_level
        ),
        "persist_calibration_report": (
            cfg.model_calibration.persist_calibration_report
        ),
        "resume_existing_session": cfg.model_calibration.resume_existing_session,
        "reuse_persisted_iterations": (
            cfg.model_calibration.reuse_persisted_iterations
        ),
        "objective_mapping_enabled": (
            cfg.model_calibration.objective_mapping.enabled
        ),
        "objective_metric": cfg.calibration.objective_metric,
        "objective_transform": cfg.objective.transform,
        "session_contract_signature": session.contract_signature,
        "persisted_iteration_reuse_allowed": True,
        "iteration_count": 0,
    }
    if (
        cfg.model_calibration.resume_existing_session
        and session.session_manifest_path.is_file()
    ):
        existing_manifest = json.loads(
            session.session_manifest_path.read_text(encoding="utf-8")
        )
        existing_signature = existing_manifest.get("session_contract_signature")
        if (
            existing_signature is not None
            and str(existing_signature) != str(session.contract_signature)
        ):
            raise ValueError(
                "Cannot resume calibration session because the persisted "
                "session contract does not match the current calibration "
                "configuration. Use a new calibration_id or disable "
                "resume_existing_session."
        )
        resumed_iteration_count = int(existing_manifest.get("iteration_count", 0))
        reuse_allowed = bool(existing_manifest.get("persisted_iteration_reuse_allowed", True))
        if existing_signature is None and resumed_iteration_count > 0:
            reuse_allowed = False
        manifest = {
            **existing_manifest,
            **manifest,
            "iteration_count": resumed_iteration_count,
            "status": "resumed_prepared" if resumed_iteration_count > 0 else "prepared",
            "resumed_iteration_count": resumed_iteration_count,
            "persisted_iteration_reuse_allowed": reuse_allowed,
        }
    session.session_manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    if cfg.model_calibration.persist_iteration_history:
        if (
            not cfg.model_calibration.resume_existing_session
            or not session.iteration_history_path.exists()
        ):
            session.iteration_history_path.write_text("", encoding="utf-8")
    return manifest


def append_iteration_record(
    *,
    history_path: Path,
    record: IterationRecord,
    detail_level: str = "minimal",
) -> None:
    """Append one minimal iteration record to the session JSONL history."""
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                record.to_mapping(detail_level=detail_level),
                ensure_ascii=True,
            )
            + "\n"
        )


def update_session_manifest(
    *,
    manifest_path: Path,
    record: IterationRecord | None = None,
) -> dict[str, Any]:
    """Update the session manifest after one iteration append."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["iteration_count"] = int(manifest.get("iteration_count", 0)) + 1
    if record is not None:
        manifest["last_iteration_id"] = record.iteration_id
        manifest["last_iteration_status"] = record.status
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def persist_iteration_record(
    *,
    session: PreparedCalibrationSession,
    record: IterationRecord,
    detail_level: str = "minimal",
) -> dict[str, Any]:
    """Append one iteration record and refresh the session manifest counter."""
    append_iteration_record(
        history_path=session.iteration_history_path,
        record=record,
        detail_level=detail_level,
    )
    return update_session_manifest(manifest_path=session.session_manifest_path, record=record)


def finalize_calibration_session(
    *,
    session: PreparedCalibrationSession,
    result: Any,
    evaluator: ModelCalibrationObjectiveEvaluator,
    best_rerun_outcome: CandidateRunOutcome | None = None,
    model_distribution_payload: dict[str, Any] | None = None,
    model_distribution_rerun_summary: dict[str, Any] | None = None,
    objective_mapping_summary: dict[str, Any] | None = None,
    persist_distribution: bool = True,
) -> dict[str, Any]:
    """Persist the final calibration result and update the session manifest."""
    result_payload = serialize_calibration_result(result)
    result_metadata = dict(result_payload.get("metadata", {}))
    result_metadata["session_prepare_time_seconds"] = session.prepare_time_seconds
    result_metadata["candidate_timing_summary"] = _summarize_candidate_run_timings(
        evaluator.outcomes
    )
    result_payload["metadata"] = result_metadata
    result_path = session.calibration_root / "calibration_result.json"
    result_path.write_text(
        json.dumps(result_payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    distribution_summary = None
    if persist_distribution:
        distribution_summary = persist_model_distribution(
            session=session,
            result=result,
            evaluator=evaluator,
            payload=model_distribution_payload,
        )

    manifest = json.loads(session.session_manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "status": "calibrated",
            "result_path": str(result_path),
            "method": result_payload["method"],
            "cost_best": result_payload["cost_best"],
            "score_best": result_payload["score_best"],
            "params_best": result_payload["params_best"],
            "n_evaluations": result_payload["n_evaluations"],
            "candidate_run_count": int(evaluator.candidate_run_count),
            "objective_cache_hit_count": int(evaluator.cache_hit_count),
            "restored_evaluation_count": int(evaluator.restored_evaluation_count),
            "session_prepare_time_seconds": session.prepare_time_seconds,
            "candidate_timing_summary": _summarize_candidate_run_timings(
                evaluator.outcomes
            ),
            "model_distribution": distribution_summary,
            "model_distribution_rerun": model_distribution_rerun_summary,
            "objective_mapping": objective_mapping_summary,
        }
    )
    if best_rerun_outcome is not None:
        manifest["best_rerun"] = {
            "status": best_rerun_outcome.status,
            "candidate_run_id": best_rerun_outcome.request.candidate_run_id,
            "candidate_config_path": str(
                best_rerun_outcome.request.candidate_config_path
            ),
            "error_type": best_rerun_outcome.error_type,
            "error_message": best_rerun_outcome.error_message,
        }
    session.session_manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def select_candidate_outputs(
    *,
    cfg: ModelCalibrationConfig,
    run_state: Any,
    session: PreparedCalibrationSession | None = None,
) -> dict[str, tuple[float, ...]]:
    """Select configured simulated observables from one run-state payload."""
    if session is not None and session.prepared_output_selectors:
        return select_candidate_outputs_from_selectors(
            selectors=session.prepared_output_selectors,
            run_state=run_state,
        )
    return _select_candidate_outputs_from_bundle(cfg=cfg, run_state=run_state)


def _objective_has_observations(cfg: ModelCalibrationConfig) -> bool:
    """Return True when at least one configured output carries observed values."""
    return any(
        output_cfg.observed_values is not None
        for output_cfg in cfg.model_calibration.output
    )


def evaluate_candidate_objective(
    *,
    cfg: ModelCalibrationConfig,
    run_state: Any,
    session: PreparedCalibrationSession | None = None,
) -> CompositeObjectiveEvaluation:
    """Evaluate configured composite objective from one candidate run-state."""
    selected = select_candidate_outputs(cfg=cfg, run_state=run_state, session=session)
    outputs_by_name = {
        output_cfg.name: output_cfg for output_cfg in cfg.model_calibration.output
    }

    blocks: list[CompositeObjectiveBlock] = []
    for block_cfg in cfg.model_calibration.objective_block:
        if block_cfg.metric == "direct_cost":
            raise NotImplementedError(
                "direct_cost objective blocks are reserved for future map comparisons"
            )

        observed_parts: list[np.ndarray] = []
        for output_name in block_cfg.uses_outputs:
            output_cfg = outputs_by_name[output_name]
            if output_cfg.observed_values is None:
                raise ValueError(
                    f"Output '{output_name}' used by block '{block_cfg.name}' "
                    "does not define observed_values"
                )
            observed_parts.append(
                np.asarray(output_cfg.observed_values, dtype=float).ravel()
            )
        observed = np.concatenate(observed_parts)

        def _selector(
            payload: dict[str, tuple[float, ...]],
            names=tuple(block_cfg.uses_outputs),
        ):
            return np.concatenate(
                [np.asarray(payload[name], dtype=float).ravel() for name in names]
            )

        blocks.append(
            CompositeObjectiveBlock(
                name=block_cfg.name,
                observed=observed,
                selector=_selector,
                metric=block_cfg.metric,
                weight=block_cfg.weight,
                normalize_cost=block_cfg.normalize_cost,
                metadata={"uses_outputs": tuple(block_cfg.uses_outputs)},
            )
        )

    objective = CompositeObjective(
        simulator=lambda _params: selected,
        blocks=tuple(blocks),
    )
    return objective.evaluate({})


def actualize_candidate(
    *,
    session: PreparedCalibrationSession,
    cfg: ModelCalibrationConfig,
    params: dict[str, float] | tuple[float, ...] | list[float],
    iteration_index: int | None = None,
    candidate_label: str | None = None,
    disable_display: bool | None = None,
    disable_postprocess: bool | None = None,
) -> CandidateRunRequest:
    """Materialize one candidate override TOML from calibrated parameters."""
    parameter_set = session.core_settings["parameter_set"]
    params_vector = tuple(float(value) for value in parameter_set.vector_from(params))
    params_named = {
        str(name): float(value)
        for name, value in parameter_set.mapping_from(params_vector).items()
    }
    if candidate_label is not None:
        iteration_id = _sanitize_candidate_label(candidate_label)
    elif iteration_index is not None:
        iteration_id = f"iter_{int(iteration_index):04d}"
    else:
        raise ValueError("actualize_candidate requires iteration_index or candidate_label")
    candidate_run_id = f"{session.calibration_id}__{iteration_id}"
    candidate_root = (
        session.candidates_root or session.calibration_root / "runtime_candidates"
    ) / iteration_id
    candidate_config_path = candidate_root / "candidate_override.toml"

    override_payload: dict[str, Any] = {
        "base_config": str(session.simulation_config_path),
        "simulation": {"run_id": candidate_run_id},
    }
    if disable_display is None:
        disable_display = cfg.model_calibration.disable_display
    if disable_postprocess is None:
        disable_postprocess = cfg.model_calibration.disable_postprocess

    if disable_display:
        override_payload["display"] = {
            "enabled": False,
            "show": False,
            "save": False,
        }
    if disable_postprocess:
        override_payload["postprocess"] = {
            "enabled": False,
        }

    for parameter_cfg in cfg.model_calibration.parameter:
        target_path = _resolve_target_path_alias(
            session.raw_simulation_toml,
            _split_target_path(parameter_cfg.target),
        )
        base_value = _lookup_nested_value(session.raw_simulation_toml, target_path)
        resolved_value = _apply_parameter_override(
            base_value=base_value,
            candidate_value=params_named[parameter_cfg.name],
            mode=parameter_cfg.mode,
        )
        _assign_nested_value(override_payload, target_path, resolved_value)

    _write_override_toml(candidate_config_path, override_payload)
    property_array_set, property_array_summary, property_array_error = _build_candidate_property_array_preview(
        session=session,
        cfg=cfg,
        params_named=params_named,
    )
    return CandidateRunRequest(
        session=session,
        iteration_id=iteration_id,
        candidate_run_id=candidate_run_id,
        candidate_root=candidate_root,
        candidate_config_path=candidate_config_path,
        params_vector=params_vector,
        params_named=params_named,
        override_payload=override_payload,
        property_array_set=property_array_set,
        property_array_summary=property_array_summary,
        property_array_error=property_array_error,
    )


def execute_best_candidate_rerun(
    *,
    session: PreparedCalibrationSession,
    cfg: ModelCalibrationConfig,
    result: Any,
    launcher_factory: Any,
) -> CandidateRunOutcome:
    """Rerun the best candidate without calibration-time output suppression."""
    params = getattr(result, "params_best", None)
    if params is None:
        params = getattr(result, "x_best")
    request = actualize_candidate(
        session=session,
        cfg=cfg,
        params=params,
        candidate_label="best",
        disable_display=False,
        disable_postprocess=False,
    )
    return execute_candidate_run(
        request=request,
        launcher_factory=launcher_factory,
        cfg=None,
    )


def _launcher_supports_runtime_direct(launcher_factory: Any) -> bool:
    """Return True when one launcher factory can run from the base config path."""
    if bool(getattr(launcher_factory, "model_calibration_runtime_direct", False)):
        return True
    try:
        from launchers import HydroModPyLauncher

        return launcher_factory is HydroModPyLauncher
    except Exception:
        return False


def _launcher_supports_runtime_reuse(launcher_factory: Any) -> bool:
    """Return True when one launcher factory supports prepared-runtime reuse."""
    if bool(getattr(launcher_factory, "model_calibration_runtime_reusable", False)):
        return True
    try:
        from launchers import HydroModPyLauncher

        return launcher_factory is HydroModPyLauncher
    except Exception:
        return False


def _launcher_cache_key(launcher_factory: Any) -> str:
    """Return one stable session-local cache key for a launcher factory."""
    module_name = str(getattr(launcher_factory, "__module__", ""))
    qualname = str(getattr(launcher_factory, "__qualname__", ""))
    if module_name or qualname:
        return f"{module_name}:{qualname}"
    return repr(launcher_factory)


def _assign_runtime_override(raw_toml: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    """Best-effort assignment into a raw TOML payload used for snapshots only."""
    try:
        _assign_nested_value(raw_toml, path, value)
    except Exception:
        return


def _capture_runtime_direct_launcher_baseline(launcher: Any) -> dict[str, Any]:
    """Capture mutable launcher fields that must be restored before each candidate."""
    cfg = getattr(launcher, "cfg", None)
    display_cfg = None if cfg is None else getattr(cfg, "display", None)
    postprocess_cfg = None if cfg is None else getattr(cfg, "postprocess", None)
    simulation_cfg = None if cfg is None else getattr(cfg, "simulation", None)
    raw_toml = getattr(getattr(launcher, "run_state", None), "raw_toml", None)
    return {
        "simulation_run_id": None if simulation_cfg is None else getattr(simulation_cfg, "run_id", None),
        "display": {
            "enabled": None if display_cfg is None else getattr(display_cfg, "enabled", None),
            "show": None if display_cfg is None else getattr(display_cfg, "show", None),
            "save": None if display_cfg is None else getattr(display_cfg, "save", None),
        },
        "postprocess_enabled": (
            None if postprocess_cfg is None else getattr(postprocess_cfg, "enabled", None)
        ),
        "raw_toml": copy.deepcopy(raw_toml) if isinstance(raw_toml, dict) else None,
    }


def _restore_runtime_direct_launcher_baseline(launcher: Any) -> None:
    """Restore one cached launcher to its pre-candidate baseline."""
    baseline = getattr(launcher, "_model_calibration_runtime_baseline", None)
    if not isinstance(baseline, dict):
        baseline = _capture_runtime_direct_launcher_baseline(launcher)
        setattr(launcher, "_model_calibration_runtime_baseline", baseline)

    cfg = getattr(launcher, "cfg", None)
    run_state = getattr(launcher, "run_state", None)
    raw_toml = getattr(run_state, "raw_toml", None)
    setup_state = getattr(run_state, "setup", None)
    if cfg is not None:
        simulation_cfg = getattr(cfg, "simulation", None)
        if simulation_cfg is not None:
            try:
                simulation_cfg.run_id = baseline.get("simulation_run_id")
            except Exception:
                pass
        display_cfg = getattr(cfg, "display", None)
        display_baseline = baseline.get("display", {})
        if display_cfg is not None and isinstance(display_baseline, dict):
            for attr_name in ("enabled", "show", "save"):
                if attr_name not in display_baseline:
                    continue
                try:
                    setattr(display_cfg, attr_name, display_baseline.get(attr_name))
                except Exception:
                    pass
        postprocess_cfg = getattr(cfg, "postprocess", None)
        if postprocess_cfg is not None:
            try:
                postprocess_cfg.enabled = baseline.get("postprocess_enabled")
            except Exception:
                pass
        postprocess_runner = getattr(launcher, "postprocess_runner", None)
        if postprocess_runner is not None and postprocess_cfg is not None:
            try:
                postprocess_runner.config = postprocess_cfg
            except Exception:
                pass
    if isinstance(raw_toml, dict) and isinstance(baseline.get("raw_toml"), dict):
        raw_toml.clear()
        raw_toml.update(copy.deepcopy(baseline["raw_toml"]))
    if setup_state is not None:
        try:
            setup_state.flow_runtime_overrides = None
        except Exception:
            pass


def _get_or_create_runtime_reusable_launcher(
    *,
    request: CandidateRunRequest,
    launcher_factory: Any,
) -> Any:
    """Return one reusable launcher instance cached on the calibration session."""
    cache_key = _launcher_cache_key(launcher_factory)
    launcher = request.session.runtime_launcher_cache.get(cache_key)
    if launcher is None:
        launcher = launcher_factory(request.session.simulation_config_path)
        prepare_runtime = getattr(launcher, "prepare_runtime", None)
        if callable(prepare_runtime):
            prepare_runtime()
        setattr(
            launcher,
            "_model_calibration_runtime_baseline",
            _capture_runtime_direct_launcher_baseline(launcher),
        )
        request.session.runtime_launcher_cache[cache_key] = launcher
        return launcher
    _restore_runtime_direct_launcher_baseline(launcher)
    return launcher


def _prepare_runtime_direct_launcher(
    *,
    launcher: Any,
    request: CandidateRunRequest,
) -> None:
    """Patch one launcher instance so it can execute a candidate without overlay TOML."""
    _restore_runtime_direct_launcher_baseline(launcher)
    cfg = getattr(launcher, "cfg", None)
    run_state = getattr(launcher, "run_state", None)
    setup_state = getattr(run_state, "setup", None)
    raw_toml = getattr(run_state, "raw_toml", None)
    if cfg is not None:
        simulation_cfg = getattr(cfg, "simulation", None)
        if simulation_cfg is not None:
            try:
                simulation_cfg.run_id = request.candidate_run_id
            except Exception:
                pass
        if "display" in request.override_payload:
            display_cfg = getattr(cfg, "display", None)
            if display_cfg is not None:
                for attr_name, default_value in (
                    ("enabled", False),
                    ("show", False),
                    ("save", False),
                ):
                    try:
                        setattr(display_cfg, attr_name, default_value)
                    except Exception:
                        pass
        if "postprocess" in request.override_payload:
            postprocess_cfg = getattr(cfg, "postprocess", None)
            if postprocess_cfg is not None:
                try:
                    postprocess_cfg.enabled = False
                except Exception:
                    pass
            postprocess_runner = getattr(launcher, "postprocess_runner", None)
            if postprocess_runner is not None and postprocess_cfg is not None:
                try:
                    postprocess_runner.config = postprocess_cfg
                except Exception:
                    pass
    if setup_state is not None:
        try:
            setup_state.run_id = request.candidate_run_id
        except Exception:
            pass
    if isinstance(raw_toml, dict):
        _assign_runtime_override(
            raw_toml,
            ("simulation", "run_id"),
            request.candidate_run_id,
        )
        if "display" in request.override_payload:
            _assign_runtime_override(raw_toml, ("display", "enabled"), False)
            _assign_runtime_override(raw_toml, ("display", "show"), False)
            _assign_runtime_override(raw_toml, ("display", "save"), False)
        if "postprocess" in request.override_payload:
            _assign_runtime_override(raw_toml, ("postprocess", "enabled"), False)


def execute_candidate_run(
    *,
    request: CandidateRunRequest,
    launcher_factory: Any,
    cfg: ModelCalibrationConfig | None = None,
) -> CandidateRunOutcome:
    """Execute one candidate simulation via a launcher factory."""
    overall_start = time.perf_counter()
    launcher_prepare_seconds = 0.0
    runtime_patch_seconds = 0.0
    simulation_seconds = 0.0
    objective_seconds = 0.0
    try:
        launcher = None
        launcher_path = request.candidate_config_path
        runtime_direct = _launcher_supports_runtime_direct(launcher_factory)
        runtime_reusable = runtime_direct and _launcher_supports_runtime_reuse(
            launcher_factory
        )
        launcher_prepare_start = time.perf_counter()
        if runtime_direct:
            launcher_path = request.session.simulation_config_path
            if runtime_reusable:
                launcher = _get_or_create_runtime_reusable_launcher(
                    request=request,
                    launcher_factory=launcher_factory,
                )
            else:
                launcher = launcher_factory(launcher_path)
        if launcher is None:
            launcher = launcher_factory(launcher_path)
        launcher_prepare_seconds = float(time.perf_counter() - launcher_prepare_start)
        if runtime_direct:
            runtime_patch_start = time.perf_counter()
            _prepare_runtime_direct_launcher(
                launcher=launcher,
                request=request,
            )
            runtime_patch_seconds = float(time.perf_counter() - runtime_patch_start)
        setup_state = getattr(getattr(launcher, "run_state", None), "setup", None)
        if setup_state is not None:
            if request.property_array_set is not None:
                setup_state.flow_runtime_overrides = {
                    "source": "model_calibration",
                    "candidate_run_id": request.candidate_run_id,
                    "iteration_id": request.iteration_id,
                    "properties": {
                        property_name: np.asarray(array.values, dtype=float).copy()
                        for property_name, array in request.property_array_set.arrays.items()
                    },
                }
            else:
                setup_state.flow_runtime_overrides = None
        run_callable = None
        if runtime_reusable:
            run_callable = getattr(launcher, "run_prepared", None)
        if not callable(run_callable):
            run_callable = launcher.run
        simulation_start = time.perf_counter()
        run_state = run_callable()
        simulation_seconds = float(time.perf_counter() - simulation_start)
    except Exception as exc:
        return CandidateRunOutcome(
            request=request,
            status="solver_run_failed",
            run_state=None,
            error_type=type(exc).__name__,
            error_message=f"{type(exc).__name__}: {exc}",
            launcher_prepare_seconds=launcher_prepare_seconds,
            runtime_patch_seconds=runtime_patch_seconds,
            simulation_seconds=simulation_seconds,
            objective_seconds=objective_seconds,
            total_seconds=float(time.perf_counter() - overall_start),
        )

    if cfg is not None and _objective_has_observations(cfg):
        try:
            objective_start = time.perf_counter()
            objective_evaluation = evaluate_candidate_objective(
                cfg=cfg,
                run_state=run_state,
                session=request.session,
            )
            objective_seconds = float(time.perf_counter() - objective_start)
        except Exception as exc:
            return CandidateRunOutcome(
                request=request,
                status="objective_evaluation_failed",
                run_state=run_state,
                objective_evaluation=None,
                error_type=type(exc).__name__,
                error_message=f"{type(exc).__name__}: {exc}",
                launcher_prepare_seconds=launcher_prepare_seconds,
                runtime_patch_seconds=runtime_patch_seconds,
                simulation_seconds=simulation_seconds,
                objective_seconds=objective_seconds,
                total_seconds=float(time.perf_counter() - overall_start),
            )
        return CandidateRunOutcome(
            request=request,
            status="objective_evaluated",
            run_state=run_state,
            objective_evaluation=objective_evaluation,
            error_type=None,
            error_message=None,
            launcher_prepare_seconds=launcher_prepare_seconds,
            runtime_patch_seconds=runtime_patch_seconds,
            simulation_seconds=simulation_seconds,
            objective_seconds=objective_seconds,
            total_seconds=float(time.perf_counter() - overall_start),
        )
    return CandidateRunOutcome(
        request=request,
        status="solver_run_succeeded",
        run_state=run_state,
        objective_evaluation=None,
        error_type=None,
        error_message=None,
        launcher_prepare_seconds=launcher_prepare_seconds,
        runtime_patch_seconds=runtime_patch_seconds,
        simulation_seconds=simulation_seconds,
        objective_seconds=objective_seconds,
        total_seconds=float(time.perf_counter() - overall_start),
    )


__all__ = (
    "actualize_candidate",
    "build_model_distribution_payload",
    "CandidateRunOutcome",
    "CandidateRunRequest",
    "IterationRecord",
    "PreparedCalibrationSession",
    "append_iteration_record",
    "detect_solver_families",
    "execute_best_candidate_rerun",
    "execute_candidate_run",
    "execute_model_distribution_reruns",
    "evaluate_candidate_objective",
    "finalize_calibration_session",
    "initialize_calibration_session",
    "ModelCalibrationObjectiveEvaluator",
    "persist_iteration_record",
    "persist_model_distribution",
    "prepare_calibration_session",
    "resolve_workspace_config",
    "serialize_calibration_result",
    "select_candidate_outputs",
    "select_model_distribution_samples",
    "update_session_manifest",
    "validate_objective_ready_for_calibration",
)
