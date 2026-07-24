"""TOML loading helpers for flow configuration."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from hydromodpy.core.toml_io.paths import resolve_declared_path
from hydromodpy.physics.flow.boundary_conditions import DIRICHLET_BC_CANONICAL_DOMAINS

FlowConfigT = TypeVar("FlowConfigT", bound=BaseModel)


def from_toml_section(
    flow_config_cls: type[FlowConfigT],
    flow_section: Mapping[str, object] | None,
    *,
    base_dir: Path,
    workspace_data_dir: Path | None = None,
) -> FlowConfigT:
    """Build a validated flow config from one `[flow]` TOML section."""
    if flow_section is None:
        return flow_config_cls()
    if not isinstance(flow_section, Mapping):
        raise ValueError("TOML section 'flow' must be a mapping when provided")
    known_keys = set(flow_config_cls.model_fields) | {"param_values"}
    unknown_keys = sorted(set(flow_section) - known_keys)
    if unknown_keys:
        raise ValueError(f"Unknown TOML key(s) in [flow]: {', '.join(unknown_keys)}")

    raw_param_list = flow_section.get("param_list", [])
    if raw_param_list is None:
        raw_param_list = []
    if not isinstance(raw_param_list, (list, tuple)):
        raise ValueError("TOML section 'flow.param_list' must be a list of ids when provided")

    raw_param = flow_section.get("param", {})
    if raw_param is None:
        raw_param = {}
    if not isinstance(raw_param, Mapping):
        raise ValueError("TOML section 'flow.param' must be a mapping when provided")
    if flow_section.get("param_values") is not None:
        raise ValueError("TOML section 'flow.param_values' is no longer supported.")

    raw_bc = _mapping_section(flow_section, "bc")
    raw_ic = _mapping_section(flow_section, "ic")
    raw_sinks_sources = _mapping_section(flow_section, "sinks_sources")
    raw_active_sinks_sources = _list_section(flow_section, "active_sinks_sources")
    raw_active_bc = _list_section(flow_section, "active_bc")

    declared_param = list(raw_param_list)
    if len(declared_param) == 0 and len(raw_param) > 0:
        declared_param = list(raw_param.keys())

    parsed_sinks_sources = resolve_well_forcing_paths(
        raw_sinks_sources,
        base_dir=base_dir,
        workspace_data_dir=workspace_data_dir,
    )
    return flow_config_cls.model_validate(
        {
            "flow_regime": flow_section.get("flow_regime", "transient"),
            "first_period_steady": flow_section.get("first_period_steady", True),
            "runtime_backend": flow_section.get("runtime_backend", "local"),
            "surface_interaction_model": flow_section.get("surface_interaction_model", "auto"),
            "runtime_max_iterations": flow_section.get("runtime_max_iterations"),
            "runtime_tol_residual_inf": flow_section.get("runtime_tol_residual_inf"),
            "runtime_tol_state_update_inf": flow_section.get("runtime_tol_state_update_inf"),
            "vi_substeps_per_period": flow_section.get("vi_substeps_per_period", 1),
            "vi_substep_on_failure": flow_section.get("vi_substep_on_failure", False),
            "vi_max_adaptive_substeps": flow_section.get("vi_max_adaptive_substeps"),
            "ts_vi_steps_per_period": flow_section.get("ts_vi_steps_per_period", 4),
            "ts_vi_adapt": flow_section.get("ts_vi_adapt", False),
            "ts_vi_dt_min_fraction": flow_section.get("ts_vi_dt_min_fraction", 1.0 / 64.0),
            "ts_vi_dt_max_fraction": flow_section.get("ts_vi_dt_max_fraction", 1.0 / 4.0),
            "ts_vi_type": flow_section.get("ts_vi_type", "beuler"),
            "ts_vi_snes_type": flow_section.get("ts_vi_snes_type", "vinewtonrsls"),
            "param_list": declared_param,
            "param": raw_param,
            "ic": raw_ic,
            "bc": raw_bc,
            "sinks_sources": parsed_sinks_sources,
            "active_sinks_sources": list(raw_active_sinks_sources),
            "active_bc": list(raw_active_bc),
        },
        context={"base_dir": base_dir, "workspace_data_dir": workspace_data_dir},
    )


def normalize_bc_payloads(
    value: Mapping[str, object] | None,
    *,
    base_dir: Path | None = None,
    workspace_data_dir: Path | None = None,
) -> dict[str, object]:
    """Flatten `[flow.bc]` TOML sections into discriminated BC payloads."""
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("flow.bc must be a mapping payload")
    bc_cfg = (
        value
        if base_dir is None
        else resolve_bc_forcing_paths(
            value,
            base_dir=base_dir,
            workspace_data_dir=workspace_data_dir,
        )
    )

    parsed: dict[str, object] = {}

    dirichlet_payload = bc_cfg.get("dirichlet")
    if dirichlet_payload is not None:
        if not isinstance(dirichlet_payload, Mapping):
            raise ValueError("flow.bc.dirichlet must be a mapping when provided")
        for raw_key, item in dirichlet_payload.items():
            key = str(raw_key).strip()
            if key == "":
                raise ValueError("flow.bc.dirichlet cannot contain empty keys")
            if item is None:
                continue
            if not isinstance(item, Mapping):
                raise ValueError(f"flow.bc.dirichlet.{key} must be a mapping")
            canonical_key = _canonicalize_dirichlet_bc_id(
                raw_bc_id=key,
                location_prefix=f"flow.bc.dirichlet.{key}",
            )
            if canonical_key in parsed:
                raise ValueError(
                    f"Duplicate Dirichlet entry for '{canonical_key}' in flow.bc.dirichlet"
                )
            parsed[canonical_key] = _prepare_bc_entry_payload(
                bc_id=canonical_key,
                raw_payload=item,
                default_kind="dirichlet",
                location_prefix=f"flow.bc.dirichlet.{key}",
                force_dirichlet=True,
            )

    cauchy_payload = bc_cfg.get("cauchy")
    if cauchy_payload is not None:
        if not isinstance(cauchy_payload, Mapping):
            raise ValueError("flow.bc.cauchy must be a mapping when provided")
        drainage_item = cauchy_payload.get("drainage")
        if drainage_item is not None:
            if not isinstance(drainage_item, Mapping):
                raise ValueError("flow.bc.cauchy.drainage must be a mapping")
            parsed["drainage"] = _prepare_bc_entry_payload(
                bc_id="drainage",
                raw_payload=drainage_item,
                default_kind="cauchy",
                location_prefix="flow.bc.cauchy.drainage",
            )

    robin_payload = bc_cfg.get("robin")
    if robin_payload is not None and "drainage" not in parsed:
        if not isinstance(robin_payload, Mapping):
            raise ValueError("flow.bc.robin must be a mapping when provided")
        drainage_item = robin_payload.get("drainage")
        if drainage_item is not None:
            if not isinstance(drainage_item, Mapping):
                raise ValueError("flow.bc.robin.drainage must be a mapping")
            parsed["drainage"] = _prepare_bc_entry_payload(
                bc_id="drainage",
                raw_payload=drainage_item,
                default_kind="robin",
                location_prefix="flow.bc.robin.drainage",
            )

    for raw_key, raw_payload in bc_cfg.items():
        key = str(raw_key).strip()
        if key == "":
            raise ValueError("flow.bc cannot contain empty keys")
        if key in {"dirichlet", "cauchy", "robin"}:
            continue
        if key == "drainage":
            if (
                isinstance(raw_payload, Mapping)
                and str(raw_payload.get("id", "")).strip() == "drainage"
                and str(raw_payload.get("kind", "")).strip().lower() in {"cauchy", "robin"}
            ):
                parsed[key] = _prepare_bc_entry_payload(
                    bc_id=key,
                    raw_payload=raw_payload,
                    default_kind=str(raw_payload.get("kind")).strip().lower(),
                    location_prefix=f"flow.bc.{key}",
                )
                continue
            raise ValueError(
                "flow.bc.drainage is no longer supported. "
                "Use flow.bc.cauchy.drainage or flow.bc.robin.drainage."
            )
        if not isinstance(raw_payload, Mapping):
            raise TypeError(f"flow.bc.{key} must be a mapping payload")

        if key in DIRICHLET_BC_CANONICAL_DOMAINS:
            if key in parsed:
                raise ValueError(f"Duplicate boundary condition entry for '{key}' in flow.bc")
            parsed[key] = _prepare_bc_entry_payload(
                bc_id=key,
                raw_payload=raw_payload,
                default_kind="dirichlet",
                location_prefix=f"flow.bc.{key}",
                force_dirichlet=True,
            )
        else:
            parsed[key] = _prepare_bc_entry_payload(
                bc_id=key,
                raw_payload=raw_payload,
                default_kind="dirichlet",
                location_prefix=f"flow.bc.{key}",
            )

    return parsed


def resolve_bc_forcing_paths(
    raw_bc: Mapping[str, object],
    *,
    base_dir: Path,
    workspace_data_dir: Path | None = None,
) -> dict[str, object]:
    """Resolve relative CSV paths declared under flow.bc.*.forcing."""
    payload = dict(raw_bc)

    def resolve_forcing_mapping(item: object) -> object:
        if not isinstance(item, Mapping):
            return item
        item_payload = dict(item)
        forcing = item_payload.get("forcing")
        if isinstance(forcing, Mapping):
            forcing_payload = _resolve_forcing_path(
                forcing,
                base_dir=base_dir,
                role="flow_bc",
                workspace_data_dir=workspace_data_dir,
            )
            item_payload["forcing"] = forcing_payload
        return item_payload

    for section_key in ("dirichlet", "cauchy", "robin"):
        section = payload.get(section_key)
        if not isinstance(section, Mapping):
            continue
        resolved_section: dict[str, object] = {}
        for bc_id, raw_item in section.items():
            resolved_section[str(bc_id)] = resolve_forcing_mapping(raw_item)
        payload[section_key] = resolved_section

    for key, raw_item in list(payload.items()):
        if key in {"dirichlet", "cauchy", "robin"}:
            continue
        payload[key] = resolve_forcing_mapping(raw_item)

    return payload


def resolve_well_forcing_paths(
    raw_sinks_sources: Mapping[str, object],
    *,
    base_dir: Path,
    workspace_data_dir: Path | None = None,
) -> dict[str, object]:
    """Resolve relative CSV paths declared under flow.sinks_sources.wells.*.forcing."""
    payload = dict(raw_sinks_sources)
    wells = payload.get("wells")
    if not isinstance(wells, Mapping):
        return payload

    resolved_wells: dict[str, object] = {}
    for well_id, raw_well in wells.items():
        if not isinstance(raw_well, Mapping):
            resolved_wells[str(well_id)] = raw_well
            continue
        well_payload = dict(raw_well)
        forcing = well_payload.get("forcing")
        if isinstance(forcing, Mapping):
            well_payload["forcing"] = _resolve_forcing_path(
                forcing,
                base_dir=base_dir,
                role="wells",
                workspace_data_dir=workspace_data_dir,
            )
        resolved_wells[str(well_id)] = well_payload
    payload["wells"] = resolved_wells
    return payload


def _mapping_section(flow_section: Mapping[str, object], name: str) -> Mapping[str, object]:
    value = flow_section.get(name, {})
    if value is None:
        value = {}
    if not isinstance(value, Mapping):
        raise ValueError(f"TOML section 'flow.{name}' must be a mapping when provided")
    return value


def _list_section(
    flow_section: Mapping[str, object], name: str
) -> list[object] | tuple[object, ...]:
    value = flow_section.get(name, [])
    if value is None:
        value = []
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"TOML section 'flow.{name}' must be a list when provided")
    return value


def _prepare_bc_entry_payload(
    *,
    bc_id: str,
    raw_payload: Mapping[str, object],
    default_kind: str,
    location_prefix: str,
    force_dirichlet: bool = False,
) -> dict[str, object]:
    payload = dict(raw_payload)
    raw_kind = str(payload.get("kind", default_kind)).strip().lower() or default_kind
    if force_dirichlet and raw_kind != "dirichlet":
        raise ValueError(f"{location_prefix}.kind must be 'dirichlet'")
    if raw_kind not in {"dirichlet", "cauchy", "robin"}:
        raise ValueError(f"{location_prefix}.kind must be one of: dirichlet, cauchy, robin")
    payload["id"] = bc_id
    payload["kind"] = raw_kind
    payload["_location_prefix"] = location_prefix
    return payload


def _canonicalize_dirichlet_bc_id(
    *,
    raw_bc_id: str,
    location_prefix: str,
) -> str:
    bc_id = str(raw_bc_id).strip()
    if bc_id == "":
        raise ValueError(f"{location_prefix} cannot be empty")
    if bc_id in DIRICHLET_BC_CANONICAL_DOMAINS:
        return bc_id
    supported_text = ", ".join(sorted(DIRICHLET_BC_CANONICAL_DOMAINS))
    raise ValueError(
        f"{location_prefix} contains unsupported Dirichlet key '{bc_id}'. "
        f"Supported keys: {supported_text}"
    )


def _resolve_forcing_path(
    forcing: Mapping[str, Any],
    *,
    base_dir: Path,
    role: str,
    workspace_data_dir: Path | None,
) -> dict[str, object]:
    """Resolve one ``forcing.path_file`` against the TOML dir then the workspace data dir.

    A bare filename falls back to ``<workspace>/data/<role>/`` and then
    ``<workspace>/data/``, like every other ``InputFile`` config field.
    """
    forcing_payload = dict(forcing)
    path_value = forcing_payload.get("path_file")
    if isinstance(path_value, str) and path_value.strip() != "":
        fallback_dirs: list[Path] | None = None
        if workspace_data_dir is not None:
            fallback_dirs = [workspace_data_dir / role, workspace_data_dir]
        forcing_payload["path_file"] = resolve_declared_path(
            path_value,
            base_dir=base_dir,
            fallback_dirs=fallback_dirs,
        )
    return forcing_payload


__all__ = [
    "from_toml_section",
    "normalize_bc_payloads",
    "resolve_bc_forcing_paths",
    "resolve_well_forcing_paths",
]
