"""Materialise a self-contained TOML overlay for one calibration candidate.

The overlay inherits the target simulation config via ``base_config`` and
rewrites each configured parameter at its target dotted path (honouring
``mode="replace"`` or ``"scale"``). The resulting file can be loaded by
:class:`hydromodpy.Project` and re-run independently of the calibration
session, which makes it the natural hand-off for twin-benchmark cases
and for exporting the best candidate of a session.

Ported from the legacy ``actualize_candidate`` helper in
``hydromodpy/calibration/benchmark.py``. The legacy helper used ad-hoc
dataclasses; this version operates on the public
:class:`~hydromodpy.calibration.parameters.ParameterSpace` and writes
the overlay with :func:`tomli_w.dumps` so the output is valid TOML.
"""

from __future__ import annotations

import json
import math
import re
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from hydromodpy.calibration.parameters import ParameterSpace


def _sanitize_label(label: str) -> str:
    """Return one filesystem-safe candidate label."""
    text = str(label).strip().lower()
    if not text:
        raise ValueError("candidate_label cannot be empty")
    return re.sub(r"[^a-z0-9_.-]+", "_", text)


def _split_target_path(target: str) -> tuple[str, ...]:
    return tuple(part for part in str(target).strip().split(".") if part)


def _lookup_nested(payload: Mapping[str, Any], dotted: Sequence[str]) -> Any:
    cursor: Any = payload
    for part in dotted:
        if isinstance(cursor, Mapping) and part in cursor:
            cursor = cursor[part]
        else:
            return None
    return cursor


def _assign_nested(payload: dict[str, Any], dotted: Sequence[str], value: Any) -> None:
    cursor = payload
    for part in dotted[:-1]:
        sub = cursor.get(part)
        if not isinstance(sub, dict):
            sub = {}
            cursor[part] = sub
        cursor = sub
    cursor[dotted[-1]] = value


def _dump_toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            raise ValueError(f"Cannot serialise non-finite float to TOML: {value}")
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return '""'
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_dump_toml_value(item) for item in value) + "]"
    if isinstance(value, Mapping):
        inline = ", ".join(f"{key} = {_dump_toml_value(sub)}" for key, sub in value.items())
        return "{ " + inline + " }"
    raise TypeError(f"Unsupported TOML value: {value!r} ({type(value).__name__})")


def _write_toml_payload(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []

    def _emit_block(section: str, block: Mapping[str, Any]) -> None:
        scalars: list[tuple[str, Any]] = []
        tables: list[tuple[str, Mapping[str, Any]]] = []
        for key, value in block.items():
            if isinstance(value, Mapping):
                tables.append((key, value))
            else:
                scalars.append((key, value))
        if section:
            lines.append(f"[{section}]")
        for key, value in scalars:
            lines.append(f"{key} = {_dump_toml_value(value)}")
        if section:
            lines.append("")
        for key, value in tables:
            nested = f"{section}.{key}" if section else key
            _emit_block(nested, value)

    top_scalars = {k: v for k, v in payload.items() if not isinstance(v, Mapping)}
    top_tables = {k: v for k, v in payload.items() if isinstance(v, Mapping)}
    for key, value in top_scalars.items():
        lines.append(f"{key} = {_dump_toml_value(value)}")
    if top_scalars and top_tables:
        lines.append("")
    for key, value in top_tables.items():
        _emit_block(key, value)

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _apply_parameter_mode(
    *, base_value: Any, candidate_value: float, mode: str, param_name: str
) -> float:
    mode_key = str(mode).strip().lower()
    if mode_key == "scale":
        if base_value is None:
            raise ValueError(
                f"Parameter {param_name!r}: scale mode requires a numeric base "
                f"value at the target path in the simulation TOML."
            )
        try:
            base = float(base_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Parameter {param_name!r}: scale mode requires a numeric base "
                f"value; got {base_value!r}."
            ) from exc
        return float(base * float(candidate_value))
    if mode_key == "replace":
        return float(candidate_value)
    raise ValueError(
        f"Parameter {param_name!r}: unsupported mode {mode!r} (expected 'replace' or 'scale')."
    )


def materialize_candidate(
    base_config: Path | str,
    params: Mapping[str, float],
    space: ParameterSpace,
    out_dir: Path | str,
    *,
    candidate_label: str | None = None,
    iteration_index: int | None = None,
    run_id: str | None = None,
    workspace_root: Path | str | None = None,
    extra_sections: Mapping[str, Mapping[str, Any]] | None = None,
) -> Path:
    """Write a standalone override TOML for one calibration candidate.

    Parameters
    ----------
    base_config
        Path to the target simulation TOML. The overlay inherits from it
        via ``base_config = "<abs path>"``.
    params
        Candidate values keyed by parameter name (must cover every
        parameter in ``space`` that has a ``target`` or ``path``).
    space
        Calibration parameter space declaring dotted target paths and
        per-parameter ``mode`` (``"replace"`` / ``"scale"``).
    out_dir
        Directory under which the overlay is written. A ``candidate_label``
        or ``iteration_index`` argument picks the subfolder name.
    candidate_label
        Filesystem-safe label (e.g. ``"truth"``). Either ``candidate_label``
        or ``iteration_index`` must be supplied.
    iteration_index
        Iteration number when no explicit label is given. Produces a
        folder like ``iter_0042``.
    run_id
        Value to write at ``simulation.run_id`` in the overlay.
    workspace_root
        Value to write at ``workspace.root``. Required when the parent
        simulation TOML does not already declare a workspace root.
    extra_sections
        Optional mapping of additional TOML sections (e.g.
        ``{"display": {"enabled": False}}``) applied on top of the overlay.

    Returns
    -------
    Path
        Absolute path to the written overlay TOML.
    """
    base_path = Path(base_config).expanduser().resolve()
    if not base_path.is_file():
        raise FileNotFoundError(f"base_config not found: {base_path}")

    out_dir_path = Path(out_dir).expanduser().resolve()
    if candidate_label is not None:
        iter_id = _sanitize_label(candidate_label)
    elif iteration_index is not None:
        iter_id = f"iter_{int(iteration_index):04d}"
    else:
        raise ValueError("materialize_candidate requires candidate_label or iteration_index")
    candidate_dir = out_dir_path / iter_id
    overlay_path = candidate_dir / "candidate_override.toml"

    with open(base_path, "rb") as f:
        base_raw = tomllib.load(f)

    overlay: dict[str, Any] = {
        "base_config": str(base_path),
    }
    if run_id is not None:
        overlay["simulation"] = {"run_id": str(run_id)}

    workspace_section: dict[str, Any] = dict(base_raw.get("workspace", {}))
    if workspace_root is not None:
        workspace_section["root"] = str(Path(workspace_root).expanduser().resolve())
    elif not workspace_section.get("root"):
        workspace_section["root"] = str(base_path.parent)
    overlay["workspace"] = workspace_section

    for param in space:
        target = param.target if param.target is not None else param.path
        if target is None:
            continue
        if param.name not in params:
            raise ValueError(f"Parameter {param.name!r} missing from candidate params mapping")
        dotted = _split_target_path(target)
        base_value = _lookup_nested(base_raw, dotted)
        resolved = _apply_parameter_mode(
            base_value=base_value,
            candidate_value=float(params[param.name]),
            mode=str(param.mode),
            param_name=param.name,
        )
        _assign_nested(overlay, dotted, resolved)

    if extra_sections:
        for section_name, section_payload in extra_sections.items():
            overlay[str(section_name)] = dict(section_payload)

    _write_toml_payload(overlay_path, overlay)
    return overlay_path


__all__ = ["materialize_candidate"]
