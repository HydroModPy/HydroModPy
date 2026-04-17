"""Shared model-calibration runtime support contracts and helpers.

This module hosts the pure helpers shared between the process-simulation
launcher and the model-calibration runtime.  Keeping these helpers here
lets calibration consume one public contract instead of reaching into
launcher-private methods.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.core.workspace.path_registry import WorkspacePathRegistry
from hydromodpy.solver.utils.mesh.gmsh_grid.catchment_mesh_bundle import (
    resolve_default_catchment_mesh_bundle_dir,
)

_NUMERIC_WITH_SUFFIX_RE = re.compile(
    r"^\s*(?P<number>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(?P<suffix>.*\S)?\s*$"
)


class ModelCalibrationRuntimeSupportUnavailable(RuntimeError):
    """Raised when runtime hydraulic support cannot be prepared."""


@dataclass(frozen=True, slots=True)
class RuntimeHydraulicPropertySupport:
    """Prepared hydraulic support returned by the process-simulation launcher."""

    n_cells: int
    source: str
    lithology_labels: tuple[str, ...] | None = None
    base_property_arrays: dict[str, tuple[float, ...]] = field(default_factory=dict)
    zone_fractions_by_property: dict[str, dict[str, tuple[float, ...]]] = field(
        default_factory=dict
    )
    zone_fractions_by_key: dict[str, tuple[float, ...]] = field(default_factory=dict)
    base_property_values_by_key: dict[str, dict[str, float]] = field(
        default_factory=dict
    )
    support_id_by_property: dict[str, str] = field(default_factory=dict)
    mesh_bundle_dir: Path | None = None
    mesh_path: Path | None = None
    mesh_summary_path: Path | None = None


@dataclass(frozen=True, slots=True)
class ResolvedRuntimeMeshPaths:
    """Resolved file-system anchors used to discover mesh-backed support."""

    source: str = "config_scalar"
    bundle_dir: Path | None = None
    mesh_path: Path | None = None
    mesh_summary_path: Path | None = None


def select_runtime_preparation_flow_solver(
    *,
    solver_families: tuple[str, ...],
) -> str | None:
    """Choose the preferred flow solver used to prepare runtime support."""
    normalized = [
        str(name).strip().lower() for name in solver_families if str(name).strip()
    ]
    for candidate in ("modflow6", "modflownwt"):
        if candidate in normalized:
            return candidate
    return None


def parse_numeric_with_optional_suffix(
    value: Any,
) -> tuple[float, str | None] | None:
    """Parse scalar-like payloads that may carry a textual unit suffix."""
    if value is None:
        return None
    match = _NUMERIC_WITH_SUFFIX_RE.match(str(value))
    if match is None:
        return None
    suffix = match.group("suffix")
    return float(match.group("number")), (None if suffix is None else str(suffix))


def parse_optional_numeric_value(raw_value: Any) -> float | None:
    """Return the numeric part of a scalar payload when it can be parsed."""
    parsed = parse_numeric_with_optional_suffix(raw_value)
    if parsed is None:
        return None
    value, _suffix = parsed
    return float(value)


def surface_property_vector(values: object, *, solver_mesh: object) -> tuple[float, ...]:
    """Normalize one surface diagnostic payload to one 1D cell support."""
    arr = np.asarray(values, dtype=float)
    flattened = np.asarray(
        solver_mesh.flatten_from_grid(arr),
        dtype=float,
    ).reshape(-1)
    return tuple(float(value) for value in flattened)


def setup_mesh_paths_from_runtime(
    setup_state: object,
) -> tuple[Path | None, Path | None, Path | None]:
    """Resolve bundle, mesh and summary paths from one prepared runtime state."""
    bundle_dir: Path | None = None
    mesh_path: Path | None = None
    mesh_summary_path: Path | None = None

    mesh_summary = getattr(setup_state, "mesh_summary", None)
    if isinstance(mesh_summary, dict):
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


def resolve_flow_property_config(
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


def parse_property_values_by_key(
    property_cfg: dict[str, Any] | None,
) -> dict[str, float]:
    """Parse one heterogeneous values-by-key mapping from a raw flow block."""
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
            numeric = parse_optional_numeric_value(raw_value)
            if numeric is None:
                continue
            parsed[str(key).strip()] = float(numeric)
        if parsed:
            return parsed
    return {}


def parse_property_support_id(property_cfg: dict[str, Any] | None) -> str | None:
    """Return the spatial-support id declared for one heterogeneous property."""
    if property_cfg is None:
        return None
    field_heterogeneous = property_cfg.get("field_heterogeneous")
    if not isinstance(field_heterogeneous, dict):
        return None
    support_id = str(field_heterogeneous.get("field_spatial_id", "")).strip()
    return None if support_id == "" else support_id


def bundle_zone_fractions(
    bundle: object,
    *,
    n_cells: int,
) -> dict[str, tuple[float, ...]]:
    """Return per-zone fractions from one bundle, with one-hot label fallback."""
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

    labels = tuple(
        str(getattr(cell, "geology_key", "") or "").strip()
        for cell in getattr(bundle, "cells", ())
    )
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


def labels_from_zone_fractions(
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


def resolve_optional_config_path(
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


def resolve_mesh_input_bundle_dir(
    *,
    raw_simulation_toml: dict[str, Any],
    simulation_config_path: Path,
) -> Path | None:
    """Resolve an optional external mesh bundle declared in the simulation config."""
    section = raw_simulation_toml.get("mesh_input")
    if not isinstance(section, dict):
        return None
    return resolve_optional_config_path(
        section.get("bundle_dir"),
        simulation_config_path=simulation_config_path,
    )


def resolve_mesh_input_mesh_path(
    *,
    raw_simulation_toml: dict[str, Any],
    simulation_config_path: Path,
) -> Path | None:
    """Resolve an optional external mesh path declared in the simulation config."""
    section = raw_simulation_toml.get("mesh_input")
    if not isinstance(section, dict):
        return None
    return resolve_optional_config_path(
        section.get("mesh_path"),
        simulation_config_path=simulation_config_path,
    )


def resolve_summary_relative_path(
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


def load_mesh_summary_payload(summary_path: Path) -> dict[str, Any] | None:
    """Load one mesh summary JSON payload when it exists and is valid."""
    if not summary_path.is_file():
        return None
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def resolve_bundle_paths_from_mesh_summary(
    summary_path: Path,
) -> tuple[Path | None, Path | None]:
    """Resolve bundle and mesh paths declared inside one mesh summary JSON."""
    payload = load_mesh_summary_payload(summary_path)
    if payload is None:
        return None, None
    return (
        resolve_summary_relative_path(
            payload.get("output_exchange_bundle_dir"),
            summary_path=summary_path,
        ),
        resolve_summary_relative_path(
            payload.get("output_mesh"),
            summary_path=summary_path,
        ),
    )


def mesh_catchment_output_dir(
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


def candidate_mesh_catchment_summary_paths(
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
    explicit_path = resolve_optional_config_path(
        section.get("output_summary_json"),
        simulation_config_path=simulation_config_path,
    )
    if explicit_path is not None:
        candidates.append(("mesh_catchment_output_summary_json_bundle", explicit_path))
    output_dir = mesh_catchment_output_dir(
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


def candidate_mesh_catchment_mesh_paths(
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
    explicit_path = resolve_optional_config_path(
        section.get("output_mesh"),
        simulation_config_path=simulation_config_path,
    )
    if explicit_path is not None:
        candidates.append(("mesh_catchment_output_mesh_default_bundle", explicit_path))
    output_dir = mesh_catchment_output_dir(
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


def discover_hydraulic_support_paths(
    *,
    raw_simulation_toml: dict[str, Any],
    simulation_config_path: Path,
    simulation_workspace: WorkspaceConfig,
) -> ResolvedRuntimeMeshPaths:
    """Discover the best reusable mesh/bundle support already materialized on disk."""
    bundle_dir = resolve_mesh_input_bundle_dir(
        raw_simulation_toml=raw_simulation_toml,
        simulation_config_path=simulation_config_path,
    )
    if bundle_dir is not None:
        return ResolvedRuntimeMeshPaths(
            source="mesh_input_bundle_dir",
            bundle_dir=bundle_dir,
        )

    mesh_path = resolve_mesh_input_mesh_path(
        raw_simulation_toml=raw_simulation_toml,
        simulation_config_path=simulation_config_path,
    )
    if mesh_path is not None:
        return ResolvedRuntimeMeshPaths(
            source="mesh_input_mesh_path_default_bundle",
            bundle_dir=resolve_default_catchment_mesh_bundle_dir(mesh_path),
            mesh_path=mesh_path,
        )

    for source, summary_path in candidate_mesh_catchment_summary_paths(
        raw_simulation_toml=raw_simulation_toml,
        simulation_config_path=simulation_config_path,
        simulation_workspace=simulation_workspace,
    ):
        bundle_dir, mesh_path_from_summary = resolve_bundle_paths_from_mesh_summary(
            summary_path
        )
        if bundle_dir is None:
            continue
        return ResolvedRuntimeMeshPaths(
            source=source,
            bundle_dir=bundle_dir,
            mesh_path=mesh_path_from_summary,
            mesh_summary_path=summary_path,
        )

    for source, candidate_mesh_path in candidate_mesh_catchment_mesh_paths(
        raw_simulation_toml=raw_simulation_toml,
        simulation_config_path=simulation_config_path,
        simulation_workspace=simulation_workspace,
    ):
        bundle_dir = resolve_default_catchment_mesh_bundle_dir(candidate_mesh_path)
        if candidate_mesh_path.exists() or bundle_dir.exists():
            return ResolvedRuntimeMeshPaths(
                source=source,
                bundle_dir=bundle_dir,
                mesh_path=candidate_mesh_path,
            )

    return ResolvedRuntimeMeshPaths()


__all__ = [
    "ResolvedRuntimeMeshPaths",
    "RuntimeHydraulicPropertySupport",
    "ModelCalibrationRuntimeSupportUnavailable",
    "bundle_zone_fractions",
    "candidate_mesh_catchment_mesh_paths",
    "candidate_mesh_catchment_summary_paths",
    "discover_hydraulic_support_paths",
    "labels_from_zone_fractions",
    "load_mesh_summary_payload",
    "mesh_catchment_output_dir",
    "parse_numeric_with_optional_suffix",
    "parse_optional_numeric_value",
    "parse_property_support_id",
    "parse_property_values_by_key",
    "resolve_bundle_paths_from_mesh_summary",
    "resolve_flow_property_config",
    "resolve_mesh_input_bundle_dir",
    "resolve_mesh_input_mesh_path",
    "resolve_optional_config_path",
    "resolve_summary_relative_path",
    "select_runtime_preparation_flow_solver",
    "setup_mesh_paths_from_runtime",
    "surface_property_vector",
]
