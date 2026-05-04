"""TOML rendering and simulation-config materialization for comparisons."""

from __future__ import annotations

import json
import math
import numbers
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hydromodpy.analysis.comparison.config import (
    ComparisonConfig,
    ComparisonSimulation,
)
from hydromodpy.core.toml_io.loader import (
    load_toml_with_base_config,
    merge_toml_payloads,
)


def _toml_scalar(value: Any) -> str:
    """Render one scalar or scalar list as TOML."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, numbers.Integral) and not isinstance(value, bool):
        return str(int(value))
    if isinstance(value, numbers.Real):
        number = float(value)
        if math.isfinite(number):
            return repr(number)
        raise ValueError("Cannot render non-finite numeric TOML value")
    if isinstance(value, Path):
        return json.dumps(value.as_posix())
    if isinstance(value, str):
        return json.dumps(value.replace("\\", "/"))
    if isinstance(value, list):
        return "[" + ", ".join(_toml_scalar(item) for item in value) + "]"
    if isinstance(value, tuple):
        return "[" + ", ".join(_toml_scalar(item) for item in value) + "]"
    raise TypeError(f"Unsupported TOML scalar type: {type(value).__name__}")


def _is_mapping_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, Mapping) for item in value)


def _render_toml_mapping(
    mapping: Mapping[str, Any],
    *,
    prefix: tuple[str, ...] = (),
) -> list[str]:
    """Render one nested TOML mapping with array-of-table support."""
    lines: list[str] = []
    scalar_items: list[tuple[str, Any]] = []
    nested_items: list[tuple[str, Mapping[str, Any]]] = []
    array_items: list[tuple[str, list[Mapping[str, Any]]]] = []

    for raw_key, value in mapping.items():
        key = str(raw_key)
        if isinstance(value, Mapping):
            nested_items.append((key, value))
        elif _is_mapping_list(value):
            array_items.append((key, value))
        else:
            scalar_items.append((key, value))

    for key, value in scalar_items:
        lines.append(f"{key} = {_toml_scalar(value)}")

    for key, value in nested_items:
        if lines and lines[-1] != "":
            lines.append("")
        section = ".".join((*prefix, key))
        lines.append(f"[{section}]")
        lines.extend(_render_toml_mapping(value, prefix=(*prefix, key)))

    for key, items in array_items:
        section = ".".join((*prefix, key))
        for item in items:
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(f"[[{section}]]")
            lines.extend(_render_toml_mapping(item, prefix=(*prefix, key)))
    return lines


def write_toml_payload(path: Path, payload: Mapping[str, Any]) -> None:
    """Write a small generated TOML payload."""
    lines = _render_toml_mapping(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _deepcopy_jsonlike(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Copy a TOML-like payload without retaining Pydantic internals."""
    return json.loads(json.dumps(payload))


def _overlay_defines_process(overlay: Mapping[str, Any]) -> bool:
    simulation = overlay.get("simulation")
    return isinstance(simulation, Mapping) and "process" in simulation


def _build_solver_process_overlay(
    *,
    base_config_path: Path,
    solver: str,
) -> list[dict[str, Any]] | None:
    """Build a process-list overlay changing the unique flow solver."""
    base_payload = load_toml_with_base_config(base_config_path)
    simulation = base_payload.get("simulation")
    if not isinstance(simulation, Mapping):
        return None
    processes = simulation.get("process")
    if not isinstance(processes, list) or not processes:
        return None

    flow_indices = [
        index
        for index, process in enumerate(processes)
        if isinstance(process, Mapping) and str(process.get("type", "")).strip().lower() == "flow"
    ]
    if len(flow_indices) != 1:
        return None

    overlays = [{} for _ in processes]
    overlays[flow_indices[0]] = {"solvers": [solver]}
    return overlays


def materialize_simulation_config(
    *,
    cfg: ComparisonConfig,
    simulation: ComparisonSimulation,
) -> Path | None:
    """Return the config path used by one comparison simulation, generating it if needed."""
    direct_config = cfg.resolve_simulation_config_path(simulation)
    if direct_config is not None:
        return direct_config

    base_config_path = cfg.base_simulation_config_path
    if base_config_path is None:
        return None

    overlay = _deepcopy_jsonlike(simulation.overlay)
    simulation_overlay = overlay.setdefault("simulation", {})
    if isinstance(simulation_overlay, dict):
        simulation_overlay.setdefault("run_id", simulation.id)
        if simulation.solver is not None and not _overlay_defines_process(overlay):
            process_overlay = _build_solver_process_overlay(
                base_config_path=base_config_path,
                solver=simulation.solver,
            )
            if process_overlay is not None:
                simulation_overlay["process"] = process_overlay

    payload = merge_toml_payloads(
        {"base_config": base_config_path.as_posix()},
        overlay,
    )
    generated_path = cfg.comparison_root / "_generated_configs" / f"{simulation.id}.toml"
    write_toml_payload(generated_path, payload)
    return generated_path


__all__ = (
    "materialize_simulation_config",
    "write_toml_payload",
)
