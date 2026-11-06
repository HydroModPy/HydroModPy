"""TOML loading helpers for flow configuration."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from hydromodpy.core.toml_io.paths import resolve_declared_path
from hydromodpy.physics.flow.boundary_condition_registry import (
    DIRICHLET_BC_CANONICAL_DOMAINS,
    boundary_definition,
)

FlowConfigT = TypeVar("FlowConfigT", bound=BaseModel)

# Keys this loader parses itself before validation. Every other declared key is
# forwarded verbatim, so a new field on the flow model reaches it without any
# edit here.
_PREPARSED_KEYS = frozenset(
    {
        "param_list",
        "param",
        "param_values",
        "ic",
        "bc",
        "sinks_sources",
    }
)


def from_toml_section(
    flow_config_cls: type[FlowConfigT],
    flow_section: Mapping[str, object] | None,
    *,
    base_dir: Path,
    workspace_data_dir: Path | None = None,
) -> FlowConfigT:
    """Build a validated flow config from one `[flow]` TOML section.

    Keys listed in :data:`_PREPARSED_KEYS` are normalized here; every other
    declared key is forwarded as-is to the model, which applies its own
    defaults.
    """
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

    declared_param = list(raw_param_list)
    if len(declared_param) == 0 and len(raw_param) > 0:
        declared_param = list(raw_param.keys())

    parsed_sinks_sources = resolve_forcing_paths(
        raw_sinks_sources,
        base_dir=base_dir,
        workspace_data_dir=workspace_data_dir,
    )
    payload: dict[str, object] = {
        key: value for key, value in flow_section.items() if key not in _PREPARSED_KEYS
    }
    payload.update(
        {
            "param_list": declared_param,
            "param": raw_param,
            "ic": raw_ic,
            "bc": raw_bc,
            "sinks_sources": parsed_sinks_sources,
        }
    )
    return flow_config_cls.model_validate(
        payload,
        context={"base_dir": base_dir, "workspace_data_dir": workspace_data_dir},
    )


_BC_KINDS = frozenset({"dirichlet", "drain"})
_FAMILY_KEYS = frozenset({"dirichlet", "cauchy", "robin"})


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
        else resolve_forcing_paths(
            value,
            base_dir=base_dir,
            workspace_data_dir=workspace_data_dir,
            role="flow_bc",
        )
    )

    parsed: dict[str, object] = {}

    for raw_key, raw_payload in bc_cfg.items():
        key = str(raw_key).strip()
        if key == "":
            raise ValueError("flow.bc cannot contain empty keys")
        if key in _FAMILY_KEYS:
            raise ValueError(
                f"[flow.bc.{key}.<id>] is no longer supported: a boundary is keyed by what it "
                "IS, not by the family it belongs to, which the registry already owns. Write "
                "[flow.bc.<id>]. Run 'hmp doctor --fix-config <file>' to rewrite it."
            )
        if raw_payload is None:
            continue
        if not isinstance(raw_payload, Mapping):
            raise TypeError(f"flow.bc.{key} must be a mapping payload")

        canonical_key = key
        default_kind = _default_kind_for(key)
        if default_kind == "dirichlet":
            # A prescribed head is keyed by the face it sits on, and only the
            # canonical faces exist; anything else there is a typo, not a new
            # boundary.
            canonical_key = _canonicalize_dirichlet_bc_id(
                raw_bc_id=key,
                location_prefix=f"flow.bc.{key}",
            )
        if canonical_key in parsed:
            raise ValueError(f"Duplicate boundary condition entry for '{canonical_key}' in flow.bc")
        parsed[canonical_key] = _prepare_bc_entry_payload(
            bc_id=canonical_key,
            raw_payload=raw_payload,
            default_kind=default_kind,
            location_prefix=f"flow.bc.{key}",
        )

    return parsed


def resolve_forcing_paths(
    section: Mapping[str, object],
    *,
    base_dir: Path,
    workspace_data_dir: Path | None = None,
    role: str | None = None,
) -> dict[str, object]:
    """Resolve the relative CSV paths of each entry of ``flow.bc`` or ``flow.sinks_sources``.

    A path resolves like every other ``InputFile`` field: against the TOML folder,
    then ``<workspace>/data/<role>/`` and ``<workspace>/data/``. ``role`` names that
    folder; without it each entry uses its own key (``wells``, ``lakes``, ``sfr``).
    """
    return {
        key: _resolve_csv_paths_in(
            item,
            base_dir=base_dir,
            role=role or str(key),
            workspace_data_dir=workspace_data_dir,
        )
        for key, item in section.items()
    }


def _resolve_csv_paths_in(
    node: object,
    *,
    base_dir: Path,
    role: str,
    workspace_data_dir: Path | None,
) -> object:
    """Return ``node`` with every nested CSV forcing ``path_file`` resolved."""
    if isinstance(node, Mapping):
        resolved: dict[str, object] = {}
        for key, value in node.items():
            resolved[str(key)] = _resolve_csv_paths_in(
                value,
                base_dir=base_dir,
                role=role,
                workspace_data_dir=workspace_data_dir,
            )
        if resolved.get("kind", "csv") == "csv" and isinstance(resolved.get("path_file"), str):
            return _resolve_forcing_path(
                resolved,
                base_dir=base_dir,
                role=role,
                workspace_data_dir=workspace_data_dir,
            )
        return resolved
    if isinstance(node, (list, tuple)):
        return [
            _resolve_csv_paths_in(
                item, base_dir=base_dir, role=role, workspace_data_dir=workspace_data_dir
            )
            for item in node
        ]
    return node


def _mapping_section(flow_section: Mapping[str, object], name: str) -> Mapping[str, object]:
    value = flow_section.get(name, {})
    if value is None:
        value = {}
    if not isinstance(value, Mapping):
        raise ValueError(f"TOML section 'flow.{name}' must be a mapping when provided")
    return value


def _default_kind_for(bc_id: str) -> str:
    """Return the kind the registry declares for a boundary, or dirichlet."""
    definition = boundary_definition(bc_id)
    if definition is None:
        return "dirichlet"
    declared = str(definition.default_type).strip().lower()
    return declared if declared in _BC_KINDS else "dirichlet"


def _prepare_bc_entry_payload(
    *,
    bc_id: str,
    raw_payload: Mapping[str, object],
    default_kind: str,
    location_prefix: str,
) -> dict[str, object]:
    """Normalize one bc payload, with the registry supplying the kind it omits.

    A boundary is keyed by what it IS. Its kind is an attribute the registry
    already declares, so writing it is never needed. Crossing families is refused:
    a head-dependent exchange is not a prescribed head, and a run that swapped
    them would solve another problem entirely.
    """
    payload = dict(raw_payload)
    raw_kind = str(payload.get("kind", default_kind)).strip().lower() or default_kind
    if raw_kind not in _BC_KINDS:
        raise ValueError(f"{location_prefix}.kind must be one of: {', '.join(sorted(_BC_KINDS))}")
    if (raw_kind == "dirichlet") != (default_kind == "dirichlet"):
        raise ValueError(
            f"{location_prefix}.kind is {raw_kind!r} but {bc_id!r} is a {default_kind!r} "
            "boundary in the registry. A prescribed head and a head-dependent exchange are "
            "not interchangeable."
        )
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
    "resolve_forcing_paths",
]
